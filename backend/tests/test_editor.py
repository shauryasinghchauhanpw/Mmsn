"""Editor tests — converted from /tmp/test_editor_smoke.py,
/tmp/test_editor_render.py, /tmp/test_editor_framing.py and
/tmp/test_editor_retest.py (Phase 2, step 2).

Fast tests use the `seeded_clip` fixture (DB rows inserted directly,
no pipeline run): clip detail, captions, auth (401/404), validation
(400/422), thumbnail-before-set. No re-render is started.

Slow tests (``@pytest.mark.slow``) run real re-renders against the
`processed_project` fixture: the full trim -> caption -> style ->
framing -> volume -> thumbnail -> regenerate chain on one clip
(version bumps 1 -> 7), plus a synthetic face-track render through
render_clip directly (the escaped-crop path).
"""
import os

import pytest

from backend.pipeline.captions import group_words, words_to_ass
from backend.pipeline.rerender import apply_caption_overrides
from backend.tests.conftest import (
    db_clip_path, ffprobe_duration, ffprobe_info, frame_md5, pixdiff,
    poll_job, volumedetect)

EDITOR_ENDPOINTS = [
    ("GET", "/api/clips/{id}"),
    ("GET", "/api/clips/{id}/captions"),
    ("POST", "/api/clips/{id}/re-render"),
    ("POST", "/api/clips/{id}/regenerate"),
    ("POST", "/api/clips/{id}/thumbnail?t=3"),
    ("GET", "/api/clips/{id}/thumbnail"),
]


# ── Fast: detail + captions (seeded clip) ───────────────────────────────

def test_get_clip_detail(client, seeded_clip):
    cid = seeded_clip["clip_id"]
    r = client.get(f"/api/clips/{cid}", headers=seeded_clip["headers"])
    assert r.status_code == 200, r.text
    clip = r.json()
    assert abs(clip["highlight_start_sec"] - 0.0) < 0.01
    assert abs(clip["highlight_end_sec"] - 28.62) < 0.05
    assert abs(clip["highlight_duration_sec"] - 28.62) < 0.05
    assert clip["version"] == 1
    assert clip["edit_params"] == {}
    assert clip["has_thumbnail"] is False


def test_get_clip_captions(client, seeded_clip):
    cid = seeded_clip["clip_id"]
    r = client.get(f"/api/clips/{cid}/captions",
                   headers=seeded_clip["headers"])
    assert r.status_code == 200, r.text
    caps = r.json()
    assert caps["style"] == "karaoke"
    assert len(caps["groups"]) >= 3
    assert abs(caps["window_start_sec"] - 0.0) < 0.01
    assert abs(caps["window_end_sec"] - 28.62) < 0.05
    assert caps["groups"][0]["text"].startswith("Hello"), \
        caps["groups"][0]["text"]
    assert caps["groups"][0]["index"] == 0


def test_get_missing_clip_returns_404(client, alice):
    assert client.get("/api/clips/999999", headers=alice).status_code == 404


# ── Fast: editor auth — 401 anon, 404 other user ─────────────────────────

@pytest.mark.parametrize("method,template", EDITOR_ENDPOINTS)
def test_editor_endpoints_unauthenticated_401(client, seeded_clip,
                                              method, template):
    url = template.format(id=seeded_clip["clip_id"])
    body = {} if method == "POST" else None
    r = client.request(method, url, json=body)
    assert r.status_code == 401, f"{method} {url} -> {r.status_code}"


@pytest.mark.parametrize("method,template", EDITOR_ENDPOINTS)
def test_editor_endpoints_other_user_404(client, seeded_clip, bob,
                                         method, template):
    url = template.format(id=seeded_clip["clip_id"])
    body = {} if method == "POST" else None
    r = client.request(method, url, headers=bob, json=body)
    assert r.status_code == 404, f"bob {method} {url} -> {r.status_code}"


# ── Fast: editor validation (seeded clip, no render starts) ─────────────

