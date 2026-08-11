"""signal run cost

Records what each analysis cost: wall-clock seconds and the tokens every LLM
call in the run spent, split by direction. A self-hosted model is paid for in
GPU time and a cloud one in tokens at different prices per direction, so a
decision between them needs all of it per run.

Nullable, and no index: these columns are read per signal and averaged, never
filtered on. NULL means the run wasn't measured — rows written before this
column, or a signal recorded outside the analysis path — never that the run
was free.

Revision ID: c9e3a7b18f24
Revises: b7d41c92e6a0
Create Date: 2026-08-11 04:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e3a7b18f24'
down_revision: Union[str, Sequence[str], None] = 'b7d41c92e6a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('signal', sa.Column('duration_seconds', sa.Float(), nullable=True))
    op.add_column('signal', sa.Column('prompt_tokens', sa.Integer(), nullable=True))
    op.add_column('signal', sa.Column('completion_tokens', sa.Integer(), nullable=True))
    op.add_column('signal', sa.Column('llm_calls', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('signal', 'llm_calls')
    op.drop_column('signal', 'completion_tokens')
    op.drop_column('signal', 'prompt_tokens')
    op.drop_column('signal', 'duration_seconds')
