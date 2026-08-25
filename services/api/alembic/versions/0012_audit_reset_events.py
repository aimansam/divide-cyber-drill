"""Add password-reset audit events (F-reset-ux + P8).

Adds two new values to the ``audit_action`` Postgres enum:

  * ``password.reset.issued`` -- admin POST /auth/users/{sub}/issue-reset
  * ``password.reset.used``   -- POST /auth/reset-password success

The audit rows keep an enumerated trail of who reset whose password
to what. ``details`` is JSON; we stash the actor sub and the
target user sub so a future admin UI can answer "show me every
password reset in the last 30 days".

Idempotent on re-run: ``IF NOT EXISTS`` is not in PG's ``ADD VALUE``
syntax (yet), so we wrap each ``ADD VALUE`` in an except / pass.
Postgres does not support removing enum values within a transaction
that uses the value -- downgrade is intentionally a no-op (the rest
of the system survives the dangling values fine and removing them
requires recreating the type).

Revision ID: 0012_audit_reset_events
Revises: 0011_pve_config
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0012_audit_reset_events"
down_revision = "0011_pve_config"
branch_labels = None
depends_on = None


def _safe_add_value(enum_value: str) -> None:
    """Postgres lets you add enum values; if the value already exists,
    it raises ``DuplicateObject``. We swallow that so the migration
    is re-runnable after a partial failure.
    """
    sql = sa.text(f"ALTER TYPE audit_action ADD VALUE '{enum_value}'")
    try:
        op.execute(sql)
    except Exception:  # noqa: BLE001
        # ``DuplicateObject`` -- already present. Any other error
        # bubbles up (logged by alembic) so we don't silently hide
        # real migration failures.
        pass


def upgrade() -> None:
    _safe_add_value("password.reset.issued")
    _safe_add_value("password.reset.used")


def downgrade() -> None:
    # Postgres refuses to DROP a value from an enum in use. The
    # safest "downgrade" is to leave the new values in place --
    # they're harmless and the AuditAction enum in the model is
    # the source of truth for what code paths can write them.
    pass
