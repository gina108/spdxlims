from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.models import TestCatalog as CatalogModel
from app.routers.orders import OrderCreateIn, OrderItemIn, _normalize_order_items, _parse_provider_id


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
