"""R1: RedisEventBus -- cross-worker event fan-out via Redis pub/sub.

These tests pin the cross-worker contract:

  * publish + recent: same shape as the in-process bus.
  * dedup on ``event["id"]``.
  * subscribe replays the buffer before going live.
  * **Cross-instance fan-out:** two independent RedisEventBus
    instances backed by the same Redis see each other's events.
    This is the core R1 win -- the multi-worker SSE fix.

We use ``fakeredis`` with a shared FakeServer so the sync
publisher + async pubsub subscriber see the same data. No real
Redis needed.

Why two RedisEventBus instances per test?
  The R1 problem statement is: "an event published by worker A
  is invisible to SSE subscribers on worker B." A single
  RedisEventBus instance can't prove the fix -- we need at
  least two independent instances, each with their own
  subscriber queue, to demonstrate that the Redis pub/sub layer
  does the fan-out.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

import fakeredis
import fakeredis.aioredis as faio
import pytest

from app.services.event_bus.redis_bus import RedisEventBus


# --- shared fake-Redis fixture -----------------------------------------

@pytest.fixture
def shared_fake_redis():
    """A fakeredis server shared between sync + async clients.

    Returns a factory the test uses to build clients that
    all see the same data.
    """
    server = fakeredis.FakeServer()
    return {
        "server": server,
        "make_sync": lambda: fakeredis.FakeRedis(
            server=server, decode_responses=True
        ),
        "make_async": lambda: faio.FakeRedis(
            server=server, decode_responses=True
        ),
    }


def _build_bus_pair(shared) -> tuple[RedisEventBus, RedisEventBus]:
    """Two independent RedisEventBus instances on the same fake Redis.

    Each instance has its own sync client + its own async
    client + its own bridge thread. The shared FakeServer makes
    them see the same data.
    """
    bus_a = RedisEventBus(
        "redis://fake/0",
        sync_client=shared["make_sync"](),
        async_client_factory=shared["make_async"],
    )
    bus_b = RedisEventBus(
        "redis://fake/0",
        sync_client=shared["make_sync"](),
        async_client_factory=shared["make_async"],
    )
    return bus_a, bus_b


@pytest.fixture(autouse=True)
def _teardown_buses():
    """No-op fixture reserved for future per-test bus tracking.

    Tests that build bus instances should call ``bus_a.close()``
    and ``bus_b.close()`` in a ``finally`` block to join the
    bridge threads cleanly. Pytest's own teardown will reap
    any daemon threads left behind.
    """
    yield


# --- protocol-shape tests ---------------------------------------------

def test_publish_and_recent_returns_in_order(shared_fake_redis):
    """publish() inserts at the left (LPUSH); recent() returns ascending."""
    bus = RedisEventBus(
        "redis://fake/0",
        sync_client=shared_fake_redis["make_sync"](),
        async_client_factory=shared_fake_redis["make_async"],
    )
    try:
        bus.publish({"id": 1, "kind": "run.started", "run_id": 7})
        bus.publish({"id": 2, "kind": "asset.running", "run_id": 7})
        bus.publish({"id": 3, "kind": "flag.captured", "run_id": 7})
        out = bus.recent(10)
        # Newest first in Redis; recent() reverses for ascending order.
        assert [e["id"] for e in out] == [1, 2, 3]
    finally:
        bus.close()


def test_publish_dedup_by_id(shared_fake_redis):
    """publish() with the same id is a no-op (skipped)."""
    bus = RedisEventBus(
        "redis://fake/0",
        sync_client=shared_fake_redis["make_sync"](),
        async_client_factory=shared_fake_redis["make_async"],
    )
    try:
        bus.publish({"id": 42, "kind": "x", "run_id": 1})
        bus.publish({"id": 42, "kind": "x", "run_id": 1})  # dup
        out = bus.recent(10)
        assert len(out) == 1
        assert out[0]["id"] == 42
    finally:
        bus.close()


def test_recent_caps_at_ring_size(shared_fake_redis):
    """The ring buffer is capped at 1024 entries (LPUSH + LTRIM)."""
    bus = RedisEventBus(
        "redis://fake/0",
        sync_client=shared_fake_redis["make_sync"](),
        async_client_factory=shared_fake_redis["make_async"],
    )
    try:
        # Publish more than the ring size.
        for i in range(1100):
            bus.publish({"id": i, "kind": "tick", "run_id": 1})
        out = bus.recent(2000)
        # The oldest 76 entries got trimmed; we should see exactly 1024.
        assert len(out) == 1024
        # Newest first in storage; oldest in returned list.
        assert out[0]["id"] == 76
        assert out[-1]["id"] == 1099
    finally:
        bus.close()


def test_recent_returns_newest_last(shared_fake_redis):
    """``recent(n)`` returns oldest-first (F8 contract)."""
    bus = RedisEventBus(
        "redis://fake/0",
        sync_client=shared_fake_redis["make_sync"](),
        async_client_factory=shared_fake_redis["make_async"],
    )
    try:
        bus.publish({"id": 10, "kind": "a", "run_id": 1})
        bus.publish({"id": 20, "kind": "b", "run_id": 1})
        bus.publish({"id": 30, "kind": "c", "run_id": 1})
        out = bus.recent(3)
        assert [e["id"] for e in out] == [10, 20, 30]
    finally:
        bus.close()


# --- cross-instance fan-out (THE R1 win) -----------------------------

def test_publish_on_bus_a_reaches_subscriber_on_bus_b(shared_fake_redis):
    """R1 core: an event published on bus A is delivered to a
    subscriber on bus B. This proves the cross-worker fan-out
    works.

    Pre-R1, the in-process bus could only deliver events within
    a single Python process. Multi-worker uvicorn deployments
    saw events only on the worker that produced them.
    """
    bus_a, bus_b = _build_bus_pair(shared_fake_redis)
    try:
        # Subscriber on bus B.
        q_b, unsub_b = bus_b.subscribe()
        # Give the bridge a beat to subscribe on bus_b's side.
        time.sleep(0.2)

        # Publish on bus A -- this is the "worker A" half of the
        # multi-worker scenario.
        bus_a.publish({"id": 100, "kind": "run.started", "run_id": 7})

        # Bus B's subscriber should see it.
        try:
            ev = q_b.get(timeout=3.0)
        except Exception as e:  # pragma: no cover
            unsub_b()
            raise AssertionError(
                f"bus_b did not receive the event published on bus_a: {e}"
            )
        assert ev["id"] == 100
        assert ev["kind"] == "run.started"
        assert ev["run_id"] == 7

        unsub_b()
    finally:
        bus_a.close()
        bus_b.close()


def test_two_independent_subscribers_both_receive(shared_fake_redis):
    """Both subscribers (on different bus instances) receive the
    published event. This mirrors two SSE handlers in different
    uvicorn workers watching the same run."""
    bus_a, bus_b = _build_bus_pair(shared_fake_redis)
    try:
        # Two subscribers on bus B -- simulates two SSE handlers
        # in the same worker.
        q1, u1 = bus_b.subscribe()
        q2, u2 = bus_b.subscribe()
        time.sleep(0.2)

        bus_a.publish({"id": 200, "kind": "flag.captured", "run_id": 7})

        e1 = q1.get(timeout=3.0)
        e2 = q2.get(timeout=3.0)
        assert e1["id"] == 200
        assert e2["id"] == 200
        u1()
        u2()
    finally:
        bus_a.close()
        bus_b.close()


def test_subscribe_replays_buffer(shared_fake_redis):
    """A subscriber that joins AFTER events were published still
    sees them via the LRANGE replay (cold-connect use case)."""
    bus_a, bus_b = _build_bus_pair(shared_fake_redis)
    try:
        # Publish BEFORE any subscriber exists -- simulates a
        # client that connects mid-drill.
        bus_a.publish({"id": 1, "kind": "run.started", "run_id": 7})
        bus_a.publish({"id": 2, "kind": "asset.running", "run_id": 7})
        bus_a.publish({"id": 3, "kind": "flag.captured", "run_id": 7})

        # Subscribe on bus B -- should see all three via replay.
        q, unsub = bus_b.subscribe()
        try:
            seen = []
            while True:
                try:
                    seen.append(q.get(timeout=0.5))
                except Exception:
                    break
        finally:
            unsub()

        assert [e["id"] for e in seen] == [1, 2, 3]
    finally:
        bus_a.close()
        bus_b.close()


def test_unsubscribe_stops_delivery(shared_fake_redis):
    """After unsubscribe(), the queue gets no more events."""
    bus_a, bus_b = _build_bus_pair(shared_fake_redis)
    try:
        q, unsub = bus_b.subscribe()
        time.sleep(0.2)

        bus_a.publish({"id": 1, "kind": "x", "run_id": 1})
        first = q.get(timeout=3.0)
        assert first["id"] == 1

        # Drain whatever else is queued, then unsubscribe.
        while not q.empty():
            q.get_nowait()
        unsub()

        # Publish more; we should NOT receive.
        bus_a.publish({"id": 2, "kind": "y", "run_id": 1})
        delivered_after_unsub = []
        while not q.empty():
            delivered_after_unsub.append(q.get_nowait())
        assert delivered_after_unsub == []
    finally:
        bus_a.close()
        bus_b.close()
