from __future__ import annotations

from spdxlims.database import Database
from spdxlims.report_layout import build_report_html


def _base_settings_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "lab_name": "SPDX",
        "address": "",
        "phone": "",
        "email": "",
        "logo_path": "",
        "header_image_path": "",
        "footer_signature_image_path": "",
        "report_footer": "",
        "director_name": "",
        "director_license": "",
        "sat_rfc": "",
        "sat_fiscal_regime": "",
        "sat_postal_code": "",
        "sat_certificate_path": "",
        "sat_key_path": "",
        "ui_language": "es",
        "report_flag_style": "text",
        "keep_panels_together": "1",
        "report_font_family": "Arial",
        "report_font_size": "11",
        "report_font_bold": "1",
        "report_abnormal_bold": "1",
        "report_subheading_font_family": "Times New Roman",
        "report_subheading_font_size": "14",
        "report_subheading_font_bold": "0",
        "report_footer_gap_mm": "22",
    }
    payload.update(overrides)
    return payload


def test_report_settings_persist_after_database_reopen(tmp_path) -> None:
    db_path = tmp_path / "lims.db"
    database = Database(db_path)
    database.initialize()
    database.save_lab_settings(_base_settings_payload())

    reopened = Database(db_path)
    reopened.initialize()
    settings = reopened.get_lab_settings()

    assert settings.report_flag_style == "text"
    assert settings.keep_panels_together == 1
    assert settings.report_font_family == "Arial"
    assert settings.report_font_size == 11
    assert settings.report_font_bold == 1
    assert settings.report_abnormal_bold == 1
    assert settings.report_subheading_font_family == "Times New Roman"
    assert settings.report_subheading_font_size == 14
    assert settings.report_subheading_font_bold == 0
    assert settings.report_footer_gap_mm == 22


def test_saved_report_preview_uses_current_report_settings_when_regenerated(tmp_path) -> None:
    database = Database(tmp_path / "lims.db")
    database.initialize()
    patient_id = database.create_patient(
        {
            "first_name": "Regina",
            "last_name": "Cunningham",
            "middle_name": "",
            "sex": "F",
            "date_of_birth": "",
            "age_value": 47,
            "age_unit": "years",
            "phone": "",
        }
    )
    database.create_test(
        {
            "code": "SG",
            "name": "Densidad",
            "category_name": "Urinalysis",
            "specimen_type": "",
            "method": "",
            "result_kind": "numeric",
            "select_options": [],
            "default_result_value": "",
            "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code("SG")
    assert test_id is not None
    order_id = database.create_order(
        None,
        None,
        None,
        patient_id,
        None,
        None,
        [{"item_type": "test", "test_id": test_id, "label": "Densidad", "source": ""}],
        "draft",
        "",
    )
    first_preview = database.get_live_report_preview(order_id)
    assert first_preview is not None
    database.finalize_report(order_id, preview_override=first_preview)

    database.save_lab_settings(_base_settings_payload(report_font_size="10", report_subheading_font_size="15"))

    saved_preview = database.get_saved_report_preview(order_id)
    assert saved_preview is not None
    assert saved_preview["report_font_size"] == 10
    assert saved_preview["report_subheading_font_size"] == 15
    html = build_report_html(saved_preview)
    assert "font-size: 10px;" in html
    assert "font-size: 15px;" in html
