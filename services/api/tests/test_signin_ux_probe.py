"""Tests for GET /api/v1/auth/setup probe endpoint (F-signin-ux).

Verifies the public probe that lets the portal decide on first paint
whether to show the sign-in form (returning deployment, admin exists)
or the onboarding wizard (empty deployment, needs setup).

Contract:
  GET /api/v1/auth/setup
    → 200 {"needs_setup": true}   when no users exist
    → 200 {"needs_setup": false}  when at least one user exists
    No token required (public endpoint).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.db.session import get_session
from app.db import models as db_models
from app.services.users import create_user
from app.core.auth import Role

# Re-use the in-memory SQLite session fixture already established
# by the test suite (conftest.py provides `session` and `client`).


class TestSetupProbeEmpty:
    """Probe when the users table is empty."""

    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/auth/setup")
        assert resp.status_code == 200

    def test_needs_setup_true_when_no_users(self, client: TestClient) -> None:
        resp = client.get("/api/v1/auth/setup")
        data = resp.json()
        assert data == {"needs_setup": True}

    def test_no_auth_header_required(self, client: TestClient) -> None:
        """Public endpoint — must not require X-Divide-Token."""
        resp = client.get(
            "/api/v1/auth/setup",
            headers={},  # explicitly no token
        )
        assert resp.status_code == 200
        assert resp.json()["needs_setup"] is True


class TestSetupProbeWithAdmin:
    """Probe after at least one user has been created."""

    def test_needs_setup_false_after_setup(self, client: TestClient) -> None:
        # Bootstrap the first admin via POST /auth/setup
        resp = client.post(
            "/api/v1/auth/setup",
            json={"sub": "probe_admin", "password": "probepass1"},
        )
        assert resp.status_code == 201, resp.text

        # Probe should now report no setup needed
        probe = client.get("/api/v1/auth/setup")
        assert probe.status_code == 200
        assert probe.json() == {"needs_setup": False}

    def test_probe_is_idempotent(self, client: TestClient) -> None:
        """Calling the probe twice gives the same result."""
        # Create admin
        client.post(
            "/api/v1/auth/setup",
            json={"sub": "probe_admin2", "password": "probepass2"},
        )
        r1 = client.get("/api/v1/auth/setup")
        r2 = client.get("/api/v1/auth/setup")
        assert r1.json() == r2.json() == {"needs_setup": False}

    def test_probe_without_token_still_returns_false(
        self, client: TestClient
    ) -> None:
        """Even after admin exists, no token needed to call the probe."""
        client.post(
            "/api/v1/auth/setup",
            json={"sub": "probe_admin3", "password": "probepass3"},
        )
        resp = client.get("/api/v1/auth/setup", headers={})
        assert resp.status_code == 200
        assert resp.json()["needs_setup"] is False
