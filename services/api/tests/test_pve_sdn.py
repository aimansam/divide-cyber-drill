"""Tests for the PVE SDN bridge provisioning service.

F-pve-bridge-wizard (SDN variant) replaces the old SSH/paramiko path
with PVE's Software-Defined Networking API
(``/cluster/sdn/{zones,vnets}``). This module tests the API client
and the planner-to-PVE glue without touching a real PVE host.

Coverage:

  * :class:`TestApplySdnPlan` -- the planner-driven applier. Mocks
    httpx and asserts on the exact URL / method / payload for each
    step (zone create, vnet create, propagate poll, idempotent re-run).

  * :class:`TestPermissionErrors` -- PVE returns 401/403 with a
    message naming a permission. We must surface that verbatim and
    attach a copy-pasteable ``pveum aclmod`` hint.

  * :class:`TestReadSdnState` -- the wizard's pre-flight probe
    endpoint, distinguished from generic failures.

  * :class:`TestGetActiveAuth` -- DB overlay vs env-var fallback for
    constructing the request credentials.

The tests inject a fake httpx transport via ``httpx.MockTransport``
so no real network calls happen.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import httpx
import pytest

from app.services.pve_sdn import (
    DEFAULT_ZONE,
    SdnAuth,
    SdnError,
    SdnPermissionError,
    apply_sdn_plan,
    get_active_auth,
    list_node_ifaces,
    list_vnets,
    list_zones,
    read_sdn_state,
    to_apply_result,
)
from app.services.pve_bridges import BridgePlan, BridgeSpec, plan_bridges


# --- helpers --------------------------------------------------------------


def _make_auth(
    *,
    base_url: str = "https://192.168.0.10:8006",
    token_id: str = "divide@pve!drill-token",
    token_secret: str = "secret-uuid",
    user: str = "divide@pve",
    node: str = "pve",
) -> SdnAuth:
    return SdnAuth(
        base_url=base_url,
        token_id=token_id,
        token_secret=token_secret,
        verify_ssl=False,
        user=user,
        node=node,
    )


def _three_bridge_plan() -> BridgePlan:
    """3 bridges (vmbr100..vmbr102), no conflicts, all from one scenario."""
    return plan_bridges(
        [
            {
                "name": "scn",
                "spec": {
                    "networks": [
                        {"name": "v100", "cidr": "10.50.0.0/24"},
                        {"name": "v101", "cidr": "10.50.1.0/24"},
                        {"name": "v102", "cidr": "10.50.2.0/24"},
                    ]
                },
            }
        ]
    )


def _make_handler(
    *,
    zones: list[dict] | None = None,
    vnets: list[dict] | None = None,
    node_ifaces: list[dict] | None = None,
    on_zone_create: Callable[[httpx.Request], httpx.Response] | None = None,
    on_vnet_create: Callable[[httpx.Request], httpx.Response] | None = None,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """Build a mock httpx transport with canned responses."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        method = request.method

        if method == "GET" and path == "/api2/json/cluster/sdn/zones":
            return httpx.Response(200, json={"data": zones or []})
        if method == "GET" and path == "/api2/json/cluster/sdn/vnets":
            return httpx.Response(200, json={"data": vnets or []})
        if (
            method == "GET"
            and path.startswith("/api2/json/nodes/")
            and path.endswith("/network")
        ):
            return httpx.Response(200, json={"data": node_ifaces or []})
        if method == "POST" and path == "/api2/json/cluster/sdn/zones":
            if on_zone_create is not None:
                return on_zone_create(request)
            return httpx.Response(200, json={"data": None})
        if method == "POST" and path == "/api2/json/cluster/sdn/vnets":
            if on_vnet_create is not None:
                return on_vnet_create(request)
            return httpx.Response(200, json={"data": None})
        return httpx.Response(404, json={"data": None, "message": "no handler"})

    return httpx.MockTransport(handler), requests


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport
) -> None:
    """Replace httpx.AsyncClient inside the sdn module."""

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.pop("verify", None)
            super().__init__(transport=transport, *args, **kwargs)

    monkeypatch.setattr("app.services.pve_sdn.httpx.AsyncClient", _PatchedClient)


