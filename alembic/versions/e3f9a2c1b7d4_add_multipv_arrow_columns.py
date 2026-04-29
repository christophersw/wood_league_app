"""add multipv arrow columns

Revision ID: e3f9a2c1b7d4
Revises: d4e8f2b1c5a9
Create Date: 2026-04-28

Adds arrow_uci_2 and arrow_uci_3 to move_analysis (Stockfish top-3 candidates)
and arrow_uci_2 to lc0_move_analysis (Lc0 top-2 candidates), enabling
good/better/best multi-arrow display on the game board.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f9a2c1b7d4"
down_revision: Union[str, Sequence[str], None] = "d4e8f2b1c5a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("move_analysis", sa.Column("arrow_uci_2", sa.String(8), nullable=True))
    op.add_column("move_analysis", sa.Column("arrow_uci_3", sa.String(8), nullable=True))
    op.add_column("lc0_move_analysis", sa.Column("arrow_uci_2", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("move_analysis", "arrow_uci_2")
    op.drop_column("move_analysis", "arrow_uci_3")
    op.drop_column("lc0_move_analysis", "arrow_uci_2")
