from __future__ import annotations
import sqlite3
from typing import Any

from spdxlims.db.records import ClientRecord, BillingCustomerRecord
from spdxlims.i18n import tr


class ClientsMixin:
    def list_clients(self, *, status_filter: str = 'all') -> list[ClientRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, phone, email, tax_id, fiscal_regime, postal_code, cfdi_use, is_active
                FROM clients
                WHERE (? = 'all' OR (? = 'active' AND is_active = 1) OR (? = 'archived' AND is_active = 0))
                ORDER BY is_active DESC, name, id
                """,
                (status_filter, status_filter, status_filter),
            ).fetchall()
        return [ClientRecord(**dict(row)) for row in rows]

    def list_billing_customers(self) -> list[BillingCustomerRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.name, c.phone, c.email, c.is_active,
                       COALESCE(SUM(CASE WHEN i.status IN ('draft', 'issued') THEN i.total_amount ELSE 0 END), 0) AS outstanding_balance,
                       COUNT(i.id) AS invoice_count
                FROM clients c
                LEFT JOIN invoices i ON i.client_id = c.id
                GROUP BY c.id, c.name, c.phone, c.email, c.is_active
                ORDER BY c.is_active DESC, c.name, c.id
                """
            ).fetchall()
        return [BillingCustomerRecord(**dict(row)) for row in rows]

    def list_client_choices(self, *, active_only: bool = False, include_ids: list[int] | None = None) -> list[tuple[int, str]]:
        include_ids = [int(value) for value in (include_ids or []) if value is not None]
        with self.connect() as connection:
            if active_only and include_ids:
                placeholders = ", ".join("?" for _ in include_ids)
                rows = connection.execute(
                    f"SELECT id, name, phone, is_active FROM clients WHERE is_active = 1 OR id IN ({placeholders}) ORDER BY is_active DESC, name, id",
                    include_ids,
                ).fetchall()
            elif active_only:
                rows = connection.execute(
                    "SELECT id, name, phone, is_active FROM clients WHERE is_active = 1 ORDER BY name, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, name, phone, is_active FROM clients ORDER BY is_active DESC, name, id"
                ).fetchall()
        return [
            (
                row["id"],
                ((row["name"] if not row["phone"] else f'{row["name"]} ({row["phone"]})') + ('' if row["is_active"] else f' [{tr("Archived")}]')),
            )
            for row in rows
        ]

    def create_client(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO clients (name, phone, email, tax_id, fiscal_regime, postal_code, cfdi_use, is_active, auto_invoice_enabled, auto_invoice_frequency) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    payload["name"].strip(),
                    str(payload.get("phone") or "").strip() or None,
                    str(payload.get("email") or "").strip() or None,
                    str(payload.get("tax_id") or "").strip() or None,
                    str(payload.get("fiscal_regime") or "").strip() or None,
                    str(payload.get("postal_code") or "").strip() or None,
                    str(payload.get("cfdi_use") or "").strip() or None,
                    1 if payload.get("auto_invoice_enabled") else 0,
                    str(payload.get("auto_invoice_frequency") or "").strip() or None,
                ),
            )
            return int(cursor.lastrowid)

    def update_client(self, client_id: int, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE clients SET name = ?, phone = ?, email = ?, tax_id = ?, fiscal_regime = ?, postal_code = ?, cfdi_use = ?, auto_invoice_enabled = ?, auto_invoice_frequency = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    payload["name"].strip(),
                    str(payload.get("phone") or "").strip() or None,
                    str(payload.get("email") or "").strip() or None,
                    str(payload.get("tax_id") or "").strip() or None,
                    str(payload.get("fiscal_regime") or "").strip() or None,
                    str(payload.get("postal_code") or "").strip() or None,
                    str(payload.get("cfdi_use") or "").strip() or None,
                    1 if payload.get("auto_invoice_enabled") else 0,
                    str(payload.get("auto_invoice_frequency") or "").strip() or None,
                    client_id,
                ),
            )

    def archive_client(self, client_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE clients SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (client_id,))

    def unarchive_client(self, client_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE clients SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (client_id,))

    def get_client(self, client_id: int) -> ClientRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT id, name, phone, email, tax_id, fiscal_regime, postal_code, cfdi_use, is_active, auto_invoice_enabled, auto_invoice_frequency, auto_invoice_last_run FROM clients WHERE id = ?", (client_id,)).fetchone()
        return ClientRecord(**dict(row)) if row is not None else None

    def list_auto_invoice_clients(self) -> list[dict[str, Any]]:
        """Active clients with auto-invoicing enabled, for the scheduler."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, auto_invoice_frequency, auto_invoice_last_run
                FROM clients
                WHERE is_active = 1
                  AND auto_invoice_enabled = 1
                  AND auto_invoice_frequency IS NOT NULL
                  AND auto_invoice_frequency != ''
                ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_auto_invoice_run(self, client_id: int, run_date: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE clients SET auto_invoice_last_run = ? WHERE id = ?",
                (run_date, int(client_id)),
            )

    def list_uninvoiced_order_ids_for_client(self, client_id: int) -> list[int]:
        """Order ids for a client not yet covered by any invoice (single or grouped)."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id
                FROM orders o
                WHERE o.client_id = ?
                  AND COALESCE(o.is_preallocated, 0) = 0
                  AND COALESCE(o.is_archived, 0) = 0
                  AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.order_id = o.id)
                  AND NOT EXISTS (SELECT 1 FROM invoice_order_links iol WHERE iol.order_id = o.id)
                ORDER BY o.id
                """,
                (int(client_id),),
            ).fetchall()
        return [int(row["id"]) for row in rows]
