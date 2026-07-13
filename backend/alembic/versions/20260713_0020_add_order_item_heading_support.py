"""add order_item heading/comment row support

Revision ID: 20260713_0020
Revises: 20260713_0019
Create Date: 2026-07-13 02:00:00

Local/SQLite mode stores panel sub-headings (e.g. "Formula Roja") and
comments as their own order_tests rows, positioned inline among the real
test rows. Server mode had no equivalent: order_item could only represent
real tests (a single group_label string per row), so panel sub-headings
were silently discarded on import and can't be created at all today. This
adds item_type ('test' | 'heading' | 'comment') and display_name (the
heading/comment's own text) to order_item, and makes test_id nullable
since heading/comment rows don't reference a real test.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260713_0020"
down_revision = "20260713_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order_item", sa.Column("item_type", sa.String(length=16), nullable=False, server_default="test"))
    op.add_column("order_item", sa.Column("display_name", sa.String(length=255), nullable=True))
    op.alter_column("order_item", "test_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    op.alter_column("order_item", "test_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("order_item", "display_name")
    op.drop_column("order_item", "item_type")
