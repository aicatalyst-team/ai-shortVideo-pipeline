"""D41-A storyboard anchors

Revision ID: 012
Revises: 011
Create Date: 2026-05-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "storyboards",
        sa.Column("anchors", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("storyboards", "anchors")
