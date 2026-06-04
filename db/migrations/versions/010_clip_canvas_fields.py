"""Phase P P10 clip canvas-node fields

Revision ID: 010
Revises: 009
Create Date: 2026-05-25

Adds 7 columns to `clips` for画布节点完整数据组（Phase F 渲染依赖）：
- first_frame_url / tail_frame_url   ：画面预览（去 frame_assets 之外的快捷缓存）
- cost_breakdown JSONB               ：本段成本细分（video/first_frame/tts）
- regen_count INTEGER                ：重生成次数（dirty 历史）
- dirty_reason TEXT                  ：被标 dirty 的原因
- blocking_for JSONB                 ：当前 clip 重生成后，会让哪些下游 clip 也 dirty（list[int]）
- depends_on JSONB                   ：当前 clip 的首帧来自哪些上游 clip 尾帧（list[int]）

P10 不强制写入；webhooks 流程后续按需写。FE 拉到字段就渲染。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clips", sa.Column("first_frame_url", sa.Text, server_default="", nullable=False))
    op.add_column("clips", sa.Column("tail_frame_url", sa.Text, server_default="", nullable=False))
    op.add_column("clips", sa.Column("cost_breakdown", JSONB))
    op.add_column("clips", sa.Column("regen_count", sa.Integer, server_default="0", nullable=False))
    op.add_column("clips", sa.Column("dirty_reason", sa.Text, server_default="", nullable=False))
    op.add_column("clips", sa.Column("blocking_for", JSONB))
    op.add_column("clips", sa.Column("depends_on", JSONB))


def downgrade() -> None:
    op.drop_column("clips", "depends_on")
    op.drop_column("clips", "blocking_for")
    op.drop_column("clips", "dirty_reason")
    op.drop_column("clips", "regen_count")
    op.drop_column("clips", "cost_breakdown")
    op.drop_column("clips", "tail_frame_url")
    op.drop_column("clips", "first_frame_url")
