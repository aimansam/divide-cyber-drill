"""F6 multi-team: Exercise / Team / TeamMembership tables + Run.team + Run.exercise_id.

Adds:
  * exercises (id, name, title, scenario_id, status, starts_at,
    ends_at, created_by, audit timestamps)
  * teams (id, exercise_id, name, color, score)
  * team_memberships (id, sub, exercise_id, team_id, role)
  * runs.exercise_id (FK exercises; nullable so legacy runs OK)
  * runs.team (string; nullable so legacy runs OK)

Unique constraints:
  * teams.name is unique within an exercise
  * team_memberships(sub, exercise_id) is unique

This is a forward-only migration. Down migration drops the new
columns + tables.

Revision ID: 0006_exercises
Revises: 0005_flag_submissions
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006_exercises"
down_revision = "0005_flag_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # exercises must be created BEFORE the FK on runs.exercise_id
    # references it. The batch_alter_table block below emits an
    # ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY which PostgreSQL
    # validates immediately against the referenced table.
    op.create_table(
        "exercises",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="idle"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
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
            ["scenario_id"], ["scenarios.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("name", name="uq_exercises_name"),
    )
    op.create_index("ix_exercises_status", "exercises", ["status"])
    op.create_index("ix_exercises_scenario_id", "exercises", ["scenario_id"])

    # Add Run columns AFTER exercises exists so the FK resolves.
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "exercise_id",
                sa.Integer(),
                sa.ForeignKey("exercises.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("team", sa.String(length=16), nullable=True)
        )

    # teams
    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False, server_default="#888888"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
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
            ["exercise_id"], ["exercises.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "exercise_id", "name", name="uq_teams_exercise_name"
        ),
    )

    # team_memberships
    op.create_table(
        "team_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sub", sa.String(length=64), nullable=False),
        sa.Column("exercise_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
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
            ["exercise_id"], ["exercises.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "sub", "exercise_id",
            name="uq_team_membership_user_exercise",
        ),
    )


def downgrade() -> None:
    # Drop Run columns first (via batch so SQLite handles the FK).
    # Otherwise the FK from runs.exercise_id -> exercises.id blocks
    # the drop_column inside a non-batch op, and batch_alter_table
    # reflects the FK target (exercises) which is gone if we drop
    # it first.
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("team")
        batch_op.drop_column("exercise_id")
    op.drop_table("team_memberships")
    op.drop_table("teams")
    op.drop_index("ix_exercises_scenario_id", table_name="exercises")
    op.drop_index("ix_exercises_status", table_name="exercises")
    op.drop_table("exercises")
