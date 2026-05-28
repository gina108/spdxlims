"""expand result entry fields for desktop workflow

Revision ID: 20260406_0005
Revises: 20260406_0004
Create Date: 2026-04-06 20:05:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260406_0005"
down_revision = "20260406_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("result", sa.Column("lower_value_text", sa.String(length=64), nullable=True))
    op.add_column("result", sa.Column("upper_value_text", sa.String(length=64), nullable=True))
    op.add_column("result", sa.Column("reference_text", sa.Text(), nullable=True))
    op.add_column("result", sa.Column("comments", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("result", "comments")
    op.drop_column("result", "reference_text")
    op.drop_column("result", "upper_value_text")
    op.drop_column("result", "lower_value_text")
