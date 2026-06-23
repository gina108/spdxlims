from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

TEST_IMPORT_COLUMNS = [
    "code",
    "name",
    "equipment",
    "specimen_type",
    "method",
    "result_kind",
    "select_options",
    "default_result",
    "range_sex",
    "age_min_days",
    "age_max_days",
    "lower_value",
    "upper_value",
    "unit",
    "reference_text",
]

PANEL_IMPORT_COLUMNS = [
    "panel_code",
    "panel_name",
    "specimen_type",
    "metodologia",
    "item_order",
    "item_type",
    "test_code",
    "label",
]

TEST_TEMPLATE_SHEETS: dict[str, list[list[str]]] = {
    "Tests": [
        TEST_IMPORT_COLUMNS,
        ["GLU", "Glucose", "Chemistry", "Serum", "Automated", "numeric", "", "", "", "", "", "70", "110", "mg/dL", ""],
        ["HGB", "Hemoglobin", "Hematology", "Whole Blood", "Automated", "numeric", "", "", "M", "", "", "13.5", "17.5", "g/dL", "Adult male reference range"],
        ["HGB", "Hemoglobin", "Hematology", "Whole Blood", "Automated", "numeric", "", "", "F", "", "", "12.0", "15.5", "g/dL", "Adult female reference range"],
        ["TSH", "Thyroid Stimulating Hormone", "Immunology", "Serum", "CLIA", "numeric", "", "", "", "0", "30", "0.7", "15.2", "uIU/mL", "Neonatal reference range"],
        ["TSH", "Thyroid Stimulating Hormone", "Immunology", "Serum", "CLIA", "numeric", "", "", "", "31", "6570", "0.4", "4.0", "uIU/mL", "Older infant to adult reference range"],
        ["ABO", "ABO Group", "Blood Bank", "Blood", "", "select", "A|B|AB|O", "O", "", "", "", "", "", "", ""],
    ],
    "Instructions": [
        ["Section / Sección", "Guidance / Guía"],
        ["Workbook structure / Estructura del libro", "Use the Tests sheet for all test rows. A test may appear on multiple rows when it has multiple reference ranges. / Use la hoja Tests para todas las filas de analitos. Una analito puede repetirse en varias filas cuando tiene varios rangos de referencia."],
        ["Required columns / Columnas obligatorias", "code, name, equipment, result_kind. Keep the same headers on the Tests sheet. / code, name, equipment, result_kind. Mantenga los mismos encabezados en la hoja Tests."],
        ["Repeated rows / Filas repetidas", "Repeat the same code on multiple rows in the same sheet to define sex-specific or age-specific ranges. / Repita el mismo código en varias filas de la misma hoja para definir rangos por sexo o por edad."],
        ["Different sexes / Diferentes sexos", "Use range_sex = M or F on separate rows. / Use range_sex = M o F en filas separadas."],
        ["Different ages / Diferentes edades", "Use age_min_days and age_max_days on separate rows. / Use age_min_days y age_max_days en filas separadas."],
        ["Selectable tests / Analitos seleccionables", "For result_kind = select, put options in select_options separated by | and keep default_result equal to one option. / Para result_kind = select, escriba las opciones en select_options separadas por | y mantenga default_result igual a una opción."],
        ["Image tests / Analitos de imagen", "Use result_kind = image to define a test that holds microscope captures. The images themselves are attached in the app on the results screen, not via this workbook. / Use result_kind = image para definir un analito que contiene capturas de microscopio. Las imágenes se adjuntan en la aplicación, en la pantalla de resultados, no en este libro."],
        ["Import behavior / Comportamiento de importación", "All non-empty sheets except Instructions are imported. / Se importan todas las hojas no vacías excepto Instructions."],
    ],
}

