"""MMSN Clipper — FastAPI backend.

Endpoints:
  GET  /health                                   (public)
  POST /auth/register                            (sign-up)
  POST /auth/jwt/login                           (sign-in, JWT)
  GET  /users/me                                 (current user)
  POST /api/projects/upload          (video file upload — primary path)
  POST /api/projects/youtube         (link -> metadata only, Data API)
  GET  /api/projects                 (list, own projects only)
  GET  /api/projects/{id}
  POST /api/projects/{id}/process    (start pipeline job)
  GET  /api/jobs/{id}                (job status)
  GET  /api/projects/{id}/clips
  GET  /api/projects/{id}/transcript
  GET  /api/projects/{id}/highlights
  GET  /api/clips/{id}                 (editor detail: clip + highlight window)
  GET  /api/clips/{id}/captions        (caption groups for the editor)
  POST /api/clips/{id}/re-render       (editor edits -> background re-render)
  POST /api/clips/{id}/regenerate      (clean re-render with stored edits)
  POST /api/clips/{id}/thumbnail?t=..  (set thumbnail frame)
  GET  /api/clips/{id}/thumbnail       (serve the thumbnail JPEG)
  GET  /api/clips/{id}/download

Phase 2, step 1: real auth (fastapi-users 15.0.0, JWT bearer). EVERY /api/*
route requires a valid token (``current_active_user``) and is scoped to the
signed-in user's own projects: a project/job/clip owned by someone else
returns 404, exactly as if it did not exist — existence is never leaked.
The Phase 1 placeholder dev user is gone; nothing works unauthenticated.

Logout is client-side token discard (see auth.py): the frontend deletes
the stored JWT on sign-out / on any 401. Tokens expire after
AUTH_TOKEN_LIFETIME_SECONDS (default 7 days).

Phase 3 (production hardening): Postgres via DATABASE_URL (see
database.py), S3-compatible storage via STORAGE_BACKEND (see
storage.py — upload/download/thumbnail go through it; the pipeline
reads DB paths, materialised by the job wrapper in jobs.py), and
Celery + Redis workers via CELERY_BROKER_URL (see celery_app.py —
unset means the in-process queue, as before). /health reports which
backends this process is running with.

Run: uvicorn backend.app.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import shutil
import uuid

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from .auth import (UserCreate, UserRead, UserUpdate, auth_backend,
                   current_active_user, fastapi_users,
                   seed_user_if_configured)
from .config import settings
from .database import SessionLocal, get_db, init_db
from .jobs import mark_stale_jobs_failed, recover_interrupted_jobs, submit_job
from .models import Clip, Highlight, Job, Project, Transcript, User
from .storage import get_storage, is_s3_ref
from .schemas import (CaptionOverrideIn, ClipCaptionsOut, ClipDetailOut,
                      ClipOut, HighlightOut, JobOut, ProjectOut,
                      ReRenderRequest, ThumbnailOut, TranscriptOut,
                      YouTubeLinkRequest)
from .youtube import (YouTubeApiError, YouTubeNotConfiguredError,
                      extract_video_id, fetch_metadata)
from ..pipeline.audio import FFmpegError, probe_duration, run
from ..pipeline.captions import CAPTION_STYLES, caption_groups
from ..pipeline.rerender import (MIN_CLIP_SECONDS, merge_edit_params,
                                 run_rerender)
from ..pipeline.runner import run_pipeline

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

app = FastAPI(title="MMSN Clipper", version="0.2.0",
              description="AI long-form video to Shorts/Reels/TikTok clipper")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth routers (fastapi-users) ──────────────────────────────────────────
# POST /auth/register, POST /auth/jwt/login, GET/PATCH/DELETE /users/me, …
app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt", tags=["auth"])
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth", tags=["auth"])
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users", tags=["users"])


@app.on_event("startup")
async def startup():
    init_db()
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.media_dir, exist_ok=True)
    await seed_user_if_configured()
    if settings.celery_enabled:
        # Celery mode: jobs survive a backend restart — re-queue rows
        # still queued/running instead of failing them (see jobs.py).
        # A misconfigured Celery (broker set, package missing) fails
        # startup loudly here rather than silently running jobs
        # in-process.
        recovered = recover_interrupted_jobs()
        if recovered:
            print(f"Re-queued {recovered} interrupted job(s) to Celery.")
    else:
        stale = mark_stale_jobs_failed()
        if stale:
            print(f"Marked {stale} stale job(s) as failed (server restarted).")


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0",
            "youtube_api_configured": bool(settings.youtube_api_key),
            "llm_scoring_configured": bool(settings.openai_api_key),
            "whisper_model": settings.whisper_model,
            # Phase 3 (production hardening) — which backends this
            # process is actually running with. Local dev reports
            # sqlite / local / in-process.
            "database": settings.database_dialect,
            "storage_backend": ("s3" if settings.use_s3 else "local"),
            "job_queue": ("celery" if settings.celery_enabled
                          else "in-process")}


def _project_or_404(db: Session, project_id: int, user: User) -> Project:
    """The caller's OWN project, or 404. Another user's project returns
    404 too — its existence is never leaked."""
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user.id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _job_or_404(db: Session, job_id: int, user: User) -> Job:
    job = db.query(Job).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    project = db.query(Project).get(job.project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/projects/upload", response_model=ProjectOut, status_code=201)
async def upload_project(file: UploadFile = File(...),
                         db: Session = Depends(get_db),
                         user: User = Depends(current_active_user)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: "
                   f"{', '.join(sorted(ALLOWED_EXTENSIONS))}")
    os.makedirs(settings.upload_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    # Stream to a temp file first (ffprobe needs a local file), then
    # hand it to the storage backend. Local mode moves it to
    # UPLOAD_DIR/<stored_name> — the exact path Phase 1/2 stored.
    # S3 mode uploads it to s3://<bucket>/uploads/<stored_name> and
    # the temp file is removed afterwards.
    tmp_path = os.path.join(settings.upload_dir,
                            f".upload-{uuid.uuid4().hex}.part")
    size = 0
    with open(tmp_path, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > settings.max_upload_bytes:
                out.close()
                os.remove(tmp_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {settings.max_upload_mb} MB limit")
            out.write(chunk)
    duration = probe_duration(tmp_path)
    if duration <= 0:
        os.remove(tmp_path)
        raise HTTPException(
            status_code=400,
            detail="Could not read this video file (ffprobe found no duration). "
                   "It may be corrupt or in an unsupported format.")
    if duration > settings.max_video_seconds:
        os.remove(tmp_path)
        raise HTTPException(
            status_code=400,
            detail=f"Video is {duration/3600:.1f}h long — the limit is "
                   f"{settings.max_video_seconds/3600:.0f}h.")
    storage = get_storage()
    stored_path = storage.put_file(
        tmp_path, storage.make_ref("upload", stored_name))
    if os.path.exists(tmp_path):
        # S3 put_file leaves the local file behind; local put_file
        # moved it, so this only fires in S3 mode.
        os.remove(tmp_path)
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
def youtube_link(body: YouTubeLinkRequest, db: Session = Depends(get_db),
                 user: User = Depends(current_active_user)):
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
def list_projects(db: Session = Depends(get_db),
                  user: User = Depends(current_active_user)):
    return db.query(Project).filter(
        Project.user_id == user.id).order_by(
        Project.created_at.desc()).all()


@app.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db),
                user: User = Depends(current_active_user)):
    return _project_or_404(db, project_id, user)


@app.post("/api/projects/{project_id}/process", response_model=JobOut,
          status_code=202)
def process_project(project_id: int, db: Session = Depends(get_db),
                    user: User = Depends(current_active_user)):
    project = _project_or_404(db, project_id, user)
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
def get_job(job_id: int, db: Session = Depends(get_db),
            user: User = Depends(current_active_user)):
    return _job_or_404(db, job_id, user)


@app.get("/api/projects/{project_id}/clips", response_model=list[ClipOut])
def list_clips(project_id: int, db: Session = Depends(get_db),
               user: User = Depends(current_active_user)):
    _project_or_404(db, project_id, user)
    return db.query(Clip).filter(Clip.project_id == project_id).all()


@app.get("/api/projects/{project_id}/highlights",
         response_model=list[HighlightOut])
def list_highlights(project_id: int, db: Session = Depends(get_db),
                    user: User = Depends(current_active_user)):
    _project_or_404(db, project_id, user)
    return db.query(Highlight).filter(
        Highlight.project_id == project_id).order_by(
        Highlight.score.desc()).all()


@app.get("/api/projects/{project_id}/transcript",
         response_model=TranscriptOut)
def get_transcript(project_id: int, db: Session = Depends(get_db),
                   user: User = Depends(current_active_user)):
    _project_or_404(db, project_id, user)
    t = db.query(Transcript).filter(
        Transcript.project_id == project_id).order_by(
        Transcript.created_at.desc()).first()
    if t is None:
        raise HTTPException(status_code=404,
                            detail="No transcript yet — process the project first.")
    return TranscriptOut(language=t.language, full_text=t.full_text,
                         segments=t.segments)


@app.get("/api/clips/{clip_id}/download")
def download_clip(clip_id: int, db: Session = Depends(get_db),
                  user: User = Depends(current_active_user)):
    clip = db.query(Clip).get(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    project = db.query(Project).get(clip.project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Clip not found")
    storage = get_storage()
    if not storage.exists(clip.path):
        raise HTTPException(status_code=410,
                            detail="Clip file is no longer on disk.")
    if is_s3_ref(clip.path):
        # S3 mode: the browser downloads straight from the bucket on
        # a presigned URL (valid S3_PRESIGNED_EXPIRY_SECONDS).
        url = storage.download_url(
            clip.path, filename=f"mmsn-clip-{clip.id}.mp4")
        return RedirectResponse(url=url, status_code=302)
    return FileResponse(clip.path, media_type="video/mp4",
                        filename=f"mmsn-clip-{clip.id}.mp4")


# ── Editor endpoints (Phase 2, step 2) ────────────────────────────────────

def _clip_or_404(db: Session, clip_id: int, user: User) -> Clip:
    """The caller's OWN clip, or 404. Another user's clip returns 404
    too — its existence is never leaked."""
    clip = db.query(Clip).get(clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    project = db.query(Project).get(clip.project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip


def _highlight_or_400(db: Session, clip: Clip) -> Highlight:
    """The highlight window a clip was cut from. Trimming and captions
    are defined relative to this window, so a clip without one cannot
    be edited (every clip the pipeline renders has one)."""
    hl = db.query(Highlight).get(clip.highlight_id) \
        if clip.highlight_id else None
    if hl is None:
        raise HTTPException(
            status_code=400,
            detail="This clip has no highlight window, so it cannot be "
                   "trimmed or re-rendered.")
    return hl


def _validate_trim(trim_start: float, trim_end: float,
                   highlight_duration: float) -> None:
    """Trim is clip-relative seconds into the highlight window:
    0 <= start < end <= highlight duration, at least ~2 s long."""
    if not (0 <= trim_start < trim_end <= highlight_duration):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid trim: need 0 <= start < end <= "
                   f"{highlight_duration:.1f}s (the highlight window), "
                   f"got start={trim_start}, end={trim_end}.")
    if trim_end - trim_start < MIN_CLIP_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Trimmed clip must be at least {MIN_CLIP_SECONDS:.0f}s "
                   f"long, got {trim_end - trim_start:.1f}s.")


def _start_rerender_job(db: Session, clip: Clip) -> Job:
    """Create + submit a kind="rerender" job for this clip (reusing the
    jobs table and the same submit_job/polling pattern as process). If
    one is already queued/running for this clip, return it instead of
    starting a second render on the same file."""
    existing = db.query(Job).filter(
        Job.clip_id == clip.id, Job.kind == "rerender",
        Job.status.in_(["queued", "running"])).first()
    if existing:
        return existing
    job = Job(project_id=clip.project_id, clip_id=clip.id,
              kind="rerender", status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    clip.status = "rendering"
    db.commit()
    submit_job(job.id, run_rerender, clip.id, SessionLocal)
    return job


@app.get("/api/clips/{clip_id}", response_model=ClipDetailOut)
def get_clip(clip_id: int, db: Session = Depends(get_db),
             user: User = Depends(current_active_user)):
    clip = _clip_or_404(db, clip_id, user)
    hl = db.query(Highlight).get(clip.highlight_id) \
        if clip.highlight_id else None
    data = ClipOut.model_validate(clip).model_dump()
    data.update({
        "highlight_start_sec": hl.start_sec if hl else None,
        "highlight_end_sec": hl.end_sec if hl else None,
        "highlight_duration_sec": (hl.end_sec - hl.start_sec) if hl else None,
        "edit_params": clip.edit_params,
    })
    return ClipDetailOut(**data)


@app.get("/api/clips/{clip_id}/captions", response_model=ClipCaptionsOut)
def get_clip_captions(clip_id: int, db: Session = Depends(get_db),
                      user: User = Depends(current_active_user)):
    """Caption groups for the editor: the words in the clip's current
    (trimmed) window, grouped the way the renderer groups them, with
    clip-relative times, plus the current style and stored overrides."""
    clip = _clip_or_404(db, clip_id, user)
    hl = _highlight_or_400(db, clip)
    params = merge_edit_params(clip.edit_params,
                               hl.end_sec - hl.start_sec, None)
    abs_start = hl.start_sec + params["trim_start"]
    abs_end = hl.start_sec + params["trim_end"]
    transcript = db.query(Transcript).filter(
        Transcript.project_id == clip.project_id).order_by(
        Transcript.created_at.desc()).first()
    if transcript is None:
        raise HTTPException(status_code=404,
                            detail="No transcript yet — process the project "
                                   "first.")
    words = [w for s in transcript.segments for w in s.get("words", [])]
    groups = caption_groups(words, abs_start, abs_end)
    overrides = [CaptionOverrideIn(**o) for o in
                 (params.get("caption_overrides") or [])
                 if isinstance(o, dict) and "group_index" in o
                 and "text" in o]
    return ClipCaptionsOut(clip_id=clip.id, style=params["style"],
                           groups=groups, overrides=overrides,
                           window_start_sec=abs_start,
                           window_end_sec=abs_end)


@app.post("/api/clips/{clip_id}/re-render", response_model=JobOut,
          status_code=202)
def rerender_clip(clip_id: int, body: ReRenderRequest,
                  db: Session = Depends(get_db),
                  user: User = Depends(current_active_user)):
    """Apply editor edits and re-render the clip for real (background
    job). Trim is relative to the highlight window; omitted fields keep
    the clip's stored values. Returns the re-render job — poll
    GET /api/jobs/{id}; on success the Clip row points at the new
    versioned file (clip_{id}_v{n}.mp4)."""
    clip = _clip_or_404(db, clip_id, user)
    hl = _highlight_or_400(db, clip)
    hl_duration = hl.end_sec - hl.start_sec
    if body.style is not None and body.style not in CAPTION_STYLES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown subtitle style '{body.style}'. Choose one of: "
                   f"{', '.join(sorted(CAPTION_STYLES))}.")
    stored = clip.edit_params
    trim_start = body.trim_start if body.trim_start is not None \
        else stored.get("trim_start", 0.0)
    trim_end = body.trim_end if body.trim_end is not None \
        else stored.get("trim_end", hl_duration)
    _validate_trim(float(trim_start), float(trim_end), hl_duration)
    params = merge_edit_params(stored, hl_duration,
                               body.model_dump(exclude_none=True))
    clip.edit_params_json = json.dumps(params)
    db.commit()
    return _start_rerender_job(db, clip)


@app.post("/api/clips/{clip_id}/regenerate", response_model=JobOut,
          status_code=202)
def regenerate_clip(clip_id: int, db: Session = Depends(get_db),
                    user: User = Depends(current_active_user)):
    """Re-render the same highlight window fresh with the clip's current
    stored edit parameters — no parameter changes. Use it after a failed
    render, or to pick up pipeline fixes (e.g. a new caption style or
    render change) without re-entering the edits. The output is a new
    versioned file, exactly like a re-render."""
    clip = _clip_or_404(db, clip_id, user)
    _highlight_or_400(db, clip)
    return _start_rerender_job(db, clip)


@app.post("/api/clips/{clip_id}/thumbnail", response_model=ThumbnailOut)
def set_clip_thumbnail(clip_id: int, t: float = Query(..., ge=0),
                       db: Session = Depends(get_db),
                       user: User = Depends(current_active_user)):
    """Extract a JPEG frame at `t` seconds into the rendered clip and
    store it as the clip's thumbnail (overwrites any previous one).
    Served by GET /api/clips/{id}/thumbnail."""
    clip = _clip_or_404(db, clip_id, user)
    storage = get_storage()
    # FFmpeg needs a local file: in S3 mode the clip is downloaded to
    # the cache first (local mode: this is the path itself, unchanged).
    clip_local = storage.local_path(clip.path)
    if not os.path.exists(clip_local):
        raise HTTPException(status_code=410,
                            detail="Clip file is no longer on disk.")
    duration = clip.duration_sec or probe_duration(clip_local)
    if duration <= 0 or t > duration:
        raise HTTPException(
            status_code=400,
            detail=f"t must be within the clip (0–{duration:.1f}s), "
                   f"got {t}.")
    if is_s3_ref(clip.path):
        # S3 mode: extract to a temp file, upload it next to the clip
        # in the bucket (media/project_<id>/clip_<id>_thumb.jpg), and
        # store the s3:// ref. The local temp file is removed after.
        from .storage import parse_s3_ref
        bucket, key = parse_s3_ref(clip.path)
        thumb_key = key.rsplit(".", 1)[0] + "_thumb.jpg" \
            if "." in os.path.basename(key) else key + "_thumb.jpg"
        # (clip filenames always end .mp4, so the rsplit above yields
        # clip_<id>_thumb.jpg next to the clip.)
        thumb_tmp = os.path.join(
            settings.media_dir, ".s3cache",
            f"thumb-{clip.id}-{uuid.uuid4().hex}.jpg")
        os.makedirs(os.path.dirname(thumb_tmp), exist_ok=True)
        result = run(["ffmpeg", "-y", "-v", "error", "-ss", str(t),
                      "-i", clip_local, "-frames:v", "1", "-q:v", "3",
                      thumb_tmp])
        if result.returncode != 0 or not os.path.exists(thumb_tmp):
            raise FFmpegError(
                f"Thumbnail extraction failed: {result.stderr.strip()[:300]}")
        thumb_ref = storage.put_file(
            thumb_tmp, f"s3://{bucket}/{thumb_key}")
        os.remove(thumb_tmp)
    else:
        work_dir = os.path.dirname(clip.path)
        thumb_path = os.path.join(work_dir, f"clip_{clip.id}_thumb.jpg")
        result = run(["ffmpeg", "-y", "-v", "error", "-ss", str(t),
                      "-i", clip.path, "-frames:v", "1", "-q:v", "3",
                      thumb_path])
        if result.returncode != 0 or not os.path.exists(thumb_path):
            raise FFmpegError(
                f"Thumbnail extraction failed: {result.stderr.strip()[:300]}")
        thumb_ref = thumb_path
    clip.thumbnail_path = thumb_ref
    db.commit()
    return ThumbnailOut(clip_id=clip.id, t=t,
                        thumbnail_url=f"/api/clips/{clip.id}/thumbnail")


@app.get("/api/clips/{clip_id}/thumbnail")
def get_clip_thumbnail(clip_id: int, db: Session = Depends(get_db),
                       user: User = Depends(current_active_user)):
    clip = _clip_or_404(db, clip_id, user)
    storage = get_storage()
    if not clip.thumbnail_path or not storage.exists(clip.thumbnail_path):
        raise HTTPException(status_code=404,
                            detail="No thumbnail set for this clip yet — "
                                   "use the editor to pick a frame.")
    if is_s3_ref(clip.thumbnail_path):
        url = storage.download_url(
            clip.thumbnail_path,
            filename=f"mmsn-clip-{clip.id}-thumb.jpg")
        return RedirectResponse(url=url, status_code=302)
    return FileResponse(clip.thumbnail_path, media_type="image/jpeg",
                        filename=f"mmsn-clip-{clip.id}-thumb.jpg")
