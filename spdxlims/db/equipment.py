from __future__ import annotations
import sqlite3
from typing import Any

from spdxlims.db.records import EquipmentRecord


class EquipmentMixin:
    def list_equipment(self) -> list[EquipmentRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, equipment_type, manufacturer, model, serial_number, location, status,
                       last_maintenance_date, next_maintenance_date, notes
                FROM equipment
                ORDER BY
                    CASE status
                        WHEN 'out_of_service' THEN 0
                        WHEN 'maintenance' THEN 1
                        WHEN 'active' THEN 2
                        ELSE 3
                    END,
                    name,
                    id
                """
            ).fetchall()
        return [EquipmentRecord(**dict(row)) for row in rows]

    def create_equipment(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO equipment (
                    name, equipment_type, manufacturer, model, serial_number, location, status,
                    last_maintenance_date, next_maintenance_date, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["name"].strip(),
                    self._normalize_optional_text(payload.get("equipment_type")),
                    self._normalize_optional_text(payload.get("manufacturer")),
                    self._normalize_optional_text(payload.get("model")),
                    self._normalize_optional_text(payload.get("serial_number")),
                    self._normalize_optional_text(payload.get("location")),
                    payload.get("status") or "active",
                    self._normalize_optional_text(payload.get("last_maintenance_date")),
                    self._normalize_optional_text(payload.get("next_maintenance_date")),
                    self._normalize_optional_text(payload.get("notes")),
                ),
            )
            return int(cursor.lastrowid)

    def update_equipment(self, equipment_id: int, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE equipment
                SET name = ?,
                    equipment_type = ?,
                    manufacturer = ?,
                    model = ?,
                    serial_number = ?,
                    location = ?,
                    status = ?,
                    last_maintenance_date = ?,
                    next_maintenance_date = ?,
                    notes = ?,
                    updated_at = datetime('now','localtime')
                WHERE id = ?
                """,
                (
                    payload["name"].strip(),
                    self._normalize_optional_text(payload.get("equipment_type")),
                    self._normalize_optional_text(payload.get("manufacturer")),
                    self._normalize_optional_text(payload.get("model")),
                    self._normalize_optional_text(payload.get("serial_number")),
                    self._normalize_optional_text(payload.get("location")),
                    payload.get("status") or "active",
                    self._normalize_optional_text(payload.get("last_maintenance_date")),
                    self._normalize_optional_text(payload.get("next_maintenance_date")),
                    self._normalize_optional_text(payload.get("notes")),
                    int(equipment_id),
                ),
            )

    def delete_equipment(self, equipment_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM equipment WHERE id = ?", (int(equipment_id),))
