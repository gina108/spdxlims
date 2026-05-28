"""split lab_order doctor and client providers

Revision ID: 20260406_0004
Revises: 20260406_0003
Create Date: 2026-04-06 19:10:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260406_0004"
down_revision = "20260406_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lab_order", sa.Column("doctor_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("lab_order", sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_lab_order_doctor_id", "lab_order", "provider", ["doctor_id"], ["id"])
    op.create_foreign_key("fk_lab_order_client_id", "lab_order", "provider", ["client_id"], ["id"])
    op.execute("UPDATE lab_order SET doctor_id = provider_id WHERE provider_id IS NOT NULL")
    op.drop_constraint(op.f("lab_order_provider_id_fkey"), "lab_order", type_="foreignkey")
    op.drop_column("lab_order", "provider_id")


def downgrade() -> None:
    op.add_column("lab_order", sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(op.f("lab_order_provider_id_fkey"), "lab_order", "provider", ["provider_id"], ["id"])
    op.execute("UPDATE lab_order SET provider_id = doctor_id WHERE doctor_id IS NOT NULL")
    op.drop_constraint("fk_lab_order_client_id", "lab_order", type_="foreignkey")
    op.drop_constraint("fk_lab_order_doctor_id", "lab_order", type_="foreignkey")
    op.drop_column("lab_order", "client_id")
    op.drop_column("lab_order", "doctor_id")