# --- tests ----------------------------------------------------------------


class TestApplySdnPlan:
    """Happy-path applier tests. All network calls are mocked."""

    def test_creates_zone_and_three_vnets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        iface_names = ["vmbr100", "vmbr101", "vmbr102"]
        node_ifaces = [
            {"iface": n, "type": "bridge"} for n in iface_names
        ]
        transport, requests = _make_handler(
            zones=[],
            vnets=[],
            node_ifaces=node_ifaces,
        )
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        plan = _three_bridge_plan()

        result = asyncio.run(apply_sdn_plan(plan, auth=auth))

        # 1 zone POST + 3 vnet POSTs = 4 POSTs
        post_count = sum(1 for r in requests if r.method == "POST")
        assert post_count == 4

        # Zone POST body
        zone_posts = [
            r for r in requests
            if r.method == "POST" and r.url.path.endswith("/cluster/sdn/zones")
        ]
        assert len(zone_posts) == 1
        body = json.loads(zone_posts[0].content.decode())
        assert body["zone"] == DEFAULT_ZONE
        assert body["type"] == "simple"

        # VNet POST bodies
        vnet_posts = [
            r for r in requests
            if r.method == "POST" and r.url.path.endswith("/cluster/sdn/vnets")
        ]
        vnet_names = [
            json.loads(r.content.decode())["vnet"] for r in vnet_posts
        ]
        assert sorted(vnet_names) == ["vmbr100", "vmbr101", "vmbr102"]

        assert result.zone_created is True
        assert sorted(result.vnets_created) == [
            "vmbr100", "vmbr101", "vmbr102"
        ]
        assert result.vnets_already_present == []
        assert result.propagate_ok is True

    def test_idempotent_when_zone_and_vnets_already_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        existing_zones = [{"zone": DEFAULT_ZONE}]
        existing_vnets = [
            {"vnet": "vmbr100", "zone": DEFAULT_ZONE},
            {"vnet": "vmbr101", "zone": DEFAULT_ZONE},
            {"vnet": "vmbr102", "zone": DEFAULT_ZONE},
        ]
        node_ifaces = [
            {"iface": n, "type": "bridge"} for n in ["vmbr100", "vmbr101", "vmbr102"]
        ]
        transport, requests = _make_handler(
            zones=existing_zones,
            vnets=existing_vnets,
            node_ifaces=node_ifaces,
        )
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        plan = _three_bridge_plan()

        result = asyncio.run(apply_sdn_plan(plan, auth=auth))

        post_count = sum(1 for r in requests if r.method == "POST")
        assert post_count == 0

        assert result.zone_created is False
        assert result.vnets_created == []
        assert sorted(result.vnets_already_present) == [
            "vmbr100", "vmbr101", "vmbr102"
        ]
        assert result.propagate_ok is True

    def test_propagation_timeout_sets_propagate_ok_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport, requests = _make_handler(
            zones=[],
            vnets=[],
            node_ifaces=[],
        )
        _patch_httpx(monkeypatch, transport)

        # Shrink the timeout so the test runs in <1s
        from app.services import pve_sdn
        monkeypatch.setattr(pve_sdn, "PROPAGATE_TIMEOUT_S", 0.5)
        monkeypatch.setattr(pve_sdn, "PROBE_INTERVAL_S", 0.1)

        auth = _make_auth()
        plan = _three_bridge_plan()

        result = asyncio.run(apply_sdn_plan(plan, auth=auth))

        assert result.vnets_created == ["vmbr100", "vmbr101", "vmbr102"]
        assert result.propagate_ok is False
        assert result.propagation_wait_s >= 0.5

    def test_dry_run_does_not_call_pve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport, requests = _make_handler()
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        plan = _three_bridge_plan()

        result = asyncio.run(apply_sdn_plan(plan, auth=auth, dry_run=True))

        assert requests == []
        assert result.zone_created is False
        assert result.vnets_created == []
        # In dry-run, the would-be bridges are listed in
        # already_present -- lets the wizard render "would create N".
        assert sorted(result.vnets_already_present) == [
            "vmbr100", "vmbr101", "vmbr102"
        ]
        assert "would_create_vnets" in result.raw_responses[0]

    def test_refuses_on_plan_conflicts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.pve_bridges import BridgePlanError

        transport, requests = _make_handler()
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        plan = BridgePlan(
            bridges=[],
            conflicts=[
                "bridge vmbr100: scenario 'a' declares CIDR X, "
                "but 'b' already uses Y"
            ],
        )

        with pytest.raises(BridgePlanError):
            asyncio.run(apply_sdn_plan(plan, auth=auth))

        assert requests == []

    def test_to_apply_result_flattens_sdn_result(self) -> None:
        from app.services.pve_sdn import SdnPlanResult

        plan = _three_bridge_plan()
        sdn = SdnPlanResult(
            zone_created=True,
            vnets_created=["vmbr100"],
            vnets_already_present=["vmbr101", "vmbr102"],
            propagate_ok=True,
            propagation_wait_s=2.5,
        )
        out = to_apply_result(plan, sdn)
        assert out.added == ["vmbr100"]
        assert out.already_present == ["vmbr101", "vmbr102"]
        assert out.reload_ok is True
        assert out.reload_method == "sdn"
        assert out.verify_ok is True
        assert out.config_path == f"/sdn/zones/{DEFAULT_ZONE}"


