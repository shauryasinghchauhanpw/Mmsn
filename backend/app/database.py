"""Database setup. SQLite for local dev (file next to the backend),
PostgreSQL in production — same models, DATABASE_URL switch."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings
from .models import Base

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_or_create_dev_user(db):
    """Phase 1 has no real auth: a single placeholder dev user owns
    everything. Real auth is a later phase — see ARCHITECTURE.md."""
    from .models import User
    user = db.query(User).filter(User.email == "dev@localhost").first()
    if user is None:
        user = User(email="dev@localhost", name="Dev User")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
