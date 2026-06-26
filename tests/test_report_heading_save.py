from __future__ import annotations

from spdxlims.database import Database
from spdxlims.report_layout import build_report_html


def test_finalize_report_saves_generated_heading_without_position_lookup(tmp_path):
    database = Database(tmp_path / "lims.db")
    database.initialize()
    patient_id = database.create_patient(
        {
            "first_name": "Maria",
            "last_name": "Garcia",
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
            "code": "CBC-WBC",
            "name": "White Blood Cells",
            "category_name": "Hematology",
            "specimen_type": "Blood",
            "method": "",
            "result_kind": "text",
            "select_options": [],
            "default_result_value": "",
            "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code("CBC-WBC")
    assert test_id is not None
    order_id = database.create_order(
        None,
        None,
        None,
        patient_id,
        None,
        None,
        [{"item_type": "test", "test_id": test_id, "label": "White Blood Cells", "source": "CBC"}],
        "draft",
        "",
    )
    preview = database.get_live_report_preview(order_id)
    assert preview is not None
    preview["items"] = [
        {
            "order_test_id": None,
            "item_type": "heading",
            "test_name": "CBC",
            "result_value": "",
            "unit": "",
            "reference_text": "",
            "lower_value": "",
            "upper_value": "",
            "flag": "",
            "comments": "",
            "sort_order": 0,
        },
        *preview["items"],
    ]

    report_id = database.finalize_report(order_id, preview_override=preview)

    saved = database.get_saved_report_preview(order_id)
    assert report_id > 0
    assert saved is not None
    assert saved["items"][0]["item_type"] == "heading"


def test_live_report_uses_panel_name_subheadings_and_metadata(tmp_path):
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
            "specimen_type": "Serum",
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
    database.create_panel(
        "CHEM",
        "Quimica Clinica",
        [
            {"item_type": "heading", "heading_text": "Metabolitos", "label": "Metabolitos"},
            {"item_type": "test", "test_id": test_id, "label": "Glucosa"},
        ],
        specimen_type="Suero",
        method="Colorimetria",
    )
    panel_id = database.get_panel_id_by_code("CHEM")
    assert panel_id is not None
    panel_items = database.get_panel_order_items(panel_id)
    order_items = [
        {
            "item_type": item.item_type,
            "test_id": item.test_id,
            "label": item.heading_text or item.label,
            "source": "Quimica Clinica",
        }
        for item in panel_items
    ]
    order_id = database.create_order(None, None, None, patient_id, None, None, order_items, "draft", "")

    preview = database.get_live_report_preview(order_id)

    assert preview is not None
    rendered = [(item["item_type"], item["test_name"], item.get("comments") or "") for item in preview["items"]]
    assert rendered[0] == ("heading", "Quimica Clinica", "")
    assert rendered[1] == ("heading", "Metabolitos", "")
    assert rendered[-1][0] == "panel_meta"
    assert "Colorimetria" in rendered[-1][2]
    assert "Suero" in rendered[-1][2]


def test_report_panel_label_strips_choice_count_and_code() -> None:
    assert Database._normalize_report_panel_label("Quimica Clinica (CHEM) - 12 tests") == "Quimica Clinica"


def test_saved_report_preview_refreshes_panel_structure(tmp_path):
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
            "specimen_type": "Serum",
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
    database.create_panel(
        "CHEM",
        "Quimica Clinica",
        [{"item_type": "test", "test_id": test_id, "label": "Glucosa"}],
        specimen_type="Suero",
        method="Colorimetria",
    )
    order_id = database.create_order(
        None,
        None,
        None,
        patient_id,
        None,
        None,
        [{"item_type": "test", "test_id": test_id, "label": "Glucosa", "source": "Quimica Clinica (CHEM) - 1 tests"}],
        "draft",
        "",
    )
    stale_preview = database.get_live_report_preview(order_id)
    assert stale_preview is not None
    stale_preview["items"] = [item for item in stale_preview["items"] if item["item_type"] != "panel_meta"]
    stale_preview["items"][0]["test_name"] = "Quimica Clinica (CHEM) - 1 tests"
    stale_preview["items"] = stale_preview["items"][1:]
    database.finalize_report(order_id, preview_override=stale_preview)

    saved = database.get_saved_report_preview(order_id)

    assert saved is not None
    rendered = [(item["item_type"], item["test_name"], item.get("comments") or "") for item in saved["items"]]
    assert rendered[0] == ("heading", "Quimica Clinica", "")
    assert rendered[-1][0] == "panel_meta"
    assert "Colorimetria" in rendered[-1][2]


def test_saved_report_preview_keeps_manually_edited_subtitle(tmp_path):
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
            "specimen_type": "Serum",
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
    database.create_panel(
        "CHEM",
        "Quimica Clinica",
        [
            {"item_type": "heading", "heading_text": "Metabolitos", "label": "Metabolitos"},
            {"item_type": "test", "test_id": test_id, "label": "Glucosa"},
        ],
        specimen_type="Suero",
        method="Colorimetria",
    )
    panel_id = database.get_panel_id_by_code("CHEM")
    assert panel_id is not None
    order_items = [
        {
            "item_type": item.item_type,
            "test_id": item.test_id,
            "label": item.heading_text or item.label,
            "source": "Quimica Clinica",
        }
        for item in database.get_panel_order_items(panel_id)
    ]
    order_id = database.create_order(None, None, None, patient_id, None, None, order_items, "draft", "")

    preview = database.get_live_report_preview(order_id)
    assert preview is not None
    # Simulate the user editing the sub-heading text in the report editor.
    for item in preview["items"]:
        if item["item_type"] == "heading" and item["test_name"] == "Metabolitos":
            item["test_name"] = "Metabolitos (suero en ayuno)"
    database.finalize_report(order_id, preview_override=preview)

    saved = database.get_saved_report_preview(order_id)

    assert saved is not None
    headings = [item["test_name"] for item in saved["items"] if item["item_type"] == "heading"]
    # The auto-generated panel title still refreshes from the catalog...
    assert "Quimica Clinica" in headings
    # ...but the manually edited sub-heading is preserved on export.
    assert "Metabolitos (suero en ayuno)" in headings
    assert "Metabolitos" not in headings


def test_old_order_recovers_panel_subheading_from_catalog(tmp_path):
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
            "code": "RBC",
            "name": "Eritrocitos",
            "category_name": "Hematology",
            "specimen_type": "Sangre total",
            "method": "",
            "result_kind": "text",
            "select_options": [],
            "default_result_value": "",
            "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code("RBC")
    assert test_id is not None
    database.create_panel(
        "BH",
        "Biometria Hematica",
        [
            {"item_type": "heading", "heading_text": "Serie Roja", "label": "Serie Roja"},
            {"item_type": "test", "test_id": test_id, "label": "Eritrocitos"},
        ],
        specimen_type="Sangre total",
        method="Impedancia",
    )
    order_id = database.create_order(
        None,
        None,
        None,
        patient_id,
        None,
        None,
        [{"item_type": "test", "test_id": test_id, "label": "Eritrocitos", "source": "Biometria Hematica (BH) - 1 tests"}],
        "draft",
        "",
    )

    preview = database.get_live_report_preview(order_id)

    assert preview is not None
    rendered = [(item["item_type"], item["test_name"]) for item in preview["items"]]
    assert ("heading", "Biometria Hematica") in rendered
    assert ("heading", "Serie Roja") in rendered


def test_existing_heading_with_panel_code_uses_panel_name(tmp_path):
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
            "code": "RBC",
            "name": "Eritrocitos",
            "category_name": "Hematology",
            "specimen_type": "Sangre total",
            "method": "",
            "result_kind": "text",
            "select_options": [],
            "default_result_value": "",
            "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code("RBC")
    assert test_id is not None
    database.create_panel(
        "BH",
        "Biometria Hematica",
        [{"item_type": "heading", "heading_text": "Serie Roja", "label": "Serie Roja"}],
    )
    order_id = database.create_order(
        None,
        None,
        None,
        patient_id,
        None,
        None,
        [
            {"item_type": "heading", "label": "Serie Roja", "source": "BH"},
            {"item_type": "test", "test_id": test_id, "label": "Eritrocitos", "source": "BH"},
        ],
        "draft",
        "",
    )

    preview = database.get_live_report_preview(order_id)

    assert preview is not None
    rendered = [(item["item_type"], item["test_name"]) for item in preview["items"]]
    assert ("heading", "Biometria Hematica") in rendered
    assert ("heading", "BH") not in rendered


def test_saved_preview_after_finalize_does_not_duplicate_generated_panel_heading(tmp_path):
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
            "code": "RBC",
            "name": "Eritrocitos",
            "category_name": "Hematology",
            "specimen_type": "Sangre total",
            "method": "",
            "result_kind": "text",
            "select_options": [],
            "default_result_value": "",
            "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code("RBC")
    assert test_id is not None
    database.create_panel(
        "BH",
        "Biometria Hematica",
        [
            {"item_type": "comment", "heading_text": "Observaciones", "label": "Observaciones"},
            {"item_type": "heading", "heading_text": "Formula Roja", "label": "Formula Roja"},
            {"item_type": "test", "test_id": test_id, "label": "Eritrocitos"},
        ],
        specimen_type="Orina",
        method="Fisicoquimico/Microscopia",
    )
    order_id = database.create_order(
        None,
        None,
        None,
        patient_id,
        None,
        None,
        [
            {"item_type": "comment", "label": "Observaciones", "source": "BH"},
            {"item_type": "heading", "label": "Formula Roja", "source": "BIOMETRIA HEMATICA"},
            {"item_type": "test", "test_id": test_id, "label": "Eritrocitos", "source": "BH"},
        ],
        "draft",
        "",
    )
    first_preview = database.get_live_report_preview(order_id)
    assert first_preview is not None
    database.finalize_report(order_id, preview_override=first_preview)

    saved = database.get_saved_report_preview(order_id)

    assert saved is not None
    headings = [item["test_name"] for item in saved["items"] if item["item_type"] == "heading"]
    assert headings.count("Biometria Hematica") == 1
    assert "BH" not in headings


def test_blank_comment_section_is_not_rendered() -> None:
    html = build_report_html(
        {
            "items": [
                {
                    "item_type": "comment",
                    "test_name": "Observaciones",
                    "result_value": "",
                    "comments": "",
                }
            ]
        }
    )

    assert "Observaciones" not in html
