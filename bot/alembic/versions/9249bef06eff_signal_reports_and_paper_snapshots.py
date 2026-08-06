"""signal reports and paper snapshots

Revision ID: 9249bef06eff
Revises: a252161afd4e
Create Date: 2026-07-17 14:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '9249bef06eff'
down_revision: Union[str, Sequence[str], None] = 'a252161afd4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('signalreport',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('signal_id', sa.Integer(), nullable=False),
    sa.Column('report_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('content', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.ForeignKeyConstraint(['signal_id'], ['signal.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_signalreport_signal_id'), 'signalreport', ['signal_id'], unique=False)
    op.create_table('papersnapshot',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('snapshot_date', sa.Date(), nullable=False),
    sa.Column('open_value', sa.Float(), nullable=False),
    sa.Column('open_cost', sa.Float(), nullable=False),
    sa.Column('realized_pnl', sa.Float(), nullable=False),
    sa.Column('spy_close', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_papersnapshot_snapshot_date'), 'papersnapshot', ['snapshot_date'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_papersnapshot_snapshot_date'), table_name='papersnapshot')
    op.drop_table('papersnapshot')
    op.drop_index(op.f('ix_signalreport_signal_id'), table_name='signalreport')
    op.drop_table('signalreport')
