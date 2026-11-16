"""Celery app — Redis-backed background workers (Phase 3).

Selected ONLY by ``CELERY_BROKER_URL`` (``REDIS_URL`` is accepted as
an alias — see ``config.py``). When it is unset this module still
imports, but ``celery_app`` is None and ``jobs.submit_job`` uses the
in-process ThreadPoolExecutor exactly as in Phase 1/2.

Run a worker (from the repo root, with the broker reachable):

    celery -A backend.app.celery_app worker --loglevel=info --concurrency=1

``--concurrency=1`` is deliberate: one pipeline job saturates the CPU
(Whisper + FFmpeg); run more worker *processes* (or machines) for
parallelism, not more threads in one worker.

Durability / recovery — job rows in the DB are the source of truth,
not the broker:
* The API process holds no job state. A backend restart does not
  touch running jobs: workers are separate processes and keep going,
  and on startup the backend re-queues any job rows still
  ``queued``/``running`` (``jobs.recover_interrupted_jobs``) in case
  the broker lost the message.
* Tasks use ``acks_late=True`` + ``reject_on_worker_lost=True``: a
  worker killed mid-task has the task redelivered to another worker.
  The task skips itself when the job row is already ``done``/``failed``
  (see ``jobs.execute_job``), so redelivery re-runs the pipeline from
  scratch. That re-run is NOT idempotent — a crashed attempt may have
  left partial clip rows behind (a known gap, see ARCHITECTURE.md §5).
  There is no automatic retry on a *failed* job (an exception marks
  the row ``failed``); re-processing is a deliberate user action
  (POST /api/projects/{id}/process again).
* No result backend is required: progress/status live on the job row
  and are polled via GET /api/jobs/{id}. ``CELERY_RESULT_BACKEND``
  defaults to the broker URL when set, and is only used if something
  asks Celery for a task result.

The worker needs the same environment as the backend: ``DATABASE_URL``
(the job rows), ``SECRET_KEY`` is NOT needed by the worker, but
``UPLOAD_DIR``/``MEDIA_DIR`` (or the S3 variables) and the Whisper
model must match, and FFmpeg must be on PATH. A worker that cannot
reach the DB or the broker fails loudly at job time — it never
silently falls back to the in-process queue.
"""
from __future__ import annotations

import logging

from .config import settings

logger = logging.getLogger(__name__)

try:
    from celery import Celery
except ImportError:  # celery not installed (local dev without it)
    Celery = None  # type: ignore[assignment]

# Task names by pipeline function name (jobs.submit_job dispatches on
# fn.__name__; the first positional arg after job_id is the id the
# task needs — project_id for run_pipeline, clip_id for run_rerender).
_TASK_BY_FN = {
    "run_pipeline": "mmsn.run_pipeline",
    "run_rerender": "mmsn.run_rerender",
}

celery_app = None
if settings.celery_enabled and Celery is not None:
    celery_app = Celery(
        "mmsn",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend_url or None,
    )
    celery_app.conf.update(
        # Redeliver a task whose worker died mid-run (see module docs).
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        # One job per worker process at a time (CPU-bound work).
        worker_prefetch_multiplier=1,
        # Keep retrying the broker at worker startup (Redis may not be
        # up yet when the worker starts).
        broker_connection_retry_on_startup=True,
        # Pipeline jobs run for minutes; no task time limit is set on
        # purpose — a long video must not be killed by a default.
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
    )


def dispatch_job(job_id: int, fn_name: str, args: tuple) -> bool:
    """Send a job to a Celery worker. ``args`` is the argument tuple
    ``submit_job`` received after ``job_id`` — only its first element
    (project_id / clip_id) is sent; the session factory is supplied
    by the task itself. Returns False when Celery is disabled or the
    function has no Celery task (caller falls back to the in-process
    pool). Raises RuntimeError when a broker is configured but the
    celery package is missing — a broken deploy must fail loudly,
    not silently run durable jobs in-process."""
    if not settings.celery_enabled:
        return False
    if celery_app is None:
        raise RuntimeError(
            "CELERY_BROKER_URL is set but the celery package is not "
            "installed. Run: pip install -r backend/requirements.txt")
    task_name = _TASK_BY_FN.get(fn_name)
    if task_name is None:
        return False
    celery_app.send_task(task_name, args=[job_id, args[0]])
    logger.info("Dispatched job %s to Celery task %s", job_id, task_name)
    return True


if celery_app is not None:
    from .database import SessionLocal  # noqa: E402
    from .jobs import execute_job  # noqa: E402
    from ..pipeline.rerender import run_rerender  # noqa: E402
    from ..pipeline.runner import run_pipeline  # noqa: E402

    @celery_app.task(name="mmsn.run_pipeline", bind=True,
                     acks_late=True, reject_on_worker_lost=True)
    def run_pipeline_task(self, job_id: int, project_id: int):
        """Celery entry point for POST /api/projects/{id}/process."""
        execute_job(job_id, run_pipeline, project_id, SessionLocal)

    @celery_app.task(name="mmsn.run_rerender", bind=True,
                     acks_late=True, reject_on_worker_lost=True)
    def run_rerender_task(self, job_id: int, clip_id: int):
        """Celery entry point for editor re-render / regenerate."""
        execute_job(job_id, run_rerender, clip_id, SessionLocal)
