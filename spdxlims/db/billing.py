from __future__ import annotations
import sqlite3
from typing import Any

from spdxlims.db.records import InvoiceRecord, ReceiptRecord


class BillingMixin:
    def next_invoice_number(self) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM invoices ORDER BY id DESC LIMIT 1").fetchone()
        next_id = (int(row["id"]) + 1) if row is not None else 1
        return f"INV-{next_id:06d}"

    def next_receipt_number(self) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM receipts ORDER BY id DESC LIMIT 1").fetchone()
        next_id = (int(row["id"]) + 1) if row is not None else 1
        return f"REC-{next_id:06d}"

    def list_invoice_order_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT o.id, o.order_number, TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name FROM orders o INNER JOIN patients p ON p.id = o.patient_id WHERE COALESCE(o.is_preallocated, 0) = 0 AND COALESCE(o.is_archived, 0) = 0 ORDER BY o.created_at DESC, o.id DESC LIMIT 100").fetchall()
        return [(row["id"], f'{row["order_number"]} - {row["patient_name"]}') for row in rows]

    def list_filtered_invoice_order_choices(
        self,
        *,
        client_id: int | None = None,
        date_from: str = "",
        date_to: str = "",
        exclude_invoiced: bool = True,
    ) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,
                       o.order_number,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       c.name AS client_name,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE
                               WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name
                               ELSE ''
                           END
                       ) AS patient_name,
                       COALESCE((
                           SELECT SUM(panel_price.price)
                           FROM (
                               SELECT MAX(COALESCE(cpp.price, tp.price, 0)) AS price
                               FROM order_tests ot_pt
                               INNER JOIN tests t_pt ON t_pt.id = ot_pt.test_id
                               LEFT JOIN test_panels tp ON (
                                   UPPER(TRIM(tp.code)) = UPPER(TRIM(ot_pt.source_label))
                                   OR UPPER(TRIM(tp.name)) = UPPER(TRIM(ot_pt.source_label))
                               )
                               LEFT JOIN client_panel_prices cpp
                                   ON cpp.panel_id = tp.id AND cpp.client_id = o.client_id
                               WHERE ot_pt.order_id = o.id
                                 AND ot_pt.source_label IS NOT NULL AND ot_pt.source_label != ''
                                 AND t_pt.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                               GROUP BY COALESCE(CAST(tp.id AS TEXT), UPPER(TRIM(ot_pt.source_label)))
                           ) AS panel_price
                       ), 0) AS total_amount
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                WHERE COALESCE(o.is_preallocated, 0) = 0
                  AND COALESCE(o.is_archived, 0) = 0
                  AND (? IS NULL OR o.client_id = ?)
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) >= DATE(?))
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) <= DATE(?))
                  AND (
                      ? = 0
                      OR (
                          NOT EXISTS (SELECT 1 FROM invoices i WHERE i.order_id = o.id)
                          AND NOT EXISTS (SELECT 1 FROM invoice_order_links iol WHERE iol.order_id = o.id)
                      )
                  )
                GROUP BY o.id, o.order_number, order_date, c.name, patient_name
                ORDER BY DATE(COALESCE(o.ordered_at, o.created_at)) DESC, o.id DESC
                """,
                (
                    client_id,
                    client_id,
                    date_from,
                    date_from,
                    date_to,
                    date_to,
                    1 if exclude_invoiced else 0,
                ),
            ).fetchall()
        return [
            (
                row["id"],
                f'{row["order_number"]} - {row["patient_name"]} - {row["client_name"] or "No Client"} - {row["order_date"] or ""} - ${float(row["total_amount"] or 0):.2f}',
            )
            for row in rows
        ]

    def list_receipt_order_choices(
        self,
        *,
        client_id: int | None = None,
        date_from: str = "",
        date_to: str = "",
        exclude_receipted: bool = True,
    ) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,
                       o.order_number,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       c.name AS client_name,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE
                               WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name
                               ELSE ''
                           END
                       ) AS patient_name,
                       COALESCE((
                           SELECT SUM(panel_price.price)
                           FROM (
                               SELECT MAX(COALESCE(cpp.price, tp.price, 0)) AS price
                               FROM order_tests ot_pt
                               INNER JOIN tests t_pt ON t_pt.id = ot_pt.test_id
                               LEFT JOIN test_panels tp ON (
                                   UPPER(TRIM(tp.code)) = UPPER(TRIM(ot_pt.source_label))
                                   OR UPPER(TRIM(tp.name)) = UPPER(TRIM(ot_pt.source_label))
                               )
                               LEFT JOIN client_panel_prices cpp
                                   ON cpp.panel_id = tp.id AND cpp.client_id = o.client_id
                               WHERE ot_pt.order_id = o.id
                                 AND ot_pt.source_label IS NOT NULL AND ot_pt.source_label != ''
                                 AND t_pt.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                               GROUP BY COALESCE(CAST(tp.id AS TEXT), UPPER(TRIM(ot_pt.source_label)))
                           ) AS panel_price
                       ), 0) AS total_amount
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                WHERE COALESCE(o.is_preallocated, 0) = 0
                  AND COALESCE(o.is_archived, 0) = 0
                  AND (? IS NULL OR o.client_id = ?)
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) >= DATE(?))
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) <= DATE(?))
                  AND (? = 0 OR NOT EXISTS (SELECT 1 FROM receipts r WHERE r.order_id = o.id))
                GROUP BY o.id, o.order_number, order_date, c.name, patient_name
                ORDER BY DATE(COALESCE(o.ordered_at, o.created_at)) DESC, o.id DESC
                """,
                (
                    client_id,
                    client_id,
                    date_from,
                    date_from,
                    date_to,
                    date_to,
                    1 if exclude_receipted else 0,
                ),
            ).fetchall()
        return [
            (
                row["id"],
                f'{row["order_number"]} - {row["patient_name"]} - {row["client_name"] or "No Client"} - {row["order_date"] or ""} - ${float(row["total_amount"] or 0):.2f}',
            )
            for row in rows
        ]

    def calculate_order_total(self, order_id: int) -> float:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE((
                    SELECT SUM(panel_price.price)
                    FROM (
                        SELECT MAX(COALESCE(cpp.price, tp.price, 0)) AS price
                        FROM order_tests ot_pt
                        INNER JOIN tests t_pt ON t_pt.id = ot_pt.test_id
                        LEFT JOIN test_panels tp ON (
                            UPPER(TRIM(tp.code)) = UPPER(TRIM(ot_pt.source_label))
                            OR UPPER(TRIM(tp.name)) = UPPER(TRIM(ot_pt.source_label))
                        )
                        LEFT JOIN client_panel_prices cpp
                            ON cpp.panel_id = tp.id
                           AND cpp.client_id = (SELECT client_id FROM orders WHERE id = ?)
                        WHERE ot_pt.order_id = ?
                          AND ot_pt.source_label IS NOT NULL AND ot_pt.source_label != ''
                          AND t_pt.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                        GROUP BY COALESCE(CAST(tp.id AS TEXT), UPPER(TRIM(ot_pt.source_label)))
                    ) AS panel_price
                ), 0) AS total
                """,
                (int(order_id), int(order_id)),
            ).fetchone()
        return float(row["total"] if row is not None else 0)

    def get_order_client_id(self, order_id: int) -> int | None:
        with self.connect() as connection:
            row = connection.execute("SELECT client_id FROM orders WHERE id = ?", (int(order_id),)).fetchone()
        if row is None or row["client_id"] is None:
            return None
        return int(row["client_id"])

    def create_invoices_for_orders(
        self,
        order_ids: list[int],
        *,
        invoice_date: str,
        status: str = "issued",
        notes: str | None = None,
        payment_form: str | None = None,
        payment_method: str | None = None,
        currency: str = "MXN",
    ) -> tuple[int, int]:
        created = 0
        skipped = 0
        normalized_order_ids = [int(order_id) for order_id in order_ids]
        with self.connect() as connection:
            for order_id in normalized_order_ids:
                existing = connection.execute(
                    "SELECT id FROM invoices WHERE order_id = ?",
                    (order_id,),
                ).fetchone()
                if existing is not None:
                    skipped += 1
                    continue
                order_row = connection.execute(
                    "SELECT client_id FROM orders WHERE id = ?",
                    (order_id,),
                ).fetchone()
                if order_row is None or order_row["client_id"] is None:
                    skipped += 1
                    continue
                client = self.get_client(int(order_row["client_id"]))
                connection.execute(
                    """
                    INSERT INTO invoices (
                        invoice_number,
                        client_id,
                        order_id,
                        invoice_date,
                        status,
                        total_amount,
                        notes,
                        cfdi_use,
                        payment_form,
                        payment_method,
                        currency,
                        xml_path
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.next_invoice_number(),
                        order_row["client_id"],
                        order_id,
                        invoice_date.strip(),
                        status or "issued",
                        self.calculate_order_total(order_id),
                        notes or None,
                        client.cfdi_use if client is not None else None,
                        payment_form or None,
                        payment_method or None,
                        currency or "MXN",
                        None,
                    ),
                )
                created += 1
        return created, skipped

    def create_client_invoices_for_orders(
        self,
        order_ids: list[int],
        *,
        invoice_date: str,
        status: str = "issued",
        notes: str | None = None,
        payment_form: str | None = None,
        payment_method: str | None = None,
        currency: str = "MXN",
    ) -> tuple[int, int, int]:
        created = 0
        linked_orders = 0
        skipped = 0
        normalized_order_ids = [int(order_id) for order_id in order_ids]
        if not normalized_order_ids:
            return created, linked_orders, skipped

        placeholders = ",".join("?" for _ in normalized_order_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT o.id,
                       o.order_number,
                       o.client_id,
                       c.cfdi_use,
                       COALESCE((
                           SELECT SUM(panel_price.price)
                           FROM (
                               SELECT MAX(COALESCE(cpp.price, tp.price, 0)) AS price
                               FROM order_tests ot_pt
                               INNER JOIN tests t_pt ON t_pt.id = ot_pt.test_id
                               LEFT JOIN test_panels tp ON (
                                   UPPER(TRIM(tp.code)) = UPPER(TRIM(ot_pt.source_label))
                                   OR UPPER(TRIM(tp.name)) = UPPER(TRIM(ot_pt.source_label))
                               )
                               LEFT JOIN client_panel_prices cpp
                                   ON cpp.panel_id = tp.id AND cpp.client_id = o.client_id
                               WHERE ot_pt.order_id = o.id
                                 AND ot_pt.source_label IS NOT NULL AND ot_pt.source_label != ''
                                 AND t_pt.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                               GROUP BY COALESCE(CAST(tp.id AS TEXT), UPPER(TRIM(ot_pt.source_label)))
                           ) AS panel_price
                       ), 0) AS total_amount
                FROM orders o
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                WHERE o.id IN ({placeholders})
                  AND COALESCE(o.is_preallocated, 0) = 0
                GROUP BY o.id, o.order_number, o.client_id, c.cfdi_use
                ORDER BY o.client_id, o.id
                """,
                tuple(normalized_order_ids),
            ).fetchall()
            last_invoice_id_row = connection.execute("SELECT id FROM invoices ORDER BY id DESC LIMIT 1").fetchone()
            next_invoice_id = (int(last_invoice_id_row["id"]) + 1) if last_invoice_id_row is not None else 1
            orders_by_client: dict[int, list[sqlite3.Row]] = {}
            found_ids = {int(row["id"]) for row in rows}
            skipped += len(set(normalized_order_ids) - found_ids)
            for row in rows:
                order_id = int(row["id"])
                if row["client_id"] is None:
                    skipped += 1
                    continue
                existing = connection.execute(
                    """
                    SELECT 1
                    FROM invoices i
                    WHERE i.order_id = ?
                    UNION
                    SELECT 1
                    FROM invoice_order_links iol
                    WHERE iol.order_id = ?
                    LIMIT 1
                    """,
                    (order_id, order_id),
                ).fetchone()
                if existing is not None:
                    skipped += 1
                    continue
                orders_by_client.setdefault(int(row["client_id"]), []).append(row)

            for client_id, client_orders in orders_by_client.items():
                order_numbers = ", ".join(str(row["order_number"]) for row in client_orders)
                invoice_notes = notes or None
                if order_numbers:
                    invoice_notes = f"{invoice_notes}\nOrders: {order_numbers}" if invoice_notes else f"Orders: {order_numbers}"
                cursor = connection.execute(
                    """
                    INSERT INTO invoices (
                        invoice_number,
                        client_id,
                        order_id,
                        invoice_date,
                        status,
                        total_amount,
                        notes,
                        cfdi_use,
                        payment_form,
                        payment_method,
                        currency,
                        xml_path
                    )
                    VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"INV-{next_invoice_id:06d}",
                        client_id,
                        invoice_date.strip(),
                        status or "issued",
                        sum(float(row["total_amount"] or 0) for row in client_orders),
                        invoice_notes,
                        client_orders[0]["cfdi_use"],
                        payment_form or None,
                        payment_method or None,
                        currency or "MXN",
                        None,
                    ),
                )
                invoice_id = int(cursor.lastrowid)
                next_invoice_id += 1
                for row in client_orders:
                    connection.execute(
                        "INSERT INTO invoice_order_links (invoice_id, order_id) VALUES (?, ?)",
                        (invoice_id, int(row["id"])),
                    )
                    linked_orders += 1
                created += 1
        return created, linked_orders, skipped

    def create_receipt_for_order(
        self,
        order_id: int,
        *,
        receipt_date: str,
        notes: str | None = None,
        payment_form: str | None = None,
        payment_method: str | None = None,
        currency: str = "MXN",
    ) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM orders WHERE id = ? AND COALESCE(is_preallocated, 0) = 0",
                (int(order_id),),
            ).fetchone()
            if row is None:
                raise ValueError("Order not found.")
            existing = connection.execute("SELECT id FROM receipts WHERE order_id = ?", (int(order_id),)).fetchone()
            if existing is not None:
                raise sqlite3.IntegrityError("A receipt already exists for this order.")
            cursor = connection.execute(
                """
                INSERT INTO receipts (
                    receipt_number,
                    order_id,
                    receipt_date,
                    total_amount,
                    notes,
                    payment_form,
                    payment_method,
                    currency
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.next_receipt_number(),
                    int(order_id),
                    receipt_date.strip(),
                    self.calculate_order_total(int(order_id)),
                    notes or None,
                    payment_form or None,
                    payment_method or None,
                    currency or "MXN",
                ),
            )
            return int(cursor.lastrowid)

    def list_invoices(self) -> list[InvoiceRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT i.id,
                       i.invoice_number,
                       i.client_id,
                       c.name AS client_name,
                       i.order_id,
                       CASE
                           WHEN i.order_id IS NOT NULL THEN o.order_number
                           WHEN COUNT(iol.order_id) > 0 THEN CAST(COUNT(iol.order_id) AS TEXT) || ' orders'
                           ELSE NULL
                       END AS order_number,
                       i.invoice_date, i.status, i.total_amount, i.notes, i.cfdi_use, i.payment_form, i.payment_method, i.currency, i.xml_path,
                       i.cfdi_uuid, i.cfdi_status, i.cfdi_xml_path, i.cfdi_pdf_path, i.cfdi_provider_id, i.cfdi_stamped_at
                FROM invoices i
                LEFT JOIN clients c ON c.id = i.client_id
                LEFT JOIN orders o ON o.id = i.order_id
                LEFT JOIN invoice_order_links iol ON iol.invoice_id = i.id
                GROUP BY i.id, i.invoice_number, i.client_id, c.name, i.order_id, o.order_number,
                         i.invoice_date, i.status, i.total_amount, i.notes, i.cfdi_use, i.payment_form, i.payment_method, i.currency, i.xml_path,
                         i.cfdi_uuid, i.cfdi_status, i.cfdi_xml_path, i.cfdi_pdf_path, i.cfdi_provider_id, i.cfdi_stamped_at
                ORDER BY i.invoice_date DESC, i.id DESC
                """
            ).fetchall()
        return [InvoiceRecord(**dict(row)) for row in rows]

    def list_invoice_orders(self, invoice_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                WITH invoice_orders AS (
                    SELECT order_id
                    FROM invoices
                    WHERE id = ? AND order_id IS NOT NULL
                    UNION
                    SELECT order_id
                    FROM invoice_order_links
                    WHERE invoice_id = ?
                )
                SELECT o.id,
                       o.order_number,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       c.name AS client_name,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE
                               WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name
                               ELSE ''
                           END
                       ) AS patient_name,
                       COALESCE((
                           SELECT SUM(panel_price.price)
                           FROM (
                               SELECT MAX(COALESCE(cpp.price, tp.price, 0)) AS price
                               FROM order_tests ot_pt
                               INNER JOIN tests t_pt ON t_pt.id = ot_pt.test_id
                               LEFT JOIN test_panels tp ON (
                                   UPPER(TRIM(tp.code)) = UPPER(TRIM(ot_pt.source_label))
                                   OR UPPER(TRIM(tp.name)) = UPPER(TRIM(ot_pt.source_label))
                               )
                               LEFT JOIN client_panel_prices cpp
                                   ON cpp.panel_id = tp.id AND cpp.client_id = o.client_id
                               WHERE ot_pt.order_id = o.id
                                 AND ot_pt.source_label IS NOT NULL AND ot_pt.source_label != ''
                                 AND t_pt.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                               GROUP BY COALESCE(CAST(tp.id AS TEXT), UPPER(TRIM(ot_pt.source_label)))
                           ) AS panel_price
                       ), 0) AS total_amount,
                       GROUP_CONCAT(
                           DISTINCT CASE
                               WHEN ot.source_label IS NOT NULL AND ot.source_label != '' THEN ot.source_label
                               ELSE NULL
                           END
                       ) AS panels
                FROM invoice_orders io
                INNER JOIN orders o ON o.id = io.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                GROUP BY o.id, o.order_number, order_date, c.name, patient_name
                ORDER BY DATE(COALESCE(o.ordered_at, o.created_at)), o.id
                """,
                (int(invoice_id), int(invoice_id)),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_invoice_order_panels(self, invoice_id: int) -> list[dict[str, Any]]:
        """One row per (order, panel) with that panel's price for the order's client.

        The price is the client-specific panel price (client_panel_prices) when
        present, otherwise the panel's default price (test_panels.price). The
        panel is resolved from order_tests.source_label, matched to test_panels
        by code or name.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                WITH invoice_orders AS (
                    SELECT order_id FROM invoices WHERE id = ? AND order_id IS NOT NULL
                    UNION
                    SELECT order_id FROM invoice_order_links WHERE invoice_id = ?
                )
                SELECT o.order_number,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != ''
                                THEN ' ' || p.middle_name ELSE '' END
                       ) AS patient_name,
                       COALESCE(tp.name, ot.source_label) AS panel,
                       COALESCE(MAX(COALESCE(cpp.price, tp.price, 0)), 0) AS panel_total
                FROM invoice_orders io
                INNER JOIN orders o ON o.id = io.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN order_tests ot ON ot.order_id = o.id
                INNER JOIN tests t ON t.id = ot.test_id
                LEFT JOIN test_panels tp ON (
                    UPPER(TRIM(tp.code)) = UPPER(TRIM(ot.source_label))
                    OR UPPER(TRIM(tp.name)) = UPPER(TRIM(ot.source_label))
                )
                LEFT JOIN client_panel_prices cpp
                    ON cpp.panel_id = tp.id AND cpp.client_id = o.client_id
                WHERE ot.source_label IS NOT NULL AND ot.source_label != ''
                  AND t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                GROUP BY o.id, o.order_number, order_date, patient_name, panel
                ORDER BY order_date, o.id, panel
                """,
                (int(invoice_id), int(invoice_id)),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_invoice_tests(self, invoice_id: int) -> list[dict[str, Any]]:
        """One row per individual test on the invoice, with order/patient context."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                WITH invoice_orders AS (
                    SELECT order_id FROM invoices WHERE id = ? AND order_id IS NOT NULL
                    UNION
                    SELECT order_id FROM invoice_order_links WHERE invoice_id = ?
                )
                SELECT o.order_number,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != ''
                                THEN ' ' || p.middle_name ELSE '' END
                       ) AS patient_name,
                       COALESCE(
                           (SELECT tp.name FROM test_panels tp
                             WHERE UPPER(TRIM(tp.code)) = UPPER(TRIM(ot.source_label))
                                OR UPPER(TRIM(tp.name)) = UPPER(TRIM(ot.source_label))
                             LIMIT 1),
                           ot.source_label
                       ) AS panel,
                       COALESCE(NULLIF(ot.display_name, ''), t.name) AS test_name,
                       t.code AS test_code,
                       COALESCE(t.price, 0) AS price
                FROM invoice_orders io
                INNER JOIN orders o ON o.id = io.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN order_tests ot ON ot.order_id = o.id
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                ORDER BY order_date, o.id, ot.sort_order, t.name
                """,
                (int(invoice_id), int(invoice_id)),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_receipts(self) -> list[ReceiptRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT r.id,
                       r.receipt_number,
                       r.order_id,
                       o.order_number,
                       c.name AS client_name,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE
                               WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name
                               ELSE ''
                           END
                       ) AS patient_name,
                       r.receipt_date,
                       r.total_amount,
                       r.notes,
                       r.payment_form,
                       r.payment_method,
                       r.currency
                FROM receipts r
                INNER JOIN orders o ON o.id = r.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                ORDER BY r.receipt_date DESC, r.id DESC
                """
            ).fetchall()
        return [ReceiptRecord(**dict(row)) for row in rows]

    def create_invoice(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            resolved_total = payload.get("total_amount")
            order_id = payload.get("order_id")
            if order_id and (resolved_total is None or float(resolved_total) == 0):
                resolved_total = self.calculate_order_total(int(order_id))
            cursor = connection.execute(
                "INSERT INTO invoices (invoice_number, client_id, order_id, invoice_date, status, total_amount, notes, cfdi_use, payment_form, payment_method, currency, xml_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (payload.get("invoice_number") or self.next_invoice_number()).strip(),
                    payload.get("client_id"),
                    order_id,
                    payload["invoice_date"].strip(),
                    payload.get("status") or "issued",
                    resolved_total or 0,
                    payload.get("notes") or None,
                    payload.get("cfdi_use") or None,
                    payload.get("payment_form") or None,
                    payload.get("payment_method") or None,
                    payload.get("currency") or "MXN",
                    payload.get("xml_path") or None,
                ),
            )
            return int(cursor.lastrowid)

    def delete_invoice(self, invoice_id: int) -> bool:
        """Permanently delete an invoice.

        Foreign keys are enabled per connection, so the ON DELETE CASCADE on
        invoice_order_links removes the order links too, freeing those orders to
        be re-invoiced. Returns True when a row was removed.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM invoices WHERE id = ?", (int(invoice_id),)
            )
            return cursor.rowcount > 0

    def get_invoice(self, invoice_id: int) -> InvoiceRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT i.id, i.invoice_number, i.client_id, c.name AS client_name,
                       i.order_id, o.order_number,
                       i.invoice_date, i.status, i.total_amount, i.notes, i.cfdi_use,
                       i.payment_form, i.payment_method, i.currency, i.xml_path,
                       i.cfdi_uuid, i.cfdi_status, i.cfdi_xml_path, i.cfdi_pdf_path,
                       i.cfdi_provider_id, i.cfdi_stamped_at
                FROM invoices i
                LEFT JOIN clients c ON c.id = i.client_id
                LEFT JOIN orders o ON o.id = i.order_id
                WHERE i.id = ?
                """,
                (int(invoice_id),),
            ).fetchone()
        return InvoiceRecord(**dict(row)) if row is not None else None

    def record_invoice_stamp(
        self,
        invoice_id: int,
        *,
        uuid: str,
        provider_id: str,
        xml_path: str | None = None,
        pdf_path: str | None = None,
        stamped_at: str,
    ) -> None:
        """Persist the PAC stamping result and mark the invoice issued + stamped."""
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE invoices
                SET cfdi_uuid = ?,
                    cfdi_provider_id = ?,
                    cfdi_xml_path = ?,
                    cfdi_pdf_path = ?,
                    cfdi_status = 'stamped',
                    cfdi_stamped_at = ?,
                    status = CASE WHEN status = 'draft' THEN 'issued' ELSE status END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    uuid.strip(),
                    str(provider_id).strip(),
                    xml_path or None,
                    pdf_path or None,
                    stamped_at,
                    int(invoice_id),
                ),
            )

    def mark_invoice_cfdi_cancelled(self, invoice_id: int) -> None:
        """Mark a stamped invoice's CFDI as cancelled at the PAC/SAT."""
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE invoices
                SET cfdi_status = 'cancelled',
                    status = 'cancelled',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(invoice_id),),
            )
