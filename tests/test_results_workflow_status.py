from spdxlims.database import Database


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


def _test(database: Database, code: str, name: str, result_kind: str) -> int:
    database.create_test(
        {
            "code": code,
            "name": name,
            "category_name": "Chemistry",
            "specimen_type": "Suero",
            "method": "",
            "result_kind": result_kind,
            "select_options": [],
            "default_result_value": "",
            "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code(code)
    assert test_id is not None
    return test_id


def _order(database: Database, patient_id: int, items: list[dict]) -> int:
    return database.create_order(None, None, None, patient_id, None, None, items, "draft", "")


def test_results_workflow_marks_order_ready_when_all_results_have_values(tmp_path):
    database = Database(tmp_path / "lims.db")
    database.initialize()
    patient_id = _patient(database)
    test_id = _test(database, "GLU", "Glucosa", "text")
    order_id = _order(
        database,
        patient_id,
        [{"item_type": "test", "test_id": test_id, "label": "Glucosa", "source": ""}],
    )

    before = next(record for record in database.list_results_workflow_orders() if record.id == order_id)
    assert before.result_count == 1
    assert before.completed_result_count == 0

    entry = database.get_order_result_entries(order_id)[0]
    database.save_result_entry(entry.order_test_id, "90", "", None, None, "", "", "text")

    after = next(record for record in database.list_results_workflow_orders() if record.id == order_id)
    assert after.result_count == 1
    assert after.completed_result_count == 1


def test_an_empty_observation_does_not_hold_an_order_back(tmp_path):
    database = Database(tmp_path / "lims.db")
    database.initialize()
    patient_id = _patient(database)
    glucose_id = _test(database, "GLU", "Glucosa", "text")
    note_id = _test(database, "OBS", "Observaciones", "observation")
    order_id = _order(
        database,
        patient_id,
        [
            {"item_type": "test", "test_id": glucose_id, "label": "Glucosa", "source": ""},
            {"item_type": "test", "test_id": note_id, "label": "Observaciones", "source": ""},
        ],
    )

    glucose_entry = next(
        entry for entry in database.get_order_result_entries(order_id) if entry.result_kind != "observation"
    )
    database.save_result_entry(glucose_entry.order_test_id, "90", "", None, None, "", "", "text")

    record = next(record for record in database.list_results_workflow_orders() if record.id == order_id)
    assert record.result_count == 2
    # The observation was left blank, and the order still counts as complete.
    assert record.completed_result_count == 2


def test_typed_results_drive_the_in_progress_dot(tmp_path):
    database = Database(tmp_path / "lims.db")
    database.initialize()
    patient_id = _patient(database)
    glucose_id = _test(database, "GLU", "Glucosa", "text")
    urea_id = _test(database, "URE", "Urea", "text")
    order_id = _order(
        database,
        patient_id,
        [
            {"item_type": "test", "test_id": glucose_id, "label": "Glucosa", "source": ""},
            {"item_type": "test", "test_id": urea_id, "label": "Urea", "source": ""},
        ],
    )

    before = next(record for record in database.list_results_workflow_orders() if record.id == order_id)
    assert before.typed_result_count == 0

    entry = next(
        entry for entry in database.get_order_result_entries(order_id) if int(entry.test_id) == glucose_id
    )
    database.save_result_entry(entry.order_test_id, "90", "", None, None, "", "", "text")

    after = next(record for record in database.list_results_workflow_orders() if record.id == order_id)
    # One of two: the dot is yellow, not blue and not grey.
    assert after.typed_result_count == 1
    assert after.completed_result_count < after.result_count
