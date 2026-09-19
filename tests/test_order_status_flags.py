"""The progress flags behind the order status dot (see BasePage.build_order_status_indicator)."""

from __future__ import annotations

import pytest

from spdxlims.database import Database


@pytest.fixture()
def database(tmp_path):
    database = Database(tmp_path / "lims.db")
    database.initialize()
    return database


def _patient(database: Database) -> int:
    return database.create_patient(
        {
            "first_name": "Maria",
            "last_name": "",
            "middle_name": "",
            "sex": "F",
            "date_of_birth": "",
            "age_value": 30,
            "age_unit": "years",
            "phone": "",
        }
    )


def _test(database: Database, code: str, *, result_kind: str = "text", default: str = "") -> int:
    database.create_test(
        {
            "code": code,
            "name": code.title(),
            "category_name": "Chemistry",
            "specimen_type": "Suero",
            "method": "",
            "result_kind": result_kind,
            "select_options": [],
            "default_result_value": default,
            "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code(code)
    assert test_id is not None
    return test_id


def _order(database: Database, patient_id: int, test_ids: list[int]) -> int:
    return database.create_order(
        None,
        None,
        None,
        patient_id,
        None,
        None,
        [{"item_type": "test", "test_id": test_id, "label": str(test_id), "source": ""} for test_id in test_ids],
        "draft",
        "",
    )


def _flags(database: Database, order_id: int) -> tuple[bool, bool]:
    record = next(record for record in database.search_orders("") if record.id == order_id)
    return (bool(record.all_results_entered), bool(record.any_results_entered))


def test_nothing_entered_yet(database):
    patient_id = _patient(database)
    order_id = _order(database, patient_id, [_test(database, "GLU"), _test(database, "URE")])

    assert _flags(database, order_id) == (False, False)


def test_some_entered_but_not_all(database):
    patient_id = _patient(database)
    glucose_id = _test(database, "GLU")
    order_id = _order(database, patient_id, [glucose_id, _test(database, "URE")])
    entry = next(
        entry for entry in database.get_order_result_entries(order_id) if int(entry.test_id) == glucose_id
    )
    database.save_result_entry(entry.order_test_id, "90", "", None, None, "", "", "text")

    # The dot is yellow here: work has started, something is still missing.
    assert _flags(database, order_id) == (False, True)


def test_every_result_entered(database):
    patient_id = _patient(database)
    order_id = _order(database, patient_id, [_test(database, "GLU"), _test(database, "URE")])
    for entry in database.get_order_result_entries(order_id):
        database.save_result_entry(entry.order_test_id, "90", "", None, None, "", "", "text")

    assert _flags(database, order_id) == (True, True)


def test_a_catalog_default_completes_a_result_but_is_not_work_in_progress(database):
    patient_id = _patient(database)
    order_id = _order(database, patient_id, [_test(database, "COL", result_kind="select", default="Amarillo")])

    # Nobody has typed anything, so the order is not "in progress", but the
    # default means there is no empty result either.
    assert _flags(database, order_id) == (True, False)


def test_an_empty_observation_does_not_keep_an_order_incomplete(database):
    patient_id = _patient(database)
    glucose_id = _test(database, "GLU")
    order_id = _order(database, patient_id, [glucose_id, _test(database, "OBS", result_kind="observation")])
    entry = next(
        entry for entry in database.get_order_result_entries(order_id) if int(entry.test_id) == glucose_id
    )
    database.save_result_entry(entry.order_test_id, "90", "", None, None, "", "", "text")

    assert _flags(database, order_id) == (True, True)
