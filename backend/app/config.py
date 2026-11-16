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
    cors_origins: list = field(default_factory=lambda: [
        o.strip() for o in os.environ.get(
            "CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
    ])

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
