"""add test formula

Revision ID: 20260616_0011
Revises: 20260407_0010
Create Date: 2026-06-16 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260616_0011"
down_revision = "20260407_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('test_catalog', sa.Column('formula', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('test_catalog', 'formula')