PANEL_TEMPLATE_SHEETS: dict[str, list[list[str]]] = {
    "CMP-DEMO": [
        PANEL_IMPORT_COLUMNS,
        ["CMP-DEMO", "Chemistry Demo Panel", "Serum", "Automated", "1", "heading", "", "Chemistry"],
        ["CMP-DEMO", "Chemistry Demo Panel", "Serum", "Automated", "2", "test", "GLU", ""],
        ["CMP-DEMO", "Chemistry Demo Panel", "Serum", "Automated", "3", "test", "TSH", ""],
        ["CMP-DEMO", "Chemistry Demo Panel", "Serum", "Automated", "4", "comment", "", "Comments"],
    ],
    "CBC-DEMO": [
        PANEL_IMPORT_COLUMNS,
        ["CBC-DEMO", "Hematology Demo Panel", "Whole Blood", "Automated", "1", "heading", "", "Hematology"],
        ["CBC-DEMO", "Hematology Demo Panel", "Whole Blood", "Automated", "2", "test", "HGB", ""],
        ["CBC-DEMO", "Hematology Demo Panel", "Whole Blood", "Automated", "3", "comment", "", "Observations"],
    ],
    "Instructions": [
        ["Section / Sección", "Guidance / Guía"],
        ["Workbook structure / Estructura del libro", "Use one sheet per panel code. / Use una hoja por código de panel."],
        ["Required columns / Columnas obligatorias", "panel_code, panel_name, specimen_type, metodologia, item_order, item_type. Keep the same headers on every panel sheet. / panel_code, panel_name, specimen_type, metodologia, item_order, item_type. Mantenga los mismos encabezados en cada hoja de panel."],
        ["Item types / Tipos de elemento", "test uses test_code, heading uses label, comment uses label. / test usa test_code, heading usa label, comment usa label."],
        ["Referenced tests / Analitos referenciadas", "Every test_code in the panel workbook must already exist in the database or be imported from a test workbook first. / Cada test_code del libro de paneles debe existir ya en la base de datos o importarse primero desde un libro de analitos."],
        ["Import behavior / Comportamiento de importación", "All non-empty sheets except Instructions are imported. / Se importan todas las hojas no vacías excepto Instructions."],
    ],
}

_SKIP_SHEETS = {"Instructions"}
_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_REL_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def write_test_import_template(path: str | Path) -> Path:
    return _write_workbook_template(path, TEST_TEMPLATE_SHEETS)


def write_panel_import_template(path: str | Path) -> Path:
    return _write_workbook_template(path, PANEL_TEMPLATE_SHEETS)


def write_test_export_workbook(path: str | Path, sheets: dict[str, list[list[str]]]) -> Path:
    return _write_workbook_template(path, sheets)


def write_panel_export_workbook(path: str | Path, sheets: dict[str, list[list[str]]]) -> Path:
    return _write_workbook_template(path, sheets)


def read_test_workbook_rows(path: str | Path) -> list[dict[str, str]]:
    rows = _read_template_rows(path, required_columns=TEST_IMPORT_COLUMNS, column_aliases={"category": "equipment"})
    for row in rows:
        if "equipment" not in row:
            row["equipment"] = ""
    return rows


def read_panel_workbook_rows(path: str | Path) -> list[dict[str, str]]:
    return _read_template_rows(path, required_columns=PANEL_IMPORT_COLUMNS, column_aliases={"method": "metodologia", "methodology": "metodologia"})


def build_test_export_sheets(test_details: Sequence[dict[str, object]]) -> dict[str, list[list[str]]]:
    rows: list[list[str]] = [TEST_IMPORT_COLUMNS]
    for detail in test_details:
        code = str(detail.get("code") or "").strip()
        if not code:
            continue
        rows.extend(_test_detail_export_rows(code, detail))
    return {
        "Tests": rows,
        "Instructions": TEST_TEMPLATE_SHEETS["Instructions"],
    }


def _test_detail_export_rows(code: str, detail: dict[str, object]) -> list[list[str]]:
    base_row = [
        code,
        str(detail.get("name") or ""),
        str(detail.get("category_name") or ""),
        str(detail.get("specimen_type") or ""),
        str(detail.get("method") or ""),
        str(detail.get("result_kind") or "text"),
        _join_options(detail.get("select_options")),
        str(detail.get("default_result_value") or ""),
    ]
    reference_ranges = detail.get("reference_ranges") or []
    if not reference_ranges:
        return [base_row + ["", "", "", "", "", "", ""]]
    rows: list[list[str]] = []
    for reference in reference_ranges:
        reference_dict = dict(reference)
        rows.append(base_row + [
            str(reference_dict.get("sex") or ""),
            _stringify(reference_dict.get("age_min_days")),
            _stringify(reference_dict.get("age_max_days")),
            _stringify(reference_dict.get("lower_value")),
            _stringify(reference_dict.get("upper_value")),
            str(reference_dict.get("unit") or ""),
            str(reference_dict.get("reference_text") or ""),
        ])
    return rows


