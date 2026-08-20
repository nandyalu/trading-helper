"""exit arm requests

A request to place the missing exits on a position, waiting for the market to
open. Webull accepts a standalone order at any hour but refuses a combo — an
OCO pair or a bracket — outside 9:30-16:00 ET, so a person noticing an
unprotected position in the evening had no way to act on it until morning.

Recording the request is what lets the app act on their behalf at the open.

Revision ID: d5a91c46e2b8
Revises: b8e5d3f19c07
Create Date: 2026-08-20 05:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5a91c46e2b8'
down_revision: Union[str, Sequence[str], None] = 'b8e5d3f19c07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'exitarmrequest',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(), nullable=False),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('message', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_exitarmrequest_ticker', 'exitarmrequest', ['ticker'])
    op.create_index('ix_exitarmrequest_status', 'exitarmrequest', ['status'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_exitarmrequest_status', table_name='exitarmrequest')
    op.drop_index('ix_exitarmrequest_ticker', table_name='exitarmrequest')
    op.drop_table('exitarmrequest')
