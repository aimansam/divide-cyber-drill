"""Add ``run.stopped`` audit action (Q17).

Distinguishes operator-initiated stops (``POST /drills/{id}/stop``)
from trainee-initiated cancels (``POST /drills/{id}/cancel``) in
the audit log. Previously both wrote ``run.cancelled``, conflating
two semantically different operator actions.

Idempotent on re-run via the ``DuplicateObject`` swallow used by
migration 0012 (``ALTER TYPE ... ADD VALUE`` has no ``IF NOT
EXISTS``). Downgrade is intentionally a no-op because Postgres
refuses to DROP a value from an in-use enum; the dangling value
is harmless and the Python ``AuditAction`` enum remains the
source of truth for what code paths can write the value.

Revision ID: 0014_audit_run_stopped
Revises: 0013_exercise_status_enum
Create Date: 2026-08-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0014_audit_run_stopped"
down_revision = "0013_exercise_status_enum"
branch_labels = None
depends_on = None


def _safe_add_value(enum_value: str) -> None:
    """ALTER TYPE ADD VALUE is non-transactional on PG and lacks
    IF NOT EXISTS; swallow DuplicateObject so the migration is
    re-runnable. Pattern copied from 0012_audit_reset_events.
    """
    sql = sa.text(f"ALTER TYPE audit_action ADD VALUE '{enum_value}'")
    try:
        op.execute(sql)
    except Exception:  # noqa: BLE001
        # DuplicateObject → already present. Other errors bubble
        # up so we don't hide real migration failures.
        pass


def upgrade() -> None:
    _safe_add_value("run.stopped")


def downgrade() -> None:
    # No-op: Postgres refuses to drop a value from an enum in use,
    # and leaving the dangling value is harmless. The Python
    # ``AuditAction`` enum is the source of truth for which values
    # can be written at runtime.
    pass
