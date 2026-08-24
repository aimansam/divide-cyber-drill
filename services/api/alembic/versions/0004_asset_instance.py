"""F3 follow-up: drop unique (run_id, role) constraint on assets.

A scenario may declare an asset with ``count: N`` (e.g.
``victim_workstation`` count: 2 to model two workstations on
the same subnet). The 0001 schema enforced (run_id, role)
uniqueness, silently capping count at 1. F3-followup lifts
that constraint so the runner can spawn multiple clones per
declared asset.

This is a one-shot migration on the existing schemas
(sqlite + Postgres). For sqlite we use a batch op to drop
and recreate the table without the unique constraint; for
postgres the unique constraint drops cleanly with
``drop_constraint``.

The runner names instances with a ``_N`` suffix (1-indexed):
   declared role: victim_workstation, count: 2
   DB rows:        role='victim_workstation_1',
                   role='victim_workstation_2'

This keeps the audit log + reports readable ("victim_workstation
#1", "victim_workstation #2") while making the (run_id, role)
no longer assumed-unique. Existing single-count rows have no
suffix (their role stays as declared); the runner only appends
the suffix when count > 1.

Revision ID: 0004_asset_instance
Revises: 0003_users
Create Date: 2026-08-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0004_asset_instance"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the (run_id, role) unique constraint on assets.

    The new constraint is non-unique; multiple clones per declared
    asset are now allowed. We *do not* add a different unique
    constraint — the runner generates sufficiently unique names
    (``divide-<run>-<role>_<N>``).
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_uqs = {
        uq["name"]
        for uq in inspector.get_unique_constraints("assets")
    }

    if "uq_assets_run_role" in existing_uqs:
        # SQLite has no DROP CONSTRAINT; we have to batch-recreate.
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("assets") as batch_op:
                batch_op.drop_constraint(
                    "uq_assets_run_role", type_="unique"
                )
        else:
            op.drop_constraint(
                "uq_assets_run_role", "assets", type_="unique"
            )


def downgrade() -> None:
    """Re-add the (run_id, role) unique constraint.

    Doing this on a non-empty DB would fail if any run has two
    rows with the same role (e.g. count: 2 victim_workstation
    rows). For dev/CI purposes we *attempt* the recreate; if it
    fails the operator already understands the implication from
    the upgrade error.
    """
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("assets") as batch_op:
            batch_op.create_unique_constraint(
                "uq_assets_run_role", ["run_id", "role"]
            )
    else:
        op.create_unique_constraint(
            "uq_assets_run_role", "assets", ["run_id", "role"]
        )
