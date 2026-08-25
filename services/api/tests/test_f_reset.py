"""Tests for the password-reset flow (F-reset-ux).

Endpoints covered:

  POST /api/v1/auth/forgot-password
    202 always. Mints a token if the user exists.

  POST /api/v1/auth/reset-password
    204 on success. 401 on bad token (generic).

  POST /api/v1/auth/users/{sub}/issue-reset
    200 with magic_link. 401/403 without admin token.

Contract checks:

  * forgot-password doesn't enumerate (same response shape for
    existing + non-existing subs).
  * The admin endpoint requires an admin token.
  * The reset endpoint actually changes the password and lets the
    user log in.
  * Single-use semantics: a token used once is invalidated.
  * Expired tokens are rejected.
  * Mismatched sub + token pairs are rejected with the generic
    401 message.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import models as db_models


# --- helpers --------------------------------------------------------------


def _bootstrap_admin(
    client: TestClient, *, sub: str = "alice", password: str = "oldpass123"
) -> None:
    """Create an admin via the setup endpoint (empty DB only)."""
    resp = client.post(
        "/api/v1/auth/setup", json={"sub": sub, "password": password}
    )
    assert resp.status_code == 201, resp.text


def _login(client: TestClient, sub: str, password: str) -> str:
    """Sign in and return the bearer token."""
    resp = client.post(
        "/api/v1/auth/login", json={"sub": sub, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _sync_session():
    """Sync SQLAlchemy session bound to the same DB the test client
    uses. Needed for reading the token column back after the
    ``forgot-password`` POST (the async session fixture is for
    HTTP-handler tests, not arbitrary ORM reads)."""
    url = os.environ.get("DIVIDE_DB_URL", "sqlite+aiosqlite:///./test.sqlite")
    sync_url = url
    if "+aiosqlite" in url:
        sync_url = url.replace("+aiosqlite", "")
    elif "+asyncpg" in url:
        sync_url = url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url, future=True)
    Sm = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Sm()


def _get_reset_token(sub: str) -> str:
    with _sync_session() as s:
        row = s.execute(
            select(db_models.User).where(db_models.User.sub == sub)
        ).scalar_one()
        assert row.reset_token is not None, f"no reset token for sub={sub!r}"
        return row.reset_token


def _backdate_token(sub: str, *, hours: int = 1) -> None:
    with _sync_session() as s:
        row = s.execute(
            select(db_models.User).where(db_models.User.sub == sub)
        ).scalar_one()
        row.reset_token_expires_at = datetime.now(UTC) - timedelta(
            hours=hours
        )
        s.commit()


@pytest.fixture(autouse=True)
def _clean_users_table():
    """Reset the users table before each test.

    The conftest's session-scoped SQLite DB is shared across tests,
    so without this each test sees leftover rows from the previous
    one and ``POST /auth/setup`` 409s. We truncate via the sync
    session (the test client uses async; both hit the same file).
    """
    with _sync_session() as s:
        s.execute(db_models.User.__table__.delete())
        s.commit()
    yield


# --- POST /auth/forgot-password -------------------------------------------


class TestForgotPassword:
    """Forgot-password must not enumerate."""

    def test_unknown_sub_returns_202(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/forgot-password", json={"sub": "ghost"}
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["ok"] is True
        assert "admin" in body["message"].lower()

    def test_known_sub_writes_token(self, client: TestClient) -> None:
        _bootstrap_admin(client, sub="resetuser", password="hunter22")
        resp = client.post(
            "/api/v1/auth/forgot-password", json={"sub": "resetuser"}
        )
        assert resp.status_code == 202
        with _sync_session() as s:
            row = s.execute(
                select(db_models.User).where(
                    db_models.User.sub == "resetuser"
                )
            ).scalar_one()
            assert row.reset_token is not None
            assert len(row.reset_token) >= 32
            assert row.reset_token_expires_at is not None

    def test_unknown_sub_does_not_create_user(
        self, client: TestClient
    ) -> None:
        before = client.get("/api/v1/auth/users")
        n_before = len(before.json())
        client.post(
            "/api/v1/auth/forgot-password", json={"sub": "phantom"}
        )
        after = client.get("/api/v1/auth/users")
        assert len(after.json()) == n_before

    def test_empty_sub_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/auth/forgot-password", json={"sub": ""}
        )
        # pydantic Field(min_length=1) -> 422.
        assert resp.status_code == 422


# --- POST /auth/reset-password --------------------------------------------


class TestResetPassword:
    """reset-password consumes a token + sets the new password."""

    def test_happy_path(self, client: TestClient) -> None:
        _bootstrap_admin(client, sub="bob", password="hunter22")
        client.post(
            "/api/v1/auth/forgot-password", json={"sub": "bob"}
        )
        token = _get_reset_token("bob")

        r = client.post(
            "/api/v1/auth/reset-password",
            json={
                "sub": "bob",
                "token": token,
                "new_password": "freshpass123",
            },
        )
        assert r.status_code == 204

        # Old password rejected.
        old = client.post(
            "/api/v1/auth/login", json={"sub": "bob", "password": "hunter22"}
        )
        assert old.status_code == 401

        # New password accepted.
        new = client.post(
            "/api/v1/auth/login",
            json={"sub": "bob", "password": "freshpass123"},
        )
        assert new.status_code == 200

    def test_token_is_single_use(self, client: TestClient) -> None:
        _bootstrap_admin(client, sub="carol", password="hunter22")
        client.post(
            "/api/v1/auth/forgot-password", json={"sub": "carol"}
        )
        token = _get_reset_token("carol")

        r1 = client.post(
            "/api/v1/auth/reset-password",
            json={
                "sub": "carol",
                "token": token,
                "new_password": "firstpass123",
            },
        )
        assert r1.status_code == 204

        # Same token replayed -> 401.
        r2 = client.post(
            "/api/v1/auth/reset-password",
            json={
                "sub": "carol",
                "token": token,
                "new_password": "secondpass123",
            },
        )
        assert r2.status_code == 401
        assert r2.json()["detail"] == "invalid or expired reset token"

        # Token columns are NULL after a successful reset.
        with _sync_session() as s:
            row = s.execute(
                select(db_models.User).where(
                    db_models.User.sub == "carol"
                )
            ).scalar_one()
            assert row.reset_token is None
            assert row.reset_token_expires_at is None

    def test_mismatched_sub_returns_401(self, client: TestClient) -> None:
        _bootstrap_admin(client, sub="dave", password="hunter22")
        client.post(
            "/api/v1/auth/forgot-password", json={"sub": "dave"}
        )
        token = _get_reset_token("dave")
        r = client.post(
            "/api/v1/auth/reset-password",
            json={
                "sub": "someoneelse",
                "token": token,
                "new_password": "anypass123",
            },
        )
        assert r.status_code == 401

    def test_mismatched_token_returns_401(self, client: TestClient) -> None:
        _bootstrap_admin(client, sub="eve", password="hunter22")
        client.post(
            "/api/v1/auth/forgot-password", json={"sub": "eve"}
        )
        r = client.post(
            "/api/v1/auth/reset-password",
            json={
                "sub": "eve",
                "token": "totally-wrong-token",
                "new_password": "anypass123",
            },
        )
        assert r.status_code == 401

    def test_expired_token_returns_401(self, client: TestClient) -> None:
        _bootstrap_admin(client, sub="frank", password="hunter22")
        client.post(
            "/api/v1/auth/forgot-password", json={"sub": "frank"}
        )
        _backdate_token("frank")
        token = _get_reset_token("frank")
        r = client.post(
            "/api/v1/auth/reset-password",
            json={
                "sub": "frank",
                "token": token,
                "new_password": "anypass123",
            },
        )
        assert r.status_code == 401

    def test_weak_password_returns_422(self, client: TestClient) -> None:
        _bootstrap_admin(client, sub="gina", password="hunter22")
        client.post(
            "/api/v1/auth/forgot-password", json={"sub": "gina"}
        )
        token = _get_reset_token("gina")
        r = client.post(
            "/api/v1/auth/reset-password",
            json={
                "sub": "gina",
                "token": token,
                "new_password": "short",  # < 8 chars
            },
        )
        assert r.status_code == 422


# --- POST /auth/users/{sub}/issue-reset (admin only) ----------------------


class TestIssueResetLink:
    """Admin-only: mint a reset token + magic link."""

    def test_admin_can_issue_reset_link(self, client: TestClient) -> None:
        _bootstrap_admin(client, sub="admin", password="adminpass1")
        admin_tok = _login(client, "admin", "adminpass1")
        # Create a victim user.
        r0 = client.post(
            "/api/v1/auth/users",
            json={
                "sub": "victim",
                "password": "victimpass1",
                "role": "red",
            },
            headers={"X-Divide-Token": admin_tok},
        )
        assert r0.status_code == 201, r0.text

        r = client.post(
            "/api/v1/auth/users/victim/issue-reset",
            headers={"X-Divide-Token": admin_tok},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["sub"] == "victim"
        assert body["reset_token"]
        assert body["magic_link"].startswith(
            "/portal/app/#/?sub=victim&token="
        )
        assert body["expires_at"]

    def test_non_admin_cannot_issue_reset_link(
        self, client: TestClient
    ) -> None:
        _bootstrap_admin(client, sub="admin", password="adminpass1")
        admin_tok = _login(client, "admin", "adminpass1")
        client.post(
            "/api/v1/auth/users",
            json={"sub": "red1", "password": "redpass1234", "role": "red"},
            headers={"X-Divide-Token": admin_tok},
        )
        red_tok = _login(client, "red1", "redpass1234")
        r = client.post(
            "/api/v1/auth/users/victim/issue-reset",
            headers={"X-Divide-Token": red_tok},
        )
        assert r.status_code == 403

    def test_unauthenticated_cannot_issue_reset_link(
        self, client: TestClient
    ) -> None:
        _bootstrap_admin(client, sub="admin", password="adminpass1")
        r = client.post("/api/v1/auth/users/victim/issue-reset")
        assert r.status_code == 401

    def test_unknown_user_returns_404(self, client: TestClient) -> None:
        _bootstrap_admin(client, sub="admin", password="adminpass1")
        admin_tok = _login(client, "admin", "adminpass1")
        r = client.post(
            "/api/v1/auth/users/ghost/issue-reset",
            headers={"X-Divide-Token": admin_tok},
        )
        assert r.status_code == 404

    def test_magic_link_round_trip(self, client: TestClient) -> None:
        """End-to-end: admin mints link -> extract token -> reset ->
        sign in with new password."""
        _bootstrap_admin(client, sub="admin", password="adminpass1")
        admin_tok = _login(client, "admin", "adminpass1")
        client.post(
            "/api/v1/auth/users",
            json={
                "sub": "end2end",
                "password": "end2end_old",
                "role": "red",
            },
            headers={"X-Divide-Token": admin_tok},
        )

        link_resp = client.post(
            "/api/v1/auth/users/end2end/issue-reset",
            headers={"X-Divide-Token": admin_tok},
        )
        assert link_resp.status_code == 200
        magic_link = link_resp.json()["magic_link"]

        # The link format is /portal/app/#/?sub=...&token=...
        # so the query string lives in the FRAGMENT (after the
        # ``#``), and the fragment also has a leading ``/`` before
        # the ``?``. We strip both before parsing.
        parsed = urlparse(magic_link)
        qs_raw = parsed.fragment.lstrip("/").lstrip("?")
        qs = parse_qs(qs_raw)
        sub = qs["sub"][0]
        token = qs["token"][0]

        # Reset.
        r = client.post(
            "/api/v1/auth/reset-password",
            json={
                "sub": sub,
                "token": token,
                "new_password": "end2end_new",
            },
        )
        assert r.status_code == 204

        # Sign in with the new password.
        login = client.post(
            "/api/v1/auth/login",
            json={"sub": sub, "password": "end2end_new"},
        )
        assert login.status_code == 200
