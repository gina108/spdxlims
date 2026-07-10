"""add is_outsourced and source_label to order_item

Revision ID: 20260704_0016
Revises: 20260704_0015
Create Date: 2026-07-04 01:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260704_0016"
down_revision = "20260704_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order_item", sa.Column("is_outsourced", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("order_item", sa.Column("source_label", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("order_item", "source_label")
    op.drop_column("order_item", "is_outsourced")
