"""add runpod tracking columns to analysis_jobs

Revision ID: b3c9f1a04e87
Revises: 45f01e2157f4
Create Date: 2026-04-19

Adds two nullable columns to the analysis_jobs table for RunPod serverless
job tracking:
  - runpod_job_id: the job ID returned by the RunPod API on submission
  - submitted_at:  UTC timestamp of when the job was submitted to RunPod
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c9f1a04e87"
down_revision: Union[str, Sequence[str], None] = "45f01e2157f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis_jobs",
        sa.Column("runpod_job_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_jobs", "submitted_at")
    op.drop_column("analysis_jobs", "runpod_job_id")
