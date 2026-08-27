"""Add ``assets.cleaned_at`` (Q22).

The orphan-cleanup endpoint stamps this column when it
successfully releases a PVE VM that the teardown loop failed to
destroy (see Q17 runner code that flips the asset row to
``AssetStatus.ORPHANED``). Keeping the row (vs hard-delete)
preserves the audit log linkage and the run's history.

Revision ID: 0016_asset_cleaned_at
Revises: 0015_audit_asset_cleaned
Create Date: 2026-08-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0016_asset_cleaned_at"
down_revision = "0015_audit_asset_cleaned"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column(
            "cleaned_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("assets", "cleaned_at")
