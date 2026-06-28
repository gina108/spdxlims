from __future__ import annotations

from pathlib import Path
from typing import Sequence

from spdxlims.catalog_excel import _write_workbook_template


def write_admin_export_workbook(path: str | Path, sheets: dict[str, list[list[str]]]) -> Path:
    return _write_workbook_template(path, sheets)


def build_invoice_excel_sheet(
    invoice_number: str,
    client_name: str,
    invoice_date: str,
    status: str,
    total: str,
    orders: list[dict],
) -> dict[str, list[list[str]]]:
    rows: list[list[str]] = [
        ['Invoice Number', 'Client', 'Date', 'Status', 'Total'],
        [invoice_number, client_name, invoice_date, status, total],
        [],
        ['Order Number', 'Order Date', 'Patient', 'Panel', 'Amount'],
    ]
    for order in orders:
        rows.append([
            str(order.get('order_number') or ''),
            str(order.get('order_date') or ''),
            str(order.get('patient_name') or ''),
            str(order.get('panel') or ''),
            f"{float(order.get('panel_total') or 0):.2f}",
        ])
    return {'Invoice': rows}


def build_client_results_sheet(
    rows: Sequence[tuple[str, str, str, str, str, str]],
) -> dict[str, list[list[str]]]:
    return {
        'Results': [
            ['Date', 'Patient', 'Panel', 'Test', 'Result', 'Unit'],
            *[list(row) for row in rows],
        ]
    }


def build_marketing_list_sheet(
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> dict[str, list[list[str]]]:
    return {
        'MarketingList': [list(header), *[list(row) for row in rows]],
    }


def build_admin_export_sheets(
    billing_rows: Sequence[Sequence[str]],
    inventory_rows: Sequence[Sequence[str]],
    invoice_rows: Sequence[Sequence[str]],
    supplier_rows: Sequence[Sequence[str]],
    movement_rows: Sequence[Sequence[str]],
) -> dict[str, list[list[str]]]:
    return {
        'Customers': [['Customer', 'Phone', 'Email', 'Open Balance', 'Invoice Count'], *[list(row) for row in billing_rows]],
        'Inventory': [['SKU', 'Name', 'Unit', 'On Hand', 'Reorder Level', 'Unit Cost'], *[list(row) for row in inventory_rows]],
        'Invoices': [['Invoice Number', 'Customer', 'Invoice Date', 'Status', 'Total Amount', 'Order Number', 'Notes'], *[list(row) for row in invoice_rows]],
        'Suppliers': [['Supplier Name', 'Tax ID (RFC)', 'Phone', 'Email'], *[list(row) for row in supplier_rows]],
        'StockMovements': [['Inventory Item', 'Supplier', 'Movement Type', 'Quantity', 'Unit Cost', 'Movement Date'], *[list(row) for row in movement_rows]],
    }
