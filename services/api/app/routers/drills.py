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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import Role, current_token, require_role
from app.db import models as db_models
from app.db.session import get_session
from app.observability import record_cancel
from app.runners.runner import Runner, RunnerError, RunRequest, build_runner
from app.db.models import Exercise, ExerciseStatus, Team
from app.services.flags import FlagError, capture_seconds, resolve_flag, verify_flag_value
from app.services.scoring import score as score_points, score_breakdown
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

    # F6: optional exercise binding. If exercise_id is provided,
    # we verify the exercise exists and is in LIVE state. We accept
    # a ``team`` name; if the exercise has no team by that name we
    # 404 (callers should add_team first).
    exercise_id_raw = body.get("exercise_id")
    team_raw = body.get("team")
    exercise_id = None
    team = None
    if exercise_id_raw is not None:
        if not isinstance(exercise_id_raw, int):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="exercise_id must be an int when provided",
            )
        ex = (
            await session.execute(
                select(Exercise).where(Exercise.id == exercise_id_raw)
            )
        ).scalar_one_or_none()
        if ex is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"exercise id={exercise_id_raw} not found",
            )
        # Allow starting in IDLE for forward-compat (operator
        # sometimes starts runs before the operator clicks
        # /start explicitly). The leaderboard will surface the run
        # regardless.
        if ex.status not in (
            db_models.ExerciseStatus.IDLE,
            db_models.ExerciseStatus.LIVE,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"exercise id={exercise_id_raw} is {ex.status.value}; "
                    "cannot start runs against ENDED / ARCHIVED exercises"
                ),
            )
        exercise_id = ex.id
        # Verify team membership when team is provided.
        if isinstance(team_raw, str):
            from app.db.models import TeamMembership
            role = getattr(token, "role", None)
            role_value = (
                role.value if hasattr(role, "value") else role
            )
            is_admin_or_lead = role_value in ("admin", "lead")
            if not is_admin_or_lead:
                # Non-admins must be a member of the exercise.
                tm = (
                    await session.execute(
                        select(TeamMembership.id).where(
                            TeamMembership.exercise_id == exercise_id,
                            TeamMembership.sub == (
                                token.sub if token else ""
                            ),
                        )
                    )
                ).first()
                if tm is None:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            "you are not a member of this exercise; "
                            "cannot submit a run for it"
                        ),
                    )
            # Validate team name in the exercise (if provided).
            t = (
                await session.execute(
                    select(Team).where(
                        Team.exercise_id == exercise_id,
                        Team.name == team_raw,
                    )
                )
            ).scalar_one_or_none()
            if t is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=(
                        f"team {team_raw!r} is not part of exercise id={exercise_id}"
                    ),
                )
            team = t.name

    # F7: optional template_id. When set, the run is spawned
    # against the template's snapshot (scenario is derived from
    # template.scenario_id so callers don't have to specify both).
    template_id_raw = body.get("template_id")
    template_id = None
    if template_id_raw is not None:
        if not isinstance(template_id_raw, int):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="template_id must be an int when provided",
            )
        from app.db.models import Template
        template_obj = (
            await session.execute(
                select(Template).where(Template.id == template_id_raw)
            )
        ).scalar_one_or_none()
        if template_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"template id={template_id_raw} not found",
            )
        template_id = template_obj.id
        if template_obj.scenario_id != scenario_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"template {template_id} is for scenario "
                    f"id={template_obj.scenario_id}, but body "
                    f"requested scenario_id={scenario_id}"
                ),
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
            RunRequest(
                scenario_id=scenario_id,
                started_by=started_by,
                exercise_id=exercise_id,
                team=team,
                template_id=template_id,
            ),
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
        "exercise_id": exercise_id,
        "team": team,
        "template_id": template_id,
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


# =========================================================================
# F4: noVNC console per asset (one HTTP endpoint; WS registered in main.py)
# =========================================================================


