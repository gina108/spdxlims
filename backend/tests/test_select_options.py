"""Selectable options for a 'select' test.

save_order_item_result called _deserialize_select_options, which was never
defined - present since the initial commit. Saving a result for any select-kind
test (ABO group, and the urinalysis analytes: Bilirrubina, Cetonas, Leucocitos,
Nitritos) raised NameError and reached the client as "internal server error".
"""

from __future__ import annotations

import pytest

from app.routers.results import _deserialize_select_options as parse


def test_the_catalog_format_is_json():
    assert parse('["A", "B", "AB", "O"]') == ["A", "B", "AB", "O"]


def test_a_real_urinalysis_option_set():
    assert parse('["Negativo", "Traza", "1+", "2+", "3+"]') == [
        "Negativo", "Traza", "1+", "2+", "3+",
    ]


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_nothing_configured_means_no_restriction(empty):
    """An empty list lets save_order_item_result accept any value, which is the
    behaviour a test with no configured options needs."""
    assert parse(empty) == []


def test_rows_written_before_the_value_was_json_still_work():
    """Legacy rows hold one option per line; rejecting them would make every
    result for an older select test unsavable."""
    assert parse("Negativo\nPositivo\n") == ["Negativo", "Positivo"]


def test_padding_and_blanks_are_dropped():
    assert parse('["  Positivo  ", "", "   ", "Negativo"]') == ["Positivo", "Negativo"]


def test_a_json_value_that_is_not_a_list_is_ignored():
    assert parse('{"not": "a list"}') == []


def test_unparseable_text_falls_back_to_lines():
    assert parse("just one option") == ["just one option"]


def test_it_matches_the_desktop_implementation():
    """The two must agree, or a result saved locally would be rejected by the
    server and the reverse."""
    import importlib.util
    import sys
    from pathlib import Path

    helpers = Path(__file__).resolve().parents[2] / "spdxlims" / "db" / "helpers.py"
    if not helpers.exists():
        pytest.skip("desktop sources not available")

    # Loaded straight from the file: importing spdxlims.db would pull in Qt,
    # which the backend environment does not have.
    spec = importlib.util.spec_from_file_location("_desktop_helpers", helpers)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_desktop_helpers"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - the helper's own imports are not our concern
        pytest.skip("desktop helpers could not be imported standalone")
    desktop = module.HelpersMixin.deserialize_select_options

    for raw in ('["A", "B"]', None, "", "x\ny", '{"a": 1}', '["  p  ", ""]'):
        assert parse(raw) == desktop(raw), raw
