"""Pydantic schemas for API requests/responses."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class YouTubeLinkRequest(BaseModel):
    url: str = Field(..., min_length=3, max_length=2048)


class ProjectOut(BaseModel):
    id: int
    title: str
    source_type: str
    source_url: str | None
    youtube_video_id: str | None
    thumbnail_url: str | None
    duration_sec: float | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: int
    project_id: int
    kind: str
    status: str
    progress: int
    error: str | None
    created_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class ClipOut(BaseModel):
    id: int
    project_id: int
    highlight_id: int | None
    title: str
    width: int
    height: int
    duration_sec: float | None
    file_size_bytes: int | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class HighlightOut(BaseModel):
    id: int
    project_id: int
    start_sec: float
    end_sec: float
    score: int
    reasons: list[str]
    title: str | None
    description: str | None
    hashtags: list[str]

    model_config = {"from_attributes": True}


class TranscriptOut(BaseModel):
    language: str | None
    full_text: str
    segments: list[dict]
