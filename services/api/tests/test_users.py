"""Tests for app.services.users + app.routers.auth (F3-prep credential login).

Covers:
  * hash_password + verify_password round-trip + tamper
  * argon2 salt differs per user
  * create_user rejects empty / unknown inputs
  * create_user rejects unknown role
  * create_user rejects duplicate sub
  * authenticate happy path
  * authenticate wrong password returns None (no raise)
  * authenticate unknown sub returns None (no raise)
  * authenticate disabled user returns None
  * POST /auth/login happy path
  * POST /auth/login bad password returns generic 401
  * POST /auth/login unknown sub returns same generic 401 (no enumeration)
  * POST /auth/login disabled returns 401
  * POST /auth/login bad body returns 422
  * POST /auth/login rate-limited (6th attempt) returns 429
  * GET /auth/users requires admin
  * GET /auth/users returns public fields only (no password_hash)
"""
from __future__ import annotations

# Local async fixtures. We use an in-memory SQLite + Base.metadata.create_all
# because we only need to exercise the service layer; the full alembic
# migration stack is exercised by the conftest's `_create_tables` for
# the router tests (where we want FK constraints + indexes as alembic
# applied them).
import asyncio

import pytest
from app.core.auth import Role
from app.db.base import Base
from app.services import users as users_service
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@pytest.fixture
def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    yield eng
    asyncio.run(eng.dispose())


@pytest.fixture
async def session(engine) -> AsyncSession:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture
def fake_redis(monkeypatch):
    """Per-test fresh fakeredis client.

    Swaps the module-level ``_client`` and ``get_redis`` factory so
    the login + drill rate-limiters operate on a fakeredis instead
    of trying to reach a real Redis at localhost:6379. Same pattern
    as ``tests/test_rate_limit.py``.
    """
    import fakeredis.aioredis as fakeredis_aioredis
    from app.services import cache as cache_module

    fake = fakeredis_aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_module, "_client", fake, raising=False)
    monkeypatch.setattr(cache_module, "get_redis", lambda: fake)
    yield fake
    # close() is async; fakeredis's client works fine without an explicit close.


# ---------- hashing ------------------------------------------------------


def test_hash_password_is_argon2id():
    h = users_service.hash_password("hunter2")
    assert h.startswith("$argon2id$"), f"unexpected hash prefix: {h!r}"


def test_verify_password_round_trip():
    h = users_service.hash_password("hunter2")
    assert users_service.verify_password(h, "hunter2") is True


def test_verify_password_rejects_wrong():
    h = users_service.hash_password("hunter2")
    assert users_service.verify_password(h, "hunter3") is False


def test_argon2_salt_differs_per_user():
    """Two users with the same password get different hashes."""
    h1 = users_service.hash_password("same")
    h2 = users_service.hash_password("same")
    assert h1 != h2


def test_verify_password_returns_false_on_garbage_hash():
    assert users_service.verify_password("not-a-phc-string", "anything") is False
    assert users_service.verify_password("", "anything") is False
    assert users_service.verify_password("$argon2id$v=19$m=65536,t=2,p=4$xx$yy", "") is False


def test_hash_password_rejects_empty():
    with pytest.raises(ValueError):
        users_service.hash_password("")


# ---------- create_user (async) -------------------------------------------


@pytest.mark.asyncio
async def test_create_user_happy_path(session: AsyncSession):
    u = await users_service.create_user(
        session, sub="alice", password="hunter2", role="red"
    )
    await session.commit()
    assert u.id is not None
    assert u.sub == "alice"
    assert u.role == "red"
    assert u.password_hash.startswith("$argon2id$")
    assert u.disabled is False


@pytest.mark.asyncio
async def test_create_user_rejects_unknown_role(session: AsyncSession):
    with pytest.raises(users_service.UserStoreError):
        await users_service.create_user(
            session, sub="alice", password="hunter2", role="admine"
        )


@pytest.mark.asyncio
async def test_create_user_rejects_empty_inputs(session: AsyncSession):
    for kw in (
        {"sub": "", "password": "hunter2", "role": "red"},
        {"sub": "alice", "password": "", "role": "red"},
        {"sub": "alice", "password": "hunter2", "role": ""},
        {"sub": "   ", "password": "hunter2", "role": "red"},
    ):
        with pytest.raises(users_service.UserStoreError):
            await users_service.create_user(session, **kw)


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_sub(session: AsyncSession):
    await users_service.create_user(
        session, sub="alice", password="hunter2", role="red"
    )
    await session.commit()
    with pytest.raises(users_service.DuplicateSubError):
        await users_service.create_user(
            session, sub="alice", password="different", role="blue"
        )


