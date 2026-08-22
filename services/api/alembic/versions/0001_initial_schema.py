"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-22 13:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # --- scenarios -------------------------------------------------------
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_scenarios"),
        sa.UniqueConstraint("name", name="uq_scenarios_name"),
    )
    op.create_index("ix_scenarios_difficulty", "scenarios", ["difficulty"])
    op.create_index("ix_scenarios_updated_at", "scenarios", ["updated_at"])

    # --- runs ------------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "succeeded", "failed", "timeout", "cancelled",
                name="run_status",
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by", sa.String(length=64), nullable=True),
        sa.Column("score_blue", sa.Integer(), nullable=True),
        sa.Column("score_red", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["scenarios.id"], name="fk_runs_scenario_id_scenarios", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
    )
    op.create_index("ix_runs_scenario_id", "runs", ["scenario_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_started_at", "runs", ["started_at"])

    # --- assets ----------------------------------------------------------
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("template", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "planned", "cloning", "booting", "running", "stopping",
                "stopped", "failed", "orphaned",
                name="asset_status",
            ),
            nullable=False,
        ),
        sa.Column("pve_vmid", sa.BigInteger(), nullable=True),
        sa.Column("pve_node", sa.String(length=64), nullable=True),
        sa.Column("pve_ip", sa.String(length=45), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_assets_run_id_runs", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assets"),
        sa.UniqueConstraint("run_id", "role", name="uq_assets_run_role"),
    )
    op.create_index("ix_assets_run_id", "assets", ["run_id"])
    op.create_index("ix_assets_status", "assets", ["status"])

    # --- audit_log -------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "scenario.created", "scenario.updated", "scenario.deleted",
                "run.started", "run.completed", "run.failed", "run.cancelled",
                "asset.spawned", "asset.failed", "asset.orphaned",
                name="audit_action",
            ),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=64), nullable=True),
        sa.Column("scenario_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["scenarios.id"], name="fk_audit_log_scenario_id_scenarios", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_audit_log_run_id_runs", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name="fk_audit_log_asset_id_assets", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_actor", "audit_log", ["actor"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_actor", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_at", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("ix_assets_status", table_name="assets")
    op.drop_index("ix_assets_run_id", table_name="assets")
    op.drop_table("assets")

    op.drop_index("ix_runs_started_at", table_name="runs")
    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_scenario_id", table_name="runs")
    op.drop_table("runs")

    op.drop_index("ix_scenarios_updated_at", table_name="scenarios")
    op.drop_index("ix_scenarios_difficulty", table_name="scenarios")
    op.drop_table("scenarios")

    # Enum types are dropped automatically with their tables in modern
    # Postgres; explicit DROP TYPE would only be needed for very old PG.
