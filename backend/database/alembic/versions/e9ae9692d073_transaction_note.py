"""transaction note (broker-sync provenance)

Revision ID: e9ae9692d073
Revises: 9249bef06eff
Create Date: 2026-07-19 03:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e9ae9692d073'
down_revision: Union[str, Sequence[str], None] = '9249bef06eff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('transaction', sa.Column('note', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('transaction', 'note')
