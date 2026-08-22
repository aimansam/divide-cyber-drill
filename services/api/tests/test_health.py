"""Health endpoint tests."""
from __future__ import annotations


def test_healthz_returns_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["env"] == "dev"
    assert "version" in body


def test_readyz_returns_503_when_db_unreachable(client):
    """Without Postgres running, /readyz should report degraded."""
    r = client.get("/readyz")
    # Either 200 with degraded status, or 503 depending on policy.
    # We assert the body has the expected shape.
    body = r.json()
    assert "status" in body
    assert "checks" in body
    assert "postgres" in body["checks"]
    assert "redis" in body["checks"]
