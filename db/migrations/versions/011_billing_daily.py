"""billing_daily aggregation table

Revision ID: 011
Revises: 010
Create Date: 2026-05-27

daily tenant-level billing aggregation for llm_calls.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_daily",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("dt", sa.Date, nullable=False),
        sa.Column("total_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_input_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("total_output_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("total_cost_cny", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("success_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fallback_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("by_provider", JSONB),
        sa.Column("by_biz_type", JSONB),
        sa.Column("aggregated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "dt", name="uq_billing_daily_tenant_dt"),
    )
    op.create_index("ix_billing_daily_dt", "billing_daily", ["dt"])
    op.create_index("ix_billing_daily_tenant", "billing_daily", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_billing_daily_tenant", table_name="billing_daily")
    op.drop_index("ix_billing_daily_dt", table_name="billing_daily")
    op.drop_table("billing_daily")
