from __future__ import annotations
import json
import re
import shutil
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class HelpersMixin:
    def _save_test_reference_ranges(self, connection: sqlite3.Connection, test_id: int, reference_ranges: list[dict[str, Any]]) -> None:
        for reference in reference_ranges:
            connection.execute(
                "INSERT INTO test_reference_ranges (test_id, sex, age_min_days, age_max_days, lower_value, upper_value, lower_value_text, upper_value_text, unit, reference_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    test_id,
                    reference.get("sex") or None,
                    reference.get("age_min_days"),
                    reference.get("age_max_days"),
                    self._decimal_to_float(reference.get("lower_value")),
                    self._decimal_to_float(reference.get("upper_value")),
                    reference.get("lower_value"),
                    reference.get("upper_value"),
                    reference.get("unit") or "",
                    reference.get("reference_text") or None,
                ),
            )

    def _save_panel_items(self, connection: sqlite3.Connection, panel_id: int, panel_items: list[dict[str, Any]]) -> None:
        seen_test_ids: set[int] = set()
        sort_index = 0
        for item in panel_items:
            item_type = item.get("item_type", "test")
            if item_type in {"heading", "comment"}:
                heading_text = (item.get("heading_text") or item.get("label") or "").strip()
                if not heading_text:
                    continue
                connection.execute(
                    "INSERT INTO test_panel_items (panel_id, test_id, item_type, heading_text, sort_order) VALUES (?, NULL, ?, ?, ?)",
                    (panel_id, item_type, heading_text, sort_index),
                )
                sort_index += 1
                continue
            test_id = item.get("test_id")
            if test_id is None or int(test_id) in seen_test_ids:
                continue
            seen_test_ids.add(int(test_id))
            connection.execute(
                "INSERT INTO test_panel_items (panel_id, test_id, item_type, heading_text, sort_order) VALUES (?, ?, 'test', NULL, ?)",
                (panel_id, int(test_id), sort_index),
            )
            sort_index += 1

    def _copy_asset(self, raw_path: str, stem: str) -> str:
        if not raw_path:
            return ""
        source = Path(raw_path)
        if not source.exists():
            return raw_path
        target = self.assets_dir / f"{stem}{source.suffix.lower()}"
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return str(target)

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
        try:
            parsed = int(str(value))
        except (TypeError, ValueError):
            return fallback
        return max(minimum, min(maximum, parsed))

    def _copy_report_branding_asset(self, raw_path: str, kind: str) -> str:
        if not raw_path:
            return ""
        source = Path(raw_path)
        if not source.exists():
            return raw_path
        normalized_stem = ''.join(char.lower() if char.isalnum() else '_' for char in source.stem).strip('_') or kind
        suffix = source.suffix.lower()
        target = self.assets_dir / f"report_{kind}_{normalized_stem}{suffix}"
        if source.resolve() == target.resolve():
            return str(target)
        counter = 2
        while target.exists():
            try:
                if source.read_bytes() == target.read_bytes():
                    return str(target)
            except OSError:
                pass
            target = self.assets_dir / f"report_{kind}_{normalized_stem}_{counter}{suffix}"
            counter += 1
        shutil.copy2(source, target)
        return str(target)

    @staticmethod
    def _normalize_report_branding_paths(raw_value: Any, fallback: str = "") -> list[str]:
        paths: list[str] = []
        if isinstance(raw_value, list):
            for item in raw_value:
                candidate = str(item or '').strip()
                if candidate and candidate not in paths:
                    paths.append(candidate)
        fallback_value = fallback.strip()
        if fallback_value and fallback_value not in paths:
            paths.insert(0, fallback_value)
        return paths

    @staticmethod
    def _normalize_instrument_key(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    @classmethod
    def _normalize_optional_instrument_key(cls, value: str) -> str | None:
        normalized = cls._normalize_instrument_key(value)
        return normalized or None

    @staticmethod
    def _normalize_instrument_code(value: str) -> str:
        return "".join(character for character in str(value or "").upper().strip() if character.isalnum() or character in {"-", "_", "%", "#"})

    def _get_or_create_category(self, connection: sqlite3.Connection, category_name: str) -> int | None:
        normalized = category_name.strip()
        if not normalized:
            return None
        row = connection.execute("SELECT id FROM test_categories WHERE name = ?", (normalized,)).fetchone()
        if row:
            return int(row["id"])
        cursor = connection.execute("INSERT INTO test_categories (name) VALUES (?)", (normalized,))
        return int(cursor.lastrowid)

    @staticmethod
    def _normalize_optional_text(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _serialize_select_options(options: Any) -> str | None:
        if isinstance(options, str):
            try:
                parsed = json.loads(options)
            except json.JSONDecodeError:
                parsed = [line.strip() for line in options.splitlines() if line.strip()]
            else:
                options = parsed
        if not isinstance(options, list):
            return None
        normalized = [str(option).strip() for option in options if str(option).strip()]
        return json.dumps(normalized, ensure_ascii=True) if normalized else None

    @staticmethod
    def deserialize_select_options(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return [line.strip() for line in raw_value.splitlines() if line.strip()]
        if not isinstance(parsed, list):
            return []
        return [str(option).strip() for option in parsed if str(option).strip()]

    def _ensure_panel_heading_test(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT id FROM tests WHERE code = '__PANEL_HEADING__'").fetchone()
        if row is not None:
            return int(row["id"])
        cursor = connection.execute("INSERT INTO tests (code, name, category_id, specimen_type, method, result_kind, is_active, sort_order) VALUES ('__PANEL_HEADING__', 'Panel Heading', NULL, NULL, NULL, 'text', 0, 0)")
        return int(cursor.lastrowid)

    def _ensure_panel_comment_test(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT id FROM tests WHERE code = '__PANEL_COMMENT__'").fetchone()
        if row is not None:
            return int(row["id"])
        cursor = connection.execute("INSERT INTO tests (code, name, category_id, specimen_type, method, result_kind, is_active, sort_order) VALUES ('__PANEL_COMMENT__', 'Panel Comment', NULL, NULL, NULL, 'text', 0, 0)")
        return int(cursor.lastrowid)

    def _ensure_urinalysis_strip_tests(self, connection: sqlite3.Connection) -> None:
        category_id = self._get_or_create_category(connection, "Urinalysis")
        for code, name, _category, specimen_type, method, result_kind, unit in self.URINALYSIS_STRIP_TESTS:
            row = connection.execute("SELECT id FROM tests WHERE code = ?", (code,)).fetchone()
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO tests (
                        code, name, category_id, specimen_type, method, result_kind,
                        select_options, default_result_value, price, is_active
                    )
                    VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0, 1)
                    """,
                    (code, name, category_id, specimen_type, method, result_kind),
                )
                test_id = int(cursor.lastrowid)
            else:
                test_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE tests
                    SET category_id = COALESCE(category_id, ?),
                        specimen_type = COALESCE(NULLIF(specimen_type, ''), ?),
                        method = COALESCE(NULLIF(method, ''), ?),
                        result_kind = CASE WHEN result_kind IN ('numeric', 'text', 'select') THEN result_kind ELSE ? END,
                        is_active = 1
                    WHERE id = ?
                    """,
                    (category_id, specimen_type, method, result_kind, test_id),
                )
            if unit:
                existing_range = connection.execute(
                    "SELECT id FROM test_reference_ranges WHERE test_id = ? AND unit = ?",
                    (test_id, unit),
                ).fetchone()
                if existing_range is None:
                    connection.execute(
                        """
                        INSERT INTO test_reference_ranges (
                            test_id, sex, age_min_days, age_max_days,
                            lower_value, upper_value, lower_value_text,
                            upper_value_text, unit, reference_text
                        )
                        VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, '')
                        """,
                        (test_id, unit),
                    )

    @staticmethod
    def _specimen_code(specimen_type: str) -> str:
        normalized = ''.join(character for character in specimen_type.upper() if character.isalnum() or character == ' ')
        mapping = {
            'SERUM': 'SER',
            'PLASMA': 'PLA',
            'WHOLE BLOOD': 'WBL',
            'BLOOD': 'BLD',
            'URINE': 'URI',
            'SWAB': 'SWB',
            'STOOL': 'STL',
        }
        if normalized in mapping:
            return mapping[normalized]
        parts = [part for part in normalized.split() if part]
        if not parts:
            return 'SPC'
        if len(parts) == 1:
            return parts[0][:3]
        return ''.join(part[0] for part in parts)[:4]

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        normalized = str(value).strip().replace(",", "")
        if not normalized:
            return None
        try:
            return Decimal(normalized)
        except InvalidOperation:
            return None

    @classmethod
    def _decimal_to_float(cls, value: Any) -> float | None:
        decimal_value = cls._to_decimal(value)
        return float(decimal_value) if decimal_value is not None else None

    @staticmethod
    def _format_patient_label(first_name: str, last_name: str, middle_name: str | None, age_value: int | None, age_unit: str | None) -> str:
        full_name = " ".join(part for part in [first_name, last_name, middle_name or ""] if part).strip()
        age_part = f' - {age_value} {age_unit}' if age_value is not None and age_unit else ''
        return f'{full_name}{age_part}'
