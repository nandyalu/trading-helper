"""agent run failures and notes

Two columns on ``agentrun``, both for the same gap: the agent acted blind to
its own failures and had no way to say what it needed.

``failures`` — what the *broker* refused, as JSON. Distinct from ``refusals``,
which is what Python declined before an order was ever sent. The two mean
different things to the agent: a screening refusal says its arithmetic was
wrong, a broker failure says the world would not take an order it formed
correctly. Only a count was kept before, so a failure was invisible to the next
morning's prompt — the agent proposed the same thing again, was refused again,
and nothing in the record explained the loop.

``notes`` — the agent's own messages to whoever maintains it, as a JSON list.
Nothing reads them automatically and nothing acts on them.

Both are nullable and both default to NULL on every existing row. Neither can
be backfilled: the detail behind the old counts was never stored.

Revision ID: d7a2e91c5f34
Revises: c4d18f6a2b90
Create Date: 2026-09-02 02:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d7a2e91c5f34"
down_revision: Union[str, None] = "c4d18f6a2b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("agentrun")}
    if "failures" not in existing:
        op.add_column("agentrun", sa.Column("failures", sa.String(), nullable=True))
    if "notes" not in existing:
        op.add_column("agentrun", sa.Column("notes", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("agentrun", "notes")
    op.drop_column("agentrun", "failures")
