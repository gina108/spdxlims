from pathlib import Path

from spdxlims.report_export import build_pdf_export_path


class DummyDatabase:
    def __init__(self, folder_path: Path) -> None:
        self.folder_path = folder_path

    def get_ui_state(self) -> dict[str, object]:
        return {
            "report_pdf_export": {
                "folder_path": str(self.folder_path),
                "filename_parts": ["order_number", "patient_name"],
            }
        }


def test_pdf_export_path_adds_number_when_file_exists(tmp_path) -> None:
    database = DummyDatabase(tmp_path)
    preview = {"order_number": "000018", "patient_name": "MA SOCORRO"}

    first_path = build_pdf_export_path(database, preview)
    first_path.write_text("first", encoding="utf-8")
    second_path = build_pdf_export_path(database, preview)
    second_path.write_text("second", encoding="utf-8")

    assert first_path.name == "000018_MA_SOCORRO.pdf"
    assert second_path.name == "000018_MA_SOCORRO (1).pdf"
    assert build_pdf_export_path(database, preview).name == "000018_MA_SOCORRO (2).pdf"
