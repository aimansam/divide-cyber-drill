"""RealProxmoxAdapter tests, all against mocked proxmoxer — no live PVE.

We mock `proxmoxer.ProxmoxAPI` at the module boundary and assert:
  * The right endpoint is hit with the right path/args.
  * PVE JSON responses are mapped to our dataclasses correctly.
  * Errors from proxmoxer surface as `ProxmoxAPIError`.
  * `destroy_vm` is idempotent on missing VMs (404 -> no-op).
  * `_call` enforces a per-call timeout.

Why mock proxmoxer rather than spin up a stub server:
  - proxmoxer's surface is large; we don't want a hand-rolled HTTP server.
  - These tests run offline and fast.
  - The real adapter's behaviour is mostly "build URL, pass kwargs, map
    response", all of which is checkable via mocks.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import ProxmoxSettings
from app.runners.adapter import CloneSpec
from app.runners.real_adapter import RealProxmoxAdapter
from app.services.proxmox import ProxmoxAPIError, ProxmoxNotConfiguredError


# --- construction ----------------------------------------------------------


def test_constructor_rejects_empty_host():
    with pytest.raises(ProxmoxNotConfiguredError):
        RealProxmoxAdapter(
            host="", port=8006, user="divide@pve",
            token_id="divide@pve!t", token_secret="x",
        )


def test_constructor_rejects_missing_token():
    with pytest.raises(ProxmoxNotConfiguredError):
        RealProxmoxAdapter(
            host="pve.example", port=8006, user="divide@pve",
            token_id="", token_secret="x",
        )


def test_constructor_strips_scheme_from_host():
    a = RealProxmoxAdapter(
        host="https://pve.example/", port=8006, user="divide@pve",
        token_id="divide@pve!t", token_secret="x", verify_ssl=False,
    )
    assert a._host == "pve.example"


def test_from_settings_missing_host():
    p = ProxmoxSettings(host=None)
    with pytest.raises(ProxmoxNotConfiguredError):
        RealProxmoxAdapter.from_settings(p)


def test_from_settings_missing_secret():
    p = ProxmoxSettings(host="pve", token_id="divide@pve!t", token_secret=None)
    with pytest.raises(ProxmoxNotConfiguredError):
        RealProxmoxAdapter.from_settings(p)


def test_from_settings_happy_path():
    p = ProxmoxSettings(
        host="pve.example", port=8006, user="divide@pve",
        token_id="divide@pve!drill", token_secret="s3cret", verify_ssl=False,
    )
    a = RealProxmoxAdapter.from_settings(p)
    assert a._host == "pve.example"
    assert a._token_name == "drill"
    assert a._token_secret == "s3cret"
    assert a._verify_ssl is False


def test_token_id_split_handles_missing_exclaim():
    """If PROXMOX_TOKEN_ID has no '!', treat the whole string as token_name."""
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="plain-token-name", token_secret="x",
    )
    assert a._token_name == "plain-token-name"


# --- helpers ---------------------------------------------------------------


def _build_mock_client() -> MagicMock:
    """Build a MagicMock that mimics proxmoxer.ProxmoxAPI chained access.

    The chain we use:
      client.nodes.get()
      client.cluster.resources.get(type=...)
      client.cluster.nextid.post()
      client.nodes(node).qemu(vmid).clone.post(**params)
      client.nodes(node).qemu(vmid).status.start.post()
      client.nodes(node).qemu(vmid).status.stop.post(**kwargs)
      client.nodes(node).qemu(vmid).delete(purge=1, skiplock=1)
      client.nodes(node).qemu(vmid).status.current.get()
      client.nodes(node).qemu(vmid).config.get()
    """
    client = MagicMock()
    return client


def _install_client(a: RealProxmoxAdapter, client: MagicMock) -> None:
    a._client = client  # bypass _get_client so we can inject the mock.


# --- list_nodes ------------------------------------------------------------


def test_list_nodes():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.nodes.get.return_value = [
        {"node": "pve", "status": "online"},
        {"node": "pve2", "status": "online"},
    ]
    _install_client(a, client)

    result = asyncio.run(a.list_nodes())

    assert result == ["pve", "pve2"]
    client.nodes.get.assert_called_once_with()


# --- find_template ---------------------------------------------------------


def test_find_template_hit():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.cluster.resources.get.return_value = [
        {"template": 1, "name": "tpl-ubuntu", "vmid": 9001},
        {"template": 0, "name": "running-vm", "vmid": 100},
    ]
    _install_client(a, client)

    assert asyncio.run(a.find_template("tpl-ubuntu")) == 9001


def test_find_template_miss():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.cluster.resources.get.return_value = [
        {"template": 1, "name": "tpl-ubuntu", "vmid": 9001},
    ]
    _install_client(a, client)

    assert asyncio.run(a.find_template("tpl-kali")) is None


def test_find_template_skips_non_templates():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.cluster.resources.get.return_value = [
        {"template": 0, "name": "match-by-name-but-not-tpl", "vmid": 1234},
    ]
    _install_client(a, client)

    assert asyncio.run(a.find_template("match-by-name-but-not-tpl")) is None


# --- allocate_vmid ---------------------------------------------------------


def test_allocate_vmid():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.cluster.nextid.get.return_value = "9102"
    _install_client(a, client)

    assert asyncio.run(a.allocate_vmid()) == 9102
    client.cluster.nextid.get.assert_called_once_with()


# --- clone_vm --------------------------------------------------------------


def test_clone_vm_with_explicit_vmid_and_overrides():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    _install_client(a, client)

    spec = CloneSpec(
        source_vmid=9001,
        new_vmid=9100,
        node="pve",
        name="divide-7-attacker",
        cores=4,
        sockets=1,
        ram_mb=4096,
        disk_gb=20,
    )
    result = asyncio.run(a.clone_vm(spec))

    clone_post = client.nodes("pve").qemu(9001).clone.post
    clone_post.assert_called_once_with(
        name="divide-7-attacker",
        newid=9100,
        cores=4,
        sockets=1,
        memory=4096,
        disk="scsi0=20G",
    )
    assert result.vmid == 9100
    assert result.node == "pve"
    assert result.name == "divide-7-attacker"


def test_clone_vm_without_newid_allocates_via_nextid():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.cluster.nextid.get.return_value = "9123"
    _install_client(a, client)

    spec = CloneSpec(
        source_vmid=9001, new_vmid=None, node="pve", name="x",
    )
    result = asyncio.run(a.clone_vm(spec))

    client.cluster.nextid.get.assert_called_once()
    assert result.vmid == 9123


def test_clone_vm_missing_node_raises():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    spec = CloneSpec(source_vmid=9001, new_vmid=9100, node="", name="x")
    with pytest.raises(ProxmoxAPIError):
        asyncio.run(a.clone_vm(spec))


def test_clone_vm_missing_source_vmid_raises():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    spec = CloneSpec(source_vmid=None, new_vmid=9100, node="pve", name="x")  # type: ignore[arg-type]
    with pytest.raises(ProxmoxAPIError):
        asyncio.run(a.clone_vm(spec))


# --- start / stop ----------------------------------------------------------


def test_start_vm_calls_correct_endpoint():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    _install_client(a, client)

    asyncio.run(a.start_vm(9100, "pve"))

    client.nodes("pve").qemu(9100).status.start.post.assert_called_once_with()


def test_stop_vm_default_no_force():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    _install_client(a, client)

    asyncio.run(a.stop_vm(9100, "pve"))

    client.nodes("pve").qemu(9100).status.stop.post.assert_called_once_with()


def test_stop_vm_force_sets_forceStop():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    _install_client(a, client)

    asyncio.run(a.stop_vm(9100, "pve", force=True))

    client.nodes("pve").qemu(9100).status.stop.post.assert_called_once_with(
        forceStop=1
    )


# --- destroy_vm (idempotent on 404) ----------------------------------------


def test_destroy_vm_happy_path():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    _install_client(a, client)

    asyncio.run(a.destroy_vm(9100, "pve"))

    client.nodes("pve").qemu(9100).delete.assert_called_once_with(
        purge=1, skiplock=1
    )


def test_destroy_vm_is_idempotent_on_404():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.nodes("pve").qemu(9100).delete.side_effect = Exception(
        "404 Not Found: no such VM"
    )
    _install_client(a, client)

    # Should NOT raise — destroy is idempotent.
    asyncio.run(a.destroy_vm(9100, "pve"))


def test_destroy_vm_propagates_other_errors():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.nodes("pve").qemu(9100).delete.side_effect = Exception(
        "500 Internal Server Error"
    )
    _install_client(a, client)

    with pytest.raises(ProxmoxAPIError):
        asyncio.run(a.destroy_vm(9100, "pve"))


# --- get_vm_state ----------------------------------------------------------


def test_get_vm_state_running_with_ip():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.nodes("pve").qemu(9100).status.current.get.return_value = {
        "vmid": 9100, "name": "drill", "status": "running", "ip": "10.0.0.42",
    }
    _install_client(a, client)

    state = asyncio.run(a.get_vm_state(9100, "pve"))
    assert state.vmid == 9100
    assert state.node == "pve"
    assert state.name == "drill"
    assert state.status == "running"
    assert state.ip == "10.0.0.42"


def test_get_vm_state_stopped_falls_back_to_ipconfig0():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.nodes("pve").qemu(9100).status.current.get.return_value = {
        "vmid": 9100, "name": "drill", "status": "stopped",
        # No "ip" field — fall through to ipconfig0.
    }
    client.nodes("pve").qemu(9100).config.get.return_value = {
        "ipconfig0": "ip=10.0.0.50/24,gw=10.0.0.1",
    }
    _install_client(a, client)

    state = asyncio.run(a.get_vm_state(9100, "pve"))
    assert state.status == "stopped"
    assert state.ip == "10.0.0.50"


def test_get_vm_state_dhcp_ipconfig_yields_none_ip():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.nodes("pve").qemu(9100).status.current.get.return_value = {
        "vmid": 9100, "name": "drill", "status": "running",
    }
    client.nodes("pve").qemu(9100).config.get.return_value = {
        "ipconfig0": "ip=dhcp",
    }
    _install_client(a, client)

    state = asyncio.run(a.get_vm_state(9100, "pve"))
    assert state.ip is None


def test_get_vm_state_missing_ipconfig_keeps_ip_none():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.nodes("pve").qemu(9100).status.current.get.return_value = {
        "vmid": 9100, "name": "drill", "status": "stopped",
    }
    client.nodes("pve").qemu(9100).config.get.side_effect = Exception("boom")
    _install_client(a, client)

    state = asyncio.run(a.get_vm_state(9100, "pve"))
    assert state.ip is None
    assert state.status == "stopped"


# --- error wrapping --------------------------------------------------------


def test_proxmoxer_exception_wrapped_as_proxmox_api_error():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.nodes.get.side_effect = Exception("connection refused")
    _install_client(a, client)

    with pytest.raises(ProxmoxAPIError) as exc_info:
        asyncio.run(a.list_nodes())
    assert "connection refused" in str(exc_info.value)


def test_401_unauthorized_is_wrapped():
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.nodes.get.side_effect = Exception("401 Unauthorized")
    _install_client(a, client)

    with pytest.raises(ProxmoxAPIError):
        asyncio.run(a.list_nodes())


def test_403_permission_check_includes_acl_hint():
    """403s should surface with a PVEVMAdmin hint so operators don't debug
    in the dark. This is the failure mode you'll hit if the token only has
    PVEAuditor and you attempt a clone/start/stop/destroy."""
    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
    )
    client = _build_mock_client()
    client.nodes.get.side_effect = Exception(
        "403 Forbidden: Permission check failed"
    )
    _install_client(a, client)

    with pytest.raises(ProxmoxAPIError) as exc_info:
        asyncio.run(a.list_nodes())
    assert "PVEVMAdmin" in str(exc_info.value)
    assert "PROXMOX-SETUP" in str(exc_info.value)


def test_timeout_surfaces_as_proxmox_api_error():
    """A hung PVE call must never leak asyncio.TimeoutError to the runner."""

    def hang(*a, **kw):
        time.sleep(5)

    a = RealProxmoxAdapter(
        host="pve", port=8006, user="u",
        token_id="u!t", token_secret="x",
        timeout_s=0.05,  # 50ms — guarantees timeout in CI
    )
    client = _build_mock_client()
    client.nodes.get.side_effect = hang
    _install_client(a, client)

    with pytest.raises(ProxmoxAPIError) as exc_info:
        asyncio.run(a.list_nodes())
    assert "timed out" in str(exc_info.value).lower()


# --- proxmoxer construction ------------------------------------------------


def test_get_client_uses_settings():
    """Verify the ProxmoxAPI constructor gets called with the right args."""
    with patch("app.runners.real_adapter.ProxmoxAPI") as api_cls:
        api_cls.return_value = MagicMock()
        a = RealProxmoxAdapter(
            host="pve.example", port=8006, user="divide@pve",
            token_id="divide@pve!drill", token_secret="s3cret", verify_ssl=False,
        )
        client = a._get_client()
        api_cls.assert_called_once_with(
            host="pve.example",
            port=8006,
            user="divide@pve",
            token_name="drill",
            token_value="s3cret",
            verify_ssl=False,
            backend="https",
        )
        assert client is api_cls.return_value
        # Second call reuses the same instance.
        assert a._get_client() is client


# --- factory behaviour -----------------------------------------------------


def test_factory_picks_mock_without_env(monkeypatch):
    monkeypatch.delenv("PROXMOX_HOST", raising=False)
    monkeypatch.delenv("PROXMOX_TOKEN_ID", raising=False)
    monkeypatch.delenv("PROXMOX_TOKEN_SECRET", raising=False)
    from app.runners.runner import _default_adapter
    from app.runners.mock_adapter import MockProxmoxAdapter

    assert isinstance(_default_adapter(), MockProxmoxAdapter)


def test_factory_picks_real_with_env(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "pve.example")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "u!t")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "s3cret")
    # `get_settings()` is lru_cached — clear it so the env above takes effect.
    from app.core import config as cfg_module
    from app.runners.runner import _default_adapter
    from app.runners.real_adapter import RealProxmoxAdapter

    cfg_module.get_settings.cache_clear()
    try:
        assert isinstance(_default_adapter(), RealProxmoxAdapter)
    finally:
        cfg_module.get_settings.cache_clear()


def test_factory_falls_back_to_mock_on_bad_config(monkeypatch):
    """If PROXMOX_HOST is empty after stripping, factory logs + falls back."""
    monkeypatch.setenv("PROXMOX_HOST", "")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "u!t")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "s3cret")
    from app.core import config as cfg_module
    from app.runners.runner import _default_adapter
    from app.runners.mock_adapter import MockProxmoxAdapter

    cfg_module.get_settings.cache_clear()
    try:
        assert isinstance(_default_adapter(), MockProxmoxAdapter)
    finally:
        cfg_module.get_settings.cache_clear()
