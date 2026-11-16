"""Render preset wiring — the x264 preset is a memory knob as well as
a speed/quality knob (see backend/pipeline/render.py).

Checks:
  1. render_clip(preset="ultrafast") renders a real 1080x1920 clip
     (fast: a 3 s generated video, 2 s clip).
  2. The default preset is "veryfast" (render_clip's own default).
  3. Settings validates RENDER_PRESET: a known preset is kept, an
     unknown value falls back to "veryfast" instead of reaching FFmpeg.
"""
import os
import subprocess

from backend.app.config import Settings
from backend.pipeline.render import render_clip
from backend.tests.conftest import ffprobe_info


def _make_video(path: str, seconds: int = 3) -> str:
    r = subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i",
        f"testsrc=duration={seconds}:size=1280x720:rate=30",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
        "-preset", "veryfast", "-c:a", "aac", "-shortest", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def test_render_clip_ultrafast_produces_1080x1920(tmp_path):
    video = _make_video(str(tmp_path / "v.mp4"))
    out = str(tmp_path / "clip.mp4")
    render_clip(video, 0.0, 2.0, [], out, preset="ultrafast")
    assert os.path.exists(out)
    info = ffprobe_info(out)
    stream = info["streams"][0]
    assert stream["width"] == 1080
    assert stream["height"] == 1920
    assert stream["codec_name"] == "h264"


def test_render_preset_setting_keeps_known_value(monkeypatch):
    monkeypatch.setenv("RENDER_PRESET", "ultrafast")
    assert Settings().render_preset == "ultrafast"
    monkeypatch.setenv("RENDER_PRESET", "veryslow")
    assert Settings().render_preset == "veryslow"


def test_render_preset_setting_falls_back_on_unknown(monkeypatch):
    monkeypatch.setenv("RENDER_PRESET", "turbo-9000")
    assert Settings().render_preset == "veryfast"
    monkeypatch.delenv("RENDER_PRESET", raising=False)
    assert Settings().render_preset == "veryfast"


def test_face_tracking_setting(monkeypatch):
    # Default on.
    monkeypatch.delenv("FACE_TRACKING", raising=False)
    assert Settings().face_tracking is True
    for raw in ("0", "false", "no", "off"):
        monkeypatch.setenv("FACE_TRACKING", raw)
        assert Settings().face_tracking is False, raw
    for raw in ("1", "true", "yes", "on"):
        monkeypatch.setenv("FACE_TRACKING", raw)
        assert Settings().face_tracking is True, raw
