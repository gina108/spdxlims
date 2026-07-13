from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import shutil
import sys
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.models import (
    AppUser,
    LabOrder,
    LabProfile,
    OrderItem,
    OutsourcedPanelExtraction,
    OutsourcedPanelRow,
    OutsourcedPanelTable,
    PanelCatalog,
    PanelCatalogItem,
    Patient,
    Provider,
    ReportItemImageSnapshot,
    ReportItemSnapshot,
    ReportOutsourcedRowSnapshot,
    ReportSnapshot,
    Result,
    ResultImage,
    TestCatalog,
    TestReferenceRange,
)


UPLOAD_DIR = BACKEND_ROOT / "app" / "static" / "uploads"
DEFAULT_SQLITE_PATH = BACKEND_ROOT.parent / "data" / "spdxlims.db"


@dataclass
class ImportContext:
    actor_id: Any
    patient_ids: dict[int, Any]
    doctor_ids: dict[int, Any]
    client_ids: dict[int, Any]
    test_ids: dict[int, Any]
    panel_ids: dict[int, Any]
    order_ids: dict[int, Any]
    order_item_ids: dict[int, Any | None]
    report_ids: dict[int, Any]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import legacy SQLite SPDXLIMS data into the PostgreSQL backend.",
    )
    parser.add_argument(
        "--sqlite",
        default=str(DEFAULT_SQLITE_PATH),
        help="Path to the legacy SQLite database file.",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")

    sqlite_db = sqlite3.connect(str(sqlite_path))
    sqlite_db.row_factory = sqlite3.Row

    db = SessionLocal()
    try:
        context = ImportContext(
            actor_id=_ensure_import_user(db).id,
            patient_ids={},
            doctor_ids={},
            client_ids={},
            test_ids={},
            panel_ids={},
            order_ids={},
            order_item_ids={},
            report_ids={},
        )

        counts: dict[str, int] = {}
        counts["lab_profile"] = import_lab_profile(sqlite_db, sqlite_path, db)
        counts["patients"] = import_patients(sqlite_db, db, context)
        counts["doctors"] = import_doctors(sqlite_db, db, context)
        counts["clients"] = import_clients(sqlite_db, db, context)
        counts["tests"] = import_tests(sqlite_db, db, context)
        counts["panels"] = import_panels(sqlite_db, db, context)
        counts["orders"] = import_orders(sqlite_db, db, context)
        counts["results"] = import_results(sqlite_db, db, context)
        counts["result_images"] = import_result_images(sqlite_db, db, context)
        counts["reports"] = import_reports(sqlite_db, db, context)
        counts["report_outsourced_rows"] = import_report_outsourced_rows(sqlite_db, db, context)
        counts["outsourced_panels"] = import_outsourced_panels(sqlite_db, db, context)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        sqlite_db.close()

    print("SQLite import completed.")
    for key, value in counts.items():
        print(f"{key}: {value}")


def import_lab_profile(sqlite_db: sqlite3.Connection, sqlite_path: Path, db: Session) -> int:
    row = sqlite_db.execute(
        """
        SELECT lab_name, address, phone, email, header_image_path, footer_signature_image_path,
               logo_path, report_footer, director_name, director_license,
               report_flag_style, keep_panels_together, report_font_family, report_font_size,
               report_font_bold, report_abnormal_bold, report_subheading_font_family,
               report_subheading_font_size, report_subheading_font_bold, report_footer_gap_mm,
               report_sex_format, report_date_format, report_show_doctor, report_show_client,
               report_show_sex, report_show_age, report_show_dob, report_show_ordered_at,
               report_show_reported_at, report_doctor_col, report_client_col, report_sex_col,
               report_age_col, report_dob_col, report_ordered_at_col, report_reported_at_col
        FROM lab_settings
        ORDER BY id ASC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return 0

    profile = db.get(LabProfile, 1)
    if profile is None:
        profile = LabProfile(id=1)
        db.add(profile)
        db.flush()

    profile.lab_name = (row["lab_name"] or "").strip()
    profile.address = (row["address"] or "").strip()
    profile.phone = (row["phone"] or "").strip()
    profile.email = (row["email"] or "").strip()
    profile.report_footer = (row["report_footer"] or "").strip()
    profile.director_name = (row["director_name"] or "").strip()
    profile.director_license = (row["director_license"] or "").strip()
    profile.logo_path = _copy_profile_asset(sqlite_path, row["logo_path"], "lab_profile_logo")
    profile.header_image_path = _copy_profile_asset(sqlite_path, row["header_image_path"], "lab_profile_header")
    profile.footer_signature_image_path = _copy_profile_asset(
        sqlite_path,
        row["footer_signature_image_path"],
        "lab_profile_footer_signature",
    )
    profile.report_settings = _report_settings_from_row(row)
    db.add(profile)
    db.flush()
    return 1


def _report_settings_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """Mirror the desktop's get_report_layout_settings() dict for server rendering."""
    keys = row.keys()

    def _bool(name: str, default: bool) -> bool:
        return _parse_bool(row[name], default=default) if name in keys else default

    def _int(name: str, default: int) -> int:
        return (_parse_int(row[name]) if name in keys else None) or default

    def _text(name: str, default: str) -> str:
        return (_clean_text(row[name]) if name in keys else None) or default

    return {
        "flag_display_mode": _text("report_flag_style", "arrows"),
        "keep_panels_together": _bool("keep_panels_together", True),
        "report_font_family": _text("report_font_family", "Segoe UI"),
        "report_font_size": _int("report_font_size", 12),
        "report_font_bold": _bool("report_font_bold", False),
        "report_abnormal_bold": _bool("report_abnormal_bold", True),
        "report_subheading_font_family": _text("report_subheading_font_family", "Segoe UI"),
        "report_subheading_font_size": _int("report_subheading_font_size", 13),
        "report_subheading_font_bold": _bool("report_subheading_font_bold", True),
        "report_footer_gap_mm": _int("report_footer_gap_mm", 2),
        "report_sex_format": _text("report_sex_format", "medium"),
        "report_date_format": _text("report_date_format", "date_only"),
        "report_show_doctor": _bool("report_show_doctor", True),
        "report_show_client": _bool("report_show_client", True),
        "report_show_sex": _bool("report_show_sex", True),
        "report_show_age": _bool("report_show_age", True),
        "report_show_dob": _bool("report_show_dob", False),
        "report_show_ordered_at": _bool("report_show_ordered_at", False),
        "report_show_reported_at": _bool("report_show_reported_at", True),
        "report_doctor_col": _text("report_doctor_col", "left"),
        "report_client_col": _text("report_client_col", "left"),
        "report_sex_col": _text("report_sex_col", "left"),
        "report_age_col": _text("report_age_col", "right"),
        "report_dob_col": _text("report_dob_col", "right"),
        "report_ordered_at_col": _text("report_ordered_at_col", "right"),
        "report_reported_at_col": _text("report_reported_at_col", "right"),
    }


def import_patients(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    rows = sqlite_db.execute(
        """
        SELECT id, patient_code, first_name, last_name, middle_name, sex, date_of_birth, phone, email,
               address, age_value, age_unit, is_active, created_at
        FROM patients
        ORDER BY id ASC
        """
    ).fetchall()
    imported = 0
    for row in rows:
        mrn = _clean_text(row["patient_code"])
        parsed_dob = _parse_date(row["date_of_birth"])
        patient = None
        if mrn:
            patient = db.scalars(select(Patient).where(Patient.mrn == mrn)).first()
        # Only de-duplicate on a strong key. Legacy records carry no MRN and the
        # date_of_birth column sometimes holds junk (e.g. a stray 'M'/'F'), so
        # matching on name alone would merge distinct people who share a common
        # name. Require a real parsed DOB before treating name+dob as identity.
        if patient is None and parsed_dob is not None:
            patient = db.scalars(
                select(Patient).where(
                    Patient.first_name == _clean_text(row["first_name"], fallback=""),
                    Patient.last_name == _clean_text(row["last_name"], fallback=""),
                    Patient.middle_name == _clean_text(row["middle_name"]),
                    Patient.dob == parsed_dob,
                )
            ).first()
        if patient is None:
            patient = Patient(
                mrn=mrn,
                first_name=_clean_text(row["first_name"], fallback=""),
                last_name=_clean_text(row["last_name"], fallback=""),
                middle_name=_clean_text(row["middle_name"]),
                dob=_parse_date(row["date_of_birth"]),
                age_value=_parse_int(row["age_value"]),
                age_unit=_normalize_age_unit(row["age_unit"]),
                sex=_normalize_sex(row["sex"]),
                phone=_clean_text(row["phone"]),
                email=_clean_text(row["email"]),
                address=_clean_text(row["address"]),
                is_active=_parse_bool(row["is_active"], default=True),
                created_at=_parse_datetime(row["created_at"]) or datetime.utcnow(),
            )
            db.add(patient)
        else:
            patient.mrn = mrn or patient.mrn
            patient.first_name = _clean_text(row["first_name"], fallback=patient.first_name)
            patient.last_name = _clean_text(row["last_name"], fallback=patient.last_name)
            patient.middle_name = _clean_text(row["middle_name"])
            patient.dob = _parse_date(row["date_of_birth"]) or patient.dob
            patient.age_value = _parse_int(row["age_value"])
            patient.age_unit = _normalize_age_unit(row["age_unit"])
            patient.sex = _normalize_sex(row["sex"])
            patient.phone = _clean_text(row["phone"])
            patient.email = _clean_text(row["email"])
            patient.address = _clean_text(row["address"])
            patient.is_active = _parse_bool(row["is_active"], default=True)
        db.flush()
        context.patient_ids[int(row["id"])] = patient.id
        imported += 1
    return imported


def import_doctors(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    rows = sqlite_db.execute(
        """
        SELECT id, full_name, license_number, phone, email, is_active, created_at
        FROM doctors
        ORDER BY id ASC
        """
    ).fetchall()
    imported = 0
    for row in rows:
        license_number = _clean_text(row["license_number"])
        full_name = _clean_text(row["full_name"], fallback="Unnamed Doctor")
        provider = None
        if license_number:
            provider = db.scalars(
                select(Provider).where(Provider.provider_type == "doctor", Provider.code == license_number)
            ).first()
        if provider is None:
            provider = db.scalars(
                select(Provider).where(Provider.provider_type == "doctor", Provider.legal_name == full_name)
            ).first()
        if provider is None:
            provider = Provider(
                provider_type="doctor",
                code=license_number,
                legal_name=full_name,
                email=_clean_text(row["email"]),
                phone=_clean_text(row["phone"]),
                active=_parse_bool(row["is_active"], default=True),
                created_at=_parse_datetime(row["created_at"]) or datetime.utcnow(),
            )
            db.add(provider)
        else:
            provider.code = license_number or provider.code
            provider.legal_name = full_name
            provider.email = _clean_text(row["email"])
            provider.phone = _clean_text(row["phone"])
            provider.active = _parse_bool(row["is_active"], default=True)
        db.flush()
        context.doctor_ids[int(row["id"])] = provider.id
        imported += 1
    return imported


def import_clients(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    rows = sqlite_db.execute(
        """
        SELECT id, name, phone, email, tax_id, is_active, created_at
        FROM clients
        ORDER BY id ASC
        """
    ).fetchall()
    imported = 0
    for row in rows:
        tax_id = _clean_text(row["tax_id"])
        name = _clean_text(row["name"], fallback="Unnamed Client")
        provider = None
        if tax_id:
            provider = db.scalars(
                select(Provider).where(Provider.provider_type == "clinic", Provider.tax_id == tax_id)
            ).first()
        if provider is None:
            provider = db.scalars(
                select(Provider).where(Provider.provider_type == "clinic", Provider.legal_name == name)
            ).first()
        if provider is None:
            provider = Provider(
                provider_type="clinic",
                legal_name=name,
                tax_id=tax_id,
                email=_clean_text(row["email"]),
                phone=_clean_text(row["phone"]),
                active=_parse_bool(row["is_active"], default=True),
                created_at=_parse_datetime(row["created_at"]) or datetime.utcnow(),
            )
            db.add(provider)
        else:
            provider.legal_name = name
            provider.tax_id = tax_id or provider.tax_id
            provider.email = _clean_text(row["email"])
            provider.phone = _clean_text(row["phone"])
            provider.active = _parse_bool(row["is_active"], default=True)
        db.flush()
        context.client_ids[int(row["id"])] = provider.id
        imported += 1
    return imported


def import_tests(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    rows = sqlite_db.execute(
        """
        SELECT id, code, name, category_id, specimen_type, method, result_kind, is_active,
               select_options, default_result_value, price
        FROM tests
        ORDER BY id ASC
        """
    ).fetchall()
    range_rows = sqlite_db.execute(
        """
        SELECT id, test_id, sex, age_min_days, age_max_days, lower_value, upper_value, unit,
               reference_text, lower_value_text, upper_value_text
        FROM test_reference_ranges
        ORDER BY test_id ASC, id ASC
        """
    ).fetchall()
    ranges_by_test: dict[int, list[sqlite3.Row]] = {}
    for row in range_rows:
        ranges_by_test.setdefault(int(row["test_id"]), []).append(row)

    imported = 0
    for row in rows:
        code = _clean_text(row["code"], fallback="")
        if not code:
            continue
        test = db.scalars(select(TestCatalog).where(TestCatalog.code == code)).first()
        first_range = (ranges_by_test.get(int(row["id"])) or [None])[0]
        unit = _clean_text(first_range["unit"]) if first_range is not None else None
        if test is None:
            test = TestCatalog(
                code=code,
                name=_clean_text(row["name"], fallback=code),
                category_name=_clean_text(row["category_id"]),
                specimen_type=_clean_text(row["specimen_type"]),
                method=_clean_text(row["method"]),
                result_kind=_normalize_result_kind(row["result_kind"]),
                select_options=_normalize_select_options(row["select_options"]),
                default_result_value=_clean_text(row["default_result_value"]),
                price=_parse_decimal(row["price"], default="0"),
                unit=unit,
                active=_parse_bool(row["is_active"], default=True),
            )
            db.add(test)
            db.flush()
        else:
            test.name = _clean_text(row["name"], fallback=test.name)
            test.category_name = _clean_text(row["category_id"])
            test.specimen_type = _clean_text(row["specimen_type"])
            test.method = _clean_text(row["method"])
            test.result_kind = _normalize_result_kind(row["result_kind"])
            test.select_options = _normalize_select_options(row["select_options"])
            test.default_result_value = _clean_text(row["default_result_value"])
            test.price = _parse_decimal(row["price"], default="0")
            test.unit = unit or test.unit
            test.active = _parse_bool(row["is_active"], default=True)
            db.flush()

        db.execute(delete(TestReferenceRange).where(TestReferenceRange.test_id == test.id))
        for source_range in ranges_by_test.get(int(row["id"]), []):
            db.add(
                TestReferenceRange(
                    test_id=test.id,
                    sex=_normalize_reference_sex(source_range["sex"]),
                    age_min_days=_parse_int(source_range["age_min_days"]),
                    age_max_days=_parse_int(source_range["age_max_days"]),
                    lower_value_text=_range_text(source_range["lower_value_text"], source_range["lower_value"]),
                    upper_value_text=_range_text(source_range["upper_value_text"], source_range["upper_value"]),
                    unit=_clean_text(source_range["unit"]),
                    reference_text=_clean_text(source_range["reference_text"]),
                )
            )
        db.flush()
        context.test_ids[int(row["id"])] = test.id
        imported += 1
    return imported


def import_panels(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    rows = sqlite_db.execute(
        """
        SELECT id, code, name, is_active
        FROM test_panels
        ORDER BY id ASC
        """
    ).fetchall()
    item_rows = sqlite_db.execute(
        """
        SELECT id, panel_id, test_id, item_type, heading_text, sort_order
        FROM test_panel_items
        ORDER BY panel_id ASC, sort_order ASC, id ASC
        """
    ).fetchall()
    items_by_panel: dict[int, list[sqlite3.Row]] = {}
    for row in item_rows:
        items_by_panel.setdefault(int(row["panel_id"]), []).append(row)

    imported = 0
    for row in rows:
        code = _clean_text(row["code"], fallback="")
        if not code:
            continue
        panel = db.scalars(select(PanelCatalog).where(PanelCatalog.code == code)).first()
        if panel is None:
            panel = PanelCatalog(
                code=code,
                name=_clean_text(row["name"], fallback=code),
                active=_parse_bool(row["is_active"], default=True),
            )
            db.add(panel)
            db.flush()
        else:
            panel.name = _clean_text(row["name"], fallback=panel.name)
            panel.active = _parse_bool(row["is_active"], default=True)
            db.flush()

        db.execute(delete(PanelCatalogItem).where(PanelCatalogItem.panel_id == panel.id))
        for source_item in items_by_panel.get(int(row["id"]), []):
            item_type = _clean_text(source_item["item_type"], fallback="test")
            local_test_id = _parse_int(source_item["test_id"])
            db.add(
                PanelCatalogItem(
                    panel_id=panel.id,
                    test_id=context.test_ids.get(local_test_id) if local_test_id is not None else None,
                    item_type=item_type or "test",
                    heading_text=_clean_text(source_item["heading_text"]),
                    sort_order=_parse_int(source_item["sort_order"]) or 0,
                )
            )
        db.flush()
        context.panel_ids[int(row["id"])] = panel.id
        imported += 1
    return imported


def import_orders(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    orders = sqlite_db.execute(
        """
        SELECT id, order_number, patient_id, doctor_id, client_id, status, ordered_at, reported_at,
               notes, accession_id, sample_id
        FROM orders
        ORDER BY id ASC
        """
    ).fetchall()
    order_tests = sqlite_db.execute(
        """
        SELECT ot.id, ot.order_id, ot.test_id, ot.display_name, ot.sort_order,
               ot.is_outsourced, ot.source_label, t.code AS test_code, t.name AS test_name
        FROM order_tests ot
        LEFT JOIN tests t ON t.id = ot.test_id
        ORDER BY ot.order_id ASC, ot.sort_order ASC, ot.id ASC
        """
    ).fetchall()
    tests_by_order: dict[int, list[sqlite3.Row]] = {}
    for row in order_tests:
        tests_by_order.setdefault(int(row["order_id"]), []).append(row)

    imported = 0
    for row in orders:
        patient_id = context.patient_ids.get(_parse_int(row["patient_id"]) or -1)
        if patient_id is None:
            continue
        order_number = _clean_text(row["order_number"], fallback="")
        if not order_number:
            continue

        order = db.scalars(select(LabOrder).where(LabOrder.order_number == order_number)).first()
        if order is None:
            order = LabOrder(
                order_number=order_number,
                patient_id=patient_id,
                doctor_id=context.doctor_ids.get(_parse_int(row["doctor_id"]) or -1),
                client_id=context.client_ids.get(_parse_int(row["client_id"]) or -1),
                accession_id=_clean_text(row["accession_id"]),
                sample_id=_clean_text(row["sample_id"]),
                notes=_clean_text(row["notes"]),
                ordered_at=_parse_datetime(row["ordered_at"]) or datetime.utcnow(),
                reported_at=_parse_datetime(row["reported_at"]),
                status=_normalize_order_status(row["status"]),
            )
            db.add(order)
            db.flush()
        else:
            _delete_existing_order_children(db, order.id)
            order.patient_id = patient_id
            order.doctor_id = context.doctor_ids.get(_parse_int(row["doctor_id"]) or -1)
            order.client_id = context.client_ids.get(_parse_int(row["client_id"]) or -1)
            order.accession_id = _clean_text(row["accession_id"])
            order.sample_id = _clean_text(row["sample_id"])
            order.notes = _clean_text(row["notes"])
            order.ordered_at = _parse_datetime(row["ordered_at"]) or order.ordered_at
            order.reported_at = _parse_datetime(row["reported_at"])
            order.status = _normalize_order_status(row["status"])
            db.flush()

        current_group_label: str | None = None
        item_sort_order = 0
        for source_item in tests_by_order.get(int(row["id"]), []):
            local_order_test_id = int(source_item["id"])
            test_code = _clean_text(source_item["test_code"], fallback="")
            display_name = _clean_text(source_item["display_name"])
            if test_code == "__PANEL_HEADING__":
                current_group_label = display_name or _clean_text(source_item["test_name"])
                context.order_item_ids[local_order_test_id] = None
                continue

            imported_test_id = context.test_ids.get(_parse_int(source_item["test_id"]) or -1)
            if imported_test_id is None:
                context.order_item_ids[local_order_test_id] = None
                continue

            order_item = OrderItem(
                order_id=order.id,
                test_id=imported_test_id,
                group_label=current_group_label,
                sort_order=item_sort_order,
                priority="routine",
                is_outsourced=_parse_bool(source_item["is_outsourced"], default=False),
                source_label=_clean_text(source_item["source_label"]),
            )
            db.add(order_item)
            db.flush()
            context.order_item_ids[local_order_test_id] = order_item.id
            item_sort_order += 1

        context.order_ids[int(row["id"])] = order.id
        imported += 1
    return imported


def import_results(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    rows = sqlite_db.execute(
        """
        SELECT order_test_id, result_value, unit, lower_value, upper_value, lower_value_text,
               upper_value_text, flag, reference_text, comments, entered_at, reviewed_at
        FROM results
        ORDER BY id ASC
        """
    ).fetchall()
    imported = 0
    for row in rows:
        order_item_id = context.order_item_ids.get(_parse_int(row["order_test_id"]) or -1)
        if order_item_id is None:
            continue
        result = db.scalars(select(Result).where(Result.order_item_id == order_item_id)).first()
        if result is None:
            result = Result(
                order_item_id=order_item_id,
                entered_by=context.actor_id,
                status="final" if row["reviewed_at"] else "draft",
            )
            db.add(result)
        result.value_text = _clean_text(row["result_value"])
        result.value_num = _parse_float(row["result_value"])
        result.unit = _clean_text(row["unit"])
        result.lower_value_text = _range_text(row["lower_value_text"], row["lower_value"])
        result.upper_value_text = _range_text(row["upper_value_text"], row["upper_value"])
        result.reference_text = _clean_text(row["reference_text"])
        result.comments = _clean_text(row["comments"])
        result.flag = _clean_text(row["flag"]) or "none"
        result.entered_at = _parse_datetime(row["entered_at"]) or datetime.utcnow()
        result.verified_by = context.actor_id if row["reviewed_at"] else None
        result.verified_at = _parse_datetime(row["reviewed_at"])
        result.status = "final" if row["reviewed_at"] else "draft"
        imported += 1
    db.flush()
    return imported


def import_result_images(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    has_table = sqlite_db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'result_images'"
    ).fetchone()
    if has_table is None:
        return 0
    rows = sqlite_db.execute(
        """
        SELECT order_test_id, image_data, mime_type, caption, sort_order
        FROM result_images
        ORDER BY order_test_id ASC, sort_order ASC, id ASC
        """
    ).fetchall()
    imported = 0
    cleared_order_items: set[Any] = set()
    for row in rows:
        order_item_id = context.order_item_ids.get(_parse_int(row["order_test_id"]) or -1)
        if order_item_id is None:
            continue
        data = row["image_data"]
        if data is None:
            continue
        if order_item_id not in cleared_order_items:
            db.execute(delete(ResultImage).where(ResultImage.order_item_id == order_item_id))
            cleared_order_items.add(order_item_id)
        db.add(
            ResultImage(
                order_item_id=order_item_id,
                image_data=bytes(data),
                mime_type=_clean_text(row["mime_type"]) or "image/png",
                caption=_clean_text(row["caption"]),
                sort_order=_parse_int(row["sort_order"]) or 0,
            )
        )
        imported += 1
    db.flush()
    return imported


def import_reports(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    reports = sqlite_db.execute(
        """
        SELECT id, order_id, report_version, status, finalized_at, patient_snapshot_name,
               patient_snapshot_sex, patient_snapshot_dob, doctor_snapshot_name,
               lab_snapshot_name, lab_snapshot_address, lab_snapshot_phone, lab_snapshot_email,
               director_snapshot_name, director_snapshot_license, footer_snapshot_text,
               header_image_snapshot_path, footer_signature_snapshot_path, general_comments
        FROM reports
        ORDER BY id ASC
        """
    ).fetchall()
    report_items = sqlite_db.execute(
        """
        SELECT report_id, order_test_id, test_name_snapshot, result_value_snapshot, unit_snapshot,
               reference_text_snapshot, lower_value_snapshot, upper_value_snapshot,
               lower_value_snapshot_text, upper_value_snapshot_text, flag_snapshot,
               comments_snapshot, sort_order, item_type_snapshot
        FROM report_items
        ORDER BY report_id ASC, sort_order ASC, id ASC
        """
    ).fetchall()
    items_by_report: dict[int, list[sqlite3.Row]] = {}
    for row in report_items:
        items_by_report.setdefault(int(row["report_id"]), []).append(row)

    imported = 0
    for row in reports:
        order_id = context.order_ids.get(_parse_int(row["order_id"]) or -1)
        if order_id is None:
            continue
        snapshot = db.scalars(select(ReportSnapshot).where(ReportSnapshot.order_id == order_id)).first()
        if snapshot is None:
            snapshot = ReportSnapshot(
                order_id=order_id,
                report_version=_parse_int(row["report_version"]) or 1,
                status=_clean_text(row["status"], fallback="final"),
                finalized_at=_parse_datetime(row["finalized_at"]) or datetime.utcnow(),
                patient_snapshot_name=_clean_text(row["patient_snapshot_name"], fallback=""),
                patient_snapshot_sex=_clean_text(row["patient_snapshot_sex"]),
                patient_snapshot_dob=_clean_text(row["patient_snapshot_dob"]),
                doctor_snapshot_name=_clean_text(row["doctor_snapshot_name"]),
                client_snapshot_name=None,
                lab_snapshot_name=_clean_text(row["lab_snapshot_name"]),
                lab_snapshot_address=_clean_text(row["lab_snapshot_address"]),
                lab_snapshot_phone=_clean_text(row["lab_snapshot_phone"]),
                lab_snapshot_email=_clean_text(row["lab_snapshot_email"]),
                director_snapshot_name=_clean_text(row["director_snapshot_name"]),
                director_snapshot_license=_clean_text(row["director_snapshot_license"]),
                footer_snapshot_text=_clean_text(row["footer_snapshot_text"]),
                header_image_snapshot_path=_clean_text(row["header_image_snapshot_path"]),
                footer_signature_snapshot_path=_clean_text(row["footer_signature_snapshot_path"]),
                general_comments=_clean_text(row["general_comments"]),
            )
            db.add(snapshot)
            db.flush()
        else:
            db.execute(delete(ReportItemSnapshot).where(ReportItemSnapshot.report_id == snapshot.id))
            db.execute(delete(ReportOutsourcedRowSnapshot).where(ReportOutsourcedRowSnapshot.report_id == snapshot.id))
            snapshot.report_version = _parse_int(row["report_version"]) or snapshot.report_version
            snapshot.status = _clean_text(row["status"], fallback=snapshot.status)
            snapshot.finalized_at = _parse_datetime(row["finalized_at"]) or snapshot.finalized_at
            snapshot.patient_snapshot_name = _clean_text(row["patient_snapshot_name"], fallback=snapshot.patient_snapshot_name)
            snapshot.patient_snapshot_sex = _clean_text(row["patient_snapshot_sex"])
            snapshot.patient_snapshot_dob = _clean_text(row["patient_snapshot_dob"])
            snapshot.doctor_snapshot_name = _clean_text(row["doctor_snapshot_name"])
            snapshot.lab_snapshot_name = _clean_text(row["lab_snapshot_name"])
            snapshot.lab_snapshot_address = _clean_text(row["lab_snapshot_address"])
            snapshot.lab_snapshot_phone = _clean_text(row["lab_snapshot_phone"])
            snapshot.lab_snapshot_email = _clean_text(row["lab_snapshot_email"])
            snapshot.director_snapshot_name = _clean_text(row["director_snapshot_name"])
            snapshot.director_snapshot_license = _clean_text(row["director_snapshot_license"])
            snapshot.footer_snapshot_text = _clean_text(row["footer_snapshot_text"])
            snapshot.header_image_snapshot_path = _clean_text(row["header_image_snapshot_path"])
            snapshot.footer_signature_snapshot_path = _clean_text(row["footer_signature_snapshot_path"])
            snapshot.general_comments = _clean_text(row["general_comments"])
            db.flush()

        for item in items_by_report.get(int(row["id"]), []):
            db.add(
                ReportItemSnapshot(
                    report_id=snapshot.id,
                    order_item_id=context.order_item_ids.get(_parse_int(item["order_test_id"]) or -1),
                    test_name_snapshot=_clean_text(item["test_name_snapshot"], fallback=""),
                    result_value_snapshot=_clean_text(item["result_value_snapshot"]),
                    unit_snapshot=_clean_text(item["unit_snapshot"]),
                    reference_text_snapshot=_clean_text(item["reference_text_snapshot"]),
                    lower_value_snapshot_text=_range_text(item["lower_value_snapshot_text"], item["lower_value_snapshot"]),
                    upper_value_snapshot_text=_range_text(item["upper_value_snapshot_text"], item["upper_value_snapshot"]),
                    flag_snapshot=_clean_text(item["flag_snapshot"]),
                    comments_snapshot=_clean_text(item["comments_snapshot"]),
                    sort_order=_parse_int(item["sort_order"]) or 0,
                    item_type_snapshot=_clean_text(item["item_type_snapshot"], fallback="test"),
                )
            )
        context.report_ids[int(row["id"])] = snapshot.id
        imported += 1
    db.flush()
    return imported


def import_report_outsourced_rows(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    if not _sqlite_has_table(sqlite_db, "report_outsourced_rows"):
        return 0
    rows = sqlite_db.execute(
        """
        SELECT report_id, panel_label, source_pdf_path, row_index, col_1, col_2, col_3, col_4, col_5
        FROM report_outsourced_rows
        ORDER BY report_id ASC, panel_label ASC, row_index ASC, id ASC
        """
    ).fetchall()
    imported = 0
    for row in rows:
        report_id = context.report_ids.get(_parse_int(row["report_id"]) or -1)
        if report_id is None:
            continue
        db.add(
            ReportOutsourcedRowSnapshot(
                report_id=report_id,
                panel_label=_clean_text(row["panel_label"], fallback="") or "",
                source_pdf_path=_clean_text(row["source_pdf_path"], fallback="") or "",
                row_index=_parse_int(row["row_index"]) or 0,
                col_1=_clean_text(row["col_1"]),
                col_2=_clean_text(row["col_2"]),
                col_3=_clean_text(row["col_3"]),
                col_4=_clean_text(row["col_4"]),
                col_5=_clean_text(row["col_5"]),
            )
        )
        imported += 1
    db.flush()
    return imported


def import_outsourced_panels(sqlite_db: sqlite3.Connection, db: Session, context: ImportContext) -> int:
    if not _sqlite_has_table(sqlite_db, "outsourced_panel_tables"):
        return 0
    tables = sqlite_db.execute(
        """
        SELECT id, order_id, panel_label, source_pdf_path
        FROM outsourced_panel_tables
        ORDER BY id ASC
        """
    ).fetchall()
    has_extractions = _sqlite_has_table(sqlite_db, "outsourced_panel_extractions")
    has_rows = _sqlite_has_table(sqlite_db, "outsourced_panel_rows")
    imported = 0
    for table_row in tables:
        order_id = context.order_ids.get(_parse_int(table_row["order_id"]) or -1)
        if order_id is None:
            continue
        panel_label = _clean_text(table_row["panel_label"], fallback="") or ""
        # Reimport is idempotent: drop any prior copy for this order/panel first.
        existing = db.scalars(
            select(OutsourcedPanelTable).where(
                OutsourcedPanelTable.order_id == order_id,
                OutsourcedPanelTable.panel_label == panel_label,
            )
        ).first()
        if existing is not None:
            db.delete(existing)
            db.flush()
        panel_table = OutsourcedPanelTable(
            order_id=order_id,
            panel_label=panel_label,
            source_pdf_path=_clean_text(table_row["source_pdf_path"], fallback="") or "",
        )
        db.add(panel_table)
        db.flush()

        extraction_ids: dict[int, Any] = {}
        if has_extractions:
            for extraction in sqlite_db.execute(
                """
                SELECT id, source_pdf_path, page_label, row_count, extracted_at
                FROM outsourced_panel_extractions
                WHERE outsourced_panel_table_id = ?
                ORDER BY id ASC
                """,
                (int(table_row["id"]),),
            ).fetchall():
                new_extraction = OutsourcedPanelExtraction(
                    outsourced_panel_table_id=panel_table.id,
                    source_pdf_path=_clean_text(extraction["source_pdf_path"], fallback="") or "",
                    page_label=_clean_text(extraction["page_label"], fallback="") or "",
                    row_count=_parse_int(extraction["row_count"]) or 0,
                    extracted_at=_parse_datetime(extraction["extracted_at"]) or datetime.utcnow(),
                )
                db.add(new_extraction)
                db.flush()
                extraction_ids[int(extraction["id"])] = new_extraction.id

        if has_rows:
            for source_row in sqlite_db.execute(
                """
                SELECT row_index, col_1, col_2, col_3, col_4, col_5, extraction_id
                FROM outsourced_panel_rows
                WHERE outsourced_panel_table_id = ?
                ORDER BY row_index ASC, id ASC
                """,
                (int(table_row["id"]),),
            ).fetchall():
                db.add(
                    OutsourcedPanelRow(
                        outsourced_panel_table_id=panel_table.id,
                        extraction_id=extraction_ids.get(_parse_int(source_row["extraction_id"]) or -1),
                        row_index=_parse_int(source_row["row_index"]) or 0,
                        col_1=_clean_text(source_row["col_1"]),
                        col_2=_clean_text(source_row["col_2"]),
                        col_3=_clean_text(source_row["col_3"]),
                        col_4=_clean_text(source_row["col_4"]),
                        col_5=_clean_text(source_row["col_5"]),
                    )
                )
        imported += 1
    db.flush()
    return imported


def _sqlite_has_table(sqlite_db: sqlite3.Connection, name: str) -> bool:
    return (
        sqlite_db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        is not None
    )


def _ensure_import_user(db: Session) -> AppUser:
    user = db.scalars(select(AppUser).where(AppUser.email == "migration@spdxlims.local")).first()
    if user is None:
        user = AppUser(
            email="migration@spdxlims.local",
            full_name="Legacy Data Import",
            role="admin",
            password_hash="import-only-account",
            is_active=True,
        )
        db.add(user)
        db.flush()
    return user


def _delete_existing_order_children(db: Session, order_id: Any) -> None:
    report = db.scalars(select(ReportSnapshot).where(ReportSnapshot.order_id == order_id)).first()
    if report is not None:
        db.execute(delete(ReportItemImageSnapshot).where(ReportItemImageSnapshot.report_id == report.id))
        db.execute(delete(ReportItemSnapshot).where(ReportItemSnapshot.report_id == report.id))
        db.execute(delete(ReportSnapshot).where(ReportSnapshot.id == report.id))

    order_item_ids = db.scalars(select(OrderItem.id).where(OrderItem.order_id == order_id)).all()
    if order_item_ids:
        db.execute(delete(ResultImage).where(ResultImage.order_item_id.in_(order_item_ids)))
        db.execute(delete(Result).where(Result.order_item_id.in_(order_item_ids)))
    db.execute(delete(OrderItem).where(OrderItem.order_id == order_id))
    db.flush()


def _copy_profile_asset(sqlite_path: Path, raw_path: Any, stem: str) -> str | None:
    resolved_source = _resolve_legacy_path(sqlite_path, raw_path)
    if resolved_source is None or not resolved_source.exists():
        return None
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = resolved_source.suffix.lower() or ".bin"
    target = UPLOAD_DIR / f"{stem}{suffix}"
    shutil.copyfile(resolved_source, target)
    return f"/static/uploads/{target.name}"


def _resolve_legacy_path(sqlite_path: Path, raw_path: Any) -> Path | None:
    value = _clean_text(raw_path)
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    repo_root = sqlite_path.parent.parent
    probe_paths = [
        sqlite_path.parent / candidate,
        repo_root / candidate,
    ]
    for probe in probe_paths:
        if probe.exists():
            return probe
    return sqlite_path.parent / candidate


def _clean_text(value: Any, *, fallback: str | None = None) -> str | None:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    return text


def _parse_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float(value: Any) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _parse_decimal(value: Any, *, default: str) -> Decimal:
    text = _clean_text(value, fallback=default) or default
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal(default)


def _parse_date(value: Any) -> date | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace(" ", "T")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _normalize_age_unit(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.lower()
    mapping = {
        "day": "days",
        "days": "days",
        "month": "months",
        "months": "months",
        "year": "years",
        "years": "years",
        "d": "days",
        "m": "months",
        "y": "years",
    }
    return mapping.get(normalized, normalized)


def _normalize_sex(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text[:1].upper()
    if normalized in {"M", "F"}:
        return normalized
    return None


def _normalize_reference_sex(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"male", "m", "masculino"}:
        return "M"
    if lowered in {"female", "f", "femenino"}:
        return "F"
    return None


def _normalize_result_kind(value: Any) -> str:
    text = (_clean_text(value, fallback="text") or "text").lower()
    if text in {"numeric", "number"}:
        return "numeric"
    if text in {"select", "choice", "options"}:
        return "select"
    return "text"


def _normalize_order_status(value: Any) -> str:
    text = (_clean_text(value, fallback="registered") or "registered").lower()
    allowed = {"registered", "in_lab", "reported", "cancelled"}
    return text if text in allowed else "registered"


def _normalize_select_options(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    parts = [part.strip() for part in text.replace("\r", "\n").split("\n")]
    cleaned = [part for part in parts if part]
    return "\n".join(cleaned) if cleaned else None


def _range_text(text_value: Any, numeric_value: Any) -> str | None:
    text = _clean_text(text_value)
    if text:
        return text
    return _clean_text(numeric_value)


if __name__ == "__main__":
    main()
