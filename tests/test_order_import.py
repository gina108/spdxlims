from __future__ import annotations

from spdxlims.pages.orders_page import OrdersPage


class FakeDatabase:
    def list_test_choices(self) -> list[tuple[int, str]]:
        return [(101, "Biometria hematica (BH)")]

    def get_test_id_by_code(self, code: str) -> int | None:
        return {"GLUC": 202}.get(code)

    def get_panel_id_by_code(self, code: str) -> int | None:
        return {"BH": 1}.get(code)


class FakeOrderService:
    def get_panel_order_items(self, panel_id: int) -> list[dict[str, object]]:
        assert panel_id == 1
        return [
            {
                "item_type": "test",
                "test_id": 101,
                "label": "Biometria hematica (BH)",
            }
        ]


def test_order_import_items_accepts_panel_item_dicts() -> None:
    page = OrdersPage.__new__(OrdersPage)
    page.database = FakeDatabase()
    page.order_service = FakeOrderService()

    items, errors = page._order_import_items({"panel_codes": "BH"})

    assert errors == []
    assert items == [
        {
            "item_type": "test",
            "test_id": 101,
            "label": "Biometria hematica (BH)",
            "source": "BH",
            "is_outsourced": 0,
        }
    ]


def test_order_import_normalizes_age_unit_labels() -> None:
    assert OrdersPage._normalize_import_age_unit("Years") == "years"
    assert OrdersPage._normalize_import_age_unit("Months") == "months"
    assert OrdersPage._normalize_import_age_unit("Days") == "days"
    assert OrdersPage._normalize_import_age_unit("años") == "years"
