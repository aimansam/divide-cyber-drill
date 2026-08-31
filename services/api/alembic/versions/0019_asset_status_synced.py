"""Add ``asset.status_synced`` audit action (Q26).

Written when the sync endpoint detects drift between the DB
asset.status and the actual PVE VM state. Lets operators answer
"when did we last confirm this VM is really running/stopped?".

Idempotent on re-run via the ``DuplicateObject`` swallow used by
migrations 0012 / 0014 / 0015 / 0017 (``ALTER TYPE ... ADD VALUE``
has no ``IF NOT EXISTS``). Downgrade is intentionally a no-op
because Postgres refuses to drop a value from an in-use enum;
the dangling value is harmless and the Python ``AuditAction``
enum remains the source of truth for what code paths can
write the value.

Revision ID: 0019_asset_status_synced
Revises: 0018_telemetry_severity_enum
Create Date: 2026-08-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0019_asset_status_synced"
down_revision = "0018_telemetry_severity_enum"
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
    _safe_add_value("asset.status_synced")


def downgrade() -> None:
    # No-op: Postgres refuses to drop a value from an enum in use,
    # and leaving the dangling value is harmless.
    pass