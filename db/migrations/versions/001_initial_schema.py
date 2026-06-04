"""Initial schema — all Phase 3 tables.

Revision ID: 001
Revises: None
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.String(8), primary_key=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("theme", sa.Text, server_default=""),
        sa.Column("reference", sa.Text, server_default=""),
        sa.Column("status", sa.String(32), server_default="scripted", index=True),
        sa.Column("style_name", sa.String(64), server_default=""),
        sa.Column("scripts", sa.Text),
        sa.Column("prompts", sa.Text),
        sa.Column("evaluation", JSONB),
        sa.Column("parsed_scripts", JSONB),
        sa.Column("operation_raw", sa.Text),
        sa.Column("operation_list", JSONB),
        sa.Column("notes", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("archived", sa.Boolean, server_default="false", index=True),
    )

    op.create_table(
        "operator_stats",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(32), unique=True, index=True, nullable=False),
        sa.Column("approved", sa.Integer, server_default="0"),
        sa.Column("rejected", sa.Integer, server_default="0"),
        sa.Column("notes", sa.Text, server_default=""),
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.String(8), sa.ForeignKey("plans.id", ondelete="SET NULL")),
        sa.Column("positive", sa.Boolean, nullable=False),
        sa.Column("comment", sa.Text, server_default=""),
        sa.Column("operators", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(8), sa.ForeignKey("plans.id", ondelete="SET NULL")),
        sa.Column("job_type", sa.String(32), index=True, nullable=False),
        sa.Column("status", sa.String(16), server_default="queued", index=True),
        sa.Column("result", JSONB),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "trending_topics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(16), index=True, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("url", sa.Text, server_default=""),
        sa.Column("hot_score", sa.Float),
        sa.Column("extra", JSONB),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )

    op.create_table(
        "publish_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.String(8), sa.ForeignKey("plans.id", ondelete="SET NULL")),
        sa.Column("platform", sa.String(16), index=True, nullable=False),
        sa.Column("status", sa.String(16), server_default="pending"),
        sa.Column("video_url", sa.Text, server_default=""),
        sa.Column("title", sa.Text, server_default=""),
        sa.Column("tags", JSONB),
        sa.Column("error", sa.Text),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "style_profiles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("core_concept", sa.Text, server_default=""),
        sa.Column("visual_style", sa.Text, server_default=""),
        sa.Column("caption_style", sa.Text, server_default=""),
        sa.Column("hook_rule", sa.Text, server_default=""),
        sa.Column("video_spec", sa.Text, server_default=""),
        sa.Column("operators", JSONB),
        sa.Column("avoid", JSONB),
        sa.Column("user_notes", sa.Text, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("style_profiles")
    op.drop_table("publish_records")
    op.drop_table("trending_topics")
    op.drop_table("jobs")
    op.drop_table("feedback")
    op.drop_table("operator_stats")
    op.drop_table("plans")
