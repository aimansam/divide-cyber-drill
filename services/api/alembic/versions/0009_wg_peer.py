"""Add wg_peer_id to users table for per-user WireGuard peer tracking.

Each user gets a stable WireGuard peer ID (UUID) assigned on first
VPN config request. The actual public/private keys are derived from
the peer_id + the server's WG_PEER_SECRET — no extra columns needed.

Revision ID: 0009_wg_peer
Revises: 0008_telemetry_events
Create Date: 2026-08-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_wg_peer"
down_revision = "0008_telemetry_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # unique=True omitted from add_column for SQLite compatibility;
    # the uniqueness is enforced by the index below (PostgreSQL honours it).
    op.add_column(
        "users",
        sa.Column("wg_peer_id", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_users_wg_peer_id", "users", ["wg_peer_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_wg_peer_id", table_name="users")
    op.drop_column("users", "wg_peer_id")
