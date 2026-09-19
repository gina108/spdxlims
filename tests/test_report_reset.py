"""Deleting a saved report puts the order back where it was before approval.

"Actualizar desde el servidor" on the report preview throws the frozen report
away and reloads from the live results. Finalizing had marked the order
finalized/reported, and deleting the report left that behind: the order stayed
finalized with no report to show for it, so the status dot went on reading green
for a report that had been sent back for editing.
"""

from __future__ import annotations

import pytest

from spdxlims.database import Database


@pytest.fixture()
def database(tmp_path):
    database = Database(tmp_path / "lims.db")
    database.initialize()
    return database


def _approved_order(database: Database) -> int:
    patient_id = database.create_patient(
        {
            "first_name": "Ana", "last_name": "Ruiz", "middle_name": "", "sex": "F",
            "date_of_birth": "", "age_value": 30, "age_unit": "years", "phone": "",
        }
    )
    database.create_test(
        {
            "code": "GLU", "name": "Glucosa", "category_name": "Chemistry", "specimen_type": "Suero",
            "method": "", "result_kind": "text", "select_options": [], "default_result_value": "", "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code("GLU")
    order_id = database.create_order(
        None, None, None, patient_id, None, None,
        [{"item_type": "test", "test_id": test_id, "label": "Glucosa", "source": ""}],
        "draft", "",
    )
    entry = database.get_order_result_entries(order_id)[0]
    database.save_result_entry(entry.order_test_id, "90", "", None, None, "", "", "text")
    database.finalize_report(order_id)
    return order_id


def _order_row(database: Database, order_id: int) -> tuple[str, str | None]:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT status, reported_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
    return (row["status"], row["reported_at"])


def test_finalizing_marks_the_order_reported(database):
    order_id = _approved_order(database)

    status, reported_at = _order_row(database, order_id)
    assert status == "finalized"
    assert reported_at is not None


def test_deleting_the_report_takes_the_order_back_out_of_finalized(database):
    order_id = _approved_order(database)

    database.delete_saved_report(order_id)

    status, reported_at = _order_row(database, order_id)
    assert status == "in_progress"
    assert reported_at is None
    assert database.get_saved_report_preview(order_id) is None


def test_an_order_that_was_never_finalized_is_left_alone(database):
    order_id = _approved_order(database)
    database.delete_saved_report(order_id)
    with database.connect() as connection:
        connection.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))

    database.delete_saved_report(order_id)

    assert _order_row(database, order_id)[0] == "cancelled"