@pytest.mark.asyncio
async def test_create_user_accepts_all_roles(session: AsyncSession):
    """Every Role enum value should be accepted."""
    for role in Role:
        u = await users_service.create_user(
            session, sub=f"u_{role.value}", password="hunter2", role=role.value
        )
        assert u.role == role.value
        await session.rollback()  # clean between iterations


# ---------- authenticate -------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_happy_path(session: AsyncSession):
    await users_service.create_user(
        session, sub="alice", password="hunter2", role="red"
    )
    await session.commit()
    user = await users_service.authenticate(
        session, sub="alice", password="hunter2"
    )
    assert user is not None
    assert user.sub == "alice"


@pytest.mark.asyncio
async def test_authenticate_wrong_password_returns_none(session: AsyncSession):
    await users_service.create_user(
        session, sub="alice", password="hunter2", role="red"
    )
    await session.commit()
    assert (
        await users_service.authenticate(
            session, sub="alice", password="WRONG"
        )
        is None
    )


@pytest.mark.asyncio
async def test_authenticate_unknown_sub_returns_none(session: AsyncSession):
    assert (
        await users_service.authenticate(
            session, sub="ghost", password="anything"
        )
        is None
    )


@pytest.mark.asyncio
async def test_authenticate_disabled_returns_none(session: AsyncSession):
    u = await users_service.create_user(
        session, sub="alice", password="hunter2", role="red"
    )
    u.disabled = True
    await session.commit()
    assert (
        await users_service.authenticate(
            session, sub="alice", password="hunter2"
        )
        is None
    )


@pytest.mark.asyncio
async def test_authenticate_empty_inputs_return_none(session: AsyncSession):
    assert await users_service.authenticate(session, sub="", password="x") is None
    assert await users_service.authenticate(session, sub="x", password="") is None


# ---------- POST /auth/login (router) ------------------------------------


@pytest.fixture
async def seeded():
    """Seed three users via the app's own sessionmaker.

    We can't reuse the local ``session`` fixture because it lives in
    a separate in-memory engine; the TestClient's request handlers
    open their own sessions via ``get_sessionmaker()``. Sharing the
    app's sessionmaker is the only way the seed rows are visible
    to the login endpoint.

    Cleans the users table first so tests are order-independent
    against the file-backed SQLite that the conftest creates.
    """
    from app.db import models as db_models
    from app.db.session import get_sessionmaker
    from sqlalchemy import delete

    sm = get_sessionmaker()
    async with sm() as s:
        await s.execute(delete(db_models.User))
        await s.commit()
    async with sm() as s:
        await users_service.create_user(s, sub="admin-user", password="hunter2", role="admin")
        await users_service.create_user(s, sub="red-user", password="hunter2", role="red")
        await users_service.create_user(s, sub="ghost", password="hunter2", role="blue")
        g = await users_service.get_by_sub(s, "ghost")
        assert g is not None
        g.disabled = True
        await s.commit()
    return {"admin": "admin-user", "red": "red-user", "disabled": "ghost"}


