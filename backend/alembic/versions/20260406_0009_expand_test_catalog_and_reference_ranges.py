"""expand shared test catalog and reference ranges

Revision ID: 20260406_0009
Revises: 20260406_0008
Create Date: 2026-04-06 23:55:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260406_0009"
down_revision = "20260406_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('test_catalog', sa.Column('category_name', sa.String(length=255), nullable=True))
    op.add_column('test_catalog', sa.Column('result_kind', sa.String(length=16), nullable=False, server_default='text'))
    op.add_column('test_catalog', sa.Column('select_options', sa.Text(), nullable=True))
    op.add_column('test_catalog', sa.Column('default_result_value', sa.Text(), nullable=True))
    op.add_column('test_catalog', sa.Column('price', sa.Numeric(12, 2), nullable=False, server_default='0'))
    op.alter_column('test_catalog', 'specimen_type', existing_type=sa.String(length=80), nullable=True)
    op.create_check_constraint('ck_test_catalog_result_kind', 'test_catalog', "result_kind in ('numeric','text','select')")

    op.create_table(
        'test_reference_range',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('test_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('sex', sa.String(length=1), nullable=True),
        sa.Column('age_min_days', sa.Integer(), nullable=True),
        sa.Column('age_max_days', sa.Integer(), nullable=True),
        sa.Column('lower_value_text', sa.String(length=64), nullable=True),
        sa.Column('upper_value_text', sa.String(length=64), nullable=True),
        sa.Column('unit', sa.String(length=32), nullable=True),
        sa.Column('reference_text', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['test_id'], ['test_catalog.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_check_constraint('ck_test_reference_range_sex', 'test_reference_range', "sex in ('M','F','O','X') or sex is null")


def downgrade() -> None:
    op.drop_constraint('ck_test_reference_range_sex', 'test_reference_range', type_='check')
    op.drop_table('test_reference_range')
    op.drop_constraint('ck_test_catalog_result_kind', 'test_catalog', type_='check')
    op.alter_column('test_catalog', 'specimen_type', existing_type=sa.String(length=80), nullable=False)
    op.drop_column('test_catalog', 'price')
    op.drop_column('test_catalog', 'default_result_value')
    op.drop_column('test_catalog', 'select_options')
    op.drop_column('test_catalog', 'result_kind')
    op.drop_column('test_catalog', 'category_name')
