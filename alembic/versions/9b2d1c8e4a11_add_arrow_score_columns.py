"""add arrow score columns

Revision ID: 9b2d1c8e4a11
Revises: f7a1c4d9e2b6
Create Date: 2026-05-01

Adds candidate score columns for top-3 arrows on both engines so UI can
shade arrows by relative strength and show labels.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "9b2d1c8e4a11"
down_revision: Union[str, Sequence[str], None] = "f7a1c4d9e2b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("move_analysis", sa.Column("arrow_score_1", sa.Float(), nullable=True))
    op.add_column("move_analysis", sa.Column("arrow_score_2", sa.Float(), nullable=True))
    op.add_column("move_analysis", sa.Column("arrow_score_3", sa.Float(), nullable=True))

    op.add_column("lc0_move_analysis", sa.Column("arrow_score_1", sa.Float(), nullable=True))
    op.add_column("lc0_move_analysis", sa.Column("arrow_score_2", sa.Float(), nullable=True))
    op.add_column("lc0_move_analysis", sa.Column("arrow_score_3", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("lc0_move_analysis", "arrow_score_3")
    op.drop_column("lc0_move_analysis", "arrow_score_2")
    op.drop_column("lc0_move_analysis", "arrow_score_1")

    op.drop_column("move_analysis", "arrow_score_3")
    op.drop_column("move_analysis", "arrow_score_2")
    op.drop_column("move_analysis", "arrow_score_1")
