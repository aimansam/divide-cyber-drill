"""After-action JSON report endpoint (L2 2.12).

The report endpoint is the user-visible payoff for closing a run.
It returns a self-contained JSON blob — the same shape our portal
"Download JSON" button (when added in the next portal plan) sends
to the browser. The payload has five top-level keys:

  * ``run``       — the Run row as an end-to-end summary.
  * ``scenario``  — a thin scenario summary (name, title, version,
                    difficulty, duration_min).
  * ``assets``    — list of Asset rows attached to the run.
  * ``audit``     — full audit-log timeline (chronological).
  * ``metrics_summary`` — Prometheus-derived counters scoped to the
                    run (events from this run's metric labels, plus
                    aggregate counters that aren't labelled by run
                    id).

RBAC:

  * Anonymous → 401.
  * Any authenticated role may call this endpoint, but red/blue
    only see their own runs. Visibility rule shared with
    drills/audit.

Status codes:
  * 200 — payload delivered.
  * 401 — no token.
  * 403 — token cannot see this run.
  * 404 — run id does not exist.
  * 409 — run is still in a non-terminal state.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Role, current_token, require_role
from app.db import models as db_models
from app.db.session import get_session
from app.services.authorization import can_view_run

router = APIRouter()


def _run_to_dict(run: db_models.Run) -> dict:
    return {
        "id": run.id,
        "scenario_id": run.scenario_id,
        "status": run.status.value,
        "started_by": run.started_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "duration_sec": run.duration_sec,
        "score_blue": run.score_blue,
        "score_red": run.score_red,
        "error": run.error,
    }


def _asset_to_dict(a: db_models.Asset) -> dict:
    return {
        "id": a.id,
        "run_id": a.run_id,
        "role": a.role,
        "kind": a.kind,
        "template": a.template,
        "status": a.status.value,
        "pve_vmid": a.pve_vmid,
        "pve_node": a.pve_node,
        "pve_ip": a.pve_ip,
        "error": a.error,
    }


def _audit_row(r: db_models.AuditLog) -> dict:
    return {
        "id": r.id,
        "at": r.at.isoformat() if r.at else None,
        "action": r.action.value,
        "actor": r.actor,
        "scenario_id": r.scenario_id,
        "asset_id": r.asset_id,
        "details": r.details,
    }


def _metrics_summary(scenario_id: int | None, adapter: str) -> dict:
    """Snapshot of Prometheus counters for this run / scenario.

    Best-effort: pulls a small set of named counters that are
    guaranteed deterministic. Cardinality matters — we do NOT
    iterate the full registry.
    """
    summary: dict = {
        "captured_at": datetime.now().isoformat(),
        "by_scenario_id": scenario_id,
        "adapter": adapter,
    }

    try:
        from app.observability import RUNS_TOTAL

        for outcome in (
            "started",
            "succeeded",
            "failed",
            "cancelled",
            "timeout",
        ):
            try:
                sample = RUNS_TOTAL.labels(outcome=outcome, adapter=adapter)
                summary[f"runs_total_{outcome}"] = int(
                    sample._value.get()  # type: ignore[attr-defined]
                )
            except (AttributeError, KeyError, ValueError):
                summary[f"runs_total_{outcome}"] = 0
    except Exception:  # noqa: BLE001 — never break the report
        summary["runs_total_error"] = "unavailable"

    return summary


@router.get(
    "/{run_id}/report",
    summary="After-action JSON report for one drill",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def get_drill_report(
    run_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Return the post-mortem JSON for one run."""
    run = (
        await session.execute(
            select(db_models.Run).where(db_models.Run.id == run_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run id={run_id} not found",
        )

    if not can_view_run(token, run):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not have access to this run",
        )

    if run.status in (
        db_models.RunStatus.PENDING,
        db_models.RunStatus.RUNNING,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"run id={run_id} is in non-terminal state "
                f"{run.status.value!r}; report is for completed runs only"
            ),
        )

    # Scenario — minimal projection.
    scenario = (
        await session.execute(
            select(db_models.Scenario).where(
                db_models.Scenario.id == run.scenario_id
            )
        )
    ).scalar_one_or_none()
    scenario_dict = None
    if scenario is not None:
        scenario_dict = {
            "id": scenario.id,
            "name": scenario.name,
            "title": scenario.title,
            "version": scenario.version,
            "difficulty": scenario.difficulty,
            "duration_min": scenario.duration_min,
            "tags": scenario.tags,
        }

    assets = (
        await session.execute(
            select(db_models.Asset).where(db_models.Asset.run_id == run_id)
        )
    ).scalars().all()

    audit = (
        await session.execute(
            select(db_models.AuditLog)
            .where(db_models.AuditLog.run_id == run_id)
            .order_by(db_models.AuditLog.at.asc())
        )
    ).scalars().all()

    from app.runners.runner import _adapter_label
    from app.runners.mock_adapter import MockProxmoxAdapter

    adapter_label = _adapter_label(MockProxmoxAdapter())

    return {
        "run": _run_to_dict(run),
        "scenario": scenario_dict,
        "assets": [_asset_to_dict(a) for a in assets],
        "audit": [_audit_row(r) for r in audit],
        "metrics_summary": _metrics_summary(
            scenario_id=run.scenario_id, adapter=adapter_label
        ),
    }