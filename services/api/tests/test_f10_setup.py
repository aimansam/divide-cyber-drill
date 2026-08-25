"""F10.1 / F10.2: bootstrap-first-admin + admin user-creation endpoints.

These tests pin the contract:

  /setup (public, single-shot):
    * 201 + LoginResponse when no users exist.
    * 409 when at least one user exists (wizard treats this as
      "step 1 already complete").
    * 422 on bad body (password too short, sub empty, etc.).

  /users POST (admin-only):
    * 201 + UserPublic when admin creates a user.
    * 409 on duplicate sub.
    * 422 on bad role.
    * 401 for anonymous.
    * 403 for non-admin (red/blue/lead).

The setup endpoint is public so the chicken-and-egg cycle
breaks: the first admin can't have a token yet. The
single-shot guard prevents an attacker from abusing a leaked
URL to grow the user table after deployment.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.auth import sign_token
from app.db import models as db_models
from app.db.session import get_sessionmaker


def _admin_token(sub: str = "alice") -> str:
    return sign_token(sub, "admin", 3600)


def _red_token(sub: str = "red-1") -> str:
    return sign_token(sub, "red", 3600)


def _blue_token(sub: str = "blue-1") -> str:
    return sign_token(sub, "blue", 3600)


def _run_async(coro):
    """Fresh loop -- pytest-asyncio owns the main thread loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def _clean_db_after():
    """Truncate users (and anything else the F10 tests touch)
    after each test so the suite stays isolated.

    Mirrors the autouse fixtures in ``test_f9_drill_console.py``
    + ``test_f11_debrief.py``.
    """
    sm = get_sessionmaker()
    yield

    async def _cleanup():
        async with sm() as s:
            await s.execute(delete(db_models.TeamMembership))
            await s.execute(delete(db_models.Team))
            await s.execute(delete(db_models.Exercise))
            await s.execute(delete(db_models.TelemetryEvent))
            await s.execute(delete(db_models.FlagSubmission))
            await s.execute(delete(db_models.AuditLog))
            await s.execute(delete(db_models.Asset))
            await s.execute(delete(db_models.Run))
            await s.execute(delete(db_models.Scenario))
            await s.execute(delete(db_models.User))
            await s.commit()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_cleanup())
    except Exception:  # noqa: BLE001 -- best-effort
        pass
    finally:
        loop.close()


async def _seed_user(sub: str, role: str = "admin") -> None:
    """Insert a single user row so subsequent setup calls 409."""
    from app.services.users import create_user

    sm = get_sessionmaker()
    async with sm() as s:
        await create_user(s, sub=sub, password="test-pass-1234", role=role)
        await s.commit()


# --- /setup (first-admin bootstrap) ------------------------------------

def test_setup_creates_first_admin_and_returns_token(client):
    """Empty DB: setup creates an admin + mints a token."""
    r = client.post(
        "/api/v1/auth/setup",
        json={"sub": "first-admin", "password": "test-pass-1234"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["sub"] == "first-admin"
    assert body["role"] == "admin"
    assert body["token"]
    assert body["ttl_remaining_s"] > 0


def test_setup_rejects_second_call_with_409(client):
    """After any user exists, /setup is single-shot -- 409."""
    _run_async(_seed_user("already-exists"))

    r = client.post(
        "/api/v1/auth/setup",
        json={"sub": "second-admin", "password": "test-pass-1234"},
    )
    assert r.status_code == 409
    assert "single-shot" in r.text or "already exists" in r.text


def test_setup_rejects_short_password_with_422(client):
    """Password below 8 chars is rejected before hitting the DB."""
    r = client.post(
        "/api/v1/auth/setup",
        json={"sub": "shortie", "password": "abc"},
    )
    assert r.status_code == 422


def test_setup_rejects_empty_sub_with_422(client):
    """Empty sub is rejected by Pydantic's min_length=1."""
    r = client.post(
        "/api/v1/auth/setup",
        json={"sub": "", "password": "test-pass-1234"},
    )
    assert r.status_code == 422


# --- /users POST (admin user creation) -------------------------------

def test_create_user_as_admin_returns_201(client):
    """Admin can create a new user."""
    _run_async(_seed_user("admin-1", role="admin"))
    r = client.post(
        "/api/v1/auth/users",
        headers={"X-Divide-Token": _admin_token("admin-1")},
        json={"sub": "red-1", "password": "red-pass", "role": "red"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["sub"] == "red-1"
    assert body["role"] == "red"
    assert body["disabled"] is False
    # password_hash is NOT in the response.
    assert "password_hash" not in body
    assert "password" not in body


def test_create_user_duplicate_sub_returns_409(client):
    """Two inserts with the same sub -> 409."""
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user("red-1", role="red"))
    r = client.post(
        "/api/v1/auth/users",
        headers={"X-Divide-Token": _admin_token("admin-1")},
        json={"sub": "red-1", "password": "another", "role": "red"},
    )
    assert r.status_code == 409


def test_create_user_unknown_role_returns_422(client):
    """Typo in role -> 422 (no silent privilege escalation)."""
    _run_async(_seed_user("admin-1", role="admin"))
    r = client.post(
        "/api/v1/auth/users",
        headers={"X-Divide-Token": _admin_token("admin-1")},
        json={"sub": "oops", "password": "test-pass-1234", "role": "admine"},
    )
    assert r.status_code == 422


def test_create_user_anonymous_returns_401(client):
    """No token -> 401 (no leakage about whether setup ran)."""
    r = client.post(
        "/api/v1/auth/users",
        json={"sub": "x", "password": "y", "role": "red"},
    )
    assert r.status_code == 401


def test_create_user_red_cannot_create_returns_403(client):
    """A red team player can't grow the user table."""
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user("red-1", role="red"))
    r = client.post(
        "/api/v1/auth/users",
        headers={"X-Divide-Token": _red_token("red-1")},
        json={"sub": "blue-2", "password": "blue-pass", "role": "blue"},
    )
    assert r.status_code == 403


def test_create_user_blue_cannot_create_returns_403(client):
    """A blue team player also can't."""
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user("blue-1", role="blue"))
    r = client.post(
        "/api/v1/auth/users",
        headers={"X-Divide-Token": _blue_token("blue-1")},
        json={"sub": "blue-2", "password": "blue-pass", "role": "blue"},
    )
    assert r.status_code == 403


def test_created_user_can_login(client):
    """End-to-end: admin creates user -> user logs in -> token works."""
    _run_async(_seed_user("admin-1", role="admin"))
    r = client.post(
        "/api/v1/auth/users",
        headers={"X-Divide-Token": _admin_token("admin-1")},
        json={"sub": "red-1", "password": "red-pass-1234", "role": "red"},
    )
    assert r.status_code == 201

    # Now log in as the freshly-created user.
    login = client.post(
        "/api/v1/auth/login",
        json={"sub": "red-1", "password": "red-pass-1234"},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["sub"] == "red-1"
    assert body["role"] == "red"
