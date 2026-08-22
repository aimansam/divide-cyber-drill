"""Router tests — verify endpoints return the expected shape and status.

Note: `/api/v1/drills` now wires into the runner (mock adapter). To
keep tests deterministic, the drill endpoints are tested separately
via integration tests that use a real DB. Here we only test the
stub-only behaviour for now.
"""
from __future__ import annotations


def test_list_scenarios_returns_empty(client):
    r = client.get("/api/v1/scenarios")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_create_scenario_requires_body(client):
    """POST without `yaml` or `path` returns 400."""
    r = client.post("/api/v1/scenarios", json={})
    assert r.status_code == 400


def test_list_drills_returns_empty(client):
    """With no runs in the DB, the endpoint returns an empty list (200)."""
    r = client.get("/api/v1/drills")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_start_drill_returns_400_when_scenario_id_missing(client):
    """Without a `scenario_id`, the endpoint returns 400 (not 501)."""
    r = client.post("/api/v1/drills", json={})
    assert r.status_code == 400


def test_start_drill_returns_422_when_scenario_missing(client):
    """When scenario_id refers to a non-existent scenario, 404."""
    r = client.post("/api/v1/drills", json={"scenario_id": 99999})
    assert r.status_code == 404


def test_proxmox_health_returns_503_when_unconfigured(client):
    r = client.get("/api/v1/proxmox/health")
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"].lower()


def test_proxmox_nodes_returns_503_when_unconfigured(client):
    r = client.get("/api/v1/proxmox/nodes")
    assert r.status_code == 503
