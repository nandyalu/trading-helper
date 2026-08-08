"""ticker status: skip symbols that stopped trading

Delisted symbols do not fail cleanly — yfinance keeps answering for the shell
with a handful of $0.000001 bars, which looks like a ticker that is merely
behind. Recording the state lets every fetch path skip it.

Revision ID: d5b81f0c2e37
Revises: a7c3e91d5f42
Create Date: 2026-08-07 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd5b81f0c2e37'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91d5f42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tickerstatus',
        sa.Column('ticker', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('inactive', sa.Boolean(), nullable=False),
        sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('last_bar_date', sa.Date(), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=True),
        sa.Column('manual', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('ticker'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('tickerstatus')