def build_panel_export_sheets(panel_details: Sequence[dict[str, object]]) -> dict[str, list[list[str]]]:
    sheets: dict[str, list[list[str]]] = {}
    for detail in panel_details:
        code = str(detail.get("code") or "").strip()
        if not code:
            continue
        rows: list[list[str]] = [PANEL_IMPORT_COLUMNS]
        for index, item in enumerate(detail.get("items") or [], start=1):
            item_dict = dict(item)
            item_type = str(item_dict.get("item_type") or "test")
            label = str(item_dict.get("heading_text") or item_dict.get("label") or "")
            test_code = str(item_dict.get("test_code") or "") if item_type == "test" else ""
            rows.append([
                code,
                str(detail.get("name") or ""),
                str(detail.get("specimen_type") or ""),
                str(detail.get("method") or ""),
                _stringify(item_dict.get("sort_order"), fallback=index),
                item_type,
                test_code,
                "" if item_type == "test" and not label.endswith(f"({test_code})") else label,
            ])
        sheets[_safe_sheet_name(code, existing_names=sheets)] = rows
    sheets["Instructions"] = PANEL_TEMPLATE_SHEETS["Instructions"]
    return sheets


def _safe_sheet_name(name: str, *, existing_names: dict[str, list[list[str]]]) -> str:
    cleaned = "".join("_" if character in "[]:*?/\\" else character for character in name).strip() or "Sheet"
    cleaned = cleaned[:31]
    candidate = cleaned
    counter = 2
    while candidate in existing_names or candidate in _SKIP_SHEETS:
        suffix = f' ({counter})'
        candidate = f"{cleaned[: max(1, 31 - len(suffix))]}{suffix}"
        counter += 1
    return candidate


def _join_options(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return "|".join(part.strip() for part in value.replace("|", "\n").splitlines() if part.strip())
        if isinstance(parsed, Sequence) and not isinstance(parsed, str):
            return "|".join(str(part).strip() for part in parsed if str(part).strip())
        return value
    if isinstance(value, Sequence):
        return '|'.join(str(part).strip() for part in value if str(part).strip())
    return str(value)


def _stringify(value: object, *, fallback: int | None = None) -> str:
    if value is None:
        return '' if fallback is None else str(fallback)
    if isinstance(value, float):
        return ('%f' % value).rstrip('0').rstrip('.')
    return str(value)


def _write_workbook_template(path: str | Path, sheets: dict[str, list[list[str]]]) -> Path:
    target = _next_available_path(Path(path))
    workbook_xml, workbook_rels, content_types = _build_workbook_parts(list(sheets))
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>\n'
        '</Relationships>\n'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\n'
        '  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>\n'
        '  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>\n'
        '  <borders count="1"><border/></borders>\n'
        '  <cellStyleXfs count="1"><xf/></cellStyleXfs>\n'
        '  <cellXfs count="1"><xf xfId="0"/></cellXfs>\n'
        '  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>\n'
        '</styleSheet>\n'
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", styles)
        for index, (_sheet_name, rows) in enumerate(sheets.items(), start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _build_rows_sheet_xml(rows))
    return target


def _build_workbook_parts(sheet_names: Sequence[str]) -> tuple[str, str, str]:
    sheet_entries: list[str] = []
    rel_entries: list[str] = []
    type_entries = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for index, sheet_name in enumerate(sheet_names, start=1):
        escaped_name = escape(sheet_name)
        sheet_entries.append(f'    <sheet name="{escaped_name}" sheetId="{index}" r:id="rId{index}"/>')
        rel_entries.append(f'  <Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>')
        type_entries.append(f'  <Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
    rel_entries.append(f'  <Relationship Id="rId{len(sheet_names) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        '  <sheets>\n'
        + '\n'.join(sheet_entries)
        + '\n  </sheets>\n'
        '</workbook>\n'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        + '\n'.join(rel_entries)
        + '\n</Relationships>\n'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        + '\n'.join(type_entries)
        + '\n</Types>\n'
    )
    return workbook_xml, workbook_rels, content_types


def _next_available_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    counter = 2
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _read_template_rows(
    path: str | Path,
    *,
    required_columns: Sequence[str],
    column_aliases: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    workbook = _read_workbook(Path(path))
    records: list[dict[str, str]] = []
    alias_map = {key.strip(): value.strip() for key, value in (column_aliases or {}).items()}
    for sheet_name, rows in workbook.items():
        if sheet_name in _SKIP_SHEETS or not rows:
            continue
        headers = [value.strip() for value in rows[0]]
        normalized_headers = [alias_map.get(header, header) for header in headers]
        if not any(headers):
            continue
        if any(column not in normalized_headers for column in required_columns):
            continue
        for row_index, values in enumerate(rows[1:], start=2):
            record = {
                normalized_headers[index]: values[index].strip() if index < len(values) else ""
                for index in range(len(normalized_headers))
            }
            if any(value for value in record.values()):
                record["__sheet_name__"] = sheet_name
                record["__row_number__"] = str(row_index)
                records.append(record)
    return records


def _build_rows_sheet_xml(rows: Iterable[Iterable[str]]) -> str:
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row, start=1):
            reference = f"{_column_letter(column_index)}{row_index}"
            escaped_value = escape(str(value))
            cells.append(f'<c r="{reference}" t="inlineStr"><is><t>{escaped_value}</t></is></c>')
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(xml_rows)}</sheetData>"
        '</worksheet>'
    )


