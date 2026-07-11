from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spdxlims.db.records import InventoryItemRecord, InventoryMovementRecord, SupplierRecord
from spdxlims.service_base import ServiceBase


def _f(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _item_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "sku": str(payload.get("sku") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "unit": (str(payload["unit"]).strip() or None) if payload.get("unit") is not None else None,
        "on_hand": _f(payload.get("on_hand")),
        "reorder_level": _f(payload.get("reorder_level")),
        "unit_cost": _f(payload.get("unit_cost")),
    }


def _supplier_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(payload.get("name") or "").strip(),
        "phone": (str(payload["phone"]).strip() or None) if payload.get("phone") is not None else None,
        "email": (str(payload["email"]).strip() or None) if payload.get("email") is not None else None,
        "tax_id": (str(payload["tax_id"]).strip() or None) if payload.get("tax_id") is not None else None,
    }


@dataclass(slots=True)
class InventoryService(ServiceBase):
    """Inventory (stock items, suppliers, movements) over local SQLite or the server API."""

    # ---- items ----
    def list_inventory_items(self) -> list[InventoryItemRecord]:
        if self._is_local():
            return self.database.list_inventory_items()
        payload = self.deployment_service.request_json("GET", "/api/stock/items")
        return [
            InventoryItemRecord(
                id=item.get("id"), sku=item.get("sku") or "", name=item.get("name") or "",
                unit=item.get("unit"), on_hand=_f(item.get("on_hand")),
                reorder_level=_f(item.get("reorder_level")), unit_cost=_f(item.get("unit_cost")),
            )
            for item in (payload or []) if isinstance(item, dict)
        ]

    def list_inventory_item_choices(self) -> list[tuple[Any, str]]:
        if self._is_local():
            return self.database.list_inventory_item_choices()
        payload = self.deployment_service.request_json("GET", "/api/stock/item-choices")
        return [(i.get("id"), str(i.get("label") or "")) for i in (payload or []) if isinstance(i, dict)]

    def create_inventory_item(self, payload: dict[str, Any]) -> Any:
        if self._is_local():
            return self.database.create_inventory_item(payload)
        response = self.deployment_service.request_json("POST", "/api/stock/items", _item_payload(payload))
        return (response or {}).get("id") if isinstance(response, dict) else None

    def update_inventory_item(self, item_id: Any, payload: dict[str, Any]) -> None:
        if self._is_local():
            self.database.update_inventory_item(int(item_id), payload)
            return
        self.deployment_service.request_json("PUT", f"/api/stock/items/{item_id}", _item_payload(payload))

    def inventory_item_has_movements(self, item_id: Any) -> bool:
        if self._is_local():
            return self.database.inventory_item_has_movements(int(item_id))
        response = self.deployment_service.request_json("GET", f"/api/stock/items/{item_id}/has-movements")
        return bool(response.get("has_movements")) if isinstance(response, dict) else False

    def delete_inventory_item(self, item_id: Any) -> None:
        if self._is_local():
            self.database.delete_inventory_item(int(item_id))
            return
        self.deployment_service.request_json("DELETE", f"/api/stock/items/{item_id}")

    # ---- suppliers ----
    def list_suppliers(self) -> list[SupplierRecord]:
        if self._is_local():
            return self.database.list_suppliers()
        payload = self.deployment_service.request_json("GET", "/api/stock/suppliers")
        return [
            SupplierRecord(id=s.get("id"), name=s.get("name") or "", phone=s.get("phone"), email=s.get("email"), tax_id=s.get("tax_id"))
            for s in (payload or []) if isinstance(s, dict)
        ]

    def list_supplier_choices(self) -> list[tuple[Any, str]]:
        if self._is_local():
            return self.database.list_supplier_choices()
        payload = self.deployment_service.request_json("GET", "/api/stock/supplier-choices")
        return [(s.get("id"), str(s.get("label") or "")) for s in (payload or []) if isinstance(s, dict)]

    def create_supplier(self, payload: dict[str, Any]) -> Any:
        if self._is_local():
            return self.database.create_supplier(payload)
        response = self.deployment_service.request_json("POST", "/api/stock/suppliers", _supplier_payload(payload))
        return (response or {}).get("id") if isinstance(response, dict) else None

    def update_supplier(self, supplier_id: Any, payload: dict[str, Any]) -> None:
        if self._is_local():
            self.database.update_supplier(int(supplier_id), payload)
            return
        self.deployment_service.request_json("PUT", f"/api/stock/suppliers/{supplier_id}", _supplier_payload(payload))

    def supplier_has_movements(self, supplier_id: Any) -> bool:
        if self._is_local():
            return self.database.supplier_has_movements(int(supplier_id))
        response = self.deployment_service.request_json("GET", f"/api/stock/suppliers/{supplier_id}/has-movements")
        return bool(response.get("has_movements")) if isinstance(response, dict) else False

    def delete_supplier(self, supplier_id: Any) -> None:
        if self._is_local():
            self.database.delete_supplier(int(supplier_id))
            return
        self.deployment_service.request_json("DELETE", f"/api/stock/suppliers/{supplier_id}")

    # ---- movements ----
    def list_inventory_movements(self) -> list[InventoryMovementRecord]:
        if self._is_local():
            return self.database.list_inventory_movements()
        payload = self.deployment_service.request_json("GET", "/api/stock/movements")
        return [
            InventoryMovementRecord(
                id=m.get("id"), inventory_item_id=m.get("inventory_item_id"),
                inventory_name=m.get("inventory_name") or "", supplier_name=m.get("supplier_name"),
                movement_type=m.get("movement_type") or "", quantity=_f(m.get("quantity")),
                unit_cost=_f(m.get("unit_cost")), movement_date=str(m.get("movement_date") or ""), notes=m.get("notes"),
            )
            for m in (payload or []) if isinstance(m, dict)
        ]

    def create_inventory_movement(self, payload: dict[str, Any]) -> Any:
        if self._is_local():
            return self.database.create_inventory_movement(payload)
        body = {
            "inventory_item_id": str(payload.get("inventory_item_id")),
            "supplier_id": None if payload.get("supplier_id") in (None, "") else str(payload.get("supplier_id")),
            "movement_type": str(payload.get("movement_type") or "purchase"),
            "quantity": _f(payload.get("quantity")),
            "unit_cost": _f(payload.get("unit_cost")),
            "movement_date": str(payload.get("movement_date") or "").strip(),
            "notes": (str(payload["notes"]).strip() or None) if payload.get("notes") is not None else None,
        }
        response = self.deployment_service.request_json("POST", "/api/stock/movements", body)
        return (response or {}).get("id") if isinstance(response, dict) else None
