"""Phase P P8 generation_sessions + clip_review_events

Revision ID: 008
Revises: 007
Create Date: 2026-05-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_sessions",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("skill_id", sa.String(64)),
        sa.Column("theme", sa.Text, server_default="", nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("locked_character_id", sa.String(64)),
        sa.Column("locked_scene_id", sa.String(64)),
        sa.Column("locked_storyboard_id", sa.String(16)),
        sa.Column("plan_id", sa.String(8)),
        sa.Column("final_score", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sessions_chat_status", "generation_sessions", ["chat_id", "status"])
    op.create_index("ix_sessions_plan_id", "generation_sessions", ["plan_id"])

    op.create_table(
        "clip_review_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.String(16),
            sa.ForeignKey("generation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("clip_index", sa.Integer),
        sa.Column("comment", sa.Text, server_default="", nullable=False),
        sa.Column("hints", JSONB),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_events_session_created", "clip_review_events", ["session_id", "created_at"])
    op.create_index("ix_events_stage_decision", "clip_review_events", ["stage", "decision"])


def downgrade() -> None:
    op.drop_index("ix_events_stage_decision", table_name="clip_review_events")
    op.drop_index("ix_events_session_created", table_name="clip_review_events")
    op.drop_table("clip_review_events")
    op.drop_index("ix_sessions_plan_id", table_name="generation_sessions")
    op.drop_index("ix_sessions_chat_status", table_name="generation_sessions")
    op.drop_table("generation_sessions")
