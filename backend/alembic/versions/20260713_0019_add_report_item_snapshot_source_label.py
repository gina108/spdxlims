"""add report_item_snapshot.source_label_snapshot

Revision ID: 20260713_0019
Revises: 20260713_0018
Create Date: 2026-07-13 01:00:00

The server-mode report preview never carried a panel/source label per item,
so the shared HTML renderer's keep-together pagination (which groups
consecutive rows sharing a label into one page-break unit) treated every
row as its own isolated group and let panels split across pages. This adds
the missing label to both the live preview (ReportPreviewItemOut.source_label)
and the finalized-report snapshot (this column), mirroring what local/SQLite
mode already stores.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260713_0019"
down_revision = "20260713_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("report_item_snapshot", sa.Column("source_label_snapshot", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("report_item_snapshot", "source_label_snapshot")
