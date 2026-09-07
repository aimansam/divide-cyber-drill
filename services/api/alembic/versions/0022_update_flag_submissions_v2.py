"""Update flag_submissions to v2 schema.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-04

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0022_update_flag_submissions_v2'
down_revision = '0021_audit_run_timeout'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old flag_submissions table and recreate with new schema
    op.drop_table('flag_submissions')
    
    op.create_table(
        'flag_submissions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('submission_id', sa.Integer(), 
                  sa.ForeignKey('submissions.id', ondelete='CASCADE'), 
                  nullable=False),
        sa.Column('lab_flag_id', sa.Integer(), 
                  sa.ForeignKey('lab_flags.id', ondelete='CASCADE'), 
                  nullable=False),
        sa.Column('flag_value', sa.String(255), nullable=False),
        sa.Column('is_correct', sa.Boolean(), nullable=False, default=False),
        sa.Column('points_earned', sa.Integer(), nullable=False, default=0),
        sa.Column('time_decay_factor', sa.Numeric(3, 2), nullable=False, default=1.00),
        sa.Column('attempt_number', sa.Integer(), nullable=False, default=1),
        sa.Column('hints_used', sa.Integer(), nullable=False, default=0),
        sa.UniqueConstraint('submission_id', 'lab_flag_id', name='uq_flag_submissions'),
    )
    
    op.create_index('idx_flag_submissions_flag', 'flag_submissions', ['lab_flag_id'])
    op.create_index('idx_flag_submissions_correct', 'flag_submissions', ['is_correct'])


def downgrade() -> None:
    # Restore old schema
    op.drop_table('flag_submissions')
    
    op.create_table(
        'flag_submissions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('run_id', sa.Integer(), 
                  sa.ForeignKey('runs.id', ondelete='CASCADE'), 
                  nullable=False),
        sa.Column('flag_id', sa.String(64), nullable=False),
        sa.Column('team', sa.String(16), nullable=False),
        sa.Column('submitted_by', sa.String(64), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('elapsed_seconds', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
