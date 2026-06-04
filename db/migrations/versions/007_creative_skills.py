"""Phase P P5 creative_skills

Revision ID: 007
Revises: 006
Create Date: 2026-05-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "creative_skills",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, server_default="", nullable=False),
        sa.Column("default_intensity", sa.String(32), server_default="标准增强", nullable=False),
        sa.Column("shot_template_key", sa.String(64), server_default="", nullable=False),
        sa.Column("prompt_director_config_key", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("uq_creative_skills_name", "creative_skills", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_creative_skills_name", table_name="creative_skills")
    op.drop_table("creative_skills")
