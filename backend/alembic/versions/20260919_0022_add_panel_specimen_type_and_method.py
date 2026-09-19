"""carry a panel's specimen type and method

Revision ID: 20260919_0022
Revises: 20260918_0021
Create Date: 2026-09-19 00:00:00

A printed report carries a line under each study - "Metodologia: Quimicaliquida
| Tipo de Muestra: Suero" - built from the panel's own metadata. Local mode has
stored both on test_panels all along and renders the line; panel_catalog never
had the columns, so the desktop POSTed them to /api/panels and the server threw
them away. A report rendered in server mode simply lost that line.

Both are nullable: most panels have one or neither, and a missing value means
the line is left off rather than printed half empty.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260919_0022"
down_revision = "20260918_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("panel_catalog", sa.Column("specimen_type", sa.String(length=255), nullable=True))
    op.add_column("panel_catalog", sa.Column("method", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("panel_catalog", "method")
    op.drop_column("panel_catalog", "specimen_type")
