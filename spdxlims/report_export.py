from __future__ import annotations

from pathlib import Path

from spdxlims.database import Database

PDF_EXPORT_SETTINGS_KEY = "report_pdf_export"
DEFAULT_EXPORT_DIR = Path.cwd() / "data" / "reports" / "exports"
FILENAME_PART_KEYS: tuple[str, ...] = ("order_number", "patient_name", "client_name", "doctor_name")


def get_pdf_export_settings(database: Database) -> dict[str, object]:
    ui_state = database.get_ui_state()
    raw = ui_state.get(PDF_EXPORT_SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "folder_path": str(raw.get("folder_path") or "").strip(),
        "filename_parts": [
            key for key in list(raw.get("filename_parts") or [])
            if isinstance(key, str) and key in FILENAME_PART_KEYS
        ] or ["order_number"],
        "printer": str(raw.get("printer") or "system_default"),
    }


def save_pdf_export_settings(database: Database, *, folder_path: str, filename_parts: list[str], printer: str = "system_default") -> None:
    ui_state = database.get_ui_state()
    ui_state[PDF_EXPORT_SETTINGS_KEY] = {
        "folder_path": folder_path.strip(),
        "filename_parts": [key for key in filename_parts if key in FILENAME_PART_KEYS] or ["order_number"],
        "printer": printer,
    }
    database.save_ui_state(ui_state)


def build_pdf_export_path(database: Database, preview: dict[str, object], *, suffix: str = "", extension: str = ".pdf") -> Path:
    settings = get_pdf_export_settings(database)
    folder_path = str(settings.get("folder_path") or "").strip()
    target_dir = Path(folder_path) if folder_path else DEFAULT_EXPORT_DIR
    filename_parts = list(settings.get("filename_parts") or ["order_number"])
    name_parts: list[str] = []
    for key in filename_parts:
        value = str(preview.get(key) or "").strip()
        if value:
            name_parts.append(_sanitize_filename_part(value))
    if not name_parts:
        fallback = str(preview.get("order_number") or preview.get("patient_name") or "report").strip()
        name_parts.append(_sanitize_filename_part(fallback or "report"))
    stem = "_".join(part for part in name_parts if part)
    if suffix:
        stem = f"{stem}{suffix}"
    return _next_available_path(target_dir / f"{stem}{extension}")


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"No available export filename for {path}")


def _sanitize_filename_part(value: str) -> str:
    sanitized = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)
    compact = "_".join(part for part in sanitized.split("_") if part)
    return compact[:80] or "report"
