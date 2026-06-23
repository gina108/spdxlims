"""add image result type

Revision ID: 20260622_0013
Revises: 20260620_0012
Create Date: 2026-06-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260622_0013"
down_revision = "20260620_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_test_catalog_result_kind", "test_catalog", type_="check")
    op.create_check_constraint(
        "ck_test_catalog_result_kind",
        "test_catalog",
        "result_kind in ('numeric','text','select','image')",
    )

    op.create_table(
        "result_image",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("order_item.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_data", sa.LargeBinary(), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False, server_default="image/png"),
        sa.Column("caption", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_result_image_order_item_id", "result_image", ["order_item_id"])

    op.create_table(
        "report_item_image_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("report_snapshot.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("order_item.id")),
        sa.Column("image_data", sa.LargeBinary(), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False, server_default="image/png"),
        sa.Column("caption", sa.Text()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_report_item_image_snapshot_report_id", "report_item_image_snapshot", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_report_item_image_snapshot_report_id", table_name="report_item_image_snapshot")
    op.drop_table("report_item_image_snapshot")
    op.drop_index("ix_result_image_order_item_id", table_name="result_image")
    op.drop_table("result_image")
    op.drop_constraint("ck_test_catalog_result_kind", "test_catalog", type_="check")
    op.create_check_constraint(
        "ck_test_catalog_result_kind",
        "test_catalog",
        "result_kind in ('numeric','text','select')",
    )
