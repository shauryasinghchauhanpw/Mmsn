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
    clip_id: int | None
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
    version: int
    has_thumbnail: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ClipDetailOut(ClipOut):
    """Single-clip view for the editor: ClipOut plus the highlight window
    the clip was cut from (trim is relative to this window), the stored
    edit parameters, and the clip's absolute window in the source video."""
    highlight_start_sec: float | None
    highlight_end_sec: float | None
    highlight_duration_sec: float | None
    edit_params: dict


class CaptionGroupOut(BaseModel):
    index: int
    start_sec: float  # clip-relative (seconds into the current clip window)
    end_sec: float
    text: str


class CaptionOverrideIn(BaseModel):
    group_index: int = Field(..., ge=0)
    # New text for the whole caption group. Empty/whitespace-only text
    # removes that group's captions from the render.
    text: str = Field(..., max_length=500)


class ClipCaptionsOut(BaseModel):
    clip_id: int
    style: str
    groups: list[CaptionGroupOut]
    overrides: list[CaptionOverrideIn]
    # Absolute window (seconds into the source video) the groups cover.
    window_start_sec: float
    window_end_sec: float


class ReRenderRequest(BaseModel):
    """Editor re-render parameters. Every field is optional: omitted
    fields keep the clip's stored value (so a request can change just the
    volume, or just the trim). caption_overrides, when present, replaces
    the stored override list entirely."""
    trim_start: float | None = Field(None, ge=0)
    trim_end: float | None = Field(None, ge=0)
    caption_overrides: list[CaptionOverrideIn] | None = None
    style: str | None = None
    framing_offset: float | None = Field(None, ge=-1, le=1)
    volume: float | None = Field(None, ge=0.25, le=2.0)


class ThumbnailOut(BaseModel):
    clip_id: int
    t: float
    thumbnail_url: str


class HighlightOut(BaseModel):
    id: int
    project_id: int
    start_sec: float
    end_sec: float
    score: int
    # "llm" only when an LLM response actually produced this highlight,
    # otherwise "heuristic". The UI shows exactly this value.
    scorer: str = "heuristic"
    reasons: list[str]
    title: str | None
    description: str | None
    hashtags: list[str]

    model_config = {"from_attributes": True}


class TranscriptOut(BaseModel):
    language: str | None
    full_text: str
    segments: list[dict]
