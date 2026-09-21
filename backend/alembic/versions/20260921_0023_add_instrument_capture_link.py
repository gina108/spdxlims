"""share which instrument captures have already been linked

Revision ID: 20260921_0023
Revises: 20260919_0022
Create Date: 2026-09-21 00:00:00

"Linked" was recorded only in each app's own SQLite (order_ui_state, scope
'instrument_capture'). That was deliberate while one machine ran two apps - it
kept them from stealing captures from each other - but with several
workstations against one server it means a capture linked on LAB1 still shows
as pending on LAB2, and can be imported a second time over results someone has
since corrected by hand.

The server already knew this: import-instrument logs capture_id in the audit
trail. This makes it queryable so every workstation sees the same state.

capture_id is the primary key: a capture belongs to one order, and re-linking
the same capture to a different order overwrites the row rather than leaving
two answers. order_id cascades, so deleting an order takes its links with it.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260921_0023"
down_revision = "20260919_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instrument_capture_link",
        sa.Column("capture_id", sa.String(length=128), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("linked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["lab_order.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_by"], ["app_user.id"]),
    )
    op.create_index("ix_instrument_capture_link_order_id", "instrument_capture_link", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_instrument_capture_link_order_id", table_name="instrument_capture_link")
    op.drop_table("instrument_capture_link")
