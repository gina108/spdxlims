from __future__ import annotations
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any

from spdxlims.db.records import TestRecord


class TestsMixin:
    def list_tests(self, *, status_filter: str = "active") -> list[TestRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT t.id, t.code, t.name, tc.name AS category_name, t.specimen_type, t.method, t.result_kind, t.select_options, t.default_result_value, t.price, t.is_active, COUNT(trr.id) AS range_count, t.result_multiplier FROM tests t LEFT JOIN test_categories tc ON tc.id = t.category_id LEFT JOIN test_reference_ranges trr ON trr.test_id = t.id WHERE (? = 'all' OR (? = 'active' AND t.is_active = 1) OR (? = 'archived' AND t.is_active = 0)) GROUP BY t.id, t.code, t.name, tc.name, t.specimen_type, t.method, t.result_kind, t.select_options, t.default_result_value, t.price, t.is_active, t.result_multiplier ORDER BY t.is_active DESC, tc.name IS NULL, tc.name, t.name",
                (status_filter, status_filter, status_filter),
            ).fetchall()
        return [TestRecord(**dict(row)) for row in rows]

    def list_test_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id, code, name FROM tests WHERE is_active = 1 ORDER BY name").fetchall()
        return [(row["id"], f'{row["name"]} ({row["code"]})') for row in rows]

    def list_client_test_price_overrides(self) -> dict[tuple[int, int], float]:
        with self.connect() as connection:
            rows = connection.execute("SELECT client_id, test_id, price FROM client_test_prices").fetchall()
        return {(int(row["client_id"]), int(row["test_id"])): float(row["price"]) for row in rows}

    def apply_client_test_price_overrides(self, entries: dict[tuple[int, int], float | None]) -> tuple[int, int]:
        updated_count = 0
        cleared_count = 0
        with self.connect() as connection:
            for (client_id, test_id), price in entries.items():
                if price is None:
                    cursor = connection.execute(
                        "DELETE FROM client_test_prices WHERE client_id = ? AND test_id = ?",
                        (client_id, test_id),
                    )
                    cleared_count += int(cursor.rowcount or 0)
                    continue
                connection.execute(
                    """
                    INSERT INTO client_test_prices (client_id, test_id, price, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(client_id, test_id)
                    DO UPDATE SET price = excluded.price, updated_at = CURRENT_TIMESTAMP
                    """,
                    (client_id, test_id, float(price)),
                )
                updated_count += 1
        return updated_count, cleared_count

    def get_test_detail(self, test_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT t.id, t.code, t.name, tc.name AS category_name, t.specimen_type, t.method, t.result_kind, t.select_options, t.default_result_value, t.price, t.result_multiplier, t.formula, t.is_active FROM tests t LEFT JOIN test_categories tc ON tc.id = t.category_id WHERE t.id = ?",
                (test_id,),
            ).fetchone()
            if row is None:
                return None
            ranges = connection.execute(
                "SELECT sex, age_min_days, age_max_days, COALESCE(lower_value_text, CAST(lower_value AS TEXT)) AS lower_value, COALESCE(upper_value_text, CAST(upper_value AS TEXT)) AS upper_value, unit, reference_text FROM test_reference_ranges WHERE test_id = ? ORDER BY id",
                (test_id,),
            ).fetchall()
        return {
            **dict(row),
            "reference_ranges": [dict(range_row) for range_row in ranges],
        }

    def get_test_id_by_code(self, code: str) -> int | None:
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM tests WHERE code = ?", (code.strip(),)).fetchone()
        return int(row["id"]) if row is not None else None

    def create_test(self, payload: dict[str, Any], reference_ranges: list[dict[str, Any]]) -> None:
        with self.connect() as connection:
            category_id = self._get_or_create_category(connection, payload.get("category_name", ""))
            cursor = connection.execute(
                "INSERT INTO tests (code, name, category_id, specimen_type, method, result_kind, select_options, default_result_value, price, result_multiplier, formula) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    payload["code"].strip(),
                    payload["name"].strip(),
                    category_id,
                    payload.get("specimen_type") or None,
                    payload.get("method") or None,
                    payload["result_kind"],
                    self._serialize_select_options(payload.get("select_options")),
                    self._normalize_optional_text(payload.get("default_result_value")),
                    float(payload.get("price") or 0),
                    float(payload["result_multiplier"]) if payload.get("result_multiplier") else None,
                    str(payload["formula"]).strip() or None if payload.get("formula") else None,
                ),
            )
            test_id = int(cursor.lastrowid)
            self._save_test_reference_ranges(connection, test_id, reference_ranges)

    def update_test(self, test_id: int, payload: dict[str, Any], reference_ranges: list[dict[str, Any]]) -> None:
        with self.connect() as connection:
            category_id = self._get_or_create_category(connection, payload.get("category_name", ""))
            connection.execute(
                "UPDATE tests SET code = ?, name = ?, category_id = ?, specimen_type = ?, method = ?, result_kind = ?, select_options = ?, default_result_value = ?, result_multiplier = ?, formula = ? WHERE id = ?",
                (
                    payload["code"].strip(),
                    payload["name"].strip(),
                    category_id,
                    payload.get("specimen_type") or None,
                    payload.get("method") or None,
                    payload["result_kind"],
                    self._serialize_select_options(payload.get("select_options")),
                    self._normalize_optional_text(payload.get("default_result_value")),
                    float(payload["result_multiplier"]) if payload.get("result_multiplier") else None,
                    str(payload["formula"]).strip() or None if payload.get("formula") else None,
                    test_id,
                ),
            )
            connection.execute("DELETE FROM test_reference_ranges WHERE test_id = ?", (test_id,))
            self._save_test_reference_ranges(connection, test_id, reference_ranges)

    def archive_test(self, test_id: int) -> None:
        with self.connect() as connection:
            test_row = connection.execute("SELECT code FROM tests WHERE id = ?", (test_id,)).fetchone()
            if test_row is None:
                return
            if str(test_row["code"]).startswith("__PANEL_"):
                raise ValueError("This system test cannot be archived.")
            connection.execute("UPDATE tests SET is_active = 0 WHERE id = ?", (test_id,))

    def unarchive_test(self, test_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE tests SET is_active = 1 WHERE id = ?", (test_id,))
