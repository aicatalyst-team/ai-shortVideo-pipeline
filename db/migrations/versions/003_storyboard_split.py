"""v2 schema: storyboard split + canvas + skill + memory + llm_calls

Revision ID: 003
Revises: 002
Create Date: 2026-05-20

Keep plans.evaluation JSONB during the compatibility window. Backfill (M3 D24)
will extract clips from plans.evaluation into the new tables.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "storyboards",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("plan_id", sa.String(8), sa.ForeignKey("plans.id", ondelete="SET NULL")),
        sa.Column("title", sa.Text, server_default="", nullable=False),
        sa.Column("theme", sa.Text, server_default="", nullable=False),
        sa.Column("style_name", sa.String(64), server_default="", nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_storyboards_status", "storyboards", ["status"])
    op.create_index("ix_storyboards_plan_id", "storyboards", ["plan_id"])

    op.create_table(
        "clips",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("storyboard_id", sa.String(16), sa.ForeignKey("storyboards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("node_id", sa.String(16)),
        sa.Column("prompt", sa.Text, server_default="", nullable=False),
        sa.Column("kling_prompt", sa.Text, server_default="", nullable=False),
        sa.Column("narration_segment", sa.Text, server_default="", nullable=False),
        sa.Column("duration_sec", sa.Integer, server_default="5", nullable=False),
        sa.Column("video_url", sa.Text, server_default="", nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("model", sa.String(64), server_default="", nullable=False),
        sa.Column("cost_cny", sa.Float, server_default="0.0", nullable=False),
        sa.Column("duration_ms", sa.Integer, server_default="0", nullable=False),
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_clips_storyboard_id_seq", "clips", ["storyboard_id", "seq"])
    op.create_index("ix_clips_status", "clips", ["status"])
    op.create_index("ix_clips_node_id", "clips", ["node_id"])

    op.create_table(
        "frame_assets",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("clip_id", sa.String(16), sa.ForeignKey("clips.id", ondelete="CASCADE")),
        sa.Column("node_id", sa.String(16)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("url", sa.Text, server_default="", nullable=False),
        sa.Column("sha256", sa.String(64), server_default="", nullable=False),
        sa.Column("width", sa.Integer, server_default="0", nullable=False),
        sa.Column("height", sa.Integer, server_default="0", nullable=False),
        sa.Column("source", sa.String(16), server_default="generated", nullable=False),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_frame_assets_clip_id_kind", "frame_assets", ["clip_id", "kind"])
    op.create_index("ix_frame_assets_sha256", "frame_assets", ["sha256"])
    op.create_index("ix_frame_assets_kind", "frame_assets", ["kind"])

    op.create_table(
        "canvas_projects",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("title", sa.Text, server_default="", nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("storyboard_id", sa.String(16), sa.ForeignKey("storyboards.id", ondelete="SET NULL")),
        sa.Column("viewport", JSONB),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_canvas_projects_owner_id", "canvas_projects", ["owner_id"])
    op.create_index("ix_canvas_projects_status", "canvas_projects", ["status"])

    op.create_table(
        "canvas_nodes",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("project_id", sa.String(16), sa.ForeignKey("canvas_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("title", sa.Text, server_default="", nullable=False),
        sa.Column("position", JSONB),
        sa.Column("size", JSONB),
        sa.Column("data", JSONB),
        sa.Column("status", sa.String(32), server_default="idle", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_canvas_nodes_project_id_type", "canvas_nodes", ["project_id", "type"])
    op.create_index("ix_canvas_nodes_status", "canvas_nodes", ["status"])

    op.create_table(
        "canvas_edges",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("project_id", sa.String(16), sa.ForeignKey("canvas_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_node_id", sa.String(16), nullable=False),
        sa.Column("target_node_id", sa.String(16), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("data", JSONB),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_canvas_edges_project_source", "canvas_edges", ["project_id", "source_node_id"])
    op.create_index("ix_canvas_edges_project_target", "canvas_edges", ["project_id", "target_node_id"])
    op.create_index("ix_canvas_edges_status", "canvas_edges", ["status"])

    op.create_table(
        "creator_memories",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(16), server_default="global", nullable=False),
        sa.Column("style_name", sa.String(64), server_default="", nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, server_default="", nullable=False),
        sa.Column("prompt_rule", sa.Text, server_default="", nullable=False),
        sa.Column("evidence", sa.Text, server_default="", nullable=False),
        sa.Column("confidence", sa.Float, server_default="0.5", nullable=False),
        sa.Column("status", sa.String(16), server_default="proposed", nullable=False),
        sa.Column("source_ref", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_creator_memories_owner_status_scope", "creator_memories", ["owner_id", "status", "scope"])

    op.create_table(
        "skills",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, server_default="", nullable=False),
        sa.Column("category", sa.String(32), server_default="prompt", nullable=False),
        sa.Column("visibility", sa.String(16), server_default="private", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_skills_owner_visibility_status", "skills", ["owner_id", "visibility", "status"])

    op.create_table(
        "skill_versions",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("skill_id", sa.String(16), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        sa.Column("input_schema", JSONB),
        sa.Column("output_schema", JSONB),
        sa.Column("definition", JSONB),
        sa.Column("prompt_template", sa.Text, server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_skill_versions_skill_id_version", "skill_versions", ["skill_id", "version"])

    op.create_table(
        "skill_runs",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("skill_version_id", sa.String(16), sa.ForeignKey("skill_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(16)),
        sa.Column("node_id", sa.String(16)),
        sa.Column("input", JSONB),
        sa.Column("output", JSONB),
        sa.Column("status", sa.String(16), server_default="success", nullable=False),
        sa.Column("latency_ms", sa.Integer, server_default="0", nullable=False),
        sa.Column("cost_cny", sa.Float, server_default="0.0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_skill_runs_skill_version_id", "skill_runs", ["skill_version_id"])
    op.create_index("ix_skill_runs_project_node", "skill_runs", ["project_id", "node_id"])

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(16)),
        sa.Column("node_id", sa.String(16)),
        sa.Column("skill_run_id", sa.String(16)),
        sa.Column("biz_type", sa.String(32), server_default="", nullable=False),
        sa.Column("provider", sa.String(32), server_default="", nullable=False),
        sa.Column("model", sa.String(64), server_default="", nullable=False),
        sa.Column("input_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer, server_default="0", nullable=False),
        sa.Column("cost_cny", sa.Float, server_default="0.0", nullable=False),
        sa.Column("latency_ms", sa.Integer, server_default="0", nullable=False),
        sa.Column("status", sa.String(16), server_default="success", nullable=False),
        sa.Column("trace_id", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_llm_calls_tenant_created", "llm_calls", ["tenant_id", "created_at"])
    op.create_index("ix_llm_calls_trace_id", "llm_calls", ["trace_id"])
    op.create_index("ix_llm_calls_provider_status", "llm_calls", ["provider", "status"])


def downgrade() -> None:
    op.drop_table("llm_calls")
    op.drop_table("skill_runs")
    op.drop_table("skill_versions")
    op.drop_table("skills")
    op.drop_table("creator_memories")
    op.drop_table("canvas_edges")
    op.drop_table("canvas_nodes")
    op.drop_table("canvas_projects")
    op.drop_table("frame_assets")
    op.drop_table("clips")
    op.drop_table("storyboards")
