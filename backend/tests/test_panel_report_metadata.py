"""The methodology line a report prints under each study.

Local mode has always emitted it (spdxlims/db/results.py append_panel_meta);
the server produced no such row, so the same order rendered through the backend
lost the line entirely. These pin the shape and the placement.
"""

from __future__ import annotations

import pytest

from app.routers.common import _panel_meta_row, inject_panel_title_rows

META = {
    "glucosa": {"specimen_type": "Suero", "method": "Quimicaliquida"},
    "biometria hematica": {"specimen_type": "Sangre Total", "method": "Citometria de flujo"},
    "solo muestra": {"specimen_type": "Orina", "method": ""},
}


def _test_row(label: str, name: str) -> dict:
    return {"item_type": "test", "source_label": label, "display_name": name, "test_name": name}


def _kinds(rows: list[dict]) -> list[str]:
    return [str(row.get("item_type") or "test") for row in rows]


def test_the_line_reads_the_way_the_printed_report_does():
    row = _panel_meta_row("GLUCOSA", META)
    assert row["comments"] == "Metodología: Quimicaliquida | Tipo de Muestra: Suero"
    assert row["item_type"] == "panel_meta"


def test_a_panel_with_no_metadata_produces_no_row():
    assert _panel_meta_row("GLUCOSA", {}) is None


def test_a_panel_with_only_one_value_still_prints():
    row = _panel_meta_row("SOLO MUESTRA", META)
    assert row is not None
    assert "Tipo de Muestra: Orina" in row["comments"]


def test_the_line_closes_the_panel_rather_than_opening_it():
    """Local mode emits it after the panel's rows; the reference report shows
    it under the analyte, not under the heading."""
    rows = inject_panel_title_rows([_test_row("GLUCOSA", "Glucosa sérica")], META)
    assert _kinds(rows) == ["heading", "test", "panel_meta"]
    assert rows[0]["display_name"] == "GLUCOSA"


def test_each_panel_gets_its_own_line_in_order():
    rows = inject_panel_title_rows(
        [
            _test_row("GLUCOSA", "Glucosa sérica"),
            _test_row("BIOMETRIA HEMATICA", "Leucocitos"),
        ],
        META,
    )
    assert _kinds(rows) == ["heading", "test", "panel_meta", "heading", "test", "panel_meta"]
    assert "Quimicaliquida" in rows[2]["comments"]
    assert "Citometria de flujo" in rows[5]["comments"]


def test_a_panel_without_metadata_is_skipped_but_others_are_not():
    rows = inject_panel_title_rows(
        [
            _test_row("SIN DATOS", "Algo"),
            _test_row("GLUCOSA", "Glucosa sérica"),
        ],
        META,
    )
    assert _kinds(rows) == ["heading", "test", "heading", "test", "panel_meta"]


def test_no_metadata_at_all_leaves_the_old_behaviour_untouched():
    """The result-entry list calls this without metadata and must not change."""
    rows = inject_panel_title_rows([_test_row("GLUCOSA", "Glucosa sérica")])
    assert _kinds(rows) == ["heading", "test"]


def test_label_matching_ignores_case_and_the_code_suffix():
    rows = inject_panel_title_rows([_test_row("Glucosa (GLU) - 1 tests", "Glucosa sérica")], META)
    assert "panel_meta" in _kinds(rows)


@pytest.mark.parametrize("label", ["", "   "])
def test_rows_with_no_panel_label_get_nothing(label):
    rows = inject_panel_title_rows([_test_row(label, "Suelto")], META)
    assert _kinds(rows) == ["test"]
