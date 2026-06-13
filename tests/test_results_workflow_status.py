from spdxlims.database import Database


def test_results_workflow_marks_order_ready_when_all_results_have_values(tmp_path):
    database = Database(tmp_path / "lims.db")
    database.initialize()
    patient_id = database.create_patient(
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
    database.create_test(
        {
            "code": "GLU",
            "name": "Glucosa",
            "category_name": "Chemistry",
            "specimen_type": "Suero",
            "method": "",
            "result_kind": "text",
            "select_options": [],
            "default_result_value": "",
            "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code("GLU")
    assert test_id is not None
    order_id = database.create_order(
        None,
        None,
        None,
        patient_id,
        None,
        None,
        [{"item_type": "test", "test_id": test_id, "label": "Glucosa", "source": ""}],
        "draft",
        "",
    )

    before = next(record for record in database.list_results_workflow_orders() if record.id == order_id)
    assert before.result_count == 1
    assert before.completed_result_count == 0

    entry = database.get_order_result_entries(order_id)[0]
    database.save_result_entry(entry.order_test_id, "90", "", None, None, "", "", "text")

    after = next(record for record in database.list_results_workflow_orders() if record.id == order_id)
    assert after.result_count == 1
    assert after.completed_result_count == 1
