"""agent stop orders

Marks the rows that are protective stops resting at the broker rather than
orders waiting to fill. A stop is *meant* to sit pending indefinitely, so
without this the dashboard would list it under "waiting to fill" forever, and
the exit path could not find the stop to cancel when the position closes —
leaving an order that would try to sell shares no longer held.

Revision ID: f3c8b21d47ae
Revises: d1f7c2a94b83
Create Date: 2026-08-11 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3c8b21d47ae'
down_revision: Union[str, Sequence[str], None] = 'd1f7c2a94b83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'agenttrade',
        sa.Column('is_stop', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agenttrade', 'is_stop')
