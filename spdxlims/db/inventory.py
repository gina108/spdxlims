from __future__ import annotations
import sqlite3
from typing import Any

from spdxlims.db.records import InventoryItemRecord, SupplierRecord, InventoryMovementRecord


class InventoryMixin:
    def list_inventory_items(self) -> list[InventoryItemRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, sku, name, unit, on_hand, reorder_level, unit_cost FROM inventory_items ORDER BY name, sku"
            ).fetchall()
        return [InventoryItemRecord(**dict(row)) for row in rows]

    def list_inventory_item_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id, sku, name FROM inventory_items ORDER BY name, sku").fetchall()
        return [(row["id"], f'{row["name"]} ({row["sku"]})') for row in rows]

    def create_inventory_item(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO inventory_items (sku, name, unit, on_hand, reorder_level, unit_cost, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))",
                (
                    payload["sku"].strip(),
                    payload["name"].strip(),
                    payload.get("unit") or None,
                    payload.get("on_hand") or 0,
                    payload.get("reorder_level") or 0,
                    payload.get("unit_cost") or 0,
                ),
            )
            return int(cursor.lastrowid)

    def get_inventory_item(self, item_id: int) -> InventoryItemRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, sku, name, unit, on_hand, reorder_level, unit_cost FROM inventory_items WHERE id = ?",
                (int(item_id),),
            ).fetchone()
        return InventoryItemRecord(**dict(row)) if row is not None else None

    def update_inventory_item(self, item_id: int, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE inventory_items SET sku = ?, name = ?, unit = ?, on_hand = ?, reorder_level = ?, unit_cost = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (
                    payload["sku"].strip(),
                    payload["name"].strip(),
                    payload.get("unit") or None,
                    payload.get("on_hand") or 0,
                    payload.get("reorder_level") or 0,
                    payload.get("unit_cost") or 0,
                    int(item_id),
                ),
            )

    def inventory_item_has_movements(self, item_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM inventory_movements WHERE inventory_item_id = ? LIMIT 1",
                (int(item_id),),
            ).fetchone()
        return row is not None

    def delete_inventory_item(self, item_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM inventory_items WHERE id = ?", (int(item_id),))

    def list_suppliers(self) -> list[SupplierRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id, name, phone, email, tax_id FROM suppliers ORDER BY name, id").fetchall()
        return [SupplierRecord(**dict(row)) for row in rows]

    def list_supplier_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id, name, tax_id FROM suppliers ORDER BY name, id").fetchall()
        return [(row["id"], row["name"] if not row["tax_id"] else f'{row["name"]} ({row["tax_id"]})') for row in rows]

    def create_supplier(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO suppliers (name, phone, email, tax_id, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))",
                (payload["name"].strip(), payload.get("phone") or None, payload.get("email") or None, payload.get("tax_id") or None),
            )
            return int(cursor.lastrowid)

    def get_supplier(self, supplier_id: int) -> SupplierRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, name, phone, email, tax_id FROM suppliers WHERE id = ?",
                (int(supplier_id),),
            ).fetchone()
        return SupplierRecord(**dict(row)) if row is not None else None

    def update_supplier(self, supplier_id: int, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE suppliers SET name = ?, phone = ?, email = ?, tax_id = ? WHERE id = ?",
                (
                    payload["name"].strip(),
                    payload.get("phone") or None,
                    payload.get("email") or None,
                    payload.get("tax_id") or None,
                    int(supplier_id),
                ),
            )

    def supplier_has_movements(self, supplier_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM inventory_movements WHERE supplier_id = ? LIMIT 1",
                (int(supplier_id),),
            ).fetchone()
        return row is not None

    def delete_supplier(self, supplier_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM suppliers WHERE id = ?", (int(supplier_id),))

    def list_inventory_movements(self) -> list[InventoryMovementRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.id, m.inventory_item_id, ii.name AS inventory_name, s.name AS supplier_name,
                       m.movement_type, m.quantity, m.unit_cost, m.movement_date, m.notes
                FROM inventory_movements m
                INNER JOIN inventory_items ii ON ii.id = m.inventory_item_id
                LEFT JOIN suppliers s ON s.id = m.supplier_id
                ORDER BY m.movement_date DESC, m.id DESC
                """
            ).fetchall()
        return [InventoryMovementRecord(**dict(row)) for row in rows]

    def create_inventory_movement(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            quantity = float(payload.get("quantity") or 0)
            movement_type = payload.get("movement_type") or "purchase"
            signed_quantity = quantity if movement_type in {"purchase", "adjustment_in"} else -abs(quantity)
            cursor = connection.execute(
                "INSERT INTO inventory_movements (inventory_item_id, supplier_id, movement_type, quantity, unit_cost, movement_date, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))",
                (
                    payload["inventory_item_id"],
                    payload.get("supplier_id"),
                    movement_type,
                    signed_quantity,
                    payload.get("unit_cost") or 0,
                    payload["movement_date"].strip(),
                    payload.get("notes") or None,
                ),
            )
            connection.execute(
                "UPDATE inventory_items SET on_hand = on_hand + ?, unit_cost = CASE WHEN ? > 0 THEN ? ELSE unit_cost END, updated_at = datetime('now','localtime') WHERE id = ?",
                (signed_quantity, payload.get("unit_cost") or 0, payload.get("unit_cost") or 0, payload["inventory_item_id"]),
            )
            return int(cursor.lastrowid)