def _read_workbook(path: Path) -> dict[str, list[list[str]]]:
    with ZipFile(path, "r") as archive:
        shared_strings = _read_shared_strings(archive)
        sheet_paths = _read_sheet_paths(archive)
        workbook: dict[str, list[list[str]]] = {}
        for name, sheet_path in sheet_paths.items():
            workbook[name] = _read_sheet(archive.read(sheet_path), shared_strings)
        return workbook


def _read_sheet_paths(archive: ZipFile) -> dict[str, str]:
    workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
    rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationships = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rel_root.findall(f"{{{_NS_REL_PKG}}}Relationship")}
    sheet_paths: dict[str, str] = {}
    for sheet in workbook_root.findall(f"{{{_NS_MAIN}}}sheets/{{{_NS_MAIN}}}sheet"):
        rel_id = sheet.attrib.get(f"{{{_NS_REL_DOC}}}id")
        name = sheet.attrib.get("name", "")
        target = relationships.get(rel_id or "")
        if name and target:
            normalized_target = target.lstrip("/")
            normalized = normalized_target if normalized_target.startswith("xl/") else f"xl/{normalized_target}"
            sheet_paths[name] = normalized
    return sheet_paths


def _read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall(f"{{{_NS_MAIN}}}si"):
        texts = [node.text or "" for node in item.findall(f".//{{{_NS_MAIN}}}t")]
        values.append("".join(texts))
    return values


def _read_sheet(payload: bytes, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(payload)
    rows: list[list[str]] = []
    for row in root.findall(f"{{{_NS_MAIN}}}sheetData/{{{_NS_MAIN}}}row"):
        values: list[str] = []
        current_column = 1
        for cell in row.findall(f"{{{_NS_MAIN}}}c"):
            reference = cell.attrib.get("r", "")
            column = _column_index(reference)
            while current_column < column:
                values.append("")
                current_column += 1
            values.append(_cell_value(cell, shared_strings))
            current_column += 1
        rows.append(values)
    return rows


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        texts = [node.text or "" for node in cell.findall(f".//{{{_NS_MAIN}}}t")]
        return "".join(texts)
    value_node = cell.find(f"{{{_NS_MAIN}}}v")
    raw_value = value_node.text if value_node is not None and value_node.text is not None else ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)]
        except (ValueError, IndexError):
            return ""
    return raw_value


def _column_letter(index: int) -> str:
    letters: list[str] = []
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def _column_index(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha()).upper()
    value = 0
    for character in letters:
        value = value * 26 + (ord(character) - 64)
    return value or 1