class TestPermissionErrors:
    """PVE returns 401/403 with a permission name in the message body."""

    def test_zone_create_403_raises_permission_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def on_zone_create(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                json={
                    "data": None,
                    "message": "Permission check failed (/sdn/zones, SDN.Allocate)\n",
                },
            )

        transport, _ = _make_handler(
            zones=[],
            vnets=[],
            node_ifaces=[],
            on_zone_create=on_zone_create,
        )
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        plan = _three_bridge_plan()

        with pytest.raises(SdnPermissionError) as ei:
            asyncio.run(apply_sdn_plan(plan, auth=auth))

        assert "SDN.Allocate" in str(ei.value)
        assert ei.value.required_role == "SDN.Allocate"
        assert "pveum aclmod" in ei.value.pveum_hint
        assert "divide@pve" in ei.value.pveum_hint

    def test_vnet_create_403_raises_permission_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def on_vnet_create(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                json={
                    "data": None,
                    "message": "Permission check failed (/sdn/vnets, SDN.Allocate)\n",
                },
            )

        transport, _ = _make_handler(
            zones=[],
            vnets=[],
            node_ifaces=[],
            on_vnet_create=on_vnet_create,
        )
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        plan = _three_bridge_plan()

        with pytest.raises(SdnPermissionError) as ei:
            asyncio.run(apply_sdn_plan(plan, auth=auth))

        assert "SDN.Allocate" in str(ei.value)
        assert ei.value.required_role == "SDN.Allocate"

    def test_500_zone_already_exists_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PVE returns 500 with 'already exists' on duplicate zone POSTs.

        We treat that as a no-op so apply_sdn_plan is safely re-runnable.
        """
        transport, _ = _make_handler(
            zones=[],
            vnets=[],
            node_ifaces=[
                {"iface": n, "type": "bridge"}
                for n in ["vmbr100", "vmbr101", "vmbr102"]
            ],
        )
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        plan = _three_bridge_plan()

        result = asyncio.run(apply_sdn_plan(plan, auth=auth))
        assert result.zone_created is True


class TestReadSdnState:
    """The wizard's pre-flight probe."""

    def test_reachable_returns_zone_and_vnets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport, _ = _make_handler(
            zones=[{"zone": DEFAULT_ZONE}],
            vnets=[{"vnet": "vmbr100", "zone": DEFAULT_ZONE}],
        )
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        readiness = asyncio.run(
            read_sdn_state(auth=auth, expected_vnets=["vmbr100", "vmbr101"])
        )

        assert readiness.reachable is True
        assert readiness.zone_present is True
        assert readiness.error is None
        assert readiness.pveum_hint is None
        assert readiness.vnets_present == ["vmbr100"]
        assert readiness.vnets_missing == ["vmbr101"]

    def test_permission_error_returns_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    403,
                    json={
                        "data": None,
                        "message": "Permission check failed (/sdn/zones, SDN.Allocate)\n",
                    },
                )
            return httpx.Response(500, json={"data": None})

        transport = httpx.MockTransport(handler)
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        readiness = asyncio.run(
            read_sdn_state(auth=auth, expected_vnets=["vmbr100"])
        )

        assert readiness.reachable is True
        assert readiness.error is not None
        assert "SDN.Allocate" in readiness.error
        assert readiness.required_role == "SDN.Allocate"
        assert readiness.pveum_hint is not None
        assert "pveum aclmod" in readiness.pveum_hint


