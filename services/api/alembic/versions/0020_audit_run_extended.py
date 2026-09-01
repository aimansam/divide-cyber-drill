"""Add ``run.extended`` audit action.

Written when an operator or authorized user extends a running drill's
timeout window (POST /api/v1/drills/{id}/extend-timeout).

Revision ID: 0020_audit_run_extended
Revises: 0019_asset_status_synced
Create Date: 2026-09-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0020_audit_run_extended"
down_revision = "0019_asset_status_synced"
branch_labels = None
depends_on = None


def _safe_add_value(enum_value: str) -> None:
    sql = sa.text(f"ALTER TYPE audit_action ADD VALUE '{enum_value}'")
    try:
        op.execute(sql)
    except Exception:  # noqa: BLE001
        pass


def upgrade() -> None:
    _safe_add_value("run.extended")


def downgrade() -> None:
    pass