def test_re_render_bad_style_returns_400(client, seeded_clip):
    cid = seeded_clip["clip_id"]
    r = client.post(f"/api/clips/{cid}/re-render",
                    headers=seeded_clip["headers"], json={"style": "nope"})
    assert r.status_code == 400
    assert "Unknown subtitle style 'nope'" in r.text


def test_re_render_trim_validation(client, seeded_clip):
    cid = seeded_clip["clip_id"]
    h = seeded_clip["headers"]
    # trim_end beyond the highlight window
    r = client.post(f"/api/clips/{cid}/re-render", headers=h,
                    json={"trim_start": 0, "trim_end": 99})
    assert r.status_code == 400
    # trim shorter than the 2 s minimum
    r = client.post(f"/api/clips/{cid}/re-render", headers=h,
                    json={"trim_start": 10, "trim_end": 11})
    assert r.status_code == 400
    # start == end
    r = client.post(f"/api/clips/{cid}/re-render", headers=h,
                    json={"trim_start": 5, "trim_end": 5})
    assert r.status_code == 400
    # start after end
    r = client.post(f"/api/clips/{cid}/re-render", headers=h,
                    json={"trim_start": 20, "trim_end": 10})
    assert r.status_code == 400
    # negative start -> 422 (pydantic ge=0 fires before the endpoint's
    # own 400 trim validation)
    r = client.post(f"/api/clips/{cid}/re-render", headers=h,
                    json={"trim_start": -1, "trim_end": 10})
    assert r.status_code == 422


def test_re_render_range_validation_422(client, seeded_clip):
    cid = seeded_clip["clip_id"]
    h = seeded_clip["headers"]
    r = client.post(f"/api/clips/{cid}/re-render", headers=h,
                    json={"volume": 3.0})
    assert r.status_code == 422
    r = client.post(f"/api/clips/{cid}/re-render", headers=h,
                    json={"framing_offset": 2})
    assert r.status_code == 422
    r = client.post(f"/api/clips/{cid}/re-render", headers=h,
                    json={"volume": 0.1})
    assert r.status_code == 422


def test_re_render_missing_clip_404(client, alice):
    r = client.post("/api/clips/999999/re-render", headers=alice, json={})
    assert r.status_code == 404


def test_thumbnail_before_set(client, seeded_clip):
    cid = seeded_clip["clip_id"]
    h = seeded_clip["headers"]
    r = client.get(f"/api/clips/{cid}/thumbnail", headers=h)
    assert r.status_code == 404
    # t beyond the clip duration
    r = client.post(f"/api/clips/{cid}/thumbnail?t=999", headers=h)
    assert r.status_code == 400


# ── Slow: full editor chain on a real rendered clip ──────────────────────

