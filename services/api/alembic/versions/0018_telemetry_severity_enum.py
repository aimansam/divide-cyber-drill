"""Q24-B1: align ``telemetry_events.severity`` with the model.

History:
  * Migration 0008 declared ``severity`` as ``String(16)``.
  * The Python model later declared it as
    ``Enum(TelemetrySeverity, name="telemetry_severity")``.
  * No follow-up migration ever created the ``telemetry_severity``
    PG type or ALTERed the column. As a result every INSERT
    failed with
      ``asyncpg.exceptions.UndefinedObjectError: type
        "telemetry_severity" does not exist``.

Fix:
  * CREATE TYPE ``telemetry_severity`` with the four values
    declared on the Python enum.
  * ALTER COLUMN to use the enum via a USAGE cast.

Why not just revert the model to ``String(16)``?
  * The enum gives Python-side validation in the API layer
    (``TelemetrySeverity(value)`` raises ``ValueError`` on a
    bad bucket). The varchar variant lets arbitrary strings
    sneak in. Keeping the enum is the better long-term move.
  * Reverting would mean changing ~6 sites that import
    ``TelemetrySeverity``; forward-fixing the DB is one
    migration.

Idempotent on re-run:
  * CREATE TYPE IF NOT EXISTS -- PG syntax doesn't support
    this directly; swallow DuplicateObject.
  * ALTER COLUMN ... TYPE -- safe to re-run.

Revision ID: 0018_telemetry_severity_enum
Revises: 0017_audit_run_reset
Create Date: 2026-08-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_telemetry_severity_enum"
down_revision = "0017_audit_run_reset"
branch_labels = None
depends_on = None


def _create_enum_type(name: str, values: list[str]) -> None:
    """CREATE TYPE ... AS ENUM is a Postgres-ism; SQLite has no
    enum type and stores enum members as plain strings under
    the SQLAlchemy Enum() shim.

    Idempotent on re-run: PG's ``DuplicateObject`` is swallowed
    in the catch block.
    """
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    values_sql = ", ".join(f"'{v}'" for v in values)
    sql = sa.text(f"CREATE TYPE {name} AS ENUM ({values_sql})")
    try:
        op.execute(sql)
    except Exception:  # noqa: BLE001
        # DuplicateObject -> already present. Other errors bubble
        # up so we don't hide real migration failures.
        pass


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    _create_enum_type(
        "telemetry_severity",
        ["info", "low", "medium", "high"],
    )
    # SQLite has no enum type, no server_default that prevents
    # the cast, and no PostgreSQL-style ``::type`` cast. Skip on
    # SQLite; the in-memory tests use SQLAlchemy's Enum() which
    # writes the string value directly. The real production
    # deploys on Postgres and will hit the next two branches.
    if dialect == "sqlite":
        return
    # The column has a server_default of ``'info'`` (set in 0008)
    # that Postgres refuses to auto-cast to the new enum type.
    # Drop it before the ALTER; the model-level default on
    # Python side still emits ``info`` for new rows.
    op.execute(
        sa.text(
            "ALTER TABLE telemetry_events "
            "ALTER COLUMN severity DROP DEFAULT"
        )
    )
    # ALTER COLUMN ... TYPE telemetry_severity USING severity::telemetry_severity
    # is safe because every existing value in the column matches
    # one of the four enum members (the column was varchar with a
    # server_default of "info" and only ever written by code paths
    # that went through TelemetrySeverity(value)).
    op.execute(
        sa.text(
            "ALTER TABLE telemetry_events "
            "ALTER COLUMN severity TYPE telemetry_severity "
            "USING severity::telemetry_severity"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        return
    # Reverse the type change. Dropping the enum itself is
    # deliberate -- it's an internal-only type and the next
    # migration up will recreate it if needed.
    op.execute(
        sa.text(
            "ALTER TABLE telemetry_events "
            "ALTER COLUMN severity TYPE varchar(16) "
            "USING severity::varchar"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE telemetry_events "
            "ALTER COLUMN severity SET DEFAULT 'info'"
        )
    )
    op.execute(sa.text("DROP TYPE IF EXISTS telemetry_severity"))
