"""
Phase 3 — SQLAlchemy ORM models for myAiVideos.

Replaces the JSON-file based MemoryManager with a proper relational schema.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Plan(Base):
    """A video production plan — replaces active_plans / archive_plans in memory.py."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(8), primary_key=True, default=lambda: uuid.uuid4().hex[:6].upper())
    mode: Mapped[str] = mapped_column(String(32))  # creative | reference | trending | baogai
    theme: Mapped[str] = mapped_column(Text, default="")
    reference: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="scripted", index=True)
    style_name: Mapped[str] = mapped_column(String(64), default="")

    scripts: Mapped[Optional[str]] = mapped_column(Text)
    prompts: Mapped[Optional[str]] = mapped_column(Text)
    evaluation: Mapped[Optional[dict]] = mapped_column(JSONB)
    parsed_scripts: Mapped[Optional[list]] = mapped_column(JSONB)
    operation_raw: Mapped[Optional[str]] = mapped_column(Text)
    operation_list: Mapped[Optional[list]] = mapped_column(JSONB)
    notes: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # relationships
    jobs: Mapped[list["Job"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    feedback: Mapped[list["Feedback"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    videos: Mapped[list["VideoRecord"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class OperatorStats(Base):
    """Per-character performance tracking — replaces operator_stats in memory.py."""

    __tablename__ = "operator_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    approved: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")


class Feedback(Base):
    """User feedback records — replaces feedback_history in memory.py."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[Optional[str]] = mapped_column(String(8), ForeignKey("plans.id", ondelete="SET NULL"))
    positive: Mapped[bool] = mapped_column(Boolean)
    comment: Mapped[str] = mapped_column(Text, default="")
    operators: Mapped[Optional[list]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    plan: Mapped[Optional["Plan"]] = relationship(back_populates="feedback")


class Job(Base):
    """Async task tracking (video generation, publishing, etc.)."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_id: Mapped[Optional[str]] = mapped_column(String(8), ForeignKey("plans.id", ondelete="SET NULL"))
    job_type: Mapped[str] = mapped_column(String(32), index=True)  # generate | publish | fetch_trending
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued | running | done | failed
    result: Mapped[Optional[dict]] = mapped_column(JSONB)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    progress_stage: Mapped[str] = mapped_column(String(64), default="")
    # (migration 006): 任务作用实体 ID（clip_id / plan_id 等）
    # 用 (target_id, status) 复合索引支持"查活跃任务"防并发预检
    target_id: Mapped[Optional[str]] = mapped_column(String(16), index=True)

    plan: Mapped[Optional["Plan"]] = relationship(back_populates="jobs")


class TrendingTopic(Base):
    """Cached hot topics from various platforms."""

    __tablename__ = "trending_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)  # douyin | weibo | bilibili
    rank: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, default="")
    hot_score: Mapped[Optional[float]] = mapped_column(Float)
    extra: Mapped[Optional[dict]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PublishRecord(Base):
    """Record of automated publishing to platforms."""

    __tablename__ = "publish_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[Optional[str]] = mapped_column(String(8), ForeignKey("plans.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(String(16), index=True)  # douyin | bilibili | xiaohongshu
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | published | failed
    video_url: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[Optional[list]] = mapped_column(JSONB)
    error: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VideoRecord(Base):
    """Generated video registry for feedback loop / batching / viral expansion."""

    __tablename__ = "video_records"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=lambda: uuid.uuid4().hex[:10].upper())
    plan_id: Mapped[Optional[str]] = mapped_column(String(8), ForeignKey("plans.id", ondelete="SET NULL"))
    chat_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual", index=True)  # manual | batch | daily_batch | variant
    style_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    theme: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    narration: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[Optional[list]] = mapped_column(JSONB)
    video_path: Mapped[str] = mapped_column(Text, default="")
    cover_path: Mapped[str] = mapped_column(Text, default="")
    quality_score: Mapped[Optional[float]] = mapped_column(Float)
    is_viral: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    plan: Mapped[Optional["Plan"]] = relationship(back_populates="videos")
    metrics: Mapped[list["VideoMetric"]] = relationship(back_populates="video", cascade="all, delete-orphan")


class VideoMetric(Base):
    """Manual post-publish metrics entered from platform dashboards."""

    __tablename__ = "video_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(12), ForeignKey("video_records.id", ondelete="CASCADE"), index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    completion_rate: Mapped[Optional[float]] = mapped_column(Float)  # 0-1
    engagement_rate: Mapped[Optional[float]] = mapped_column(Float)  # 0-1
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    video: Mapped["VideoRecord"] = relationship(back_populates="metrics")


class StyleProfile(Base):
    """Persistent style/brand profile — replaces style_profile in memory.py."""

    __tablename__ = "style_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # e.g. "default"
    core_concept: Mapped[str] = mapped_column(Text, default="")
    visual_style: Mapped[str] = mapped_column(Text, default="")
    caption_style: Mapped[str] = mapped_column(Text, default="")
    hook_rule: Mapped[str] = mapped_column(Text, default="")
    video_spec: Mapped[str] = mapped_column(Text, default="")
    operators: Mapped[Optional[list]] = mapped_column(JSONB)
    avoid: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    user_notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ─── v2 schema: storyboard / canvas / skill / memory / llm_calls ───
# Migration: 003_storyboard_split.py
# Keep plans.evaluation JSONB during the compatibility window. New tables store
# clips, frame assets, canvas state, skills, memory, and LLM usage independently.


def _short_id() -> str:
    return uuid.uuid4().hex[:16].upper()


class Storyboard(Base):
    """Storyboard: one video maps to one storyboard."""

    __tablename__ = "storyboards"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    plan_id: Mapped[Optional[str]] = mapped_column(String(8), ForeignKey("plans.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, default="")
    theme: Mapped[str] = mapped_column(Text, default="")
    style_name: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    storyboard_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    anchors: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    clips: Mapped[list["Clip"]] = relationship(back_populates="storyboard", cascade="all, delete-orphan")


class Clip(Base):
    """Addressable video clip for R6 single-segment regeneration."""

    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    storyboard_id: Mapped[str] = mapped_column(String(16), ForeignKey("storyboards.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    node_id: Mapped[Optional[str]] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(Text, default="")
    kling_prompt: Mapped[str] = mapped_column(Text, default="")
    narration_segment: Mapped[str] = mapped_column(Text, default="")
    duration_sec: Mapped[int] = mapped_column(Integer, default=5)
    video_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    cost_cny: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Phase P P10（migration 010）：画布节点完整数据组（Phase F 渲染依赖）
    first_frame_url: Mapped[str] = mapped_column(Text, default="")
    tail_frame_url: Mapped[str] = mapped_column(Text, default="")
    cost_breakdown: Mapped[Optional[dict]] = mapped_column(JSONB)
    regen_count: Mapped[int] = mapped_column(Integer, default=0)
    dirty_reason: Mapped[str] = mapped_column(Text, default="")
    blocking_for: Mapped[Optional[list]] = mapped_column(JSONB)
    depends_on: Mapped[Optional[list]] = mapped_column(JSONB)
    # （migration 004）：完整存储 R2.1 SceneShot Pydantic dump。
    # clips 表字段虽多但没覆盖 voice_type / wardrobe_choice / position 嵌套 / key_props 等关键 schema。
    # r_metadata 把 SceneShot.model_dump() 整体落库 → 下游 R3-R7 重生成时能完整复原上下文。
    r_metadata: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    storyboard: Mapped["Storyboard"] = relationship(back_populates="clips")
    frame_assets: Mapped[list["FrameAsset"]] = relationship(back_populates="clip", cascade="all, delete-orphan")


class FrameAsset(Base):
    """First frame, tail frame, cover, reference image, or uploaded asset."""

    __tablename__ = "frame_assets"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    clip_id: Mapped[Optional[str]] = mapped_column(String(16), ForeignKey("clips.id", ondelete="CASCADE"))
    node_id: Mapped[Optional[str]] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16), default="generated")
    asset_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    clip: Mapped[Optional["Clip"]] = relationship(back_populates="frame_assets")


class CanvasProject(Base):
    """User- or tenant-owned creative canvas project."""

    __tablename__ = "canvas_projects"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    storyboard_id: Mapped[Optional[str]] = mapped_column(String(16), ForeignKey("storyboards.id", ondelete="SET NULL"))
    viewport: Mapped[Optional[dict]] = mapped_column(JSONB)
    project_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    nodes: Mapped[list["CanvasNode"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    edges: Mapped[list["CanvasEdge"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class CanvasNode(Base):
    """Canvas node: idea/script/storyboard/frame/clip/skill/memory/render."""

    __tablename__ = "canvas_nodes"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    project_id: Mapped[str] = mapped_column(String(16), ForeignKey("canvas_projects.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[Optional[dict]] = mapped_column(JSONB)
    size: Mapped[Optional[dict]] = mapped_column(JSONB)
    data: Mapped[Optional[dict]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="idle", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped["CanvasProject"] = relationship(back_populates="nodes")


class CanvasEdge(Base):
    """Semantic canvas edge such as clip_tail_to_frame."""

    __tablename__ = "canvas_edges"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    project_id: Mapped[str] = mapped_column(String(16), ForeignKey("canvas_projects.id", ondelete="CASCADE"), nullable=False)
    source_node_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    target_node_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[Optional[dict]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped["CanvasProject"] = relationship(back_populates="edges")


class CreatorMemory(Base):
    """Long-term creator memory: preferences, avoids, rules, insights, habits."""

    __tablename__ = "creator_memories"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(16), default="global", index=True)
    style_name: Mapped[str] = mapped_column(String(64), default="")
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    prompt_rule: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    source_ref: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Skill(Base):
    """Reusable creation skill."""

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="prompt")
    visibility: Mapped[str] = mapped_column(String(16), default="private", index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    versions: Mapped[list["SkillVersion"]] = relationship(back_populates="skill", cascade="all, delete-orphan")


class CreativeSkill(Base):
    """Product-facing video creation skill used by Phase P."""

    __tablename__ = "creative_skills"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    default_intensity: Mapped[str] = mapped_column(String(32), default="标准增强")
    shot_template_key: Mapped[str] = mapped_column(String(64), default="")
    prompt_director_config_key: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillVersion(Base):
    """Versioned runnable definition for a skill."""

    __tablename__ = "skill_versions"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    skill_id: Mapped[str] = mapped_column(String(16), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    input_schema: Mapped[Optional[dict]] = mapped_column(JSONB)
    output_schema: Mapped[Optional[dict]] = mapped_column(JSONB)
    definition: Mapped[Optional[dict]] = mapped_column(JSONB)
    prompt_template: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    skill: Mapped["Skill"] = relationship(back_populates="versions")


class SkillRun(Base):
    """Skill execution record."""

    __tablename__ = "skill_runs"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    skill_version_id: Mapped[str] = mapped_column(String(16), ForeignKey("skill_versions.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[Optional[str]] = mapped_column(String(16))
    node_id: Mapped[Optional[str]] = mapped_column(String(16))
    input: Mapped[Optional[dict]] = mapped_column(JSONB)
    output: Mapped[Optional[dict]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="success")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_cny: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlmCall(Base):
    """LLM usage meter row, written by the Java gateway UsageMeterAspect."""

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String(16))
    node_id: Mapped[Optional[str]] = mapped_column(String(16))
    skill_run_id: Mapped[Optional[str]] = mapped_column(String(16))
    biz_type: Mapped[str] = mapped_column(String(32), default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_cny: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="success")
    trace_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    # （migration 004）：failover 链路追溯。
    # status='fallback' 时单字段不足以表达"先调 DeepSeek 超时 → 切 Qwen 5xx → 最后 GLM 成功"。
    # fallback_chain 存 list[{provider, model, status, latency_ms, error}] 完整链路。
    # 常见面试场景"LLM 5xx 怎么处理"必背：这就是证据来源。
    fallback_chain: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BillingDaily(Base):
    """daily tenant-level billing aggregation."""

    __tablename__ = "billing_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dt: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cost_cny: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    success_calls: Mapped[int] = mapped_column(Integer, default=0)
    fallback_calls: Mapped[int] = mapped_column(Integer, default=0)
    failed_calls: Mapped[int] = mapped_column(Integer, default=0)
    by_provider: Mapped[Optional[dict]] = mapped_column(JSONB)
    by_biz_type: Mapped[Optional[dict]] = mapped_column(JSONB)
    aggregated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("tenant_id", "dt", name="uq_billing_daily_tenant_dt"),)


class GenerationSession(Base):
    """Phase P P8: one complete video generation session context."""

    __tablename__ = "generation_sessions"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_short_id)
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    skill_id: Mapped[Optional[str]] = mapped_column(String(64))
    theme: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    locked_character_id: Mapped[Optional[str]] = mapped_column(String(64))
    locked_scene_id: Mapped[Optional[str]] = mapped_column(String(64))
    locked_storyboard_id: Mapped[Optional[str]] = mapped_column(String(16))
    plan_id: Mapped[Optional[str]] = mapped_column(String(8), index=True)
    final_score: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    events: Mapped[list["ClipReviewEvent"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ClipReviewEvent(Base):
    """Phase P P8: user review event trail for continue / regen / cancel."""

    __tablename__ = "clip_review_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(16), ForeignKey("generation_sessions.id", ondelete="CASCADE"), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    clip_index: Mapped[Optional[int]] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    hints: Mapped[Optional[list]] = mapped_column(JSONB)
    event_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["GenerationSession"] = relationship(back_populates="events")


class FailRecord(Base):
    """Phase P P9: structured failure record with 7 error_code categories."""

    __tablename__ = "fail_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[Optional[str]] = mapped_column(
        String(16), ForeignKey("generation_sessions.id", ondelete="SET NULL"), index=True
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    event_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
