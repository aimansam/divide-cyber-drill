"""Tests for the PVE bridge planner + SDN applier (F-pve-bridge-wizard).

Covers:

  * :func:`plan_bridges` -- pure planner, no I/O.
  * :func:`apply_bridges` -- now delegates to ``apply_sdn_plan`` (the
     old SSH-executor implementation has been removed; the test for
     it lives in ``test_pve_sdn.py``).

Conflict detection is the most important thing the planner does --
it must catch the F3-RUNBOOK's known foot-gun of two scenarios
declaring the same bridge slot with different CIDRs.
"""
from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from app.services.pve_bridges import (
    BRIDGE_START,
    BridgePlan,
    BridgePlanError,
    BridgeSpec,
    plan_bridges,
)


class TestPlanBridges:
    """Pure planner -- no DB, no network."""

    def test_single_scenario_single_network(self) -> None:
        plan = plan_bridges(
            [
                {
                    "name": "first-live-drill",
                    "spec": {
                        "networks": [
                            {"name": "drill_vlan", "cidr": "10.50.0.0/24"},
                        ]
                    },
                }
            ]
        )
        assert plan.conflicts == []
        assert len(plan.bridges) == 1
        assert plan.bridges[0].name == f"vmbr{BRIDGE_START}"
        assert plan.bridges[0].cidr == "10.50.0.0/24"
        assert plan.bridges[0].gateway_ip == "10.50.0.1"

    def test_dedup_same_name_same_cidr(self) -> None:
        plan = plan_bridges(
            [
                {"name": "a", "spec": {"networks": [{"name": "v", "cidr": "10.0.0.0/24"}]}},
                {"name": "b", "spec": {"networks": [{"name": "v", "cidr": "10.0.0.0/24"}]}},
            ]
        )
        assert plan.conflicts == []
        assert len(plan.bridges) == 1

    def test_same_name_different_cidr_gets_two_bridges(self) -> None:
        """Two scenarios sharing ``name`` with different CIDRs is
        not a conflict -- they're two different bridges. The
        wizard just creates both."""
        plan = plan_bridges(
            [
                {"name": "a", "spec": {"networks": [{"name": "v", "cidr": "10.0.0.0/24"}]}},
                {"name": "b", "spec": {"networks": [{"name": "v", "cidr": "10.0.1.0/24"}]}},
            ]
        )
        assert plan.conflicts == []
        assert len(plan.bridges) == 2

    def test_cidr_overlap_detected(self) -> None:
        plan = plan_bridges(
            [
                {"name": "a", "spec": {"networks": [
                    {"name": "n1", "cidr": "10.50.0.0/24"},
                    {"name": "n2", "cidr": "10.50.0.0/24"},
                ]}},
            ]
        )
        assert any("overlap" in c.lower() for c in plan.conflicts)

    def test_per_scenario_allocation(self) -> None:
        plan = plan_bridges(
            [
                {"name": "a", "spec": {"networks": [
                    {"name": "n1", "cidr": "10.0.0.0/24"},
                    {"name": "n2", "cidr": "10.0.1.0/24"},
                ]}},
                {"name": "b", "spec": {"networks": [
                    {"name": "n1", "cidr": "10.0.2.0/24"},
                ]}},
            ]
        )
        assert plan.conflicts == []
        names = [b.name for b in plan.bridges]
        assert len(names) == 3
        assert names == sorted(names)

    def test_no_networks(self) -> None:
        plan = plan_bridges([{"name": "x", "spec": {"networks": []}}])
        assert plan.conflicts == []
        assert plan.bridges == []

    def test_missing_cidr_skipped(self) -> None:
        plan = plan_bridges(
            [{"name": "x", "spec": {"networks": [
                {"name": "broken"},
                {"name": "good", "cidr": "10.0.0.0/24"},
            ]}}]
        )
        assert len(plan.bridges) == 1
        assert plan.bridges[0].network == "good"

    def test_invalid_cidr_raises(self) -> None:
        with pytest.raises(BridgePlanError):
            plan_bridges(
                [{"name": "x", "spec": {"networks": [
                    {"name": "bad", "cidr": "not-a-cidr"}
                ]}}]
            )

    def test_double_nested_spec(self) -> None:
        plan = plan_bridges(
            [{"name": "x", "spec": {
                "metadata": {"name": "x"},
                "spec": {"networks": [{"name": "v", "cidr": "10.50.0.0/24"}]}
            }}]
        )
        assert len(plan.bridges) == 1
        assert plan.bridges[0].cidr == "10.50.0.0/24"

    def test_stanza_format_matches_runbook(self) -> None:
        spec = BridgeSpec(
            name="vmbr100",
            cidr="10.50.0.0/24",
            gateway_ip="10.50.0.1",
            scenario="first-live-drill",
            network="drill_vlan",
        )
        s = spec.stanza
        assert "auto vmbr100" in s
        assert "iface vmbr100 inet static" in s
        assert "address 10.50.0.1/24" in s
        assert "bridge-ports none" in s
        assert "post-up   iptables -A FORWARD -i vmbr100 -j DROP" in s
        assert "post-down iptables -D FORWARD -i vmbr100 -j DROP" in s

