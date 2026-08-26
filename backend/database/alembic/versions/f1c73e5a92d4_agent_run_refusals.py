"""agent run refusals

What the agent tried and was refused. The run already stored a count, which
throws away the interesting half: "3 rejected" says nothing, while "it tried to
buy $1,944 against $1,000 of cash" explains a week of odd behaviour.

Placed orders need no copy — they are in agenttrade. A refusal leaves no other
trace at all.

Revision ID: f1c73e5a92d4
Revises: e3b91d7c4a25
Create Date: 2026-08-26 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1c73e5a92d4'
down_revision: Union[str, Sequence[str], None] = 'e3b91d7c4a25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agentrun', sa.Column('refusals', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agentrun', 'refusals')
