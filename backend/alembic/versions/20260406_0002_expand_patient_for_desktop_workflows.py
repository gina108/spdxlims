"""expand patient for desktop workflows

Revision ID: 20260406_0002
Revises: 20260221_0001
Create Date: 2026-04-06 14:30:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260406_0002"
down_revision = "20260221_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patient", sa.Column("middle_name", sa.String(length=120), nullable=True))
    op.add_column("patient", sa.Column("age_value", sa.Integer(), nullable=True))
    op.add_column("patient", sa.Column("age_unit", sa.String(length=16), nullable=True))
    op.add_column("patient", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("patient", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("patient", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.alter_column("patient", "dob", existing_type=sa.Date(), nullable=True)
    op.alter_column("patient", "sex", existing_type=sa.String(length=1), nullable=True)
    op.drop_constraint("ck_patient_sex", "patient", type_="check")
    op.create_check_constraint("ck_patient_sex", "patient", "sex in ('M','F','O','X') or sex is null")
    op.create_check_constraint("ck_patient_age_unit", "patient", "age_unit in ('days','months','years') or age_unit is null")


def downgrade() -> None:
    op.drop_constraint("ck_patient_age_unit", "patient", type_="check")
    op.drop_constraint("ck_patient_sex", "patient", type_="check")
    op.create_check_constraint("ck_patient_sex", "patient", "sex in ('M','F','X')")
    op.alter_column("patient", "sex", existing_type=sa.String(length=1), nullable=False)
    op.alter_column("patient", "dob", existing_type=sa.Date(), nullable=False)
    op.drop_column("patient", "is_active")
    op.drop_column("patient", "address")
    op.drop_column("patient", "email")
    op.drop_column("patient", "age_unit")
    op.drop_column("patient", "age_value")
    op.drop_column("patient", "middle_name")
