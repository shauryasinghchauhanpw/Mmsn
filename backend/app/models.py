"""SQLAlchemy models — users, projects, jobs, transcripts, highlights,
clips, exports. SQLite for local dev, PostgreSQL in production
(same models, switch DATABASE_URL)."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        String, Text)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _now():
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=True)
    # fastapi-users fields (Phase 2, step 1). hashed_password is nullable
    # only so the pre-auth dev rows in an existing mmsn.db survive the
    # migration (see database.init_db) — every user created through
    # /auth/register always has one. Those old rows can never log in.
    hashed_password = Column(String(1024), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)
    projects = relationship("Project", back_populates="user")


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(500), nullable=False)
    # upload | youtube_link
    source_type = Column(String(32), nullable=False)
    source_url = Column(String(2048), nullable=True)
    youtube_video_id = Column(String(32), nullable=True)
    source_path = Column(String(1024), nullable=True)  # local file, if uploaded
    thumbnail_url = Column(String(2048), nullable=True)
    duration_sec = Column(Float, nullable=True)
    # uploaded | metadata_only | queued | processing | done | failed
    status = Column(String(32), default="uploaded", nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)
    user = relationship("User", back_populates="projects")
    jobs = relationship("Job", back_populates="project")
    clips = relationship("Clip", back_populates="project")
    highlights = relationship("Highlight", back_populates="project")


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    # For kind="rerender" jobs: the clip being re-rendered (NULL for
    # kind="process" jobs, which cover a whole project).
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=True)
    kind = Column(String(64), default="process", nullable=False)
    # queued | running | done | failed
    status = Column(String(32), default="queued", nullable=False)
    progress = Column(Integer, default=0, nullable=False)  # 0-100
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    project = relationship("Project", back_populates="jobs")


class Transcript(Base):
    __tablename__ = "transcripts"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    language = Column(String(16), nullable=True)
    full_text = Column(Text, nullable=False)
    # JSON: [{start, end, text, words: [{start, end, word}]}]
    segments_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)

    @property
    def segments(self):
        return json.loads(self.segments_json)


class Highlight(Base):
    __tablename__ = "highlights"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    start_sec = Column(Float, nullable=False)
    end_sec = Column(Float, nullable=False)
    score = Column(Integer, nullable=False)  # 0-100 virality score
    # Which scorer actually produced this highlight: "llm" only when an
    # LLM response did, otherwise "heuristic". Recorded by runner.py from
    # detect_highlights(); the UI shows exactly this value, so it must
    # never claim LLM scoring when the heuristic ran.
    scorer = Column(String(16), default="heuristic", nullable=False)
    reasons_json = Column(Text, nullable=False)  # JSON list of reason strings
    title = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    hashtags_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    project = relationship("Project", back_populates="highlights")

    @property
    def reasons(self):
        return json.loads(self.reasons_json)

    @property
    def hashtags(self):
        return json.loads(self.hashtags_json) if self.hashtags_json else []


class Clip(Base):
    __tablename__ = "clips"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    highlight_id = Column(Integer, ForeignKey("highlights.id"), nullable=True)
    title = Column(String(500), nullable=False)
    path = Column(String(1024), nullable=False)
    width = Column(Integer, default=1080, nullable=False)
    height = Column(Integer, default=1920, nullable=False)
    duration_sec = Column(Float, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    # rendering | ready | failed
    status = Column(String(32), default="rendering", nullable=False)
    # Editor (Phase 2, step 2): the clip's current edit parameters as JSON
    # (trim_start/trim_end relative to the highlight window, style,
    # framing_offset, volume, caption_overrides). Re-renders and
    # "regenerate" both read from here, so the editor's last state is the
    # render's source of truth.
    edit_params_json = Column(Text, nullable=True)
    # Render version, starting at 1. Each re-render writes
    # clip_{id}_v{n}.mp4 with n = version + 1 so browsers never serve a
    # stale cached file under the old URL.
    version = Column(Integer, default=1, nullable=False)
    # JPEG thumbnail frame set from the editor (NULL until the user picks
    # one); served by GET /api/clips/{id}/thumbnail.
    thumbnail_path = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    project = relationship("Project", back_populates="clips")

    @property
    def edit_params(self) -> dict:
        """Stored edit parameters, or {} for a never-edited clip."""
        if not self.edit_params_json:
            return {}
        try:
            return json.loads(self.edit_params_json)
        except (ValueError, TypeError):
            return {}

    @property
    def has_thumbnail(self) -> bool:
        return bool(self.thumbnail_path)


class Export(Base):
    __tablename__ = "exports"
    id = Column(Integer, primary_key=True)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=False)
    platform = Column(String(64), nullable=False)  # youtube_shorts | tiktok | reels
    path = Column(String(1024), nullable=True)
    status = Column(String(32), default="pending", nullable=False)
    created_at = Column(DateTime, default=_now, nullable=False)
