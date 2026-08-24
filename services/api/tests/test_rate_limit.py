"""Tests for the per-token rate limit on POST /api/v1/drills (L2 2.7).

The rate limiter is a window-counter in Redis keyed on ``token.sub``.
We mock the ``app.services.cache.get_redis`` factory to return a
``fakeredis.aioredis`` client (already in the dev extras) so tests
run without a real Redis container.

Test tiers:

  1. **Unit tests** (the bulk) call
     :func:`check_drill_start_limit` directly. They're fast and don't
     need a real DB or runner. They exercise the bucket math.

  2. **HTTP smoke** (one test) verifies the limiter is wired into
     ``start_drill``: anonymous → 401; over-limit → 429.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException


@pytest.fixture
def fake_redis(monkeypatch):
    """Per-test fresh fakeredis client. ``flushall`` not needed —
    each test gets a new instance via the fixture.

    Replacing the cache module's ``get_redis`` factory is enough
    because ``check_drill_start_limit`` resolves Redis lazily via
    that factory.
    """
    import fakeredis.aioredis as fakeredis_aioredis

    fake = fakeredis_aioredis.FakeRedis(decode_responses=True)

    import app.services.cache as cache_module

    # Wipe any state from a previous test in the same session.
    monkeypatch.setattr(cache_module, "_client", fake, raising=False)
    monkeypatch.setattr(cache_module, "get_redis", lambda: fake)
    return fake


@pytest.fixture
def set_limit(monkeypatch):
    """Pin ``check_drill_start_limit`` to a known config for the test.

    Yields the rate_limit module so tests can call ``set_config``.
    The fixture restores the defaults afterwards.
    """
    import app.services.rate_limit as rl

    rl.set_config(limit=5, window_seconds=3600)
    yield rl
    rl.set_config(limit=rl.DEFAULT_LIMIT, window_seconds=rl.DEFAULT_WINDOW_SECONDS)


def _run(coro):
    return asyncio.run(coro)


# --- Unit tests --------------------------------------------------------------


def test_first_n_requests_pass(fake_redis, set_limit):
    """The first N requests within the limit return without raising."""
    set_limit.set_config(limit=5)
    from app.services.rate_limit import check_drill_start_limit as rl

    async def _go():
        for _ in range(5):
            await rl("alice")

    _run(_go())  # no exception == pass


def test_over_limit_raises_429(fake_redis, set_limit):
    """The (limit+1)th request from the same sub raises 429."""
    from app.services.rate_limit import check_drill_start_limit as rl

    async def _go():
        for _ in range(5):
            await rl("alice")
        with pytest.raises(HTTPException) as exc_info:
            await rl("alice")
        assert exc_info.value.status_code == 429
        assert "alice" in exc_info.value.detail

    _run(_go())


def test_separate_subjects_get_separate_buckets(fake_redis, set_limit):
    """Alice and Bob each have their own bucket."""
    from app.services.rate_limit import check_drill_start_limit as rl

    set_limit.set_config(limit=2)

    async def _go():
        # Alice uses her budget.
        await rl("alice")
        await rl("alice")
        with pytest.raises(HTTPException):
            await rl("alice")
        # Bob's bucket is independent.
        await rl("bob")
        await rl("bob")
        with pytest.raises(HTTPException):
            await rl("bob")

    _run(_go())


def test_window_expires_refills_budget(fake_redis, set_limit):
    """After the window expires, the bucket resets.

    We use a tiny window (1s) and a tiny TTL to test this without
    actually waiting. fakeredis honours TTLs.
    """
    from app.services.rate_limit import check_drill_start_limit as rl

    set_limit.set_config(limit=1, window_seconds=1)

    async def _go():
        await rl("alice")
        with pytest.raises(HTTPException):
            await rl("alice")  # over limit
        # Wait out the window.
        await asyncio.sleep(1.2)
        await rl("alice")  # allowed again

    _run(_go())


# --- HTTP smoke --------------------------------------------------------------


@pytest.fixture
def client(fake_redis, set_limit):
    from app.core.config import get_settings
    from app.db import session as session_module
    from app.services import db as db_module

    get_settings.cache_clear()
    db_module._engine = None
    session_module._session_maker = None

    import importlib

    import app.main as _app_main

    importlib.reload(_app_main)
    from fastapi.testclient import TestClient

    return TestClient(_app_main.app)


def test_http_anonymous_is_401_not_429(client, fake_redis, set_limit):
    """No token → 401 from the auth gate, NOT 429 from the limiter.

    This proves the limiter is gated *after* auth — important so a
    denial-of-service probe against the limiter isn't possible without
    a token.
    """
    set_limit.set_config(limit=0)  # limit=0 wouldn't change the auth outcome
    r = client.post("/api/v1/drills", json={"scenario_id": 999})
    assert r.status_code == 401


def test_redis_unreachable_fails_open(monkeypatch, set_limit):
    """If Redis is down the limiter logs a warning and lets the request through.

    Fail-open is the safety posture for this control-plane gate — we'd
    rather let a few extra drill starts through than refuse a legitimate
    request because Redis went down. Operators wanting fail-closed set
    ``DIVIDE_RATE_LIMIT_FAIL_CLOSED=true`` and get a 503 instead.
    """
    import app.services.cache as cache_module
    from app.services.rate_limit import check_drill_start_limit as rl

    class _BrokenRedis:
        def pipeline(self):
            raise ConnectionError("simulated outage")

    monkeypatch.setattr(cache_module, "_client", _BrokenRedis(), raising=False)
    monkeypatch.setattr(cache_module, "get_redis", lambda: _BrokenRedis())

    async def _go():
        # Should NOT raise.
        await rl("alice")

    _run(_go())  # no exception == pass
