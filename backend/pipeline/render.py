"""Rendering — FFmpeg cut + face-tracked 9:16 reframe + caption burn-in +
H.264/AAC MP4 export at 1080x1920, 30fps.

The clip window is split at scene cuts inside it; each segment is rendered
with a static crop centred on the segment's median face position (from the
smoothed YuNet track), then segments are concatenated. With no faces the
whole clip renders in one centre-crop pass — the common case for slides /
screen recordings. Captions are burned per segment from the same word
timestamps, so there is no extra re-encode pass.

Note on the FFmpeg build: the Ubuntu/dev build used here includes libx264
(GPL). For a commercial product use an LGPL build (see
THIRD_PARTY_LICENSES.md) — the render command itself does not depend on
which H.264 encoder the build ships.
"""
from __future__ import annotations

import os
import statistics

from .audio import FFmpegError, run
from .captions import write_ass
from .reframe import vertical_filter


def _escape_filter_path(path: str) -> str:
    # libass filter argument: escape : and ' inside the path.
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _render_segment(source_path: str, start: float, end: float,
                    ass_path: str | None, out_path: str,
                    center_x: float | None, volume: float = 1.0,
                    preset: str = "veryfast") -> None:
    vf = vertical_filter(center_x)
    if ass_path and os.path.exists(ass_path):
        vf += f",ass='{_escape_filter_path(ass_path)}'"
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", str(start), "-to", str(end), "-i", source_path,
           "-vf", vf]
    if volume != 1.0:
        cmd += ["-af", f"volume={volume}"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", "23",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", out_path]
    result = run(cmd)
    if result.returncode != 0 or not os.path.exists(out_path):
        raise FFmpegError(
            f"Clip render failed: {result.stderr.strip()[:500]}")


def _concat_segments(segment_paths: list[str], out_path: str,
                     preset: str = "veryfast") -> None:
    list_path = out_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in segment_paths:
            f.write(f"file '{p}'\n")
    result = run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                  "-i", list_path, "-c", "copy", out_path])
    if result.returncode != 0 or not os.path.exists(out_path):
        # Fallback: re-encode concat (handles any timestamp mismatch).
        result = run(["ffmpeg", "-y", "-v", "error", "-f", "concat",
                      "-safe", "0", "-i", list_path,
                      "-c:v", "libx264", "-preset", preset, "-crf", "23",
                      "-c:a", "aac", out_path])
    if result.returncode != 0 or not os.path.exists(out_path):
        raise FFmpegError(
            f"Clip concat failed: {result.stderr.strip()[:500]}")


def render_clip(source_path: str, start: float, end: float,
                words: list, out_path: str,
                face_track=None, scenes=None,
                width: int = 1080, height: int = 1920,
                volume: float = 1.0, style: str = "karaoke",
                framing_offset: float = 0.0,
                preset: str = "veryfast") -> str:
    """Render one vertical clip. `words` are absolute-time word dicts for
    captions; `face_track` is a smoothed [(t, center_x)] list (may be
    empty -> centre crop); `scenes` are (start, end) spans used as
    segment boundaries. Raises FFmpegError on failure.

    Editor parameters (all optional, defaults keep first-time renders
    identical to Phase 1):
      volume         audio multiplier, applied as an FFmpeg `volume`
                     filter (1.0 = unchanged, filter omitted entirely).
      style          caption style name, one of captions.CAPTION_STYLES
                     ("karaoke" default).
      framing_offset horizontal nudge added to the face-track median
                     centre, -1..1, clamped to 0..1. With no face track
                     it nudges the centre crop instead (0.5 + offset).
      preset         x264 preset ("veryfast" default). This is a memory
                     knob as well as a speed/quality knob: at 1080x1920
                     the render child peaks at ~418 MB with "veryfast"
                     but ~210 MB with "ultrafast" (measured 2026-11-16)
                     — the Render free deploy sets "ultrafast" so the
                     job fits in 512 MB alongside the backend process.
    """
    work_dir = os.path.dirname(out_path)
    # Segment boundaries: scene cuts strictly inside the window.
    cuts = sorted({s for s, _ in (scenes or []) if start < s < end})
    bounds = [start] + cuts + [end]
    segments = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)
                if bounds[i + 1] - bounds[i] > 0.1]
    if not segments:
        segments = [(start, end)]

    track = face_track or []
    segment_paths = []
    for i, (seg_start, seg_end) in enumerate(segments):
        # Median face position inside this segment, or None -> centre crop.
        xs = [x for t, x in track if seg_start <= t < seg_end]
        center_x = statistics.median(xs) if xs else None
        if framing_offset:
            # Nudge the crop centre; no face -> nudge from centre (0.5).
            base = center_x if center_x is not None else 0.5
            center_x = min(1.0, max(0.0, base + framing_offset))
        ass_path = None
        if words:
            ass_path = os.path.join(work_dir, f".seg{i}.ass")
            write_ass(words, seg_start, seg_end, ass_path, style=style)
        seg_path = os.path.join(work_dir, f".seg{i}.mp4")
        _render_segment(source_path, seg_start, seg_end, ass_path,
                        seg_path, center_x, volume=volume, preset=preset)
        segment_paths.append(seg_path)
        if ass_path and os.path.exists(ass_path):
            os.remove(ass_path)

    if len(segment_paths) == 1:
        os.replace(segment_paths[0], out_path)
    else:
        _concat_segments(segment_paths, out_path, preset=preset)
        for p in segment_paths:
            if os.path.exists(p):
                os.remove(p)
    return out_path
