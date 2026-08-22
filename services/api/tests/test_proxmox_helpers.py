"""Unit tests for the read-only Proxmox helpers (Stage 2).

These tests use a fake ProxmoxAPI client object to avoid network I/O.
Live PVE connectivity is verified manually via the running container.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.proxmox import (
    ProxmoxAPIError,
    ProxmoxNotConfiguredError,
    clear_cache,
    get_version,
    list_nodes,
    list_storage,
    list_templates,
)


class FakeNodesAPI:
    def __init__(self, data):
        self._data = data

    def get(self):
        return self._data


class FakeQemuAPI:
    def __init__(self, data):
        self._data = data

    def get(self):
        return self._data


class FakeClient:
    """Minimal stand-in for proxmoxer.ProxmoxAPI for read-only calls."""

    def __init__(self, *, version=None, nodes=None, storage=None, qemu_per_node=None, fail_nodes=False):
        self._version = version
        self._nodes = nodes or []
        self._storage = storage or []
        self._qemu_per_node = qemu_per_node or {}
        self._fail_nodes = fail_nodes

    @property
    def version(self):
        outer = self

        class _Version:
            def get(self_inner):
                if isinstance(outer._version, Exception):
                    raise outer._version
                return outer._version

        return _Version()

    @property
    def nodes(self):
        outer = self

        class _Nodes:
            def __init__(self):
                pass

            def get(self):
                if outer._fail_nodes:
                    raise RuntimeError("nodes call failed")
                return outer._nodes

            def __call__(self, name):
                # Return an object with .qemu attribute
                class _Node:
                    def __init__(self, q):
                        self.qemu = FakeQemuAPI(q)

                return _Node(outer._qemu_per_node.get(name, []))

        return _Nodes()

    @property
    def storage(self):
        outer = self

        class _Storage:
            def get(self):
                return outer._storage

        return _Storage()


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_cache()
    yield
    clear_cache()


def test_get_version_returns_dict():
    client = FakeClient(version={"version": "8.2.4", "release": "5.15.158-2", "repoid": "abc123"})
    with patch("app.services.proxmox.get_proxmox_client", return_value=client):
        v = get_version()
    assert v["version"] == "8.2.4"
    assert v["release"].startswith("5.")


def test_get_version_wraps_errors():
    client = FakeClient(version=ConnectionError("connection refused"))
    with patch("app.services.proxmox.get_proxmox_client", return_value=client):
        with pytest.raises(ProxmoxAPIError, match="ConnectionError"):
            get_version()


def test_list_nodes_parses_fields():
    raw = [
        {
            "node": "pve",
            "status": "online",
            "level": "c",
            "ip": "192.168.0.10",
            "cpu": 0.1234,
            "maxmem": 8589934592,
            "mem": 4294967296,
        },
        {"node": "pve2", "status": "offline", "level": "?", "ip": ""},
    ]
    client = FakeClient(nodes=raw)
    with patch("app.services.proxmox.get_proxmox_client", return_value=client):
        nodes = list_nodes()
    assert len(nodes) == 2
    assert nodes[0]["node"] == "pve"
    assert nodes[0]["status"] == "online"
    assert nodes[0]["ip"] == "192.168.0.10"
    assert nodes[0]["mem_total_bytes"] == 8589934592
    assert nodes[0]["cpu_pct"] == pytest.approx(0.1234)
    assert nodes[1]["ip"] is None  # empty string normalized


def test_list_nodes_wraps_errors():
    client = FakeClient(nodes=[], fail_nodes=True)
    with patch("app.services.proxmox.get_proxmox_client", return_value=client):
        with pytest.raises(ProxmoxAPIError):
            list_nodes()


def test_list_storage_parses_free_and_total():
    raw = [
        {
            "storage": "local-lvm",
            "type": "lvmthin",
            "content": "images,rootdir",
            "avail": 500_000_000_000,
            "total": 1_000_000_000_000,
            "active": 1,
        },
        {"storage": "local", "type": "dir", "content": "iso,vztmpl,backup", "active": 1},
    ]
    client = FakeClient(storage=raw)
    with patch("app.services.proxmox.get_proxmox_client", return_value=client):
        items = list_storage()
    assert items[0]["storage"] == "local-lvm"
    assert items[0]["content"] == ["images", "rootdir"]
    assert items[0]["free_bytes"] == 500_000_000_000
    assert items[1]["total_bytes"] is None  # missing field


def test_list_templates_filters_templates_only():
    qemu_data = [
        {"vmid": 9000, "name": "tpl-kali", "node": "pve", "status": "stopped", "template": 1},
        {"vmid": 102, "name": "casaos", "node": "pve", "status": "running", "template": 0},
        {"vmid": 9001, "name": "tpl-ubuntu", "node": "pve", "status": "stopped", "template": 1},
    ]
    client = FakeClient(nodes=[{"node": "pve"}], qemu_per_node={"pve": qemu_data})
    with patch("app.services.proxmox.get_proxmox_client", return_value=client):
        items = list_templates(node="pve")
    # Only template VMs are returned (casaos excluded)
    assert {t["vmid"] for t in items} == {9000, 9001}
    assert {t["name"] for t in items} == {"tpl-kali", "tpl-ubuntu"}
    # The output shape doesn't include 'template' — it's implicit by inclusion


def test_list_templates_no_templates_returns_empty():
    qemu_data = [
        {"vmid": 102, "name": "casaos", "node": "pve", "status": "running", "template": 0},
    ]
    client = FakeClient(nodes=[{"node": "pve"}], qemu_per_node={"pve": qemu_data})
    with patch("app.services.proxmox.get_proxmox_client", return_value=client):
        items = list_templates(node="pve")
    assert items == []


def test_list_templates_all_nodes():
    client = FakeClient(
        nodes=[{"node": "pve"}, {"node": "pve2"}],
        qemu_per_node={
            "pve": [{"vmid": 9000, "name": "tpl-kali", "template": 1, "node": "pve"}],
            "pve2": [{"vmid": 9001, "name": "tpl-win", "template": 1, "node": "pve2"}],
        },
    )
    with patch("app.services.proxmox.get_proxmox_client", return_value=client):
        items = list_templates()  # no node filter
    assert {t["vmid"] for t in items} == {9000, 9001}


def test_not_configured_propagates():
    """If host is missing, ProxmoxNotConfiguredError should bypass the wrapper."""
    with (
        patch("app.services.proxmox.settings") as fake_settings,
    ):
        fake_settings.proxmox.host = ""
        fake_settings.proxmox.token_id = ""
        fake_settings.proxmox.token_secret = None
        with pytest.raises(ProxmoxNotConfiguredError):
            get_version()


# ---------------------------------------------------------------------------
# Router-level tests (mocked helpers)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_settings_and_cache():
    """Reset lru_caches before each test so env-var changes take effect."""
    from app.core.config import get_settings
    from app.services import proxmox as p

    get_settings.cache_clear()
    p.clear_cache()
    yield
    get_settings.cache_clear()
    p.clear_cache()


class TestRouterSuccess:
    """When Proxmox IS configured AND helpers succeed, return 200 + data."""

    def test_health_returns_200(self, client, monkeypatch):
        monkeypatch.setenv("PROXMOX_HOST", "https://pve.test")
        monkeypatch.setenv("PROXMOX_TOKEN_ID", "drill-token")
        monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret-uuid")
        from app.routers import proxmox as r
        with patch.object(r, "get_version", return_value={"version": "8.2.4", "release": "5.15", "repoid": "abc"}):
            r_proxmox = client.get("/api/v1/proxmox/health")
        assert r_proxmox.status_code == 200
        body = r_proxmox.json()
        assert body["version"] == "8.2.4"
        assert body["host"] == "https://pve.test"

    def test_nodes_returns_200_with_items(self, client, monkeypatch):
        monkeypatch.setenv("PROXMOX_HOST", "https://pve.test")
        monkeypatch.setenv("PROXMOX_TOKEN_ID", "drill-token")
        monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret-uuid")
        from app.routers import proxmox as r
        with patch.object(r, "list_nodes", return_value=[{"node": "pve", "status": "online", "level": "c"}]):
            r_proxmox = client.get("/api/v1/proxmox/nodes")
        assert r_proxmox.status_code == 200
        body = r_proxmox.json()
        assert body["total"] == 1
        assert body["items"][0]["node"] == "pve"

    def test_storage_returns_200(self, client, monkeypatch):
        monkeypatch.setenv("PROXMOX_HOST", "https://pve.test")
        monkeypatch.setenv("PROXMOX_TOKEN_ID", "drill-token")
        monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret-uuid")
        from app.routers import proxmox as r
        with patch.object(r, "list_storage", return_value=[{"storage": "local-lvm", "type": "lvmthin", "free_bytes": 1}]):
            r_proxmox = client.get("/api/v1/proxmox/storage")
        assert r_proxmox.status_code == 200
        assert r_proxmox.json()["total"] == 1

    def test_templates_filters_by_node(self, client, monkeypatch):
        monkeypatch.setenv("PROXMOX_HOST", "https://pve.test")
        monkeypatch.setenv("PROXMOX_TOKEN_ID", "drill-token")
        monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret-uuid")
        from app.routers import proxmox as r
        with patch.object(r, "list_templates", return_value=[{"vmid": 9000, "name": "tpl-kali", "node": "pve"}]) as mck:
            r_proxmox = client.get("/api/v1/proxmox/templates?node=pve")
        assert r_proxmox.status_code == 200
        assert mck.call_args.kwargs == {"node": "pve"}

    def test_health_returns_502_on_api_error(self, client, monkeypatch):
        monkeypatch.setenv("PROXMOX_HOST", "https://pve.test")
        monkeypatch.setenv("PROXMOX_TOKEN_ID", "drill-token")
        monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret-uuid")
        from app.routers import proxmox as r
        with patch.object(r, "get_version", side_effect=r.ProxmoxAPIError("Connection refused")):
            r_proxmox = client.get("/api/v1/proxmox/health")
        assert r_proxmox.status_code == 502
        assert "Connection refused" in r_proxmox.json()["detail"]
