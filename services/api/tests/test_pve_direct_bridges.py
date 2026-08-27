"""Tests for the PVE direct-bridge applier (PVE 9 happy path).

The direct applier bypasses SDN and POSTs to PVE's node-level
network API (``/nodes/{n}/network``) which creates Linux bridges
on the node directly. This is the only viable path on stock PVE 9
without an external SDN controller installed.

Coverage:

  * :class:`TestApplyDirectPlan` -- happy path with 3 bridges
    (vmbr100..vmbr102). Verifies each bridge is POSTed to
    ``/nodes/{n}/network`` with the right ``type=bridge``,
    ``address=gateway_ip/prefix``, and ``comments=div:ide:...``.

  * :class:`TestDirectPlanIdempotent` -- re-running when bridges
    already exist returns ``vnets_already_present`` and skips the
    POSTs.

  * :class:`TestDirectPlanPermissionDenied` -- PVE returns 403 for
    a missing ``Sys.Modify``. We must surface that as
    ``SdnPermissionError`` with ``required_role="Sys.Modify"`` and a
    ``pveum`` hint that includes the custom-role creation snippet.

  * :class:`TestDirectPlanConflicts` -- the planner rejects plans
    with CIDR overlaps before any network calls are made.

The tests inject a fake httpx transport via ``httpx.MockTransport``
so no real network calls happen.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import httpx
import pytest

from app.services.pve_bridges import (
    BridgePlan,
    BridgePlanError,
    plan_bridges,
)
from app.services.pve_sdn import (
    SdnAuth,
    SdnPermissionError,
    apply_direct_plan,
)


# --- helpers --------------------------------------------------------------


def _make_auth(
    *,
    base_url: str = "https://192.168.0.10:8006",
    token_id: str = "divide@pve@pam!drill-token",
    token_secret: str = "secret-uuid",
    user: str = "divide@pve@pam",
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


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport
) -> None:
    """Replace httpx.AsyncClient inside the sdn module."""

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.pop("verify", None)
            super().__init__(transport=transport, *args, **kwargs)

    monkeypatch.setattr("app.services.pve_sdn.httpx.AsyncClient", _PatchedClient)


def _run(coro):
    """Sync helper to run an async function from test bodies."""
    return asyncio.get_event_loop().run_until_complete(coro)

class TestApplyDirectPlan:
    """Happy-path applier tests. All network calls are mocked."""

    def test_creates_three_bridges(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty node -> 3 POSTs to /nodes/{n}/network, all succeed."""
        posted_bodies: list[dict[str, Any]] = []
        get_calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            method = request.method
            if method == "GET" and path.startswith("/api2/json/nodes/"):
                get_calls["n"] += 1
                if get_calls["n"] == 1:
                    # Initial probe: no bridges.
                    return httpx.Response(200, json={"data": []})
                # Propagation re-check: bridges appeared.
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {"iface": "vmbr100", "type": "bridge"},
                            {"iface": "vmbr101", "type": "bridge"},
                            {"iface": "vmbr102", "type": "bridge"},
                        ]
                    },
                )
            if method == "POST" and path.startswith("/api2/json/nodes/"):
                body = json.loads(request.content) if request.content else {}
                posted_bodies.append(body)
                return httpx.Response(200, json={"data": None})
            return httpx.Response(404, json={"data": None})

        _patch_httpx(monkeypatch, httpx.MockTransport(handler))

        result = _run(apply_direct_plan(_three_bridge_plan(), auth=_make_auth()))

        assert result.propagate_ok
        assert result.vnets_created == ["vmbr100", "vmbr101", "vmbr102"]
        assert result.vnets_already_present == []
        assert len(posted_bodies) == 3
        # Verify each POST shape (PVE 9 format: address bare, netmask
        # dotted-quad).
        first = posted_bodies[0]
        assert first["iface"] == "vmbr100"
        assert first["type"] == "bridge"
        assert first["autostart"] == 1
        assert first["address"] == "10.50.0.1"
        assert first["netmask"] == "255.255.255.0"
        assert first["comments"].startswith("div:ide:")
        # All POSTs targeted the right node path.
        for body in posted_bodies:
            assert body["iface"].startswith("vmbr10")


class TestDirectPlanIdempotent:
    """Re-running apply when bridges already exist is a no-op."""

    def test_skips_existing_bridges(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        existing = [
            {"iface": "vmbr100", "type": "bridge"},
            {"iface": "vmbr101", "type": "bridge"},
            {"iface": "vmbr102", "type": "bridge"},
        ]
        posted_bodies: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"data": existing})
            if request.method == "POST":
                posted_bodies.append(
                    json.loads(request.content) if request.content else {}
                )
                return httpx.Response(200, json={"data": None})
            return httpx.Response(404, json={"data": None})

        _patch_httpx(monkeypatch, httpx.MockTransport(handler))

        result = _run(apply_direct_plan(_three_bridge_plan(), auth=_make_auth()))

        assert result.propagate_ok
        assert result.vnets_created == []
        assert result.vnets_already_present == [
            "vmbr100",
            "vmbr101",
            "vmbr102",
        ]
        # No POSTs when everything's already there.
        assert posted_bodies == []


class TestDirectPlanPermissionDenied:
    """PVE 9 returns 403 (Sys.Modify) when the token lacks the privilege."""

    def test_sys_modify_missing_surfaces_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"data": []})
            # POST: 403 with the literal PVE 9 message.
            return httpx.Response(
                403,
                json={
                    "data": None,
                    "message": (
                        "Permission check failed (/nodes/pve, Sys.Modify)"
                    ),
                },
            )

        _patch_httpx(monkeypatch, httpx.MockTransport(handler))

        with pytest.raises(SdnPermissionError) as exc_info:
            _run(
                apply_direct_plan(
                    _three_bridge_plan(), auth=_make_auth(user="divide@pve@pam")
                )
            )

        err = exc_info.value
        assert err.required_role == "Sys.Modify"
        assert "Sys.Modify" in err.pveum_hint
        # The hint must include the custom-role creation snippet
        # so the operator can grant the privilege in one shot.
        assert "pveum role add DivideNetAdmin" in err.pveum_hint
        assert "pveum aclmod divide@pve@pam" in err.pveum_hint
        assert "-privs Sys.Modify" in err.pveum_hint


class TestDirectPlanConflicts:
    """The applier refuses plans with CIDR overlaps (no network calls)."""

    def test_conflicting_plan_raises_before_any_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two networks with the same CIDR -> planner flags a conflict.
        plan = plan_bridges(
            [
                {
                    "name": "scn",
                    "spec": {
                        "networks": [
                            {"name": "v1", "cidr": "10.50.0.0/24"},
                            {"name": "v2", "cidr": "10.50.0.0/24"},
                        ]
                    },
                }
            ]
        )
        assert plan.conflicts, "test precondition: planner flags overlap"

        requests_seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(request)
            return httpx.Response(500, json={"data": None, "message": "fail"})

        _patch_httpx(monkeypatch, httpx.MockTransport(handler))

        with pytest.raises(BridgePlanError) as exc_info:
            _run(apply_direct_plan(plan, auth=_make_auth()))
        assert "conflicts" in str(exc_info.value).lower()
        # Zero network calls -- the conflict was caught first.
        assert requests_seen == []
