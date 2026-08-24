"""Tests for the GET /api/v1/me identity-echo endpoint.

The endpoint is the server-side replacement for the portal's
client-side JWT decode. It's gated by ``require_token`` -- an
anonymous caller gets 401, same as the rest of the authenticated
API. The response carries the verified ``sub``/``role``/``iat``/
``exp`` plus a convenience ``ttl_remaining_s``.

This file is part of the M3.2 commit (Half 1 of role-by-role UI):
see services/portal/app/src/lib/auth.ts (useMe) + app.tsx role
router. The tests pin the wire shape so the portal's useMe() can
rely on it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_token() -> str:
    from app.core.auth import Role, sign_token

    return sign_token("admin-test", Role.ADMIN.value, 3600)


def test_me_admin_returns_full_payload(client: TestClient, admin_token: str):
    """GET /api/v1/me with an admin token returns the verified payload
    plus ttl_remaining_s. The ttl must be positive (less than 3600)
    and reasonably close to the ttl we minted.
    """
    r = client.get("/api/v1/me", headers={"X-Divide-Token": admin_token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sub"] == "admin-test"
    assert body["role"] == "admin"
    assert isinstance(body["iat"], int) and body["iat"] > 0
    assert isinstance(body["exp"], int) and body["exp"] > body["iat"]
    assert isinstance(body["ttl_remaining_s"], int)
    # We minted a 1h token; ttl should be in [3590, 3600] (clock skew).
    assert 3590 <= body["ttl_remaining_s"] <= 3600, body


@pytest.mark.parametrize(
    "role_value",
    ["admin", "lead", "red", "blue", "observer"],
)
def test_me_every_role_returns_correct_role_string(
    client: TestClient, role_value: str
):
    """All five roles from the Role enum round-trip through /me.
    Catches typos and rollouts where the server returns a different
    case or value than the Role enum.
    """
    from app.core.auth import sign_token

    tok = sign_token(f"user-{role_value}", role_value, 3600)
    r = client.get("/api/v1/me", headers={"X-Divide-Token": tok})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == role_value
    assert body["sub"] == f"user-{role_value}"


def test_me_anonymous_returns_401(client: TestClient):
    """No X-Divide-Token -> require_token kicks in -> 401."""
    r = client.get("/api/v1/me")
    assert r.status_code == 401, r.text
    assert "X-Divide-Token" in r.text


def test_me_malformed_token_returns_401(client: TestClient):
    """Garbage in the X-Divide-Token header is a real auth failure,
    not anonymous -- but the response shape is still 401 (with the
    'invalid token' detail). Same split as the rest of the API.
    """
    r = client.get(
        "/api/v1/me",
        headers={"X-Divide-Token": "this.is.not.a.token"},
    )
    assert r.status_code == 401, r.text


def test_me_ttl_remaining_decreases_with_token_age(
    client: TestClient,
):
    """Mint two tokens, sleep 1.2s, hit /me with the older one.
    The ttl_remaining_s should be lower than the fresh one by
    roughly the elapsed time. We allow a generous window because
    the test machine might be slow.
    """
    import time as _time

    from app.core.auth import sign_token

    fresh = sign_token("fresh", "red", 3600)
    _time.sleep(1.2)
    r = client.get("/api/v1/me", headers={"X-Divide-Token": fresh})
    assert r.status_code == 200
    body = r.json()
    # We slept >=1.2s; ttl should be <= 3600 - 1 (very loose).
    assert body["ttl_remaining_s"] <= 3600 - 1, body
    assert body["ttl_remaining_s"] >= 3590, body  # still has the bulk


def test_me_endpoint_listed_in_openapi(client: TestClient):
    """The endpoint appears in /openapi.json under the /api/v1/me
    path so the auto-generated docs (when env != production) and
    any downstream client-gen tooling can pick it up.
    """
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert "/api/v1/me" in spec["paths"], (
        f"/api/v1/me not in OpenAPI paths: {list(spec['paths'].keys())}"
    )
    op = spec["paths"]["/api/v1/me"]["get"]
    assert op.get("summary", "").lower().startswith("return"), op


def test_me_does_not_leak_signing_secret(client: TestClient, admin_token: str):
    """The payload has the public claims (sub/role/iat/exp) but
    nothing sensitive -- specifically, no signature, no secret,
    no raw token string. Catches a future refactor that returns
    the whole JWS instead of the parsed payload.
    """
    r = client.get("/api/v1/me", headers={"X-Divide-Token": admin_token})
    body = r.json()
    forbidden = {"signature", "sig", "secret", "token", "raw", "jws"}
    assert not (forbidden & set(body.keys())), body