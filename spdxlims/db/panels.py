from __future__ import annotations
import sqlite3
from typing import Any

from spdxlims.db.records import PanelRecord, PanelItemRecord


class PanelsMixin:
    def list_panels(self, *, status_filter: str = "active") -> list[PanelRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT tp.id, tp.code, tp.name, tp.specimen_type, tp.method, tp.is_active, tp.price, GROUP_CONCAT(CASE WHEN tpi.item_type = 'test' THEN t.name ELSE tpi.heading_text END, ', ') AS test_names FROM test_panels tp LEFT JOIN test_panel_items tpi ON tpi.panel_id = tp.id LEFT JOIN tests t ON t.id = tpi.test_id AND tpi.item_type = 'test' WHERE (? = 'all' OR (? = 'active' AND tp.is_active = 1) OR (? = 'archived' AND tp.is_active = 0)) GROUP BY tp.id, tp.code, tp.name, tp.specimen_type, tp.method, tp.is_active, tp.price ORDER BY tp.is_active DESC, tp.name", (status_filter, status_filter, status_filter)).fetchall()
        return [PanelRecord(**dict(row)) for row in rows]

    def list_panel_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT tp.id, tp.code, tp.name, SUM(CASE WHEN tpi.item_type = 'test' THEN 1 ELSE 0 END) AS item_count FROM test_panels tp LEFT JOIN test_panel_items tpi ON tpi.panel_id = tp.id WHERE tp.is_active = 1 GROUP BY tp.id, tp.code, tp.name ORDER BY tp.name").fetchall()
        return [(row["id"], f'{row["code"]} - {row["name"]}') for row in rows]

    def get_panel_tests(self, panel_id: int) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT t.id, t.name, t.code FROM test_panel_items tpi INNER JOIN tests t ON t.id = tpi.test_id WHERE tpi.panel_id = ? AND tpi.item_type = 'test' ORDER BY tpi.sort_order, t.name", (panel_id,)).fetchall()
        return [(row["id"], f'{row["name"]} ({row["code"]})') for row in rows]

    def get_panel_order_items(self, panel_id: int) -> list[PanelItemRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT tpi.item_type, tpi.test_id, tpi.heading_text, tpi.sort_order, CASE WHEN tpi.item_type = 'test' THEN t.name || ' (' || t.code || ')' ELSE tpi.heading_text END AS label FROM test_panel_items tpi LEFT JOIN tests t ON t.id = tpi.test_id WHERE tpi.panel_id = ? ORDER BY tpi.sort_order, tpi.id", (panel_id,)).fetchall()
        return [PanelItemRecord(**dict(row)) for row in rows]

    def get_panel_detail(self, panel_id: int, *, include_inactive: bool = False) -> dict[str, Any] | None:
        with self.connect() as connection:
            if include_inactive:
                row = connection.execute("SELECT id, code, name, specimen_type, method, is_active FROM test_panels WHERE id = ?", (panel_id,)).fetchone()
            else:
                row = connection.execute("SELECT id, code, name, specimen_type, method, is_active FROM test_panels WHERE id = ? AND is_active = 1", (panel_id,)).fetchone()
            if row is None:
                return None
            item_rows = connection.execute("SELECT tpi.item_type, tpi.test_id, t.code AS test_code, tpi.heading_text, tpi.sort_order, CASE WHEN tpi.item_type = 'test' THEN t.name || ' (' || t.code || ')' ELSE tpi.heading_text END AS label FROM test_panel_items tpi LEFT JOIN tests t ON t.id = tpi.test_id WHERE tpi.panel_id = ? ORDER BY tpi.sort_order, tpi.id", (panel_id,)).fetchall()
        return {
            **dict(row),
            "items": [dict(item_row) for item_row in item_rows],
        }

    def get_panel_id_by_code(self, code: str) -> int | None:
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM test_panels WHERE code = ? AND is_active = 1", (code.strip(),)).fetchone()
        return int(row["id"]) if row is not None else None

    def get_panel_report_metadata_by_name(self) -> dict[str, dict[str, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT name, specimen_type, method FROM test_panels WHERE is_active = 1").fetchall()
        return {
            str(row["name"] or "").strip(): {
                "specimen_type": str(row["specimen_type"] or "").strip(),
                "method": str(row["method"] or "").strip(),
            }
            for row in rows
            if str(row["name"] or "").strip()
        }

    def create_panel(self, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str = "", method: str = "") -> None:
        with self.connect() as connection:
            cursor = connection.execute("INSERT INTO test_panels (code, name, specimen_type, method, is_active) VALUES (?, ?, ?, ?, 1)", (code.strip(), name.strip(), specimen_type.strip() or None, method.strip() or None))
            panel_id = int(cursor.lastrowid)
            self._save_panel_items(connection, panel_id, panel_items)

    def update_panel(self, panel_id: int, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str = "", method: str = "") -> None:
        with self.connect() as connection:
            connection.execute("UPDATE test_panels SET code = ?, name = ?, specimen_type = ?, method = ?, is_active = 1 WHERE id = ?", (code.strip(), name.strip(), specimen_type.strip() or None, method.strip() or None, panel_id))
            connection.execute("DELETE FROM test_panel_items WHERE panel_id = ?", (panel_id,))
            self._save_panel_items(connection, panel_id, panel_items)

    def apply_panel_default_prices(self, entries: dict[int, float]) -> int:
        updated_count = 0
        with self.connect() as connection:
            for panel_id, price in entries.items():
                cursor = connection.execute(
                    "UPDATE test_panels SET price = ? WHERE id = ?",
                    (float(price), int(panel_id)),
                )
                updated_count += int(cursor.rowcount or 0)
        return updated_count

    def list_client_panel_price_overrides(self) -> dict[tuple[int, int], float]:
        with self.connect() as connection:
            rows = connection.execute("SELECT client_id, panel_id, price FROM client_panel_prices").fetchall()
        return {(int(row["client_id"]), int(row["panel_id"])): float(row["price"]) for row in rows}

    def apply_client_panel_price_overrides(self, entries: dict[tuple[int, int], float | None]) -> tuple[int, int]:
        updated_count = 0
        cleared_count = 0
        with self.connect() as connection:
            for (client_id, panel_id), price in entries.items():
                if price is None:
                    cursor = connection.execute(
                        "DELETE FROM client_panel_prices WHERE client_id = ? AND panel_id = ?",
                        (int(client_id), int(panel_id)),
                    )
                    cleared_count += int(cursor.rowcount or 0)
                    continue
                connection.execute(
                    """
                    INSERT INTO client_panel_prices (client_id, panel_id, price, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(client_id, panel_id)
                    DO UPDATE SET price = excluded.price, updated_at = CURRENT_TIMESTAMP
                    """,
                    (int(client_id), int(panel_id), float(price)),
                )
                updated_count += 1
        return updated_count, cleared_count

    def archive_panel(self, panel_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE test_panels SET is_active = 0 WHERE id = ?", (panel_id,))

    def unarchive_panel(self, panel_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE test_panels SET is_active = 1 WHERE id = ?", (panel_id,))
