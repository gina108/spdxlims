"""add order_item.sort_order

Revision ID: 20260713_0018
Revises: 20260704_0017
Create Date: 2026-07-13 00:00:00

Server-mode reports were sorting order items by their (random UUID) primary
key instead of entry order, which scattered analitos that belong to the same
panel and made each one render under its own repeated heading. This adds a
persisted sort_order and backfills existing rows using Postgres's physical
row order (ctid) as a best-effort approximation of insertion order, since the
true order was never previously stored.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260713_0018"
down_revision = "20260704_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order_item", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        """
        UPDATE order_item
        SET sort_order = ranked.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY ctid) - 1 AS rn
            FROM order_item
        ) AS ranked
        WHERE order_item.id = ranked.id
        """
    )


def downgrade() -> None:
    op.drop_column("order_item", "sort_order")
