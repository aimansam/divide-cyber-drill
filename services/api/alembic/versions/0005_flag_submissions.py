"""F5: add flag_submissions table.

The F5 plan introduces a flag-submission primitive where:
  * Each scenario declares ``spec.flags[]``: a list of
    {id, side, value, planted_on_role, decay_window_seconds,
    base_points}.
  * The runner plants the value on the right asset (typically via
    cloud-init user_data; out of scope for the schema commit).
  * A team captures a flag via POST /api/v1/drills/{id}/submit-flag.
  * Points = base * max(0, 1 - elapsed/window).

The flag_submissions table records each captured flag; the unique
constraint uq_flag_submissions_run_flag_team prevents double-
scoring. Scoring is frozen at capture time.

Revision ID: 0005_flag_submissions
Revises: 0004_asset_instance
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_flag_submissions"
down_revision = "0004_asset_instance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flag_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("flag_id", sa.String(length=64), nullable=False),
        sa.Column("team", sa.String(length=16), nullable=False),
        sa.Column("submitted_by", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=False),
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
            ["run_id"], ["runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "run_id", "flag_id", "team",
            name="uq_flag_submissions_run_flag_team",
        ),
    )
    op.create_index(
        "ix_flag_submissions_run_id",
        "flag_submissions",
        ["run_id"],
    )
    op.create_index(
        "ix_flag_submissions_team",
        "flag_submissions",
        ["team"],
    )
def downgrade() -> None:
    op.drop_index("ix_flag_submissions_team", table_name="flag_submissions")
    op.drop_index("ix_flag_submissions_run_id", table_name="flag_submissions")
    op.drop_table("flag_submissions")
