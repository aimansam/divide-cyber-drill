"""R1: RedisEventBus -- cross-worker event fan-out via Redis pub/sub.

This is the production backend for the EventBus Protocol. It
runs across uvicorn workers (and even across separate machines)
because state lives in Redis, not in any single Python process.

Schema
------

  * **Channel:** ``divide:events:global`` -- every published event
    hits this Redis pub/sub channel. Every worker subscribed to
    RedisEventBus receives a copy.
  * **Ring buffer:** Redis LIST ``divide:events:buffer`` -- capped
    at 1024 entries via ``LTRIM`` after every ``LPUSH``. Replaces
    the in-process ``deque(maxlen=1024)``.

Why one global channel (not per-run)?
  * Each subscriber filters by run_id client-side (the SSE
    generator already does this). A per-run channel would force
    every worker to maintain a per-run subscription, which adds
    book-keeping and doesn't reduce noise meaningfully -- events
    are tiny.
  * Per-run channels make cold-reconnect more expensive (the
    new worker has to ``SUBSCRIBE`` to every run_id it cares about).
  * We can revisit with a per-run sharding scheme in a future
    plan if fan-out gets too noisy at 100+ runs.

Sync API (matching the EventBus Protocol)
----------------------------------------

The F8 callers (``app.routers.events``, ``app.services.event_recorder``)
call ``bus.publish(event)`` / ``bus.recent(n)`` / ``bus.subscribe()``
as **sync** methods. RedisEventBus therefore uses the **sync**
``redis.Redis`` client (not ``redis.asyncio``).

Internally a daemon thread runs an asyncio event loop to bridge
the Redis pub/sub async client into per-subscriber
``queue.Queue`` instances. Publishers + recent() use the sync
client directly; subscribers register a callback that gets
invoked from the bridge thread.
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue as _queue
import threading
from typing import Any, Callable

import redis as redis_sync

_log = logging.getLogger(__name__)


_CHANNEL = "divide:events:global"
_BUFFER_KEY = "divide:events:buffer"
_RING_SIZE = 1024
_SUBSCRIBE_QUEUE_MAX = 256


class RedisEventBus:
    """Redis-backed event bus for multi-worker deployments.

    Implements the ``EventBus`` Protocol from
    ``app.services.event_bus.__init__``. Sync API only --
    matches the F8 in-process bus shape.
    """

    def __init__(
        self,
        url: str,
        *,
        sync_client: redis_sync.Redis | None = None,
        async_client_factory: "Callable[[], Any] | None" = None,
    ) -> None:
        """Construct a Redis-backed event bus.

        ``url`` is used to build the default sync + async clients.
        Tests can pass ``sync_client`` / ``async_client_factory``
        to inject fakeredis-backed clients so the bus works
        without a real Redis server.

        ``async_client_factory`` is called once when the bridge
        starts. It must return an object that behaves like an
        ``redis.asyncio.Redis`` (with ``pubsub()``, ``aclose()``).
        """
        self._url = url
        # Sync client for publish + recent. redis-py handles
        # connection pooling internally.
        self._client = sync_client or redis_sync.from_url(
            url, encoding="utf-8", decode_responses=True
        )
        self._async_client_factory = async_client_factory
        # Bridge thread: runs an asyncio loop that listens on
        # the Redis pub/sub channel and forwards messages to
        # per-subscriber queues. Lazily started on first subscribe().
        self._bridge_thread: threading.Thread | None = None
        self._bridge_started = threading.Event()
        self._bridge_stop = threading.Event()
        self._bridge_error: BaseException | None = None
        self._lock = threading.Lock()
        # Subscriber queues registered in this process. The bridge
        # pushes events here; the SSE handler drains them.
        self._subscribers: list[_queue.Queue] = []

    # --- lifecycle -----------------------------------------------------

    def close(self) -> None:
        """Tear down the bridge thread + close the redis pool.

        Tests + lifespan handlers call this. Production code
        generally lets the process exit clean it up.
        """
        self._bridge_stop.set()
        if self._bridge_thread is not None and self._bridge_thread.is_alive():
            self._bridge_thread.join(timeout=2.0)
        try:
            self._client.close()
        except Exception:  # pragma: no cover
            pass

    # --- protocol methods ---------------------------------------------

    def publish(self, event: dict[str, Any]) -> None:
        """LPUSH to ring buffer + PUBLISH on the channel.

        Idempotent on ``event["id"]``: a publish with an ``id``
        already in the buffer is a no-op. We check by reading
        the last 32 entries (cheap LRANGE) -- if we find a match,
        we skip.
        """
        ev_id = event.get("id")
        if ev_id is not None:
            recent_raw = self._client.lrange(_BUFFER_KEY, 0, 31)
            for raw in recent_raw:
                try:
                    existing = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if existing.get("id") == ev_id:
                    return  # dedup hit
        payload = json.dumps(event, default=str)
        pipe = self._client.pipeline(transaction=True)
        pipe.lpush(_BUFFER_KEY, payload)
        pipe.ltrim(_BUFFER_KEY, 0, _RING_SIZE - 1)
        pipe.publish(_CHANNEL, payload)
        pipe.execute()
        # Local fan-out (in-process subscribers). The Redis pub/sub
        # path will fan out to other workers; this loop handles the
        # subscribers in *this* process (the publisher's own workers).
        with self._lock:
            local_subs = list(self._subscribers)
        for q in local_subs:
            try:
                q.put_nowait(event)
            except _queue.Full:
                pass

    def subscribe(
        self, maxsize: int = _SUBSCRIBE_QUEUE_MAX
    ) -> tuple[_queue.Queue, Callable[[], None]]:
        """Return ``(queue, unsubscribe)``.

        The queue is filled by replaying the buffer + the live
        pub/sub forwarder. Dedup is by ``event["id"]``; an event
        that's in both the replay and the live feed is delivered
        only once.
        """
        # Ensure the bridge is running before we read the buffer,
        # so we don't miss events that arrive between LRANGE and
        # the subscriber going live.
        self._ensure_bridge()

        q: _queue.Queue = _queue.Queue(maxsize=maxsize)

        # 1. Replay from the ring buffer (LRANGE returns newest-first).
        raw_events = self._client.lrange(_BUFFER_KEY, 0, _RING_SIZE - 1)
        seen: set[Any] = set()
        for raw in reversed(raw_events):  # reverse for FIFO delivery
            try:
                ev = json.loads(raw)
            except (TypeError, ValueError):
                continue
            ev_id = ev.get("id")
            if ev_id is not None:
                if ev_id in seen:
                    continue
                seen.add(ev_id)
            try:
                q.put_nowait(ev)
            except _queue.Full:
                break  # bounded queue; drop oldest un-read events

        # 2. Register for live fan-out.
        # The bridge dedups against the events we've already queued
        # so we don't re-deliver a replayed event.
        q.__dict__["_redis_seen"] = seen  # type: ignore[attr-defined]
        with self._lock:
            self._subscribers.append(q)

        def _unsub() -> None:
            with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)

        return q, _unsub

    def recent(self, n: int = 50) -> list[dict[str, Any]]:
        """Return up to the last ``n`` events (newest last)."""
        raw_events = self._client.lrange(_BUFFER_KEY, 0, n - 1)
        out: list[dict[str, Any]] = []
        for raw in reversed(raw_events):  # LRANGE newest-first -> reverse
            try:
                out.append(json.loads(raw))
            except (TypeError, ValueError):
                continue
        return out[-n:]

    # --- internals -----------------------------------------------------

    def _ensure_bridge(self) -> None:
        """Start the bridge thread (idempotent).

        The bridge runs an asyncio loop + an ``redis.asyncio``
        pubsub subscription. It forwards messages into
        ``_subscribers`` queues. Only one bridge per process.
        """
        if self._bridge_thread is not None and self._bridge_thread.is_alive():
            return
        # Reset state for a fresh thread (e.g., after a previous failure).
        self._bridge_started.clear()
        self._bridge_stop.clear()
        self._bridge_error = None
        self._bridge_thread = threading.Thread(
            target=self._bridge_main,
            name="redis-event-bus-bridge",
            daemon=True,
        )
        self._bridge_thread.start()
        # Wait for the bridge to actually subscribe to the channel.
        # Bounded to avoid hanging tests on a bad Redis URL.
        if not self._bridge_started.wait(timeout=5.0):
            raise RuntimeError(
                "RedisEventBus: bridge thread failed to start within 5s; "
                "is Redis reachable at %s?" % self._url
            )
        if self._bridge_error is not None:
            raise self._bridge_error

    def _bridge_main(self) -> None:
        """Bridge-thread entry point: own asyncio loop, listen to pub/sub.

        This function is the **only** async code in RedisEventBus --
        the rest of the class is sync because that's the EventBus
        Protocol contract.
        """
        try:
            asyncio.run(self._bridge_async())
        except BaseException as e:  # pragma: no cover
            self._bridge_error = e
            self._bridge_started.set()

    async def _bridge_async(self) -> None:
        """Async body: subscribe + forward to local queues."""
        if self._async_client_factory is not None:
            async_client = self._async_client_factory()
        else:
            import redis.asyncio as redis_asyncio

            async_client = redis_asyncio.from_url(
                self._url, encoding="utf-8", decode_responses=True
            )
        pubsub = async_client.pubsub()
        try:
            await pubsub.subscribe(_CHANNEL)
            self._bridge_started.set()
            while not self._bridge_stop.is_set():
                # poll=True keeps the loop responsive to stop.
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.5
                )
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue
                try:
                    event = json.loads(message["data"])
                except (TypeError, ValueError, KeyError):
                    _log.warning("redis_event_bus: malformed frame %r", message)
                    continue
                self._forward(event)
        finally:
            try:
                await pubsub.unsubscribe(_CHANNEL)
                await pubsub.aclose()
                await async_client.aclose()
            except Exception:  # pragma: no cover
                pass

    def _forward(self, event: dict[str, Any]) -> None:
        """Push ``event`` to every subscriber queue (dedup'd)."""
        with self._lock:
            local_subs = list(self._subscribers)
        ev_id = event.get("id")
        for q in local_subs:
            seen = q.__dict__.get("_redis_seen")  # type: ignore[attr-defined]
            if seen is not None and ev_id is not None:
                if ev_id in seen:
                    seen.discard(ev_id)  # consume -- next time it's "new"
                    continue
            try:
                q.put_nowait(event)
            except _queue.Full:
                pass
