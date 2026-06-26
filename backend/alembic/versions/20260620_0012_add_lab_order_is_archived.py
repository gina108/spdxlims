"""add lab_order is_archived

Revision ID: 20260620_0012
Revises: 20260616_0011
Create Date: 2026-06-20 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260620_0012"
down_revision = "20260616_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lab_order", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("lab_order", "is_archived")
