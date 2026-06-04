"""metadata + LLM fallback chain

Revision ID: 004
Revises: 003
Create Date: 2026-05-20

（之后）：
- clips.r_metadata JSONB：存 R2.1 SceneShot.model_dump() 完整 Pydantic schema
  下游 R3-R7 重生成时能完整复原上下文（voice_type / wardrobe_choice / position
  嵌套 / key_props 等 schema 字段在 clips 平铺列不够装）。
- llm_calls.fallback_chain JSONB：LlmRouter 多模型 failover 链路追溯
  存 list[{provider, model, status, latency_ms, error}] 完整链路
  常见面试场景"LLM 5xx 怎么处理"的证据来源。

铁律 5：只 add_column，不动其他字段。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clips",
        sa.Column("r_metadata", JSONB, nullable=True),
    )
    op.add_column(
        "llm_calls",
        sa.Column("fallback_chain", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_calls", "fallback_chain")
    op.drop_column("clips", "r_metadata")
