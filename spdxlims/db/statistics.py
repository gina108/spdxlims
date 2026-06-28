from __future__ import annotations

from typing import Any

# Orders carry placeholder "tests" for panel headings/comments; never count them.
_PLACEHOLDER_CODES = ("__PANEL_HEADING__", "__PANEL_COMMENT__")

# Shared order filter: real orders only (skip pre-allocated blanks and archived),
# with an optional ordered-at date window and optional client.
_ORDER_DATE_FILTER = """
    COALESCE(o.is_preallocated, 0) = 0
    AND COALESCE(o.is_archived, 0) = 0
    AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) >= DATE(?))
    AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) <= DATE(?))
"""


class StatisticsMixin:
    """Operational/analytics reports (volumes, inventory usage) for the Statistics page."""

    @staticmethod
    def _date_params(date_from: str, date_to: str) -> list[Any]:
        date_from = (date_from or "").strip()
        date_to = (date_to or "").strip()
        return [date_from, date_from, date_to, date_to]

    @staticmethod
    def _subjects_clause(
        subjects: list[tuple[str, Any]] | None,
        *,
        panel_direct: bool = False,
        test_direct: bool = False,
    ) -> tuple[str, list[Any]]:
        """Restrict a report to the selected doctors, tests, and/or panels.

        Subjects are grouped by kind. Within a kind the values are OR-ed (``IN``);
        across kinds they are AND-ed. When a kind matches the report's own grouping
        dimension (``panel_direct`` for panel volume, ``test_direct`` for test
        volume) it restricts the grouped rows directly so only the chosen panels/
        tests appear; otherwise it narrows the order set via ``EXISTS``. Doctors
        always match at the order level. Returns an SQL fragment plus bound params.
        """
        doctors = [value for kind, value in (subjects or []) if kind == "doctor" and value is not None]
        clients = [value for kind, value in (subjects or []) if kind == "client" and value is not None]
        tests = [value for kind, value in (subjects or []) if kind == "test" and value is not None]
        panels: list[str] = []
        for kind, value in (subjects or []):
            if kind != "panel" or value in (None, ""):
                continue
            # A panel subject carries every source-label form (code and name).
            if isinstance(value, (list, tuple)):
                panels.extend(str(form) for form in value if form not in (None, ""))
            else:
                panels.append(str(value))
        clauses: list[str] = []
        params: list[Any] = []
        if doctors:
            clauses.append(f"o.doctor_id IN ({', '.join('?' for _ in doctors)})")
            params += doctors
        if clients:
            clauses.append(f"o.client_id IN ({', '.join('?' for _ in clients)})")
            params += clients
        if tests:
            placeholders = ", ".join("?" for _ in tests)
            if test_direct:
                clauses.append(f"ot.test_id IN ({placeholders})")
            else:
                clauses.append(f"EXISTS (SELECT 1 FROM order_tests sx WHERE sx.order_id = o.id AND sx.test_id IN ({placeholders}))")
            params += tests
        if panels:
            placeholders = ", ".join("?" for _ in panels)
            if panel_direct:
                clauses.append(f"TRIM(ot.source_label) IN ({placeholders})")
            else:
                clauses.append(f"EXISTS (SELECT 1 FROM order_tests sx WHERE sx.order_id = o.id AND TRIM(sx.source_label) IN ({placeholders}))")
            params += panels
        if not clauses:
            return "", []
        return " AND " + " AND ".join(clauses), params

    def list_panel_filter_options(self) -> list[tuple[list[str], str]]:
        """Panels seen on orders, de-duplicated against the catalog for the filter.

        Orders store a panel's source label as either its code (Excel import) or
        its name (manual/portal entry), so the same panel can appear under two
        labels. Each returned option is ``(match_values, display_label)`` where
        ``match_values`` are all source-label forms (code and name) to match and
        the label is the panel name. Labels with no catalog match are returned
        as-is so nothing is dropped.
        """
        with self.connect() as connection:
            used = {
                str(row["panel"]).strip()
                for row in connection.execute(
                    "SELECT DISTINCT TRIM(source_label) AS panel FROM order_tests WHERE COALESCE(source_label, '') != ''"
                ).fetchall()
                if str(row["panel"]).strip()
            }
            catalog = [dict(row) for row in connection.execute("SELECT code, name FROM test_panels").fetchall()]
        options: list[tuple[list[str], str]] = []
        consumed: set[str] = set()
        for panel in catalog:
            code = str(panel.get("code") or "").strip()
            name = str(panel.get("name") or "").strip()
            forms = [form for form in (code, name) if form]
            if not any(form in used for form in forms):
                continue
            consumed.update(forms)
            options.append((forms, name or code))
        for label in sorted(used - consumed, key=str.lower):
            options.append(([label], label))
        options.sort(key=lambda option: option[1].lower())
        return options

    def report_test_volume(self, date_from: str = "", date_to: str = "", client_id: int | None = None, subjects: list[tuple[str, Any]] | None = None) -> list[dict[str, Any]]:
        """How many times each individual test was ordered in the window."""
        params = self._date_params(date_from, date_to)
        params += [client_id, client_id]
        subject_sql, subject_params = self._subjects_clause(subjects, test_direct=True)
        params += subject_params
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT t.code AS test_code,
                       t.name AS test_name,
                       COALESCE(tc.name, '') AS category,
                       COUNT(*) AS times_ordered
                FROM order_tests ot
                INNER JOIN orders o ON o.id = ot.order_id
                INNER JOIN tests t ON t.id = ot.test_id
                LEFT JOIN test_categories tc ON tc.id = t.category_id
                WHERE t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                  AND {_ORDER_DATE_FILTER}
                  AND (? IS NULL OR o.client_id = ?){subject_sql}
                GROUP BY t.id, t.code, t.name, category
                ORDER BY times_ordered DESC, t.name
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def report_panel_volume(self, date_from: str = "", date_to: str = "", client_id: int | None = None, subjects: list[tuple[str, Any]] | None = None) -> list[dict[str, Any]]:
        """How many orders included each panel (grouped by its source label)."""
        params = self._date_params(date_from, date_to)
        params += [client_id, client_id]
        subject_sql, subject_params = self._subjects_clause(subjects, panel_direct=True)
        params += subject_params
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT COALESCE(tp.name, TRIM(ot.source_label)) AS panel,
                       COUNT(DISTINCT o.id) AS times_ordered,
                       COUNT(*) AS test_instances
                FROM order_tests ot
                INNER JOIN orders o ON o.id = ot.order_id
                INNER JOIN tests t ON t.id = ot.test_id
                LEFT JOIN test_panels tp
                       ON tp.code = TRIM(ot.source_label) OR tp.name = TRIM(ot.source_label)
                WHERE COALESCE(ot.source_label, '') != ''
                  AND t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                  AND {_ORDER_DATE_FILTER}
                  AND (? IS NULL OR o.client_id = ?){subject_sql}
                GROUP BY COALESCE(tp.name, TRIM(ot.source_label))
                ORDER BY times_ordered DESC, panel
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def report_client_volume(self, date_from: str = "", date_to: str = "", subjects: list[tuple[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Orders and tests per referring client in the window."""
        params = self._date_params(date_from, date_to)
        subject_sql, subject_params = self._subjects_clause(subjects)
        params += subject_params
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT COALESCE(c.name, '') AS client_name,
                       COUNT(DISTINCT o.id) AS order_count,
                       SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1 ELSE 0 END) AS test_count
                FROM orders o
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                WHERE {_ORDER_DATE_FILTER}{subject_sql}
                GROUP BY o.client_id, client_name
                ORDER BY order_count DESC, client_name
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def report_doctor_volume(self, date_from: str = "", date_to: str = "", subjects: list[tuple[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Orders and tests per referring doctor in the window."""
        params = self._date_params(date_from, date_to)
        subject_sql, subject_params = self._subjects_clause(subjects)
        params += subject_params
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT COALESCE(d.full_name, '') AS doctor_name,
                       COUNT(DISTINCT o.id) AS order_count,
                       SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1 ELSE 0 END) AS test_count
                FROM orders o
                LEFT JOIN doctors d ON d.id = o.doctor_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                WHERE {_ORDER_DATE_FILTER}{subject_sql}
                GROUP BY o.doctor_id, doctor_name
                ORDER BY order_count DESC, doctor_name
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def report_inventory_usage(self, date_from: str = "", date_to: str = "") -> list[dict[str, Any]]:
        """Per item: purchased/consumed/adjusted in the window plus current stock.

        Movement quantities are stored signed (consumption/out are negative), so
        ``consumed`` flips the sign to report a positive amount used. The date
        window lives in the JOIN so items with no movements still appear (zeros).
        """
        date_from = (date_from or "").strip()
        date_to = (date_to or "").strip()
        params = [date_from, date_from, date_to, date_to]
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT ii.name AS item_name,
                       ii.sku AS sku,
                       COALESCE(ii.unit, '') AS unit,
                       COALESCE(SUM(CASE WHEN m.movement_type = 'purchase' THEN m.quantity ELSE 0 END), 0) AS purchased,
                       COALESCE(SUM(CASE WHEN m.movement_type = 'consumption' THEN -m.quantity ELSE 0 END), 0) AS consumed,
                       COALESCE(SUM(CASE WHEN m.movement_type IN ('adjustment_in', 'adjustment_out') THEN m.quantity ELSE 0 END), 0) AS adjusted,
                       COALESCE(SUM(m.quantity), 0) AS net_change,
                       ii.on_hand AS on_hand,
                       ii.reorder_level AS reorder_level
                FROM inventory_items ii
                LEFT JOIN inventory_movements m
                       ON m.inventory_item_id = ii.id
                      AND (? = '' OR DATE(m.movement_date) >= DATE(?))
                      AND (? = '' OR DATE(m.movement_date) <= DATE(?))
                GROUP BY ii.id, item_name, sku, unit, on_hand, reorder_level
                ORDER BY item_name, sku
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]
