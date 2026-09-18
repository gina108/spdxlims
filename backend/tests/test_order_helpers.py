from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.models import TestCatalog as CatalogModel
from app.routers.orders import (
    OrderCreateIn,
    OrderItemIn,
    _compute_next_order_number,
    _normalize_order_items,
    _parse_provider_id,
)


class FakeDb:
    def __init__(self, values):
        self.values = values

    def get(self, model, value):
        return self.values.get((model, value))


def test_normalize_order_items_deduplicates_tests_and_preserves_source():
    test_id = uuid4()
    db = FakeDb({(CatalogModel, test_id): CatalogModel(id=test_id, code="CBC", name="CBC", active=True)})
    payload = OrderCreateIn(
        patient_id=str(uuid4()),
        items=[
            OrderItemIn(test_id=str(test_id), source="Panel A"),
            OrderItemIn(test_id=str(test_id), source="Panel A"),
        ],
    )

    result = _normalize_order_items(payload, db)

    assert result == [{"item_type": "test", "test_id": test_id, "label": None, "source": "Panel A"}]


def test_normalize_order_items_keeps_heading_and_comment_items():
    test_id = uuid4()
    db = FakeDb({(CatalogModel, test_id): CatalogModel(id=test_id, code="CBC", name="CBC", active=True)})
    payload = OrderCreateIn(
        patient_id=str(uuid4()),
        items=[
            OrderItemIn(item_type="heading", label="Formula Roja", source="Panel A"),
            OrderItemIn(test_id=str(test_id), source="Panel A"),
            OrderItemIn(item_type="comment", label="Observaciones", source="Panel A"),
            OrderItemIn(item_type="heading", label="  ", source="Panel A"),
        ],
    )

    result = _normalize_order_items(payload, db)

    assert result == [
        {"item_type": "heading", "test_id": None, "label": "Formula Roja", "source": "Panel A"},
        {"item_type": "test", "test_id": test_id, "label": None, "source": "Panel A"},
        {"item_type": "comment", "test_id": None, "label": "Observaciones", "source": "Panel A"},
    ]


def test_normalize_order_items_rejects_missing_or_inactive_tests():
    test_id = uuid4()
    db = FakeDb({(CatalogModel, test_id): CatalogModel(id=test_id, code="OLD", name="Old", active=False)})
    payload = OrderCreateIn(patient_id=str(uuid4()), test_ids=[str(test_id)])

    with pytest.raises(HTTPException) as exc_info:
        _normalize_order_items(payload, db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "test not found"


def test_parse_provider_id_allows_empty_provider():
    assert _parse_provider_id(None, field_name="doctor_id", expected_type="doctor", db=FakeDb({})) is None

# ── Order-number series floor ────────────────────────────────────────────

def test_floor_lifts_the_series_above_the_other_database():
    """The server was about to re-issue numbers the local install already used."""
    existing = ["001910", "001911", "001912"]
    assert _compute_next_order_number(existing, floor=500000) == "500001"


def test_floor_is_ignored_once_the_series_passes_it():
    assert _compute_next_order_number(["500004", "500003"], floor=500000) == "500005"


def test_no_floor_keeps_the_plain_max_plus_one():
    assert _compute_next_order_number(["001910", "001912"], floor=0) == "001913"


def test_empty_database_starts_at_the_floor():
    assert _compute_next_order_number([], floor=500000) == "500001"
    assert _compute_next_order_number([], floor=0) == "000001"


def test_prefixed_numbers_do_not_drag_the_series_up():
    """Only all-digit numbers count, matching the desktop's _next_order_number."""
    assert _compute_next_order_number(["S999999", "001912"], floor=0) == "001913"


def test_non_digit_and_blank_values_are_ignored():
    assert _compute_next_order_number(["", "  ", None, "ABC", "001912"], floor=0) == "001913"


def test_highest_wins_even_when_it_is_not_the_most_recent_row():
    """The old version scanned only the 200 newest rows and understated this."""
    assert _compute_next_order_number(["002012", "000001", "000002"], floor=0) == "002013"
