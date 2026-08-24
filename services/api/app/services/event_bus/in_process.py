"""F8 InProcessEventBus: in-process ring buffer + asyncio pub/sub.

See ``app.services.event_bus.__init__`` for the API contract
(``EventBus`` Protocol) and the factory that selects this
backend by default.
"""
from __future__ import annotations

import asyncio
from collections import deque
from threading import Lock
from typing import Any, Callable


# Ring buffer size: 1024 events. ~64 KB for typical events;
# ~256 KB worst case (full payload). Plenty for SSE reconnect
# windows (which are typically < 30 sec).
_RING_SIZE = 1024


class InProcessEventBus:
    """Single-process pub/sub for TelemetryEvent-shaped dicts.

    Lock-protected ring buffer + a list of asyncio.Queue
    subscribers. See ``app.services.event_bus.__init__`` for
    the Protocol this class implements.
    """

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

    def subscribe(
        self, maxsize: int = 256
    ) -> tuple[asyncio.Queue, Callable[[], None]]:
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

    def reset(self) -> None:
        """Clear the buffer + subscribers. Test-only.

        Replaces the module-level ``reset_for_tests()`` from
        pre-R1 code; the package's ``__init__.py`` exposes a
        convenience wrapper that delegates here.
        """
        with self._lock:
            self._buffer.clear()
            self._subscribers.clear()
