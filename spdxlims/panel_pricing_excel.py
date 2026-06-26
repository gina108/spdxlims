from __future__ import annotations

from pathlib import Path
from typing import Sequence

from spdxlims.catalog_excel import _read_workbook, _write_workbook_template
from spdxlims.client_pricing_excel import (
    CLIENT_HEADER_PREFIX,
    _format_price,
    _normalize_header,
    _parse_client_header,
    parse_optional_price,  # re-exported for callers
)
from spdxlims.database import ClientRecord, PanelRecord

PANEL_PRICE_SHEET = "Panel Prices"
PANEL_REFERENCE_SHEET = "Default Prices"
PANEL_DIRECTORY_SHEET = "Clients"
PANEL_INSTRUCTIONS_SHEET = "Instructions"
FIXED_COLUMNS = ["panel_code", "panel_name", "default_price"]

__all__ = [
    "PANEL_PRICE_SHEET",
    "build_panel_price_sheets",
    "read_panel_price_matrix",
    "write_panel_price_workbook",
    "parse_optional_price",
]


def write_panel_price_workbook(path: str | Path, sheets: dict[str, list[list[str]]]) -> Path:
    return _write_workbook_template(path, sheets)


def build_panel_price_sheets(
    panel_records: Sequence[PanelRecord],
    clients: Sequence[ClientRecord],
    overrides: dict[tuple[int, int], float],
) -> dict[str, list[list[str]]]:
    header = FIXED_COLUMNS + [f"{CLIENT_HEADER_PREFIX}{client.id}:{client.name}" for client in clients]
    price_rows: list[list[str]] = [header]
    reference_rows: list[list[str]] = [header]
    for panel in panel_records:
        default_price = _format_price(panel.price)
        editable_row = [panel.code, panel.name, default_price]
        reference_row = [panel.code, panel.name, default_price]
        for client in clients:
            override = overrides.get((client.id, panel.id))
            editable_row.append(_format_price(override) if override is not None else "")
            reference_row.append(default_price)
        price_rows.append(editable_row)
        reference_rows.append(reference_row)

    client_rows: list[list[str]] = [["client_id", "client_name", "status"]]
    for client in clients:
        client_rows.append([str(client.id), client.name, "active" if client.is_active else "archived"])

    instructions = [
        ["Section / Seccion", "Guidance / Guia"],
        ["Editable sheet / Hoja editable", "Edit only the Panel Prices sheet. / Edite solo la hoja Panel Prices."],
        ["Default price / Precio predeterminado", "Edit the default_price column to set the base price for a panel. / Edite la columna default_price para fijar el precio base de un panel."],
        ["Columns / Columnas", "The first columns are panel_code, panel_name, and default_price. Every remaining column belongs to one client. / Las primeras columnas son panel_code, panel_name y default_price. Cada columna restante pertenece a un cliente."],
        ["Client headers / Encabezados de clientes", "Keep client header cells unchanged so the importer can map prices back to the right client. / Mantenga sin cambios los encabezados de clientes para que la importacion pueda asignar los precios al cliente correcto."],
        ["Blank values / Valores vacios", "Leave a client price blank to remove any custom override and fall back to the default panel price. / Deje vacio un precio de cliente para quitar cualquier precio personalizado y volver al precio predeterminado del panel."],
        ["Numbers only / Solo numeros", "Enter plain numbers like 250 or 250.50. / Ingrese numeros simples como 250 o 250.50."],
    ]

    return {
        PANEL_PRICE_SHEET: price_rows,
        PANEL_REFERENCE_SHEET: reference_rows,
        PANEL_DIRECTORY_SHEET: client_rows,
        PANEL_INSTRUCTIONS_SHEET: instructions,
    }


def read_panel_price_matrix(path: str | Path) -> tuple[list[dict[str, str]], list[tuple[int, str]]]:
    workbook = _read_workbook(Path(path))
    rows = workbook.get(PANEL_PRICE_SHEET)
    if not rows:
        raise ValueError(f"The workbook is missing the {PANEL_PRICE_SHEET} sheet.")
    header = [_normalize_header(cell) for cell in rows[0]]
    if header[: len(FIXED_COLUMNS)] != FIXED_COLUMNS:
        raise ValueError("The Panel Prices sheet must start with panel_code, panel_name, default_price.")
    client_columns: list[tuple[int, str]] = []
    for raw_header in rows[0][len(FIXED_COLUMNS):]:
        client_id, label = _parse_client_header(raw_header)
        client_columns.append((client_id, label))
    parsed_rows: list[dict[str, str]] = []
    for row_number, values in enumerate(rows[1:], start=2):
        padded = list(values) + [""] * max(0, len(header) - len(values))
        if not any(str(cell).strip() for cell in padded):
            continue
        row = {header[index]: str(padded[index]).strip() for index in range(len(header))}
        row["__row_number__"] = str(row_number)
        parsed_rows.append(row)
    return parsed_rows, client_columns
