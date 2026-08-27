"""Global audit-log endpoints.

Exposed at ``/api/v1/audit/*``. Q21 added a single endpoint:

  * ``GET /audit``                         -- cross-run audit search

Unlike ``GET /drills/{id}/audit`` (which scopes to a single run),
this endpoint lets admins/leads/observers search the entire
``audit_log`` table. Filters: ``action`` (substring), ``actor``
(exact), ``run_id`` (exact), ``since`` (ISO), ``until`` (ISO),
``limit`` (default 200, capped at 1000).

Use cases:
  * "Show me every ``run.failed`` in the last 24h"
  * "What did admin do today"
  * "All events on drill #42"

Q21 deliberately keeps the result list the same shape as the
per-run audit endpoint so the portal's existing row renderer
can be reused with minor refactoring.

RBAC: admin, lead, observer. Red/blue can read their own drill
audits via the per-run endpoint but not the global feed -- they
shouldn't see other trainees' events.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Role, require_role
from app.db import models as db_models
from app.db.session import get_session

log = structlog.get_logger()

# Q21: admin/lead/observer get the global audit feed. Red/blue
# are explicitly excluded -- they can read their own drill's
# audit via ``GET /api/v1/drills/{id}/audit`` but never the
# cross-tenant stream.
router = APIRouter(
    dependencies=[Depends(require_role(Role.ADMIN, Role.LEAD, Role.OBSERVER))],
)


@router.get(
    "",
    summary="Cross-run audit-log search",
)
async def search_audit(
    session: AsyncSession = Depends(get_session),
    action: str | None = Query(
        None,
        description="Substring match on the action enum (case-insensitive). "
        "e.g. 'run.failed' matches ``run.failed``.",
    ),
    actor: str | None = Query(
        None,
        description="Exact match on the actor (token subject). "
        "Use 'system' for events with no actor.",
    ),
    run_id: int | None = Query(
        None,
        description="Filter to events tied to one run.",
    ),
    since: datetime | None = Query(
        None,
        description="Lower bound on ``at`` (ISO 8601). Inclusive.",
    ),
    until: datetime | None = Query(
        None,
        description="Upper bound on ``at`` (ISO 8601). Exclusive.",
    ),
    limit: int = Query(
        200,
        ge=1,
        le=1000,
        description="Maximum rows to return. Default 200, capped at 1000.",
    ),
) -> dict[str, Any]:
    """Search the audit log across all runs.

    Newest-first. Response mirrors the per-run audit endpoint's
    ``items`` shape so a future portal refactor can reuse the
    existing renderer.
    """
    stmt = select(db_models.AuditLog).order_by(db_models.AuditLog.at.desc())

    if action is not None:
        # PG native enum columns don't have an ILIKE operator.
        # Cast to text so the substring match works against the
        # ``values_callable`` string values (``run.failed``,
        # ``run.stopped`` etc).
        stmt = stmt.where(
            db_models.AuditLog.action.cast(db_models.String).ilike(f"%{action}%")
        )
    if actor is not None:
        stmt = stmt.where(db_models.AuditLog.actor == actor)
    if run_id is not None:
        stmt = stmt.where(db_models.AuditLog.run_id == run_id)
    if since is not None:
        stmt = stmt.where(db_models.AuditLog.at >= since)
    if until is not None:
        stmt = stmt.where(db_models.AuditLog.at < until)

    stmt = stmt.limit(limit)

    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "at": r.at.isoformat() if r.at else None,
                "action": r.action.value,
                "actor": r.actor,
                "scenario_id": r.scenario_id,
                "asset_id": r.asset_id,
                "run_id": r.run_id,
                "details": r.details,
            }
            for r in rows
        ],
        "total": len(rows),
        "limit": limit,
    }


__all__ = ["router", "search_audit"]
