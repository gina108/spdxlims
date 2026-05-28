"""add report snapshots and reported_at to lab orders

Revision ID: 20260406_0006
Revises: 20260406_0005
Create Date: 2026-04-06 21:40:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260406_0006"
down_revision = "20260406_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lab_order", sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "report_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("patient_snapshot_name", sa.String(length=255), nullable=False),
        sa.Column("patient_snapshot_sex", sa.String(length=16), nullable=True),
        sa.Column("patient_snapshot_dob", sa.String(length=32), nullable=True),
        sa.Column("doctor_snapshot_name", sa.String(length=255), nullable=True),
        sa.Column("client_snapshot_name", sa.String(length=255), nullable=True),
        sa.Column("lab_snapshot_name", sa.String(length=255), nullable=True),
        sa.Column("lab_snapshot_address", sa.Text(), nullable=True),
        sa.Column("lab_snapshot_phone", sa.String(length=64), nullable=True),
        sa.Column("lab_snapshot_email", sa.String(length=255), nullable=True),
        sa.Column("director_snapshot_name", sa.String(length=255), nullable=True),
        sa.Column("director_snapshot_license", sa.String(length=255), nullable=True),
        sa.Column("footer_snapshot_text", sa.Text(), nullable=True),
        sa.Column("header_image_snapshot_path", sa.Text(), nullable=True),
        sa.Column("footer_signature_snapshot_path", sa.Text(), nullable=True),
        sa.Column("general_comments", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["lab_order.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_report_snapshot_order"),
    )
    op.create_check_constraint("ck_report_snapshot_status", "report_snapshot", "status in ('final')")

    op.create_table(
        "report_item_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("test_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("result_value_snapshot", sa.Text(), nullable=True),
        sa.Column("unit_snapshot", sa.String(length=32), nullable=True),
        sa.Column("reference_text_snapshot", sa.Text(), nullable=True),
        sa.Column("lower_value_snapshot_text", sa.String(length=64), nullable=True),
        sa.Column("upper_value_snapshot_text", sa.String(length=64), nullable=True),
        sa.Column("flag_snapshot", sa.String(length=16), nullable=True),
        sa.Column("comments_snapshot", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("item_type_snapshot", sa.String(length=16), nullable=False, server_default="test"),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_item.id"]),
        sa.ForeignKeyConstraint(["report_id"], ["report_snapshot.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_check_constraint("ck_report_item_snapshot_type", "report_item_snapshot", "item_type_snapshot in ('test','heading','comment')")


def downgrade() -> None:
    op.drop_constraint("ck_report_item_snapshot_type", "report_item_snapshot", type_="check")
    op.drop_table("report_item_snapshot")
    op.drop_constraint("ck_report_snapshot_status", "report_snapshot", type_="check")
    op.drop_table("report_snapshot")
    op.drop_column("lab_order", "reported_at")
