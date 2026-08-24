"""F6: Exercise + Team + TeamMembership endpoints.

Endpoints (all admin-only except the read-side which admin/lead/observer
+ members of the exercise can see):

  POST   /exercises                       admin -> create
  GET    /exercises                       any role -> list (visibility-filtered)
  GET    /exercises/{id}                  any role -> detail
  POST   /exercises/{id}/start            admin -> IDLE -> LIVE
  POST   /exercises/{id}/stop             admin -> LIVE -> ENDED
  POST   /exercises/{id}/archive          admin -> any -> ARCHIVED
  POST   /exercises/{id}/teams            admin -> add team
  GET    /exercises/{id}/leaderboard      any role -> ranked team scores

  POST   /exercises/{id}/members          admin/lead/operator -> add member

The exercise_id is read in path; team_id is read in path for some
scopes (members); sub is read from the token.

RBAC:
  * create / mutate exercise -> admin only.
  * read the exercise + leaderboard -> admin / lead / observer
    (always) OR any user who is a TeamMember of the exercise.
  * transition between states -> admin only.

Visibility filter (``can_view_exercise``) lives in
``app.services.authorization`` and is shared with the run-level
RBAC so a member of an exercise can see the runs that affect it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import Role, current_token, require_role
from app.db import models as db_models
from app.db.models import (
    Exercise,
    ExerciseStatus,
    Team,
    TeamMembership,
    TeamRole,
)
from app.db.session import get_session


router = APIRouter()


# --- helpers ----------------------------------------------------------


async def _load_exercise_or_404(
    session: AsyncSession, exercise_id: int
) -> Exercise:
    ex = (
        await session.execute(
            select(Exercise)
            .where(Exercise.id == exercise_id)
            .options(
                selectinload(Exercise.runs),
                selectinload(Exercise.teams),
            )
        )
    ).scalar_one_or_none()
    if ex is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"exercise id={exercise_id} not found",
        )
    # Force-load teams eagerly so sync serializer doesn't trigger lazy IO.
    _ = list(ex.teams or [])
    return ex
    if ex is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"exercise id={exercise_id} not found",
        )
    return ex


def _can_view(token, exercise: Exercise, membership_sub: str | None = None) -> bool:
    """Return True iff the token (or no token) is allowed to see this
    exercise. Admin / lead / observer always pass; otherwise the
    user must be a TeamMember of the exercise.
    """
    role = getattr(token, "role", None)
    if role in (Role.ADMIN, Role.LEAD, Role.OBSERVER):
        return True
    if membership_sub is not None:
        # Caller already verified membership in this exercise.
        return True
    # Fallback: defer to the can_view_run-style check using ``sub``.
    sub = getattr(token, "sub", None)
    # We need a fresh DB lookup to be sure; the caller does it.
    return False


# --- create / list / detail -------------------------------------------


@router.post(
    "",
    summary="Create an Exercise",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def create_exercise(
    body: dict,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Create a new Exercise in IDLE state.

    Body::

        {
          "name": "tabletop-2026-09-12",   # unique slug
          "title": "Q3 Tabletop",          # human-friendly
          "scenario_id": 7,                # FK
          "starts_at": "2026-09-12T09:00:00Z",  # optional
          "ends_at":   "2026-09-12T17:00:00Z",  # optional
          "teams": [
            {"name": "red",  "color": "#dc2626"},
            {"name": "blue", "color": "#2563eb"}
          ]
        }
    """
    name = body.get("name")
    title = body.get("title")
    scenario_id = body.get("scenario_id")
    starts_at_raw = body.get("starts_at")
    ends_at_raw = body.get("ends_at")
    teams_raw = body.get("teams") or []
    if not isinstance(name, str) or not isinstance(title, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="name and title must be strings",
        )
    if not isinstance(scenario_id, int):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scenario_id must be an int",
        )
    if not teams_raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="at least one team required",
        )
    # F6: validate the scenario exists. If it doesn't, 404, not
    # a 409 from the FK error. Operators get a clearer message.
    from app.db.models import Scenario
    scen = (
        await session.execute(
            select(Scenario).where(Scenario.id == scenario_id)
        )
    ).scalar_one_or_none()
    if scen is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"scenario id={scenario_id} not found",
        )
    # Parse datetimes (assume ISO 8601 with tz suffix or naive-UTC).
    starts_at = None
    ends_at = None
    if starts_at_raw:
        try:
            starts_at = datetime.fromisoformat(
                starts_at_raw.replace("Z", "+00:00")
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="starts_at must be ISO 8601",
            )
    if ends_at_raw:
        try:
            ends_at = datetime.fromisoformat(
                ends_at_raw.replace("Z", "+00:00")
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="ends_at must be ISO 8601",
            )
    if ends_at is not None and starts_at is not None and ends_at < starts_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ends_at must be >= starts_at",
        )

    ex = Exercise(
        name=name,
        title=title,
        scenario_id=scenario_id,
        starts_at=starts_at,
        ends_at=ends_at,
        status=ExerciseStatus.IDLE,
        created_by=getattr(token, "sub", "unknown"),
    )
    session.add(ex)
    try:
        await session.flush()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"could not create exercise: {exc}",
        )

    # Create the requested teams in IDLE state.
    for t in teams_raw:
        if not isinstance(t, dict) or "name" not in t:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="teams must be a list of {name, color?}",
            )
        team = Team(
            exercise_id=ex.id,
            name=str(t["name"]),
            color=str(t.get("color") or "#888888"),
        )
        session.add(team)

    await session.commit()
    # Don't refresh(ex) -- it invalidates the selectinload. Pull
    # teams with a separate query while the session is still active.
    teams_q = await session.execute(
        select(Team).where(Team.exercise_id == ex.id)
    )
    created_teams = list(teams_q.scalars().all())
    return _serialize_exercise(ex, created_teams)



