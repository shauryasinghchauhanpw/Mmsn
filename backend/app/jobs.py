"""Background jobs — in-process queue (Phase 1/2) + Celery (Phase 3).

Two dispatch modes, one job table, selected by ``CELERY_BROKER_URL``
(see ``config.py``):

* **In-process (default, broker unset):** the Phase 1/2 behaviour —
  a module-level ``ThreadPoolExecutor`` (2 workers). Jobs die with
  the process; on startup, jobs left ``queued``/``running`` by a
  previous process are marked ``failed`` (``mark_stale_jobs_failed``).
* **Celery (broker set):** ``submit_job`` sends the job to a Celery
  worker (``backend/app/celery_app.py``) instead of the pool. The
  pipeline entrypoints are unchanged — the Celery tasks call the same
  ``execute_job`` wrapper below, which is the single place that
  claims a job, runs it, and records a crash.

Job rows in the DB are the source of truth in both modes (status /
progress / error). With Celery, a queued/running job survives a
backend-process restart: the API process holds no job state, workers
are separate processes, and on startup the backend re-queues any job
rows still ``queued``/``running`` (``recover_interrupted_jobs``) in
case the broker lost the message. A worker killed mid-task has its
task redelivered (``acks_late`` — see ``celery_app.py``); the task
skips itself if the job already finished, so a redelivery after a
crash re-runs the pipeline from scratch. That re-run can leave
duplicate clip rows from the crashed attempt — a known gap, see
ARCHITECTURE.md §5.

S3 mode (``STORAGE_BACKEND=s3``): the pipeline reads file paths from
the DB, so before a job runs, ``execute_job`` materialises the
project's source file (and, for re-renders, the clip file) from S3
into the local cache and points the DB rows at the cached copies;
after the job it uploads any newly rendered clips to S3, points the
rows back at the ``s3://`` refs, and deletes the superseded S3
objects. The original ref is recorded in a ``.ref`` sidecar next to
each cached file (see ``storage.local_path``), so a worker killed
mid-job leaves rows pointing at cache paths that the next attempt
can resolve back to their S3 refs instead of failing. Local mode
skips all of this — the wrapper is a no-op there.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .config import settings
from .database import SessionLocal
from .models import Clip, Job, Project
from .storage import get_storage, is_s3_ref

logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mmsn-job")


def mark_stale_jobs_failed() -> int:
    """Mark jobs orphaned by a previous process run as failed.

    In-process mode only. In Celery mode the backend never does this —
    see recover_interrupted_jobs() — because a restart must not kill
    jobs that a live worker is still running."""
    db = SessionLocal()
    try:
        stale = db.query(Job).filter(
            Job.status.in_(["queued", "running"])).all()
        for job in stale:
            job.status = "failed"
            job.error = "Server restarted while this job was running."
            job.finished_at = datetime.utcnow()
        db.commit()
        return len(stale)
    finally:
        db.close()


def update_job(job_id: int, **fields) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).get(job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        db.commit()
    finally:
        db.close()


def _mark_job_failed(job_id: int, message: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).get(job_id)
        if job is not None and job.status == "running":
            job.status = "failed"
            job.error = message
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


# ── S3 materialise / publish (no-op unless STORAGE_BACKEND=s3) ──────────

def _materialize_path(ref: str | None) -> tuple[str | None, str | None]:
    """Return ``(local_path, original_ref)`` for a stored file ref.

    * ``s3://…`` ref → download to the local cache, return the cached
      path and the original ref (so the caller can restore it later).
    * A local path under the S3 cache dir (a row left pointing at the
      cache by a killed worker) → resolve the original ref from its
      ``.ref`` sidecar and re-download if the cached file is gone.
    * Any other local path → returned unchanged, no original ref.
    Returns ``(None, None)`` for an empty ref.
    """
    if not ref:
        return None, None
    storage = get_storage()
    if is_s3_ref(ref):
        return storage.local_path(ref), ref
    if settings.use_s3:
        from .storage import original_ref_for_cached
        original = original_ref_for_cached(ref)
        if original is not None:
            return storage.local_path(original), original
    return ref, None


def _publish_local_file(local_path: str, target_ref: str | None = None) -> str | None:
    """Upload a newly rendered local file to S3 and return its ref.
    Local mode: returns the path unchanged. Returns None when the
    file does not exist (nothing to publish). ``target_ref`` overrides
    the destination key — the re-render path needs it because
    ``rerender.py`` writes the new version next to the *cached* clip
    (``media/.s3cache/``), while the clip's S3 key must stay next to
    the original object (``media/project_<id>/clip_<id>_v<n>.mp4``);
    deriving the key from the local path would publish it under
    ``.s3cache/`` instead. Without ``target_ref`` the key is derived
    from the file's path relative to MEDIA_DIR (correct for first
    renders, which write straight under ``media/project_<id>/``)."""
    if not local_path or not os.path.exists(local_path):
        return None
    if not settings.use_s3:
        return local_path
    storage = get_storage()
    if target_ref is None:
        media_root = os.path.abspath(settings.media_dir)
        rel = os.path.relpath(os.path.abspath(local_path), media_root)
        target_ref = storage.make_ref("media", rel)
    storage.put_file(local_path, target_ref)
    try:
        os.remove(local_path)
    except OSError:
        logger.warning("Could not remove published local file %s",
                       local_path)
    return target_ref


def _s3_prepare(fn_name: str, args: tuple) -> dict:
    """Before a job runs in S3 mode: materialise its input files to
    the local cache and point the DB rows at them. Returns the
    original refs (``{}`` in local mode, or when nothing needed
    materialising) for ``_s3_finish`` to restore/publish afterwards.
    Keys: ``project_source`` (s3 ref or None), ``clip_path`` (s3 ref
    or None), ``clip_id`` / ``project_id`` for the finish step."""
    originals: dict = {}
    if not settings.use_s3:
        return originals
    db = SessionLocal()
    try:
        if fn_name == "run_pipeline":
            project_id = args[0]
            project = db.query(Project).get(project_id)
            if project is None:
                return originals
            local, orig = _materialize_path(project.source_path)
            if orig is not None:
                project.source_path = local
                db.commit()
                originals["project_source"] = orig
            originals["project_id"] = project_id
        elif fn_name == "run_rerender":
            clip_id = args[0]
            clip = db.query(Clip).get(clip_id)
            if clip is None:
                return originals
            project = db.query(Project).get(clip.project_id)
            if project is not None:
                local, orig = _materialize_path(project.source_path)
                if orig is not None:
                    project.source_path = local
                    db.commit()
                    originals["project_source"] = orig
            local, orig = _materialize_path(clip.path)
            if orig is not None:
                clip.path = local
                db.commit()
                originals["clip_path"] = orig
            originals["clip_id"] = clip_id
            originals["project_id"] = clip.project_id
    finally:
        db.close()
    return originals


def _s3_finish(fn_name: str, originals: dict) -> None:
    """After a job runs in S3 mode: publish newly rendered clips to
    S3, restore the input refs, and delete superseded S3 objects.
    Runs even when the job failed — a failed job must leave the rows
    pointing at the real stored files, not at cache copies."""
    if not settings.use_s3 or not originals:
        return
    storage = get_storage()
    db = SessionLocal()
    try:
        if fn_name == "run_pipeline":
            project_id = originals.get("project_id")
            if project_id is not None:
                for clip in db.query(Clip).filter(
                        Clip.project_id == project_id).all():
                    if clip.path and not is_s3_ref(clip.path):
                        ref = _publish_local_file(clip.path)
                        if ref is not None:
                            clip.path = ref
                project = db.query(Project).get(project_id)
                if project is not None and originals.get("project_source"):
                    project.source_path = originals["project_source"]
                db.commit()
        elif fn_name == "run_rerender":
            clip_id = originals.get("clip_id")
            clip = db.query(Clip).get(clip_id) if clip_id else None
            if clip is not None:
                old_ref = originals.get("clip_path")
                if clip.path and not is_s3_ref(clip.path):
                    # Success: the row points at the new local version.
                    # It lives next to the *cached* clip, so its key
                    # must be derived from the original object's
                    # directory, not from the local cache path (see
                    # _publish_local_file).
                    target_ref = None
                    if old_ref:
                        target_ref = (old_ref.rsplit("/", 1)[0] + "/"
                                      + os.path.basename(clip.path))
                    ref = _publish_local_file(clip.path, target_ref)
                    if ref is not None:
                        clip.path = ref
                        if old_ref and old_ref != ref:
                            storage.delete(old_ref)
                elif old_ref:
                    # Failed render: the row still points at the cached
                    # old version — point it back at the S3 object.
                    clip.path = old_ref
            project_id = originals.get("project_id")
            project = db.query(Project).get(project_id) \
                if project_id else None
            if project is not None and originals.get("project_source"):
                project.source_path = originals["project_source"]
            db.commit()
    except Exception:
        logger.exception("S3 publish/restore after job failed; DB rows "
                         "may still point at local cache paths")
        db.rollback()
    finally:
        db.close()


# ── Shared job execution (both dispatch modes) ───────────────────────────

def execute_job(job_id: int, fn, *args, **kwargs):
    """Run ``fn(job_id, *args, **kwargs)`` for one job row: claim it
    (``queued`` → ``running``), run it, and record a crash as
    ``failed`` with the error on the row. ``fn`` updates the job row
    itself (status/progress/error) via its own DB session; this
    wrapper only handles the claim, the crash path, and the S3
    materialise/publish around the run. Idempotent start: a task
    redelivered after the job already finished (``done``/``failed``)
    is skipped."""
    db = SessionLocal()
    try:
        job = db.query(Job).get(job_id)
        if job is None:
            return
        if job.status in ("done", "failed"):
            logger.info("Job %s already %s — skipping redelivery",
                        job_id, job.status)
            return
        job.status = "running"
        db.commit()
    finally:
        db.close()
    fn_name = getattr(fn, "__name__", "")
    originals = _s3_prepare(fn_name, args)
    try:
        fn(job_id, *args, **kwargs)
    except Exception:
        logger.exception("Job %s crashed", job_id)
        _mark_job_failed(job_id,
                         "Unexpected internal error — see server logs.")
    finally:
        _s3_finish(fn_name, originals)


def submit_job(job_id: int, fn, *args, **kwargs):
    """Dispatch ``fn(job_id, *args, **kwargs)`` for background
    execution. Celery mode (broker configured): send it to a worker
    — the session-factory argument is dropped, the Celery task
    supplies its own. In-process mode: the ThreadPoolExecutor, as
    before. Unknown functions fall back to the pool with a warning
    (only run_pipeline / run_rerender have Celery tasks)."""
    fn_name = getattr(fn, "__name__", "")
    if settings.celery_enabled:
        from .celery_app import dispatch_job  # lazy: avoids a cycle
        if dispatch_job(job_id, fn_name, args):
            return None
        logger.warning("No Celery task for %s — running in-process",
                       fn_name)
    return executor.submit(execute_job, job_id, fn, *args, **kwargs)


def recover_interrupted_jobs() -> int:
    """Celery-mode startup recovery: re-queue every job row still
    ``queued`` or ``running``. The broker may have lost the message
    (e.g. a Redis restart without persistence) while the DB row
    survived — the row is the source of truth, so a stuck row means
    the work never finished. Tasks skip themselves if the job already
    reached ``done``/``failed``, so a double delivery is harmless.
    Returns the number of jobs re-queued. In-process mode must NOT
    call this — use mark_stale_jobs_failed() instead."""
    if not settings.celery_enabled:
        return 0
    from .celery_app import dispatch_job  # lazy: avoids a cycle
    db = SessionLocal()
    try:
        stuck = db.query(Job).filter(
            Job.status.in_(["queued", "running"])).all()
        count = 0
        for job in stuck:
            fn_name = ("run_pipeline" if job.kind == "process"
                       else "run_rerender" if job.kind == "rerender"
                       else "")
            arg = (job.project_id if job.kind == "process"
                   else job.clip_id)
            if fn_name and arg is not None and dispatch_job(
                    job.id, fn_name, (arg,)):
                count += 1
            else:
                logger.warning("Could not re-queue job %s (kind=%s)",
                               job.id, job.kind)
        return count
    finally:
        db.close()
