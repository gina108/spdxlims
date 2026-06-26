from spdxlims.report_layout import _paginate_result_rows, _rebalance_paged_row_groups
from spdxlims.report_layout import _rendered_image_height_mm, _row_page_limit_for_footer
from spdxlims.report_layout import build_report_html
from spdxlims.i18n import tr
from spdxlims.db.results import ResultsMixin


def test_report_header_places_age_above_birthdate() -> None:
    html = build_report_html(
        {
            "patient_age_value": 42,
            "patient_age_unit": "years",
            "patient_dob": "1980-01-01",
            "items": [],
        }
    )

    assert html.index(f">{tr('Age')}:</td>") < html.index(f">{tr('DOB')}:</td>")


def test_report_title_row_shows_right_aligned_page_number() -> None:
    html = build_report_html(
        {
            "items": [
                {
                    "item_type": "test",
                    "test_name": f"Test {index}",
                    "result_value": str(index),
                }
                for index in range(40)
            ],
        }
    )

    assert 'class="results-page-number"' in html
    assert tr("Page {page_number} of {total_pages}", page_number=1, total_pages=2) in html
    assert tr("Page {page_number} of {total_pages}", page_number=2, total_pages=2) in html


def test_report_layout_uses_font_settings() -> None:
    html = build_report_html(
        {
            "report_font_family": "Arial",
            "report_font_size": 11,
            "report_font_bold": True,
            "report_footer_gap_mm": 17,
            "items": [{"item_type": "test", "test_name": "Glucose", "result_value": "1"}],
        }
    )

    assert 'font-family: "Arial", Arial, sans-serif' in html
    assert "font-size: 11px; font-weight: 700;" in html
    assert "padding-bottom: 17mm;" in html


def test_report_layout_can_bold_abnormal_results() -> None:
    html = build_report_html(
        {
            "report_abnormal_bold": True,
            "items": [
                {"item_type": "test", "test_name": "Densidad", "result_value": "1", "flag": "low"},
                {"item_type": "test", "test_name": "Color", "result_value": "Amarillo", "flag": "none"},
            ],
        }
    )

    assert '<tr class="abnormal-result">' in html
    assert ".results-body tr.abnormal-result td { font-weight: 700 !important; }" in html


def test_report_layout_uses_subheading_font_settings() -> None:
    html = build_report_html(
        {
            "report_subheading_font_family": "Times New Roman",
            "report_subheading_font_size": 14,
            "report_subheading_font_bold": False,
            "items": [{"item_type": "heading", "test_name": "Chemistry"}],
        }
    )

    assert 'font-family: "Times New Roman", Arial, sans-serif' in html
    assert "font-weight: 400 !important; color: #223145; font-size: 14px !important;" in html


def test_report_footer_height_reduces_row_budget(tmp_path) -> None:
    from PySide6.QtGui import QImage

    short_footer = tmp_path / "short_footer.png"
    tall_footer = tmp_path / "tall_footer.png"
    QImage(1000, 100, QImage.Format_RGB32).save(str(short_footer))
    QImage(1000, 250, QImage.Format_RGB32).save(str(tall_footer))

    short_limit = _row_page_limit_for_footer(short_footer, has_footer=True, has_general_comments=False)
    tall_limit = _row_page_limit_for_footer(tall_footer, has_footer=True, has_general_comments=False)

    assert tall_limit < short_limit


def test_report_footer_gap_reduces_row_budget(tmp_path) -> None:
    from PySide6.QtGui import QImage

    footer = tmp_path / "footer.png"
    QImage(1000, 100, QImage.Format_RGB32).save(str(footer))

    small_gap = _row_page_limit_for_footer(footer, has_footer=True, has_general_comments=False, footer_gap_mm=4)
    large_gap = _row_page_limit_for_footer(footer, has_footer=True, has_general_comments=False, footer_gap_mm=30)

    assert large_gap < small_gap


def test_rendered_footer_height_uses_page_width(tmp_path) -> None:
    from PySide6.QtGui import QImage

    footer = tmp_path / "footer.png"
    QImage(1000, 250, QImage.Format_RGB32).save(str(footer))

    assert _rendered_image_height_mm(footer, 200.0) == 50.0


def test_report_pagination_keeps_first_page_filled() -> None:
    rows = [(f"<tr><td>{index}</td></tr>", 1.0, "test") for index in range(40)]

    pages = _paginate_result_rows(rows, 28.0)
    balanced = _rebalance_paged_row_groups(pages, 28.0)

    assert [len(page) for page in balanced] == [28, 12]


