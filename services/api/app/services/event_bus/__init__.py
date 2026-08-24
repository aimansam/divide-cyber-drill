"""F8 + R1: event bus for live SSE telemetry.

This package exposes a single ``EventBus`` Protocol with two
implementations:

  * ``InProcessEventBus`` -- the original F8 ring buffer +
    asyncio pub/sub. Cheap, single-worker.
  * ``RedisEventBus`` -- backed by Redis pub/sub + a Redis
    LIST used as a ring buffer. Cross-worker fan-out.

Selection is by env var:

  * ``DIVIDE_EVENT_BUS=redis`` + reachable Redis       -> RedisEventBus
  * ``DIVIDE_EVENT_BUS=memory`` (or unset)            -> InProcessEventBus
  * anything else                                      -> InProcessEventBus (with a warning)

See ``build_event_bus()`` at the bottom of this module for the
exact rules. The factory is the only supported entry point; the
``bus`` symbol re-exports the in-process singleton for backward
compatibility with pre-R1 code.

API (both implementations, sync):

  * ``publish(event)`` -- add an event to the ring buffer +
    fan out to all subscribed listeners. Idempotent on ``id``.
  * ``subscribe()`` -- return ``(queue, unsubscribe)``. SSE
    handlers use the queue to await the next event.
  * ``recent(n)`` -- the last ``n`` events from the ring buffer
    (newest last). Used by ``GET /runs/{id}/events/recent`` for
    cold-connect replay.

Why a Protocol (not an ABC)?
  * No shared state on the type itself; each impl owns its
    own buffer / connection pool.
  * ``@runtime_checkable`` lets tests assert ``isinstance(bus,
    EventBus)`` without paying the ABCMeta cost.
  * Adding a third backend (NATS, Kafka, ...) is a new module +
    one new ``elif`` in ``build_event_bus()``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, runtime_checkable

from .in_process import InProcessEventBus

__all__ = [
    "EventBus",
    "InProcessEventBus",
    "RedisEventBus",
    "build_event_bus",
    "utcnow_iso",
    "bus",              # legacy alias -- pre-R1 code imports it
    "reset_for_tests",
]


_log = logging.getLogger(__name__)


@runtime_checkable
class EventBus(Protocol):
    """Protocol every event-bus implementation must satisfy.

    F8 shipped ``InProcessEventBus`` (in-process ring buffer).
    R1 adds ``RedisEventBus`` (Redis pub/sub + LIST-based ring
    buffer). The rest of the codebase only depends on this
    Protocol; the factory below picks the right backend.

    All methods are SYNC because the F8 callers (``app.routers.events``
    and ``app.services.event_recorder``) call them as sync methods
    from inside async handlers. The async-ness of the Redis backend
    is hidden inside a daemon thread that bridges pub/sub messages
    into per-subscriber queues.
    """

    def publish(self, event: dict[str, Any]) -> None:
        """Add an event to the buffer + fan out to subscribers.

        Implementations MUST dedup on ``event["id"]``: a publish
        with an ``id`` that's already in the buffer is a no-op.
        """
        ...

    def subscribe(
        self, maxsize: int = 256
    ) -> "tuple[Any, Callable[[], None]]":
        """Return ``(queue, unsubscribe)``.

        ``queue.get()`` returns the next event. ``unsubscribe()``
        detaches the subscriber; safe to call multiple times.
        """
        ...

    def recent(self, n: int = 50) -> list[dict[str, Any]]:
        """Return up to the last ``n`` events (newest last)."""
        ...


def build_event_bus() -> EventBus:
    """Factory: pick the right backend based on env vars.

    Selection rules (in order):

      1. ``DIVIDE_EVENT_BUS=redis``                     -> RedisEventBus
      2. ``DIVIDE_EVENT_BUS=memory`` (or unset)        -> InProcessEventBus
      3. anything else                                  -> InProcessEventBus
         (with a warning, so misconfig is loud)

    The factory caches the result per-process; tests can call
    ``reset_for_tests()`` to drop the cached singleton + reset
    the in-process bus buffer.

    Note: we only check the env var here, not Redis reachability.
    A failed Redis connection surfaces when ``RedisEventBus`` is
    actually used (subscribe() / publish()).
    """
    override = os.environ.get("DIVIDE_EVENT_BUS", "").strip().lower()
    if override == "redis":
        from .redis_bus import RedisEventBus

        from app.core.config import settings

        _log.info("event_bus: RedisEventBus selected (DIVIDE_EVENT_BUS=redis)")
        return RedisEventBus(settings.redis_url)

    if override not in ("", "memory"):
        _log.warning(
            "unknown DIVIDE_EVENT_BUS=%r; falling back to in-process bus",
            override,
        )

    return _in_process_singleton()


# --- in-process singleton (legacy alias) --------------------------------

_in_process_bus = InProcessEventBus()


def _in_process_singleton() -> InProcessEventBus:
    """Return the module-level in-process bus."""
    return _in_process_bus


def reset_for_tests() -> None:
    """Clear the in-process bus. Test-only."""
    _in_process_bus.reset()


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp. Used as ``ts`` when caller doesn't
    supply one."""
    return datetime.now(timezone.utc).isoformat()


# Backward-compat alias. Pre-R1 code did
# ``from app.services.event_bus import bus``. Keep the symbol
# working so we don't need a sweeping import rename.
bus: EventBus = _in_process_bus
