"""add desktop-style inventory tables (stock items, suppliers, movements)

Revision ID: 20260704_0017
Revises: 20260704_0016
Create Date: 2026-07-04 02:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260704_0017"
down_revision = "20260704_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_stock_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sku", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=32)),
        sa.Column("on_hand", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("reorder_level", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "inventory_supplier",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=40)),
        sa.Column("email", sa.String(length=255)),
        sa.Column("tax_id", sa.String(length=40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "inventory_movement",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("inventory_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_stock_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_supplier.id", ondelete="SET NULL")),
        sa.Column("movement_type", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("movement_date", sa.Date()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_inventory_movement_item", "inventory_movement", ["inventory_item_id"])
    op.create_index("ix_inventory_movement_supplier", "inventory_movement", ["supplier_id"])


def downgrade() -> None:
    op.drop_index("ix_inventory_movement_supplier", table_name="inventory_movement")
    op.drop_index("ix_inventory_movement_item", table_name="inventory_movement")
    op.drop_table("inventory_movement")
    op.drop_table("inventory_supplier")
    op.drop_table("inventory_stock_item")
