"""allow the observation result kind in the catalog

Revision ID: 20260918_0021
Revises: 20260713_0020
Create Date: 2026-09-18 23:00:00

Local/SQLite mode has a fifth result kind, 'observation': a free-text note
that is printed as a wide row with no unit or reference range, and left off
the report entirely when it is empty. The server's check constraint allowed
only numeric/text/select/image, so the lab's observation tests (Serie roja,
Serie blanca, ...) were downgraded to 'text' on import. As plain text they
are counted as results that must be filled in, which keeps an order off the
"ready to approve" status for a note that was never required.
"""

from alembic import op

revision = "20260918_0021"
down_revision = "20260713_0020"
branch_labels = None
depends_on = None

_KINDS_WITH_OBSERVATION = "result_kind in ('numeric','text','select','image','observation')"
_KINDS_BEFORE = "result_kind in ('numeric','text','select','image')"


def upgrade() -> None:
    op.drop_constraint("ck_test_catalog_result_kind", "test_catalog", type_="check")
    op.create_check_constraint("ck_test_catalog_result_kind", "test_catalog", _KINDS_WITH_OBSERVATION)


def downgrade() -> None:
    # Anything still marked as an observation becomes text again, or the old
    # constraint could not be put back.
    op.execute("UPDATE test_catalog SET result_kind = 'text' WHERE result_kind = 'observation'")
    op.drop_constraint("ck_test_catalog_result_kind", "test_catalog", type_="check")
    op.create_check_constraint("ck_test_catalog_result_kind", "test_catalog", _KINDS_BEFORE)
