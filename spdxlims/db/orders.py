from __future__ import annotations
import re
import sqlite3
from typing import Any

from spdxlims.db.records import (
    OrderSummaryRecord,
    OrderBrowserRecord,
    ResultWorkflowRecord,
    OutsourcedPanelChoiceRecord,
    OrderLookupRecord,
    OrderEditRecord,
    ResultEntryRecord,
)


class OrdersMixin:
    def next_order_number(self) -> str:
        with self.connect() as connection:
            return self._next_order_number(connection)

    def _next_order_number(self, connection: sqlite3.Connection, prefix: str = "") -> str:
        # Highest numeric tail *within* the given prefix, aggregated in SQL so the
        # whole orders table never crosses into Python. An empty prefix matches
        # only all-digit order numbers, so prefixed batches keep their own series.
        tail_start = len(prefix) + 1
        row = connection.execute(
            """
            SELECT MAX(CAST(SUBSTR(order_number, ?) AS INTEGER)) AS highest
            FROM orders
            WHERE SUBSTR(order_number, 1, ?) = ?
              AND SUBSTR(order_number, ?) GLOB '[0-9]*'
              AND SUBSTR(order_number, ?) NOT GLOB '*[^0-9]*'
            """,
            (tail_start, len(prefix), prefix, tail_start, tail_start),
        ).fetchone()
        highest = int(row["highest"] or 0) if row is not None else 0
        return f"{highest + 1:06d}"

    def _normalize_order_items(self, order_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique_items: list[dict[str, Any]] = []
        seen_test_ids: set[int] = set()
        for item in order_items:
            is_outsourced = 1 if item.get("is_outsourced") else 0
            if item.get("item_type") in {"heading", "comment"}:
                unique_items.append(
                    {
                        "item_type": item.get("item_type"),
                        "label": (item.get("label") or "").strip(),
                        "source": item.get("source") or "",
                        "is_outsourced": is_outsourced,
                    }
                )
                continue
            test_id = item.get("test_id")
            if test_id is None or test_id in seen_test_ids:
                continue
            seen_test_ids.add(test_id)
            unique_items.append(
                {
                    "item_type": "test",
                    "test_id": int(test_id),
                    "label": item.get("label"),
                    "source": item.get("source") or "",
                    "is_outsourced": is_outsourced,
                }
            )
        return unique_items

    def _save_order_items(self, connection: sqlite3.Connection, order_id: int, order_items: list[dict[str, Any]]) -> None:
        heading_test_id = self._ensure_panel_heading_test(connection)
        comment_test_id = self._ensure_panel_comment_test(connection)
        for index, item in enumerate(order_items):
            outsourced_value = 1 if item.get("is_outsourced") else 0
            source_label = str(item.get("source") or "").strip() or None
            if item["item_type"] == "heading":
                connection.execute(
                    "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                    (order_id, heading_test_id, outsourced_value, source_label, item["label"], index),
                )
                continue
            if item["item_type"] == "comment":
                connection.execute(
                    "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                    (order_id, comment_test_id, outsourced_value, source_label, item["label"], index),
                )
                continue
            test_id = item["test_id"]
            test_row = connection.execute("SELECT name FROM tests WHERE id = ?", (test_id,)).fetchone()
            display_name = test_row["name"] if test_row else None
            connection.execute(
                "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                (order_id, test_id, outsourced_value, source_label, display_name, index),
            )

    def _delete_order_test_row(self, connection: sqlite3.Connection, order_test_id: int) -> None:
        """Delete an order_tests row together with every row that references it.

        Four tables carry a FK to order_tests (results, result_images,
        report_items, report_item_images); leaving any of them behind makes the
        delete fail with 'FOREIGN KEY constraint failed'.
        """
        connection.execute("DELETE FROM results WHERE order_test_id = ?", (order_test_id,))
        connection.execute("DELETE FROM result_images WHERE order_test_id = ?", (order_test_id,))
        connection.execute("DELETE FROM report_item_images WHERE order_test_id = ?", (order_test_id,))
        connection.execute("DELETE FROM report_items WHERE order_test_id = ?", (order_test_id,))
        connection.execute("DELETE FROM order_tests WHERE id = ?", (order_test_id,))

    def create_order(self, order_number: str | None, accession_id: str | None, sample_id: str | None, patient_id: int, doctor_id: int | None, client_id: int | None, order_items: list[dict[str, Any]], status: str, notes: str) -> int:
        unique_items = self._normalize_order_items(order_items)
        explicit_order_number = (order_number or "").strip()
        with self.connect() as connection:
            resolved_order_number = explicit_order_number or self._next_order_number(connection)
            attempts_left = 1 if explicit_order_number else 5
            while True:
                try:
                    cursor = connection.execute(
                        "INSERT INTO orders (order_number, accession_id, sample_id, patient_id, doctor_id, client_id, status, is_preallocated, ordered_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP, ?)",
                        (resolved_order_number, (accession_id or '').strip() or None, (sample_id or '').strip() or None, patient_id, doctor_id, client_id, status, notes.strip() or None),
                    )
                    break
                except sqlite3.IntegrityError as exc:
                    attempts_left -= 1
                    if attempts_left <= 0 or "orders.order_number" not in str(exc):
                        raise
                    resolved_order_number = self._next_order_number(connection)
            order_id = int(cursor.lastrowid)
            self._save_order_items(connection, order_id, unique_items)
        return order_id

    def create_preallocated_order_batch(self, count: int, client_id: int | None = None, batch_prefix: str | None = None) -> list[dict[str, Any]]:
        labels: list[dict[str, Any]] = []
        normalized_prefix = (batch_prefix or '').strip().upper()
        with self.connect() as connection:
            placeholder_patient_id = self._get_or_create_preallocated_patient(connection)
            next_number = int(self._next_order_number(connection, normalized_prefix))
            for _ in range(count):
                order_number = f"{normalized_prefix}{next_number:06d}"
                attempts_left = 5
                while True:
                    try:
                        cursor = connection.execute(
                            "INSERT INTO orders (order_number, accession_id, sample_id, patient_id, doctor_id, client_id, status, is_preallocated, ordered_at, notes) VALUES (?, NULL, NULL, ?, NULL, ?, 'draft', 1, CURRENT_TIMESTAMP, ?)",
                            (order_number, placeholder_patient_id, client_id, 'Preprinted barcode batch'),
                        )
                        break
                    except sqlite3.IntegrityError as exc:
                        attempts_left -= 1
                        if attempts_left <= 0 or "orders.order_number" not in str(exc):
                            raise
                        next_number += 1
                        order_number = f"{normalized_prefix}{next_number:06d}"
                next_number += 1
                order_id = int(cursor.lastrowid)
                created_row = connection.execute("SELECT created_at FROM orders WHERE id = ?", (order_id,)).fetchone()
                labels.append({
                    'order_id': order_id,
                    'order_number': order_number,
                    'accession_id': '',
                    'sample_id': '',
                    'client_id': client_id,
                    'patient_name': '',
                    'test_name': '',
                    'specimen_type': '',
                    'specimen_code': 'SPC',
                    'test_code': '',
                    'group_label': '',
                    'created_at': created_row['created_at'] if created_row is not None else '',
                })
        return labels

    def find_order_by_number(self, order_number: str) -> OrderLookupRecord | None:
        normalized = order_number.strip()
        if not normalized:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, order_number, status, COALESCE(is_preallocated, 0) AS is_preallocated FROM orders WHERE order_number = ?",
                (normalized,),
            ).fetchone()
        return OrderLookupRecord(**dict(row)) if row is not None else None

    def get_order_edit_record(self, order_id: int) -> OrderEditRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, order_number, accession_id, sample_id, patient_id, doctor_id, client_id, status, notes, COALESCE(is_preallocated, 0) AS is_preallocated FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
            if row is None:
                return None
            item_rows = connection.execute(
                "SELECT ot.test_id, ot.display_name, ot.source_label, ot.sort_order, COALESCE(ot.is_outsourced, 0) AS is_outsourced, t.code AS test_code FROM order_tests ot INNER JOIN tests t ON t.id = ot.test_id WHERE ot.order_id = ? ORDER BY ot.sort_order, ot.id",
                (order_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for item_row in item_rows:
            code = item_row['test_code']
            label = item_row['display_name'] or ''
            is_outsourced = int(item_row['is_outsourced'] or 0)
            source_label = str(item_row['source_label'] or '')
            if code == '__PANEL_HEADING__':
                items.append({'item_type': 'heading', 'label': label, 'source': source_label, 'is_outsourced': is_outsourced})
            elif code == '__PANEL_COMMENT__':
                items.append({'item_type': 'comment', 'label': label, 'source': source_label, 'is_outsourced': is_outsourced})
            else:
                items.append({'item_type': 'test', 'test_id': int(item_row['test_id']), 'label': label, 'source': source_label, 'is_outsourced': is_outsourced})
        payload = dict(row)
        payload['items'] = items
        return OrderEditRecord(**payload)

    def assign_preallocated_order(self, order_id: int, accession_id: str | None, sample_id: str | None, patient_id: int, doctor_id: int | None, client_id: int | None, order_items: list[dict[str, Any]], status: str, notes: str) -> None:
        unique_items = self._normalize_order_items(order_items)
        with self.connect() as connection:
            row = connection.execute("SELECT COALESCE(is_preallocated, 0) AS is_preallocated FROM orders WHERE id = ?", (order_id,)).fetchone()
            if row is None:
                raise sqlite3.IntegrityError('Order not found.')
            if int(row['is_preallocated']) != 1:
                raise sqlite3.IntegrityError('Only preallocated barcode orders can be assigned from this workflow.')
            connection.execute(
                "UPDATE orders SET accession_id = ?, sample_id = ?, patient_id = ?, doctor_id = ?, client_id = ?, status = ?, is_preallocated = 0, notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ((accession_id or '').strip() or None, (sample_id or '').strip() or None, patient_id, doctor_id, client_id, status, notes.strip() or None, order_id),
            )
            for existing_row in connection.execute("SELECT id FROM order_tests WHERE order_id = ?", (order_id,)).fetchall():
                self._delete_order_test_row(connection, int(existing_row["id"]))
            self._save_order_items(connection, order_id, unique_items)

    def update_order(self, order_id: int, accession_id: str | None, sample_id: str | None, patient_id: int, doctor_id: int | None, client_id: int | None, order_items: list[dict[str, Any]], status: str, notes: str) -> None:
        unique_items = self._normalize_order_items(order_items)
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM orders WHERE id = ?", (order_id,)).fetchone()
            if row is None:
                raise sqlite3.IntegrityError('Order not found.')
            connection.execute(
                "UPDATE orders SET accession_id = ?, sample_id = ?, patient_id = ?, doctor_id = ?, client_id = ?, status = ?, notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ((accession_id or '').strip() or None, (sample_id or '').strip() or None, patient_id, doctor_id, client_id, status, notes.strip() or None, order_id),
            )
            # Remove any existing report — it references order_tests rows and must be
            # cleared before we delete/replace those rows, otherwise the FK from
            # report_items → order_tests fires.  The report can be regenerated after
            # the order is saved.
            report_row = connection.execute("SELECT id FROM reports WHERE order_id = ?", (order_id,)).fetchone()
            if report_row is not None:
                report_id = int(report_row["id"])
                connection.execute("DELETE FROM report_items WHERE report_id = ?", (report_id,))
                connection.execute("DELETE FROM report_item_images WHERE report_id = ?", (report_id,))
                connection.execute("DELETE FROM report_outsourced_rows WHERE report_id = ?", (report_id,))
                connection.execute("DELETE FROM reports WHERE id = ?", (report_id,))
            heading_test_id = self._ensure_panel_heading_test(connection)
            comment_test_id = self._ensure_panel_comment_test(connection)
            # New set of real test IDs
            new_test_ids = {
                item["test_id"] for item in unique_items if item.get("item_type") == "test"
            }
            # Existing real-test rows — preserve results for tests still in the list
            existing_rows = connection.execute(
                "SELECT id, test_id FROM order_tests WHERE order_id = ? AND test_id NOT IN (?, ?)",
                (order_id, heading_test_id, comment_test_id),
            ).fetchall()
            existing_map: dict[int, int] = {}
            for r in existing_rows:
                tid = int(r["test_id"])
                ot_id = int(r["id"])
                if tid not in new_test_ids:
                    # Test removed — drop it along with everything hanging off it
                    self._delete_order_test_row(connection, ot_id)
                else:
                    existing_map[tid] = ot_id
            # Headings and comments are matched to the incoming list by label so a
            # re-save reuses the same row.  Panel comments keep their typed text in
            # `results` (e.g. "Piocitos: 10 %"), so deleting and re-inserting these
            # rows would both trip the results → order_tests FK and lose the text.
            structural_pool: dict[tuple[int, str], list[int]] = {}
            for structural_row in connection.execute(
                "SELECT id, test_id, display_name FROM order_tests WHERE order_id = ? AND test_id IN (?, ?) ORDER BY sort_order, id",
                (order_id, heading_test_id, comment_test_id),
            ).fetchall():
                key = (int(structural_row["test_id"]), str(structural_row["display_name"] or ""))
                structural_pool.setdefault(key, []).append(int(structural_row["id"]))
            # Reconcile each item in the new list
            for index, item in enumerate(unique_items):
                outsourced = 1 if item.get("is_outsourced") else 0
                source = str(item.get("source") or "").strip() or None
                if item["item_type"] in {"heading", "comment"}:
                    structural_test_id = heading_test_id if item["item_type"] == "heading" else comment_test_id
                    label = item["label"]
                    reusable = structural_pool.get((structural_test_id, str(label or "")))
                    if reusable:
                        connection.execute(
                            "UPDATE order_tests SET sort_order = ?, is_outsourced = ?, source_label = ? WHERE id = ?",
                            (index, outsourced, source, reusable.pop(0)),
                        )
                    else:
                        connection.execute(
                            "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                            (order_id, structural_test_id, outsourced, source, label, index),
                        )
                else:
                    test_id = int(item["test_id"])
                    if test_id in existing_map:
                        # Already exists — just refresh sort order and outsourced flag
                        connection.execute(
                            "UPDATE order_tests SET sort_order = ?, is_outsourced = ?, source_label = ? WHERE id = ?",
                            (index, outsourced, source, existing_map[test_id]),
                        )
                    else:
                        # Genuinely new test
                        test_row = connection.execute("SELECT name FROM tests WHERE id = ?", (test_id,)).fetchone()
                        display_name = test_row["name"] if test_row else None
                        connection.execute(
                            "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                            (order_id, test_id, outsourced, source, display_name, index),
                        )
            # Headings/comments the new list no longer contains
            for leftover_ids in structural_pool.values():
                for leftover_id in leftover_ids:
                    self._delete_order_test_row(connection, leftover_id)

    def set_order_archived(self, order_id: int, archived: bool) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE orders SET is_archived = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if archived else 0, order_id),
            )

    def list_recent_orders(self) -> list[OrderSummaryRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT o.id, o.order_number, TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name, d.full_name AS doctor_name, o.status, o.created_at, SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1 ELSE 0 END) AS item_count, CASE WHEN COUNT(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') AND COALESCE(ot.is_outsourced, 0) = 0 THEN 1 END) > 0 AND COUNT(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') AND COALESCE(ot.is_outsourced, 0) = 0 THEN 1 END) = COUNT(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') AND COALESCE(ot.is_outsourced, 0) = 0 AND COALESCE(NULLIF(TRIM(r.result_value), ''), NULLIF(TRIM(t.default_result_value), '')) IS NOT NULL THEN 1 END) THEN 1 ELSE 0 END AS all_results_entered FROM orders o INNER JOIN patients p ON p.id = o.patient_id LEFT JOIN doctors d ON d.id = o.doctor_id LEFT JOIN order_tests ot ON ot.order_id = o.id LEFT JOIN tests t ON t.id = ot.test_id LEFT JOIN results r ON r.order_test_id = ot.id WHERE COALESCE(o.is_preallocated, 0) = 0 AND COALESCE(o.is_archived, 0) = 0 GROUP BY o.id, o.order_number, patient_name, d.full_name, o.status, o.created_at ORDER BY o.created_at DESC, o.id DESC LIMIT 25").fetchall()
        return [OrderSummaryRecord(**dict(row)) for row in rows]

    def search_orders(self, search_text: str = "", include_archived: bool = False) -> list[OrderBrowserRecord]:
        normalized = search_text.strip().lower()
        like_value = f"%{normalized}%"
        archived_clause = "" if include_archived else "AND COALESCE(o.is_archived, 0) = 0"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT o.id,
                       o.order_number,
                       COALESCE(o.ordered_at, o.created_at) AS order_date,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END
                       ) AS patient_name,
                       c.name AS client_name,
                       d.full_name AS doctor_name,
                       o.status,
                       COALESCE(o.is_archived, 0) AS is_archived,
                       SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1 ELSE 0 END) AS item_count,
                       CASE WHEN COUNT(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') AND COALESCE(ot.is_outsourced, 0) = 0 THEN 1 END) > 0
                            AND COUNT(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') AND COALESCE(ot.is_outsourced, 0) = 0 THEN 1 END) = COUNT(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') AND COALESCE(ot.is_outsourced, 0) = 0 AND COALESCE(NULLIF(TRIM(r.result_value), ''), NULLIF(TRIM(t.default_result_value), '')) IS NOT NULL THEN 1 END)
                           THEN 1 ELSE 0 END AS all_results_entered
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN doctors d ON d.id = o.doctor_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                LEFT JOIN results r ON r.order_test_id = ot.id
                WHERE COALESCE(o.is_preallocated, 0) = 0
                  {archived_clause}
                  AND (
                      ? = '' OR
                      LOWER(COALESCE(o.order_number, '')) LIKE ? OR
                      LOWER(TRIM(
                          p.first_name || ' ' || p.last_name ||
                          CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END
                      )) LIKE ? OR
                      LOWER(COALESCE(c.name, '')) LIKE ?
                  )
                GROUP BY o.id, o.order_number, order_date, patient_name, c.name, d.full_name, o.status, o.is_archived
                ORDER BY COALESCE(o.ordered_at, o.created_at) DESC, o.id DESC
                LIMIT 250
                """,
                (normalized, like_value, like_value, like_value),
            ).fetchall()
        return [OrderBrowserRecord(**dict(row)) for row in rows]

    def list_results_workflow_orders(self) -> list[ResultWorkflowRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                -- Pick the page of orders first, then aggregate only their
                -- tests. Joining orders x order_tests x results and grouping
                -- afterwards built the full fan-out for every order in the
                -- database before LIMIT could discard it, and the plan was
                -- fragile: once ANALYZE had run it got roughly 2x slower again.
                WITH recent_orders AS (
                    SELECT o.id,
                           o.order_number,
                           o.patient_id,
                           o.doctor_id,
                           o.client_id,
                           o.updated_at,
                           COALESCE(o.ordered_at, o.created_at) AS order_date
                    FROM orders o
                    WHERE COALESCE(o.is_preallocated, 0) = 0
                      AND COALESCE(o.is_archived, 0) = 0
                    ORDER BY COALESCE(o.ordered_at, o.created_at) DESC, o.id DESC
                    LIMIT 1000
                ),
                counts AS (
                    SELECT ot.order_id,
                           COUNT(*) AS result_count,
                           COUNT(CASE
                               WHEN COALESCE(NULLIF(TRIM(rst.result_value), ''), NULLIF(TRIM(t.default_result_value), '')) IS NOT NULL
                               THEN 1
                           END) AS completed_result_count
                    FROM order_tests ot
                    INNER JOIN tests t ON t.id = ot.test_id
                    LEFT JOIN results rst ON rst.order_test_id = ot.id
                    WHERE ot.order_id IN (SELECT id FROM recent_orders)
                      AND t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                      AND COALESCE(ot.is_outsourced, 0) = 0
                    GROUP BY ot.order_id
                )
                SELECT o.id,
                       o.order_number,
                       o.order_date,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END
                       ) AS patient_name,
                       p.phone AS patient_phone,
                       d.full_name AS doctor_name,
                       c.name AS client_name,
                       c.phone AS client_phone,
                       r.report_version,
                       r.finalized_at AS report_finalized_at,
                       CASE WHEN r.finalized_at IS NOT NULL AND (
                           p.updated_at > r.finalized_at OR o.updated_at > r.finalized_at
                       ) THEN 1 ELSE 0 END AS report_outdated,
                       COALESCE(cnt.result_count, 0) AS result_count,
                       COALESCE(cnt.completed_result_count, 0) AS completed_result_count
                FROM recent_orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN doctors d ON d.id = o.doctor_id
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN reports r ON r.order_id = o.id
                LEFT JOIN counts cnt ON cnt.order_id = o.id
                ORDER BY o.order_date DESC, o.id DESC
                """
            ).fetchall()
        return [ResultWorkflowRecord(**dict(row)) for row in rows]

    def list_outsourced_order_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT
                       o.id,
                       o.order_number,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END
                       ) AS patient_name
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN order_tests ot ON ot.order_id = o.id
                WHERE COALESCE(o.is_preallocated, 0) = 0
                  AND COALESCE(o.is_archived, 0) = 0
                  AND COALESCE(ot.is_outsourced, 0) = 1
                ORDER BY COALESCE(o.ordered_at, o.created_at) DESC, o.id DESC
                """
            ).fetchall()
        return [
            (int(row["id"]), f'{row["order_number"]} - {row["patient_name"]}')
            for row in rows
        ]

    def list_outsourced_panels_for_order(self, order_id: int) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT TRIM(COALESCE(ot.source_label, '')) AS panel_label
                FROM order_tests ot
                WHERE ot.order_id = ?
                  AND COALESCE(ot.is_outsourced, 0) = 1
                  AND TRIM(COALESCE(ot.source_label, '')) != ''
                ORDER BY panel_label
                """,
                (order_id,),
            ).fetchall()
        return [str(row["panel_label"]) for row in rows]

    def append_outsourced_panel_extraction(
        self,
        order_id: int,
        panel_label: str,
        source_pdf_path: str,
        page_label: str,
        rows: list[list[object]],
    ) -> int:
        normalized_label = panel_label.strip()
        normalized_source = source_pdf_path.strip()
        if not normalized_label:
            raise sqlite3.IntegrityError("An outsourced panel must be selected.")
        if not normalized_source:
            raise sqlite3.IntegrityError("A source PDF path is required.")
        normalized_rows = self._normalize_outsourced_table_rows(rows)
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM outsourced_panel_tables WHERE order_id = ? AND panel_label = ?",
                (order_id, normalized_label),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO outsourced_panel_tables (
                        order_id, panel_label, source_pdf_path, updated_at
                    ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (order_id, normalized_label, normalized_source),
                )
                table_id = int(cursor.lastrowid)
            else:
                table_id = int(existing["id"])
                connection.execute(
                    "UPDATE outsourced_panel_tables SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (table_id,),
                )
            ext_cursor = connection.execute(
                """
                INSERT INTO outsourced_panel_extractions (
                    outsourced_panel_table_id, source_pdf_path, page_label, row_count
                ) VALUES (?, ?, ?, ?)
                """,
                (table_id, normalized_source, str(page_label).strip(), len(normalized_rows)),
            )
            extraction_id = int(ext_cursor.lastrowid)
            for row_index, row in enumerate(normalized_rows):
                connection.execute(
                    """
                    INSERT INTO outsourced_panel_rows (
                        outsourced_panel_table_id, extraction_id, row_index,
                        col_1, col_2, col_3, col_4, col_5
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (table_id, extraction_id, row_index, row[0], row[1], row[2], row[3], row[4]),
                )
        return extraction_id

    def list_outsourced_panel_extractions(
        self, order_id: int, panel_label: str
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT ope.id, ope.source_pdf_path, ope.page_label,
                       ope.row_count, ope.extracted_at
                FROM outsourced_panel_extractions ope
                INNER JOIN outsourced_panel_tables opt
                        ON opt.id = ope.outsourced_panel_table_id
                WHERE opt.order_id = ? AND opt.panel_label = ?
                ORDER BY ope.extracted_at ASC, ope.id ASC
                """,
                (order_id, panel_label.strip()),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_outsourced_panel_extraction(self, extraction_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM outsourced_panel_rows WHERE extraction_id = ?",
                (extraction_id,),
            )
            connection.execute(
                "DELETE FROM outsourced_panel_extractions WHERE id = ?",
                (extraction_id,),
            )

    def save_outsourced_panel_table(
        self,
        order_id: int,
        panel_label: str,
        source_pdf_path: str,
        rows: list[list[object]],
    ) -> None:
        self.append_outsourced_panel_extraction(order_id, panel_label, source_pdf_path, "", rows)

    def replace_outsourced_panel_rows(
        self, order_id: int, sections: list[dict[str, Any]]
    ) -> None:
        """Overwrite the live outsourced rows for an order with edited sections.

        Used when the report editor lets the user edit the extracted (outsourced)
        PDF rows: the report PDF renders from these live tables, so the edits must
        be persisted here to survive. Each panel's rows are consolidated into a
        single extraction; panels no longer present are cleared.
        """
        sections_by_label: dict[str, dict[str, Any]] = {}
        for section in sections or []:
            label = str(section.get("panel_label") or "").strip()
            if label:
                sections_by_label[label] = section
        with self.connect() as connection:
            existing_tables = {
                str(row["panel_label"]).strip(): int(row["id"])
                for row in connection.execute(
                    "SELECT id, panel_label FROM outsourced_panel_tables WHERE order_id = ?",
                    (order_id,),
                ).fetchall()
            }
            labels = set(sections_by_label) | set(existing_tables)
            for label in labels:
                section = sections_by_label.get(label)
                rows = self._normalize_outsourced_table_rows(
                    [
                        [
                            row.get("col_1"), row.get("col_2"), row.get("col_3"),
                            row.get("col_4"), row.get("col_5"),
                        ]
                        for row in list((section or {}).get("rows") or [])
                    ]
                )
                table_id = existing_tables.get(label)
                if table_id is None:
                    source_pdf_path = str((section or {}).get("source_pdf_path") or "").strip()
                    cursor = connection.execute(
                        """
                        INSERT INTO outsourced_panel_tables (
                            order_id, panel_label, source_pdf_path, updated_at
                        ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (order_id, label, source_pdf_path),
                    )
                    table_id = int(cursor.lastrowid)
                else:
                    connection.execute(
                        "UPDATE outsourced_panel_tables SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (table_id,),
                    )
                connection.execute(
                    "DELETE FROM outsourced_panel_rows WHERE outsourced_panel_table_id = ?",
                    (table_id,),
                )
                connection.execute(
                    "DELETE FROM outsourced_panel_extractions WHERE outsourced_panel_table_id = ?",
                    (table_id,),
                )
                if not rows:
                    continue
                source_row = connection.execute(
                    "SELECT source_pdf_path FROM outsourced_panel_tables WHERE id = ?",
                    (table_id,),
                ).fetchone()
                source_pdf_path = str((source_row["source_pdf_path"] if source_row else "") or "")
                ext_cursor = connection.execute(
                    """
                    INSERT INTO outsourced_panel_extractions (
                        outsourced_panel_table_id, source_pdf_path, page_label, row_count
                    ) VALUES (?, ?, '', ?)
                    """,
                    (table_id, source_pdf_path, len(rows)),
                )
                extraction_id = int(ext_cursor.lastrowid)
                for row_index, row in enumerate(rows):
                    connection.execute(
                        """
                        INSERT INTO outsourced_panel_rows (
                            outsourced_panel_table_id, extraction_id, row_index,
                            col_1, col_2, col_3, col_4, col_5
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (table_id, extraction_id, row_index, row[0], row[1], row[2], row[3], row[4]),
                    )

    def get_outsourced_panel_preview_sections(self, order_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT opt.panel_label,
                       opt.source_pdf_path,
                       opr.row_index,
                       opr.col_1,
                       opr.col_2,
                       opr.col_3,
                       opr.col_4,
                       opr.col_5
                FROM outsourced_panel_tables opt
                LEFT JOIN outsourced_panel_rows opr ON opr.outsourced_panel_table_id = opt.id
                WHERE opt.order_id = ?
                ORDER BY opt.panel_label, opr.id
                """,
                (order_id,),
            ).fetchall()
        return self._group_outsourced_rows(rows)

    @staticmethod
    def _normalize_outsourced_table_rows(rows: list[list[object]]) -> list[list[str]]:
        normalized_rows: list[list[str]] = []
        for raw_row in rows:
            normalized = [str(value or "").strip() for value in list(raw_row)[:5]]
            while len(normalized) < 5:
                normalized.append("")
            if any(normalized):
                normalized_rows.append(normalized)
        return normalized_rows

    @staticmethod
    def _group_outsourced_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        grouped: list[dict[str, Any]] = []
        current_key: tuple[str, str] | None = None
        current_section: dict[str, Any] | None = None
        for row in rows:
            panel_label = str(row["panel_label"] or "").strip()
            source_pdf_path = str(row["source_pdf_path"] or "").strip()
            key = (panel_label, source_pdf_path)
            if current_key != key:
                current_key = key
                current_section = {
                    "panel_label": panel_label,
                    "source_pdf_path": source_pdf_path,
                    "rows": [],
                }
                grouped.append(current_section)
            if current_section is None:
                continue
            if row["row_index"] is None:
                continue
            # Renumber sequentially within the section. Each extraction restarts its
            # own row_index at 0, so the stored value collides across extractions and
            # would interleave page 1/page 2 rows if used for ordering. Rows arrive in
            # insertion order (ordered by id), so position gives the true sequence.
            current_section["rows"].append(
                {
                    "row_index": len(current_section["rows"]),
                    "col_1": str(row["col_1"] or ""),
                    "col_2": str(row["col_2"] or ""),
                    "col_3": str(row["col_3"] or ""),
                    "col_4": str(row["col_4"] or ""),
                    "col_5": str(row["col_5"] or ""),
                }
            )
        return grouped

    def list_result_order_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT o.id, o.order_number, TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name, SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1 ELSE 0 END) AS item_count FROM orders o INNER JOIN patients p ON p.id = o.patient_id INNER JOIN order_tests ot ON ot.order_id = o.id INNER JOIN tests t ON t.id = ot.test_id WHERE o.status IN ('draft', 'in_progress') AND COALESCE(o.is_preallocated, 0) = 0 AND COALESCE(o.is_archived, 0) = 0 GROUP BY o.id, o.order_number, patient_name ORDER BY o.created_at DESC, o.id DESC").fetchall()
        return [(row["id"], f'{row["order_number"]} - {row["patient_name"]} ({row["item_count"]} tests)') for row in rows]

    def list_report_order_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,
                       o.order_number,
                       o.status,
                       TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name,
                       SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1 ELSE 0 END) AS item_count
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN order_tests ot ON ot.order_id = o.id
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE o.status IN ('draft', 'in_progress', 'finalized')
                  AND COALESCE(o.is_preallocated, 0) = 0
                  AND COALESCE(o.is_archived, 0) = 0
                GROUP BY o.id, o.order_number, o.status, patient_name
                ORDER BY o.created_at DESC, o.id DESC
                """
            ).fetchall()
        return [
            (
                row["id"],
                f'{row["order_number"]} - {row["patient_name"]} ({row["item_count"]} tests, {row["status"]})',
            )
            for row in rows
        ]

    def list_filtered_report_order_choices(
        self,
        *,
        client_id: int | None = None,
        test_id: int | None = None,
        date_from: str = "",
        date_to: str = "",
    ) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,
                       o.order_number,
                       o.status,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       c.name AS client_name,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE
                               WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name
                               ELSE ''
                           END
                       ) AS patient_name,
                       SUM(
                           CASE
                               WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1
                               ELSE 0
                           END
                       ) AS item_count
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                INNER JOIN order_tests ot ON ot.order_id = o.id
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE o.status IN ('draft', 'in_progress', 'finalized')
                  AND COALESCE(o.is_preallocated, 0) = 0
                  AND COALESCE(o.is_archived, 0) = 0
                  AND (? IS NULL OR o.client_id = ?)
                  AND (? IS NULL OR EXISTS (
                      SELECT 1
                      FROM order_tests match_ot
                      WHERE match_ot.order_id = o.id AND match_ot.test_id = ?
                  ))
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) >= DATE(?))
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) <= DATE(?))
                GROUP BY o.id, o.order_number, o.status, order_date, c.name, patient_name
                ORDER BY DATE(COALESCE(o.ordered_at, o.created_at)) DESC, o.id DESC
                """,
                (
                    client_id,
                    client_id,
                    test_id,
                    test_id,
                    date_from,
                    date_from,
                    date_to,
                    date_to,
                ),
            ).fetchall()
        return [
            (
                row["id"],
                f'{row["order_number"]} - {row["patient_name"]} - {row["client_name"] or "No Client"} - {row["order_date"] or ""} ({row["item_count"]} tests, {row["status"]})',
            )
            for row in rows
        ]

    def get_order_result_entries(self, order_id: int) -> list[ResultEntryRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT ot.id AS order_test_id, o.id AS order_id, o.order_number, TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name, d.full_name AS doctor_name, p.sex AS patient_sex, p.date_of_birth, p.age_value, p.age_unit, t.id AS test_id, COALESCE(ot.display_name, t.name) AS test_name, t.specimen_type, CASE WHEN t.code = '__PANEL_HEADING__' THEN 'heading' WHEN t.code = '__PANEL_COMMENT__' THEN 'comment' ELSE 'test' END AS item_type, t.result_kind, t.select_options, t.default_result_value, t.result_multiplier, t.formula, r.result_value, r.unit, COALESCE(r.lower_value_text, CAST(r.lower_value AS TEXT)) AS lower_value, COALESCE(r.upper_value_text, CAST(r.upper_value AS TEXT)) AS upper_value, r.flag, r.reference_text, r.comments, ot.status AS test_status, COALESCE(ot.is_outsourced, 0) AS is_outsourced, ot.source_label FROM order_tests ot INNER JOIN orders o ON o.id = ot.order_id INNER JOIN patients p ON p.id = o.patient_id LEFT JOIN doctors d ON d.id = o.doctor_id INNER JOIN tests t ON t.id = ot.test_id LEFT JOIN results r ON r.order_test_id = ot.id WHERE o.id = ? ORDER BY ot.sort_order, ot.id", (order_id,)).fetchall()
            records: list[ResultEntryRecord] = []
            for row in rows:
                data = dict(row)
                age_days = self._resolve_age_days(data.pop("date_of_birth"), data.pop("age_value"), data.pop("age_unit"))
                data["patient_age_days"] = age_days
                if data.get("item_type") not in {"heading", "comment"}:
                    if not data.get("result_value") and data.get("default_result_value"):
                        data["result_value"] = data["default_result_value"]
                    reference = self._resolve_reference_range(connection, data["test_id"], data["patient_sex"], age_days)
                    if reference is not None:
                        if not data["unit"]:
                            data["unit"] = reference["unit"]
                        if data["lower_value"] is None:
                            data["lower_value"] = reference["lower_value"]
                        if data["upper_value"] is None:
                            data["upper_value"] = reference["upper_value"]
                        if not data["reference_text"]:
                            data["reference_text"] = reference["reference_text"]
                records.append(ResultEntryRecord(**data))
            return records

    def list_client_results_for_export(
        self,
        *,
        client_id: int | None = None,
        date_from: str = "",
        date_to: str = "",
    ) -> list[tuple[str, str, str, str, str, str]]:
        """Returns (order_date, patient_name, panel, test_name, result_value, unit) rows."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT SUBSTR(COALESCE(o.ordered_at, o.created_at), 1, 10) AS order_date,
                       TRIM(p.first_name || ' ' || p.last_name ||
                            CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != ''
                                 THEN ' ' || p.middle_name ELSE '' END) AS patient_name,
                       COALESCE(ot.source_label, '') AS panel,
                       COALESCE(ot.display_name, t.name) AS test_name,
                       COALESCE(r.result_value, '') AS result_value,
                       COALESCE(r.unit, '') AS unit
                FROM order_tests ot
                INNER JOIN orders o ON o.id = ot.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN tests t ON t.id = ot.test_id
                LEFT JOIN results r ON r.order_test_id = ot.id
                WHERE t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                  AND COALESCE(o.is_archived, 0) = 0
                  AND (? IS NULL OR o.client_id = ?)
                  AND (? = '' OR SUBSTR(COALESCE(o.ordered_at, o.created_at), 1, 10) >= ?)
                  AND (? = '' OR SUBSTR(COALESCE(o.ordered_at, o.created_at), 1, 10) <= ?)
                ORDER BY COALESCE(o.ordered_at, o.created_at), p.last_name, p.first_name, ot.sort_order
                """,
                (client_id, client_id, date_from, date_from, date_to, date_to),
            ).fetchall()
        return [(str(r[0] or ""), str(r[1] or ""), str(r[2] or ""),
                 str(r[3] or ""), str(r[4] or ""), str(r[5] or "")) for r in rows]

    def list_order_test_codes(self, order_id: int) -> dict[int, str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT ot.id AS order_test_id, t.code FROM order_tests ot INNER JOIN tests t ON t.id = ot.test_id WHERE ot.order_id = ?",
                (order_id,),
            ).fetchall()
        return {int(row["order_test_id"]): str(row["code"] or "") for row in rows}
