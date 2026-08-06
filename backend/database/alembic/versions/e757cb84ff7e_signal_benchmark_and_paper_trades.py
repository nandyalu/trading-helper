"""signal benchmark columns and paper trades

Revision ID: e757cb84ff7e
Revises: b545ad3baa0e
Create Date: 2026-07-17 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e757cb84ff7e'
down_revision: Union[str, Sequence[str], None] = 'b545ad3baa0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('papertransaction',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticker', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('side', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('price', sa.Float(), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('signal_id', sa.Integer(), nullable=True),
    sa.Column('note', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.ForeignKeyConstraint(['signal_id'], ['signal.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_papertransaction_ticker'), 'papertransaction', ['ticker'], unique=False)
    # All nullable, so plain ADD COLUMN works on SQLite — no table rebuild needed.
    op.add_column('signal', sa.Column('message_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('signal', sa.Column('benchmark_price_at_signal', sa.Float(), nullable=True))
    op.add_column('signal', sa.Column('benchmark_price_at_evaluation', sa.Float(), nullable=True))
    op.add_column('signal', sa.Column('alpha_pct', sa.Float(), nullable=True))
    op.add_column('signal', sa.Column('outcome_vs_benchmark', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('signal', sa.Column('price_target_hit', sa.Boolean(), nullable=True))
    op.create_index(op.f('ix_signal_message_id'), 'signal', ['message_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_signal_message_id'), table_name='signal')
    op.drop_column('signal', 'price_target_hit')
    op.drop_column('signal', 'outcome_vs_benchmark')
    op.drop_column('signal', 'alpha_pct')
    op.drop_column('signal', 'benchmark_price_at_evaluation')
    op.drop_column('signal', 'benchmark_price_at_signal')
    op.drop_column('signal', 'message_id')
    op.drop_index(op.f('ix_papertransaction_ticker'), table_name='papertransaction')
    op.drop_table('papertransaction')
