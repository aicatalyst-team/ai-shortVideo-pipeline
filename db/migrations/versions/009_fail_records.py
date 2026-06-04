"""Phase P P9 fail_records

Revision ID: 009
Revises: 008
Create Date: 2026-05-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fail_records",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.String(16),
            sa.ForeignKey("generation_sessions.id", ondelete="SET NULL"),
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(48), nullable=False),
        sa.Column("error_message", sa.Text, server_default="", nullable=False),
        sa.Column("suggestion", sa.Text, server_default="", nullable=False),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_fail_records_session", "fail_records", ["session_id"])
    op.create_index("ix_fail_records_code", "fail_records", ["error_code"])


def downgrade() -> None:
    op.drop_index("ix_fail_records_code", table_name="fail_records")
    op.drop_index("ix_fail_records_session", table_name="fail_records")
    op.drop_table("fail_records")
