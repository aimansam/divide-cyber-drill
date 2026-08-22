"""Stub router tests — verify stubs return the expected shape."""
from __future__ import annotations


def test_list_scenarios_returns_empty(client):
    r = client.get("/api/v1/scenarios")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_create_scenario_returns_501(client):
    r = client.post("/api/v1/scenarios", json={})
    assert r.status_code == 501


def test_list_drills_returns_empty(client):
    r = client.get("/api/v1/drills")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_start_drill_returns_501(client):
    r = client.post("/api/v1/drills", json={})
    assert r.status_code == 501


def test_proxmox_health_returns_503_when_unconfigured(client):
    r = client.get("/api/v1/proxmox/health")
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"].lower()


def test_proxmox_nodes_returns_503_when_unconfigured(client):
    r = client.get("/api/v1/proxmox/nodes")
    assert r.status_code == 503
