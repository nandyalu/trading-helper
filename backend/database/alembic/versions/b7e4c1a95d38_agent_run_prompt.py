"""agent run prompt, response and orders

The words the agent was shown and the answer it gave. Nullable, because no run
before this migration kept them and none can be reconstructed: the prompt is
built from a book, a watchlist and a signal list that have all moved since.

Revision ID: b7e4c1a95d38
Revises: a4d21f8e60bc
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "b7e4c1a95d38"
down_revision: Union[str, Sequence[str], None] = "a4d21f8e60bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in ("prompt", "response", "orders"):
        op.add_column(
            "agentrun",
            sa.Column(column, sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        )


def downgrade() -> None:
    for column in ("orders", "response", "prompt"):
        op.drop_column("agentrun", column)