@router.get(
    "/{run_id}/assets/{asset_id}/console",
    summary="Get a VNC ticket for one asset's console",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def get_asset_console(
    run_id: int,
    asset_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Issue a PVE VNC ticket for an asset and return a WebSocket path.

    The browser opens a WebSocket against
    ``/api/v1/drills/{run_id}/assets/{asset_id}/console/ws`` with
    ``X-Divide-Token``. The WS proxy authenticates with the same
    token, validates the asset, and proxies bytes to PVE's
    ``/nodes/{n}/qemu/{v}/vncproxy?port=...&vncticket=...``.

    Why a WS proxy (and not direct browser -> PVE)?
      * The PVE token is server-side (HMAC secret). Exposing it
        to the browser would let any operator-misclick leak it.
      * The browser can't bypass our RBAC; the proxy enforces
        ``can_view_run`` on every frame before opening the
        upstream socket.
      * Run summary + audit entries stay consistent.

    RBAC: Reads run_id + asset_id, validates they exist, validates
    ``can_view_run``. A red/blue who can't see the run gets 403
    (don't expose the existence).

    Errors:
      * 404 if run_id or asset_id not found.
      * 403 if caller cannot view the run.
      * 409 if asset hasn't been cloned yet (pve_vmid is None).
      * 502 if PVE rejects the ticket (transient; retry).
    """
    row = (
        await session.execute(
            select(
                db_models.Run.id,
                db_models.Run.started_by,
                db_models.Asset.id,
                db_models.Asset.pve_vmid,
                db_models.Asset.pve_node,
                db_models.Asset.status,
            )
            .where(db_models.Asset.id == asset_id)
            .where(db_models.Asset.run_id == run_id)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run id={run_id} asset id={asset_id} not found",
        )
    _run_id, started_by, _asset_id_db, pve_vmid, pve_node, asset_status = row
    if not can_view_run(token, db_models.Run(id=_run_id, started_by=started_by)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not have access to this run",
        )
    if pve_vmid is None or not pve_node:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"asset id={asset_id} has not been cloned yet "
                f"(status={asset_status.value}); cannot open console"
            ),
        )

    from app.runners.runner import build_runner
    runner = build_runner()
    try:
        ticket = await runner._adapter.get_vnc_ticket(pve_vmid, pve_node)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"PVE vncproxy failed for vmid={pve_vmid} on node={pve_node}: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    return {
        "asset_id": asset_id,
        "run_id": run_id,
        "vmid": pve_vmid,
        "node": pve_node,
        "ticket": ticket.ticket,
        "port": ticket.port,
        "ws_path": (
            f"/api/v1/drills/{run_id}/assets/{asset_id}/console/ws"
        ),
        "expires_in_seconds": 7200,
    }


# =========================================================================
# F5: flag submission per run
# =========================================================================


@router.post(
    "/{run_id}/submit-flag",
    summary="Submit a captured flag value for scoring",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.RED, Role.BLUE,
    ))],
)
async def submit_flag(
    run_id: int,
    body: dict,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Validate a submitted flag value against a run's scenario.

    Body::

        {
          "flag_id": "flag-1",
          "value": "FLAG{pwned_the_router}"
        }

    Scoring:
      * ``points = floor(base_points * max(0, 1 - elapsed / window))``.
      * At t=0 the team gets the full ``base_points``; at
        t=window they get 0; past window also 0.
      * Frozen at capture time so re-grading a scoring rule
        doesn't change history.

    Errors:
      * 401 / 403 -- auth + RBAC.
      * 404 -- run not found, or asset not found.
      * 409 -- run is terminal (drill ended).
      * 422 -- flag_id not in scenario spec, or value mismatch.
      * 409 -- same team already captured the same flag (unique
        constraint on flag_submissions).

    The endpoint doesn't require can_view_run directly: a red
    operator running their own drill, or a blue watching it,
    can submit. We DO require the run to be active.
    """
    flag_id = body.get("flag_id")
    value = body.get("value")
    if not isinstance(flag_id, str) or not isinstance(value, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="body must include flag_id (str) and value (str)",
        )

    row = (
        await session.execute(
            select(
                db_models.Run.id,
                db_models.Run.status,
                db_models.Run.started_at,
                db_models.Run.started_by,
                db_models.Scenario.spec,
                db_models.Scenario.name,
            )
            .where(db_models.Run.id == run_id)
            .join(db_models.Scenario, db_models.Run.scenario_id == db_models.Scenario.id)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run id={run_id} not found",
        )
    _run_id, run_status, started_at, started_by, spec, scenario_name = row
    # F6: with the multi-team setup, RBAC for submit-flag is:
    #   * admin/lead/observer: always
    #   * the run's started_by
    #   * member of the run's exercise (so a red/blue team member
    #     can capture flags against their team's run)
    from app.core.auth import Role as _Role
    from app.db.models import TeamMembership
    role = token.role if hasattr(token, "role") else None
    role_value = role.value if hasattr(role, "value") else role
    is_admin_or_lead = role_value in ("admin", "lead", "observer")
    is_owner = started_by == getattr(token, "sub", None)
    is_team_member = False
    if not is_admin_or_lead and not is_owner:
        # Look up Run.exercise_id (we already have started_by +
        # the exercise implicit via run; but ex_id isn't in scope
        # here yet — re-query).
        ex_id = (
            await session.execute(
                select(db_models.Run.exercise_id).where(
                    db_models.Run.id == run_id
                )
            )
        ).scalar_one()
        if ex_id is not None:
            tm = (
                await session.execute(
                    select(TeamMembership.id).where(
                        TeamMembership.exercise_id == ex_id,
                        TeamMembership.sub == (
                            token.sub if token else ""
                        ),
                    )
                )
            ).first()
            is_team_member = tm is not None
    if not (is_admin_or_lead or is_owner or is_team_member):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not have access to submit flags for this run",
        )
    if run_status not in (db_models.RunStatus.RUNNING, db_models.RunStatus.PENDING):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=FlagError.run_not_active(run_status.value).message,
        )

    try:
        flag_spec = resolve_flag(spec, flag_id)
    except FlagError as exc:
        if exc.kind == "flag_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=exc.message,
            )
        raise

    if not verify_flag_value(flag_spec, value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="flag value did not match",
        )

    # The team hunting this flag is the opposite of the flag
    # side: a red-side flag is hunted by blue, a blue-side flag
    # is hunted by red. self-side flags are ignored.
    if flag_spec.side == "red":
        team = "blue"
    elif flag_spec.side == "blue":
        team = "red"
    else:
        # F5 design choice: self-side flags are planted as
        # proof-of-life and out of scope for F5 scoring.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"flag {flag_id!r} is self-side; F5 only scores red/blue side flags"
            ),
        )

    elapsed = capture_seconds(started_at)
    points = score_points(
        base_points=flag_spec.base_points,
        window_seconds=flag_spec.window_seconds,
        elapsed_seconds=elapsed,
    )
    breakdown = score_breakdown(
        flag_spec.base_points,
        flag_spec.window_seconds,
        elapsed,
    )

    submission = db_models.FlagSubmission(
        run_id=run_id,
        flag_id=flag_spec.flag_id,
        team=team,
        submitted_by=getattr(token, "sub", "unknown"),
        points=points,
        elapsed_seconds=elapsed,
    )
    session.add(submission)
    try:
        await session.commit()
    except IntegrityError:  # noqa
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=FlagError.duplicate(team, flag_spec.flag_id).message,
        )

    # Update run-level score (sum of all submissions per team).
    from sqlalchemy import func as sa_func
    red_q = await session.execute(
        select(sa_func.coalesce(sa_func.sum(db_models.FlagSubmission.points), 0))
        .where(db_models.FlagSubmission.run_id == run_id)
        .where(db_models.FlagSubmission.team == "red")
    )
    blue_q = await session.execute(
        select(sa_func.coalesce(sa_func.sum(db_models.FlagSubmission.points), 0))
        .where(db_models.FlagSubmission.run_id == run_id)
        .where(db_models.FlagSubmission.team == "blue")
    )
    red_total = int(red_q.scalar_one() or 0)
    blue_total = int(blue_q.scalar_one() or 0)
    run_obj = await session.execute(
        select(db_models.Run).where(db_models.Run.id == run_id)
    )
    run_obj = run_obj.scalar_one()
    run_obj.score_red = red_total
    run_obj.score_blue = blue_total
    # F6: if this run is part of an exercise, bump the team's
    # aggregate score so the leaderboard surfaces it.
    if run_obj.exercise_id is not None:
        team_q = await session.execute(
            select(Team).where(
                Team.exercise_id == run_obj.exercise_id,
                Team.name == team,
            )
        )
        team_obj = team_q.scalar_one_or_none()
        if team_obj is not None:
            team_obj.score = team_obj.score + points
    await session.commit()

    return {
        "submission_id": submission.id,
        "run_id": run_id,
        "flag_id": flag_spec.flag_id,
        "team": team,
        "points": points,
        "elapsed_seconds": elapsed,
        "breakdown": breakdown,
        "scenario_name": scenario_name,
    }


