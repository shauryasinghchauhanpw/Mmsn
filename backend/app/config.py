"""MMSN Clipper backend — configuration from environment variables.

No real secrets live in the repo: copy .env.example to .env and fill in keys
there. Every key here is optional; missing keys disable the feature that
needs them, with a clear message — never a fake result.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()  # .env (gitignored) -> os.environ; .env.example documents keys


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


_X264_PRESETS = frozenset({
    "ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
    "slow", "slower", "veryslow", "placebo",
})


def _render_preset() -> str:
    preset = os.environ.get("RENDER_PRESET", "veryfast").strip().lower()
    return preset if preset in _X264_PRESETS else "veryfast"


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DATABASE_URL", "sqlite:///./mmsn.db"))
    upload_dir: str = field(default_factory=lambda: os.environ.get(
        "UPLOAD_DIR", "./uploads"))
    media_dir: str = field(default_factory=lambda: os.environ.get(
        "MEDIA_DIR", "./media"))
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 2048))
    max_video_seconds: int = field(default_factory=lambda: _int("MAX_VIDEO_SECONDS", 14400))
    whisper_model: str = field(default_factory=lambda: os.environ.get(
        "WHISPER_MODEL", "tiny"))
    whisper_device: str = field(default_factory=lambda: os.environ.get(
        "WHISPER_DEVICE", "cpu"))
    whisper_compute_type: str = field(default_factory=lambda: os.environ.get(
        "WHISPER_COMPUTE_TYPE", "int8"))
    # ── Transcription provider ──────────────────────────────────────────
    # "local" (default): faster-whisper on this machine — needs ~1 GB
    # RAM for the tiny model. "groq": Groq's hosted Whisper
    # large-v3-turbo API — free plan, no card, word-level timestamps
    # (see backend/pipeline/groq_transcribe.py). Groq is what makes the
    # no-card Render free deploy work: with transcription offloaded,
    # the backend only needs RAM for FastAPI + FFmpeg + OpenCV, which
    # fits in 512 MB. Audio is sent to Groq's API in groq mode.
    transcription_provider: str = field(default_factory=lambda: os.environ.get(
        "TRANSCRIPTION_PROVIDER", "local").strip().lower())
    groq_api_key: str = field(default_factory=lambda: os.environ.get(
        "GROQ_API_KEY", ""))
    groq_model: str = field(default_factory=lambda: os.environ.get(
        "GROQ_MODEL", "whisper-large-v3-turbo"))
    groq_base_url: str = field(default_factory=lambda: os.environ.get(
        "GROQ_BASE_URL", "https://api.groq.com/openai/v1"))
    # Long audio is split into chunks of at most this many seconds
    # (and ~20 MB each) for Groq's 25 MB/file cap.
    groq_max_chunk_seconds: int = field(
        default_factory=lambda: _int("GROQ_MAX_CHUNK_SECONDS", 600))
    # ── Render preset (x264) ────────────────────────────────────────────
    # "veryfast" (default) is the quality/speed balance from Phase 1.
    # It is also a MEMORY knob: at 1080x1920 the render child peaks at
    # ~418 MB with "veryfast" but ~210 MB with "ultrafast" (measured
    # 2026-11-16). The Render free deploy (512 MB) sets "ultrafast" so
    # a job fits alongside the backend process; anything else keeps
    # "veryfast". Unknown values fall back to "veryfast" — a typo must
    # never reach FFmpeg as an invalid preset.
    render_preset: str = field(default_factory=lambda: _render_preset())
    # ── Face tracking ───────────────────────────────────────────────────
    # On (default): YuNet face detection + smoothing per clip, so the
    # 9:16 crop follows the speaker. It decodes video frames in-process
    # and costs ~180 MB of peak RAM — the single biggest in-process
    # cost. Off (FACE_TRACKING=0): the centre crop is used instead
    # (the same fallback as "no face found"). The Render free deploy
    # (512 MB) turns it off so a job fits next to the render child.
    face_tracking: bool = field(
        default_factory=lambda: _bool("FACE_TRACKING", True))
    clips_per_project: int = field(default_factory=lambda: _int("CLIPS_PER_PROJECT", 3))
    clip_min_seconds: int = field(default_factory=lambda: _int("CLIP_MIN_SECONDS", 15))
    clip_max_seconds: int = field(default_factory=lambda: _int("CLIP_MAX_SECONDS", 60))
    youtube_api_key: str = field(default_factory=lambda: os.environ.get(
        "YOUTUBE_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.environ.get(
        "OPENAI_API_KEY", ""))
    openai_base_url: str = field(default_factory=lambda: os.environ.get(
        "OPENAI_BASE_URL", "https://api.openai.com/v1"))
    openai_model: str = field(default_factory=lambda: os.environ.get(
        "OPENAI_MODEL", "gpt-4o-mini"))
    hf_token: str = field(default_factory=lambda: os.environ.get("HF_TOKEN", ""))
    # ── Production hardening (Phase 3) ──────────────────────────────────
    # Storage backend: "local" (default — files under UPLOAD_DIR/MEDIA_DIR,
    # exactly as before) or "s3" (S3-compatible object storage, see
    # backend/app/storage.py). S3 mode is selected ONLY by setting
    # STORAGE_BACKEND=s3; every S3 variable below is ignored otherwise,
    # so local dev keeps working with no extra setup.
    storage_backend: str = field(default_factory=lambda: os.environ.get(
        "STORAGE_BACKEND", "local").strip().lower())
    s3_endpoint_url: str = field(default_factory=lambda: os.environ.get(
        "S3_ENDPOINT_URL", ""))
    s3_bucket: str = field(default_factory=lambda: os.environ.get(
        "S3_BUCKET", ""))
    s3_access_key: str = field(default_factory=lambda: os.environ.get(
        "S3_ACCESS_KEY", ""))
    s3_secret_key: str = field(default_factory=lambda: os.environ.get(
        "S3_SECRET_KEY", ""))
    s3_region: str = field(default_factory=lambda: os.environ.get(
        "S3_REGION", "us-east-1"))
    # How long a presigned S3 download URL stays valid (seconds).
    s3_presigned_expiry_seconds: int = field(
        default_factory=lambda: _int("S3_PRESIGNED_EXPIRY_SECONDS", 3600))
    # ── Background jobs: Celery + Redis (Phase 3) ───────────────────────
    # CELERY_BROKER_URL is the switch. When it is unset (default) the
    # Phase 1 in-process ThreadPoolExecutor runs jobs, exactly as before.
    # Set it to a Redis URL (e.g. redis://localhost:6379/0) to hand jobs
    # to Celery workers instead. REDIS_URL is accepted as an alias.
    # CELERY_RESULT_BACKEND defaults to the broker URL when unset.
    celery_broker_url: str = field(default_factory=lambda: os.environ.get(
        "CELERY_BROKER_URL", os.environ.get("REDIS_URL", "")))
    celery_result_backend: str = field(default_factory=lambda: os.environ.get(
        "CELERY_RESULT_BACKEND", ""))
    # Auth (Phase 2, step 1): JWT secret. SECRET_KEY is the primary name;
    # AUTH_SECRET is accepted as an alias. Must be a long random string —
    # auth.py refuses to start with a missing/short one. Never commit a
    # real value; generate one into the local .env only (see .env.example).
    secret_key: str = field(default_factory=lambda: os.environ.get(
        "SECRET_KEY", os.environ.get("AUTH_SECRET", "")))
    # JWT lifetime in seconds. Default 7 days (604800).
    auth_token_lifetime_seconds: int = field(default_factory=lambda: _int(
        "AUTH_TOKEN_LIFETIME_SECONDS", 7 * 24 * 3600))
    # Optional seed/dev account, created on startup only if BOTH are set
    # (local dev/testing only — never set in production). No user is
    # auto-created when these are absent.
    seed_email: str = field(default_factory=lambda: os.environ.get(
        "SEED_EMAIL", ""))
    seed_password: str = field(default_factory=lambda: os.environ.get(
        "SEED_PASSWORD", ""))
    cors_origins: list = field(default_factory=lambda: [
        o.strip() for o in os.environ.get(
            "CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
    ])

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def use_s3(self) -> bool:
        """True only when STORAGE_BACKEND=s3. Any other value (including
        a typo) falls back to local storage — a misspelled backend must
        never silently send files somewhere unexpected."""
        return self.storage_backend == "s3"

    @property
    def celery_enabled(self) -> bool:
        """True only when a broker URL is configured. Unset = the
        in-process queue, exactly as in Phase 1/2."""
        return bool(self.celery_broker_url)

    @property
    def celery_result_backend_url(self) -> str:
        """Result backend: explicit CELERY_RESULT_BACKEND, else the
        broker URL, else '' (no result backend — job state lives in
        the DB, so Celery results are only a convenience)."""
        return self.celery_result_backend or self.celery_broker_url

    @property
    def database_dialect(self) -> str:
        """'sqlite' or 'postgresql' (or whatever SQLAlchemy URL scheme
        was given), for engine options and /health reporting."""
        return self.database_url.split("://", 1)[0].split("+", 1)[0]


settings = Settings()
