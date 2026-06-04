"""Phase 6 video registry + metrics feedback

Revision ID: 002
Revises: 001
Create Date: 2026-04-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "video_records",
        sa.Column("id", sa.String(12), primary_key=True),
        sa.Column("plan_id", sa.String(8), sa.ForeignKey("plans.id", ondelete="SET NULL")),
        sa.Column("chat_id", sa.String(64), server_default="", nullable=False),
        sa.Column("source", sa.String(32), server_default="manual", nullable=False),
        sa.Column("style_name", sa.String(64), server_default="", nullable=False),
        sa.Column("theme", sa.Text, server_default="", nullable=False),
        sa.Column("title", sa.Text, server_default="", nullable=False),
        sa.Column("narration", sa.Text, server_default="", nullable=False),
        sa.Column("tags", JSONB),
        sa.Column("video_path", sa.Text, server_default="", nullable=False),
        sa.Column("cover_path", sa.Text, server_default="", nullable=False),
        sa.Column("quality_score", sa.Float),
        sa.Column("is_viral", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_video_records_chat_id", "video_records", ["chat_id"])
    op.create_index("ix_video_records_source", "video_records", ["source"])
    op.create_index("ix_video_records_style_name", "video_records", ["style_name"])
    op.create_index("ix_video_records_is_viral", "video_records", ["is_viral"])
    op.create_index("ix_video_records_created_at", "video_records", ["created_at"])

    op.create_table(
        "video_metrics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("video_id", sa.String(12), sa.ForeignKey("video_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("views", sa.Integer, server_default="0", nullable=False),
        sa.Column("completion_rate", sa.Float),
        sa.Column("engagement_rate", sa.Float),
        sa.Column("likes", sa.Integer, server_default="0", nullable=False),
        sa.Column("comments", sa.Integer, server_default="0", nullable=False),
        sa.Column("shares", sa.Integer, server_default="0", nullable=False),
        sa.Column("note", sa.Text, server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_video_metrics_video_id", "video_metrics", ["video_id"])
    op.create_index("ix_video_metrics_created_at", "video_metrics", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_video_metrics_created_at", table_name="video_metrics")
    op.drop_index("ix_video_metrics_video_id", table_name="video_metrics")
    op.drop_table("video_metrics")

    op.drop_index("ix_video_records_created_at", table_name="video_records")
    op.drop_index("ix_video_records_is_viral", table_name="video_records")
    op.drop_index("ix_video_records_style_name", table_name="video_records")
    op.drop_index("ix_video_records_source", table_name="video_records")
    op.drop_index("ix_video_records_chat_id", table_name="video_records")
    op.drop_table("video_records")
