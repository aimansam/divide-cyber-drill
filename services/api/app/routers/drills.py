"""Drill lifecycle endpoints.

Phase 1: accepts POST to start a run, returns the new run id. The
adapter is selected by :func:`app.runners.build_runner` — when
PROXMOX_* env vars are set the factory returns ``RealProxmoxAdapter``;
otherwise it falls back to ``MockProxmoxAdapter`` so dev / CI / tests
keep working without PVE creds.

The DB is persistent. State is read from Postgres, not from in-memory
process state, so the API can be restarted without losing runs.

RBAC (L2 2.9):
  * POST   /drills                  → admin, lead, red (start a run)
  * POST   /drills/{id}/stop        → admin, lead (force-stop any run)
  * POST   /drills/{id}/cancel      → admin, lead, red (red: own runs only)
  * GET    /drills                  → any role; red/blue filtered to own
  * GET    /drills/{id}             → any role; red/blue see only own
  * GET    /drills/{id}/audit       → any role; red/blue see only own

The visibility filter is implemented in
:mod:`app.services.authorization` and applied uniformly across
list / detail / audit / (future) report endpoints. The matrix
table is the source of truth for ``docs/USER-REQUIREMENTS.md`` §2.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import Role, current_token, require_role
from app.db import models as db_models
from app.db.session import get_session
from app.observability import record_cancel
from app.runners.runner import Runner, RunnerError, RunRequest, build_runner
from app.services.authorization import can_view_run, visible_runs_query
from app.services.rate_limit import check_drill_start_limit

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


@router.post(
    "",
    summary="Start a drill (mock adapter, no PVE)",
    # The body of this endpoint calls ``check_drill_start_limit(token.sub)``
    # directly so we have access to the verified subject. Keeping it out
    # of ``dependencies=`` also means the 429 detail can name the subject,
    # which the UI surfaces in a toast.
    dependencies=[Depends(require_role(Role.ADMIN, Role.LEAD, Role.RED))],
)
async def start_drill(
    body: dict,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    scenario_id = body.get("scenario_id")
    if not isinstance(scenario_id, int):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="body must include integer `scenario_id`",
        )

    # ``started_by`` attribution: prefer the token subject (proves
    # which user ran the drill in audit logs); fall back to the
    # body's ``started_by`` for legacy callers + smoke scripts.
    started_by = token.sub if token else body.get("started_by")

    # Rate-limit AFTER auth so we have a verified subject. The
    # auth gate has already rejected anything anonymous, so this
    # either has a real sub or token was not required by the
    # caller-side helper — we fall back to ``_anonymous_bucket``
    # in that degenerate case so anonymous calls (which shouldn't
    # reach here) share one budget.
    from app.services.rate_limit import check_drill_start_limit as _rl

    await _rl(started_by or "_anonymous_bucket")

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
            RunRequest(scenario_id=scenario_id, started_by=started_by),
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


@router.post(
    "/{run_id}/stop",
    summary="Stop a drill",
    dependencies=[Depends(require_role(Role.ADMIN, Role.LEAD))],
)
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
    dependencies=[Depends(require_role(Role.ADMIN, Role.LEAD, Role.RED))],
)
async def cancel_drill(
    run_id: int,
    body: dict | None = None,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Abort a run mid-flight.

    Body is optional; only ``reason`` and ``actor`` are read:
      * ``reason`` (str, default "user-requested") — recorded on the
        Run row + audit entry. Surfaces in the UI as the cancel cause.
      * ``actor`` (str, optional) — who cancelled (e.g. "trainee-7").
        Defaults to the token subject if a token was supplied.

    Status codes:
      * 200 — run cancelled; assets best-effort torn down.
      * 401 — no token (require_token under require_role).
      * 403 — token role is not in {admin, lead, red}, or red is
        trying to cancel a run they didn't start.
      * 404 — run not found.
      * 409 — run is already in a terminal state (succeeded / failed /
        cancelled / timeout). Caller must check the run state first.

    RBAC: the route-level ``require_role`` gate passes for admin,
    lead, and red. After that, an additional check rejects red
    callers attempting to cancel a run that wasn't started by
    them (``run.started_by != token.sub``). Admins and leads can
    cancel any run.
    """
    body = body or {}
    reason = body.get("reason") or "user-requested"
    actor = body.get("actor") or (token.sub if token else None)

    # Own-only filter for red. Done before the runner call so we
    # return a clean 403 rather than a 404 from "not found" -- the
    # latter would obscure the auth reason and make the UI confusing.
    if token and token.role == Role.RED.value:
        run_row = (
            await session.execute(
                select(db_models.Run.started_by).where(
                    db_models.Run.id == run_id
                )
            )
        ).scalar_one_or_none()
        if run_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"run id={run_id} not found",
            )
        if run_row != token.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="red team can only cancel runs they started",
            )

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


