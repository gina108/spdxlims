"""initial lims schema

Revision ID: 20260221_0001
Revises:
Create Date: 2026-02-21 14:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260221_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role in ('admin','tech','reviewer','lab_manager')", name="ck_app_user_role"),
    )

    op.create_table(
        "patient",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mrn", sa.String(length=64), unique=True),
        sa.Column("first_name", sa.String(length=120), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column("dob", sa.Date(), nullable=False),
        sa.Column("sex", sa.String(length=1), nullable=False),
        sa.Column("phone", sa.String(length=40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("sex in ('M','F','X')", name="ck_patient_sex"),
    )

    op.create_table(
        "test_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("specimen_type", sa.String(length=80), nullable=False),
        sa.Column("unit", sa.String(length=32)),
        sa.Column("method", sa.String(length=120)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "provider",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_type", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=64), unique=True),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("tax_id", sa.String(length=64)),
        sa.Column("email", sa.String(length=255)),
        sa.Column("phone", sa.String(length=40)),
        sa.Column("address", sa.Text()),
        sa.Column("billing_terms_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("provider_type in ('doctor','clinic')", name="ck_provider_type"),
    )

    op.create_table(
        "provider_price",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("provider.id"), nullable=False),
        sa.Column("test_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("test_catalog.id"), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.UniqueConstraint("provider_id", "test_id", "effective_from", name="uq_provider_price"),
    )

    op.create_table(
        "lab_order",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_number", sa.String(length=64), nullable=False, unique=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patient.id"), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("provider.id")),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.CheckConstraint("status in ('registered','collected','in_lab','completed','reported','amended')", name="ck_lab_order_status"),
    )

    op.create_table(
        "order_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lab_order.id", ondelete="CASCADE"), nullable=False),
        sa.Column("test_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("test_catalog.id"), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="routine"),
        sa.CheckConstraint("priority in ('routine','stat')", name="ck_order_item_priority"),
    )

    op.create_table(
        "sample",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lab_order.id", ondelete="CASCADE"), nullable=False),
        sa.Column("barcode", sa.String(length=64), nullable=False, unique=True),
        sa.Column("specimen_type", sa.String(length=80), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.CheckConstraint("status in ('registered','collected','received','rejected','processed')", name="ck_sample_status"),
    )

    op.create_table(
        "result",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("order_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sample_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sample.id")),
        sa.Column("value_text", sa.Text()),
        sa.Column("value_num", sa.Numeric()),
        sa.Column("unit", sa.String(length=32)),
        sa.Column("flag", sa.String(length=16)),
        sa.Column("entered_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("verified_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_user.id")),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.CheckConstraint("status in ('draft','verified','amended')", name="ck_result_status"),
    )

    op.create_table(
        "supplier",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=64), unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("contact_name", sa.String(length=120)),
        sa.Column("email", sa.String(length=255)),
        sa.Column("phone", sa.String(length=40)),
        sa.Column("address", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "inventory_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sku", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("min_stock", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("max_stock", sa.Numeric(14, 3)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "inventory_lot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_item.id"), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("supplier.id")),
        sa.Column("lot_number", sa.String(length=120), nullable=False),
        sa.Column("expiration_date", sa.Date()),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 4)),
        sa.Column("initial_qty", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("current_qty", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.UniqueConstraint("item_id", "lot_number", name="uq_inventory_item_lot"),
        sa.CheckConstraint("status in ('active','quarantine','expired','consumed','discarded')", name="ck_inventory_lot_status"),
    )

    op.create_table(
        "inventory_txn",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("txn_ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_item.id"), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_lot.id")),
        sa.Column("txn_type", sa.String(length=24), nullable=False),
        sa.Column("qty", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 4)),
        sa.Column("reference_type", sa.String(length=32)),
        sa.Column("reference_id", sa.String(length=128)),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_user.id"), nullable=False),
        sa.CheckConstraint("qty > 0", name="ck_inventory_txn_qty_positive"),
        sa.CheckConstraint("txn_type in ('purchase_in','usage_out','adjustment_plus','adjustment_minus','waste_out','return_out')", name="ck_inventory_txn_type"),
    )

    op.create_table(
        "invoice",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("provider.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("issue_date", sa.Date()),
        sa.Column("due_date", sa.Date()),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("tax", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("provider_id", "period_start", "period_end", name="uq_invoice_period"),
        sa.CheckConstraint("status in ('draft','issued','paid','void')", name="ck_invoice_status"),
    )

    op.create_table(
        "invoice_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("invoice.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lab_order.id")),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("order_item.id")),
        sa.Column("test_code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("qty", sa.Numeric(12, 2), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
    )

    op.create_table(
        "month_end_close",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("opened_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("closed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_user.id")),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.UniqueConstraint("period_start", "period_end", name="uq_month_end_period"),
        sa.CheckConstraint("status in ('open','in_review','closed')", name="ck_month_end_close_status"),
    )

    op.create_table(
        "month_end_checklist",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("close_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("month_end_close.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_key", sa.String(length=64), nullable=False),
        sa.Column("is_done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("done_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_user.id")),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("close_id", "item_key", name="uq_month_end_checklist"),
    )

    op.create_table(
        "month_end_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("close_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("month_end_close.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_type", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("snapshot_type in ('billing','inventory','operations')", name="ck_month_end_snapshot_type"),
    )

    op.create_table(
        "audit_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_user.id")),
        sa.Column("entity", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("before_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("after_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("audit_event")
    op.drop_table("month_end_snapshot")
    op.drop_table("month_end_checklist")
    op.drop_table("month_end_close")
    op.drop_table("invoice_line")
    op.drop_table("invoice")
    op.drop_table("inventory_txn")
    op.drop_table("inventory_lot")
    op.drop_table("inventory_item")
    op.drop_table("supplier")
    op.drop_table("result")
    op.drop_table("sample")
    op.drop_table("order_item")
    op.drop_table("lab_order")
    op.drop_table("provider_price")
    op.drop_table("provider")
    op.drop_table("test_catalog")
    op.drop_table("patient")
    op.drop_table("app_user")


