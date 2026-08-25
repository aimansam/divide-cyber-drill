"""Tests for the PVE runtime config store (DB singleton, day-1 web setup).

The web-only day-1 setup adds three things on top of the existing
``pve_bridges`` wizard:

    * ``PveConfig`` row in DB  -- the new source of truth (overrides env)
    * 3 admin endpoints       -- GET / POST / DELETE on ``/admin/pve-config``
    * In-process overlay      -- the ``services/proxmox.py`` layer reads
                                  from this overlay first, falls back to
                                  ``PROXMOX_*`` env vars if absent.

These tests cover the service layer + endpoint contracts. They do NOT
exercise a live PVE -- the probe-before-commit path is exercised via
the ``monkeypatch``'d ``get_version`` (returns a sentinel dict on
success, raises on failure).
"""
from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.db.models import PveConfig
from app.services import pve_config as pve_config_svc
from app.services import proxmox as proxmox_svc
from app.services.proxmox import (
    ProxmoxAPIError,
    set_db_overlay,
)


def _overlay() -> dict | None:
    """Read the live value of ``_DB_OVERLAY``.

    Important: this can't be a module-level binding because
    ``from app.services.proxmox import _DB_OVERLAY`` captures the
    value at import time and never re-reads. Module globals
    written by ``set_db_overlay`` would be invisible to a captured
    name. Attribute access on the module always sees the latest
    value.
    """
    return proxmox_svc._DB_OVERLAY


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env_pve(monkeypatch):
    """Set sane PROXMOX_* env vars for every test.

    The conftest doesn't set any PVE env vars (this code is exercised
    end-to-end in live deploys only). For unit tests we need a baseline
    so that ``env_source_dict()`` returns non-empty fields and the
    overlay-vs-env comparison has something to compare against.

    We use ``monkeypatch.setenv`` (not setattr on the Settings instance)
    because the conftest's ``client`` fixture clears the get_settings
    LRU cache, which discards any instance-level changes we made. Env
    vars survive cache clears; instance attrs do not.
    """
    monkeypatch.setenv("PROXMOX_HOST", "https://env-host")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "env!token")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "env-secret")
    monkeypatch.setenv("PROXMOX_USER", "env@pve")
    monkeypatch.setenv("PROXMOX_PORT", "8006")
    monkeypatch.setenv("PROXMOX_VERIFY_SSL", "false")
    # The Settings instance was already cached when app.main was
    # imported. Force a rebuild so the new env vars take effect.
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_overlay():
    """Every test starts with no overlay (env-var fallback)."""
    set_db_overlay(None)
    yield
    set_db_overlay(None)


def _bootstrap_admin_and_token(client: TestClient) -> str:
    """Create an admin via the public /auth/setup + login flow."""
    client.post(
        "/api/v1/auth/setup",
        json={"sub": "admin", "password": "adminpass1"},
    )
    r = client.post(
        "/api/v1/auth/login",
        json={"sub": "admin", "password": "adminpass1"},
    )
    return r.json()["token"]


def _mint_non_admin_token(client: TestClient) -> str:
    """Mint a non-admin token by signing JWT directly (no DB roundtrip)."""
    from app.core.auth import sign_token

    return sign_token(sub="red1", role="red", ttl_s=3600)


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