@router.get(
    "",
    summary="List drills (visibility-filtered by token role)",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def list_drills(
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """List runs, scoped to what the caller's role can see.

    admin / lead / observer → all runs.
    red / blue              → only runs where ``started_by == token.sub``.

    The visibility filter is applied at the SQL layer (see
    :func:`app.services.authorization.visible_runs_query`), so the
    response shape doesn't change role-to-role -- only the rows
    returned. The UI is the same code path for every persona; it
    just sees a shorter list when the caller is a participant.
    """
    stmt = visible_runs_query(token).order_by(db_models.Run.id.desc())
    rows = (await session.execute(stmt)).scalars().all()
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


@router.get(
    "/{run_id}",
    summary="Get one drill by id (with assets, visibility-filtered)",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def get_drill(
    run_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Return a single Run with its Asset rows expanded.

    Used by the test UI / drill inspector. Read-only -- does not touch
    PVE.

    RBAC: any authenticated role may call this, but red/blue only
    see their own runs. The 404 vs 403 question:

      * Run exists, caller can see it        → 200.
      * Run exists, caller cannot see it     → 403 (do not leak
                                              existence to a
                                              non-entitled caller).
      * Run does not exist                   → 404.

    Why we have this on top of /api/v1/drills (list):
        The list endpoint returns summary rows only (no assets). The
        inspector UI needs the assets + audit log for a *single* run,
        and the cancel/stop endpoints both mutate state. A read-only
        GET fills the gap.

    Implementation note:
        ``Run.duration_sec`` is a @property that touches ``started_at``
        and ``ended_at`` columns; serializing it via the lazy ORM
        would trigger a MissingGreenlet error inside the async session.
        ``selectinload(assets)`` eagerly pulls the assets in the same
        round-trip as the Run row, so serialization is in-memory.
    """
    stmt = (
        select(db_models.Run)
        .where(db_models.Run.id == run_id)
        .options(selectinload(db_models.Run.assets))
    )
    run = (await session.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run id={run_id} not found",
        )
    if not can_view_run(token, run):
        # 403, not 404: the row exists, just not for you.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not have access to this run",
        )
    return {
        "run_id": run.id,
        "scenario_id": run.scenario_id,
        "status": run.status.value,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "started_by": run.started_by,
        "duration_sec": run.duration_sec,
        "score_blue": run.score_blue,
        "score_red": run.score_red,
        "error": run.error,
        "assets": [
            {
                "asset_id": a.id,
                "role": a.role,
                "kind": a.kind,
                "template": a.template,
                "status": a.status.value,
                "pve_vmid": a.pve_vmid,
                "pve_node": a.pve_node,
                "pve_ip": a.pve_ip,
                "error": a.error,
            }
            for a in run.assets
        ],
    }


@router.get(
    "/{run_id}/audit",
    summary="Get the audit-log entries for one drill (visibility-filtered)",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def get_drill_audit(
    run_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Return the append-only audit_log rows linked to this run, oldest first.

    Read-only. Useful for the test UI to verify the lifecycle hooks fired
    (run.started, asset.spawned, run.completed / run.cancelled).

    RBAC: same matrix as GET /drills/{id}. A red/blue caller who
    cannot see the run also cannot see its audit log; they get
    403, not an empty list. Returning empty for "exists but not
    yours" would silently confirm the run's existence to a probe.
    """
    # Fetch both the existence flag and the started_by in one round
    # trip so we can distinguish "doesn't exist" from "exists but
    # not yours" without leaking the existence either way.
    row = (
        await session.execute(
            select(db_models.Run.id, db_models.Run.started_by).where(
                db_models.Run.id == run_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run id={run_id} not found",
        )
    run_id_db, started_by = row
    # Reuse can_view_run by constructing a transient proxy object.
    # Cheaper than a second DB round-trip and keeps the rule in
    # one place.
    if not can_view_run(token, db_models.Run(id=run_id_db, started_by=started_by)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not have access to this run",
        )

    rows = (
        await session.execute(
            select(db_models.AuditLog)
            .where(db_models.AuditLog.run_id == run_id)
            .order_by(db_models.AuditLog.at.asc())
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "at": r.at.isoformat() if r.at else None,
                "action": r.action.value,
                "actor": r.actor,
                "scenario_id": r.scenario_id,
                "asset_id": r.asset_id,
                "details": r.details,
            }
            for r in rows
        ],
        "total": len(rows),
    }