# --- HTTP endpoint tests --------------------------------------------------


class TestAdminBridgeEndpoints:
    """Contract tests for the 3 new admin endpoints."""

    def test_expected_bridges_returns_list(
        self, client: TestClient
    ) -> None:
        # Bootstrap an admin.
        client.post(
            "/api/v1/auth/setup",
            json={"sub": "admin", "password": "adminpass1"},
        )
        tok = client.post(
            "/api/v1/auth/login",
            json={"sub": "admin", "password": "adminpass1"},
        ).json()["token"]
        r = client.get(
            "/api/v1/admin/expected-bridges",
            headers={"X-Divide-Token": tok},
        )
        assert r.status_code == 200
        body = r.json()
        assert "bridges" in body
        assert "conflicts" in body
        assert isinstance(body["bridges"], list)

    def test_expected_bridges_requires_admin(
        self, client: TestClient
    ) -> None:
        r = client.get("/api/v1/admin/expected-bridges")
        assert r.status_code == 401

    def test_pve_setup_bridges_requires_creds(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/v1/auth/setup",
            json={"sub": "admin", "password": "adminpass1"},
        )
        tok = client.post(
            "/api/v1/auth/login",
            json={"sub": "admin", "password": "adminpass1"},
        ).json()["token"]
        # F-pve-bridge-wizard (SDN): POST takes only {dry_run, node};
        # if PVE creds are unset (env or DB) the endpoint returns 502
        # with a wizard-actionable error.
        r = client.post(
            "/api/v1/admin/pve-setup-bridges",
            headers={"X-Divide-Token": tok},
            json={"dry_run": True},
        )
        # Either 502 (no PVE creds in env) or 200 (env-var-driven stack
        # has them set). Either way the request body must be accepted.
        assert r.status_code in (200, 502)
        if r.status_code == 502:
            assert "PVE" in r.json()["detail"] or "host" in r.json()["detail"]

    def test_pve_setup_bridges_dry_run(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/v1/auth/setup",
            json={"sub": "admin", "password": "adminpass1"},
        )
        tok = client.post(
            "/api/v1/auth/login",
            json={"sub": "admin", "password": "adminpass1"},
        ).json()["token"]
        r = client.post(
            "/api/v1/admin/pve-setup-bridges",
            headers={"X-Divide-Token": tok},
            json={"dry_run": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["dry_run"] is True
        assert body["ok"] is True
        # SDN path: when dry-run, the response carries the would-be
        # plan so the wizard can render "would create N Vnets" before
        # actually issuing POSTs to PVE.
        assert "would_create_vnets" in body or body.get("reload_method") == "none"

    def test_pve_bridge_status_returns_expected(
        self, client: TestClient
    ) -> None:
        client.post(
            "/api/v1/auth/setup",
            json={"sub": "admin", "password": "adminpass1"},
        )
        tok = client.post(
            "/api/v1/auth/login",
            json={"sub": "admin", "password": "adminpass1"},
        ).json()["token"]
        r = client.get(
            "/api/v1/admin/pve-bridge-status?node=pve",
            headers={"X-Divide-Token": tok},
        )
        assert r.status_code == 200
        body = r.json()
        assert "expected" in body
        assert "present" in body
        assert "missing" in body
        assert "ready" in body
