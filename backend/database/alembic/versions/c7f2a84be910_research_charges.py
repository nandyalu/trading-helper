"""research charges

What the agent paid to have a ticker analysed. Research is free to it today,
so there is no pressure to choose what to look at; charging makes "what is
worth researching" a decision that can be graded.

Stored rather than derived from a price times a count. The price is a setting
and settings change; a charge is something that happened, and re-pricing
history every time the setting moves would rewrite a book already reported.

Revision ID: c7f2a84be910
Revises: d5a91c46e2b8
Create Date: 2026-08-25 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7f2a84be910'
down_revision: Union[str, Sequence[str], None] = 'd5a91c46e2b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'researchcharge',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(), nullable=False),
        sa.Column('charged_at', sa.DateTime(), nullable=False),
        sa.Column('amount_usd', sa.Float(), nullable=False),
        sa.Column('signal_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['signal_id'], ['signal.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_researchcharge_ticker', 'researchcharge', ['ticker'])
    op.create_index('ix_researchcharge_charged_at', 'researchcharge', ['charged_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_researchcharge_charged_at', table_name='researchcharge')
    op.drop_index('ix_researchcharge_ticker', table_name='researchcharge')
    op.drop_table('researchcharge')
