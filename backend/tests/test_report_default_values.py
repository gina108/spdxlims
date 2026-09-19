"""A test with a catalog default prints that default on the report.

An EGO panel is mostly defaults - Color "Amarillo", Aspecto "Transparente",
Cristales "Ausentes" - which the technician only edits when the sample differs.
The results editor has always shown them, and local mode prints them because its
preview is built from the same entries. The server's preview read the stored
result alone, so those rows were blank on a report reviewed for approval while
the editor showed them filled in.
"""

from __future__ import annotations

import pytest

from app.routers.reports import printed_result_value


def _entry(value_text=None, default=None):
    return {"test_name": "Color", "value_text": value_text, "default_result_value": default}


def test_an_untouched_test_prints_its_catalog_default():
    assert printed_result_value(_entry(default="Amarillo")) == "Amarillo"


def test_a_typed_result_wins_over_the_default():
    assert printed_result_value(_entry(value_text="Ambar", default="Amarillo")) == "Ambar"


@pytest.mark.parametrize("stored", ["", None])
def test_an_empty_result_falls_back_rather_than_printing_nothing(stored):
    assert printed_result_value(_entry(value_text=stored, default="Ausentes")) == "Ausentes"


def test_a_test_with_no_default_is_still_blank_when_nothing_was_entered():
    assert printed_result_value(_entry()) is None
    assert printed_result_value(_entry(value_text="", default="")) in (None, "")
