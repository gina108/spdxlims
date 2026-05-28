"""add order item group label

Revision ID: 20260407_0010
Revises: 20260406_0009
Create Date: 2026-04-07 00:20:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260407_0010"
down_revision = "20260406_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('order_item', sa.Column('group_label', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('order_item', 'group_label')
