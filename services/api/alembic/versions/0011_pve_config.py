"""Add PVE runtime config table (web-only day-1 setup).

Adds a single-row table that the onboarding wizard can populate from the
browser instead of requiring ``deploy/.env`` edits + container restart.

Resolution order (see ``services/proxmox.py``):
    1. ``pve_config`` row in DB (set by ``POST /api/v1/admin/pve-config``)
    2. ``PROXMOX_*`` env vars on the API container

The table has no unique constraint besides the primary key -- it is a
singleton by convention. The ``id`` is hard-coded to 1 in every write
path (see ``services/pve_config.py:upsert_config``); if the row is
deleted and recreated, it can take any id but stays at id=1 because
we explicitly INSERT ... ON CONFLICT (id) DO UPDATE.

The token_secret column stores plain text (same risk profile as
``users.password_hash``). It is NEVER returned from the API: the
``to_public_dict`` method on the model masks it as ``"***"`` before
serialization.

This is a forward-only migration. The down drops the table, which
silently reverts the operator back to env-only configuration -- a
perfectly usable state for any deployment that hadn't yet adopted the
wizard's PVE-credentials step.

Revision ID: 0011_pve_config
Revises: 0010_user_reset_tokens
Create Date: 2026-08-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0011_pve_config"
down_revision = "0010_user_reset_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pve_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        # F3-prep pattern: env is for boot, DB is for runtime. The
        # NOT NULL here is intentional -- if a row exists, it must
        # be complete. The service layer rejects writes that leave
        # any of these blank.
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="8006"),
        sa.Column("user", sa.String(length=255), nullable=False),
        sa.Column("token_id", sa.String(length=255), nullable=False),
        sa.Column("token_secret", sa.String(length=255), nullable=False),
        # Default False: most PVE installs use a self-signed cert; the
        # wizard form pre-checks this for the operator.
        sa.Column(
            "verify_ssl",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("node", sa.String(length=64), nullable=True),
        # Who last touched this. The endpoint sets it from the JWT
        # sub; nullable so a fresh row can be inserted without
        # coupling to the users table (chicken-and-egg: at first
        # boot there is no admin yet).
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        # ``func.now()`` is portable: ``sa.text("now()")`` is
        # Postgres-specific and breaks sqlite tests. SQLAlchemy
        # compiles ``func.now()`` to the right dialect's CURRENT_TIMESTAMP.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # No index needed -- singleton table, lookups are by PK only.
    # The TimestampMixin audit columns (created_at, updated_at) let us
    # reconstruct who-when without a separate audit_log row, but the
    # router also writes an audit_log entry on POST/DELETE so the
    # day-2 admin's PveOpsCard can render a "config last changed"
    # line without us writing it here.


def downgrade() -> None:
    op.drop_table("pve_config")
