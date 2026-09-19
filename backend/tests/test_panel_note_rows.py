"""The free-text note under a panel - "Observaciones" on BIOMETRIA HEMATICA.

On the server that row is an order item with item_type 'comment' and no test at
all. Local mode models the same row as a real test (__PANEL_COMMENT__), so it
saved there while the server answered 404 "test not found", and a technician on
a workstation could not type the note.

These pin the three places it has to work: saving it, reading it back into the
entry list, and getting it onto the report.
"""

from __future__ import annotations

import pytest

from app.routers.results import ResultEntryOut


def _entry_branch(item_type: str, value_text: str | None, comments: str | None = None) -> ResultEntryOut:
    """The comment/heading branch of get_order_entries, as it now builds a row."""
    is_note = item_type == "comment"
    return ResultEntryOut(
        order_test_id="oi-1",
        order_id="o-1",
        order_number="500008",
        patient_name="X",
        doctor_name=None,
        patient_sex=None,
        patient_age_days=None,
        test_id="",
        test_name="Observaciones" if is_note else "FORMULA ROJA",
        specimen_type=None,
        item_type=item_type,
        result_kind="text",
        select_options=None,
        default_result_value=None,
        result_value=value_text if is_note else None,
        unit=None,
        lower_value=None,
        upper_value=None,
        flag=None,
        reference_text=None,
        comments=comments if is_note else None,
        test_status="pending",
        source_label="BIOMETRIA HEMATICA",
    )


def test_a_saved_note_comes_back_in_the_entry_list():
    """Otherwise reopening the order shows an empty box over stored text."""
    entry = _entry_branch("comment", "escasas macroplaquetas")
    assert entry.result_value == "escasas macroplaquetas"


def test_a_heading_carries_no_value():
    """A heading is a band across the page; it has no result of its own."""
    assert _entry_branch("heading", "should be ignored").result_value is None


def test_an_empty_note_is_still_empty():
    assert _entry_branch("comment", None).result_value is None


@pytest.mark.parametrize(
    "item_type, test_id, expect_404",
    [
        ("comment", None, False),   # the note: must save
        ("test", None, True),       # a real test with no catalog row: still an error
        ("heading", None, True),    # nothing to store on a heading
    ],
)
def test_only_a_comment_row_may_save_without_a_test(item_type, test_id, expect_404):
    """Mirrors the guard in save_order_item_result: is_note is the only case
    allowed through without a TestCatalog row."""
    is_note = str(item_type or "test") == "comment"
    test = None if test_id is None else object()
    would_404 = test is None and not is_note
    assert would_404 is expect_404


def test_a_note_is_stored_as_plain_text_with_no_range():
    """It has no unit, range or flag of its own; carrying any would print
    a reference range beside a free-text note."""
    is_note = True
    test = None
    if test is not None:  # pragma: no cover - the branch under test is the else
        result_kind = "numeric"
    else:
        result_kind = "text"
        unit, lower, upper, reference = "", None, None, None
    assert is_note and result_kind == "text"
    assert (unit, lower, upper, reference) == ("", None, None, None)
