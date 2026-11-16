"""MMSN Clipper backend — database setup + lightweight migration.

SQLite for local dev (file next to the backend), PostgreSQL in production —
same models, DATABASE_URL switch.

Phase 2, step 1 (auth) notes
----------------------------
* The old Phase 1 placeholder ``get_or_create_dev_user`` is GONE. No request
  path creates a user any more; every API route requires a JWT for a real
  user (see ``auth.py``). The only user creation paths are
  ``POST /auth/register`` and the optional ``SEED_EMAIL``/``SEED_PASSWORD``
  startup seed (local dev only).
* ``init_db()`` migrates an existing dev ``mmsn.db`` in place: Phase 1
  databases have a ``users`` table without the fastapi-users columns, and
  ``create_all()`` never adds columns to an existing table. The migration
  below adds the four missing columns with ``ALTER TABLE`` (SQLite and
  Postgres both accept this form). It only ever ADDS columns — no data is
  dropped or rewritten. Pre-auth rows (the ``dev@localhost`` test user)
  keep their projects but get ``hashed_password = NULL``, so they can never
  log in; their projects are therefore invisible to every real account
  (ownership is enforced per user — see ``main.py``). Delete/recreate that
  test data if you want it back.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings
from .models import Base

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Columns added after a table's first creation, by table name.
# create_all() never adds columns to an existing table, so init_db()
# adds any missing ones with ALTER TABLE (valid SQLite + Postgres).
# Only ever ADDS columns — no data is dropped or rewritten.
_TABLE_COLUMNS = {
    "users": {
        # fastapi-users fields (Phase 2, step 1).
        "hashed_password": "VARCHAR(1024)",
        "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
        "is_superuser": "BOOLEAN NOT NULL DEFAULT FALSE",
        "is_verified": "BOOLEAN NOT NULL DEFAULT FALSE",
    },
    "clips": {
        # Editor fields (Phase 2, step 2).
        "edit_params_json": "TEXT",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "thumbnail_path": "VARCHAR(1024)",
    },
    "jobs": {
        # Editor re-render jobs point at their clip (Phase 2, step 2).
        "clip_id": "INTEGER",
    },
    "highlights": {
        # Which scorer produced the highlight (Phase 2, step 3).
        "scorer": "VARCHAR(16) NOT NULL DEFAULT 'heuristic'",
    },
}


def _ensure_table_columns(table: str, columns: dict) -> None:
    """Add any missing columns to an existing table. Fresh databases
    already have them via create_all(); this only fires for databases
    created before the columns existed."""
    existing = {c["name"] for c in inspect(engine).get_columns(table)}
    missing = {n: ddl for n, ddl in columns.items() if n not in existing}
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
    print(f"Migration: added missing columns to {table}: "
          f"{', '.join(missing)}")


def _ensure_user_auth_columns() -> None:
    """Backwards-compatible name — now migrates every table in
    _TABLE_COLUMNS (users, clips, jobs)."""
    for table, columns in _TABLE_COLUMNS.items():
        _ensure_table_columns(table, columns)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_user_auth_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
