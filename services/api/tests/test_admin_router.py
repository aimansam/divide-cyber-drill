"""Smoke tests for the admin/setup wizard HTTP endpoints.

These hit the FastAPI app via TestClient and assert the right status
codes + response shapes. No live PVE / no live Redis.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class _FakeRedis:
    """Tiny in-memory redis stand-in for tests that touch progress."""

    def __init__(self):
        self.data: dict[str, dict[str, str]] = {}

    async def hset(self, key, mapping):
        self.data.setdefault(key, {}).update(mapping)

    async def expire(self, key, seconds):  # noqa: ARG002
        pass

    async def hgetall(self, key):
        return dict(self.data.get(key, {}))

    async def scan_iter(self, match=None):
        if match is None:
            for k in list(self.data.keys()):
                yield k
            return
        for k in list(self.data.keys()):
            if "*" in match:
                prefix = match.split("*", 1)[0]
                if k.startswith(prefix):
                    yield k
            elif k == match:
                yield k


@pytest.fixture
def client():
    """Build a TestClient for the app with PVE/Redis stubbed out."""
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_probe_endpoint_returns_snapshot(client):
    """GET /api/v1/admin/probe returns the ProbeResponse shape."""
    # Stub probe_pve so we don't need a live PVE.
    from app.services.admin import PveProbeResult
    fake_result = PveProbeResult(
        reachable=True, version="9.1.7 (9)", pve_user="divide@pve@pam",
        has_drill_privs=True, has_setup_privs=False,
        drill_privs_present=["VM.Allocate", "VM.Clone", "VM.PowerMgmt"],
        drill_privs_missing=[],
        setup_privs_present=[],
        setup_privs_missing=["Datastore.AllocateSpace", "Datastore.Allocate", "Datastore.Audit"],
        storage=[{"storage": "local", "content": "iso,vztmpl", "avail_bytes": 50 * 1024**3}],
        nodes=["pve"], error=None,
    )
    with patch("app.services.admin.probe_pve") as p:
        p.return_value = fake_result
        r = client.get("/api/v1/admin/probe")
        assert r.status_code == 200
        body = r.json()
        assert body["reachable"] is True
        assert body["has_drill_privs"] is True
        assert body["has_setup_privs"] is False
        assert "Datastore.AllocateSpace" in body["setup_privs_missing"]


def test_drill_template_status_when_ready(client):
    """drill-template-status returns ready=True when PVE lists the template."""
    with patch("app.services.proxmox.list_templates") as lt:
        lt.return_value = [
            {"name": "tpl-debian-cloudinit", "vmid": 9000, "template": 1},
        ]
        r = client.get("/api/v1/admin/drill-template-status")
        assert r.status_code == 200
        body = r.json()
        assert body["ready"] is True
        assert body["vmid"] == 9000


def test_drill_template_status_when_missing(client):
    """drill-template-status returns ready=False + error when template absent."""
    with patch("app.services.proxmox.list_templates") as lt:
        lt.return_value = [{"name": "some-other-template", "vmid": 8000}]
        r = client.get("/api/v1/admin/drill-template-status")
        body = r.json()
        assert body["ready"] is False
        assert "not found" in body["error"]


def test_set_template_endpoint(client):
    """POST /api/v1/admin/set-template/{vmid} flips template=1 on the VM."""
    with patch("app.services.admin.set_template_flag") as stf:
        r = client.post("/api/v1/admin/set-template/9000", json={"node": "pve"})
        assert r.status_code == 200
        assert r.json() == {"vmid": 9000, "template": True, "node": "pve"}
        stf.assert_called_once_with(9000, "pve")


def test_progress_endpoint_returns_404_for_unknown_job(client, monkeypatch):
    monkeypatch.setattr("app.services.cache.get_redis", lambda: _FakeRedis())
    r = client.get("/api/v1/admin/progress/upload/nope")
    assert r.status_code == 404


def test_progress_endpoint_validates_kind(client, monkeypatch):
    monkeypatch.setattr("app.services.cache.get_redis", lambda: _FakeRedis())
    r = client.get("/api/v1/admin/progress/garbage/x")
    assert r.status_code == 400
    assert "kind" in r.json()["detail"].lower()


def test_upload_qcow2_rejects_empty(client):
    """Empty multipart body should 400, not 500."""
    r = client.post(
        "/api/v1/admin/upload-qcow2",
        files={"file": ("empty.qcow2", b"", "application/octet-stream")},
        data={"node": "pve", "storage": "local"},
    )
    assert r.status_code == 400
    assert "empty" in r.json()["detail"]


def test_upload_qcow2_streams_real_file(client, tmp_path: Path, monkeypatch):
    """A small qcow2 file uploads end-to-end against a fake httpx client."""
    from app.core.config import get_settings
    from app.services import proxmox as px

    monkeypatch.setenv("PROXMOX_HOST", "pve.lan")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "divide@pve!t")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret")
    get_settings.cache_clear()
    px.get_proxmox_client.cache_clear()
    monkeypatch.setattr("app.services.cache.get_redis", lambda: _FakeRedis())

    fpath = tmp_path / "debian-13.qcow2"
    fpath.write_bytes(b"\x00" * (64 * 1024))  # 64 KB

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"data": "local:import/debian-13.qcow2"}

    class FakeHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return fake_response

    with patch("httpx.AsyncClient", FakeHttpxClient):
        with open(fpath, "rb") as fh:
            r = client.post(
                "/api/v1/admin/upload-qcow2",
                files={"file": ("debian-13.qcow2", fh, "application/octet-stream")},
                data={"node": "pve", "storage": "local"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["result_volid"] == "local:import/debian-13.qcow2"
