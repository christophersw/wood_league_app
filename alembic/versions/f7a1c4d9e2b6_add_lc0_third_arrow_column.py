"""add lc0 third arrow column

Revision ID: f7a1c4d9e2b6
Revises: e3f9a2c1b7d4
Create Date: 2026-05-01

Adds arrow_uci_3 to lc0_move_analysis for top-3 board arrows.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f7a1c4d9e2b6"
down_revision: Union[str, Sequence[str], None] = "e3f9a2c1b7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lc0_move_analysis", sa.Column("arrow_uci_3", sa.String(8), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("lc0_move_analysis", "arrow_uci_3")
