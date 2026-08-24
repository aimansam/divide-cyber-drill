"""F7 range templates: Template table + Run.template_id.

Adds:
  * templates (id, name, title, description, from_run_id,
    scenario_id, snapshot JSON, created_by, audit timestamps)
  * runs.template_id (FK templates; nullable so legacy runs OK)

This is a forward-only migration. Down migration drops the new
column + table.

Revision ID: 0007_templates
Revises: 0006_exercises
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_templates"
down_revision = "0006_exercises"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New Template table
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("from_run_id", sa.Integer(), nullable=True),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
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
            ["from_run_id"], ["runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["scenarios.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("name", name="uq_templates_name"),
    )
    op.create_index(
        "ix_templates_scenario_id", "templates", ["scenario_id"]
    )
    op.create_index(
        "ix_templates_created_by", "templates", ["created_by"]
    )

    # Run.template_id (nullable, SET NULL on delete)
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "template_id",
                sa.Integer(),
                sa.ForeignKey("templates.id", ondelete="SET NULL"),
                nullable=True,
            )
        )


def downgrade() -> None:
    # Drop Run.template_id first so FK reference is gone.
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("template_id")
    op.drop_index("ix_templates_created_by", table_name="templates")
    op.drop_index("ix_templates_scenario_id", table_name="templates")
    op.drop_table("templates")
