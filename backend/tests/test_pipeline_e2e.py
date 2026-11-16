"""End-to-end pipeline tests — converted from /tmp/test_auth.py (job
part), /tmp/test_editor_framing.py (regression part) and
/tmp/test_phase2_final.py (fresh-run part).

Fast tests: upload validation, process validation (missing project,
metadata-only YouTube project), job ownership on a missing job.

Slow test (``@pytest.mark.slow``): the full pipeline on the
`processed_project` fixture — upload -> process -> real 1080x1920
H.264 MP4 clips, ffprobe checks, download byte-identical to disk,
transcript with word timestamps, highlights with the heuristic scorer
label. The fixture polls the job to done; the test asserts on the
results. (If the editor chain test ran first in this session, clip 0
is already at version 7 / 15 s — the assertions below are written to
hold for the clip in either state: dimensions, API/disk duration
agreement, and byte-identical download.)
"""
import os

import pytest

from backend.app.database import SessionLocal
from backend.app.models import Project
from backend.tests.conftest import db_clip_path, ffprobe_info


def test_upload_rejects_unsupported_extension(client, alice):
    r = client.post("/api/projects/upload", headers=alice,
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400
    assert "Unsupported file type" in r.text


def test_upload_rejects_non_video_file(client, alice):
    r = client.post("/api/projects/upload", headers=alice,
                    files={"file": ("fake.mp4", b"this is not a video",
                                    "video/mp4")})
    assert r.status_code == 400
    assert "Could not read this video file" in r.text


def test_process_missing_project_404(client, alice):
    r = client.post("/api/projects/999999/process", headers=alice)
    assert r.status_code == 404


def test_process_youtube_link_project_returns_400(client, alice):
    """A metadata-only project has no source file, so processing it
    must fail with a clear 400 (a link alone can never produce clips)."""
    db = SessionLocal()
    try:
        me = client.get("/users/me", headers=alice).json()
        project = Project(user_id=me["id"], title="YT link",
                          source_type="youtube_link",
                          source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                          youtube_video_id="dQw4w9WgXcQ",
                          duration_sec=200.0, status="metadata_only")
        db.add(project)
        db.commit()
        db.refresh(project)
        pid = project.id
    finally:
        db.close()
    r = client.post(f"/api/projects/{pid}/process", headers=alice)
    assert r.status_code == 400
    assert "metadata only" in r.text.lower() or "link" in r.text.lower()


def test_process_returns_existing_job_while_one_is_queued(client, alice,
                                                          test_video):
    """If a process job is already queued/running for the project, POST
    /process returns that job instead of starting a second one. The
    queued job is seeded directly in the test DB so no real pipeline
    runs in this fast test."""
    from backend.app.models import Job

    with open(test_video, "rb") as f:
        r = client.post("/api/projects/upload", headers=alice,
                        files={"file": ("test_video.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    db = SessionLocal()
    try:
        job = Job(project_id=pid, kind="process", status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        queued_id = job.id
    finally:
        db.close()
    r = client.post(f"/api/projects/{pid}/process", headers=alice)
    assert r.status_code == 202, r.text
    assert r.json()["id"] == queued_id
    assert r.json()["status"] == "queued"


@pytest.mark.slow
def test_full_pipeline_end_to_end(client, processed_project, bob):
    """Upload -> process -> clips -> download, with ffprobe checks.
    The fixture already ran the pipeline to done; this test verifies
    every artefact of that run."""
    headers = processed_project["headers"]
    pid = processed_project["project_id"]
    clips = processed_project["clips"]
    assert len(clips) >= 1

    # Ownership: another user gets 404 on the project's resources.
    r = client.get(f"/api/projects/{pid}/clips", headers=bob)
    assert r.status_code == 404
    r = client.get(f"/api/projects/{pid}/highlights", headers=bob)
    assert r.status_code == 404
    r = client.get(f"/api/projects/{pid}/transcript", headers=bob)
    assert r.status_code == 404

    # Project status and clips.
    r = client.get(f"/api/projects/{pid}", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "done"

    for clip in clips:
        path = db_clip_path(clip["id"])
        assert path and os.path.exists(path), f"clip {clip['id']} missing"
        info = ffprobe_info(path)
        stream = info["streams"][0]
        assert stream["codec_name"] == "h264"
        assert stream["width"] == 1080 and stream["height"] == 1920
        # ffprobe duration agrees with the API row (whatever version
        # the clip is at — the editor chain may have trimmed clip 0).
        current = client.get(f"/api/clips/{clip['id']}",
                             headers=headers).json()
        assert abs(float(info["format"]["duration"])
                   - current["duration_sec"]) < 0.2
        # Download is byte-identical to the file on disk.
        r = client.get(f"/api/clips/{clip['id']}/download",
                       headers=headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "video/mp4"
        with open(path, "rb") as f:
            assert r.content == f.read()
        # Another user's download is 404.
        r = client.get(f"/api/clips/{clip['id']}/download", headers=bob)
        assert r.status_code == 404

    # Highlights: heuristic scorer recorded (no LLM key in test env).
    highlights = processed_project["highlights"]
    assert highlights
    assert all(h["scorer"] == "heuristic" for h in highlights)
    assert all(h["reasons"] for h in highlights)
    assert all(0 <= h["score"] <= 100 for h in highlights)

    # Transcript: segments with word-level timestamps.
    transcript = processed_project["transcript"]
    assert transcript["language"] == "en"
    assert len(transcript["full_text"]) > 50
    assert len(transcript["segments"]) >= 1
    assert any(s.get("words") for s in transcript["segments"])