@router.get(
    "",
    summary="List exercises",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def list_exercises(
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """List exercises visible to the caller.

    Admin/lead/observer see all; red/blue see exercises they're
    a TeamMember of.
    """
    role = getattr(token, "role", None)
    if role in (Role.ADMIN, Role.LEAD, Role.OBSERVER):
        rows = (
            await session.execute(
                select(Exercise).order_by(Exercise.id.desc())
            )
        ).scalars().all()
    else:
        sub = getattr(token, "sub", None)
        rows = (
            await session.execute(
                select(Exercise)
                .join(
                    TeamMembership,
                    TeamMembership.exercise_id == Exercise.id,
                )
                .where(TeamMembership.sub == sub)
                .order_by(Exercise.id.desc())
            )
        ).scalars().all()

    # Bulk-fetch teams for every exercise in one query so we
    # don't N+1 the serialiser.
    out = []
    if rows:
        ex_ids = [r.id for r in rows]
        teams = (
            await session.execute(
                select(Team).where(Team.exercise_id.in_(ex_ids))
            )
        ).scalars().all()
        teams_by_ex: dict[int, list] = {}
        for t in teams:
            teams_by_ex.setdefault(t.exercise_id, []).append(t)
    else:
        teams_by_ex = {}

    for ex in rows:
        out.append(_serialize_exercise(ex, teams_by_ex.get(ex.id, [])))
    return {"items": out, "total": len(out)}


def _serialize_exercise(
    ex: Exercise,
    teams: list[Team] | None = None,
    run_count: int | None = None,
) -> dict:
    """Render an Exercise dict. Pure function (no DB)."""
    if teams is None:
        teams = list(getattr(ex, "teams", []) or [])
    if run_count is None:
        # We can't safely evaluate ex.runs here (would lazy-load).
        # Default to the cached count from the relationship.
        # Callers that need an authoritative count should pass it.
        try:
            _runs = len(ex.runs)
        except Exception:
            _runs = 0
        run_count = _runs
    return {
        "id": ex.id,
        "name": ex.name,
        "title": ex.title,
        "scenario_id": ex.scenario_id,
        "status": ex.status.value if hasattr(ex.status, "value") else ex.status,
        "starts_at": (
            ex.starts_at.isoformat() if ex.starts_at else None
        ),
        "ends_at": (
            ex.ends_at.isoformat() if ex.ends_at else None
        ),
        "created_by": ex.created_by,
        "created_at": (
            ex.created_at.isoformat() if ex.created_at else None
        ),
        "updated_at": (
            ex.updated_at.isoformat() if ex.updated_at else None
        ),
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "color": t.color,
                "score": t.score,
            }
            for t in teams
        ],
        "run_count": run_count,
    }


@router.get(
    "/{exercise_id}",
    summary="Get one exercise",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def get_exercise(
    exercise_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    role = getattr(token, "role", None)
    if role not in (Role.ADMIN, Role.LEAD, Role.OBSERVER):
        sub = getattr(token, "sub", None)
        member = (
            await session.execute(
                select(TeamMembership.id).where(
                    TeamMembership.exercise_id == exercise_id,
                    TeamMembership.sub == sub,
                )
            )
        ).first()
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "you do not have access to this exercise "
                    "(not a team member)"
                ),
            )

    ex = await _load_exercise_or_404(session, exercise_id)
    return _serialize_exercise(ex, list(ex.teams or []))


# --- state transitions -------------------------------------------------