# --- F7: reset + save-as-template ---------------------------------------


@router.post(
    "/{run_id}/reset",
    summary="Reset a Run to its template snapshot",
    dependencies=[Depends(require_role(Role.ADMIN, Role.LEAD))],
)
async def reset_run(
    run_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Reset a Run's assets + flags to the originating template snapshot.

    This is the operator's "undo" button -- they can pull a run
    back to the snapshot state without re-creating the run.
    If the run is not bound to a template (template_id is NULL),
    this is a 409 (use ``save-as-template`` first to bind one).
    """
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
    if run.template_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"run id={run_id} has no template; "
                "use POST /drills/{id}/save-as-template first"
            ),
        )
    # Load the template's snapshot.
    from app.db.models import Template
    template = (
        await session.execute(
            select(Template).where(Template.id == run.template_id)
        )
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"run id={run_id} references missing template id={run.template_id}"
            ),
        )
    # Reset the run's lifecycle so the runner treats it as a
    # fresh start: PENDING + restart started_at.
    run.status = db_models.RunStatus.PENDING
    run.score_red = 0
    run.score_blue = 0
    run.started_at = None
    run.ended_at = None
    # Drop existing assets (cascade deletes their children).
    existing_assets = (
        await session.execute(
            select(db_models.Asset).where(db_models.Asset.run_id == run_id)
        )
    ).scalars().all()
    for a in existing_assets:
        await session.delete(a)
    # Re-stage assets from snapshot. We pull role / kind /
    # template_name; networks is recorded on the original scenario
    # but doesn't have its own column on Asset (kept in
    # scenario.spec.networks). Storing it would require a new
    # column, deferred until F7.5.
    snapshot = template.snapshot or {}
    new_asset_ids = []
    for asset_spec in snapshot.get("assets", []) or []:
        asset = db_models.Asset(
            run_id=run.id,
            role=str(asset_spec.get("role", "victim")),
            kind=str(asset_spec.get("kind", "vm")),
            template=str(asset_spec.get("template", "") or "") or None,
            status=db_models.AssetStatus.PLANNED,
            pve_vmid=None,
        )
        session.add(asset)
        await session.flush()
        new_asset_ids.append(asset.id)
    await session.commit()
    return {
        "run_id": run.id,
        "template_id": template.id,
        "status": run.status.value,
        "asset_count": len(new_asset_ids),
        "reset_by": getattr(token, "sub", "unknown"),
        "snapshot_id": (
            template.snapshot.get("scenario_id") if snapshot else None
        ),
    }


@router.post(
    "/{run_id}/save-as-template",
    summary="Save the current Run as a Template",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def save_run_as_template(
    run_id: int,
    body: dict,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Snapshot the current Run's state into a new Template.

    The Run doesn't have to be SUCCEEDED (unlike creating a
    template from a finished run via /templates). This is the
    operator's "bookmark" button while the drill is still
    running -- handy for capturing an interesting intermediate
    state.

    Body::

        {
          "name": "mid-drill-snapshot",
          "title": "Captured at t=15min",
          "description": "..."
        }
    """
    name = body.get("name")
    title = body.get("title")
    description = body.get("description", "")
    if not isinstance(name, str) or not isinstance(title, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="name + title must be strings",
        )
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
    # Capture FK values before any potential rollback.
    scenario_id = run.scenario_id
    scenario = (
        await session.execute(
            select(db_models.Scenario).where(
                db_models.Scenario.id == scenario_id
            )
        )
    ).scalar_one_or_none()
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"run id={run_id} references missing scenario"
            ),
        )
    snapshot = await _build_template_snapshot_from_live(run, scenario, session)

    template = db_models.Template(
        name=name,
        title=title,
        description=description,
        from_run_id=run_id,
        scenario_id=scenario_id,
        snapshot=snapshot,
        created_by=getattr(token, "sub", "unknown"),
    )
    session.add(template)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a template named {name!r} already exists",
        )
    # Bind the run to the new template (so a future /reset works).
    run.template_id = template.id
    await session.commit()
    return _serialize_template_full(template)


