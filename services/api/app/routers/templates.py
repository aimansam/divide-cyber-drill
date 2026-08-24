"""F7: Range Template endpoints.

Endpoints:

  GET    /templates                              any role -> list
  POST   /templates                              admin    -> create
  GET    /templates/{id}                         any role -> detail
  DELETE /templates/{id}                         admin    -> delete
  POST   /templates/{id}/clone                   any role -> spawn run

POST /templates/{id}/clone reuses POST /drills semantics with
``template_id`` set; the run is then driven against the
template's snapshot.  See F7.2 for the reset endpoint.

RBAC:
  * create / delete -> admin only
  * read -> any role (admin / lead / observer / red / blue /
    team members of any exercise the template is associated with)

The "team members" filter is intentionally NOT applied to
templates.  Templates are shared, public-by-default range
artifacts.  A future "private" tier can gate that if needed.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Role, current_token, require_role
from app.db import models as db_models
from app.db.models import Run, Template
from app.db.session import get_session


router = APIRouter()


# --- helpers -----------------------------------------------------------


def _serialize_template(t: Template) -> dict[str, Any]:
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


async def _load_template_or_404(
    session: AsyncSession, template_id: int
) -> Template:
    t = (
        await session.execute(
            select(Template).where(Template.id == template_id)
        )
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"template id={template_id} not found",
        )
    return t


def _build_snapshot(run: Run, scenario: db_models.Scenario) -> dict[str, Any]:
    """Build the immutable snapshot dict for a Run's template.

    Pulls assets / flags / networks / scoring from the scenario
    spec so the template is self-contained -- replaying a run
    doesn't need to re-query the live scenario row (handy for
    cold-storage / backup).
    """
    spec = scenario.spec or {}
    inner = spec.get("spec", spec) if isinstance(spec, dict) else {}
    return {
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "scenario_version": scenario.version,
        "assets": list(inner.get("assets", []) or []),
        "flags": list(inner.get("flags", []) or []),
        "networks": list(inner.get("networks", []) or []),
        "scoring": inner.get("scoring", {}),
        "win_conditions": inner.get("win_conditions", {}),
        "run_status_at_snapshot": run.status.value,
    }


# --- create / list / detail --------------------------------------------


@router.post(
    "",
    summary="Create a Template from a Run",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def create_template(
    body: dict,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """Create a Template by snapshotting an existing Run.

    Body::

        {
          "name": "router-baseline-v1",
          "title": "Router Baseline (v1)",
          "description": "Working state from 2026-08-25 drill",
          "from_run_id": 42,
        }

    The source Run must be in a terminal state (SUCCEEDED / FAILED
    / ENDED).  ``scenario_id`` and ``snapshot`` are derived from
    the source Run's scenario.
    """
    name = body.get("name")
    title = body.get("title")
    description = body.get("description", "")
    from_run_id = body.get("from_run_id")
    if not isinstance(name, str) or not isinstance(title, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="name + title must be strings",
        )
    if not isinstance(from_run_id, int):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from_run_id must be an int",
        )
    # Capture source Run + scenario eagerly.  After we potentially
    # fail to commit, reading attributes on `run` or `scen` from
    # a rolled-back session would trigger lazy-load and crash
    # (the lesson learned in F6).
    run = (
        await session.execute(
            select(Run).where(Run.id == from_run_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run id={from_run_id} not found",
        )
    if run.status.value not in ("succeeded", "failed", "ended"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"run id={from_run_id} is {run.status.value}; "
                "templates can only be created from terminal runs"
            ),
        )
    scenario = (
        await session.execute(
            select(db_models.Scenario).where(
                db_models.Scenario.id == run.scenario_id
            )
        )
    ).scalar_one_or_none()
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"run id={from_run_id} references missing scenario"
            ),
        )
    scenario_id = scenario.id
    snapshot = _build_snapshot(run, scenario)

    template = Template(
        name=name,
        title=title,
        description=description,
        from_run_id=from_run_id,
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
            detail=(
                f"a template named {name!r} already exists"
            ),
        )
    return _serialize_template(template)


@router.get(
    "",
    summary="List templates",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def list_templates(
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    """List all templates (templates are shared across roles).

    Filters apply if a future "private" tier is added.
    """
    rows = (
        await session.execute(
            select(Template).order_by(Template.id.desc())
        )
    ).scalars().all()
    return {
        "items": [_serialize_template(t) for t in rows],
        "total": len(rows),
    }


@router.get(
    "/{template_id}",
    summary="Get one template",
    dependencies=[Depends(require_role(
        Role.ADMIN, Role.LEAD, Role.OBSERVER, Role.RED, Role.BLUE,
    ))],
)
async def get_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    t = await _load_template_or_404(session, template_id)
    return _serialize_template(t)


@router.delete(
    "/{template_id}",
    summary="Delete a template",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def delete_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
    token=Depends(current_token),
) -> dict:
    t = await _load_template_or_404(session, template_id)
    template_name = t.name
    await session.delete(t)
    await session.commit()
    return {
        "deleted": template_id,
        "name": template_name,
    }
