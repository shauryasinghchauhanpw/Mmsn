"""Pipeline runner — the whole job, as a plain function of
(project_id, session_factory) so it can move unchanged from the Phase 1
in-process queue to Redis/Celery workers later.

Steps: audio extraction -> transcription -> highlight detection ->
scene snap -> per-clip ASS captions -> FFmpeg render -> DB rows.
Any step that cannot run fails the job with a clear error message —
nothing is ever faked.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from ..app.config import settings
from ..app.jobs import update_job
from ..app.models import Clip, Highlight, Job, Project, Transcript
from .audio import extract_audio, probe_duration
from .captions import write_ass  # noqa: F401  (kept for direct use/tests)
from .highlights import detect_highlights
from .reframe import face_track_for_clip
from .render import render_clip
from .scenes import detect_scenes, snap_to_scene
from .transcribe import TranscriptionUnavailableError, transcribe

logger = logging.getLogger(__name__)


def _progress(job_id: int, pct: int):
    update_job(job_id, progress=pct)


def _fail(job_id: int, project_id: int, db, message: str):
    update_job(job_id, status="failed", error=message,
               finished_at=datetime.utcnow())
    project = db.query(Project).get(project_id)
    if project is not None:
        project.status = "failed"
        db.commit()
    logger.error("Job %s failed: %s", job_id, message)


def run_pipeline(job_id: int, project_id: int, session_factory):
    """Entry point for the job queue. Updates the job row as it goes."""
    db = session_factory()
    try:
        project = db.query(Project).get(project_id)
        if project is None:
            update_job(job_id, status="failed",
                       error=f"Project {project_id} not found.",
                       finished_at=datetime.utcnow())
            return
        if not project.source_path or not os.path.exists(project.source_path):
            _fail(job_id, project_id, db,
                  "No uploaded video file for this project. A pasted YouTube "
                  "link only provides metadata — upload the video file to "
                  "generate clips.")
            return

        os.makedirs(settings.media_dir, exist_ok=True)
        work_dir = os.path.join(settings.media_dir, f"project_{project_id}")
        os.makedirs(work_dir, exist_ok=True)
        wav_path = os.path.join(work_dir, "audio.wav")

        # 1. Audio extraction (10%)
        _progress(job_id, 10)
        try:
            extract_audio(project.source_path, wav_path)
        except Exception as exc:
            _fail(job_id, project_id, db, f"Audio extraction failed: {exc}")
            return

        # 2. Transcription (10-50%)
        _progress(job_id, 20)
        try:
            result = transcribe(wav_path, model_name=settings.whisper_model,
                                device=settings.whisper_device,
                                compute_type=settings.whisper_compute_type)
        except TranscriptionUnavailableError as exc:
            _fail(job_id, project_id, db, str(exc))
            return
        _progress(job_id, 50)

        transcript = Transcript(project_id=project_id,
                                language=result["language"],
                                full_text=result["full_text"],
                                segments_json=json.dumps(result["segments"]))
        db.add(transcript)
        db.commit()

        # 3. Highlight detection (50-60%)
        llm_config = None
        if settings.openai_api_key:
            llm_config = (settings.openai_api_key,
                          settings.openai_base_url, settings.openai_model)
        highlights, scorer = detect_highlights(
            result["segments"], count=settings.clips_per_project,
            min_s=settings.clip_min_seconds,
            max_s=settings.clip_max_seconds, llm_config=llm_config)
        if not highlights:
            _fail(job_id, project_id, db,
                  "No highlight moments found — the transcript was too short "
                  "or too sparse to build a 15-60s clip.")
            return
        _progress(job_id, 60)

        # 4. Scene detection (best-effort) + snap boundaries
        scenes = detect_scenes(project.source_path)
        all_words = [w for s in result["segments"] for w in s.get("words", [])]

        # 5. Render clips (60-95%)
        rendered = 0
        for i, h in enumerate(highlights):
            start, end = snap_to_scene(h["start_sec"], h["end_sec"], scenes)
            hl = Highlight(project_id=project_id, start_sec=start,
                           end_sec=end, score=h["score"],
                           scorer=scorer,
                           reasons_json=json.dumps(h["reasons"]),
                           title=h["title"], description=h["description"],
                           hashtags_json=json.dumps(h["hashtags"]))
            db.add(hl)
            db.commit()
            db.refresh(hl)

            # Face-tracked reframe (YuNet + smoothing + cut resets);
            # empty track -> centre crop inside render_clip.
            face_track = face_track_for_clip(project.source_path, start, end,
                                             scenes)
            out_path = os.path.join(work_dir, f"clip_{hl.id}.mp4")
            try:
                render_clip(project.source_path, start, end, all_words,
                            out_path, face_track=face_track, scenes=scenes)
            except Exception as exc:
                logger.warning("Clip %s render failed: %s", hl.id, exc)
                continue
            clip = Clip(project_id=project_id, highlight_id=hl.id,
                        title=h["title"], path=out_path, width=1080,
                        height=1920,
                        duration_sec=probe_duration(out_path),
                        file_size_bytes=os.path.getsize(out_path),
                        status="ready")
            db.add(clip)
            db.commit()
            rendered += 1
            _progress(job_id, 60 + int(35 * (i + 1) / len(highlights)))

        if rendered == 0:
            _fail(job_id, project_id, db,
                  "All clip renders failed — check the server logs for the "
                  "FFmpeg error.")
            return

        project.status = "done"
        db.commit()
        update_job(job_id, status="done", progress=100,
                   finished_at=datetime.utcnow())
        logger.info("Job %s done: project %s, %d clips",
                    job_id, project_id, rendered)
    finally:
        db.close()
