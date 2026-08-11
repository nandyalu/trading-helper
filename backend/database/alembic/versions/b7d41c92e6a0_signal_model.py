"""signal llm model

Records which LLM produced each signal. Trying a different model only tells
you something if the scorecard can separate its signals from the previous
model's, which needs the model stored per row. Nullable: rows written before
this column stay NULL, meaning "unknown" — in practice gemma4-e2b-96k, the
only model this deployment had run.

Revision ID: b7d41c92e6a0
Revises: d5b81f0c2e37
Create Date: 2026-08-10 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7d41c92e6a0'
down_revision: Union[str, Sequence[str], None] = 'd5b81f0c2e37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('signal', sa.Column('model', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_signal_model'), 'signal', ['model'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_signal_model'), table_name='signal')
    op.drop_column('signal', 'model')
