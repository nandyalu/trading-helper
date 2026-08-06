"""alert log for the intraday watchdog

Revision ID: a252161afd4e
Revises: e757cb84ff7e
Create Date: 2026-07-17 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a252161afd4e'
down_revision: Union[str, Sequence[str], None] = 'e757cb84ff7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('alert',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticker', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('alert_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('dedupe_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('message', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_alert_ticker'), 'alert', ['ticker'], unique=False)
    op.create_index(op.f('ix_alert_dedupe_key'), 'alert', ['dedupe_key'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_alert_dedupe_key'), table_name='alert')
    op.drop_index(op.f('ix_alert_ticker'), table_name='alert')
    op.drop_table('alert')
