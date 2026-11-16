"""Clip re-render — the editor's render worker (Phase 2, step 2).

``run_rerender(job_id, clip_id, session_factory)`` is the background job
for POST /api/clips/{id}/re-render and /regenerate. It re-renders ONE
clip from its source video with the clip's stored edit parameters:

  trim (clip-relative seconds into the highlight window) -> absolute
      window = highlight.start + trim_start .. highlight.start + trim_end
  caption overrides -> edited caption-group text replaces the group's
      words; the new words are re-timed proportionally across the group's
      span (equal slices). This is an APPROXIMATION, stated honestly:
      the edited words do not come from a new transcription, so their
      timing is evenly spread, not speech-aligned. A re-transcription
      after an edit would be the accurate (and much slower) alternative.
  style / framing_offset / volume -> passed straight to render_clip().

The output is versioned: clip_{id}_v{version+1}.mp4 next to the original.
Only after the new file renders successfully does the Clip row switch
to it (path/duration/file_size/version/status) and the old version file
get deleted. If the render fails, the Clip row keeps pointing at the
last good file and its status returns to "ready" — the job row carries
the error, so a failed re-render never leaves the user without a clip.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from ..app.config import settings
from ..app.jobs import update_job
from ..app.models import Clip, Highlight, Project, Transcript
from .audio import probe_duration
from .captions import CAPTION_STYLES, DEFAULT_STYLE, group_words
from .memory import trim_memory
from .reframe import face_track_for_clip
from .render import render_clip
from .scenes import detect_scenes

logger = logging.getLogger(__name__)

MIN_CLIP_SECONDS = 2.0


def default_edit_params(highlight_duration: float) -> dict:
    """The edit parameters of a never-edited clip: full highlight window,
    karaoke captions, no nudge, volume 1.0."""
    return {
        "trim_start": 0.0,
        "trim_end": float(highlight_duration),
        "caption_overrides": [],
        "style": DEFAULT_STYLE,
        "framing_offset": 0.0,
        "volume": 1.0,
    }


def merge_edit_params(stored: dict, highlight_duration: float,
                      update: dict | None) -> dict:
    """Stored params, filled with defaults, with `update` applied on top.
    Unknown keys are dropped; out-of-range values are clamped so a bad
    stored row can never crash a render."""
    params = default_edit_params(highlight_duration)
    params.update({k: v for k, v in (stored or {}).items() if k in params})
    if update:
        params.update({k: v for k, v in update.items()
                       if k in params and v is not None})
    params["style"] = params.get("style") or DEFAULT_STYLE
    if params["style"] not in CAPTION_STYLES:
        params["style"] = DEFAULT_STYLE
    params["framing_offset"] = min(1.0, max(-1.0,
                                            float(params["framing_offset"])))
    params["volume"] = min(2.0, max(0.25, float(params["volume"])))
    params["trim_start"] = max(0.0, float(params["trim_start"]))
    params["trim_end"] = min(float(highlight_duration),
                             float(params["trim_end"]))
    return params


def retime_text(text: str, start: float, end: float) -> list[dict]:
    """Split edited caption text into word dicts, re-timed proportionally
    across [start, end]: each word gets an equal slice of the span.
    APPROXIMATION (see module docstring): timing is evenly spread, not
    speech-aligned. Words carry a leading space (except the first), the
    same convention faster-whisper words use, so joining them reproduces
    the edited text exactly."""
    tokens = text.split()
    if not tokens:
        return []
    span = max(0.0, end - start)
    out = []
    for i, token in enumerate(tokens):
        out.append({
            "start": start + span * i / len(tokens),
            "end": start + span * (i + 1) / len(tokens),
            "word": (" " + token) if i > 0 else token,
        })
    return out


def apply_caption_overrides(words: list, start: float, end: float,
                            overrides: list[dict]) -> list[dict]:
    """Apply caption text overrides to the words in [start, end].

    `overrides` are {group_index, text} against the caption groups of
    the current (trimmed) window, in order. An override replaces its
    group's words with re-timed words from the new text; an empty text
    drops the group (no captions for it). Groups without an override
    keep their transcribed words. Unknown group indexes are ignored.

    Group boundaries are preserved: the first word of an edited group
    and the first word of the group after it carry a ``_new_group``
    flag, so the renderer's regrouping (captions.group_words) cannot
    absorb the edited words into a neighbouring group or pull the next
    word into the edited one — without this, an edit like "HELLO
    EDITED WORDS" rendered as "HELLO EDITED WORDS welcome".
    Returns the flat word list the renderer captions from.
    """
    window_words = [w for w in words if w["end"] > start and w["start"] < end]
    groups = group_words(window_words)
    by_index = {int(o["group_index"]): o["text"]
                for o in (overrides or [])
                if isinstance(o, dict) and "group_index" in o
                and "text" in o}
    out: list[dict] = []
    for i, group in enumerate(groups):
        if i not in by_index:
            out.extend(group)
            continue
        new_text = str(by_index[i]).strip()
        if new_text:
            new_words = retime_text(new_text, group[0]["start"],
                                    group[-1]["end"])
            new_words[0]["_new_group"] = True
            out.extend(new_words)
        # Boundary after the edited (or dropped) group: the next group's
        # first word must start a new group when re-grouped.
        if i + 1 < len(groups) and groups[i + 1]:
            nxt = dict(groups[i + 1][0])
            nxt["_new_group"] = True
            groups[i + 1][0] = nxt
    return out


def _fail(job_id: int, clip_id: int, db, message: str):
    update_job(job_id, status="failed", error=message,
               finished_at=datetime.utcnow())
    clip = db.query(Clip).get(clip_id)
    if clip is not None and clip.status == "rendering":
        # The old file is still good — point the clip back at it.
        clip.status = "ready"
        db.commit()
    logger.error("Re-render job %s (clip %s) failed: %s",
                 job_id, clip_id, message)


def run_rerender(job_id: int, clip_id: int, session_factory):
    """Background job entry point. Updates the job row as it goes."""
    db = session_factory()
    try:
        clip = db.query(Clip).get(clip_id)
        if clip is None:
            update_job(job_id, status="failed",
                       error=f"Clip {clip_id} not found.",
                       finished_at=datetime.utcnow())
            return
        project = db.query(Project).get(clip.project_id)
        highlight = (db.query(Highlight).get(clip.highlight_id)
                     if clip.highlight_id else None)
        if project is None or not project.source_path or \
                not os.path.exists(project.source_path):
            _fail(job_id, clip_id, db,
                  "Source video is no longer on disk — cannot re-render.")
            return
        if highlight is None:
            _fail(job_id, clip_id, db,
                  "This clip has no highlight window, so it cannot be "
                  "trimmed or re-rendered.")
            return
        transcript = db.query(Transcript).filter(
            Transcript.project_id == project.id).order_by(
            Transcript.created_at.desc()).first()
        if transcript is None:
            _fail(job_id, clip_id, db,
                  "No transcript for this project — cannot rebuild captions.")
            return

        hl_duration = highlight.end_sec - highlight.start_sec
        params = merge_edit_params(clip.edit_params, hl_duration, None)
        abs_start = highlight.start_sec + params["trim_start"]
        abs_end = highlight.start_sec + params["trim_end"]
        if abs_end - abs_start < MIN_CLIP_SECONDS:
            _fail(job_id, clip_id, db,
                  "Trim window is shorter than "
                  f"{MIN_CLIP_SECONDS:.0f} seconds.")
            return
        update_job(job_id, progress=20)

        all_words = [w for s in transcript.segments
                     for w in s.get("words", [])]
        words = apply_caption_overrides(
            all_words, abs_start, abs_end,
            params.get("caption_overrides") or [])

        # Scene detection (best-effort) + face track for the new window.
        scenes = detect_scenes(project.source_path)
        face_track = (face_track_for_clip(
            project.source_path, abs_start, abs_end, scenes)
            if settings.face_tracking else [])
        # Hand memory back before the render child starts (see
        # backend/pipeline/memory.py) — same reason as in runner.py.
        trim_memory()
        update_job(job_id, progress=40)

        work_dir = os.path.dirname(clip.path)
        os.makedirs(work_dir, exist_ok=True)
        new_version = (clip.version or 1) + 1
        out_path = os.path.join(work_dir,
                                f"clip_{clip.id}_v{new_version}.mp4")
        old_path = clip.path
        try:
            render_clip(project.source_path, abs_start, abs_end, words,
                        out_path, face_track=face_track, scenes=scenes,
                        volume=params["volume"], style=params["style"],
                        framing_offset=params["framing_offset"],
                        preset=settings.render_preset)
        except Exception as exc:
            _fail(job_id, clip_id, db, f"Render failed: {exc}")
            return
        update_job(job_id, progress=80)

        clip.path = out_path
        clip.version = new_version
        clip.duration_sec = probe_duration(out_path)
        clip.file_size_bytes = os.path.getsize(out_path)
        clip.status = "ready"
        clip.edit_params_json = json.dumps(params)
        db.commit()
        # Old version is superseded only now that the new one is stored.
        if old_path != out_path and os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                logger.warning("Could not delete superseded clip file %s",
                               old_path)
        update_job(job_id, status="done", progress=100,
                   finished_at=datetime.utcnow())
        logger.info("Re-render job %s done: clip %s v%s (%.1fs)",
                    job_id, clip.id, new_version, clip.duration_sec or 0)
    finally:
        db.close()
