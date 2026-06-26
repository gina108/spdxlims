"""Automatic creation of internal (non-CFDI) invoices on a per-client cadence.

A client can opt into having its un-invoiced orders batched into a draft invoice
on a recurring schedule. The scheduler runs once at application startup; for each
opted-in client it checks whether the next due date has been reached and, if so,
groups all of that client's un-invoiced orders into a single draft invoice.

These are the internal invoices (``INV-...``), not the official CFDI facturas.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import TYPE_CHECKING

from spdxlims.i18n import tr
from spdxlims.log import get_logger

if TYPE_CHECKING:
    from spdxlims.database import Database

_log = get_logger(__name__)

# Frequency codes are stored verbatim in clients.auto_invoice_frequency.
FREQ_MENSUAL = "mensual"
FREQ_QUINCENAL = "quincenal"
FREQ_SEMANAL = "semanal"
FREQ_2_SEMANAS = "2_semanas"
FREQ_3_SEMANAS = "3_semanas"
FREQ_4_SEMANAS = "4_semanas"

# (code, English label key passed through tr()) in display order.
FREQUENCY_OPTIONS: tuple[tuple[str, str], ...] = (
    (FREQ_MENSUAL, "Monthly"),
    (FREQ_QUINCENAL, "Twice a month (1st & 16th)"),
    (FREQ_SEMANAL, "Every week"),
    (FREQ_2_SEMANAS, "Every 2 weeks"),
    (FREQ_3_SEMANAS, "Every 3 weeks"),
    (FREQ_4_SEMANAS, "Every 4 weeks"),
)

_FIXED_DAYS = {
    FREQ_SEMANAL: 7,
    FREQ_2_SEMANAS: 14,
    FREQ_3_SEMANAS: 21,
    FREQ_4_SEMANAS: 28,
}


def frequency_label(code: str | None) -> str:
    for option_code, label in FREQUENCY_OPTIONS:
        if option_code == code:
            return tr(label)
    return ""


def _add_one_month(value: date) -> date:
    month = value.month % 12 + 1
    year = value.year + (1 if value.month == 12 else 0)
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def next_due_date(frequency: str, last_run: date) -> date | None:
    """The first date on or after which a new run is due, given the last run."""
    if frequency == FREQ_MENSUAL:
        return _add_one_month(last_run)
    if frequency == FREQ_QUINCENAL:
        # Twice a month on the 1st and 16th.
        if last_run.day < 16:
            return last_run.replace(day=16)
        return _add_one_month(last_run.replace(day=1))
    days = _FIXED_DAYS.get(frequency)
    if days is None:
        return None
    return last_run + timedelta(days=days)


def is_due(frequency: str, last_run: date, today: date) -> bool:
    due = next_due_date(frequency, last_run)
    return due is not None and today >= due


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def run_auto_invoicing(database: "Database", today: date | None = None) -> int:
    """Create due draft invoices for opted-in clients. Returns invoices created.

    On a client's first eligible run (no recorded last run) the schedule is only
    initialized -- no invoice is generated -- so enabling the option never causes
    a surprise bill covering the client's entire un-invoiced history.
    """
    today = today or date.today()
    created_total = 0
    try:
        clients = database.list_auto_invoice_clients()
    except Exception:  # noqa: BLE001 - startup must never be blocked by this
        _log.exception("Failed to load clients for auto-invoicing")
        return 0

    for client in clients:
        client_id = int(client["id"])
        frequency = client["auto_invoice_frequency"]
        last_run = _parse_date(client["auto_invoice_last_run"])
        try:
            if last_run is None:
                database.mark_auto_invoice_run(client_id, today.isoformat())
                continue
            if not is_due(frequency, last_run, today):
                continue
            order_ids = database.list_uninvoiced_order_ids_for_client(client_id)
            if order_ids:
                created, _linked, _skipped = database.create_client_invoices_for_orders(
                    order_ids,
                    invoice_date=today.isoformat(),
                    status="draft",
                    notes=tr("Auto-generated invoice"),
                )
                created_total += created
            database.mark_auto_invoice_run(client_id, today.isoformat())
        except Exception:  # noqa: BLE001 - one bad client must not stop the rest
            _log.exception("Auto-invoicing failed for client %s", client_id)

    if created_total:
        _log.info("Auto-invoicing created %s draft invoice(s)", created_total)
    return created_total
