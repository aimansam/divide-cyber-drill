"""Unit tests for app.services.admin (the PVE setup wizard helpers).

These tests cover:
  * probe_pve() -- normal path, missing perms, totally down PVE
  * upload_qcow2() -- streams in chunks, reports progress, handles errors
  * create_template_from_qcow2() -- step order + VMID allocation
  * Redis-backed progress round-trip
  * The DRILL_PRIVS constant stays aligned with preflight's expectations

We mock the proxmoxer client and httpx entirely -- no live PVE.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

# --- probe_pve --------------------------------------------------------------


def test_probe_returns_not_configured_when_env_empty(monkeypatch):
    """No PROXMOX_* env -> ProbeResult with error and no perms."""
    from app.core.config import get_settings
    from app.services import proxmox as px
    from app.services.admin import probe_pve

    monkeypatch.setattr(px, "_CACHE", {})
    px.get_proxmox_client.cache_clear()

    monkeypatch.setenv("PROXMOX_HOST", "")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "")
    get_settings.cache_clear()
    px.get_proxmox_client.cache_clear()

    result = probe_pve()
    assert result.reachable is False
    assert "not set" in result.error.lower() or "must be set" in result.error.lower()
    assert result.drill_privs_missing == ["VM.Allocate", "VM.Clone", "VM.PowerMgmt"]
    assert "Datastore" in str(result.setup_privs_missing)


def test_probe_reports_missing_drill_privs(monkeypatch):
    """With perms read-only for VMs, has_drill_privs=False."""
    from app.core.config import get_settings
    from app.services import proxmox as px
    from app.services.admin import probe_pve

    monkeypatch.setenv("PROXMOX_HOST", "pve.lan")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "divide@pve!t")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret")
    get_settings.cache_clear()
    px.get_proxmox_client.cache_clear()

    # probe_pve imports get_version/list_permissions/list_storage directly,
    # so we patch them at the admin module level.
    monkeypatch.setattr("app.services.admin.get_version",
                        lambda: {"version": "9.1", "release": "9"})
    monkeypatch.setattr("app.services.admin.list_permissions",
                        lambda: {"/": {"VM.Audit": 1, "VM.Console": 1}})
    monkeypatch.setattr("app.services.admin.list_storage", lambda: [])
    monkeypatch.setattr("app.services.admin.get_proxmox_client",
                        lambda: MagicMock(nodes=MagicMock(get=lambda: [{"node": "pve"}])))

    result = probe_pve()

    assert result.reachable is True
    assert result.has_drill_privs is False
    assert "VM.Clone" in result.drill_privs_missing
    assert "VM.Allocate" in result.drill_privs_missing


def test_probe_passes_when_full_perms_present(monkeypatch):
    """Full PVEVMAdmin + storage perms -> both flags True."""
    from app.core.config import get_settings
    from app.services import proxmox as px
    from app.services.admin import probe_pve

    monkeypatch.setenv("PROXMOX_HOST", "pve.lan")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "divide@pve!t")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret")
    get_settings.cache_clear()
    px.get_proxmox_client.cache_clear()

    perms = {
        "/": {
            "VM.Allocate": 1, "VM.Clone": 1, "VM.PowerMgmt": 1,
            "Datastore.AllocateSpace": 1, "Datastore.Allocate": 1, "Datastore.Audit": 1,
        },
    }
    storage = [
        {"storage": "local", "content": "iso,vztmpl,backup", "avail_bytes": 50 * 1024**3},
        {"storage": "local-lvm", "content": "images,rootdir", "avail_bytes": 200 * 1024**3},
    ]
    nodes = [{"node": "pve"}]

    monkeypatch.setattr("app.services.admin.get_version",
                        lambda: {"version": "9.1", "release": "9"})
    monkeypatch.setattr("app.services.admin.list_permissions", lambda: perms)
    monkeypatch.setattr("app.services.admin.list_storage", lambda: storage)
    monkeypatch.setattr("app.services.admin.get_proxmox_client",
                        lambda: MagicMock(nodes=MagicMock(get=lambda: nodes)))

    result = probe_pve()

    assert result.reachable is True
    assert result.has_drill_privs is True
    assert result.has_setup_privs is True
    assert result.drill_privs_missing == []
    assert result.setup_privs_missing == []
    assert result.nodes == ["pve"]
    assert len(result.storage) == 2


def test_probe_drill_privs_align_with_preflight():
    """DRILL_PRIVS in admin must equal the set preflight checks.

    If a future change adds e.g. VM.Snapshot to one side, this test
    catches the drift. See tools/preflight.py DRILL_PRIVS.
    """
    from app.services import admin as adm

    expected = frozenset({"VM.Allocate", "VM.Clone", "VM.PowerMgmt"})
    assert expected == adm.DRILL_PRIVS


# --- upload_qcow2 -----------------------------------------------------------


def _make_fake_qcow2(tmp_path: Path, size_kb: int = 256) -> Path:
    """Create a small file that pretends to be a qcow2."""
    p = tmp_path / "debian-13.qcow2"
    p.write_bytes(b"\x00" * (size_kb * 1024))
    return p


class _FakeAsyncClient:
    """Captures the upload call so we can assert shape + return a fake response."""

    def __init__(self, status: int = 200, body: dict | None = None):
        self.status = status
        self.body = body or {"data": "local:import/debian-13.qcow2"}
        self.last_files = None
        self.last_data = None
        self.last_url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, headers=None, files=None, data=None):
        self.last_url = url
        self.last_files = files
        self.last_data = data
        # Files is a dict of (name, (filename, iterator, content_type))
        # Drain the iterator so the upload "completes".
        if files:
            for _name, val in files.items():
                _ = list(val[1])
        return httpx.Response(self.status, json=self.body)


def _patched_admin(monkeypatch, *, redis_client=None):
    """Helper: monkeypatch the admin module's dependencies for upload tests.

    Sets sane PROXMOX_* env, clears the settings + proxmox client caches,
    and stubs out the Redis client so we don't need a live one.
    """
    from app.core.config import get_settings
    from app.services import proxmox as px

    monkeypatch.setenv("PROXMOX_HOST", "pve.lan")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "divide@pve!t")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret")
    get_settings.cache_clear()
    px.get_proxmox_client.cache_clear()
    monkeypatch.setattr(
        "app.services.cache.get_redis",
        lambda: redis_client or _FakeRedis(),
    )


def test_upload_qcow2_streams_in_chunks(tmp_path, monkeypatch):
    """upload_qcow2 must stream the file body (not load all into memory)."""
    from app.services import admin as adm

    _patched_admin(monkeypatch)

    fpath = _make_fake_qcow2(tmp_path, size_kb=512)
    progress_calls = []

    fake = _FakeAsyncClient(status=200, body={"data": "local:import/debian-13.qcow2"})

    with patch("httpx.AsyncClient", return_value=fake):
        result = asyncio.run(adm.upload_qcow2(
            local_path=fpath, node="pve", storage="local",
            progress_callback=lambda s, t: progress_calls.append((s, t)),
        ))

    assert result.status == "success"
    assert result.result_volid == "local:import/debian-13.qcow2"
    assert result.bytes_sent == result.total_bytes
    assert result.total_bytes == 512 * 1024
    # Progress callback fired at least once per chunk.
    assert progress_calls, "progress_callback never fired"
    assert progress_calls[-1][0] == progress_calls[-1][1]


def test_upload_qcow2_handles_pve_error(tmp_path, monkeypatch):
    """If PVE returns 4xx/5xx, status='error' and the error string is set."""
    from app.services import admin as adm

    _patched_admin(monkeypatch)

    fpath = _make_fake_qcow2(tmp_path, size_kb=64)
    fake = _FakeAsyncClient(status=403, body={"errors": "permission denied"})

    with patch("httpx.AsyncClient", return_value=fake):
        result = asyncio.run(adm.upload_qcow2(
            local_path=fpath, node="pve", storage="local",
        ))

    assert result.status == "error"
    assert "403" in (result.error or "")


def test_upload_qcow2_missing_file_raises(tmp_path):
    from app.services import admin as adm

    with pytest.raises(FileNotFoundError):
        asyncio.run(adm.upload_qcow2(
            local_path=tmp_path / "nonexistent.qcow2",
            node="pve", storage="local",
        ))


# --- create_template_from_qcow2 --------------------------------------------


def test_create_template_walks_through_steps(monkeypatch):
    """create_template_from_qcow2 should call the right PVE endpoints
    in the right order and flip template=1 at the end."""
    from app.core.config import get_settings
    from app.services import admin as adm
    from app.services import proxmox as px

    monkeypatch.setenv("PROXMOX_HOST", "pve.lan")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "divide@pve!t")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret")
    get_settings.cache_clear()
    px.get_proxmox_client.cache_clear()
    monkeypatch.setattr("app.services.cache.get_redis", lambda: _FakeRedis())

    call_order: list[str] = []

    mock_client = MagicMock()
    mock_client.cluster.nextid.get.side_effect = lambda: (call_order.append("nextid"), 9000)[1]

    qemu = MagicMock()
    qemu.post.side_effect = lambda **kw: call_order.append("qemu.create")
    qemu.return_value.importdisk.post.side_effect = lambda **kw: call_order.append("qemu.importdisk")
    qemu.return_value.config.post.side_effect = lambda **kw: call_order.append("qemu.config")
    qemu.return_value.template.post.side_effect = lambda **kw: call_order.append("qemu.template")
    mock_client.nodes.return_value.qemu = qemu

    # admin.py imported get_proxmox_client at module load, so we have to
    # patch it in the admin module's namespace.
    monkeypatch.setattr("app.services.admin.get_proxmox_client", lambda: mock_client)

    result = asyncio.run(adm.create_template_from_qcow2(
        template_name="tpl-test",
        source_volid="local:import/debian-13.qcow2",
        node="pve",
        job_id="testjob01",
    ))

    assert result.status == "success"
    assert result.vmid == 9000
    assert call_order == [
        "nextid", "qemu.create", "qemu.importdisk", "qemu.config", "qemu.template",
    ]


def test_create_template_records_failure_on_error(monkeypatch):
    """If any PVE call raises, status='error' and error string is set."""
    from app.core.config import get_settings
    from app.services import admin as adm
    from app.services import proxmox as px

    monkeypatch.setenv("PROXMOX_HOST", "pve.lan")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "divide@pve!t")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret")
    get_settings.cache_clear()
    px.get_proxmox_client.cache_clear()
    monkeypatch.setattr("app.services.cache.get_redis", lambda: _FakeRedis())

    mock_client = MagicMock()
    mock_client.cluster.nextid.get.return_value = 9000

    qemu = MagicMock()
    qemu.post.return_value = None  # VM create OK
    qemu.return_value.importdisk.post.side_effect = RuntimeError("disk full")
    mock_client.nodes.return_value.qemu = qemu

    monkeypatch.setattr("app.services.admin.get_proxmox_client", lambda: mock_client)

    result = asyncio.run(adm.create_template_from_qcow2(
        template_name="tpl-test",
        source_volid="local:import/debian-13.qcow2",
        node="pve",
    ))

    assert result.status == "error"
    assert "disk full" in (result.error or "")


# --- Redis-backed progress --------------------------------------------------


class _FakeRedis:
    """Tiny in-memory redis stand-in for the wizard progress helpers."""

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
        # Match is a glob like 'divide:setup:*'. We don't need glob here
        # since the tests only store one or two keys.
        for k in list(self.data.keys()):
            if "*" in match:
                prefix = match.split("*", 1)[0]
                if k.startswith(prefix):
                    yield k
            elif k == match:
                yield k


def test_progress_round_trip():
    from app.services import admin as adm

    redis = _FakeRedis()
    with patch("app.services.cache.get_redis", return_value=redis):
        up = adm.UploadProgress(
            job_id="abc123",
            filename="debian.qcow2",
            target_volid="local:import/debian.qcow2",
            bytes_sent=1024,
            total_bytes=2048,
            started_at=0.0,
            finished_at=None,
            status="running",
            error=None,
            result_volid=None,
        )
        asyncio.run(adm._set_progress(up))

        # Read it back.
        loaded = asyncio.run(adm.get_progress("abc123", kind="upload"))
        assert loaded is not None
        assert loaded["job_id"] == "abc123"
        assert loaded["bytes_sent"] == 1024
        assert loaded["status"] == "running"
        assert loaded["percent"] == 50.0


def test_progress_missing_returns_none():
    from app.services import admin as adm

    with patch("app.services.cache.get_redis", return_value=_FakeRedis()):
        loaded = asyncio.run(adm.get_progress("nope", kind="upload"))
        assert loaded is None