def test_report_pagination_can_keep_panel_together_when_it_fits() -> None:
    rows = [(f"<tr><td>intro {index}</td></tr>", 1.0, "test") for index in range(3)]
    rows.extend(
        [
            ("<tr><td>Panel A</td></tr>", 1.0, "heading", "Panel A"),
            ("<tr><td>A1</td></tr>", 1.0, "test", "Panel A"),
            ("<tr><td>A2</td></tr>", 1.0, "test", "Panel A"),
            ("<tr><td>A3</td></tr>", 1.0, "test", "Panel A"),
            ("<tr><td>A4</td></tr>", 1.0, "test", "Panel A"),
            ("<tr><td>Meta</td></tr>", 1.0, "panel_meta", "Panel A"),
        ]
    )

    pages = _paginate_result_rows(rows, 7.0, keep_panels_together=True)

    assert [len(page) for page in pages] == [3, 6]


def test_report_pagination_splits_panel_when_it_cannot_fit_on_one_page() -> None:
    rows = [
        ("<tr><td>Panel A</td></tr>", 1.0, "heading", "Panel A"),
        ("<tr><td>A1</td></tr>", 1.0, "test", "Panel A"),
        ("<tr><td>A2</td></tr>", 1.0, "test", "Panel A"),
        ("<tr><td>A3</td></tr>", 1.0, "test", "Panel A"),
    ]

    pages = _paginate_result_rows(rows, 3.0, keep_panels_together=True)

    assert [len(page) for page in pages] == [3, 1]


def test_report_pagination_avoids_orphaned_heading() -> None:
    rows = [(f"<tr><td>{index}</td></tr>", 1.0, "test") for index in range(31)]
    rows.append(("<tr><td>heading</td></tr>", 1.0, "heading"))
    rows.append(("<tr><td>child</td></tr>", 1.0, "test"))

    pages = _paginate_result_rows(rows, 32.0)
    balanced = _rebalance_paged_row_groups(pages, 32.0)

    assert balanced[0][-1][2] == "test"
    assert balanced[1][0][2] == "heading"


def test_report_pagination_avoids_orphaned_panel_metadata() -> None:
    rows = [(f"<tr><td>{index}</td></tr>", 1.0, "test", "Panel A") for index in range(4)]
    rows.append(("<tr><td>Meta</td></tr>", 1.0, "panel_meta", "Panel A"))

    pages = _paginate_result_rows(rows, 4.0)
    balanced = _rebalance_paged_row_groups(pages, 4.0)

    assert [len(page) for page in balanced] == [3, 2]
    assert balanced[1][0][2] == "test"
    assert balanced[1][1][2] == "panel_meta"


def test_short_panel_metadata_fits_with_previous_rows_when_space_is_available(tmp_path) -> None:
    from PySide6.QtGui import QImage

    footer = tmp_path / "footer.png"
    QImage(1222, 250, QImage.Format_RGB32).save(str(footer))
    items = [
        {"item_type": "heading", "test_name": "EXAMEN GENERAL DE ORINA"},
        {"item_type": "heading", "test_name": "EXAMEN DE LAS CARACTERISTICAS FISICAS"},
        *[
            {"item_type": "test", "test_name": f"Analito {index}", "result_value": "Ausente"}
            for index in range(23)
        ],
        {"item_type": "test", "test_name": "Levaduras", "result_value": "Ausentes"},
        {
            "item_type": "panel_meta",
            "comments": "Metodología: Fisicoquimico/Microscopia | Tipo de Muestra: Orina",
        },
    ]
    html = build_report_html(
        {
            "footer_signature_image_path": str(footer),
            "report_footer_gap_mm": 2,
            "report_font_size": 12,
            "items": items,
        }
    )
    first_page_body = html.split('<table class="results-body">', 1)[1].split("</table>", 1)[0]

    assert "Levaduras" in first_page_body
    assert "Metodología" in first_page_body


