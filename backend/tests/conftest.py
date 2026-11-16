"""MMSN Clipper — automated pytest suite (Phase 3).

Runs the FastAPI app in-process with fastapi.testclient.TestClient
against a FRESH temp SQLite DB and temp upload/media dirs per pytest
run. The dev database (./mmsn.db) is never touched.

Environment setup happens here, BEFORE the app is imported, because
backend/app/config.py reads os.environ at import time (and load_dotenv
never overrides variables already set).

Markers: ``slow`` — tests that run the real Whisper + FFmpeg pipeline
or a real re-render (minutes). ``pytest -m "not slow"`` runs the fast
suite only: auth, validation, ownership, URL parsing, LLM mock
scoring, editor validation — no full render.

Test video: generated locally with FFmpeg (testsrc + real spoken
English via the flite filter). No YouTube video is ever downloaded.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid

# ── Test environment (must precede any backend.app import) ───────────────
_TMP_ROOT = tempfile.mkdtemp(prefix="mmsn-test-")
_TEST_DB = os.path.join(_TMP_ROOT, "test.db")
_TEST_UPLOADS = os.path.join(_TMP_ROOT, "uploads")
_TEST_MEDIA = os.path.join(_TMP_ROOT, "media")
os.makedirs(_TEST_UPLOADS, exist_ok=True)
os.makedirs(_TEST_MEDIA, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["UPLOAD_DIR"] = _TEST_UPLOADS
os.environ["MEDIA_DIR"] = _TEST_MEDIA
# Test-only JWT secret (never a real secret; the test DB is throwaway).
os.environ["SECRET_KEY"] = (
    "pytest-only-test-secret-key-0123456789abcdef-0123456789abcdef")
os.environ["OPENAI_API_KEY"] = ""
os.environ["YOUTUBE_API_KEY"] = ""
os.environ.pop("SEED_EMAIL", None)
os.environ.pop("SEED_PASSWORD", None)
# The pipeline's httpx calls honour proxy env vars, and this VM's
# NO_PROXY value (which contains "[::1]") breaks httpx's localhost URL
# handling (see TESTING.md, Phase 2 step 3). The suite makes no outbound
# calls except to the local LLM mock, so drop the proxy vars entirely.
for _var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
             "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
    os.environ.pop(_var, None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.database import SessionLocal  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.models import Clip, Highlight, Project, Transcript  # noqa: E402

# ── Spoken test script (~210 words, ~66 s via flite) ─────────────────────
TEST_SCRIPT = (
    "Hello everyone, welcome back to the channel. Today I am going to share "
    "a secret about how to make your first short video go viral in 2026. "
    "Most creators make the same mistake: they start with a boring "
    "introduction and lose the viewer in the first three seconds. Here is "
    "the truth. The first three seconds decide everything. If you hook the "
    "viewer fast, they stay. If you do not, they scroll away forever. So "
    "here are five proven tricks that actually work. First, start with a "
    "question. Ask the viewer something they already care about. Second, "
    "show the result before you explain the process. People love a payoff. "
    "Third, cut the silence. Every pause longer than half a second is a "
    "reason to leave. Fourth, add captions, because eighty percent of "
    "viewers watch without sound. And fifth, end with a loop, so the video "
    "feels like it never stops. Now let me show you exactly how I edit my "
    "own videos step by step, with real examples from my channel, and the "
    "three tools I use every single day. Stay until the end, because the "
    "last tip is the one nobody talks about, and it doubled my watch time "
    "in just two weeks. Let us begin with the hook."
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: runs the real Whisper/FFmpeg pipeline or a "
        "real re-render (minutes); skipped by -m 'not slow'")


# ── Small helpers shared by the test modules ─────────────────────────────

def make_words(text: str, start: float, end: float) -> list[dict]:
    """Split `text` into word dicts with proportional timing across
    [start, end], faster-whisper style (leading space except first)."""
    tokens = text.split()
    span = max(0.0, end - start)
    return [{
        "start": start + span * i / len(tokens),
        "end": start + span * (i + 1) / len(tokens),
        "word": (" " + tok) if i else tok,
    } for i, tok in enumerate(tokens)]


def make_segments(text: str, start: float, end: float,
                  n_segments: int = 3) -> list[dict]:
    """Synthetic transcript segments for `text` across [start, end]."""
    words = make_words(text, start, end)
    per = max(1, len(words) // n_segments)
    segments = []
    for i in range(n_segments):
        chunk = words[i * per:(i + 1) * per] if i < n_segments - 1 \
            else words[i * per:]
        if not chunk:
            continue
        segments.append({
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
            "text": "".join(w["word"] for w in chunk).strip(),
            "words": chunk,
        })
    return segments


def ffprobe_info(path: str) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height,r_frame_rate",
         "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def ffprobe_duration(path: str) -> float:
    return float(ffprobe_info(path)["format"]["duration"])


def extract_frame(video: str, t: float, out: str) -> str:
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t),
                        "-i", video, "-frames:v", "1", out],
                       capture_output=True, text=True)
    assert r.returncode == 0 and os.path.exists(out), r.stderr
    return out


def frame_md5(video: str, t: float, out: str) -> str:
    extract_frame(video, t, out)
    return hashlib.md5(open(out, "rb").read()).hexdigest()


def volumedetect(path: str) -> tuple[float | None, float | None]:
    r = subprocess.run(["ffmpeg", "-i", path, "-vn", "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    mean = maxv = None
    for line in (r.stderr or "").splitlines():
        if "mean_volume" in line:
            mean = float(line.split("mean_volume:")[1].split("dB")[0])
        if "max_volume" in line:
            maxv = float(line.split("max_volume:")[1].split("dB")[0])
    return mean, maxv


def pixdiff(a: str, b: str) -> float:
    import cv2
    import numpy as np
    ia = cv2.imread(a)
    ib = cv2.imread(b)
    return float(np.mean(np.abs(ia.astype(np.float32)
                                - ib.astype(np.float32))))


def poll_job(client: TestClient, job_id: int, headers: dict | None = None,
             timeout: int = 900) -> dict:
    """Poll GET /api/jobs/{id} until done/failed (or timeout)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert r.status_code == 200, f"poll job {job_id}: {r.status_code}"
        job = r.json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(5)
    raise TimeoutError(f"job {job_id} did not finish in {timeout}s")


