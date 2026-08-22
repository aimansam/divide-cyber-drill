"""Drill lifecycle endpoints.

Phase 1: accepts POST to start a run, returns the new run id. Uses the
in-memory MockProxmoxAdapter until RealProxmoxAdapter lands.

The DB is persistent. State is read from Postgres, not from in-memory
process state, so the API can be restarted without losing runs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models as db_models
from app.db.session import get_session
from app.runners.mock_adapter import MockProxmoxAdapter
from app.runners.runner import Runner, RunnerError, RunRequest

router = APIRouter()


def _get_runner() -> Runner:
    """Until RealProxmoxAdapter lands, every API request uses the mock.
    Each request gets a fresh mock (no shared state) so the catalog is
    always empty from the mock's perspective. Replace this with a singleton
    RealProxmoxAdapter once PVE auth works.
    """
    return Runner(MockProxmoxAdapter())


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