@pytest.mark.slow
def test_editor_full_chain(client, processed_project, tmp_path):
    """Trim -> caption edit -> style -> framing -> volume -> thumbnail
    -> regenerate on the first clip of the processed project, one
    re-render per step (versions 1 -> 7). Each step is a real
    background job polled to done, verified with ffprobe / frame
    hashes / volumedetect — the same checks as the Phase 2 scripts."""
    headers = processed_project["headers"]
    clip = processed_project["clips"][0]
    cid = clip["id"]
    out_dir = str(tmp_path)

    def get_clip():
        r = client.get(f"/api/clips/{cid}", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    def rerender(body):
        r = client.post(f"/api/clips/{cid}/re-render", headers=headers,
                        json=body)
        assert r.status_code == 202, r.text
        job = poll_job(client, r.json()["id"], headers=headers)
        assert job["status"] == "done", f"re-render failed: {job.get('error')}"
        return job

    # 1. TRIM 0–15 s
    v1_path = db_clip_path(cid)
    assert v1_path and os.path.exists(v1_path)
    rerender({"trim_start": 0, "trim_end": 15})
    clip = get_clip()
    assert clip["version"] == 2
    path = db_clip_path(cid)
    assert path.endswith(f"clip_{cid}_v2.mp4"), path
    assert abs(ffprobe_duration(path) - 15.0) < 0.6
    assert abs(clip["duration_sec"] - 15.0) < 0.6
    assert not os.path.exists(v1_path)  # old version deleted

    # 2. CAPTION EDIT group 0 -> "HELLO EDITED WORDS"
    caps = client.get(f"/api/clips/{cid}/captions",
                      headers=headers).json()
    assert caps["groups"], "no caption groups in the trimmed window"
    orig_g0 = caps["groups"][0]["text"]
    rerender({"caption_overrides": [{"group_index": 0,
                                     "text": "HELLO EDITED WORDS"}]})
    clip = get_clip()
    assert clip["version"] == 3
    assert abs(ffprobe_duration(db_clip_path(cid)) - 15.0) < 0.6
    # API-level: the override is stored and listed; the raw groups are
    # the transcript groups (the endpoint returns overrides separately).
    caps = client.get(f"/api/clips/{cid}/captions",
                      headers=headers).json()
    assert caps["groups"][0]["text"] == orig_g0
    assert caps["overrides"] == [{"group_index": 0,
                                  "text": "HELLO EDITED WORDS"}]
    # ASS-level check, rebuilt exactly as the renderer builds it.
    transcript = processed_project["transcript"]
    words = [w for s in transcript["segments"] for w in s.get("words", [])]
    hl = next(h for h in processed_project["highlights"]
              if h["id"] == clip["highlight_id"])
    window_words = [w for w in words
                    if w["end"] > hl["start_sec"]
                    and w["start"] < hl["start_sec"] + 15.0]
    orig_groups = ["".join(w["word"] for w in g)
                   for g in group_words(window_words)]
    assert orig_groups[0] == orig_g0
    edited = apply_caption_overrides(
        words, hl["start_sec"], hl["start_sec"] + 15.0,
        [{"group_index": 0, "text": "HELLO EDITED WORDS"}])
    groups = ["".join(w["word"] for w in g) for g in group_words(edited)]
    assert groups[0] == "HELLO EDITED WORDS"
    # Boundary fix: the next group keeps exactly its own words.
    assert groups[1] == orig_groups[1], (groups[1], orig_groups[1])
    ass = words_to_ass(edited, start_offset=hl["start_sec"],
                       style="karaoke")
    for w in ("HELLO", "EDITED", "WORDS"):
        assert w in ass

    # 3. STYLE -> bold (frame at t=5 must change)
    frame_before = frame_md5(db_clip_path(cid), 5.0,
                             os.path.join(out_dir, "style_before.jpg"))
    rerender({"style": "bold"})
    clip = get_clip()
    assert clip["version"] == 4
    assert clip["edit_params"]["style"] == "bold"
    frame_after = frame_md5(db_clip_path(cid), 5.0,
                            os.path.join(out_dir, "style_after.jpg"))
    assert frame_before != frame_after

    # 4. FRAMING +0.9 (crop must move — the escaped-comma fix)
    frame_before = frame_md5(db_clip_path(cid), 5.0,
                             os.path.join(out_dir, "frame_before.jpg"))
    rerender({"framing_offset": 0.9})
    clip = get_clip()
    assert clip["version"] == 5
    frame_after = frame_md5(db_clip_path(cid), 5.0,
                            os.path.join(out_dir, "frame_after.jpg"))
    assert frame_before != frame_after

    # 5. VOLUME 0.5 (mean level must drop ~6 dB)
    mean_before, _ = volumedetect(db_clip_path(cid))
    rerender({"volume": 0.5})
    clip = get_clip()
    assert clip["version"] == 6
    mean_after, _ = volumedetect(db_clip_path(cid))
    assert mean_before is not None and mean_after is not None
    drop = mean_before - mean_after
    assert 5.0 < drop < 7.0, f"volume drop {drop:.2f} dB"

    # 6. THUMBNAIL from t=3
    r = client.post(f"/api/clips/{cid}/thumbnail?t=3", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["thumbnail_url"] == f"/api/clips/{cid}/thumbnail"
    r = client.get(f"/api/clips/{cid}/thumbnail", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 1000
    assert get_clip()["has_thumbnail"] is True

    # 7. REGENERATE (stored params kept, new version)
    r = client.post(f"/api/clips/{cid}/regenerate", headers=headers)
    assert r.status_code == 202, r.text
    job = poll_job(client, r.json()["id"], headers=headers)
    assert job["status"] == "done", job.get("error")
    clip = get_clip()
    assert clip["version"] == 7
    assert clip["edit_params"]["style"] == "bold"
    assert clip["edit_params"]["volume"] == 0.5
    assert clip["edit_params"]["trim_end"] == 15
    assert clip["edit_params"]["framing_offset"] == 0.9
    assert abs(ffprobe_duration(db_clip_path(cid)) - 15.0) < 0.6

    # Download still works after all versions.
    r = client.get(f"/api/clips/{cid}/download", headers=headers)
    assert r.status_code == 200 and len(r.content) > 100_000


@pytest.mark.slow
def test_synthetic_face_track_render(test_video, tmp_path):
    """Face-track + nudge path through render_clip directly (real
    FFmpeg). A synthetic track (median x=0.25) with offset 0 vs +0.5
    must move the crop, and the face-tracked render must differ from
    a plain centre crop — the Phase 2 re-test for the escaped-comma
    crop-filter fix."""
    from backend.pipeline.render import render_clip

    out_dir = str(tmp_path)
    track = [(float(t), 0.25) for t in range(0, 29)]
    out0 = os.path.join(out_dir, "synth_face0.mp4")
    out1 = os.path.join(out_dir, "synth_face_nudge.mp4")
    render_clip(test_video, 0.0, 10.0, [], out0, face_track=track,
                scenes=None)
    render_clip(test_video, 0.0, 10.0, [], out1, face_track=track,
                scenes=None, framing_offset=0.5)
    assert os.path.exists(out0) and os.path.exists(out1)
    assert abs(ffprobe_duration(out0) - 10.0) < 0.6
    f0 = frame_md5(out0, 5.0, os.path.join(out_dir, "f0.jpg"))
    f1 = frame_md5(out1, 5.0, os.path.join(out_dir, "f1.jpg"))
    assert f0 != f1
    d = pixdiff(os.path.join(out_dir, "f0.jpg"),
                os.path.join(out_dir, "f1.jpg"))
    assert d > 5.0, f"mean abs pixel diff {d:.2f}"
    # Face-track (median 0.25) differs from a plain centre crop.
    out_centre = os.path.join(out_dir, "centre.mp4")
    render_clip(test_video, 0.0, 10.0, [], out_centre, scenes=None)
    fc = frame_md5(out_centre, 5.0, os.path.join(out_dir, "fc.jpg"))
    assert fc != f0
    d2 = pixdiff(os.path.join(out_dir, "f0.jpg"),
                 os.path.join(out_dir, "fc.jpg"))
    assert d2 > 5.0, f"mean abs pixel diff {d2:.2f}"


@pytest.mark.slow
def test_framing_rerender_moves_centre_crop(client, processed_project,
                                            tmp_path):
    """API-level framing check on a clip whose source has no face
    (the test video is testsrc): offset +0.9 must still move the
    centre+nudge crop — this is the re-render that failed before the
    comma-escaping fix with 'No such filter: 0)'."""
    headers = processed_project["headers"]
    clip = processed_project["clips"][-1]  # a clip the chain test did not touch
    cid = clip["id"]
    out_dir = str(tmp_path)
    before = frame_md5(db_clip_path(cid), 5.0,
                       os.path.join(out_dir, "before.jpg"))
    r = client.post(f"/api/clips/{cid}/re-render", headers=headers,
                    json={"framing_offset": 0.9})
    assert r.status_code == 202, r.text
    job = poll_job(client, r.json()["id"], headers=headers)
    assert job["status"] == "done", f"framing job failed: {job.get('error')}"
    after = frame_md5(db_clip_path(cid), 5.0,
                      os.path.join(out_dir, "after.jpg"))
    assert before != after
    d = pixdiff(os.path.join(out_dir, "before.jpg"),
                os.path.join(out_dir, "after.jpg"))
    assert d > 5.0, f"mean abs pixel diff {d:.2f}"
