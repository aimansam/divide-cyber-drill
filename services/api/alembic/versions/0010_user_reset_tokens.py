"""Add password-reset token fields to users table (F-reset-ux).

Adds two columns to ``users``:

  * ``reset_token``        -- opaque random token (URL-safe base64, ~32
                              bytes raw -> ~43 chars). Null when no
                              reset is pending. Acts as a one-time
                              bearer credential: the reset endpoint
                              validates ``reset_token == request.token``
                              AND that ``reset_token_expires_at`` is
                              in the future.
  * ``reset_token_expires_at`` -- unix timestamp (UTC) when the token
                              stops being valid. 24h after issuance by
                              convention (see ``_RESET_TOKEN_TTL_S``
                              in services/users.py).

Why this shape (vs. a separate ``password_resets`` table):

  * One active reset per user at a time is the only thing we need.
    A separate table would let a user have multiple in-flight
    resets; that's not a useful feature.
  * The token lives with the user row, so admin-issued resets,
    user-issued resets, and the audit trail are all in one place.
  * The columns are nullable, so existing rows are unaffected and
    the migration is reversible without data loss.

This is a forward-only migration. Down migration drops both
columns. If a user has a pending reset when the down runs, that
reset is silently invalidated (they'll have to request a new one).

Revision ID: 0010_user_reset_tokens
Revises: 0009_wg_peer
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_user_reset_tokens"
down_revision = "0009_wg_peer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("reset_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "reset_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # No index on ``reset_token``: it's a low-cardinality column
    # (mostly NULL) and lookup is by primary key + equality, which
    # is one row even on a million-row users table. Adding an
    # index would just slow down inserts for no win.


def downgrade() -> None:
    op.drop_column("users", "reset_token_expires_at")
    op.drop_column("users", "reset_token")
