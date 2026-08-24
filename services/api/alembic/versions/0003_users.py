"""users table for F3-prep credential login

Adds a ``users`` table backing ``POST /api/v1/auth/login``. The
existing ``tools/issue_token.py`` paste-your-token flow keeps
working; this just adds an alternative path so the LAN demo can
ship username + password UX without an IdP.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sub", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("sub", name="uq_users_sub"),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_disabled", "users", ["disabled"])


def downgrade() -> None:
    op.drop_index("ix_users_disabled", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_table("users")
