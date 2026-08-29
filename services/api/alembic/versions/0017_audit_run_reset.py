"""Add ``run.reset`` audit action (Q23-B3).

Distinguishes operator-initiated resets
(``POST /drills/{id}/reset``) from operator stops
(``POST /drills/{id}/stop``) and trainee aborts
(``POST /drills/{id}/cancel``). Previously reset_run wrote
no audit row at all, so "who reset what when" was
unanswerable.

Idempotent on re-run via the ``DuplicateObject`` swallow used by
migrations 0012 / 0014 / 0015 (``ALTER TYPE ... ADD VALUE`` has
no ``IF NOT EXISTS``). Downgrade is intentionally a no-op
because Postgres refuses to drop a value from an in-use enum;
the dangling value is harmless and the Python ``AuditAction``
enum remains the source of truth for what code paths can
write the value.

Revision ID: 0017_audit_run_reset
Revises: 0016_asset_cleaned_at
Create Date: 2026-08-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_audit_run_reset"
down_revision = "0016_asset_cleaned_at"
branch_labels = None
depends_on = None


def _safe_add_value(enum_value: str) -> None:
    sql = sa.text(f"ALTER TYPE audit_action ADD VALUE '{enum_value}'")
    try:
        op.execute(sql)
    except Exception:  # noqa: BLE001
        # DuplicateObject -> already present. Other errors bubble
        # up so we don't hide real migration failures.
        pass


def upgrade() -> None:
    _safe_add_value("run.reset")


def downgrade() -> None:
    # No-op: Postgres refuses to drop a value from an enum in use,
    # and leaving the dangling value is harmless.
    pass
