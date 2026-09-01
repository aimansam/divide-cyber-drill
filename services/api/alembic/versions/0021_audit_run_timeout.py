"""Add run.timeout to audit_action enum

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-01

"""
from alembic import op
import sqlalchemy as sa

revision = '0021_audit_run_timeout'
down_revision = '0020_audit_run_extended'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'run.timeout' to the audit_action enum
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'run.timeout'")


def downgrade() -> None:
    # Cannot remove values from an enum in PostgreSQL
    pass
