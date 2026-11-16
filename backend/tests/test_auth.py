"""Auth tests — converted from /tmp/test_auth.py (Phase 2, step 1).

Covers: unauthenticated 401s on every protected route, register/login
flow and validation, wrong-password rejection, per-user ownership
(other users' resources return 404, never 403 — existence is not
leaked), the YouTube endpoint's auth gate + not-configured path, and
the public /health endpoint.
"""
import pytest
from uuid import uuid4

UNAUTH_ENDPOINTS = [
    ("GET", "/api/projects"),
    ("GET", "/api/projects/1"),
    ("POST", "/api/projects/1/process"),
    ("GET", "/api/jobs/1"),
    ("GET", "/api/projects/1/clips"),
    ("GET", "/api/projects/1/highlights"),
    ("GET", "/api/projects/1/transcript"),
    ("GET", "/api/clips/1/download"),
    ("GET", "/api/clips/1"),
    ("GET", "/api/clips/1/captions"),
    ("POST", "/api/clips/1/re-render"),
    ("POST", "/api/clips/1/regenerate"),
    ("POST", "/api/clips/1/thumbnail?t=3"),
    ("GET", "/api/clips/1/thumbnail"),
    ("POST", "/api/projects/youtube"),
    ("GET", "/users/me"),
]


@pytest.mark.parametrize("method,path", UNAUTH_ENDPOINTS)
def test_unauthenticated_requests_return_401(client, method, path):
    r = client.request(method, path)
    assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["youtube_api_configured"] is False  # no key in test env
    assert body["llm_scoring_configured"] is False
    assert body["whisper_model"] == "tiny"


def test_register_login_and_me(client):
    email = "flow-" + uuid4().hex[:8] + "@example.com"
    r = client.post("/auth/register", json={
        "email": email, "password": "correct-horse-1", "name": "Flow"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == email
    assert r.json()["name"] == "Flow"
    assert r.json()["is_active"] is True
    assert r.json()["is_superuser"] is False

    r = client.post("/auth/jwt/login",
                    data={"username": email, "password": "correct-horse-1"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    assert token and r.json()["token_type"] == "bearer"

    r = client.get("/users/me",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == email


def test_duplicate_register_returns_400(client, alice):
    # `alice` is already registered; re-registering the same email fails.
    # (We recover her email from /users/me.)
    me = client.get("/users/me", headers=alice).json()
    r = client.post("/auth/register", json={
        "email": me["email"], "password": "correct-horse-1"})
    assert r.status_code == 400
    assert "REGISTER_USER_ALREADY_EXISTS" in r.text


def test_short_password_returns_400(client):
    r = client.post("/auth/register", json={
        "email": "short-" + uuid4().hex[:8]
                 + "@example.com",
        "password": "abc"})
    assert r.status_code == 400


def test_invalid_email_returns_422(client):
    r = client.post("/auth/register", json={
        "email": "not-an-email", "password": "correct-horse-1"})
    assert r.status_code == 422


def test_wrong_password_rejected(client, alice):
    me = client.get("/users/me", headers=alice).json()
    r = client.post("/auth/jwt/login",
                    data={"username": me["email"],
                          "password": "wrong-password"})
    # fastapi-users returns 400 LOGIN_BAD_CREDENTIALS (documented
    # behaviour), not 401.
    assert r.status_code == 400
    assert "LOGIN_BAD_CREDENTIALS" in r.text


def test_unknown_user_login_rejected(client):
    r = client.post("/auth/jwt/login",
                    data={"username": "nobody@example.com",
                          "password": "correct-horse-1"})
    assert r.status_code == 400
    assert "LOGIN_BAD_CREDENTIALS" in r.text


def test_upload_and_ownership(client, alice, bob, test_video):
    """Alice uploads; Bob must not see the project anywhere (404)."""
    with open(test_video, "rb") as f:
        r = client.post("/api/projects/upload", headers=alice,
                        files={"file": ("test_video.mp4", f, "video/mp4")})
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["status"] == "uploaded"
    assert abs(project["duration_sec"] - 65.87) < 1.0
    pid = project["id"]

    # Alice sees her own project; Bob's list excludes it.
    r = client.get(f"/api/projects/{pid}", headers=alice)
    assert r.status_code == 200
    r = client.get("/api/projects", headers=bob)
    assert r.status_code == 200
    assert all(p["id"] != pid for p in r.json())

    # Bob gets 404 (not 403) on every Alice-owned resource.
    for method, path in [
            ("GET", f"/api/projects/{pid}"),
            ("POST", f"/api/projects/{pid}/process"),
            ("GET", f"/api/projects/{pid}/clips"),
            ("GET", f"/api/projects/{pid}/highlights"),
            ("GET", f"/api/projects/{pid}/transcript")]:
        r = client.request(method, path, headers=bob)
        assert r.status_code == 404, f"bob {method} {path} -> {r.status_code}"

    # Missing job ids are 404 for everyone (no leak, no crash).
    for headers in (alice, bob):
        r = client.get("/api/jobs/999999", headers=headers)
        assert r.status_code == 404


def test_youtube_endpoint_auth_and_not_configured(client, alice):
    # Authenticated, valid URL, no API key configured -> 501 with the
    # not-configured code (auth passed, then the not-configured path).
    r = client.post("/api/projects/youtube", headers=alice, json={
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert r.status_code == 501, r.text
    assert r.json()["detail"]["code"] == "youtube_api_not_configured"

    # Non-YouTube URL -> 400, before any API-key check.
    r = client.post("/api/projects/youtube", headers=alice, json={
        "url": "https://example.com/not-a-video"})
    assert r.status_code == 400

    # Missing URL -> 422 (pydantic validation).
    r = client.post("/api/projects/youtube", headers=alice, json={})
    assert r.status_code == 422
