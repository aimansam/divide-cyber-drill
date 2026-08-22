"""Drill lifecycle endpoints.

Phase 1: accepts POST to start a run, returns the new run id. The
adapter is selected by :func:`app.runners.build_runner` — when
PROXMOX_* env vars are set the factory returns ``RealProxmoxAdapter``;
otherwise it falls back to ``MockProxmoxAdapter`` so dev / CI / tests
keep working without PVE creds.

The DB is persistent. State is read from Postgres, not from in-memory
process state, so the API can be restarted without losing runs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as db_models
from app.db.session import get_session
from app.observability import record_cancel
from app.runners.runner import Runner, RunnerError, RunRequest, build_runner

router = APIRouter()


def _get_runner() -> Runner:
    """Pick the right adapter via the env-driven factory.

    Returns a fresh ``Runner`` per request. The adapter itself is
    cheap to construct (just config + lazy proxmoxer client), so we
    don't bother caching it across requests. If we later need shared
    state (e.g. a connection pool), this is the place to swap in a
    module-level singleton.
    """
    return build_runner()


@router.post("", summary="Start a drill (mock adapter, no PVE)")
async def start_drill(
    body: dict,
    session: AsyncSession = Depends(get_session),
) -> dict:
    scenario_id = body.get("scenario_id")
    if not isinstance(scenario_id, int):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="body must include integer `scenario_id`",
        )

    # Pre-check: scenario must exist and not be archived. The runner
    # would raise RunnerError too, but doing the check here lets us
    # return a proper 404 / 410 instead of 422 for this clearer case.
    scenario = (
        await session.execute(
            select(db_models.Scenario).where(db_models.Scenario.id == scenario_id)
        )
    ).scalar_one_or_none()
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"scenario id={scenario_id} not found",
        )
    if scenario.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"scenario id={scenario_id} is archived; restore it first",
        )

    runner = _get_runner()
    try:
        result = await runner.start_run(
            RunRequest(scenario_id=scenario_id, started_by=body.get("started_by")),
            session,
        )
    except RunnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return {
        "run_id": result.run_id,
        "status": result.status.value,
    }


@router.post("/{run_id}/stop", summary="Stop a drill")
async def stop_drill(
    run_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    runner = _get_runner()
    try:
        run = await runner.stop_run(run_id, session=session)
    except RunnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return {
        "run_id": run.id,
        "status": run.status.value,
        "assets": [
            {"role": a.role, "status": a.status.value, "pve_vmid": a.pve_vmid}
            for a in run.assets
        ],
    }


@router.post(
    "/{run_id}/cancel",
    summary="Cancel a running drill (trainee-initiated abort)",
)
async def cancel_drill(
    run_id: int,
    body: dict | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Abort a run mid-flight.

    Body is optional; only ``reason`` and ``actor`` are read:
      * ``reason`` (str, default "user-requested") — recorded on the
        Run row + audit entry. Surfaces in the UI as the cancel cause.
      * ``actor`` (str, optional) — who cancelled (e.g. "trainee-7").

    Status codes:
      * 200 — run cancelled; assets best-effort torn down.
      * 404 — run not found.
      * 409 — run is already in a terminal state (succeeded / failed /
        cancelled / timeout). Caller must check the run state first.
    """
    body = body or {}
    reason = body.get("reason") or "user-requested"
    actor = body.get("actor")
    runner = _get_runner()
    try:
        run = await runner.cancel_run(
            run_id, reason=reason, actor=actor, session=session
        )
    except RunnerError as exc:
        # Distinguish "not found" from "already terminal" so the UI
        # can react sensibly (re-fetch vs display toast).
        msg = str(exc)
        if "not found" in msg:
            record_cancel(result="not_found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=msg,
            ) from exc
        record_cancel(result="already_terminal")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=msg,
        ) from exc
    except Exception:  # noqa: BLE001
        record_cancel(result="error")
        raise
    return {
        "run_id": run.id,
        "status": run.status.value,
        "reason": run.error,
        "assets": [
            {"role": a.role, "status": a.status.value, "pve_vmid": a.pve_vmid}
            for a in run.assets
        ],
    }


@router.get("", summary="List drills (all runs in DB)")
async def list_drills(session: AsyncSession = Depends(get_session)) -> dict:
    rows = (
        await session.execute(select(db_models.Run).order_by(db_models.Run.id.desc()))
    ).scalars().all()
    return {
        "items": [
            {
                "run_id": r.id,
                "scenario_id": r.scenario_id,
                "status": r.status.value,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "started_by": r.started_by,
                "duration_sec": r.duration_sec,
                "score_blue": r.score_blue,
                "score_red": r.score_red,
            }
            for r in rows
        ],
        "total": len(rows),
    }
