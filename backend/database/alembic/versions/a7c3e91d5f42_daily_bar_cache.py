"""daily OHLCV bar cache

One row per (ticker, date), holding completed sessions only. Every yfinance
history call in the app reads through it. Purely a cache: dropping the table
costs nothing but a refetch.

Revision ID: a7c3e91d5f42
Revises: f8a2c1e07b93
Create Date: 2026-08-07 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91d5f42'
down_revision: Union[str, Sequence[str], None] = 'f8a2c1e07b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'dailybar',
        sa.Column('ticker', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('open', sa.Float(), nullable=False),
        sa.Column('high', sa.Float(), nullable=False),
        sa.Column('low', sa.Float(), nullable=False),
        sa.Column('close', sa.Float(), nullable=False),
        sa.Column('volume', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('ticker', 'date'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('dailybar')
