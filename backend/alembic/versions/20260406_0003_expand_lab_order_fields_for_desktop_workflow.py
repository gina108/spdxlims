"""expand lab_order fields for desktop workflow

Revision ID: 20260406_0003
Revises: 20260406_0002
Create Date: 2026-04-06 17:30:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260406_0003"
down_revision = "20260406_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lab_order", sa.Column("accession_id", sa.String(length=64), nullable=True))
    op.add_column("lab_order", sa.Column("sample_id", sa.String(length=64), nullable=True))
    op.add_column("lab_order", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("lab_order", "notes")
    op.drop_column("lab_order", "sample_id")
    op.drop_column("lab_order", "accession_id")
