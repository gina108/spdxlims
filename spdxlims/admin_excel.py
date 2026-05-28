from __future__ import annotations

from pathlib import Path
from typing import Sequence

from spdxlims.catalog_excel import _write_workbook_template


def write_admin_export_workbook(path: str | Path, sheets: dict[str, list[list[str]]]) -> Path:
    return _write_workbook_template(path, sheets)


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
