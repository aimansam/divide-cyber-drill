"""F8: in-process event bus for live SSE.

The bus is a tiny pub/sub for TelemetryEvent-shaped dicts:

  * ``publish(event)`` -- add an event to the ring buffer + fan
    out to all subscribed ``asyncio.Queue`` instances.
  * ``subscribe()`` -- return a queue + an ``unsubscribe`` handle.
    SSE handlers use this to wait for the next event.
  * ``recent(n)`` -- the last ``n`` events from the ring buffer.
    Used by ``GET /runs/{id}/events/recent`` for cold-connect
    replay.

Persistence is *separate* from the bus. The bus is a transient
fan-out -- it does not survive process restart. The DB is the
durable record (insert in ``app.routers.events.ingest``).

Why an in-process bus?
  * SSE handlers run inside the same Python process as the API.
    A bus is the cheapest fan-out.
  * Multi-worker deployments (uvicorn workers > 1) mean the
    subscriber and the publisher may live in different processes.
    For F8 we accept this: each worker only fans out events it
    sees. Live cross-worker events are deferred to F8.5 with
    Redis pub/sub or similar.

Why a ring buffer?
  * ``recent(n)`` is O(1) -- a single list slice.
  * Bounded memory: even a busy range producing 1k events/sec
    stays well under 1 MB of buffer.
"""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable


# Ring buffer size: 1024 events. ~64 KB for typical events;
# ~256 KB worst case (full payload). Plenty for SSE reconnect
# windows (which are typically < 30 sec).
_RING_SIZE = 1024


class EventBus:
    """Per-process pub/sub for TelemetryEvent-shaped dicts."""

    def __init__(self) -> None:
        # Ring buffer of events (newest at the right).
        self._buffer: deque = deque(maxlen=_RING_SIZE)
        # Live subscribers (asyncio queues).
        self._subscribers: list[asyncio.Queue] = []
        # Thread-safe lock for buffer + subscriber list mutations.
        self._lock = Lock()

    def publish(self, event: dict[str, Any]) -> None:
        """Add an event to the buffer + fan out to subscribers.

        Idempotent on ``id``: if an event with the same id is
        already in the buffer, we skip. This matters because a
        publisher retry shouldn't produce duplicate SSE events.
        """
        # The ``id`` field is the DB primary key. We use it for
        # dedup; an event without id (custom payload) is always
        # appended.
        ev_id = event.get("id")
        with self._lock:
            if ev_id is not None:
                for existing in self._buffer:
                    if existing.get("id") == ev_id:
                        return  # already published
            # Insert at the right (newest).
            self._buffer.append(event)
            # Snapshot subscribers under the lock to avoid races
            # where a subscriber unsubscribes mid-iteration.
            subs = list(self._subscribers)
        # Fan out (no lock; queues are thread-safe via asyncio).
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer; drop. SSE handlers should always
                # have a bounded queue so they don't leak memory.
                pass

    def subscribe(self, maxsize: int = 256) -> tuple[asyncio.Queue, Callable[[], None]]:
        """Return ``(queue, unsubscribe)``.

        ``queue.get()`` returns the next event. The handler is
        responsible for draining the queue.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(q)

        def _unsub() -> None:
            with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)

        return q, _unsub

    def recent(self, n: int = 50) -> list[dict[str, Any]]:
        """Return up to the last ``n`` events (newest last)."""
        with self._lock:
            buf = list(self._buffer)
        return buf[-n:]


# Singleton -- one bus per process. Reset between pytest
# runs via ``reset_for_tests()`` if needed.
bus = EventBus()


def reset_for_tests() -> None:
    """Clear the bus. Test-only."""
    with bus._lock:
        bus._buffer.clear()
        bus._subscribers.clear()


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp. Used as ``ts`` when caller doesn't
    supply one."""
    return datetime.now(timezone.utc).isoformat()