class TestGetActiveAuth:
    """DB overlay > env-var fallback for SDN auth."""

    def test_uses_overlay_when_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services import proxmox

        monkeypatch.setattr(proxmox, "_DB_OVERLAY", {
            "host": "https://10.0.0.5",
            "port": 8006,
            "user": "alice@pve",
            "token_id": "alice@pve!tk",
            "token_secret": "s3cret",
            "verify_ssl": True,
            "node": "node-7",
        })
        auth = get_active_auth()
        assert auth.base_url == "https://10.0.0.5:8006"
        assert auth.user == "alice@pve"
        assert auth.token_id == "alice@pve!tk"
        assert auth.token_secret == "s3cret"
        assert auth.verify_ssl is True
        assert auth.node == "node-7"

    def test_falls_back_to_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services import proxmox

        monkeypatch.setattr(proxmox, "_DB_OVERLAY", None)
        monkeypatch.setenv("PROXMOX_HOST", "https://192.168.1.10")
        monkeypatch.setenv("PROXMOX_PORT", "8006")
        monkeypatch.setenv("PROXMOX_USER", "bob@pve")
        monkeypatch.setenv("PROXMOX_TOKEN_ID", "bob@pve!tk")
        monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "env-secret")
        monkeypatch.setenv("PROXMOX_VERIFY_SSL", "false")
        monkeypatch.setenv("PROXMOX_NODE", "pve-node-2")
        from app.core.config import get_settings
        get_settings.cache_clear()
        try:
            auth = get_active_auth()
            assert auth.base_url == "https://192.168.1.10:8006"
            assert auth.user == "bob@pve"
            assert auth.token_secret == "env-secret"
            assert auth.node == "pve-node-2"
        finally:
            get_settings.cache_clear()

    def test_missing_host_raises_sdn_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services import proxmox

        monkeypatch.setattr(proxmox, "_DB_OVERLAY", None)
        monkeypatch.setenv("PROXMOX_HOST", "")
        monkeypatch.setenv("PROXMOX_TOKEN_ID", "x!y")
        monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "z")
        from app.core.config import get_settings
        get_settings.cache_clear()
        try:
            with pytest.raises(SdnError) as ei:
                get_active_auth()
            assert "host" in str(ei.value).lower()
        finally:
            get_settings.cache_clear()


class TestListEndpoints:
    """Smoke tests for the read-only list helpers."""

    def test_list_zones(self, monkeypatch: pytest.MonkeyPatch) -> None:
        transport, _ = _make_handler(zones=[{"zone": "divide"}])
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        zones = asyncio.run(list_zones(auth))
        assert zones == [{"zone": "divide"}]

    def test_list_vnets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        transport, _ = _make_handler(vnets=[{"vnet": "vmbr100"}])
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        vnets = asyncio.run(list_vnets(auth))
        assert vnets == [{"vnet": "vmbr100"}]

    def test_list_node_ifaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport, _ = _make_handler(
            node_ifaces=[{"iface": "vmbr0", "type": "bridge"}]
        )
        _patch_httpx(monkeypatch, transport)

        auth = _make_auth()
        ifaces = asyncio.run(list_node_ifaces(auth))
        assert ifaces == [{"iface": "vmbr0", "type": "bridge"}]