"""when the agent asked to be woken

``agentrun.next_wakeup`` — the time the agent chose for its own next pass.

Stored rather than only acted on, for two reasons. The next prompt reports
what the last several wakeups produced, so the agent can see whether its own
cadence is earning anything. And a record of trades with no record of when it
chose to look cannot answer why it missed a move.

Nullable. NULL means the pass asked for nothing, which is different from
asking for the default — the scheduler's fallback is a fact about the
scheduler, not a decision the agent made.

Revision ID: f1a5c93e28b7
Revises: e8b3f42a17d9
Create Date: 2026-09-03 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1a5c93e28b7"
down_revision: Union[str, None] = "e8b3f42a17d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("agentrun")}
    if "next_wakeup" not in existing:
        op.add_column("agentrun", sa.Column("next_wakeup", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("agentrun", "next_wakeup")
