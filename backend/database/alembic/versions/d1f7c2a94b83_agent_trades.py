"""agent trades

The autonomous agent's own book of record. It cannot be derived from the
broker: the simulated account is funded with $1,000,000 while the agent runs on
a budget of a few hundred, so the account's buying power says nothing about
what the agent may spend. Cash comes from these rows instead.

``price`` is nullable because a market order has no price at submission, and
``status`` starts pending because an order placed outside session hours does
not fill until the open. Only filled rows with a price count toward cash.

Revision ID: d1f7c2a94b83
Revises: c9e3a7b18f24
Create Date: 2026-08-11 04:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd1f7c2a94b83'
down_revision: Union[str, Sequence[str], None] = 'c9e3a7b18f24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'agenttrade',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticker', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('side', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('placed_at', sa.DateTime(), nullable=False),
        sa.Column('filled_at', sa.DateTime(), nullable=True),
        sa.Column('client_order_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('broker_order_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('signal_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['signal_id'], ['signal.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agenttrade_ticker'), 'agenttrade', ['ticker'], unique=False)
    op.create_index(op.f('ix_agenttrade_status'), 'agenttrade', ['status'], unique=False)
    op.create_index(op.f('ix_agenttrade_signal_id'), 'agenttrade', ['signal_id'], unique=False)
    # Unique: the client order id is how a broker response is matched back to
    # its row, so a duplicate would settle the wrong trade.
    op.create_index(
        op.f('ix_agenttrade_client_order_id'), 'agenttrade', ['client_order_id'], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_agenttrade_client_order_id'), table_name='agenttrade')
    op.drop_index(op.f('ix_agenttrade_signal_id'), table_name='agenttrade')
    op.drop_index(op.f('ix_agenttrade_status'), table_name='agenttrade')
    op.drop_index(op.f('ix_agenttrade_ticker'), table_name='agenttrade')
    op.drop_table('agenttrade')
