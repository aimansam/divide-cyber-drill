"""F9.4: toggle-disabled endpoint + RBAC.

These tests pin the contract:

  * 200 + UserPublic when admin toggles an enabled user
    (disabled: false -> true).
  * 200 + UserPublic when admin toggles again (true -> false).
  * 404 when the user doesn't exist.
  * 401 anonymous.
  * 403 for non-admin (red/blue/lead).

We seed one admin + one red user per test (per-test DB cleanup
autouse fixture, mirroring the F10 / F11 pattern).
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


def _lead_token(sub: str = "lead-1") -> str:
    return sign_token(sub, "lead", 3600)


def _run_async(coro):
    """Fresh loop -- pytest-asyncio owns the main-thread loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def _clean_db_after():
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


async def _seed_user(sub: str, role: str) -> None:
    from app.services.users import create_user

    sm = get_sessionmaker()
    async with sm() as s:
        await create_user(s, sub=sub, password="test-pass-1234", role=role)
        await s.commit()


async def _seed_user_disabled(sub: str, role: str, *, disabled: bool) -> None:
    """Seed a user with an explicit disabled flag (for the
    "already disabled -> enabled" toggle case)."""
    from sqlalchemy import select

    from app.services.users import hash_password

    sm = get_sessionmaker()
    async with sm() as s:
        u = db_models.User(
            sub=sub,
            password_hash=hash_password("test-pass-1234"),
            role=role,
            disabled=disabled,
        )
        s.add(u)
        await s.commit()


# --- happy paths -------------------------------------------------------

def test_admin_toggles_enabled_user_to_disabled(client):
    """A fresh user starts enabled. The toggle flips to disabled."""
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user("red-1", role="red"))

    r = client.post(
        "/api/v1/auth/users/red-1/toggle-disabled",
        headers={"X-Divide-Token": _admin_token("admin-1")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sub"] == "red-1"
    assert body["disabled"] is True
    assert body["role"] == "red"


def test_admin_toggles_disabled_user_to_enabled(client):
    """A second toggle flips back to enabled."""
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user_disabled("red-1", role="red", disabled=True))

    r = client.post(
        "/api/v1/auth/users/red-1/toggle-disabled",
        headers={"X-Divide-Token": _admin_token("admin-1")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["disabled"] is False


def test_admin_toggles_returns_no_password_hash(client):
    """UserPublic shape -- password_hash is never leaked."""
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user("red-1", role="red"))

    r = client.post(
        "/api/v1/auth/users/red-1/toggle-disabled",
        headers={"X-Divide-Token": _admin_token("admin-1")},
    )
    body = r.json()
    assert "password_hash" not in body
    assert "password" not in body


# --- failure paths ------------------------------------------------------

def test_toggle_unknown_user_returns_404(client):
    _run_async(_seed_user("admin-1", role="admin"))
    r = client.post(
        "/api/v1/auth/users/never-existed/toggle-disabled",
        headers={"X-Divide-Token": _admin_token("admin-1")},
    )
    assert r.status_code == 404
    assert "never-existed" in r.text


def test_toggle_anonymous_returns_401(client):
    r = client.post("/api/v1/auth/users/anyone/toggle-disabled")
    assert r.status_code == 401


def test_toggle_red_cannot_returns_403(client):
    """A red team player can't disable another account."""
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user("red-1", role="red"))
    r = client.post(
        "/api/v1/auth/users/red-1/toggle-disabled",
        headers={"X-Divide-Token": _red_token("red-1")},
    )
    assert r.status_code == 403


def test_toggle_blue_cannot_returns_403(client):
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user("blue-1", role="blue"))
    r = client.post(
        "/api/v1/auth/users/blue-1/toggle-disabled",
        headers={"X-Divide-Token": _blue_token("blue-1")},
    )
    assert r.status_code == 403


def test_toggle_lead_cannot_returns_403(client):
    """Lead isn't admin -- the toggle is admin-only."""
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user("lead-1", role="lead"))
    r = client.post(
        "/api/v1/auth/users/lead-1/toggle-disabled",
        headers={"X-Divide-Token": _lead_token("lead-1")},
    )
    assert r.status_code == 403


# --- end-to-end: toggle + login flow ----------------------------------

def test_disabled_user_cannot_login_after_toggle(client):
    """End-to-end: admin disables a user -> login fails (401)."""
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user("red-1", role="red"))

    # Login works before the toggle.
    r1 = client.post(
        "/api/v1/auth/login",
        json={"sub": "red-1", "password": "test-pass-1234"},
    )
    assert r1.status_code == 200

    # Admin disables the user.
    r2 = client.post(
        "/api/v1/auth/users/red-1/toggle-disabled",
        headers={"X-Divide-Token": _admin_token("admin-1")},
    )
    assert r2.status_code == 200
    assert r2.json()["disabled"] is True

    # Login now fails (the auth path checks disabled too).
    r3 = client.post(
        "/api/v1/auth/login",
        json={"sub": "red-1", "password": "test-pass-1234"},
    )
    # 401 -- the login router returns the same generic message
    # regardless of whether the password is wrong or the
    # account is disabled (no enumeration oracle). We just
    # assert non-200.
    assert r3.status_code == 401


def test_admin_can_re_enable_user_via_second_toggle(client):
    """Toggle is reversible -- admin can re-enable."""
    _run_async(_seed_user("admin-1", role="admin"))
    _run_async(_seed_user_disabled("red-1", role="red", disabled=True))

    # First toggle -> enabled.
    r1 = client.post(
        "/api/v1/auth/users/red-1/toggle-disabled",
        headers={"X-Divide-Token": _admin_token("admin-1")},
    )
    assert r1.json()["disabled"] is False

    # Second toggle -> disabled again.
    r2 = client.post(
        "/api/v1/auth/users/red-1/toggle-disabled",
        headers={"X-Divide-Token": _admin_token("admin-1")},
    )
    assert r2.json()["disabled"] is True