@router.post(
    "/{exercise_id}/start",
    summary="Start the exercise (IDLE -> LIVE)",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def start_exercise(
    exercise_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    ex = await _load_exercise_or_404(session, exercise_id)
    try:
        ex.transition_to(ExerciseStatus.LIVE)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    ex.starts_at = ex.starts_at or datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(ex)
    return _serialize_exercise(ex, list(ex.teams or []))


@router.post(
    "/{exercise_id}/stop",
    summary="Stop the exercise (LIVE -> ENDED)",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def stop_exercise(
    exercise_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    ex = await _load_exercise_or_404(session, exercise_id)
    try:
        ex.transition_to(ExerciseStatus.ENDED)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    ex.ends_at = ex.ends_at or datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(ex)
    return _serialize_exercise(ex, list(ex.teams or []))


@router.post(
    "/{exercise_id}/archive",
    summary="Archive the exercise (any -> ARCHIVED)",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def archive_exercise(
    exercise_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    ex = await _load_exercise_or_404(session, exercise_id)
    try:
        ex.transition_to(ExerciseStatus.ARCHIVED)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await session.commit()
    await session.refresh(ex)
    return _serialize_exercise(ex, list(ex.teams or []))


# --- teams & members --------------------------------------------------


@router.post(
    "/{exercise_id}/teams",
    summary="Add a team to an existing exercise",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def add_team(
    exercise_id: int,
    body: dict,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    ex = await _load_exercise_or_404(session, exercise_id)
    name = body.get("name")
    color = body.get("color") or "#888888"
    if not isinstance(name, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="name must be a string",
        )
    team = Team(exercise_id=ex.id, name=name, color=color)
    session.add(team)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"team {name!r} already exists in this exercise",
        )
    return {
        "id": team.id,
        "name": team.name,
        "color": team.color,
        "score": team.score,
        "exercise_id": ex.id,
    }


@router.post(
    "/{exercise_id}/members",
    summary="Add a member to a team in this exercise",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD,
    ))],
)
async def add_member(
    exercise_id: int,
    body: dict,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    ex = await _load_exercise_or_404(session, exercise_id)
    sub = body.get("sub")
    team_id = body.get("team_id")
    role = body.get("role", "member")
    if not isinstance(sub, str) or not isinstance(team_id, int):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="body must include sub (str) + team_id (int)",
        )
    if role not in ("operator", "member"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="role must be 'operator' or 'member'",
        )
    # Validate team is in this exercise.
    team = (
        await session.execute(
            select(Team).where(
                Team.id == team_id, Team.exercise_id == ex.id
            )
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"team id={team_id} not in exercise id={ex.id}",
        )

    # Capture ex.id before commit; after rollback the session
    # is invalidated and any attempt to read attributes via SQL
    # would fail with MissingGreenlet.
    ex_id = ex.id
    member = TeamMembership(
        sub=sub,
        exercise_id=ex_id,
        team_id=team_id,
        role=TeamRole(role),
    )
    session.add(member)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"user {sub!r} is already a member of exercise id={ex_id}",
        )
    return {
        "id": member.id,
        "sub": sub,
        "exercise_id": ex.id,
        "team_id": team_id,
        "team_name": team.name,
        "role": role,
    }


# --- leaderboard ------------------------------------------------------


@router.get(
    "/{exercise_id}/leaderboard",
    summary="Get ranked team scores for the exercise",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def get_leaderboard(
    exercise_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Return teams ranked by score (descending).

    Aggregates per-team scores from ``Team.score`` (which F5's
    submit-flag endpoint updates). If the exercise has no
    flag Submissions yet, all teams score 0 and the order is by
    team.id (deterministic).
    """
    role = getattr(token, "role", None)
    if role not in (Role.ADMIN, Role.LEAD, Role.OBSERVER):
        sub = getattr(token, "sub", None)
        member = (
            await session.execute(
                select(TeamMembership.id).where(
                    TeamMembership.exercise_id == exercise_id,
                    TeamMembership.sub == sub,
                )
            )
        ).first()
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "you do not have access to this leaderboard "
                    "(not a team member)"
                ),
            )

    ex = await _load_exercise_or_404(session, exercise_id)
    teams = (
        await session.execute(
            select(Team)
            .where(Team.exercise_id == ex.id)
            .order_by(Team.score.desc(), Team.id.asc())
        )
    ).scalars().all()
    return {
        "exercise_id": ex.id,
        "exercise_name": ex.name,
        "exercise_title": ex.title,
        "exercise_status": ex.status.value,
        "teams": [
            {
                "rank": i + 1,
                "team_id": t.id,
                "name": t.name,
                "color": t.color,
                "score": t.score,
            }
            for i, t in enumerate(teams)
        ],
    }