class TestPveConfigService:
    """The ``pve_config`` module: get / upsert / delete (no HTTP)."""

    def test_get_config_returns_none_when_empty(self, client):
        async def _check():
            from app.db.session import get_sessionmaker

            sm = get_sessionmaker()
            async with sm() as db:
                return await pve_config_svc.get_config(db)

        row = asyncio.run(_check())
        assert row is None

    def test_upsert_writes_singleton(self, client):
        async def _run():
            from app.db.session import get_sessionmaker

            sm = get_sessionmaker()
            async with sm() as db:
                row = await pve_config_svc.upsert_config(
                    db,
                    host="https://192.168.0.10",
                    port=8006,
                    user="divide@pve@pam",
                    token_id="divide@pve@pam!drill-token",
                    token_secret="abc-123",
                    verify_ssl=False,
                    node="pve",
                    updated_by="admin",
                )
                q = await db.execute(select(PveConfig).where(PveConfig.id == 1))
                roundtripped = q.scalar_one()
                return row, roundtripped

        row, roundtripped = asyncio.run(_run())
        assert row.id == 1
        assert row.host == "https://192.168.0.10"
        assert row.token_secret == "abc-123"
        assert roundtripped.host == row.host

    def test_upsert_overwrites_existing(self, client):
        async def _run():
            from app.db.session import get_sessionmaker

            sm = get_sessionmaker()
            async with sm() as db:
                await pve_config_svc.upsert_config(
                    db,
                    host="https://first",
                    port=8006,
                    user="u1",
                    token_id="u1!t",
                    token_secret="s1",
                    verify_ssl=True,
                    node=None,
                    updated_by="admin",
                )
                return await pve_config_svc.upsert_config(
                    db,
                    host="https://second",
                    port=443,
                    user="u2",
                    token_id="u2!t",
                    token_secret="s2",
                    verify_ssl=False,
                    node="pve2",
                    updated_by="admin2",
                )

        row2 = asyncio.run(_run())
        assert row2.id == 1  # singleton
        assert row2.host == "https://second"
        assert row2.token_secret == "s2"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"host": "", "user": "u", "token_id": "u!t", "token_secret": "s"},
            {"host": "h", "user": "", "token_id": "u!t", "token_secret": "s"},
            {"host": "h", "user": "u", "token_id": "", "token_secret": "s"},
            {"host": "h", "user": "u", "token_id": "u!t", "token_secret": ""},
        ],
    )
    def test_upsert_rejects_blank_required_fields(self, client, kwargs):
        async def _run():
            from app.db.session import get_sessionmaker

            sm = get_sessionmaker()
            async with sm() as db:
                return await pve_config_svc.upsert_config(
                    db,
                    port=8006,
                    verify_ssl=False,
                    node=None,
                    updated_by="admin",
                    **kwargs,
                )

        with pytest.raises(pve_config_svc.PveConfigError):
            asyncio.run(_run())

    def test_delete_returns_false_when_empty(self, client):
        async def _run():
            from app.db.session import get_sessionmaker

            sm = get_sessionmaker()
            async with sm() as db:
                # Earlier tests in this session may have left a row;
                # drain it so this test is order-independent.
                existing = await pve_config_svc.delete_config(db)
                return await pve_config_svc.delete_config(db)

        assert asyncio.run(_run()) is False

    def test_to_public_dict_masks_secret(self):
        row = PveConfig(
            host="https://h",
            port=8006,
            user="u",
            token_id="u!t",
            token_secret="super-secret-do-not-leak",
            verify_ssl=False,
            node=None,
        )
        out = row.to_public_dict()
        assert out["token_secret"] == "***"
        assert "super-secret" not in str(out)
        assert out["source"] == "db"

    def test_env_source_dict_returns_env_shape(self):
        out = pve_config_svc.env_source_dict()
        assert out["source"] == "env"
        assert out["host"] == "https://env-host"
        assert out["token_secret"] == "***"  # never echo


# ---------------------------------------------------------------------------
# Overlay plumbing (services/proxmox.py)
# ---------------------------------------------------------------------------


class TestProxmoxOverlay:
    """Verify the in-memory overlay actually replaces env-var resolution."""

    def test_set_db_overlay_replaces_settings(self):
        set_db_overlay(
            {
                "host": "https://db-host",
                "port": 8006,
                "user": "u",
                "token_id": "u!t",
                "token_secret": "db-secret",
                "verify_ssl": False,
                "node": "pve",
            }
        )
        from app.services.proxmox import _validate_config

        host, user, token_name, secret = _validate_config()
        assert host == "db-host"
        assert user == "u"
        assert token_name == "t"
        assert secret == "db-secret"

    def test_set_db_overlay_none_reverts_to_env(self):
        # Install then clear overlay.
        set_db_overlay(
            {
                "host": "https://db-host",
                "port": 8006,
                "user": "u",
                "token_id": "u!t",
                "token_secret": "db-secret",
                "verify_ssl": False,
                "node": "pve",
            }
        )
        set_db_overlay(None)
        from app.services.proxmox import _validate_config

        host, user, token_name, secret = _validate_config()
        # Env vars are configured (see _env_pve fixture)
        assert host == "env-host"
        assert user == "env@pve"
        assert token_name == "token"
        assert secret == "env-secret"


# ---------------------------------------------------------------------------
# Endpoint contracts (HTTP)
# ---------------------------------------------------------------------------


