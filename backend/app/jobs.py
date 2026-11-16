"""Background jobs — Phase 1: a simple in-process threaded queue.

Honest limits: jobs die with the process, there are no retries across
restarts, and only 2 workers run at once. On startup, jobs left in
`queued`/`running` by a previous process are marked `failed`
("server restarted") — they are never silently re-run.

Path forward (see ARCHITECTURE.md §5): replace the executor with
Redis + Celery; the pipeline entrypoint (pipeline/runner.py) is already a
plain function of (project_id, session_factory) and moves unchanged.
Do NOT claim Celery/Redis are running — they are not.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .database import SessionLocal
from .models import Job

logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mmsn-job")


def mark_stale_jobs_failed() -> int:
    """Mark jobs orphaned by a previous process run as failed."""
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


def submit_job(job_id: int, fn, *args, **kwargs):
    """Submit fn(job_id, *args, **kwargs) to the pool. fn must update the
    job row itself (status/progress/error) via its own DB session."""
    def _wrapped():
        db = SessionLocal()
        try:
            job = db.query(Job).get(job_id)
            if job is None:
                return
            job.status = "running"
            db.commit()
        finally:
            db.close()
        try:
            fn(job_id, *args, **kwargs)
        except Exception:
            logger.exception("Job %s crashed", job_id)
            db = SessionLocal()
            try:
                job = db.query(Job).get(job_id)
                if job is not None and job.status == "running":
                    job.status = "failed"
                    job.error = "Unexpected internal error — see server logs."
                    job.finished_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()

    return executor.submit(_wrapped)


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
