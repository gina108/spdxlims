"""add outsourced panel tables and panel_meta report item type

Revision ID: 20260704_0014
Revises: 20260622_0013
Create Date: 2026-07-04 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260704_0014"
down_revision = "20260622_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Allow the desktop's panel_meta report rows (methodology / sample-type lines).
    op.drop_constraint("ck_report_item_snapshot_type", "report_item_snapshot", type_="check")
    op.create_check_constraint(
        "ck_report_item_snapshot_type",
        "report_item_snapshot",
        "item_type_snapshot in ('test','heading','comment','panel_meta')",
    )

    # Immutable snapshot of outsourced-PDF rows captured when a report is finalized.
    op.create_table(
        "report_outsourced_row_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("report_snapshot.id", ondelete="CASCADE"), nullable=False),
        sa.Column("panel_label", sa.String(length=255), nullable=False),
        sa.Column("source_pdf_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("row_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("col_1", sa.Text()),
        sa.Column("col_2", sa.Text()),
        sa.Column("col_3", sa.Text()),
        sa.Column("col_4", sa.Text()),
        sa.Column("col_5", sa.Text()),
    )
    op.create_index("ix_report_outsourced_row_snapshot_report_id", "report_outsourced_row_snapshot", ["report_id"])

    # Live (editable) outsourced-PDF extraction workspace attached to an order.
    op.create_table(
        "outsourced_panel_table",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("lab_order.id", ondelete="CASCADE"), nullable=False),
        sa.Column("panel_label", sa.String(length=255), nullable=False),
        sa.Column("source_pdf_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("order_id", "panel_label", name="uq_outsourced_panel_table_order_label"),
    )
    op.create_index("ix_outsourced_panel_table_order_id", "outsourced_panel_table", ["order_id"])

    op.create_table(
        "outsourced_panel_extraction",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("outsourced_panel_table_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("outsourced_panel_table.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_pdf_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("page_label", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_outsourced_panel_extraction_table_id", "outsourced_panel_extraction", ["outsourced_panel_table_id"])

    op.create_table(
        "outsourced_panel_row",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("outsourced_panel_table_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("outsourced_panel_table.id", ondelete="CASCADE"), nullable=False),
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("outsourced_panel_extraction.id", ondelete="SET NULL")),
        sa.Column("row_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("col_1", sa.Text()),
        sa.Column("col_2", sa.Text()),
        sa.Column("col_3", sa.Text()),
        sa.Column("col_4", sa.Text()),
        sa.Column("col_5", sa.Text()),
    )
    op.create_index("ix_outsourced_panel_row_table_id", "outsourced_panel_row", ["outsourced_panel_table_id"])


def downgrade() -> None:
    op.drop_index("ix_outsourced_panel_row_table_id", table_name="outsourced_panel_row")
    op.drop_table("outsourced_panel_row")
    op.drop_index("ix_outsourced_panel_extraction_table_id", table_name="outsourced_panel_extraction")
    op.drop_table("outsourced_panel_extraction")
    op.drop_index("ix_outsourced_panel_table_order_id", table_name="outsourced_panel_table")
    op.drop_table("outsourced_panel_table")
    op.drop_index("ix_report_outsourced_row_snapshot_report_id", table_name="report_outsourced_row_snapshot")
    op.drop_table("report_outsourced_row_snapshot")
    op.drop_constraint("ck_report_item_snapshot_type", "report_item_snapshot", type_="check")
    op.create_check_constraint(
        "ck_report_item_snapshot_type",
        "report_item_snapshot",
        "item_type_snapshot in ('test','heading','comment')",
    )