def _serialize_template_full(t: db_models.Template) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "title": t.title,
        "description": t.description,
        "from_run_id": t.from_run_id,
        "scenario_id": t.scenario_id,
        "snapshot": t.snapshot,
        "created_by": t.created_by,
        "created_at": (
            t.created_at.isoformat() if t.created_at else None
        ),
        "updated_at": (
            t.updated_at.isoformat() if t.updated_at else None
        ),
    }


async def _build_template_snapshot_from_live(
    run, scenario, session
) -> dict:
    """Build a snapshot from a live run (used by save-as-template).

    Unlike _build_snapshot (which uses the scenario YAML), this
    version reads the live assets so a run that's drifted from the
    original scenario still produces a faithful snapshot.
    """
    from app.db.models import Asset as _Asset
    assets_rows = (
        await session.execute(
            select(_Asset).where(_Asset.run_id == run.id)
        )
    ).scalars().all()
    assets_snapshot = [
        {
            "role": a.role,
            "kind": a.kind,
            "networks": list(a.networks or []),
            "template": (a.template_name or ""),
        }
        for a in assets_rows
    ]
    spec = scenario.spec or {}
    inner = spec.get("spec", spec) if isinstance(spec, dict) else {}
    return {
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "scenario_version": scenario.version,
        "assets": assets_snapshot,
        "flags": list(inner.get("flags", []) or []),
        "networks": list(inner.get("networks", []) or []),
        "scoring": inner.get("scoring", {}),
        "win_conditions": inner.get("win_conditions", {}),
        "run_status_at_snapshot": run.status.value,
    }
