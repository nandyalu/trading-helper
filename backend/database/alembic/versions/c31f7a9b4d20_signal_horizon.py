"""signal trade horizon

Records which trade horizon produced each signal ("swing" or "position").
The horizon decides how long to wait before grading and how wide the Hold
band is, so a scorecard that mixed them would compare two different
questions. Nullable: rows written before this column stay NULL, meaning
"unknown", and backend/services/signals.py horizon_params() falls back to the
default for them.

Revision ID: c31f7a9b4d20
Revises: e494b1e16258
Create Date: 2026-08-06 02:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c31f7a9b4d20'
down_revision: Union[str, Sequence[str], None] = 'e494b1e16258'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('signal', sa.Column('horizon', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_signal_horizon'), 'signal', ['horizon'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_signal_horizon'), table_name='signal')
    op.drop_column('signal', 'horizon')
