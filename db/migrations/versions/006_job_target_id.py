"""Job target_id for concurrent regenerate protection

Revision ID: 006
Revises: 005
Create Date: 2026-05-21

jobs 加 target_id (str 16) + 索引。

痛点：同 clip 短时间多次 POST /api/v1/clips/{id}/regenerate
  → 多个 worker 并发跑同 clip
  → race condition（最后一个 commit 赢，前面白烧 API 配额）
  → 常见面试场景"防重复提交 / 防并发"经典场景

解：
  jobs.target_id 记录任务作用的实体 ID（如 clip_id / plan_id）
  + (target_id, status) 复合索引让"查活跃任务"走索引
  POST 接口预检：有 status in ('queued','running') 的同 target_id 任务 → 409
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("target_id", sa.String(16), nullable=True))
    op.create_index("ix_jobs_target_id_status", "jobs", ["target_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_target_id_status", table_name="jobs")
    op.drop_column("jobs", "target_id")
