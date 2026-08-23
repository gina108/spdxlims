from __future__ import annotations
import json
import sqlite3
from typing import Any

from spdxlims.db.records import PanelRecord, PanelItemRecord

# How a panel lays out on the report. 'resultado' is the standard
# ESTUDIO/RESULTADO/UNIDAD/REFERENCIA grid every existing panel uses.
PANEL_KIND_RESULTADO = "resultado"
PANEL_KIND_CULTIVO = "cultivo"
PANEL_KIND_FROTIS = "frotis"
PANEL_KINDS = (PANEL_KIND_RESULTADO, PANEL_KIND_CULTIVO, PANEL_KIND_FROTIS)

# Legacy values written before the three-way choice existed.
_PANEL_KIND_ALIASES = {"standard": PANEL_KIND_RESULTADO, "culture": PANEL_KIND_CULTIVO}


def normalize_panel_kind(value: Any) -> str:
    kind = str(value or "").strip().casefold()
    kind = _PANEL_KIND_ALIASES.get(kind, kind)
    return kind if kind in PANEL_KINDS else PANEL_KIND_RESULTADO


# Layout blocks a frotis panel declares: a title band followed by labelled
# narrative blocks (Serie roja / Serie blanca / Serie plaquetaria), each drawing
# its prose from a text test's result value.
FROTIS_CONFIG_DEFAULTS: dict[str, Any] = {
    "title": "",
    "section_names": [],
    "method_note": "",
}

# Layout blocks a culture panel can declare, in render order. Each block lists
# the test names it draws from; the values themselves come from the order's
# results like any other test, so nothing here affects ordering or data entry.
# Names (not codes) because both the live and the snapshotted report previews
# always carry test_name, which keeps this working for historical reports.
CULTURE_CONFIG_DEFAULTS: dict[str, Any] = {
    "title": "",
    # Top block: a heading followed by free-form two-column rows the tech fills
    # in per order (stored in order_culture_data, not as tests).
    "pathogens_heading": "MICROORGANISMOS PATOGENOS BUSCADOS EN EL CULTIVO",
    "isolate_label": "AGENTE ETIOLOGICO AISLADO:",
    "isolate_name": "",
    "extra_names": [],
    "susceptibility_heading": "Pruebas susceptibilidad antimicrobiana",
    # The gram chosen on the order picks which antibiotic list prints, and which
    # of these two labels heads it.
    "gram_label_positive": "GRAM POSITIVOS:",
    "gram_label_negative": "GRAM NEGATIVOS:",
    "antibiotic_names_positive": [],
    "antibiotic_names_negative": [],
    # Column titles printed above the antibiogram. Leave col_3 blank to print a
    # two-column antibiogram with no concentration column.
    "antibiogram_col_1": "ANTIBIOTICO",
    "antibiogram_col_2": "INHIBICION",
    "antibiogram_col_3": "CONCENTRACION",
    # Disc load per antibiotic name, e.g. {"Ampicilina": "10 µg"}. Presentation
    # metadata for the panel, not a test result -- `tests` has no unit column and
    # reference ranges would be the wrong home for it.
    "antibiotic_concentrations": {},
    "method_note": "",
}

