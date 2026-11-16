"""Real authentication — fastapi-users 15.0.0, JWT bearer tokens.

What this wires up (Phase 2, step 1):
  POST /auth/register      sign-up (email + password, min 8 chars)
  POST /auth/jwt/login     sign-in, returns {"access_token", "token_type"}
                           (OAuth2 password form: username=<email>)
  GET  /users/me           current user (email, id, flags)
  current_active_user      dependency used by every /api/* route

JWT: HS256, secret from SECRET_KEY (or AUTH_SECRET) env, lifetime
AUTH_TOKEN_LIFETIME_SECONDS (default 7 days). Logout is client-side:
the frontend discards the token; there is no server-side token list, so a
discarded token stays technically valid until it expires (max 7 days).
That is the documented trade-off of stateless JWTs — a token blocklist
would be a later step if needed.

Why a custom user-database adapter?
-----------------------------------
fastapi-users 15 ships only an *async* SQLAlchemy adapter, but this app
uses sync SQLAlchemy sessions everywhere (sync engine, ThreadPoolExecutor
jobs). Rather than running a second async engine against the same SQLite
file, this module provides a thin sync adapter implementing fastapi-users'
``BaseUserDatabase`` interface: its methods are ``async def`` (as the
interface requires) but run the existing sync session inside them. The
blocking calls are single-row SQLite/Postgres lookups — negligible for
this app's scale. If the app ever moves to an async engine, swap this
adapter for fastapi-users-db-sqlalchemy's ``SQLAlchemyUserDatabase`` and
delete it.

NOT in this step (explicitly): password reset, email verification,
OAuth (Google/GitHub), refresh tokens, token revocation/blocklist.
``is_verified`` exists on the model but nothing sets it yet — registration
does not send a verification email and login does not require verification.
"""
from __future__ import annotations

from typing import Optional

from fastapi_users import BaseUserManager, FastAPIUsers, schemas
from fastapi_users.authentication import (AuthenticationBackend,
                                          BearerTransport, JWTStrategy)
from fastapi_users.db import BaseUserDatabase
from fastapi_users.exceptions import (InvalidPasswordException,
                                      UserNotExists)
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import User

if not settings.secret_key or len(settings.secret_key) < 32:
    raise RuntimeError(
        "SECRET_KEY (or AUTH_SECRET) must be set to a random string of at "
        "least 32 characters. Generate one with "
        "`python3 -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
        "and put it in the local .env — never commit a real secret.")

MIN_PASSWORD_LENGTH = 8


class SyncSQLAlchemyUserDatabase(BaseUserDatabase[User, int]):
    """fastapi-users user DB backed by the app's sync SQLAlchemy session.

    OAuth methods are intentionally unimplemented — no OAuth in this step.
    """

    def __init__(self, session: Session):
        self.session = session

    async def get(self, id: int) -> Optional[User]:
        return self.session.get(User, id)

    async def get_by_email(self, email: str) -> Optional[User]:
        return self.session.query(User).filter(
            func.lower(User.email) == email.lower()).first()

    async def get_by_oauth_account(self, oauth: str, account_id: str):
        raise NotImplementedError("OAuth is not configured in this step.")

    async def create(self, create_dict: dict) -> User:
        user = User(**create_dict)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    async def update(self, user: User, update_dict: dict) -> User:
        for key, value in update_dict.items():
            setattr(user, key, value)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    async def delete(self, user: User) -> None:
        self.session.delete(user)
        self.session.commit()

    async def add_oauth_account(self, user: User, create_dict: dict):
        raise NotImplementedError("OAuth is not configured in this step.")

    async def update_oauth_account(self, user: User, oauth_account,
                                   update_dict: dict):
        raise NotImplementedError("OAuth is not configured in this step.")


class UserManager(BaseUserManager[User, int]):
    """Password policy: at least 8 characters (fastapi-users' default is
    no minimum at all). No other rules in this step."""

    def parse_id(self, value) -> int:
        """JWT ``sub`` is a string; user ids are ints. fastapi-users
        requires this override (its default raises NotImplementedError)."""
        return int(value)

    async def validate_password(self, password: str,
                                user: schemas.UC | User) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidPasswordException(
                reason=f"Password must be at least {MIN_PASSWORD_LENGTH} "
                       "characters long.")

    async def on_after_register(self, user: User, request=None) -> None:
        print(f"Registered new user: {user.email} (id={user.id})")

    async def on_after_login(self, user: User, request=None,
                             response=None) -> None:
        print(f"User logged in: {user.email} (id={user.id})")


async def get_user_manager():
    session = SessionLocal()
    try:
        yield UserManager(SyncSQLAlchemyUserDatabase(session))
    finally:
        session.close()


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=settings.secret_key,
        lifetime_seconds=settings.auth_token_lifetime_seconds)


bearer_transport = BearerTransport(tokenUrl="auth/jwt/login")

auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy)

fastapi_users = FastAPIUsers[User, int](get_user_manager, [auth_backend])

# Dependency for every protected route: 401 without a valid token,
# 401 also when the account is inactive.
current_active_user = fastapi_users.current_user(active=True)


# ── fastapi-users schemas (name is our extra field) ──────────────────────

class UserRead(schemas.BaseUser[int]):
    name: Optional[str] = None


class UserCreate(schemas.BaseUserCreate):
    name: Optional[str] = None


class UserUpdate(schemas.BaseUserUpdate):
    name: Optional[str] = None


async def seed_user_if_configured() -> None:
    """Startup seed (local dev/testing ONLY): if SEED_EMAIL and
    SEED_PASSWORD are both set, create that user if missing. Otherwise do
    nothing — no user is ever auto-created. Never set these in production.
    """
    email = settings.seed_email.strip()
    password = settings.seed_password
    if not email or not password:
        return
    async for manager in get_user_manager():
        try:
            existing = await manager.get_by_email(email)
        except UserNotExists:
            # fastapi-users' manager raises instead of returning None.
            existing = None
        if existing is not None:
            print(f"Seed user already exists: {email}")
            return
        try:
            user = await manager.create(
                UserCreate(email=email, password=password, name="Seed User"),
                safe=False)
        except InvalidPasswordException as exc:
            print(f"WARNING: seed user not created — password invalid: {exc}")
            return
        print(f"Seed user created (dev only): {user.email} (id={user.id})")
