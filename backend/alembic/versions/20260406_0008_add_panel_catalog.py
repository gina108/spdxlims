"""add panel catalog for shared orders

Revision ID: 20260406_0008
Revises: 20260406_0007
Create Date: 2026-04-06 23:05:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260406_0008"
down_revision = "20260406_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "panel_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "panel_catalog_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("panel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("test_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("item_type", sa.String(length=16), nullable=False, server_default="test"),
        sa.Column("heading_text", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["panel_id"], ["panel_catalog.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_id"], ["test_catalog.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_check_constraint("ck_panel_catalog_item_type", "panel_catalog_item", "item_type in ('test','heading','comment')")


def downgrade() -> None:
    op.drop_constraint("ck_panel_catalog_item_type", "panel_catalog_item", type_="check")
    op.drop_table("panel_catalog_item")
    op.drop_table("panel_catalog")
