"""signal trade plan: entry, stop, and conviction

TradingAgents computes a stop-loss, an entry price, a win probability, a
risk/reward ratio, and an expected value for every analysis, on the trader's
proposal one stage before the final decision. The backend used to read only the
final decision text and discard all of it. These columns keep it.

All nullable, because "the model didn't state it" must stay distinguishable
from a value. A missing stop read as 0.0 would look like a stop at $0.

Revision ID: f8a2c1e07b93
Revises: c31f7a9b4d20
Create Date: 2026-08-06 05:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a2c1e07b93'
down_revision: Union[str, Sequence[str], None] = 'c31f7a9b4d20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    'entry_price',
    'stop_loss',
    'win_probability',
    'risk_reward',
    'expected_value_r',
)


def upgrade() -> None:
    """Upgrade schema."""
    for name in _COLUMNS:
        op.add_column('signal', sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    for name in reversed(_COLUMNS):
        op.drop_column('signal', name)
