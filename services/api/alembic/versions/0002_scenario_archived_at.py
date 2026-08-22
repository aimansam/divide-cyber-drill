"""add archived_at to scenarios

Soft-delete column. Set by the sync when the backing YAML disappears
from the catalog. NULL = active. We never hard-delete a scenario
because Runs FK into it for after-action reports.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scenarios",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Useful for filtering active vs archived at the catalog layer.
    op.create_index(
        "ix_scenarios_archived_at",
        "scenarios",
        ["archived_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scenarios_archived_at", table_name="scenarios")
    op.drop_column("scenarios", "archived_at")
