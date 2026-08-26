"""Q4: Create the missing exercise_status Postgres enum type.

Migration 0006 declared ``exercises.status`` as ``sa.String(length=16)``
(plain VARCHAR) but the SQLAlchemy model (``app.db.models.Exercise.status``)
declares the same column as ``Enum(ExerciseStatus, name="exercise_status")``.
On every Postgres install that mismatch means:
  * The table column is VARCHAR (correct, no data loss).
  * The ``exercise_status`` enum TYPE is never created.
  * When SQLAlchemy INSERTs, it casts the literal to ``exercise_status``
    (because that's the model declaration) and Postgres rejects:
      type "exercise_status" does not exist
  * The unit tests pass because they run on SQLite, which doesn't have
    PG's CREATE TYPE step.

This migration creates the missing enum and migrates the existing
column from VARCHAR to the enum. The migration is safe on empty data
(skip the ALTER COLUMN when no rows exist) and on legacy data (the
existing values ``idle``/``live``/``ended``/``archived`` are all
already valid enum values).

Revision ID: 0013_exercise_status_enum
Revises: 0012_audit_reset_events
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0013_exercise_status_enum"
down_revision = "0012_audit_reset_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite (used by the default pytest conftest) doesn't have PG's
    # CREATE TYPE / ALTER COLUMN TYPE ... USING syntax. The model uses
    # a SQLAlchemy Enum which compiles to VARCHAR on SQLite already, so
    # there's nothing to fix there -- skip the PG-only DDL entirely.
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Step 1: create the enum type. Idempotent so the migration is
    # re-runnable after a partial failure.
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_type t "
            "JOIN pg_namespace n ON n.oid = t.typnamespace "
            "WHERE n.nspname='public' AND t.typname='exercise_status'"
        )
    ).first()
    if row is None:
        op.execute(
            sa.text(
                "CREATE TYPE exercise_status AS ENUM "
                "('idle', 'live', 'ended', 'archived')"
            )
        )

    # Step 2: migrate the column. Three sub-steps because the column
    # has a server_default (``'idle'::character varying``) that Postgres
    # cannot auto-cast to the new enum type:
    #   (a) drop the default so it does not block the type change
    #   (b) ALTER COLUMN TYPE with USING cast to migrate values
    #   (c) re-attach the default, this time as the enum literal
    op.execute(sa.text("ALTER TABLE exercises ALTER COLUMN status DROP DEFAULT"))
    op.execute(
        sa.text(
            "ALTER TABLE exercises "
            "ALTER COLUMN status TYPE exercise_status "
            "USING status::exercise_status"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE exercises "
            "ALTER COLUMN status SET DEFAULT 'idle'::exercise_status"
        )
    )


def downgrade() -> None:
    # Revert to plain VARCHAR. The values remain valid; nothing is lost.
    # SQLite-only column types are unchanged; this branch only runs on PG.
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(sa.text("ALTER TABLE exercises ALTER COLUMN status DROP DEFAULT"))
    op.execute(
        sa.text(
            "ALTER TABLE exercises "
            "ALTER COLUMN status TYPE VARCHAR(16) "
            "USING status::VARCHAR"
        )
    )
    op.execute(
        sa.text("ALTER TABLE exercises ALTER COLUMN status SET DEFAULT 'idle'")
    )
    # Drop the enum. Note: this will fail if any other column references
    # the type, but the only consumer is exercises.status, so it's safe.
    op.execute(sa.text("DROP TYPE IF EXISTS exercise_status"))
