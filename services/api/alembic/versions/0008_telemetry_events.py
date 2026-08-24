"""F8 SOC view: TelemetryEvent table.

Adds:
  * telemetry_events (id, run_id, asset_id, ts, source, kind,
    severity, payload JSON, audit timestamps)

This is a forward-only migration. Down migration drops the
table.

Revision ID: 0008_telemetry_events
Revises: 0007_templates
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008_telemetry_events"
down_revision = "0007_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_telemetry_run_id_ts",
        "telemetry_events",
        ["run_id", "ts"],
    )
    op.create_index(
        "ix_telemetry_kind", "telemetry_events", ["kind"]
    )
    op.create_index(
        "ix_telemetry_severity", "telemetry_events", ["severity"]
    )
    op.create_index(
        "ix_telemetry_source", "telemetry_events", ["source"]
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_source", table_name="telemetry_events")
    op.drop_index("ix_telemetry_severity", table_name="telemetry_events")
    op.drop_index("ix_telemetry_kind", table_name="telemetry_events")
    op.drop_index("ix_telemetry_run_id_ts", table_name="telemetry_events")
    op.drop_table("telemetry_events")
