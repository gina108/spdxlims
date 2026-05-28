"""add shared lab profile

Revision ID: 20260406_0007
Revises: 20260406_0006
Create Date: 2026-04-06 22:20:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260406_0007"
down_revision = "20260406_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lab_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lab_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("address", sa.Text(), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("logo_path", sa.Text(), nullable=True),
        sa.Column("header_image_path", sa.Text(), nullable=True),
        sa.Column("footer_signature_image_path", sa.Text(), nullable=True),
        sa.Column("report_footer", sa.Text(), nullable=False, server_default=""),
        sa.Column("director_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("director_license", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO lab_profile (id, lab_name, address, phone, email, report_footer, director_name, director_license) VALUES (1, '', '', '', '', '', '', '')")


def downgrade() -> None:
    op.drop_table("lab_profile")
