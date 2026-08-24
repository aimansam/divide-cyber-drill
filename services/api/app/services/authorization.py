"""Role-based access control (RBAC) for Run visibility.

This module implements the persona matrix from
``docs/USER-REQUIREMENTS.md`` §2 as a query-level filter, so the
same visibility rule applies to list endpoints, detail endpoints,
audit endpoints, and the future report endpoint. The matrix:

    +------------+----------------------------------+
    | Role       | Visibility                       |
    +============+==================================+
    | admin      | All runs                         |
    | lead       | All runs                         |
    | observer   | All runs (read-only)             |
    | red        | Only runs where started_by == sub |
    | blue       | Only runs where started_by == sub |
    | (anon)     | None (depends on endpoint gate)   |
    +------------+----------------------------------+

Why a separate service and not a per-endpoint helper:
  * The matrix is one coherent rule. If it lives in 4 endpoints
    and one of them drifts, you get a security bug that looks
    like a feature.
  * The same filter applies to list queries (SELECT ... WHERE)
    and single-row checks (can I see this row?). Splitting them
    into two helpers forces the same rule into both code paths.
  * Tests can parametrize over (role, expected count) without
    instantiating any endpoint.

What's NOT here:
  * The role gate itself (401 / 403 on the request) lives in
    ``app.core.auth.require_role``. This module assumes the
    caller has already passed that gate.
  * Ownership of assets within a Run. Once red is on the team
    that owns a run, they see all of its assets. Per-asset
    ownership is L3 work (3.3 quota / 3.4 per-user library).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, false, select

from app.core.auth import Role
from app.db import models as db_models

if TYPE_CHECKING:
    from app.core.auth import TokenData


# Roles that can see every run in the system. Adding a new
# "see-all" role (e.g. auditor, watchdog) is a one-line change
# here; the rest of the code adapts automatically.
SEE_ALL_ROLES: frozenset[str] = frozenset(
    {
        Role.ADMIN.value,
        Role.LEAD.value,
        Role.OBSERVER.value,
    }
)

# Roles that see only their own runs (filtered by token.sub ==
# Run.started_by). Adding a new "see-own" role is also one line.
SEE_OWN_ROLES: frozenset[str] = frozenset(
    {
        Role.RED.value,
        Role.BLUE.value,
    }
)


def visible_runs_query(token: "TokenData | None") -> Select:
    """Build a SELECT for the Run rows this token is allowed to see.

    Use as the base query in list endpoints::

        stmt = visible_runs_query(token).order_by(Run.id.desc())
        rows = (await session.execute(stmt)).scalars().all()

    Anonymous callers (``token is None``) get a query that always
    returns no rows. The endpoint gate (require_token / require_role)
    should have already rejected them with 401, but defense in depth:
    if a future router forgets the gate, the visibility filter still
    returns nothing rather than leaking data.

    Unknown role strings (defensive -- shouldn't happen with
    :class:`Role`-restricted tokens, but the token format allows
    any string) get the same empty-result treatment as anon.
    """
    q = select(db_models.Run)
    if token is None:
        return q.where(false())
    if token.role in SEE_ALL_ROLES:
        return q
    if token.role in SEE_OWN_ROLES:
        return q.where(db_models.Run.started_by == token.sub)
    # Unknown role -- fail closed.
    return q.where(false())


def can_view_run(token: "TokenData | None", run: db_models.Run) -> bool:
    """Single-row visibility check. Used by GET /drills/{id} and
    GET /drills/{id}/audit to decide between 200 and 403.

    We deliberately do NOT distinguish "not yours" from "doesn't
    exist" -- both return 403 from the caller side, which avoids
    leaking the existence of runs the caller shouldn't know about.
    Endpoints that already raised 404 before this gate keep their
    404 behavior; this function only answers the 200-vs-403
    question.
    """
    if token is None:
        return False
    if token.role in SEE_ALL_ROLES:
        return True
    if token.role in SEE_OWN_ROLES:
        return run.started_by == token.sub
    return False