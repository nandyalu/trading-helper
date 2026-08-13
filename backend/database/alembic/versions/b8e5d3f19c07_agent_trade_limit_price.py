"""agent trade limit price and exit kind

Where a resting exit is armed, and which leg of the bracket it is. Neither was
stored as data. ``price`` cannot carry the level — that column is the fill
price and stays NULL until the order actually triggers — and ``is_stop`` marks
both legs alike, so a stop and a take-profit were told apart only by the
wording of ``reason`` ("stop-loss resting at $95.30"). The auto trader page
could list the exits but could not put the stop and the target on the holding's
own row without parsing that sentence back into a number and a kind.

The upgrade recovers both from ``reason`` for rows already written, so the
exits armed by hand on 2026-08-13 are not left blank.

Revision ID: b8e5d3f19c07
Revises: f3c8b21d47ae
Create Date: 2026-08-13 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8e5d3f19c07'
down_revision: Union[str, Sequence[str], None] = 'f3c8b21d47ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agenttrade', sa.Column('limit_price', sa.Float(), nullable=True))
    op.add_column('agenttrade', sa.Column('exit_kind', sa.String(), nullable=True))
    # Recover the level from the text it was only ever stored in. The comma is
    # a thousands separator, stripped so the result parses as a number.
    op.execute(
        """
        UPDATE agenttrade
           SET limit_price = CAST(
                   REPLACE(SUBSTR(reason, INSTR(reason, '$') + 1), ',', '') AS REAL
               )
         WHERE is_stop = 1
           AND reason LIKE '%$%'
        """
    )
    op.execute(
        """
        UPDATE agenttrade
           SET exit_kind = CASE WHEN reason LIKE 'stop-loss%' THEN 'stop' ELSE 'target' END
         WHERE is_stop = 1
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agenttrade', 'exit_kind')
    op.drop_column('agenttrade', 'limit_price')