class TestPveConfigEndpoints:
    """Three endpoints: GET / POST / DELETE on /admin/pve-config."""

    def test_get_returns_env_source_when_no_row(self, client):
        tok = _bootstrap_admin_and_token(client)
        r = client.get(
            "/api/v1/admin/pve-config",
            headers={"X-Divide-Token": tok},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "env"
        assert body["token_secret"] == "***"

    def test_get_requires_admin(self, client):
        # No token at all -> 401
        r = client.get("/api/v1/admin/pve-config")
        assert r.status_code == 401

    def test_post_requires_admin_role(self, client):
        # Token but wrong role -> 403
        non_admin = _mint_non_admin_token(client)
        r = client.post(
            "/api/v1/admin/pve-config",
            json={
                "host": "https://h",
                "user": "u",
                "token_id": "u!t",
                "token_secret": "s",
            },
            headers={"X-Divide-Token": non_admin},
        )
        assert r.status_code == 403

    def test_post_validates_required_fields(self, client):
        tok = _bootstrap_admin_and_token(client)
        # Empty host -> 422 from Pydantic
        r = client.post(
            "/api/v1/admin/pve-config",
            json={"host": "", "user": "u", "token_id": "u!t", "token_secret": "s"},
            headers={"X-Divide-Token": tok},
        )
        assert r.status_code == 422

    def test_post_probe_failure_does_not_write(self, client, monkeypatch):
        """If PVE rejects the creds, the row must NOT be persisted."""

        def fake_get_version():
            raise ProxmoxAPIError("401 Unauthorized")

        monkeypatch.setattr(
            "app.routers.admin.get_version", fake_get_version, raising=False
        )
        tok = _bootstrap_admin_and_token(client)
        r = client.post(
            "/api/v1/admin/pve-config",
            json={
                "host": "https://192.168.0.10",
                "user": "divide@pve@pam",
                "token_id": "divide@pve@pam!drill-token",
                "token_secret": "bad-secret",
                "verify_ssl": False,
            },
            headers={"X-Divide-Token": tok},
        )
        assert r.status_code == 502
        assert "401" in r.json()["detail"]
        assert _overlay() is None

        async def _check_empty():
            from app.db.session import get_sessionmaker

            sm = get_sessionmaker()
            async with sm() as db:
                q = await db.execute(select(PveConfig))
                assert q.scalar_one_or_none() is None

        asyncio.run(_check_empty())

    def test_post_probe_success_writes_and_returns_db_shape(self, client, monkeypatch):
        def fake_get_version():
            return {"version": "8.2.0", "release": "1", "repoid": "abc"}

        # The monkeypatch path: app.routers.admin imports get_version lazily.
        # We need to patch the symbol that the route will resolve.
        monkeypatch.setattr(
            "app.services.proxmox.get_version", fake_get_version, raising=False
        )
        tok = _bootstrap_admin_and_token(client)
        r = client.post(
            "/api/v1/admin/pve-config",
            json={
                "host": "https://192.168.0.10",
                "user": "divide@pve@pam",
                "token_id": "divide@pve@pam!drill-token",
                "token_secret": "good-secret",
                "verify_ssl": False,
                "node": "pve",
            },
            headers={"X-Divide-Token": tok},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "db"
        assert body["token_secret"] == "***"
        assert body["host"] == "https://192.168.0.10"
        assert body["user"] == "divide@pve@pam"
        assert body["node"] == "pve"
        assert body["probed"] is True

        async def _check():
            from app.db.session import get_sessionmaker

            sm = get_sessionmaker()
            async with sm() as db:
                q = await db.execute(select(PveConfig))
                row = q.scalar_one()
                assert row.token_secret == "good-secret"

        asyncio.run(_check())
        assert _overlay() is not None
        assert _overlay()["host"] == "https://192.168.0.10"

    def test_get_after_post_returns_db_source(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.services.proxmox.get_version",
            lambda: {"version": "x", "release": "y", "repoid": "z"},
            raising=False,
        )
        tok = _bootstrap_admin_and_token(client)
        client.post(
            "/api/v1/admin/pve-config",
            json={
                "host": "https://h",
                "user": "u",
                "token_id": "u!t",
                "token_secret": "s",
                "verify_ssl": False,
            },
            headers={"X-Divide-Token": tok},
        )
        r = client.get(
            "/api/v1/admin/pve-config",
            headers={"X-Divide-Token": tok},
        )
        body = r.json()
        assert body["source"] == "db"
        assert body["host"] == "https://h"

    def test_delete_clears_db_and_overlay(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.services.proxmox.get_version",
            lambda: {"version": "x", "release": "y", "repoid": "z"},
            raising=False,
        )
        tok = _bootstrap_admin_and_token(client)
        # Post then delete
        rpost = client.post(
            "/api/v1/admin/pve-config",
            json={
                "host": "https://h",
                "user": "u",
                "token_id": "u!t",
                "token_secret": "s",
            },
            headers={"X-Divide-Token": tok},
        )
        assert rpost.status_code == 200, rpost.text
        assert _overlay() is not None
        r = client.delete(
            "/api/v1/admin/pve-config",
            headers={"X-Divide-Token": tok},
        )
        assert r.status_code == 200
        assert r.json()["deleted"] is True
        assert _overlay() is None
        # GET now reports env source
        r2 = client.get(
            "/api/v1/admin/pve-config",
            headers={"X-Divide-Token": tok},
        )
        assert r2.json()["source"] == "env"

    def test_delete_when_no_row_is_noop(self, client):
        tok = _bootstrap_admin_and_token(client)
        r = client.delete(
            "/api/v1/admin/pve-config",
            headers={"X-Divide-Token": tok},
        )
        assert r.status_code == 200
        assert r.json()["deleted"] is False
