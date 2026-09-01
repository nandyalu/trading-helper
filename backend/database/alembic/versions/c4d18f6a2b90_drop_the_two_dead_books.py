"""drop the two dead books

The real transaction log and the hand-followed paper book, plus the paper
equity-curve snapshots. All three were removed from the app on 2026-09-01, when
it became one autonomous agent trading one simulated account.

The agent's own book lives in ``agenttrade`` and is untouched.

**This migration only matters for a database that predates 2026-09-01.** The
experiment restarted on a new volume, so the container this ships in creates
these tables never and drops them never. It exists so that a database carried
forward — a copy of one of the old volumes, opened to read the record — comes up
matching the models rather than holding three tables nothing can write to.

``downgrade`` recreates the tables empty. It cannot bring the rows back, and
nothing in the app would read them if it did.

Revision ID: c4d18f6a2b90
Revises: b7e4c1a95d38
Create Date: 2026-09-01 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4d18f6a2b90"
down_revision: Union[str, None] = "b7e4c1a95d38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# A database that never had these tables is not an error: the app has shipped
# to fresh volumes since, and dropping what is not there must not stop startup.
_TABLES = ("papersnapshot", "papertransaction", "transaction")


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in _TABLES:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    op.create_table(
        "transaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transaction_ticker", "transaction", ["ticker"])

    op.create_table(
        "papertransaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_papertransaction_ticker", "papertransaction", ["ticker"])

    op.create_table(
        "papersnapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("total_value", sa.Float(), nullable=False),
        sa.Column("total_cost", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_papersnapshot_snapshot_date", "papersnapshot", ["snapshot_date"])