GRAM_POSITIVE = "positivo"
GRAM_NEGATIVE = "negativo"


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

    @staticmethod
    def _normalize_layout_config(raw: Any, defaults: dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}
        config = dict(defaults)
        if not isinstance(raw, dict):
            return config
        for key, default in defaults.items():
            value = raw.get(key, default)
            if isinstance(default, dict):
                config[key] = (
                    {str(k).strip(): str(v or "").strip() for k, v in value.items() if str(k).strip()}
                    if isinstance(value, dict)
                    else {}
                )
            elif isinstance(default, list):
                config[key] = [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []
            elif isinstance(default, bool):
                config[key] = bool(value)
            else:
                config[key] = str(value or "").strip()
        return config

    @classmethod
    def normalize_culture_config(cls, raw: Any) -> dict[str, Any]:
        return cls._normalize_layout_config(raw, CULTURE_CONFIG_DEFAULTS)

    @classmethod
    def normalize_frotis_config(cls, raw: Any) -> dict[str, Any]:
        return cls._normalize_layout_config(raw, FROTIS_CONFIG_DEFAULTS)

    def _layout_panels_by_name(self, kind: str, normalizer) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT name, code, panel_kind, culture_config FROM test_panels WHERE is_active = 1"
            ).fetchall()
        panels: dict[str, dict[str, Any]] = {}
        for row in rows:
            if normalize_panel_kind(row["panel_kind"]) != kind:
                continue
            name = str(row["name"] or "").strip()
            if not name:
                continue
            config = normalizer(row["culture_config"])
            if not config.get("title"):
                config["title"] = name
            panels[name.casefold()] = config
        return panels

    def get_culture_panels_by_name(self) -> dict[str, dict[str, Any]]:
        """Cultivo panel layout configs keyed by panel name (casefolded)."""
        return self._layout_panels_by_name(PANEL_KIND_CULTIVO, self.normalize_culture_config)

    def get_frotis_panels_by_name(self) -> dict[str, dict[str, Any]]:
        """Frotis panel layout configs keyed by panel name (casefolded)."""
        return self._layout_panels_by_name(PANEL_KIND_FROTIS, self.normalize_frotis_config)

    # --- per-order culture data (gram choice + free-form rows) ---

    def get_order_culture_data(self, order_id: int, panel_code: str, report_version: int = 0) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT gram, rows_json FROM order_culture_data WHERE order_id = ? AND panel_code = ? AND report_version = ?",
                (int(order_id), str(panel_code), int(report_version)),
            ).fetchone()
            if row is None and report_version:
                # A report finalized before this feature existed has no snapshot;
                # fall back to the live copy rather than printing an empty block.
                row = connection.execute(
                    "SELECT gram, rows_json FROM order_culture_data WHERE order_id = ? AND panel_code = ? AND report_version = 0",
                    (int(order_id), str(panel_code)),
                ).fetchone()
        if row is None:
            return {"gram": "", "rows": []}
        try:
            raw_rows = json.loads(row["rows_json"] or "[]")
        except json.JSONDecodeError:
            raw_rows = []
        rows = [
            {"label": str(entry.get("label") or "").strip(), "value": str(entry.get("value") or "").strip()}
            for entry in raw_rows
            if isinstance(entry, dict)
        ]
        return {"gram": str(row["gram"] or "").strip().casefold(), "rows": rows}

    def save_order_culture_data(
        self,
        order_id: int,
        panel_code: str,
        gram: str,
        rows: list[dict[str, Any]],
        report_version: int = 0,
    ) -> None:
        normalized = [
            {"label": str(entry.get("label") or "").strip(), "value": str(entry.get("value") or "").strip()}
            for entry in rows
            if isinstance(entry, dict) and (str(entry.get("label") or "").strip() or str(entry.get("value") or "").strip())
        ]
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO order_culture_data (order_id, panel_code, report_version, gram, rows_json, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(order_id, panel_code, report_version)
                DO UPDATE SET gram = excluded.gram, rows_json = excluded.rows_json, updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(order_id),
                    str(panel_code),
                    int(report_version),
                    str(gram or "").strip().casefold(),
                    json.dumps(normalized, ensure_ascii=False),
                ),
            )

    def snapshot_order_culture_data(self, order_id: int, report_version: int) -> None:
        """Freeze the live culture rows against a finalized report version."""
        if int(report_version) <= 0:
            return
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO order_culture_data (order_id, panel_code, report_version, gram, rows_json, updated_at)
                SELECT order_id, panel_code, ?, gram, rows_json, CURRENT_TIMESTAMP
                FROM order_culture_data WHERE order_id = ? AND report_version = 0
                ON CONFLICT(order_id, panel_code, report_version)
                DO UPDATE SET gram = excluded.gram, rows_json = excluded.rows_json, updated_at = CURRENT_TIMESTAMP
                """,
                (int(report_version), int(order_id)),
            )

    def get_culture_panel_codes_by_name(self) -> dict[str, str]:
        """Panel name (casefolded) -> panel code, for cultivo panels."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT name, code, panel_kind FROM test_panels WHERE is_active = 1"
            ).fetchall()
        return {
            str(row["name"] or "").strip().casefold(): str(row["code"] or "").strip()
            for row in rows
            if normalize_panel_kind(row["panel_kind"]) == PANEL_KIND_CULTIVO and str(row["name"] or "").strip()
        }

    def get_panel_kind(self, panel_id: int) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT panel_kind FROM test_panels WHERE id = ?", (int(panel_id),)).fetchone()
        return normalize_panel_kind(row["panel_kind"] if row is not None else None)

    def get_panel_layout_config(self, panel_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT panel_kind, culture_config FROM test_panels WHERE id = ?", (int(panel_id),)
            ).fetchone()
        if row is None:
            return {}
        kind = normalize_panel_kind(row["panel_kind"])
        if kind == PANEL_KIND_CULTIVO:
            return self.normalize_culture_config(row["culture_config"])
        if kind == PANEL_KIND_FROTIS:
            return self.normalize_frotis_config(row["culture_config"])
        return {}

    def set_panel_kind(self, panel_id: int, panel_kind: str, layout_config: dict[str, Any] | None = None) -> None:
        kind = normalize_panel_kind(panel_kind)
        if kind == PANEL_KIND_CULTIVO:
            payload = json.dumps(self.normalize_culture_config(layout_config), ensure_ascii=False)
        elif kind == PANEL_KIND_FROTIS:
            payload = json.dumps(self.normalize_frotis_config(layout_config), ensure_ascii=False)
        else:
            payload = None
        with self.connect() as connection:
            connection.execute(
                "UPDATE test_panels SET panel_kind = ?, culture_config = ? WHERE id = ?",
                (kind, payload, int(panel_id)),
            )

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
