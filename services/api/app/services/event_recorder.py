"""F8: persist + fan-out TelemetryEvents.

The single entry point for emitting events from server-side
code (runner, flag capture, asset spawn, etc.). It:

  1. Inserts a ``TelemetryEvent`` row.
  2. Publishes to the in-process ``EventBus`` so SSE subscribers
     get it instantly.

Both operations are best-effort: a DB insert failure or a
publish failure does NOT raise -- telemetry is a side-channel.
Failing telemetry must never block the drill.

Why wrap both behind one function?

  * The runner / flag / asset paths all need to emit events.
    A single helper means we don't have 5 call sites that each
    do their own insert + publish.
  * Telemetry policy (best-effort vs. strict) lives in one place.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    TelemetryEvent,
    TelemetrySeverity,
)
from app.services.event_bus import bus


logger = logging.getLogger(__name__)


async def record_event(
    session: AsyncSession,
    *,
    run_id: int | None,
    asset_id: int | None = None,
    kind: str,
    source: str,
    severity: TelemetrySeverity = TelemetrySeverity.INFO,
    payload: dict[str, Any] | None = None,
    ts: datetime | None = None,
) -> TelemetryEvent | None:
    """Persist a TelemetryEvent + publish to the bus.

    Returns the persisted event (for tests) or ``None`` on
    failure (we log + swallow).

    Q14: do NOT roll back the outer transaction on telemetry
    failure. The runner does ``session.add(run); await
    session.flush()`` to populate ``run.id``, then calls
    ``record_event``, then continues to add assets with
    ``run_id=run.id``. If the telemetry insert fails and we
    rollback, the Run row disappears from the transaction and
    the subsequent Asset INSERT hits an FK violation with
    ``Key (run_id)=(N) is not present in table "runs"`` -- the
    catastrophic Q14 bug that turned POST /api/v1/drills into a
    raw 500.

    The fix: use ``session.begin_nested()`` (SAVEPOINT) so the
    telemetry insert is isolated from the outer transaction. If
    it fails, we rollback only the SAVEPOINT and return None.
    If it succeeds, we release the SAVEPOINT (no-op) so the
    outer transaction keeps both rows.
    """
    from sqlalchemy.exc import SQLAlchemyError

    payload = payload or {}
    ts = ts or datetime.now(timezone.utc)
    event = TelemetryEvent(
        run_id=run_id,
        asset_id=asset_id,
        ts=ts,
        source=source,
        kind=kind,
        severity=severity,
        payload=payload,
    )
    try:
        # SAVEPOINT isolates telemetry from the outer transaction.
        # If the inner flush fails, only the SAVEPOINT rolls back;
        # the Run row (and any other prior work) survives.
        async with session.begin_nested():
            session.add(event)
            await session.flush()
    except SQLAlchemyError as exc:  # noqa: BLE001
        logger.warning(
            "F8 event_bus.record_event: db flush failed: %s", exc
        )
        return None
    serialized = {
        "id": event.id,
        "run_id": event.run_id,
        "asset_id": event.asset_id,
        "ts": event.ts.isoformat() if event.ts else None,
        "source": event.source,
        "kind": event.kind,
        "severity": event.severity.value,
        "payload": event.payload,
    }
    # Fan-out (in-process).
    try:
        bus.publish(serialized)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "F8 event_bus.record_event: bus.publish failed: %s", exc
        )
    return event
