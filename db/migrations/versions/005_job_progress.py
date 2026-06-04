"""Job progress fields for D30 single-segment regenerate

Revision ID: 005
Revises: 004
Create Date: 2026-05-21

adds jobs.progress and jobs.progress_stage for polling/SSE consumers.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("progress", sa.Integer, server_default="0", nullable=False))
    op.add_column("jobs", sa.Column("progress_stage", sa.String(64), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("jobs", "progress_stage")
    op.drop_column("jobs", "progress")
