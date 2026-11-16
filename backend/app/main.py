"""MMSN Clipper — FastAPI backend.

Endpoints:
  GET  /health
  POST /api/projects/upload          (video file upload — primary path)
  POST /api/projects/youtube         (link -> metadata only, Data API)
  GET  /api/projects                 (list)
  GET  /api/projects/{id}
  POST /api/projects/{id}/process    (start pipeline job)
  GET  /api/jobs/{id}                (job status)
  GET  /api/projects/{id}/clips
  GET  /api/projects/{id}/transcript
  GET  /api/clips/{id}/download

Phase 1: single dev user (no real auth yet — see ARCHITECTURE.md).
Run: uvicorn backend.app.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import shutil
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal, get_db, get_or_create_dev_user, init_db
from .jobs import mark_stale_jobs_failed, submit_job
from .models import Clip, Job, Project, Transcript
from .schemas import (ClipOut, HighlightOut, JobOut, ProjectOut,
                      TranscriptOut, YouTubeLinkRequest)
from .youtube import (YouTubeApiError, YouTubeNotConfiguredError,
                      extract_video_id, fetch_metadata)
from ..pipeline.audio import probe_duration
from ..pipeline.runner import run_pipeline

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

app = FastAPI(title="MMSN Clipper", version="0.1.0",
              description="AI long-form video to Shorts/Reels/TikTok clipper (Phase 1)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.media_dir, exist_ok=True)
    db = SessionLocal()
    try:
        get_or_create_dev_user(db)
        stale = mark_stale_jobs_failed()
        if stale:
            print(f"Marked {stale} stale job(s) as failed (server restarted).")
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0",
            "youtube_api_configured": bool(settings.youtube_api_key),
            "llm_scoring_configured": bool(settings.openai_api_key),
            "whisper_model": settings.whisper_model}


def _project_or_404(db: Session, project_id: int) -> Project:
    project = db.query(Project).get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.post("/api/projects/upload", response_model=ProjectOut, status_code=201)
async def upload_project(file: UploadFile = File(...),
                         db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: "
                   f"{', '.join(sorted(ALLOWED_EXTENSIONS))}")
    user = get_or_create_dev_user(db)
    os.makedirs(settings.upload_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = os.path.join(settings.upload_dir, stored_name)
    size = 0
    with open(stored_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > settings.max_upload_bytes:
                out.close()
                os.remove(stored_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {settings.max_upload_mb} MB limit")
            out.write(chunk)
    duration = probe_duration(stored_path)
    if duration <= 0:
        os.remove(stored_path)
        raise HTTPException(
            status_code=400,
            detail="Could not read this video file (ffprobe found no duration). "
                   "It may be corrupt or in an unsupported format.")
    if duration > settings.max_video_seconds:
        os.remove(stored_path)
        raise HTTPException(
            status_code=400,
            detail=f"Video is {duration/3600:.1f}h long — the limit is "
                   f"{settings.max_video_seconds/3600:.0f}h.")
    project = Project(
        user_id=user.id,
        title=os.path.splitext(file.filename or stored_name)[0][:500],
        source_type="upload", source_path=stored_path,
        duration_sec=duration, status="uploaded")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.post("/api/projects/youtube", response_model=ProjectOut, status_code=201)
def youtube_link(body: YouTubeLinkRequest, db: Session = Depends(get_db)):
    """Link-paste path: metadata ONLY via the YouTube Data API.
    No video bytes are fetched; a link alone can never produce clips."""
    video_id = extract_video_id(body.url)
    if not video_id:
        raise HTTPException(
            status_code=400,
            detail="That doesn't look like a YouTube URL. Supported: "
                   "youtube.com/watch?v=..., youtu.be/..., youtube.com/shorts/..., "
                   "embed and /live/ links, or a bare 11-character video ID.")
    try:
        meta = fetch_metadata(video_id, settings.youtube_api_key)
    except YouTubeNotConfiguredError as exc:
        raise HTTPException(status_code=501, detail={
            "code": "youtube_api_not_configured",
            "message": str(exc)}) from exc
    except YouTubeApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    user = get_or_create_dev_user(db)
    project = Project(
        user_id=user.id, title=meta.title or f"YouTube {video_id}",
        source_type="youtube_link", source_url=body.url,
        youtube_video_id=video_id, thumbnail_url=meta.thumbnail_url,
        duration_sec=meta.duration_sec, status="metadata_only")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@app.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return _project_or_404(db, project_id)


@app.post("/api/projects/{project_id}/process", response_model=JobOut,
          status_code=202)
def process_project(project_id: int, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id)
    if project.source_type == "youtube_link" and not project.source_path:
        raise HTTPException(
            status_code=400,
            detail="This project is a YouTube link (metadata only). Upload the "
                   "video file to generate clips — a link cannot be processed.")
    existing = db.query(Job).filter(
        Job.project_id == project_id,
        Job.status.in_(["queued", "running"])).first()
    if existing:
        return existing
    job = Job(project_id=project_id, kind="process", status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    project.status = "processing"
    db.commit()
    submit_job(job.id, run_pipeline, project_id, SessionLocal)
    return job


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/projects/{project_id}/clips", response_model=list[ClipOut])
def list_clips(project_id: int, db: Session = Depends(get_db)):
    _project_or_404(db, project_id)
    return db.query(Clip).filter(Clip.project_id == project_id).all()


@app.get("/api/projects/{project_id}/highlights",
         response_model=list[HighlightOut])
def list_highlights(project_id: int, db: Session = Depends(get_db)):
    from .models import Highlight
    _project_or_404(db, project_id)
    return db.query(Highlight).filter(
        Highlight.project_id == project_id).order_by(
        Highlight.score.desc()).all()


@app.get("/api/projects/{project_id}/transcript",
         response_model=TranscriptOut)
def get_transcript(project_id: int, db: Session = Depends(get_db)):
    _project_or_404(db, project_id)
    t = db.query(Transcript).filter(
        Transcript.project_id == project_id).order_by(
        Transcript.created_at.desc()).first()
    if t is None:
        raise HTTPException(status_code=404,
                            detail="No transcript yet — process the project first.")
    return TranscriptOut(language=t.language, full_text=t.full_text,
                         segments=t.segments)


@app.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: int, db: Session = Depends(get_db)):
    clip = db.query(Clip).get(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    if not os.path.exists(clip.path):
        raise HTTPException(status_code=410,
                            detail="Clip file is no longer on disk.")
    return FileResponse(clip.path, media_type="video/mp4",
                        filename=f"mmsn-clip-{clip.id}.mp4")
