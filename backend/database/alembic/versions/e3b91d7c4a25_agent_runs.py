"""agent runs

One decision pass, and what the agent said about it. The reasoning went to
Discord and evaporated, leaving trades but no account of the days between
them — and a book you can only read on the days money moved is a ledger, not a
history.

Revision ID: e3b91d7c4a25
Revises: c7f2a84be910
Create Date: 2026-08-26 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3b91d7c4a25'
down_revision: Union[str, Sequence[str], None] = 'c7f2a84be910'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'agentrun',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ran_at', sa.DateTime(), nullable=False),
        sa.Column('reasoning', sa.String(), nullable=False, server_default=''),
        sa.Column('placed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('rejected', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('adjusted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped', sa.String(), nullable=True),
        sa.Column('equity', sa.Float(), nullable=True),
        sa.Column('cash', sa.Float(), nullable=True),
        sa.Column('research_spent', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agentrun_ran_at', 'agentrun', ['ran_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_agentrun_ran_at', table_name='agentrun')
    op.drop_table('agentrun')