def test_merge_restores_source_label_for_sub_headings() -> None:
    # Sub-headings (e.g. "EXAMEN DE LAS CARACTERISTICAS FISICAS" inside
    # "EXAMEN GENERAL DE ORINA") lose their source_label when a report is saved
    # because heading rows have no order_test_id and are not matched by the
    # normal merge path.  The fix must re-attach source_label so that all rows
    # belonging to EGO end up in one pagination chunk, preventing the heading
    # and first sub-section from being stranded on a different page.
    saved_items = [
        {"order_test_id": None, "item_type": "heading", "test_name": "EXAMEN GENERAL DE ORINA", "source_label": None},
        {"order_test_id": None, "item_type": "heading", "test_name": "EXAMEN DE LAS CARACTERISTICAS FISICAS", "source_label": None},
        {"order_test_id": "t1", "item_type": "test", "test_name": "Color", "result_value": "Amarillo", "source_label": None},
    ]
    live_items = [
        {"order_test_id": None, "item_type": "heading", "test_name": "EXAMEN GENERAL DE ORINA", "source_label": None},
        {"order_test_id": None, "item_type": "heading", "test_name": "EXAMEN DE LAS CARACTERISTICAS FISICAS", "source_label": "EXAMEN GENERAL DE ORINA"},
        {"order_test_id": "t1", "item_type": "test", "test_name": "Color", "result_value": "Amarillo", "source_label": "EXAMEN GENERAL DE ORINA"},
    ]
    merged = ResultsMixin._merge_saved_result_values_into_live_items(saved_items, live_items)

    ego_heading = merged[0]
    fisicas_heading = merged[1]
    color_test = merged[2]

    # Top-level heading has no source_label in the live data — should stay None
    assert not (ego_heading.get("source_label") or "").strip()
    # Sub-heading must regain its source_label
    assert fisicas_heading["source_label"] == "EXAMEN GENERAL DE ORINA"
    # Test item source_label is restored via the normal order_test_id path
    assert color_test["source_label"] == "EXAMEN GENERAL DE ORINA"


def test_merge_skips_source_label_restore_for_ambiguous_heading_names() -> None:
    # If two live headings share the same name, we cannot safely pick one; skip.
    saved_items = [
        {"order_test_id": None, "item_type": "heading", "test_name": "QUIMICAS", "source_label": None},
    ]
    live_items = [
        {"order_test_id": None, "item_type": "heading", "test_name": "QUIMICAS", "source_label": "PANEL A"},
        {"order_test_id": None, "item_type": "heading", "test_name": "QUIMICAS", "source_label": "PANEL B"},
    ]
    merged = ResultsMixin._merge_saved_result_values_into_live_items(saved_items, live_items)
    assert not (merged[0].get("source_label") or "").strip()


def test_panel_with_sub_headings_stays_together_in_saved_report_layout() -> None:
    # Simulate a saved report where sub-headings have their source_label restored.
    # All EGO rows should share panel_group = "EXAMEN GENERAL DE ORINA" so the
    # pagination keeps them as one chunk and avoids a split.
    ego_items = [
        {"item_type": "heading", "test_name": "EXAMEN GENERAL DE ORINA"},
        {"item_type": "heading", "test_name": "EXAMEN DE LAS CARACTERISTICAS FISICAS", "source_label": "EXAMEN GENERAL DE ORINA"},
        {"item_type": "test", "test_name": "Color", "result_value": "Amarillo", "source_label": "EXAMEN GENERAL DE ORINA"},
        {"item_type": "test", "test_name": "Aspecto", "result_value": "Claro", "source_label": "EXAMEN GENERAL DE ORINA"},
        {"item_type": "test", "test_name": "Densidad", "result_value": "1.005", "source_label": "EXAMEN GENERAL DE ORINA"},
        {"item_type": "heading", "test_name": "EXAMEN DE LAS CARACTERISTICAS QUIMICAS", "source_label": "EXAMEN GENERAL DE ORINA"},
        *[{"item_type": "test", "test_name": f"Quim {i}", "result_value": "Neg", "source_label": "EXAMEN GENERAL DE ORINA"} for i in range(9)],
        {"item_type": "heading", "test_name": "EXAMEN MICROSCOPICO DEL SEDIMENTO URINARIO", "source_label": "EXAMEN GENERAL DE ORINA"},
        *[{"item_type": "test", "test_name": f"Micro {i}", "result_value": "Neg", "source_label": "EXAMEN GENERAL DE ORINA"} for i in range(9)],
        {"item_type": "panel_meta", "comments": "Metodología: Fisicoquimico | Tipo de Muestra: Orina"},
    ]
    # Preceding items that fill ~13 row-units (TP+TT + GLUCOSA + CREATININA proxy)
    preceding = [
        {"item_type": "heading", "test_name": "PANEL PREVIO"},
        *[{"item_type": "test", "test_name": f"Pre {i}", "result_value": "1"} for i in range(11)],
        {"item_type": "panel_meta", "comments": "Met: algo"},
    ]
    html = build_report_html({"items": preceding + ego_items})

    # All of EGO (every sub-heading and test) must appear on the same page.
    pages = html.split("results-page-number")
    ego_page = next((p for p in pages if "EXAMEN GENERAL DE ORINA" in p), None)
    assert ego_page is not None, "EGO heading not found in any page"
    assert "EXAMEN DE LAS CARACTERISTICAS FISICAS" in ego_page
    assert "EXAMEN DE LAS CARACTERISTICAS QUIMICAS" in ego_page
    assert "EXAMEN MICROSCOPICO DEL SEDIMENTO URINARIO" in ego_page
