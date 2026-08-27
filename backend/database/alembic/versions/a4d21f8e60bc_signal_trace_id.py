"""signal trace id

Names the file holding every LLM call of the run that produced this signal.
Nullable, because traces are only written when LLM_TRACE_DIR is set and every
signal recorded before this migration has none.

Revision ID: a4d21f8e60bc
Revises: f1c73e5a92d4
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "a4d21f8e60bc"
down_revision: Union[str, Sequence[str], None] = "f1c73e5a92d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "signal",
        sa.Column("trace_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.create_index(op.f("ix_signal_trace_id"), "signal", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_signal_trace_id"), table_name="signal")
    op.drop_column("signal", "trace_id")