def db_clip_path(clip_id: int) -> str | None:
    """Disk path of a clip row in the TEST db (test-only shortcut)."""
    db = SessionLocal()
    try:
        clip = db.query(Clip).get(clip_id)
        return clip.path if clip else None
    finally:
        db.close()


def register_and_login(client: TestClient, email: str,
                       password: str = "correct-horse-1",
                       name: str | None = None) -> dict:
    """Register a fresh user and return Authorization headers."""
    payload = {"email": email, "password": password}
    if name:
        payload["name"] = name
    r = client.post("/auth/register", json=payload)
    assert r.status_code == 201, r.text
    r = client.post("/auth/jwt/login",
                    data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    """App under TestClient; the context manager runs startup
    (init_db on the temp DB, seed skipped, stale jobs marked)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def test_video(tmp_path_factory):
    """Locally generated test video: testsrc 1280x720 30fps + real
    spoken English (flite). ~66 s, ~210 words. No YouTube download."""
    out_dir = tmp_path_factory.mktemp("video")
    script_path = out_dir / "script.txt"
    script_path.write_text(TEST_SCRIPT)
    video = str(out_dir / "test_video.mp4")
    r = subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=duration=120:size=1280x720:rate=30",
        "-f", "lavfi", "-i",
        f"flite=textfile={script_path}:voice=slt",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
        "-preset", "veryfast", "-c:a", "aac", "-shortest", video],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert os.path.exists(video)
    return video


@pytest.fixture()
def alice(client):
    """Fresh registered user A with auth headers."""
    return register_and_login(client, unique_email("alice"), name="Alice")


@pytest.fixture()
def bob(client):
    """Fresh registered user B with auth headers."""
    return register_and_login(client, unique_email("bob"), name="Bob")


@pytest.fixture(scope="session")
def processed_project(client, test_video):
    """SLOW (built lazily, only when a test requests it): upload the
    test video as a dedicated user, run the full pipeline, poll to done.
    Returns project/clip/highlight ids, headers, and the transcript."""
    headers = register_and_login(client, unique_email("e2e"))
    with open(test_video, "rb") as f:
        r = client.post("/api/projects/upload", headers=headers,
                        files={"file": ("test_video.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    project = r.json()
    r = client.post(f"/api/projects/{project['id']}/process",
                    headers=headers)
    assert r.status_code == 202, r.text
    job = poll_job(client, r.json()["id"], headers=headers)
    assert job["status"] == "done", f"pipeline failed: {job.get('error')}"
    clips = client.get(f"/api/projects/{project['id']}/clips",
                       headers=headers).json()
    assert clips, "pipeline produced no clips"
    highlights = client.get(
        f"/api/projects/{project['id']}/highlights",
        headers=headers).json()
    transcript = client.get(
        f"/api/projects/{project['id']}/transcript",
        headers=headers).json()
    return {"project_id": project["id"], "duration_sec": project["duration_sec"],
            "clips": clips, "highlights": highlights,
            "transcript": transcript, "headers": headers}


@pytest.fixture()
def seeded_clip(client, test_video):
    """FAST editor fixture: a clip with highlight + transcript rows
    inserted directly into the TEST db — no pipeline run. The clip
    points at the generated test video (a real file on disk) so the
    editor endpoints behave as they would for a rendered clip, except
    no re-render job is started by the fast tests.

    Window: highlight 0.00–28.62 s; transcript covers the same window.
    """
    headers = register_and_login(client, unique_email("seeded"))
    db = SessionLocal()
    try:
        project = Project(user_id=_user_id(client, headers),
                          title="seeded", source_type="upload",
                          source_path=test_video, duration_sec=65.87,
                          status="uploaded")
        db.add(project)
        db.commit()
        db.refresh(project)
        highlight = Highlight(project_id=project.id, start_sec=0.0,
                              end_sec=28.62, score=81, scorer="heuristic",
                              reasons_json=json.dumps(["Seeded highlight"]),
                              title="Seeded clip", description="",
                              hashtags_json=json.dumps(["#shorts"]))
        db.add(highlight)
        db.commit()
        db.refresh(highlight)
        segments = make_segments(TEST_SCRIPT, 0.0, 28.62, n_segments=3)
        transcript = Transcript(
            project_id=project.id, language="en",
            full_text=" ".join(s["text"] for s in segments),
            segments_json=json.dumps(segments))
        db.add(transcript)
        clip = Clip(project_id=project.id, highlight_id=highlight.id,
                    title="Seeded clip", path=test_video, width=1080,
                    height=1920, duration_sec=28.62,
                    file_size_bytes=os.path.getsize(test_video),
                    status="ready")
        db.add(clip)
        db.commit()
        db.refresh(clip)
        return {"project_id": project.id, "clip_id": clip.id,
                "highlight_id": highlight.id, "headers": headers,
                "highlight_duration": 28.62}
    finally:
        db.close()


def _user_id(client: TestClient, headers: dict) -> int:
    r = client.get("/users/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]
