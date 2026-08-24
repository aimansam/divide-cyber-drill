"""F8: TelemetryEvent ingest + recent + live-stream endpoints.

Endpoints:

  POST /runs/{run_id}/events                admin/lead -> inject a custom event
  GET  /runs/{run_id}/events                any role   -> recent events (history)
  GET  /runs/{run_id}/events/recent         any role   -> recent events (alias)
  GET  /runs/{run_id}/events/stream         any role   -> SSE live stream

The runner / flag-capture / asset-spawner also call into the
``EventBus`` directly to publish events; those bypass this
router (they don't need HTTP). Only the manual /inject path
goes through this router.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Role, current_token, require_role
from app.db import models as db_models
from app.db.models import Run, TelemetryEvent, TelemetrySeverity
from app.db.session import get_session
from app.services.event_bus import bus


router = APIRouter()


# --- helpers -----------------------------------------------------------


def _serialize_event(e: TelemetryEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "run_id": e.run_id,
        "asset_id": e.asset_id,
        "ts": e.ts.isoformat() if e.ts else None,
        "source": e.source,
        "kind": e.kind,
        "severity": e.severity.value if hasattr(e.severity, "value") else e.severity,
        "payload": e.payload,
    }


async def _load_run_or_404(session: AsyncSession, run_id: int) -> Run:
    run = (
        await session.execute(
            select(Run).where(Run.id == run_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run id={run_id} not found",
        )
    return run


# --- ingest (POST) -----------------------------------------------------


@router.post(
    "/runs/{run_id}/events",
    summary="Inject a TelemetryEvent for a run",
    dependencies=[Depends(require_role(Role.ADMIN, Role.LEAD))],
)
async def ingest_event(
    run_id: int,
    body: dict,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Manually inject a telemetry event.

    Body::

        {
          "kind": "kill-chain.signal",
          "severity": "high",
          "asset_id": 5,           # optional
          "ts": "2026-08-25T01:00:00Z",  # optional; now if missing
          "payload": {"message": "..."}
        }

    The runner / flag-capture path does NOT go through this
    endpoint; it calls ``app.services.event_bus.publish()``
    directly. This is for human-injected events.
    """
    kind = body.get("kind")
    severity_raw = body.get("severity", "info")
    asset_id = body.get("asset_id")
    ts_raw = body.get("ts")
    payload = body.get("payload") or {}
    if not isinstance(kind, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="kind must be a string",
        )
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="payload must be an object",
        )
    if not isinstance(asset_id, int) and asset_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="asset_id must be an int or null",
        )
    # Severity: accept string from the wire, validate against enum.
    try:
        severity = TelemetrySeverity(severity_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"severity must be one of "
                f"{[s.value for s in TelemetrySeverity]}"
            ),
        )
    # TS: accept ISO 8601, default to now (UTC).
    if ts_raw:
        try:
            ts = datetime.fromisoformat(
                ts_raw.replace("Z", "+00:00")
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="ts must be ISO 8601",
            )
    else:
        ts = datetime.now(timezone.utc)

    await _load_run_or_404(session, run_id)

    event = TelemetryEvent(
        run_id=run_id,
        asset_id=asset_id,
        ts=ts,
        source=getattr(token, "sub", "unknown"),
        kind=kind,
        severity=severity,
        payload=payload,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)

    serialized = _serialize_event(event)
    bus.publish(serialized)
    return serialized


# --- history (GET) -----------------------------------------------------


@router.get(
    "/runs/{run_id}/events",
    summary="List recent telemetry events for a run",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def list_events(
    run_id: int,
    limit: int = 100,
    severity: str | None = None,
    kind: str | None = None,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Return the most recent events for a run.

    Filters:
      * ``limit``: max events to return (default 100, capped 1000).
      * ``severity``: filter by severity bucket.
      * ``kind``: filter by event kind (exact match).
    """
    if limit < 1 or limit > 1000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="limit must be 1..1000",
        )
    await _load_run_or_404(session, run_id)
    stmt = (
        select(TelemetryEvent)
        .where(TelemetryEvent.run_id == run_id)
        .order_by(TelemetryEvent.ts.asc())
        .limit(limit)
    )
    if severity:
        try:
            stmt = stmt.where(
                TelemetryEvent.severity == TelemetrySeverity(severity)
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"unknown severity {severity!r}",
            )
    if kind:
        stmt = stmt.where(TelemetryEvent.kind == kind)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [_serialize_event(r) for r in rows],
        "total": len(rows),
        "run_id": run_id,
    }


@router.get(
    "/runs/{run_id}/events/recent",
    summary="Most recent events from the in-memory ring buffer",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def recent_events(
    run_id: int,
    n: int = 50,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Return up to ``n`` events from the in-process bus buffer.

    Used by the SOC dashboard on initial connect -- the SSE
    stream then takes over for new events.
    """
    if n < 1 or n > 1024:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="n must be 1..1024",
        )
    await _load_run_or_404(session, run_id)
    items = [
        e for e in bus.recent(n)
        if e.get("run_id") == run_id
    ]
    return {
        "items": items[-n:],
        "total": len(items),
        "run_id": run_id,
    }


# --- live SSE ----------------------------------------------------------


@router.get(
    "/runs/{run_id}/events/stream",
    summary="Server-Sent-Events live tail of telemetry events",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def stream_events(
    run_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> StreamingResponse:
    """SSE live stream of TelemetryEvents for a run.

    On connect:
      * send a ``hello`` event with the run_id (so the client
        can confirm the stream is alive).
      * replay up to 50 recent events from the bus ring buffer
        (``event: history``).

    Then keep streaming ``event: live`` for each new event
    until the client disconnects (or 30 minutes elapse, whichever
    comes first).

    Note: this fan-out is in-process. Multi-worker deployments
    will only deliver events from the worker that receives the
    publisher call. F8.5 with Redis pub/sub is the fix; we
    document the limitation here.
    """
    await _load_run_or_404(session, run_id)

    queue, unsubscribe = bus.subscribe()

    async def _generator():
        try:
            # Initial hello.
            yield _sse_format(
                "hello", {"run_id": run_id, "ts": _utcnow_iso()}
            )
            # Replay recent events for this run.
            for ev in bus.recent(50):
                if ev.get("run_id") != run_id:
                    continue
                yield _sse_format("history", ev)
            # Live tail.
            end_at = asyncio.get_event_loop().time() + 30 * 60
            while True:
                # Check timeout.
                if asyncio.get_event_loop().time() > end_at:
                    yield _sse_format(
                        "bye",
                        {"reason": "max-stream-minutes=30"},
                    )
                    return
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=10.0
                    )
                except asyncio.TimeoutError:
                    # Heartbeat. SSE clients use heartbeats to
                    # detect dead connections through proxies.
                    yield ": ping\n\n"
                    continue
                if event.get("run_id") != run_id:
                    continue
                yield _sse_format("live", event)
        finally:
            unsubscribe()

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


def _sse_format(event_name: str, data: dict[str, Any]) -> str:
    """Format a dict as an SSE frame.

    Frame shape::

        event: live
        data: {"id": 1, ...}

    (Note: a blank line terminates the frame, per the SSE spec.)
    """
    payload = json.dumps(data, default=str)
    return f"event: {event_name}\ndata: {payload}\n\n"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