def test_login_happy_path(client: TestClient, seeded):
    r = client.post(
        "/api/v1/auth/login",
        json={"sub": "admin-user", "password": "hunter2"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "token" in body and "." in body["token"]
    assert body["sub"] == "admin-user"
    assert body["role"] == "admin"
    assert body["iat"] > 0
    assert body["exp"] > body["iat"]
    assert body["ttl_remaining_s"] > 0


def test_login_bad_password_returns_generic_401(client: TestClient, seeded):
    r = client.post(
        "/api/v1/auth/login",
        json={"sub": "admin-user", "password": "WRONG"},
    )
    assert r.status_code == 401
    # Generic message — no enumeration.
    assert r.json()["detail"] == "invalid credentials"


def test_login_unknown_sub_returns_same_401(client: TestClient, seeded):
    r = client.post(
        "/api/v1/auth/login",
        json={"sub": "ghost-user", "password": "hunter2"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


def test_login_disabled_returns_401(client: TestClient, seeded):
    r = client.post(
        "/api/v1/auth/login",
        json={"sub": "ghost", "password": "hunter2"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


def test_login_bad_body_returns_422(client: TestClient):
    r = client.post("/api/v1/auth/login", json={"sub": "", "password": ""})
    assert r.status_code == 422


def test_login_missing_fields_returns_422(client: TestClient):
    r = client.post("/api/v1/auth/login", json={"sub": "x"})
    assert r.status_code == 422


def test_login_response_never_includes_password_hash(client: TestClient, seeded):
    r = client.post(
        "/api/v1/auth/login",
        json={"sub": "admin-user", "password": "hunter2"},
    )
    assert r.status_code == 200
    assert "password" not in r.json()
    assert "password_hash" not in r.json()


# ---------- rate-limit on login ------------------------------------------


def test_login_rate_limited_after_5_failures(client: TestClient, seeded, fake_redis):
    """Six failed attempts -> 429 on the sixth."""
    # Use the same sub so the bucket fills.
    for i in range(5):
        r = client.post(
            "/api/v1/auth/login",
            json={"sub": "admin-user", "password": f"WRONG{i}"},
        )
        assert r.status_code == 401, f"attempt {i}: {r.text}"
    r = client.post(
        "/api/v1/auth/login",
        json={"sub": "admin-user", "password": "WRONG6"},
    )
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert "rate limit" in detail.lower() or "too many" in detail.lower()


def test_login_rate_limit_per_sub_does_not_block_other_subs(
    client: TestClient, seeded, fake_redis
):
    """Failed attempts on sub A don't lock out sub B."""
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"sub": "admin-user", "password": "WRONG"},
        )
    # B (red-user) should still be able to log in.
    r = client.post(
        "/api/v1/auth/login",
        json={"sub": "red-user", "password": "hunter2"},
    )
    assert r.status_code == 200


def test_login_successful_does_not_consume_bucket(
    client: TestClient, seeded, fake_redis
):
    """A successful login does not increment the failure bucket."""
    # 4 failures + 1 success + check that 1 more failure is allowed.
    for i in range(4):
        client.post(
            "/api/v1/auth/login",
            json={"sub": "admin-user", "password": f"WRONG{i}"},
        )
    ok = client.post(
        "/api/v1/auth/login",
        json={"sub": "admin-user", "password": "hunter2"},
    )
    assert ok.status_code == 200
    # The 5th failure (which would normally trigger 429) should still
    # be a 401 because the success didn't increment the bucket.
    r = client.post(
        "/api/v1/auth/login",
        json={"sub": "admin-user", "password": "WRONG5"},
    )
    assert r.status_code == 401


# ---------- GET /auth/users (admin only) ---------------------------------


def test_users_list_anonymous_returns_401(client: TestClient):
    r = client.get("/api/v1/auth/users")
    assert r.status_code == 401


def test_users_list_red_returns_403(client: TestClient, seeded):
    from app.core.auth import sign_token

    token = sign_token(sub="red-user", role="red", ttl_s=600)
    r = client.get("/api/v1/auth/users", headers={"X-Divide-Token": token})
    assert r.status_code == 403


def test_users_list_admin_returns_rows(client: TestClient, seeded):
    from app.core.auth import sign_token

    token = sign_token(sub="admin-user", role="admin", ttl_s=600)
    r = client.get("/api/v1/auth/users", headers={"X-Divide-Token": token})
    assert r.status_code == 200
    rows = r.json()
    subs = {row["sub"] for row in rows}
    assert subs == {"admin-user", "red-user", "ghost"}


def test_users_list_does_not_leak_password_hash(client: TestClient, seeded):
    from app.core.auth import sign_token

    token = sign_token(sub="admin-user", role="admin", ttl_s=600)
    r = client.get("/api/v1/auth/users", headers={"X-Divide-Token": token})
    assert r.status_code == 200
    for row in r.json():
        assert "password" not in row
        assert "password_hash" not in row
        # Public fields are present.
        assert {"sub", "role", "disabled", "last_login_at", "created_at"} <= set(row.keys())


def test_users_list_disabled_field_is_visible(client: TestClient, seeded):
    from app.core.auth import sign_token

    token = sign_token(sub="admin-user", role="admin", ttl_s=600)
    r = client.get("/api/v1/auth/users", headers={"X-Divide-Token": token})
    rows = r.json()
    by_sub = {row["sub"]: row for row in rows}
    assert by_sub["ghost"]["disabled"] is True
    assert by_sub["admin-user"]["disabled"] is False


# ---------- POST /auth/logout ---------------------------------------------


def test_logout_returns_ok(client: TestClient):
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_logout_requires_no_auth(client: TestClient):
    # Stateless: should work whether you have a token or not.
    r1 = client.post("/api/v1/auth/logout")
    assert r1.status_code == 200
    r2 = client.post("/api/v1/auth/logout", headers={"X-Divide-Token": "garbage"})
    assert r2.status_code == 200
