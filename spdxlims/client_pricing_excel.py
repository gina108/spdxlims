from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

from spdxlims.catalog_excel import _read_workbook, _write_workbook_template
from spdxlims.database import ClientRecord, TestRecord

CLIENT_PRICE_SHEET = "Client Prices"
CLIENT_REFERENCE_SHEET = "Default Prices"
CLIENT_DIRECTORY_SHEET = "Clients"
CLIENT_INSTRUCTIONS_SHEET = "Instructions"
CLIENT_HEADER_PREFIX = "client:"
FIXED_COLUMNS = ["test_code", "test_name", "default_price"]


def write_client_price_workbook(path: str | Path, sheets: dict[str, list[list[str]]]) -> Path:
    return _write_workbook_template(path, sheets)


def build_client_price_sheets(
    test_records: Sequence[TestRecord],
    clients: Sequence[ClientRecord],
    overrides: dict[tuple[int, int], float],
) -> dict[str, list[list[str]]]:
    header = FIXED_COLUMNS + [f"{CLIENT_HEADER_PREFIX}{client.id}:{client.name}" for client in clients]
    price_rows: list[list[str]] = [header]
    reference_rows: list[list[str]] = [header]
    for test in test_records:
        default_price = _format_price(test.price)
        editable_row = [test.code, test.name, default_price]
        reference_row = [test.code, test.name, default_price]
        for client in clients:
            override = overrides.get((client.id, test.id))
            editable_row.append(_format_price(override) if override is not None else "")
            reference_row.append(default_price)
        price_rows.append(editable_row)
        reference_rows.append(reference_row)

    client_rows: list[list[str]] = [["client_id", "client_name", "status"]]
    for client in clients:
        client_rows.append([str(client.id), client.name, "active" if client.is_active else "archived"])

    instructions = [
        ["Section / Seccion", "Guidance / Guia"],
        ["Editable sheet / Hoja editable", "Edit only the Client Prices sheet. Blank cells mean use the default test price. / Edite solo la hoja Client Prices. Las celdas en blanco significan usar el precio predeterminado de la prueba."],
        ["Columns / Columnas", "The first columns are test_code, test_name, and default_price. Every remaining column belongs to one client. / Las primeras columnas son test_code, test_name y default_price. Cada columna restante pertenece a un cliente."],
        ["Client headers / Encabezados de clientes", "Keep client header cells unchanged so the importer can map prices back to the right client. / Mantenga sin cambios los encabezados de clientes para que la importacion pueda asignar los precios al cliente correcto."],
        ["Blank values / Valores vacios", "Leave a client price blank to remove any custom override and fall back to the default test price. / Deje vacio un precio de cliente para quitar cualquier precio personalizado y volver al precio predeterminado de la prueba."],
        ["Numbers only / Solo numeros", "Enter plain numbers like 250 or 250.50. / Ingrese numeros simples como 250 o 250.50."],
    ]

    return {
        CLIENT_PRICE_SHEET: price_rows,
        CLIENT_REFERENCE_SHEET: reference_rows,
        CLIENT_DIRECTORY_SHEET: client_rows,
        CLIENT_INSTRUCTIONS_SHEET: instructions,
    }


def read_client_price_matrix(path: str | Path) -> tuple[list[dict[str, str]], list[tuple[int, str]]]:
    workbook = _read_workbook(Path(path))
    rows = workbook.get(CLIENT_PRICE_SHEET)
    if not rows:
        raise ValueError(f"The workbook is missing the {CLIENT_PRICE_SHEET} sheet.")
    header = [_normalize_header(cell) for cell in rows[0]]
    if header[: len(FIXED_COLUMNS)] != FIXED_COLUMNS:
        raise ValueError("The Client Prices sheet must start with test_code, test_name, default_price.")
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


def _parse_client_header(raw_header: str) -> tuple[int, str]:
    header = str(raw_header).strip()
    if not header.startswith(CLIENT_HEADER_PREFIX):
        raise ValueError(f"Invalid client column header: {header}")
    payload = header[len(CLIENT_HEADER_PREFIX):]
    client_id_text, _separator, label = payload.partition(":")
    if not client_id_text.isdigit():
        raise ValueError(f"Invalid client column header: {header}")
    return int(client_id_text), label.strip()


def _normalize_header(value: str) -> str:
    return str(value).strip().lower()


def _format_price(value: float | None) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def parse_optional_price(value: str) -> float | None:
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        return float(Decimal(normalized))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid price value: {normalized}") from exc
