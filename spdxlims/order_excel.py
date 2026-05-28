from __future__ import annotations

from pathlib import Path

from spdxlims.catalog_excel import _read_template_rows, _write_workbook_template

ORDER_IMPORT_COLUMNS = [
    "order_number",
    "accession_id",
    "sample_id",
    "patient_code",
    "first_name",
    "last_name",
    "middle_name",
    "sex",
    "date_of_birth",
    "age_value",
    "age_unit",
    "phone",
    "email",
    "address",
    "national_id",
    "doctor",
    "client",
    "panel_codes",
    "status",
    "notes",
]

ORDER_TEMPLATE_SHEETS: dict[str, list[list[str]]] = {
    "Orders": [
        ORDER_IMPORT_COLUMNS,
        [
            "",
            "",
            "",
            "P-001",
            "Maria",
            "Lopez",
            "",
            "F",
            "1988-04-17",
            "",
            "",
            "",
            "maria.lopez@example.com",
            "Street 123",
            "CURP/RFC optional",
            "Dr. Example",
            "",
            "BH",
            "draft",
            "",
        ],
    ],
    "Instructions": [
        ["Section / Seccion", "Guidance / Guia"],
        ["Required columns", "first_name and panel_codes are required. last_name may be blank. Patient rows are created automatically when no match is found."],
        ["Patient matching", "patient_code is reused when present. Otherwise the import matches active patients by first_name, last_name, middle_name, and date_of_birth. Blank last_name is allowed."],
        ["Patient fields", "Use patient_code, first_name, last_name, middle_name, sex, date_of_birth, age_value, age_unit, phone, email, address, and national_id to create the patient."],
        ["Panels", "Use panel catalog codes separated by commas, semicolons, pipes, or line breaks. Example: BH;QS."],
        ["Order numbers", "Leave order_number blank to assign the next automatic number."],
        ["Status", "Use draft or in_progress. Blank defaults to draft."],
    ],
}


def build_order_import_template_sheets(
    *,
    clients: list[tuple[object, str]] | None = None,
    panels: list[object] | None = None,
) -> dict[str, list[list[str]]]:
    sheets = {name: [list(row) for row in rows] for name, rows in ORDER_TEMPLATE_SHEETS.items()}
    sheets["Clients"] = _client_reference_rows(clients or [])
    sheets["Panels"] = _panel_reference_rows(panels or [])
    sheets["Age Units"] = [
        ["age_unit", "label"],
        ["years", "Years"],
        ["months", "Months"],
        ["days", "Days"],
    ]
    return sheets


def write_order_import_template(
    path: str | Path,
    *,
    clients: list[tuple[object, str]] | None = None,
    panels: list[object] | None = None,
) -> Path:
    return _write_workbook_template(path, build_order_import_template_sheets(clients=clients, panels=panels))


def read_order_workbook_rows(path: str | Path) -> list[dict[str, str]]:
    return _read_template_rows(path, required_columns=ORDER_IMPORT_COLUMNS)


def _client_reference_rows(clients: list[tuple[object, str]]) -> list[list[str]]:
    rows = [["client", "client_id"]]
    rows.extend([[str(label), str(client_id)] for client_id, label in clients])
    return rows


def _panel_reference_rows(panels: list[object]) -> list[list[str]]:
    rows = [["panel_code", "panel_name", "tests"]]
    for panel in panels:
        code = str(getattr(panel, "code", "") or "").strip()
        name = str(getattr(panel, "name", "") or "").strip()
        tests = str(getattr(panel, "test_names", "") or "").strip()
        if code or name:
            rows.append([code, name, tests])
    return rows
