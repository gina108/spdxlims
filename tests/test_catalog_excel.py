from __future__ import annotations

from zipfile import ZIP_DEFLATED, ZipFile

from spdxlims.catalog_excel import read_test_workbook_rows, write_test_import_template


def test_read_test_workbook_rows_accepts_absolute_sheet_targets(tmp_path):
    workbook_path = write_test_import_template(tmp_path / "tests.xlsx")

    with ZipFile(workbook_path, "r") as source:
        entries = {name: source.read(name) for name in source.namelist()}

    rels_path = "xl/_rels/workbook.xml.rels"
    entries[rels_path] = entries[rels_path].replace(b'Target="worksheets/', b'Target="/xl/worksheets/')

    with ZipFile(workbook_path, "w", compression=ZIP_DEFLATED) as target:
        for name, payload in entries.items():
            target.writestr(name, payload)

    rows = read_test_workbook_rows(workbook_path)

    assert len(rows) == 6
    assert rows[0]["code"] == "GLU"
