"""add report_settings json to lab_profile

Revision ID: 20260704_0015
Revises: 20260704_0014
Create Date: 2026-07-04 00:30:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260704_0015"
down_revision = "20260704_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lab_profile", sa.Column("report_settings", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("lab_profile", "report_settings")
