"""why an analysis ran

``signal.trigger`` — what caused this analysis to happen. One of:

- ``sweep`` — the scheduled morning run over the whole watchlist
- ``commissioned`` — the agent paid for it and asked for it immediately
- ``move`` — the watchdog saw an unusual price or volume move
- ``earnings`` — the ticker reports soon
- ``manual`` — run from the API

**The agent could not tell these apart, and they are not the same object.** A
signal produced because a stock just moved 5% is the analyst reacting to a move
already in the price. A scheduled one is not reacting to anything. How much
weight a signal deserves depends on which it is, and the agent was shown only
the decision.

Nullable, and every existing row stays NULL. It cannot be backfilled: the
reason was written to the log and nowhere else, so a value invented now would
be a guess presented as a record.

Revision ID: e8b3f42a17d9
Revises: d7a2e91c5f34
Create Date: 2026-09-03 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e8b3f42a17d9"
down_revision: Union[str, None] = "d7a2e91c5f34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("signal")}
    if "trigger" not in existing:
        op.add_column("signal", sa.Column("trigger", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("signal", "trigger")
