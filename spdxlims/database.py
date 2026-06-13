from __future__ import annotations

import json
import re
import shutil
import sqlite3
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from spdxlims.i18n import tr
from spdxlims.whatsapp_phone import DEFAULT_COUNTRY_CODE, clean_country_code


@dataclass(slots=True)
class PatientRecord:
    id: int
    patient_code: str | None
    first_name: str
    last_name: str
    middle_name: str | None
    sex: str | None
    date_of_birth: str | None
    age_value: int | None
    age_unit: str | None
    phone: str | None
    is_active: int


@dataclass(slots=True)
class LabSettingsRecord:
    lab_name: str
    address: str
    phone: str
    email: str
    logo_path: str
    header_image_path: str
    footer_signature_image_path: str
    report_footer: str
    director_name: str
    director_license: str
    sat_rfc: str
    sat_fiscal_regime: str
    sat_postal_code: str
    sat_certificate_path: str
    sat_key_path: str
    ui_language: str
    report_flag_style: str
    keep_panels_together: int
    report_font_family: str
    report_font_size: int
    report_font_bold: int
    report_abnormal_bold: int
    report_subheading_font_family: str
    report_subheading_font_size: int
    report_subheading_font_bold: int
    report_footer_gap_mm: int
    ui_state: str
    report_sex_format: str = "short"
    report_date_format: str = "auto"
    report_show_doctor: int = 1
    report_show_client: int = 1
    report_show_sex: int = 1
    report_show_age: int = 1
    report_show_dob: int = 1
    report_show_ordered_at: int = 1
    report_show_reported_at: int = 1
    report_doctor_col: str = "left"
    report_client_col: str = "left"
    report_sex_col: str = "left"
    report_age_col: str = "right"
    report_dob_col: str = "right"
    report_ordered_at_col: str = "right"
    report_reported_at_col: str = "right"


@dataclass(slots=True)
class DoctorRecord:
    id: int
    full_name: str
    license_number: str | None
    phone: str | None
    email: str | None
    is_active: int


@dataclass(slots=True)
class ClientRecord:
    id: int
    name: str
    phone: str | None
    email: str | None
    tax_id: str | None
    fiscal_regime: str | None
    postal_code: str | None
    cfdi_use: str | None
    is_active: int


@dataclass(slots=True)
class BillingCustomerRecord:
    id: int
    name: str
    phone: str | None
    email: str | None
    outstanding_balance: float
    invoice_count: int
    is_active: int


@dataclass(slots=True)
class EquipmentRecord:
    id: int
    name: str
    equipment_type: str | None
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    location: str | None
    status: str
    last_maintenance_date: str | None
    next_maintenance_date: str | None
    notes: str | None


@dataclass(slots=True)
class TestRecord:
    id: int
    code: str
    name: str
    category_name: str | None
    specimen_type: str | None
    method: str | None
    result_kind: str
    select_options: str | None
    default_result_value: str | None
    price: float | None
    is_active: int
    range_count: int
    result_multiplier: float | None = None


@dataclass(slots=True)
class PanelRecord:
    id: int
    code: str
    name: str
    specimen_type: str | None
    method: str | None
    is_active: int
    test_names: str | None


@dataclass(slots=True)
class PanelItemRecord:
    item_type: str
    test_id: int | None
    heading_text: str | None
    sort_order: int
    label: str


@dataclass(slots=True)
class InventoryItemRecord:
    id: int
    sku: str
    name: str
    unit: str | None
    on_hand: float
    reorder_level: float
    unit_cost: float


@dataclass(slots=True)
class SupplierRecord:
    id: int
    name: str
    phone: str | None
    email: str | None
    tax_id: str | None


@dataclass(slots=True)
class InventoryMovementRecord:
    id: int
    inventory_item_id: int
    inventory_name: str
    supplier_name: str | None
    movement_type: str
    quantity: float
    unit_cost: float
    movement_date: str
    notes: str | None


@dataclass(slots=True)
class InvoiceRecord:
    id: int
    invoice_number: str
    client_id: int | None
    client_name: str | None
    order_id: int | None
    order_number: str | None
    invoice_date: str
    status: str
    total_amount: float
    notes: str | None
    cfdi_use: str | None
    payment_form: str | None
    payment_method: str | None
    currency: str | None
    xml_path: str | None


@dataclass(slots=True)
class ReceiptRecord:
    id: int
    receipt_number: str
    order_id: int
    order_number: str
    client_name: str | None
    patient_name: str
    receipt_date: str
    total_amount: float
    notes: str | None
    payment_form: str | None
    payment_method: str | None
    currency: str | None


@dataclass(slots=True)
class OrderSummaryRecord:
    id: int
    order_number: str
    patient_name: str
    doctor_name: str | None
    status: str
    created_at: str
    item_count: int
    all_results_entered: bool


@dataclass(slots=True)
class OrderBrowserRecord:
    id: int
    order_number: str
    order_date: str
    patient_name: str
    client_name: str | None
    doctor_name: str | None
    status: str
    item_count: int


@dataclass(slots=True)
class ResultWorkflowRecord:
    id: int
    order_number: str
    order_date: str
    patient_name: str
    patient_phone: str | None
    doctor_name: str | None
    client_name: str | None
    client_phone: str | None
    report_version: int | None
    report_finalized_at: str | None
    result_count: int
    completed_result_count: int
    report_outdated: int = 0


@dataclass(slots=True)
class OutsourcedPanelChoiceRecord:
    order_id: int
    order_number: str
    patient_name: str
    panel_label: str


@dataclass(slots=True)
class OrderLookupRecord:
    id: int
    order_number: str
    status: str
    is_preallocated: int


@dataclass(slots=True)
class OrderEditRecord:
    id: int
    order_number: str
    accession_id: str | None
    sample_id: str | None
    patient_id: int | None
    doctor_id: int | None
    client_id: int | None
    status: str
    notes: str | None
    is_preallocated: int
    items: list[dict[str, Any]]


@dataclass(slots=True)
class ResultEntryRecord:
    order_test_id: int
    order_id: int
    order_number: str
    patient_name: str
    doctor_name: str | None
    patient_sex: str | None
    patient_age_days: int | None
    test_id: int
    test_name: str
    specimen_type: str | None
    item_type: str
    result_kind: str
    select_options: str | None
    default_result_value: str | None
    result_value: str | None
    unit: str | None
    lower_value: str | None
    upper_value: str | None
    flag: str | None
    reference_text: str | None
    comments: str | None
    test_status: str
    is_outsourced: int
    source_label: str | None
    result_multiplier: float | None = None


@dataclass(slots=True)
class InstrumentResultMappingRecord:
    id: int
    instrument_profile: str
    device_id: str | None
    raw_code: str
    raw_name: str | None
    specimen_type: str | None
    panel_hint: str | None
    test_id: int
    test_code: str
    test_name: str
    unit_override: str | None
    reference_range_override: str | None
    is_active: int
    value_slice_start: int | None = None
    value_slice_end: int | None = None
    value_multiplier: float | None = None
    decimal_places: int | None = None
    value_formula: str | None = None


@dataclass(slots=True)
class InstrumentOrderMatchRecord:
    instrument_profile: str
    instrument_field: str
    order_field: str
    auto_import: int = 1
    broadcast_enabled: int = 0
    broadcast_protocol: str = "hl7_orm"
    broadcast_encoding: str = "ascii"
    broadcast_patient_id: int = 1
    broadcast_patient_name: int = 1
    broadcast_dob: int = 1
    broadcast_age: int = 1
    broadcast_sex: int = 1
    broadcast_doctor: int = 1


@dataclass(slots=True)
class TestReferenceRangeRecord:
    sex: str | None
    age_min_days: int | None
    age_max_days: int | None
    lower_value: str | None
    upper_value: str | None
    unit: str
    reference_text: str | None


class Database:
    URINALYSIS_STRIP_TESTS = (
        ("EGO-LEU", "Urine leukocytes", "Urinalysis", "Urine", "Strip reader", "text", ""),
        ("EGO-NIT", "Urine nitrite", "Urinalysis", "Urine", "Strip reader", "text", ""),
        ("EGO-URO", "Urine urobilinogen", "Urinalysis", "Urine", "Strip reader", "text", "mg/dL"),
        ("EGO-PRO", "Urine protein", "Urinalysis", "Urine", "Strip reader", "text", "mg/dL"),
        ("EGO-PH", "Urine pH", "Urinalysis", "Urine", "Strip reader", "text", ""),
        ("EGO-BLO", "Urine blood", "Urinalysis", "Urine", "Strip reader", "text", ""),
        ("EGO-SG", "Urine specific gravity", "Urinalysis", "Urine", "Strip reader", "text", ""),
        ("EGO-KET", "Urine ketones", "Urinalysis", "Urine", "Strip reader", "text", ""),
        ("EGO-BIL", "Urine bilirubin", "Urinalysis", "Urine", "Strip reader", "text", ""),
        ("EGO-GLU", "Urine glucose", "Urinalysis", "Urine", "Strip reader", "text", ""),
    )

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.assets_dir = db_path.parent / "assets" / "lab"
        self.assets_dir.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'tech', 'reviewer')),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS patients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_code TEXT UNIQUE,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    middle_name TEXT,
                    sex TEXT CHECK (sex IN ('M', 'F', 'O')),
                    date_of_birth DATE,
                    age_value INTEGER,
                    age_unit TEXT CHECK (age_unit IN ('days', 'months', 'years')),
                    phone TEXT,
                    email TEXT,
                    address TEXT,
                    national_id TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS doctors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    license_number TEXT,
                    phone TEXT,
                    email TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT,
                    email TEXT,
                    tax_id TEXT,
                    fiscal_regime TEXT,
                    postal_code TEXT,
                    cfdi_use TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS equipment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    equipment_type TEXT,
                    manufacturer TEXT,
                    model TEXT,
                    serial_number TEXT UNIQUE,
                    location TEXT,
                    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'maintenance', 'out_of_service', 'retired')),
                    last_maintenance_date DATE,
                    next_maintenance_date DATE,
                    notes TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS inventory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    unit TEXT,
                    on_hand REAL NOT NULL DEFAULT 0,
                    reorder_level REAL NOT NULL DEFAULT 0,
                    unit_cost REAL NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS suppliers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    phone TEXT,
                    email TEXT,
                    tax_id TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS inventory_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inventory_item_id INTEGER NOT NULL,
                    supplier_id INTEGER,
                    movement_type TEXT NOT NULL CHECK (movement_type IN ('purchase', 'adjustment_in', 'adjustment_out', 'consumption')),
                    quantity REAL NOT NULL,
                    unit_cost REAL NOT NULL DEFAULT 0,
                    movement_date DATE NOT NULL,
                    notes TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (inventory_item_id) REFERENCES inventory_items(id),
                    FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
                );

                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT NOT NULL UNIQUE,
                    client_id INTEGER,
                    order_id INTEGER,
                    invoice_date DATE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'issued' CHECK (status IN ('draft', 'issued', 'paid', 'cancelled')),
                    total_amount REAL NOT NULL DEFAULT 0,
                    notes TEXT,
                    cfdi_use TEXT,
                    payment_form TEXT,
                    payment_method TEXT,
                    currency TEXT NOT NULL DEFAULT 'MXN',
                    xml_path TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES clients(id),
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS invoice_order_links (
                    invoice_id INTEGER NOT NULL,
                    order_id INTEGER NOT NULL UNIQUE,
                    PRIMARY KEY (invoice_id, order_id),
                    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_number TEXT NOT NULL UNIQUE,
                    order_id INTEGER NOT NULL UNIQUE,
                    receipt_date DATE NOT NULL,
                    total_amount REAL NOT NULL DEFAULT 0,
                    notes TEXT,
                    payment_form TEXT,
                    payment_method TEXT,
                    currency TEXT NOT NULL DEFAULT 'MXN',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS test_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    category_id INTEGER,
                    specimen_type TEXT,
                    method TEXT,
                    result_kind TEXT NOT NULL CHECK (result_kind IN ('numeric', 'text', 'select')),
                    select_options TEXT,
                    default_result_value TEXT,
                    price REAL NOT NULL DEFAULT 0,
                    result_multiplier REAL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (category_id) REFERENCES test_categories(id)
                );

                CREATE TABLE IF NOT EXISTS client_test_prices (
                    client_id INTEGER NOT NULL,
                    test_id INTEGER NOT NULL,
                    price REAL NOT NULL,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (client_id, test_id),
                    FOREIGN KEY (client_id) REFERENCES clients(id),
                    FOREIGN KEY (test_id) REFERENCES tests(id)
                );

                CREATE TABLE IF NOT EXISTS test_reference_ranges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_id INTEGER NOT NULL,
                    sex TEXT CHECK (sex IN ('M', 'F', 'O') OR sex IS NULL),
                    age_min_days INTEGER,
                    age_max_days INTEGER,
                    lower_value REAL,
                    upper_value REAL,
                    lower_value_text TEXT,
                    upper_value_text TEXT,
                    unit TEXT NOT NULL,
                    reference_text TEXT,
                    FOREIGN KEY (test_id) REFERENCES tests(id)
                );

                CREATE TABLE IF NOT EXISTS test_panels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    specimen_type TEXT,
                    method TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS test_panel_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    panel_id INTEGER NOT NULL,
                    test_id INTEGER,
                    item_type TEXT NOT NULL DEFAULT 'test' CHECK (item_type IN ('test', 'heading', 'comment')),
                    heading_text TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (panel_id) REFERENCES test_panels(id) ON DELETE CASCADE,
                    FOREIGN KEY (test_id) REFERENCES tests(id)
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_number TEXT NOT NULL UNIQUE,
                    accession_id TEXT,
                    sample_id TEXT,
                    patient_id INTEGER NOT NULL,
                    doctor_id INTEGER,
                    client_id INTEGER,
                    status TEXT NOT NULL CHECK (status IN ('draft', 'in_progress', 'finalized', 'cancelled')),
                    is_preallocated INTEGER NOT NULL DEFAULT 0,
                    ordered_at DATETIME,
                    collected_at DATETIME,
                    reported_at DATETIME,
                    notes TEXT,
                    created_by INTEGER,
                    finalized_by INTEGER,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (patient_id) REFERENCES patients(id),
                    FOREIGN KEY (doctor_id) REFERENCES doctors(id),
                    FOREIGN KEY (client_id) REFERENCES clients(id),
                    FOREIGN KEY (created_by) REFERENCES users(id),
                    FOREIGN KEY (finalized_by) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS order_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    test_id INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'entered', 'validated', 'reported')),
                    is_outsourced INTEGER NOT NULL DEFAULT 0,
                    source_label TEXT,
                    display_name TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (order_id, test_id),
                    FOREIGN KEY (order_id) REFERENCES orders(id),
                    FOREIGN KEY (test_id) REFERENCES tests(id)
                );

                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_test_id INTEGER NOT NULL UNIQUE,
                    result_value TEXT,
                    unit TEXT,
                    lower_value REAL,
                    upper_value REAL,
                    flag TEXT CHECK (flag IN ('low', 'normal', 'high', 'abnormal', 'none')),
                    reference_text TEXT,
                    comments TEXT,
                    entered_by INTEGER,
                    entered_at DATETIME,
                    reviewed_by INTEGER,
                    reviewed_at DATETIME,
                    FOREIGN KEY (order_test_id) REFERENCES order_tests(id),
                    FOREIGN KEY (entered_by) REFERENCES users(id),
                    FOREIGN KEY (reviewed_by) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS instrument_result_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_profile TEXT NOT NULL,
                    device_id TEXT,
                    raw_code TEXT NOT NULL,
                    raw_name TEXT,
                    specimen_type TEXT,
                    panel_hint TEXT,
                    test_id INTEGER NOT NULL,
                    unit_override TEXT,
                    reference_range_override TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (test_id) REFERENCES tests(id),
                    UNIQUE (
                        instrument_profile,
                        device_id,
                        raw_code,
                        specimen_type,
                        panel_hint
                    )
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL UNIQUE,
                    report_version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL CHECK (status IN ('draft', 'final')),
                    finalized_at DATETIME,
                    finalized_by INTEGER,
                    patient_snapshot_name TEXT NOT NULL,
                    patient_snapshot_sex TEXT,
                    patient_snapshot_dob DATE,
                    doctor_snapshot_name TEXT,
                    lab_snapshot_name TEXT NOT NULL,
                    lab_snapshot_address TEXT,
                    lab_snapshot_phone TEXT,
                    lab_snapshot_email TEXT,
                    director_snapshot_name TEXT,
                    director_snapshot_license TEXT,
                    footer_snapshot_text TEXT,
                    header_image_snapshot_path TEXT,
                    footer_signature_snapshot_path TEXT,
                    general_comments TEXT,
                    FOREIGN KEY (order_id) REFERENCES orders(id),
                    FOREIGN KEY (finalized_by) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS report_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id INTEGER NOT NULL,
                    order_test_id INTEGER NOT NULL,
                    test_name_snapshot TEXT NOT NULL,
                    result_value_snapshot TEXT,
                    unit_snapshot TEXT,
                    reference_text_snapshot TEXT,
                    lower_value_snapshot REAL,
                    upper_value_snapshot REAL,
                    lower_value_snapshot_text TEXT,
                    upper_value_snapshot_text TEXT,
                    flag_snapshot TEXT,
                    comments_snapshot TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (report_id) REFERENCES reports(id),
                    FOREIGN KEY (order_test_id) REFERENCES order_tests(id)
                );

                CREATE TABLE IF NOT EXISTS outsourced_panel_tables (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    panel_label TEXT NOT NULL,
                    source_pdf_path TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (order_id, panel_label),
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS outsourced_panel_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    outsourced_panel_table_id INTEGER NOT NULL,
                    row_index INTEGER NOT NULL,
                    col_1 TEXT,
                    col_2 TEXT,
                    col_3 TEXT,
                    col_4 TEXT,
                    col_5 TEXT,
                    FOREIGN KEY (outsourced_panel_table_id) REFERENCES outsourced_panel_tables(id)
                );

                CREATE TABLE IF NOT EXISTS report_outsourced_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id INTEGER NOT NULL,
                    panel_label TEXT NOT NULL,
                    source_pdf_path TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    col_1 TEXT,
                    col_2 TEXT,
                    col_3 TEXT,
                    col_4 TEXT,
                    col_5 TEXT,
                    FOREIGN KEY (report_id) REFERENCES reports(id)
                );

                CREATE TABLE IF NOT EXISTS lab_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    lab_name TEXT NOT NULL DEFAULT '',
                    address TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    logo_path TEXT NOT NULL DEFAULT '',
                    header_image_path TEXT NOT NULL DEFAULT '',
                    footer_signature_image_path TEXT NOT NULL DEFAULT '',
                    report_footer TEXT NOT NULL DEFAULT '',
                    director_name TEXT NOT NULL DEFAULT '',
                    director_license TEXT NOT NULL DEFAULT '',
                    sat_rfc TEXT NOT NULL DEFAULT '',
                    sat_fiscal_regime TEXT NOT NULL DEFAULT '',
                    sat_postal_code TEXT NOT NULL DEFAULT '',
                    sat_certificate_path TEXT NOT NULL DEFAULT '',
                    sat_key_path TEXT NOT NULL DEFAULT '',
                    ui_language TEXT NOT NULL DEFAULT 'es',
                    report_flag_style TEXT NOT NULL DEFAULT 'arrows',
                    keep_panels_together INTEGER NOT NULL DEFAULT 0,
                    report_font_family TEXT NOT NULL DEFAULT 'Segoe UI',
                    report_font_size INTEGER NOT NULL DEFAULT 12,
                    report_font_bold INTEGER NOT NULL DEFAULT 0,
                    report_abnormal_bold INTEGER NOT NULL DEFAULT 0,
                    report_subheading_font_family TEXT NOT NULL DEFAULT 'Segoe UI',
                    report_subheading_font_size INTEGER NOT NULL DEFAULT 13,
                    report_subheading_font_bold INTEGER NOT NULL DEFAULT 1,
                    report_footer_gap_mm INTEGER NOT NULL DEFAULT 8,
                    report_sex_format TEXT NOT NULL DEFAULT 'short',
                    report_date_format TEXT NOT NULL DEFAULT 'auto',
                    report_show_doctor INTEGER NOT NULL DEFAULT 1,
                    report_show_client INTEGER NOT NULL DEFAULT 1,
                    report_show_sex INTEGER NOT NULL DEFAULT 1,
                    report_show_age INTEGER NOT NULL DEFAULT 1,
                    report_show_dob INTEGER NOT NULL DEFAULT 1,
                    report_show_ordered_at INTEGER NOT NULL DEFAULT 1,
                    report_show_reported_at INTEGER NOT NULL DEFAULT 1,
                    report_doctor_col TEXT NOT NULL DEFAULT 'left',
                    report_client_col TEXT NOT NULL DEFAULT 'left',
                    report_sex_col TEXT NOT NULL DEFAULT 'left',
                    report_age_col TEXT NOT NULL DEFAULT 'right',
                    report_dob_col TEXT NOT NULL DEFAULT 'right',
                    report_ordered_at_col TEXT NOT NULL DEFAULT 'right',
                    report_reported_at_col TEXT NOT NULL DEFAULT 'right',
                    ui_state TEXT NOT NULL DEFAULT '{}',
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                INSERT INTO lab_settings (id)
                SELECT 1
                WHERE NOT EXISTS (SELECT 1 FROM lab_settings WHERE id = 1);
                """
            )
            self._migrate_patients_table(connection)
            self._migrate_orders_table(connection)
            self._migrate_lab_settings_table(connection)
            self._migrate_tests_table(connection)
            self._migrate_client_test_prices_table(connection)
            self._migrate_precision_text_columns(connection)
            self._migrate_test_panels_table(connection)
            self._migrate_test_panel_items_table(connection)
            self._migrate_reports_table(connection)
            self._migrate_outsourced_panel_tables(connection)
            self._migrate_instrument_result_mappings_table(connection)
            self._migrate_equipment_table(connection)
            self._migrate_instrument_order_match_config_table(connection)
            self._migrate_instrument_captures_cache_table(connection)
            self._migrate_doctors_table(connection)
            self._migrate_clients_table(connection)
            self._migrate_inventory_items_table(connection)
            self._migrate_invoices_table(connection)
            self._migrate_suppliers_table(connection)
            self._ensure_urinalysis_strip_tests(connection)

    def list_patients(self, *, status_filter: str = 'active') -> list[PatientRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, patient_code, first_name, last_name, middle_name, sex, date_of_birth, age_value, age_unit, phone, is_active
                FROM patients
                WHERE COALESCE(patient_code, '') != '__PREALLOCATED__'
                  AND (? = 'all' OR (? = 'active' AND is_active = 1) OR (? = 'archived' AND is_active = 0))
                ORDER BY is_active DESC, created_at DESC, id DESC
                """
                , (status_filter, status_filter, status_filter)
            ).fetchall()
        return [PatientRecord(**dict(row)) for row in rows]

    def list_patient_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, first_name, last_name, middle_name, age_value, age_unit FROM patients WHERE COALESCE(patient_code, '') != '__PREALLOCATED__' AND is_active = 1 ORDER BY last_name, first_name, id"
            ).fetchall()
        return [
            (
                row["id"],
                self._format_patient_label(
                    row["first_name"],
                    row["last_name"],
                    row["middle_name"],
                    row["age_value"],
                    row["age_unit"],
                ),
            )
            for row in rows
        ]

    def get_patient(self, patient_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, patient_code, first_name, last_name, middle_name, sex, date_of_birth, age_value, age_unit, phone, email, address, national_id, is_active FROM patients WHERE id = ?",
                (patient_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def create_patient(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO patients (patient_code, first_name, last_name, middle_name, sex, date_of_birth, age_value, age_unit, phone, email, address, national_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(payload.get("patient_code") or "").strip() or None,
                    payload["first_name"].strip(),
                    payload["last_name"].strip(),
                    str(payload.get("middle_name") or "").strip() or None,
                    str(payload.get("sex") or "").strip() or None,
                    str(payload.get("date_of_birth") or "").strip() or None,
                    payload.get("age_value"),
                    str(payload.get("age_unit") or "").strip() or None,
                    str(payload.get("phone") or "").strip() or None,
                    str(payload.get("email") or "").strip() or None,
                    str(payload.get("address") or "").strip() or None,
                    str(payload.get("national_id") or "").strip() or None,
                ),
            )
            return int(cursor.lastrowid)

    def update_patient(self, patient_id: int, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE patients SET first_name = ?, last_name = ?, middle_name = ?, sex = ?, date_of_birth = ?, age_value = ?, age_unit = ?, phone = ?, email = ?, address = ?, national_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    payload["first_name"].strip(),
                    payload["last_name"].strip(),
                    str(payload.get("middle_name") or "").strip() or None,
                    str(payload.get("sex") or "").strip() or None,
                    str(payload.get("date_of_birth") or "").strip() or None,
                    payload.get("age_value"),
                    str(payload.get("age_unit") or "").strip() or None,
                    str(payload.get("phone") or "").strip() or None,
                    str(payload.get("email") or "").strip() or None,
                    str(payload.get("address") or "").strip() or None,
                    str(payload.get("national_id") or "").strip() or None,
                    patient_id,
                ),
            )

    def archive_patient(self, patient_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE patients SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND COALESCE(patient_code, '') != '__PREALLOCATED__'",
                (patient_id,),
            )

    def unarchive_patient(self, patient_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE patients SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND COALESCE(patient_code, '') != '__PREALLOCATED__'",
                (patient_id,),
            )

    def _get_or_create_preallocated_patient(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT id FROM patients WHERE patient_code = '__PREALLOCATED__' LIMIT 1").fetchone()
        if row is not None:
            return int(row["id"])
        cursor = connection.execute(
            "INSERT INTO patients (patient_code, first_name, last_name, middle_name, phone, email, address, national_id) VALUES ('__PREALLOCATED__', 'Unassigned', 'Barcode', NULL, NULL, NULL, NULL, NULL)"
        )
        return int(cursor.lastrowid)

    def list_doctors(self, *, status_filter: str = 'all') -> list[DoctorRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, full_name, license_number, phone, email, is_active
                FROM doctors
                WHERE (? = 'all' OR (? = 'active' AND is_active = 1) OR (? = 'archived' AND is_active = 0))
                ORDER BY is_active DESC, full_name, id
                """,
                (status_filter, status_filter, status_filter),
            ).fetchall()
        return [DoctorRecord(**dict(row)) for row in rows]

    def list_doctor_choices(self, *, active_only: bool = False, include_ids: list[int] | None = None) -> list[tuple[int, str]]:
        include_ids = [int(value) for value in (include_ids or []) if value is not None]
        with self.connect() as connection:
            if active_only and include_ids:
                placeholders = ", ".join("?" for _ in include_ids)
                rows = connection.execute(
                    f"SELECT id, full_name, license_number, is_active FROM doctors WHERE is_active = 1 OR id IN ({placeholders}) ORDER BY is_active DESC, full_name, id",
                    include_ids,
                ).fetchall()
            elif active_only:
                rows = connection.execute(
                    "SELECT id, full_name, license_number, is_active FROM doctors WHERE is_active = 1 ORDER BY full_name, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, full_name, license_number, is_active FROM doctors ORDER BY is_active DESC, full_name, id"
                ).fetchall()
        return [
            (
                row["id"],
                ((row["full_name"] if not row["license_number"] else f'{row["full_name"]} ({row["license_number"]})') + ('' if row["is_active"] else f' [{tr("Archived")}]')),
            )
            for row in rows
        ]

    def get_doctor(self, doctor_id: int) -> DoctorRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT id, full_name, license_number, phone, email, is_active FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
        return DoctorRecord(**dict(row)) if row is not None else None

    def create_doctor(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO doctors (full_name, license_number, phone, email, is_active) VALUES (?, ?, ?, ?, 1)",
                (
                    payload["full_name"].strip(),
                    payload.get("license_number") or None,
                    payload.get("phone") or None,
                    payload.get("email") or None,
                ),
            )
            return int(cursor.lastrowid)

    def update_doctor(self, doctor_id: int, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE doctors SET full_name = ?, license_number = ?, phone = ?, email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    payload["full_name"].strip(),
                    payload.get("license_number") or None,
                    payload.get("phone") or None,
                    payload.get("email") or None,
                    doctor_id,
                ),
            )

    def archive_doctor(self, doctor_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE doctors SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (doctor_id,))

    def unarchive_doctor(self, doctor_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE doctors SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (doctor_id,))

    def list_clients(self, *, status_filter: str = 'all') -> list[ClientRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, phone, email, tax_id, fiscal_regime, postal_code, cfdi_use, is_active
                FROM clients
                WHERE (? = 'all' OR (? = 'active' AND is_active = 1) OR (? = 'archived' AND is_active = 0))
                ORDER BY is_active DESC, name, id
                """,
                (status_filter, status_filter, status_filter),
            ).fetchall()
        return [ClientRecord(**dict(row)) for row in rows]

    def list_billing_customers(self) -> list[BillingCustomerRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.name, c.phone, c.email, c.is_active,
                       COALESCE(SUM(CASE WHEN i.status IN ('draft', 'issued') THEN i.total_amount ELSE 0 END), 0) AS outstanding_balance,
                       COUNT(i.id) AS invoice_count
                FROM clients c
                LEFT JOIN invoices i ON i.client_id = c.id
                GROUP BY c.id, c.name, c.phone, c.email, c.is_active
                ORDER BY c.is_active DESC, c.name, c.id
                """
            ).fetchall()
        return [BillingCustomerRecord(**dict(row)) for row in rows]

    def list_client_choices(self, *, active_only: bool = False, include_ids: list[int] | None = None) -> list[tuple[int, str]]:
        include_ids = [int(value) for value in (include_ids or []) if value is not None]
        with self.connect() as connection:
            if active_only and include_ids:
                placeholders = ", ".join("?" for _ in include_ids)
                rows = connection.execute(
                    f"SELECT id, name, phone, is_active FROM clients WHERE is_active = 1 OR id IN ({placeholders}) ORDER BY is_active DESC, name, id",
                    include_ids,
                ).fetchall()
            elif active_only:
                rows = connection.execute(
                    "SELECT id, name, phone, is_active FROM clients WHERE is_active = 1 ORDER BY name, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, name, phone, is_active FROM clients ORDER BY is_active DESC, name, id"
                ).fetchall()
        return [
            (
                row["id"],
                ((row["name"] if not row["phone"] else f'{row["name"]} ({row["phone"]})') + ('' if row["is_active"] else f' [{tr("Archived")}]')),
            )
            for row in rows
        ]

    def create_client(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO clients (name, phone, email, tax_id, fiscal_regime, postal_code, cfdi_use, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (
                    payload["name"].strip(),
                    str(payload.get("phone") or "").strip() or None,
                    str(payload.get("email") or "").strip() or None,
                    str(payload.get("tax_id") or "").strip() or None,
                    str(payload.get("fiscal_regime") or "").strip() or None,
                    str(payload.get("postal_code") or "").strip() or None,
                    str(payload.get("cfdi_use") or "").strip() or None,
                ),
            )
            return int(cursor.lastrowid)

    def update_client(self, client_id: int, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE clients SET name = ?, phone = ?, email = ?, tax_id = ?, fiscal_regime = ?, postal_code = ?, cfdi_use = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    payload["name"].strip(),
                    str(payload.get("phone") or "").strip() or None,
                    str(payload.get("email") or "").strip() or None,
                    str(payload.get("tax_id") or "").strip() or None,
                    str(payload.get("fiscal_regime") or "").strip() or None,
                    str(payload.get("postal_code") or "").strip() or None,
                    str(payload.get("cfdi_use") or "").strip() or None,
                    client_id,
                ),
            )

    def archive_client(self, client_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE clients SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (client_id,))

    def unarchive_client(self, client_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE clients SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (client_id,))

    def list_inventory_items(self) -> list[InventoryItemRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, sku, name, unit, on_hand, reorder_level, unit_cost FROM inventory_items ORDER BY name, sku"
            ).fetchall()
        return [InventoryItemRecord(**dict(row)) for row in rows]

    def list_inventory_item_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id, sku, name FROM inventory_items ORDER BY name, sku").fetchall()
        return [(row["id"], f'{row["name"]} ({row["sku"]})') for row in rows]

    def create_inventory_item(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO inventory_items (sku, name, unit, on_hand, reorder_level, unit_cost) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    payload["sku"].strip(),
                    payload["name"].strip(),
                    payload.get("unit") or None,
                    payload.get("on_hand") or 0,
                    payload.get("reorder_level") or 0,
                    payload.get("unit_cost") or 0,
                ),
            )
            return int(cursor.lastrowid)

    def list_suppliers(self) -> list[SupplierRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id, name, phone, email, tax_id FROM suppliers ORDER BY name, id").fetchall()
        return [SupplierRecord(**dict(row)) for row in rows]

    def list_supplier_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id, name, tax_id FROM suppliers ORDER BY name, id").fetchall()
        return [(row["id"], row["name"] if not row["tax_id"] else f'{row["name"]} ({row["tax_id"]})') for row in rows]

    def create_supplier(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO suppliers (name, phone, email, tax_id) VALUES (?, ?, ?, ?)",
                (payload["name"].strip(), payload.get("phone") or None, payload.get("email") or None, payload.get("tax_id") or None),
            )
            return int(cursor.lastrowid)

    def list_inventory_movements(self) -> list[InventoryMovementRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.id, m.inventory_item_id, ii.name AS inventory_name, s.name AS supplier_name,
                       m.movement_type, m.quantity, m.unit_cost, m.movement_date, m.notes
                FROM inventory_movements m
                INNER JOIN inventory_items ii ON ii.id = m.inventory_item_id
                LEFT JOIN suppliers s ON s.id = m.supplier_id
                ORDER BY m.movement_date DESC, m.id DESC
                """
            ).fetchall()
        return [InventoryMovementRecord(**dict(row)) for row in rows]

    def create_inventory_movement(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            quantity = float(payload.get("quantity") or 0)
            movement_type = payload.get("movement_type") or "purchase"
            signed_quantity = quantity if movement_type in {"purchase", "adjustment_in"} else -abs(quantity)
            cursor = connection.execute(
                "INSERT INTO inventory_movements (inventory_item_id, supplier_id, movement_type, quantity, unit_cost, movement_date, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    payload["inventory_item_id"],
                    payload.get("supplier_id"),
                    movement_type,
                    signed_quantity,
                    payload.get("unit_cost") or 0,
                    payload["movement_date"].strip(),
                    payload.get("notes") or None,
                ),
            )
            connection.execute(
                "UPDATE inventory_items SET on_hand = on_hand + ?, unit_cost = CASE WHEN ? > 0 THEN ? ELSE unit_cost END, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (signed_quantity, payload.get("unit_cost") or 0, payload.get("unit_cost") or 0, payload["inventory_item_id"]),
            )
            return int(cursor.lastrowid)

    def next_invoice_number(self) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM invoices ORDER BY id DESC LIMIT 1").fetchone()
        next_id = (int(row["id"]) + 1) if row is not None else 1
        return f"INV-{next_id:06d}"

    def next_receipt_number(self) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM receipts ORDER BY id DESC LIMIT 1").fetchone()
        next_id = (int(row["id"]) + 1) if row is not None else 1
        return f"REC-{next_id:06d}"

    def list_invoice_order_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT o.id, o.order_number, TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name FROM orders o INNER JOIN patients p ON p.id = o.patient_id WHERE COALESCE(o.is_preallocated, 0) = 0 ORDER BY o.created_at DESC, o.id DESC LIMIT 100").fetchall()
        return [(row["id"], f'{row["order_number"]} - {row["patient_name"]}') for row in rows]

    def list_filtered_invoice_order_choices(
        self,
        *,
        client_id: int | None = None,
        date_from: str = "",
        date_to: str = "",
        exclude_invoiced: bool = True,
    ) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,
                       o.order_number,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       c.name AS client_name,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE
                               WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name
                               ELSE ''
                           END
                       ) AS patient_name,
                       COALESCE(
                           SUM(
                               CASE
                                   WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN COALESCE(t.price, 0)
                                   ELSE 0
                               END
                           ),
                           0
                       ) AS total_amount
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                WHERE COALESCE(o.is_preallocated, 0) = 0
                  AND (? IS NULL OR o.client_id = ?)
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) >= DATE(?))
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) <= DATE(?))
                  AND (
                      ? = 0
                      OR (
                          NOT EXISTS (SELECT 1 FROM invoices i WHERE i.order_id = o.id)
                          AND NOT EXISTS (SELECT 1 FROM invoice_order_links iol WHERE iol.order_id = o.id)
                      )
                  )
                GROUP BY o.id, o.order_number, order_date, c.name, patient_name
                ORDER BY DATE(COALESCE(o.ordered_at, o.created_at)) DESC, o.id DESC
                """,
                (
                    client_id,
                    client_id,
                    date_from,
                    date_from,
                    date_to,
                    date_to,
                    1 if exclude_invoiced else 0,
                ),
            ).fetchall()
        return [
            (
                row["id"],
                f'{row["order_number"]} - {row["patient_name"]} - {row["client_name"] or "No Client"} - {row["order_date"] or ""} - ${float(row["total_amount"] or 0):.2f}',
            )
            for row in rows
        ]

    def list_receipt_order_choices(
        self,
        *,
        client_id: int | None = None,
        date_from: str = "",
        date_to: str = "",
        exclude_receipted: bool = True,
    ) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,
                       o.order_number,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       c.name AS client_name,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE
                               WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name
                               ELSE ''
                           END
                       ) AS patient_name,
                       COALESCE(
                           SUM(
                               CASE
                                   WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN COALESCE(t.price, 0)
                                   ELSE 0
                               END
                           ),
                           0
                       ) AS total_amount
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                WHERE COALESCE(o.is_preallocated, 0) = 0
                  AND (? IS NULL OR o.client_id = ?)
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) >= DATE(?))
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) <= DATE(?))
                  AND (? = 0 OR NOT EXISTS (SELECT 1 FROM receipts r WHERE r.order_id = o.id))
                GROUP BY o.id, o.order_number, order_date, c.name, patient_name
                ORDER BY DATE(COALESCE(o.ordered_at, o.created_at)) DESC, o.id DESC
                """,
                (
                    client_id,
                    client_id,
                    date_from,
                    date_from,
                    date_to,
                    date_to,
                    1 if exclude_receipted else 0,
                ),
            ).fetchall()
        return [
            (
                row["id"],
                f'{row["order_number"]} - {row["patient_name"]} - {row["client_name"] or "No Client"} - {row["order_date"] or ""} - ${float(row["total_amount"] or 0):.2f}',
            )
            for row in rows
        ]

    def calculate_order_total(self, order_id: int) -> float:
        with self.connect() as connection:
            row = connection.execute("SELECT COALESCE(SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN COALESCE(t.price, 0) ELSE 0 END), 0) AS total FROM order_tests ot INNER JOIN tests t ON t.id = ot.test_id WHERE ot.order_id = ?", (order_id,)).fetchone()
        return float(row["total"] if row is not None else 0)

    def get_order_client_id(self, order_id: int) -> int | None:
        with self.connect() as connection:
            row = connection.execute("SELECT client_id FROM orders WHERE id = ?", (int(order_id),)).fetchone()
        if row is None or row["client_id"] is None:
            return None
        return int(row["client_id"])

    def create_invoices_for_orders(
        self,
        order_ids: list[int],
        *,
        invoice_date: str,
        status: str = "issued",
        notes: str | None = None,
        payment_form: str | None = None,
        payment_method: str | None = None,
        currency: str = "MXN",
    ) -> tuple[int, int]:
        created = 0
        skipped = 0
        normalized_order_ids = [int(order_id) for order_id in order_ids]
        with self.connect() as connection:
            for order_id in normalized_order_ids:
                existing = connection.execute(
                    "SELECT id FROM invoices WHERE order_id = ?",
                    (order_id,),
                ).fetchone()
                if existing is not None:
                    skipped += 1
                    continue
                order_row = connection.execute(
                    "SELECT client_id FROM orders WHERE id = ?",
                    (order_id,),
                ).fetchone()
                if order_row is None or order_row["client_id"] is None:
                    skipped += 1
                    continue
                client = self.get_client(int(order_row["client_id"]))
                connection.execute(
                    """
                    INSERT INTO invoices (
                        invoice_number,
                        client_id,
                        order_id,
                        invoice_date,
                        status,
                        total_amount,
                        notes,
                        cfdi_use,
                        payment_form,
                        payment_method,
                        currency,
                        xml_path
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.next_invoice_number(),
                        order_row["client_id"],
                        order_id,
                        invoice_date.strip(),
                        status or "issued",
                        self.calculate_order_total(order_id),
                        notes or None,
                        client.cfdi_use if client is not None else None,
                        payment_form or None,
                        payment_method or None,
                        currency or "MXN",
                        None,
                    ),
                )
                created += 1
        return created, skipped

    def create_client_invoices_for_orders(
        self,
        order_ids: list[int],
        *,
        invoice_date: str,
        status: str = "issued",
        notes: str | None = None,
        payment_form: str | None = None,
        payment_method: str | None = None,
        currency: str = "MXN",
    ) -> tuple[int, int, int]:
        created = 0
        linked_orders = 0
        skipped = 0
        normalized_order_ids = [int(order_id) for order_id in order_ids]
        if not normalized_order_ids:
            return created, linked_orders, skipped

        placeholders = ",".join("?" for _ in normalized_order_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT o.id,
                       o.order_number,
                       o.client_id,
                       c.cfdi_use,
                       COALESCE(
                           SUM(
                               CASE
                                   WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN COALESCE(t.price, 0)
                                   ELSE 0
                               END
                           ),
                           0
                       ) AS total_amount
                FROM orders o
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                WHERE o.id IN ({placeholders})
                  AND COALESCE(o.is_preallocated, 0) = 0
                GROUP BY o.id, o.order_number, o.client_id, c.cfdi_use
                ORDER BY o.client_id, o.id
                """,
                tuple(normalized_order_ids),
            ).fetchall()
            last_invoice_id_row = connection.execute("SELECT id FROM invoices ORDER BY id DESC LIMIT 1").fetchone()
            next_invoice_id = (int(last_invoice_id_row["id"]) + 1) if last_invoice_id_row is not None else 1
            orders_by_client: dict[int, list[sqlite3.Row]] = {}
            found_ids = {int(row["id"]) for row in rows}
            skipped += len(set(normalized_order_ids) - found_ids)
            for row in rows:
                order_id = int(row["id"])
                if row["client_id"] is None:
                    skipped += 1
                    continue
                existing = connection.execute(
                    """
                    SELECT 1
                    FROM invoices i
                    WHERE i.order_id = ?
                    UNION
                    SELECT 1
                    FROM invoice_order_links iol
                    WHERE iol.order_id = ?
                    LIMIT 1
                    """,
                    (order_id, order_id),
                ).fetchone()
                if existing is not None:
                    skipped += 1
                    continue
                orders_by_client.setdefault(int(row["client_id"]), []).append(row)

            for client_id, client_orders in orders_by_client.items():
                order_numbers = ", ".join(str(row["order_number"]) for row in client_orders)
                invoice_notes = notes or None
                if order_numbers:
                    invoice_notes = f"{invoice_notes}\nOrders: {order_numbers}" if invoice_notes else f"Orders: {order_numbers}"
                cursor = connection.execute(
                    """
                    INSERT INTO invoices (
                        invoice_number,
                        client_id,
                        order_id,
                        invoice_date,
                        status,
                        total_amount,
                        notes,
                        cfdi_use,
                        payment_form,
                        payment_method,
                        currency,
                        xml_path
                    )
                    VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"INV-{next_invoice_id:06d}",
                        client_id,
                        invoice_date.strip(),
                        status or "issued",
                        sum(float(row["total_amount"] or 0) for row in client_orders),
                        invoice_notes,
                        client_orders[0]["cfdi_use"],
                        payment_form or None,
                        payment_method or None,
                        currency or "MXN",
                        None,
                    ),
                )
                invoice_id = int(cursor.lastrowid)
                next_invoice_id += 1
                for row in client_orders:
                    connection.execute(
                        "INSERT INTO invoice_order_links (invoice_id, order_id) VALUES (?, ?)",
                        (invoice_id, int(row["id"])),
                    )
                    linked_orders += 1
                created += 1
        return created, linked_orders, skipped

    def create_receipt_for_order(
        self,
        order_id: int,
        *,
        receipt_date: str,
        notes: str | None = None,
        payment_form: str | None = None,
        payment_method: str | None = None,
        currency: str = "MXN",
    ) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM orders WHERE id = ? AND COALESCE(is_preallocated, 0) = 0",
                (int(order_id),),
            ).fetchone()
            if row is None:
                raise ValueError("Order not found.")
            existing = connection.execute("SELECT id FROM receipts WHERE order_id = ?", (int(order_id),)).fetchone()
            if existing is not None:
                raise sqlite3.IntegrityError("A receipt already exists for this order.")
            cursor = connection.execute(
                """
                INSERT INTO receipts (
                    receipt_number,
                    order_id,
                    receipt_date,
                    total_amount,
                    notes,
                    payment_form,
                    payment_method,
                    currency
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.next_receipt_number(),
                    int(order_id),
                    receipt_date.strip(),
                    self.calculate_order_total(int(order_id)),
                    notes or None,
                    payment_form or None,
                    payment_method or None,
                    currency or "MXN",
                ),
            )
            return int(cursor.lastrowid)

    def get_client(self, client_id: int) -> ClientRecord | None:
        with self.connect() as connection:
            row = connection.execute("SELECT id, name, phone, email, tax_id, fiscal_regime, postal_code, cfdi_use, is_active FROM clients WHERE id = ?", (client_id,)).fetchone()
        return ClientRecord(**dict(row)) if row is not None else None

    def list_invoices(self) -> list[InvoiceRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT i.id,
                       i.invoice_number,
                       i.client_id,
                       c.name AS client_name,
                       i.order_id,
                       CASE
                           WHEN i.order_id IS NOT NULL THEN o.order_number
                           WHEN COUNT(iol.order_id) > 0 THEN CAST(COUNT(iol.order_id) AS TEXT) || ' orders'
                           ELSE NULL
                       END AS order_number,
                       i.invoice_date, i.status, i.total_amount, i.notes, i.cfdi_use, i.payment_form, i.payment_method, i.currency, i.xml_path
                FROM invoices i
                LEFT JOIN clients c ON c.id = i.client_id
                LEFT JOIN orders o ON o.id = i.order_id
                LEFT JOIN invoice_order_links iol ON iol.invoice_id = i.id
                GROUP BY i.id, i.invoice_number, i.client_id, c.name, i.order_id, o.order_number,
                         i.invoice_date, i.status, i.total_amount, i.notes, i.cfdi_use, i.payment_form, i.payment_method, i.currency, i.xml_path
                ORDER BY i.invoice_date DESC, i.id DESC
                """
            ).fetchall()
        return [InvoiceRecord(**dict(row)) for row in rows]

    def list_invoice_orders(self, invoice_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                WITH invoice_orders AS (
                    SELECT order_id
                    FROM invoices
                    WHERE id = ? AND order_id IS NOT NULL
                    UNION
                    SELECT order_id
                    FROM invoice_order_links
                    WHERE invoice_id = ?
                )
                SELECT o.id,
                       o.order_number,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       c.name AS client_name,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE
                               WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name
                               ELSE ''
                           END
                       ) AS patient_name,
                       COALESCE(
                           SUM(
                               CASE
                                   WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN COALESCE(t.price, 0)
                                   ELSE 0
                               END
                           ),
                           0
                       ) AS total_amount,
                       GROUP_CONCAT(
                           DISTINCT CASE
                               WHEN ot.source_label IS NOT NULL AND ot.source_label != '' THEN ot.source_label
                               ELSE NULL
                           END
                       ) AS panels
                FROM invoice_orders io
                INNER JOIN orders o ON o.id = io.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                GROUP BY o.id, o.order_number, order_date, c.name, patient_name
                ORDER BY DATE(COALESCE(o.ordered_at, o.created_at)), o.id
                """,
                (int(invoice_id), int(invoice_id)),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_invoice_order_panels(self, invoice_id: int) -> list[dict[str, Any]]:
        """One row per (order, panel) with that panel's subtotal."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                WITH invoice_orders AS (
                    SELECT order_id FROM invoices WHERE id = ? AND order_id IS NOT NULL
                    UNION
                    SELECT order_id FROM invoice_order_links WHERE invoice_id = ?
                )
                SELECT o.order_number,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != ''
                                THEN ' ' || p.middle_name ELSE '' END
                       ) AS patient_name,
                       ot.source_label AS panel,
                       COALESCE(
                           SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                                    THEN COALESCE(t.price, 0) ELSE 0 END),
                           0
                       ) AS panel_total
                FROM invoice_orders io
                INNER JOIN orders o ON o.id = io.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN order_tests ot ON ot.order_id = o.id
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE ot.source_label IS NOT NULL AND ot.source_label != ''
                  AND t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                GROUP BY o.id, o.order_number, order_date, patient_name, ot.source_label
                ORDER BY order_date, o.id, ot.source_label
                """,
                (int(invoice_id), int(invoice_id)),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_receipts(self) -> list[ReceiptRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT r.id,
                       r.receipt_number,
                       r.order_id,
                       o.order_number,
                       c.name AS client_name,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE
                               WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name
                               ELSE ''
                           END
                       ) AS patient_name,
                       r.receipt_date,
                       r.total_amount,
                       r.notes,
                       r.payment_form,
                       r.payment_method,
                       r.currency
                FROM receipts r
                INNER JOIN orders o ON o.id = r.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                ORDER BY r.receipt_date DESC, r.id DESC
                """
            ).fetchall()
        return [ReceiptRecord(**dict(row)) for row in rows]

    def create_invoice(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            resolved_total = payload.get("total_amount")
            order_id = payload.get("order_id")
            if order_id and (resolved_total is None or float(resolved_total) == 0):
                resolved_total = self.calculate_order_total(int(order_id))
            cursor = connection.execute(
                "INSERT INTO invoices (invoice_number, client_id, order_id, invoice_date, status, total_amount, notes, cfdi_use, payment_form, payment_method, currency, xml_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (payload.get("invoice_number") or self.next_invoice_number()).strip(),
                    payload.get("client_id"),
                    order_id,
                    payload["invoice_date"].strip(),
                    payload.get("status") or "issued",
                    resolved_total or 0,
                    payload.get("notes") or None,
                    payload.get("cfdi_use") or None,
                    payload.get("payment_form") or None,
                    payload.get("payment_method") or None,
                    payload.get("currency") or "MXN",
                    payload.get("xml_path") or None,
                ),
            )
            return int(cursor.lastrowid)

    def list_equipment(self) -> list[EquipmentRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, equipment_type, manufacturer, model, serial_number, location, status,
                       last_maintenance_date, next_maintenance_date, notes
                FROM equipment
                ORDER BY
                    CASE status
                        WHEN 'out_of_service' THEN 0
                        WHEN 'maintenance' THEN 1
                        WHEN 'active' THEN 2
                        ELSE 3
                    END,
                    name,
                    id
                """
            ).fetchall()
        return [EquipmentRecord(**dict(row)) for row in rows]

    def create_equipment(self, payload: dict[str, Any]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO equipment (
                    name, equipment_type, manufacturer, model, serial_number, location, status,
                    last_maintenance_date, next_maintenance_date, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["name"].strip(),
                    self._normalize_optional_text(payload.get("equipment_type")),
                    self._normalize_optional_text(payload.get("manufacturer")),
                    self._normalize_optional_text(payload.get("model")),
                    self._normalize_optional_text(payload.get("serial_number")),
                    self._normalize_optional_text(payload.get("location")),
                    payload.get("status") or "active",
                    self._normalize_optional_text(payload.get("last_maintenance_date")),
                    self._normalize_optional_text(payload.get("next_maintenance_date")),
                    self._normalize_optional_text(payload.get("notes")),
                ),
            )
            return int(cursor.lastrowid)

    def update_equipment(self, equipment_id: int, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE equipment
                SET name = ?,
                    equipment_type = ?,
                    manufacturer = ?,
                    model = ?,
                    serial_number = ?,
                    location = ?,
                    status = ?,
                    last_maintenance_date = ?,
                    next_maintenance_date = ?,
                    notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    payload["name"].strip(),
                    self._normalize_optional_text(payload.get("equipment_type")),
                    self._normalize_optional_text(payload.get("manufacturer")),
                    self._normalize_optional_text(payload.get("model")),
                    self._normalize_optional_text(payload.get("serial_number")),
                    self._normalize_optional_text(payload.get("location")),
                    payload.get("status") or "active",
                    self._normalize_optional_text(payload.get("last_maintenance_date")),
                    self._normalize_optional_text(payload.get("next_maintenance_date")),
                    self._normalize_optional_text(payload.get("notes")),
                    int(equipment_id),
                ),
            )

    def delete_equipment(self, equipment_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM equipment WHERE id = ?", (int(equipment_id),))

    def get_lab_settings(self) -> LabSettingsRecord:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT lab_name, address, phone, email, logo_path, header_image_path, footer_signature_image_path, report_footer, director_name, director_license, sat_rfc, sat_fiscal_regime, sat_postal_code, sat_certificate_path, sat_key_path, ui_language, report_flag_style, keep_panels_together, report_font_family, report_font_size, report_font_bold, report_abnormal_bold, report_subheading_font_family, report_subheading_font_size, report_subheading_font_bold, report_footer_gap_mm, ui_state, report_sex_format, report_date_format, report_show_doctor, report_show_client, report_show_sex, report_show_age, report_show_dob, report_show_ordered_at, report_show_reported_at FROM lab_settings WHERE id = 1"
            ).fetchone()
        return LabSettingsRecord(**dict(row))

    def save_lab_settings(self, payload: dict[str, str]) -> None:
        header_image_path = self._copy_asset(payload.get("header_image_path", ""), "header")
        footer_image_path = self._copy_asset(payload.get("footer_signature_image_path", ""), "footer_signature")
        logo_path = self._copy_asset(payload.get("logo_path", ""), "logo")
        with self.connect() as connection:
            connection.execute(
                "UPDATE lab_settings SET lab_name = ?, address = ?, phone = ?, email = ?, logo_path = ?, header_image_path = ?, footer_signature_image_path = ?, report_footer = ?, director_name = ?, director_license = ?, sat_rfc = ?, sat_fiscal_regime = ?, sat_postal_code = ?, sat_certificate_path = ?, sat_key_path = ?, ui_language = ?, report_flag_style = ?, keep_panels_together = ?, report_font_family = ?, report_font_size = ?, report_font_bold = ?, report_abnormal_bold = ?, report_subheading_font_family = ?, report_subheading_font_size = ?, report_subheading_font_bold = ?, report_footer_gap_mm = ?, ui_state = ?, report_sex_format = ?, report_date_format = ?, report_show_doctor = ?, report_show_client = ?, report_show_sex = ?, report_show_age = ?, report_show_dob = ?, report_show_ordered_at = ?, report_show_reported_at = ?, report_doctor_col = ?, report_client_col = ?, report_sex_col = ?, report_age_col = ?, report_dob_col = ?, report_ordered_at_col = ?, report_reported_at_col = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (
                    payload.get("lab_name", "").strip(),
                    payload.get("address", "").strip(),
                    payload.get("phone", "").strip(),
                    payload.get("email", "").strip(),
                    logo_path,
                    header_image_path,
                    footer_image_path,
                    payload.get("report_footer", "").strip(),
                    payload.get("director_name", "").strip(),
                    payload.get("director_license", "").strip(),
                    payload.get("sat_rfc", "").strip(),
                    payload.get("sat_fiscal_regime", "").strip(),
                    payload.get("sat_postal_code", "").strip(),
                    payload.get("sat_certificate_path", "").strip(),
                    payload.get("sat_key_path", "").strip(),
                    payload.get("ui_language", "es").strip() or "es",
                    payload.get("report_flag_style", "arrows").strip() or "arrows",
                    1 if str(payload.get("keep_panels_together", "0")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    payload.get("report_font_family", "Segoe UI").strip() or "Segoe UI",
                    self._bounded_int(payload.get("report_font_size"), 8, 18, 12),
                    1 if str(payload.get("report_font_bold", "0")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_abnormal_bold", "0")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    payload.get("report_subheading_font_family", "Segoe UI").strip() or "Segoe UI",
                    self._bounded_int(payload.get("report_subheading_font_size"), 8, 18, 13),
                    1 if str(payload.get("report_subheading_font_bold", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    self._bounded_int(payload.get("report_footer_gap_mm"), 0, 60, 8),
                    payload.get("ui_state", self.get_ui_state_json()),
                    payload.get("report_sex_format", "short").strip() or "short",
                    payload.get("report_date_format", "auto").strip() or "auto",
                    1 if str(payload.get("report_show_doctor", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_client", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_sex", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_age", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_dob", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_ordered_at", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    1 if str(payload.get("report_show_reported_at", "1")).strip() in {"1", "true", "True", "yes", "on"} else 0,
                    payload.get("report_doctor_col", "left").strip() or "left",
                    payload.get("report_client_col", "left").strip() or "left",
                    payload.get("report_sex_col", "left").strip() or "left",
                    payload.get("report_age_col", "right").strip() or "right",
                    payload.get("report_dob_col", "right").strip() or "right",
                    payload.get("report_ordered_at_col", "right").strip() or "right",
                    payload.get("report_reported_at_col", "right").strip() or "right",
                ),
            )

    def get_report_layout_settings(self) -> dict[str, Any]:
        settings = self.get_lab_settings()
        return {
            "flag_display_mode": settings.report_flag_style,
            "keep_panels_together": bool(settings.keep_panels_together),
            "report_font_family": settings.report_font_family,
            "report_font_size": settings.report_font_size,
            "report_font_bold": bool(settings.report_font_bold),
            "report_abnormal_bold": bool(settings.report_abnormal_bold),
            "report_subheading_font_family": settings.report_subheading_font_family,
            "report_subheading_font_size": settings.report_subheading_font_size,
            "report_subheading_font_bold": bool(settings.report_subheading_font_bold),
            "report_footer_gap_mm": settings.report_footer_gap_mm,
            "report_sex_format": settings.report_sex_format,
            "report_date_format": settings.report_date_format,
            "report_show_doctor": bool(settings.report_show_doctor),
            "report_show_client": bool(settings.report_show_client),
            "report_show_sex": bool(settings.report_show_sex),
            "report_show_age": bool(settings.report_show_age),
            "report_show_dob": bool(settings.report_show_dob),
            "report_show_ordered_at": bool(settings.report_show_ordered_at),
            "report_show_reported_at": bool(settings.report_show_reported_at),
            "report_doctor_col": settings.report_doctor_col,
            "report_client_col": settings.report_client_col,
            "report_sex_col": settings.report_sex_col,
            "report_age_col": settings.report_age_col,
            "report_dob_col": settings.report_dob_col,
            "report_ordered_at_col": settings.report_ordered_at_col,
            "report_reported_at_col": settings.report_reported_at_col,
        }

    def get_ui_state(self) -> dict[str, Any]:
        settings = self.get_lab_settings()
        try:
            data = json.loads(settings.ui_state or '{}')
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def get_ui_state_json(self) -> str:
        return json.dumps(self.get_ui_state(), ensure_ascii=False)

    def save_ui_state(self, ui_state: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE lab_settings SET ui_state = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (json.dumps(ui_state, ensure_ascii=False),),
            )

    def get_whatsapp_country_code(self) -> str:
        ui_state = self.get_ui_state()
        return clean_country_code(str(ui_state.get("whatsapp_country_code") or DEFAULT_COUNTRY_CODE))

    def save_whatsapp_country_code(self, country_code: str) -> None:
        ui_state = self.get_ui_state()
        ui_state["whatsapp_country_code"] = clean_country_code(country_code)
        self.save_ui_state(ui_state)

    def get_report_branding_options(self) -> dict[str, Any]:
        settings = self.get_lab_settings()
        ui_state = self.get_ui_state()
        stored = ui_state.get("report_branding")
        if not isinstance(stored, dict):
            stored = {}
        headers = self._normalize_report_branding_paths(stored.get("headers"), settings.header_image_path)
        footers = self._normalize_report_branding_paths(stored.get("footers"), settings.footer_signature_image_path)
        selected_header = str(stored.get("selected_header") or settings.header_image_path or (headers[0] if headers else ""))
        selected_footer = str(stored.get("selected_footer") or settings.footer_signature_image_path or (footers[0] if footers else ""))
        if selected_header and selected_header not in headers:
            headers.insert(0, selected_header)
        if selected_footer and selected_footer not in footers:
            footers.insert(0, selected_footer)
        return {
            "headers": headers,
            "footers": footers,
            "selected_header": selected_header,
            "selected_footer": selected_footer,
        }

    def save_report_branding_options(
        self,
        header_paths: list[str],
        footer_paths: list[str],
        selected_header: str,
        selected_footer: str,
    ) -> None:
        branding = {
            "headers": self._normalize_report_branding_paths(header_paths),
            "footers": self._normalize_report_branding_paths(footer_paths),
            "selected_header": selected_header.strip(),
            "selected_footer": selected_footer.strip(),
        }
        ui_state = self.get_ui_state()
        ui_state["report_branding"] = branding
        self.save_ui_state(ui_state)

    def add_report_branding_asset(self, raw_path: str, kind: str) -> str:
        copied_path = self._copy_report_branding_asset(raw_path, kind)
        if not copied_path:
            return ""
        branding = self.get_report_branding_options()
        key = "headers" if kind == "header" else "footers"
        selected_key = "selected_header" if kind == "header" else "selected_footer"
        paths = list(branding[key])
        if copied_path not in paths:
            paths.append(copied_path)
        branding[key] = paths
        branding[selected_key] = copied_path
        self.save_report_branding_options(
            branding["headers"],
            branding["footers"],
            branding["selected_header"],
            branding["selected_footer"],
        )
        return copied_path
    def get_label_print_preferences(self, client_id: int | None = None) -> dict[str, str]:
        ui_state = self.get_ui_state()
        stored = ui_state.get("label_print_defaults")
        if not isinstance(stored, dict):
            stored = {}
        default_prefs = stored.get("default")
        if not isinstance(default_prefs, dict):
            default_prefs = {}
        preferences = {
            "template": str(default_prefs.get("template") or "general"),
            "payload": str(default_prefs.get("payload") or "order_only"),
            "size": str(default_prefs.get("size") or "small_tall"),
            "grouping": str(default_prefs.get("grouping") or "per_test"),
            "code_type": str(default_prefs.get("code_type") or "barcode_name"),
            "copies": str(default_prefs.get("copies") or "1"),
            "show_barcode": "1" if default_prefs.get("show_barcode", True) else "0",
            "show_patient_name": "1" if default_prefs.get("show_patient_name", str(default_prefs.get("code_type") or "barcode_name") == "barcode_name") else "0",
            "show_order_number_text": "1" if bool(default_prefs.get("show_order_number_text")) else "0",
            "show_datetime": "1" if bool(default_prefs.get("show_datetime")) else "0",
            "printer": str(default_prefs.get("printer") or "niimbot:B1"),
        }
        if client_id is not None:
            client_map = stored.get("clients")
            if isinstance(client_map, dict):
                client_prefs = client_map.get(str(client_id))
                if isinstance(client_prefs, dict):
                    if client_prefs.get("template"):
                        preferences["template"] = str(client_prefs["template"])
                    if client_prefs.get("payload"):
                        preferences["payload"] = str(client_prefs["payload"])
        return preferences

    def get_order_panel_codes(self, order_id: int) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT COALESCE(ot.source_label, '') AS panel_code
                FROM order_tests ot
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE ot.order_id = ?
                  AND t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                  AND COALESCE(ot.source_label, '') != ''
                ORDER BY panel_code
                """,
                (order_id,),
            ).fetchall()
        return [str(row["panel_code"]) for row in rows]

    def get_panel_extra_copies(self) -> dict[str, int]:
        ui_state = self.get_ui_state()
        stored = ui_state.get("label_print_defaults")
        if not isinstance(stored, dict):
            return {}
        extras = stored.get("panel_extra_copies")
        if not isinstance(extras, dict):
            return {}
        result: dict[str, int] = {}
        for k, v in extras.items():
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if n > 0:
                result[str(k)] = n
        return result

    def save_panel_extra_copies(self, extra_copies: dict[str, int]) -> None:
        ui_state = self.get_ui_state()
        stored = ui_state.get("label_print_defaults")
        if not isinstance(stored, dict):
            stored = {}
        stored["panel_extra_copies"] = {k: v for k, v in extra_copies.items() if v > 0}
        ui_state["label_print_defaults"] = stored
        self.save_ui_state(ui_state)

    def save_label_print_preferences(
        self,
        template: str,
        payload: str,
        client_id: int | None = None,
        *,
        size: str | None = None,
        grouping: str | None = None,
        code_type: str | None = None,
        copies: str | None = None,
        show_barcode: bool | None = None,
        show_patient_name: bool | None = None,
        show_order_number_text: bool | None = None,
        show_datetime: bool | None = None,
        printer: str | None = None,
    ) -> None:
        ui_state = self.get_ui_state()
        stored = ui_state.get("label_print_defaults")
        if not isinstance(stored, dict):
            stored = {}
        if client_id is None:
            default_prefs = stored.get("default")
            if not isinstance(default_prefs, dict):
                default_prefs = {}
            default_prefs["template"] = template
            default_prefs["payload"] = payload
            if size is not None:
                default_prefs["size"] = size
            if grouping is not None:
                default_prefs["grouping"] = grouping
            if code_type is not None:
                default_prefs["code_type"] = code_type
            if copies is not None:
                default_prefs["copies"] = copies
            if show_barcode is not None:
                default_prefs["show_barcode"] = bool(show_barcode)
            if show_patient_name is not None:
                default_prefs["show_patient_name"] = bool(show_patient_name)
            if show_order_number_text is not None:
                default_prefs["show_order_number_text"] = bool(show_order_number_text)
            if show_datetime is not None:
                default_prefs["show_datetime"] = bool(show_datetime)
            if printer is not None:
                default_prefs["printer"] = printer
            stored["default"] = default_prefs
        else:
            client_map = stored.get("clients")
            if not isinstance(client_map, dict):
                client_map = {}
            client_map[str(client_id)] = {"template": template, "payload": payload}
            stored["clients"] = client_map
        ui_state["label_print_defaults"] = stored
        self.save_ui_state(ui_state)

    def get_receipt_print_preferences(self) -> dict[str, str]:
        ui_state = self.get_ui_state()
        stored = ui_state.get("receipt_print_defaults")
        if not isinstance(stored, dict):
            stored = {}
        return {
            "auto_print": str(stored.get("auto_print") or "0"),
            "paper_format": str(stored.get("paper_format") or "letter"),
            "printer": str(stored.get("printer") or "system_default"),
        }

    def save_receipt_print_preferences(self, *, auto_print: bool, paper_format: str, printer: str = "system_default") -> None:
        ui_state = self.get_ui_state()
        ui_state["receipt_print_defaults"] = {
            "auto_print": "1" if auto_print else "0",
            "paper_format": paper_format,
            "printer": printer,
        }
        self.save_ui_state(ui_state)

    def list_tests(self, *, status_filter: str = "active") -> list[TestRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT t.id, t.code, t.name, tc.name AS category_name, t.specimen_type, t.method, t.result_kind, t.select_options, t.default_result_value, t.price, t.is_active, COUNT(trr.id) AS range_count, t.result_multiplier FROM tests t LEFT JOIN test_categories tc ON tc.id = t.category_id LEFT JOIN test_reference_ranges trr ON trr.test_id = t.id WHERE (? = 'all' OR (? = 'active' AND t.is_active = 1) OR (? = 'archived' AND t.is_active = 0)) GROUP BY t.id, t.code, t.name, tc.name, t.specimen_type, t.method, t.result_kind, t.select_options, t.default_result_value, t.price, t.is_active, t.result_multiplier ORDER BY t.is_active DESC, tc.name IS NULL, tc.name, t.name",
                (status_filter, status_filter, status_filter),
            ).fetchall()
        return [TestRecord(**dict(row)) for row in rows]

    def list_test_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id, code, name FROM tests WHERE is_active = 1 ORDER BY name").fetchall()
        return [(row["id"], f'{row["name"]} ({row["code"]})') for row in rows]

    def list_client_test_price_overrides(self) -> dict[tuple[int, int], float]:
        with self.connect() as connection:
            rows = connection.execute("SELECT client_id, test_id, price FROM client_test_prices").fetchall()
        return {(int(row["client_id"]), int(row["test_id"])): float(row["price"]) for row in rows}

    def apply_client_test_price_overrides(self, entries: dict[tuple[int, int], float | None]) -> tuple[int, int]:
        updated_count = 0
        cleared_count = 0
        with self.connect() as connection:
            for (client_id, test_id), price in entries.items():
                if price is None:
                    cursor = connection.execute(
                        "DELETE FROM client_test_prices WHERE client_id = ? AND test_id = ?",
                        (client_id, test_id),
                    )
                    cleared_count += int(cursor.rowcount or 0)
                    continue
                connection.execute(
                    """
                    INSERT INTO client_test_prices (client_id, test_id, price, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(client_id, test_id)
                    DO UPDATE SET price = excluded.price, updated_at = CURRENT_TIMESTAMP
                    """,
                    (client_id, test_id, float(price)),
                )
                updated_count += 1
        return updated_count, cleared_count

    def get_test_detail(self, test_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT t.id, t.code, t.name, tc.name AS category_name, t.specimen_type, t.method, t.result_kind, t.select_options, t.default_result_value, t.price, t.result_multiplier, t.is_active FROM tests t LEFT JOIN test_categories tc ON tc.id = t.category_id WHERE t.id = ?",
                (test_id,),
            ).fetchone()
            if row is None:
                return None
            ranges = connection.execute(
                "SELECT sex, age_min_days, age_max_days, COALESCE(lower_value_text, CAST(lower_value AS TEXT)) AS lower_value, COALESCE(upper_value_text, CAST(upper_value AS TEXT)) AS upper_value, unit, reference_text FROM test_reference_ranges WHERE test_id = ? ORDER BY id",
                (test_id,),
            ).fetchall()
        return {
            **dict(row),
            "reference_ranges": [dict(range_row) for range_row in ranges],
        }

    def get_test_id_by_code(self, code: str) -> int | None:
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM tests WHERE code = ?", (code.strip(),)).fetchone()
        return int(row["id"]) if row is not None else None

    def create_test(self, payload: dict[str, Any], reference_ranges: list[dict[str, Any]]) -> None:
        with self.connect() as connection:
            category_id = self._get_or_create_category(connection, payload.get("category_name", ""))
            cursor = connection.execute(
                "INSERT INTO tests (code, name, category_id, specimen_type, method, result_kind, select_options, default_result_value, price, result_multiplier) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    payload["code"].strip(),
                    payload["name"].strip(),
                    category_id,
                    payload.get("specimen_type") or None,
                    payload.get("method") or None,
                    payload["result_kind"],
                    self._serialize_select_options(payload.get("select_options")),
                    self._normalize_optional_text(payload.get("default_result_value")),
                    float(payload.get("price") or 0),
                    float(payload["result_multiplier"]) if payload.get("result_multiplier") else None,
                ),
            )
            test_id = int(cursor.lastrowid)
            self._save_test_reference_ranges(connection, test_id, reference_ranges)

    def update_test(self, test_id: int, payload: dict[str, Any], reference_ranges: list[dict[str, Any]]) -> None:
        with self.connect() as connection:
            category_id = self._get_or_create_category(connection, payload.get("category_name", ""))
            connection.execute(
                "UPDATE tests SET code = ?, name = ?, category_id = ?, specimen_type = ?, method = ?, result_kind = ?, select_options = ?, default_result_value = ?, result_multiplier = ? WHERE id = ?",
                (
                    payload["code"].strip(),
                    payload["name"].strip(),
                    category_id,
                    payload.get("specimen_type") or None,
                    payload.get("method") or None,
                    payload["result_kind"],
                    self._serialize_select_options(payload.get("select_options")),
                    self._normalize_optional_text(payload.get("default_result_value")),
                    float(payload["result_multiplier"]) if payload.get("result_multiplier") else None,
                    test_id,
                ),
            )
            connection.execute("DELETE FROM test_reference_ranges WHERE test_id = ?", (test_id,))
            self._save_test_reference_ranges(connection, test_id, reference_ranges)

    def archive_test(self, test_id: int) -> None:
        with self.connect() as connection:
            test_row = connection.execute("SELECT code FROM tests WHERE id = ?", (test_id,)).fetchone()
            if test_row is None:
                return
            if str(test_row["code"]).startswith("__PANEL_"):
                raise ValueError("This system test cannot be archived.")
            connection.execute("UPDATE tests SET is_active = 0 WHERE id = ?", (test_id,))

    def unarchive_test(self, test_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE tests SET is_active = 1 WHERE id = ?", (test_id,))

    def list_panels(self, *, status_filter: str = "active") -> list[PanelRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT tp.id, tp.code, tp.name, tp.specimen_type, tp.method, tp.is_active, GROUP_CONCAT(CASE WHEN tpi.item_type = 'test' THEN t.name ELSE tpi.heading_text END, ', ') AS test_names FROM test_panels tp LEFT JOIN test_panel_items tpi ON tpi.panel_id = tp.id LEFT JOIN tests t ON t.id = tpi.test_id AND tpi.item_type = 'test' WHERE (? = 'all' OR (? = 'active' AND tp.is_active = 1) OR (? = 'archived' AND tp.is_active = 0)) GROUP BY tp.id, tp.code, tp.name, tp.specimen_type, tp.method, tp.is_active ORDER BY tp.is_active DESC, tp.name", (status_filter, status_filter, status_filter)).fetchall()
        return [PanelRecord(**dict(row)) for row in rows]

    def list_panel_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT tp.id, tp.code, tp.name, SUM(CASE WHEN tpi.item_type = 'test' THEN 1 ELSE 0 END) AS item_count FROM test_panels tp LEFT JOIN test_panel_items tpi ON tpi.panel_id = tp.id WHERE tp.is_active = 1 GROUP BY tp.id, tp.code, tp.name ORDER BY tp.name").fetchall()
        return [(row["id"], f'{row["code"]} - {row["name"]}') for row in rows]

    def get_panel_tests(self, panel_id: int) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT t.id, t.name, t.code FROM test_panel_items tpi INNER JOIN tests t ON t.id = tpi.test_id WHERE tpi.panel_id = ? AND tpi.item_type = 'test' ORDER BY tpi.sort_order, t.name", (panel_id,)).fetchall()
        return [(row["id"], f'{row["name"]} ({row["code"]})') for row in rows]

    def get_panel_order_items(self, panel_id: int) -> list[PanelItemRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT tpi.item_type, tpi.test_id, tpi.heading_text, tpi.sort_order, CASE WHEN tpi.item_type = 'test' THEN t.name || ' (' || t.code || ')' ELSE tpi.heading_text END AS label FROM test_panel_items tpi LEFT JOIN tests t ON t.id = tpi.test_id WHERE tpi.panel_id = ? ORDER BY tpi.sort_order, tpi.id", (panel_id,)).fetchall()
        return [PanelItemRecord(**dict(row)) for row in rows]

    def get_panel_detail(self, panel_id: int, *, include_inactive: bool = False) -> dict[str, Any] | None:
        with self.connect() as connection:
            if include_inactive:
                row = connection.execute("SELECT id, code, name, specimen_type, method, is_active FROM test_panels WHERE id = ?", (panel_id,)).fetchone()
            else:
                row = connection.execute("SELECT id, code, name, specimen_type, method, is_active FROM test_panels WHERE id = ? AND is_active = 1", (panel_id,)).fetchone()
            if row is None:
                return None
            item_rows = connection.execute("SELECT tpi.item_type, tpi.test_id, t.code AS test_code, tpi.heading_text, tpi.sort_order, CASE WHEN tpi.item_type = 'test' THEN t.name || ' (' || t.code || ')' ELSE tpi.heading_text END AS label FROM test_panel_items tpi LEFT JOIN tests t ON t.id = tpi.test_id WHERE tpi.panel_id = ? ORDER BY tpi.sort_order, tpi.id", (panel_id,)).fetchall()
        return {
            **dict(row),
            "items": [dict(item_row) for item_row in item_rows],
        }

    def get_panel_id_by_code(self, code: str) -> int | None:
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM test_panels WHERE code = ? AND is_active = 1", (code.strip(),)).fetchone()
        return int(row["id"]) if row is not None else None

    def get_panel_report_metadata_by_name(self) -> dict[str, dict[str, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT name, specimen_type, method FROM test_panels WHERE is_active = 1").fetchall()
        return {
            str(row["name"] or "").strip(): {
                "specimen_type": str(row["specimen_type"] or "").strip(),
                "method": str(row["method"] or "").strip(),
            }
            for row in rows
            if str(row["name"] or "").strip()
        }

    def create_panel(self, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str = "", method: str = "") -> None:
        with self.connect() as connection:
            cursor = connection.execute("INSERT INTO test_panels (code, name, specimen_type, method, is_active) VALUES (?, ?, ?, ?, 1)", (code.strip(), name.strip(), specimen_type.strip() or None, method.strip() or None))
            panel_id = int(cursor.lastrowid)
            self._save_panel_items(connection, panel_id, panel_items)

    def update_panel(self, panel_id: int, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str = "", method: str = "") -> None:
        with self.connect() as connection:
            connection.execute("UPDATE test_panels SET code = ?, name = ?, specimen_type = ?, method = ?, is_active = 1 WHERE id = ?", (code.strip(), name.strip(), specimen_type.strip() or None, method.strip() or None, panel_id))
            connection.execute("DELETE FROM test_panel_items WHERE panel_id = ?", (panel_id,))
            self._save_panel_items(connection, panel_id, panel_items)

    def archive_panel(self, panel_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE test_panels SET is_active = 0 WHERE id = ?", (panel_id,))

    def unarchive_panel(self, panel_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE test_panels SET is_active = 1 WHERE id = ?", (panel_id,))

    def next_order_number(self) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM orders ORDER BY id DESC LIMIT 1").fetchone()
        next_id = (int(row["id"]) + 1) if row is not None else 1
        return f"{next_id:06d}"

    def _normalize_order_items(self, order_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique_items: list[dict[str, Any]] = []
        seen_test_ids: set[int] = set()
        for item in order_items:
            is_outsourced = 1 if item.get("is_outsourced") else 0
            if item.get("item_type") in {"heading", "comment"}:
                unique_items.append(
                    {
                        "item_type": item.get("item_type"),
                        "label": (item.get("label") or "").strip(),
                        "source": item.get("source") or "",
                        "is_outsourced": is_outsourced,
                    }
                )
                continue
            test_id = item.get("test_id")
            if test_id is None or test_id in seen_test_ids:
                continue
            seen_test_ids.add(test_id)
            unique_items.append(
                {
                    "item_type": "test",
                    "test_id": int(test_id),
                    "label": item.get("label"),
                    "source": item.get("source") or "",
                    "is_outsourced": is_outsourced,
                }
            )
        return unique_items

    def _save_order_items(self, connection: sqlite3.Connection, order_id: int, order_items: list[dict[str, Any]]) -> None:
        heading_test_id = self._ensure_panel_heading_test(connection)
        comment_test_id = self._ensure_panel_comment_test(connection)
        for index, item in enumerate(order_items):
            outsourced_value = 1 if item.get("is_outsourced") else 0
            source_label = str(item.get("source") or "").strip() or None
            if item["item_type"] == "heading":
                connection.execute(
                    "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                    (order_id, heading_test_id, outsourced_value, source_label, item["label"], index),
                )
                continue
            if item["item_type"] == "comment":
                connection.execute(
                    "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                    (order_id, comment_test_id, outsourced_value, source_label, item["label"], index),
                )
                continue
            test_id = item["test_id"]
            test_row = connection.execute("SELECT name FROM tests WHERE id = ?", (test_id,)).fetchone()
            display_name = test_row["name"] if test_row else None
            connection.execute(
                "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                (order_id, test_id, outsourced_value, source_label, display_name, index),
            )

    def create_order(self, order_number: str | None, accession_id: str | None, sample_id: str | None, patient_id: int, doctor_id: int | None, client_id: int | None, order_items: list[dict[str, Any]], status: str, notes: str) -> int:
        unique_items = self._normalize_order_items(order_items)
        with self.connect() as connection:
            resolved_order_number = (order_number or "").strip() or self.next_order_number()
            cursor = connection.execute(
                "INSERT INTO orders (order_number, accession_id, sample_id, patient_id, doctor_id, client_id, status, is_preallocated, ordered_at, notes) VALUES (?, ?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP, ?)",
                (resolved_order_number, (accession_id or '').strip() or None, (sample_id or '').strip() or None, patient_id, doctor_id, client_id, status, notes.strip() or None),
            )
            order_id = int(cursor.lastrowid)
            self._save_order_items(connection, order_id, unique_items)
        return order_id

    def create_preallocated_order_batch(self, count: int, client_id: int | None = None, batch_prefix: str | None = None) -> list[dict[str, Any]]:
        labels: list[dict[str, Any]] = []
        normalized_prefix = (batch_prefix or '').strip().upper()
        with self.connect() as connection:
            placeholder_patient_id = self._get_or_create_preallocated_patient(connection)
            row = connection.execute("SELECT id FROM orders ORDER BY id DESC LIMIT 1").fetchone()
            next_id = (int(row["id"]) + 1) if row is not None else 1
            for offset in range(count):
                order_number = f"{normalized_prefix}{next_id + offset:06d}"
                cursor = connection.execute(
                    "INSERT INTO orders (order_number, accession_id, sample_id, patient_id, doctor_id, client_id, status, is_preallocated, ordered_at, notes) VALUES (?, NULL, NULL, ?, NULL, ?, 'draft', 1, CURRENT_TIMESTAMP, ?)",
                    (order_number, placeholder_patient_id, client_id, 'Preprinted barcode batch'),
                )
                order_id = int(cursor.lastrowid)
                created_row = connection.execute("SELECT created_at FROM orders WHERE id = ?", (order_id,)).fetchone()
                labels.append({
                    'order_id': order_id,
                    'order_number': order_number,
                    'accession_id': '',
                    'sample_id': '',
                    'client_id': client_id,
                    'patient_name': '',
                    'test_name': '',
                    'specimen_type': '',
                    'specimen_code': 'SPC',
                    'test_code': '',
                    'group_label': '',
                    'created_at': created_row['created_at'] if created_row is not None else '',
                })
        return labels

    def find_order_by_number(self, order_number: str) -> OrderLookupRecord | None:
        normalized = order_number.strip()
        if not normalized:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, order_number, status, COALESCE(is_preallocated, 0) AS is_preallocated FROM orders WHERE order_number = ?",
                (normalized,),
            ).fetchone()
        return OrderLookupRecord(**dict(row)) if row is not None else None

    def get_order_edit_record(self, order_id: int) -> OrderEditRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, order_number, accession_id, sample_id, patient_id, doctor_id, client_id, status, notes, COALESCE(is_preallocated, 0) AS is_preallocated FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
            if row is None:
                return None
            item_rows = connection.execute(
                "SELECT ot.test_id, ot.display_name, ot.source_label, ot.sort_order, COALESCE(ot.is_outsourced, 0) AS is_outsourced, t.code AS test_code FROM order_tests ot INNER JOIN tests t ON t.id = ot.test_id WHERE ot.order_id = ? ORDER BY ot.sort_order, ot.id",
                (order_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for item_row in item_rows:
            code = item_row['test_code']
            label = item_row['display_name'] or ''
            is_outsourced = int(item_row['is_outsourced'] or 0)
            source_label = str(item_row['source_label'] or '')
            if code == '__PANEL_HEADING__':
                items.append({'item_type': 'heading', 'label': label, 'source': source_label, 'is_outsourced': is_outsourced})
            elif code == '__PANEL_COMMENT__':
                items.append({'item_type': 'comment', 'label': label, 'source': source_label, 'is_outsourced': is_outsourced})
            else:
                items.append({'item_type': 'test', 'test_id': int(item_row['test_id']), 'label': label, 'source': source_label, 'is_outsourced': is_outsourced})
        payload = dict(row)
        payload['items'] = items
        return OrderEditRecord(**payload)

    def assign_preallocated_order(self, order_id: int, accession_id: str | None, sample_id: str | None, patient_id: int, doctor_id: int | None, client_id: int | None, order_items: list[dict[str, Any]], status: str, notes: str) -> None:
        unique_items = self._normalize_order_items(order_items)
        with self.connect() as connection:
            row = connection.execute("SELECT COALESCE(is_preallocated, 0) AS is_preallocated FROM orders WHERE id = ?", (order_id,)).fetchone()
            if row is None:
                raise sqlite3.IntegrityError('Order not found.')
            if int(row['is_preallocated']) != 1:
                raise sqlite3.IntegrityError('Only preallocated barcode orders can be assigned from this workflow.')
            connection.execute(
                "UPDATE orders SET accession_id = ?, sample_id = ?, patient_id = ?, doctor_id = ?, client_id = ?, status = ?, is_preallocated = 0, notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ((accession_id or '').strip() or None, (sample_id or '').strip() or None, patient_id, doctor_id, client_id, status, notes.strip() or None, order_id),
            )
            connection.execute("DELETE FROM order_tests WHERE order_id = ?", (order_id,))
            self._save_order_items(connection, order_id, unique_items)

    def update_order(self, order_id: int, accession_id: str | None, sample_id: str | None, patient_id: int, doctor_id: int | None, client_id: int | None, order_items: list[dict[str, Any]], status: str, notes: str) -> None:
        unique_items = self._normalize_order_items(order_items)
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM orders WHERE id = ?", (order_id,)).fetchone()
            if row is None:
                raise sqlite3.IntegrityError('Order not found.')
            connection.execute(
                "UPDATE orders SET accession_id = ?, sample_id = ?, patient_id = ?, doctor_id = ?, client_id = ?, status = ?, notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ((accession_id or '').strip() or None, (sample_id or '').strip() or None, patient_id, doctor_id, client_id, status, notes.strip() or None, order_id),
            )
            heading_test_id = self._ensure_panel_heading_test(connection)
            comment_test_id = self._ensure_panel_comment_test(connection)
            structural_ids = (heading_test_id, comment_test_id)
            # New set of real test IDs
            new_test_ids = {
                item["test_id"] for item in unique_items if item.get("item_type") == "test"
            }
            # Existing real-test rows — preserve results for tests still in the list
            existing_rows = connection.execute(
                "SELECT id, test_id FROM order_tests WHERE order_id = ? AND test_id NOT IN (?, ?)",
                (order_id, heading_test_id, comment_test_id),
            ).fetchall()
            existing_map: dict[int, int] = {}
            for r in existing_rows:
                tid = int(r["test_id"])
                ot_id = int(r["id"])
                if tid not in new_test_ids:
                    # Test removed — safe to delete its results
                    connection.execute("DELETE FROM results WHERE order_test_id = ?", (ot_id,))
                    connection.execute("DELETE FROM order_tests WHERE id = ?", (ot_id,))
                else:
                    existing_map[tid] = ot_id
            # Headings and comments carry no results — delete and re-insert freely
            connection.execute(
                "DELETE FROM order_tests WHERE order_id = ? AND test_id IN (?, ?)",
                (order_id, heading_test_id, comment_test_id),
            )
            # Reconcile each item in the new list
            for index, item in enumerate(unique_items):
                outsourced = 1 if item.get("is_outsourced") else 0
                source = str(item.get("source") or "").strip() or None
                if item["item_type"] == "heading":
                    connection.execute(
                        "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                        (order_id, heading_test_id, outsourced, source, item["label"], index),
                    )
                elif item["item_type"] == "comment":
                    connection.execute(
                        "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                        (order_id, comment_test_id, outsourced, source, item["label"], index),
                    )
                else:
                    test_id = int(item["test_id"])
                    if test_id in existing_map:
                        # Already exists — just refresh sort order and outsourced flag
                        connection.execute(
                            "UPDATE order_tests SET sort_order = ?, is_outsourced = ?, source_label = ? WHERE id = ?",
                            (index, outsourced, source, existing_map[test_id]),
                        )
                    else:
                        # Genuinely new test
                        test_row = connection.execute("SELECT name FROM tests WHERE id = ?", (test_id,)).fetchone()
                        display_name = test_row["name"] if test_row else None
                        connection.execute(
                            "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
                            (order_id, test_id, outsourced, source, display_name, index),
                        )

    def list_recent_orders(self) -> list[OrderSummaryRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT o.id, o.order_number, TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name, d.full_name AS doctor_name, o.status, o.created_at, SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1 ELSE 0 END) AS item_count, CASE WHEN COUNT(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') AND COALESCE(ot.is_outsourced, 0) = 0 THEN 1 END) > 0 AND COUNT(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') AND COALESCE(ot.is_outsourced, 0) = 0 THEN 1 END) = COUNT(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') AND COALESCE(ot.is_outsourced, 0) = 0 AND COALESCE(NULLIF(TRIM(r.result_value), ''), NULLIF(TRIM(t.default_result_value), '')) IS NOT NULL THEN 1 END) THEN 1 ELSE 0 END AS all_results_entered FROM orders o INNER JOIN patients p ON p.id = o.patient_id LEFT JOIN doctors d ON d.id = o.doctor_id LEFT JOIN order_tests ot ON ot.order_id = o.id LEFT JOIN tests t ON t.id = ot.test_id LEFT JOIN results r ON r.order_test_id = ot.id WHERE COALESCE(o.is_preallocated, 0) = 0 GROUP BY o.id, o.order_number, patient_name, d.full_name, o.status, o.created_at ORDER BY o.created_at DESC, o.id DESC LIMIT 25").fetchall()
        return [OrderSummaryRecord(**dict(row)) for row in rows]

    def search_orders(self, search_text: str = "") -> list[OrderBrowserRecord]:
        normalized = search_text.strip().lower()
        like_value = f"%{normalized}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,
                       o.order_number,
                       COALESCE(o.ordered_at, o.created_at) AS order_date,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END
                       ) AS patient_name,
                       c.name AS client_name,
                       d.full_name AS doctor_name,
                       o.status,
                       SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1 ELSE 0 END) AS item_count
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN doctors d ON d.id = o.doctor_id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                WHERE COALESCE(o.is_preallocated, 0) = 0
                  AND (
                      ? = '' OR
                      LOWER(COALESCE(o.order_number, '')) LIKE ? OR
                      LOWER(TRIM(
                          p.first_name || ' ' || p.last_name ||
                          CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END
                      )) LIKE ? OR
                      LOWER(COALESCE(c.name, '')) LIKE ?
                  )
                GROUP BY o.id, o.order_number, order_date, patient_name, c.name, d.full_name, o.status
                ORDER BY COALESCE(o.ordered_at, o.created_at) DESC, o.id DESC
                LIMIT 250
                """,
                (normalized, like_value, like_value, like_value),
            ).fetchall()
        return [OrderBrowserRecord(**dict(row)) for row in rows]

    def list_results_workflow_orders(self) -> list[ResultWorkflowRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,
                       o.order_number,
                       COALESCE(o.ordered_at, o.created_at) AS order_date,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END
                       ) AS patient_name,
                       p.phone AS patient_phone,
                       d.full_name AS doctor_name,
                       c.name AS client_name,
                       c.phone AS client_phone,
                       r.report_version,
                       r.finalized_at AS report_finalized_at,
                       CASE WHEN r.finalized_at IS NOT NULL AND (
                           p.updated_at > r.finalized_at OR o.updated_at > r.finalized_at
                       ) THEN 1 ELSE 0 END AS report_outdated,
                       COUNT(CASE
                           WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                                AND COALESCE(ot.is_outsourced, 0) = 0
                           THEN 1
                       END) AS result_count,
                       COUNT(CASE
                           WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                                AND COALESCE(ot.is_outsourced, 0) = 0
                                AND COALESCE(NULLIF(TRIM(rst.result_value), ''), NULLIF(TRIM(t.default_result_value), '')) IS NOT NULL
                           THEN 1
                       END) AS completed_result_count
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN doctors d ON d.id = o.doctor_id
                LEFT JOIN clients c ON c.id = o.client_id
                LEFT JOIN reports r ON r.order_id = o.id
                LEFT JOIN order_tests ot ON ot.order_id = o.id
                LEFT JOIN tests t ON t.id = ot.test_id
                LEFT JOIN results rst ON rst.order_test_id = ot.id
                WHERE COALESCE(o.is_preallocated, 0) = 0
                GROUP BY o.id, o.order_number, order_date, patient_name, p.phone, d.full_name, c.name, c.phone, r.report_version, r.finalized_at, p.updated_at, o.updated_at
                ORDER BY COALESCE(o.ordered_at, o.created_at) DESC, o.id DESC
                LIMIT 100
                """
            ).fetchall()
        return [ResultWorkflowRecord(**dict(row)) for row in rows]

    def list_outsourced_order_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT
                       o.id,
                       o.order_number,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END
                       ) AS patient_name
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN order_tests ot ON ot.order_id = o.id
                WHERE COALESCE(o.is_preallocated, 0) = 0
                  AND COALESCE(ot.is_outsourced, 0) = 1
                ORDER BY COALESCE(o.ordered_at, o.created_at) DESC, o.id DESC
                """
            ).fetchall()
        return [
            (int(row["id"]), f'{row["order_number"]} - {row["patient_name"]}')
            for row in rows
        ]

    def list_outsourced_panels_for_order(self, order_id: int) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT TRIM(COALESCE(ot.source_label, '')) AS panel_label
                FROM order_tests ot
                WHERE ot.order_id = ?
                  AND COALESCE(ot.is_outsourced, 0) = 1
                  AND TRIM(COALESCE(ot.source_label, '')) != ''
                ORDER BY panel_label
                """,
                (order_id,),
            ).fetchall()
        return [str(row["panel_label"]) for row in rows]

    def save_outsourced_panel_table(
        self,
        order_id: int,
        panel_label: str,
        source_pdf_path: str,
        rows: list[list[object]],
    ) -> None:
        normalized_label = panel_label.strip()
        normalized_source = source_pdf_path.strip()
        if not normalized_label:
            raise sqlite3.IntegrityError("An outsourced panel must be selected.")
        if not normalized_source:
            raise sqlite3.IntegrityError("A source PDF path is required.")
        normalized_rows = self._normalize_outsourced_table_rows(rows)
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT id
                FROM outsourced_panel_tables
                WHERE order_id = ? AND panel_label = ?
                """,
                (order_id, normalized_label),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO outsourced_panel_tables (
                        order_id, panel_label, source_pdf_path, updated_at
                    ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (order_id, normalized_label, normalized_source),
                )
                table_id = int(cursor.lastrowid)
            else:
                table_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE outsourced_panel_tables
                    SET source_pdf_path = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (normalized_source, table_id),
                )
                connection.execute(
                    "DELETE FROM outsourced_panel_rows WHERE outsourced_panel_table_id = ?",
                    (table_id,),
                )
            for row_index, row in enumerate(normalized_rows):
                connection.execute(
                    """
                    INSERT INTO outsourced_panel_rows (
                        outsourced_panel_table_id, row_index, col_1, col_2, col_3, col_4, col_5
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (table_id, row_index, row[0], row[1], row[2], row[3], row[4]),
                )

    def get_outsourced_panel_preview_sections(self, order_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT opt.panel_label,
                       opt.source_pdf_path,
                       opr.row_index,
                       opr.col_1,
                       opr.col_2,
                       opr.col_3,
                       opr.col_4,
                       opr.col_5
                FROM outsourced_panel_tables opt
                LEFT JOIN outsourced_panel_rows opr ON opr.outsourced_panel_table_id = opt.id
                WHERE opt.order_id = ?
                ORDER BY opt.panel_label, opr.row_index, opr.id
                """,
                (order_id,),
            ).fetchall()
        return self._group_outsourced_rows(rows)

    @staticmethod
    def _normalize_outsourced_table_rows(rows: list[list[object]]) -> list[list[str]]:
        normalized_rows: list[list[str]] = []
        for raw_row in rows:
            normalized = [str(value or "").strip() for value in list(raw_row)[:5]]
            while len(normalized) < 5:
                normalized.append("")
            if any(normalized):
                normalized_rows.append(normalized)
        return normalized_rows

    @staticmethod
    def _group_outsourced_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        grouped: list[dict[str, Any]] = []
        current_key: tuple[str, str] | None = None
        current_section: dict[str, Any] | None = None
        for row in rows:
            panel_label = str(row["panel_label"] or "").strip()
            source_pdf_path = str(row["source_pdf_path"] or "").strip()
            key = (panel_label, source_pdf_path)
            if current_key != key:
                current_key = key
                current_section = {
                    "panel_label": panel_label,
                    "source_pdf_path": source_pdf_path,
                    "rows": [],
                }
                grouped.append(current_section)
            if current_section is None:
                continue
            if row["row_index"] is None:
                continue
            current_section["rows"].append(
                {
                    "row_index": int(row["row_index"]),
                    "col_1": str(row["col_1"] or ""),
                    "col_2": str(row["col_2"] or ""),
                    "col_3": str(row["col_3"] or ""),
                    "col_4": str(row["col_4"] or ""),
                    "col_5": str(row["col_5"] or ""),
                }
            )
        return grouped

    def list_result_order_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT o.id, o.order_number, TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name, SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1 ELSE 0 END) AS item_count FROM orders o INNER JOIN patients p ON p.id = o.patient_id INNER JOIN order_tests ot ON ot.order_id = o.id INNER JOIN tests t ON t.id = ot.test_id WHERE o.status IN ('draft', 'in_progress') AND COALESCE(o.is_preallocated, 0) = 0 GROUP BY o.id, o.order_number, patient_name ORDER BY o.created_at DESC, o.id DESC").fetchall()
        return [(row["id"], f'{row["order_number"]} - {row["patient_name"]} ({row["item_count"]} tests)') for row in rows]

    def list_report_order_choices(self) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,
                       o.order_number,
                       o.status,
                       TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name,
                       SUM(CASE WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1 ELSE 0 END) AS item_count
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN order_tests ot ON ot.order_id = o.id
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE o.status IN ('draft', 'in_progress', 'finalized')
                  AND COALESCE(o.is_preallocated, 0) = 0
                GROUP BY o.id, o.order_number, o.status, patient_name
                ORDER BY o.created_at DESC, o.id DESC
                """
            ).fetchall()
        return [
            (
                row["id"],
                f'{row["order_number"]} - {row["patient_name"]} ({row["item_count"]} tests, {row["status"]})',
            )
            for row in rows
        ]

    def list_filtered_report_order_choices(
        self,
        *,
        client_id: int | None = None,
        test_id: int | None = None,
        date_from: str = "",
        date_to: str = "",
    ) -> list[tuple[int, str]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.id,
                       o.order_number,
                       o.status,
                       DATE(COALESCE(o.ordered_at, o.created_at)) AS order_date,
                       c.name AS client_name,
                       TRIM(
                           p.first_name || ' ' || p.last_name ||
                           CASE
                               WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name
                               ELSE ''
                           END
                       ) AS patient_name,
                       SUM(
                           CASE
                               WHEN t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__') THEN 1
                               ELSE 0
                           END
                       ) AS item_count
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                INNER JOIN order_tests ot ON ot.order_id = o.id
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE o.status IN ('draft', 'in_progress', 'finalized')
                  AND COALESCE(o.is_preallocated, 0) = 0
                  AND (? IS NULL OR o.client_id = ?)
                  AND (? IS NULL OR EXISTS (
                      SELECT 1
                      FROM order_tests match_ot
                      WHERE match_ot.order_id = o.id AND match_ot.test_id = ?
                  ))
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) >= DATE(?))
                  AND (? = '' OR DATE(COALESCE(o.ordered_at, o.created_at)) <= DATE(?))
                GROUP BY o.id, o.order_number, o.status, order_date, c.name, patient_name
                ORDER BY DATE(COALESCE(o.ordered_at, o.created_at)) DESC, o.id DESC
                """,
                (
                    client_id,
                    client_id,
                    test_id,
                    test_id,
                    date_from,
                    date_from,
                    date_to,
                    date_to,
                ),
            ).fetchall()
        return [
            (
                row["id"],
                f'{row["order_number"]} - {row["patient_name"]} - {row["client_name"] or "No Client"} - {row["order_date"] or ""} ({row["item_count"]} tests, {row["status"]})',
            )
            for row in rows
        ]

    def get_order_result_entries(self, order_id: int) -> list[ResultEntryRecord]:
        with self.connect() as connection:
            rows = connection.execute("SELECT ot.id AS order_test_id, o.id AS order_id, o.order_number, TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name, d.full_name AS doctor_name, p.sex AS patient_sex, p.date_of_birth, p.age_value, p.age_unit, t.id AS test_id, COALESCE(ot.display_name, t.name) AS test_name, t.specimen_type, CASE WHEN t.code = '__PANEL_HEADING__' THEN 'heading' WHEN t.code = '__PANEL_COMMENT__' THEN 'comment' ELSE 'test' END AS item_type, t.result_kind, t.select_options, t.default_result_value, t.result_multiplier, r.result_value, r.unit, COALESCE(r.lower_value_text, CAST(r.lower_value AS TEXT)) AS lower_value, COALESCE(r.upper_value_text, CAST(r.upper_value AS TEXT)) AS upper_value, r.flag, r.reference_text, r.comments, ot.status AS test_status, COALESCE(ot.is_outsourced, 0) AS is_outsourced, ot.source_label FROM order_tests ot INNER JOIN orders o ON o.id = ot.order_id INNER JOIN patients p ON p.id = o.patient_id LEFT JOIN doctors d ON d.id = o.doctor_id INNER JOIN tests t ON t.id = ot.test_id LEFT JOIN results r ON r.order_test_id = ot.id WHERE o.id = ? ORDER BY ot.sort_order, ot.id", (order_id,)).fetchall()
            records: list[ResultEntryRecord] = []
            for row in rows:
                data = dict(row)
                age_days = self._resolve_age_days(data.pop("date_of_birth"), data.pop("age_value"), data.pop("age_unit"))
                data["patient_age_days"] = age_days
                if data.get("item_type") not in {"heading", "comment"}:
                    if not data.get("result_value") and data.get("default_result_value"):
                        data["result_value"] = data["default_result_value"]
                    reference = self._resolve_reference_range(connection, data["test_id"], data["patient_sex"], age_days)
                    if reference is not None:
                        if not data["unit"]:
                            data["unit"] = reference["unit"]
                        if data["lower_value"] is None:
                            data["lower_value"] = reference["lower_value"]
                        if data["upper_value"] is None:
                            data["upper_value"] = reference["upper_value"]
                        if not data["reference_text"]:
                            data["reference_text"] = reference["reference_text"]
                records.append(ResultEntryRecord(**data))
            return records

    def list_client_results_for_export(
        self,
        *,
        client_id: int | None = None,
        date_from: str = "",
        date_to: str = "",
    ) -> list[tuple[str, str, str, str, str, str]]:
        """Returns (order_date, patient_name, panel, test_name, result_value, unit) rows."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT SUBSTR(COALESCE(o.ordered_at, o.created_at), 1, 10) AS order_date,
                       TRIM(p.first_name || ' ' || p.last_name ||
                            CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != ''
                                 THEN ' ' || p.middle_name ELSE '' END) AS patient_name,
                       COALESCE(ot.source_label, '') AS panel,
                       COALESCE(ot.display_name, t.name) AS test_name,
                       COALESCE(r.result_value, '') AS result_value,
                       COALESCE(r.unit, '') AS unit
                FROM order_tests ot
                INNER JOIN orders o ON o.id = ot.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN tests t ON t.id = ot.test_id
                LEFT JOIN results r ON r.order_test_id = ot.id
                WHERE t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                  AND (? IS NULL OR o.client_id = ?)
                  AND (? = '' OR SUBSTR(COALESCE(o.ordered_at, o.created_at), 1, 10) >= ?)
                  AND (? = '' OR SUBSTR(COALESCE(o.ordered_at, o.created_at), 1, 10) <= ?)
                ORDER BY COALESCE(o.ordered_at, o.created_at), p.last_name, p.first_name, ot.sort_order
                """,
                (client_id, client_id, date_from, date_from, date_to, date_to),
            ).fetchall()
        return [(str(r[0] or ""), str(r[1] or ""), str(r[2] or ""),
                 str(r[3] or ""), str(r[4] or ""), str(r[5] or "")) for r in rows]

    def list_order_test_codes(self, order_id: int) -> dict[int, str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT ot.id AS order_test_id, t.code FROM order_tests ot INNER JOIN tests t ON t.id = ot.test_id WHERE ot.order_id = ?",
                (order_id,),
            ).fetchall()
        return {int(row["order_test_id"]): str(row["code"] or "") for row in rows}

    def list_instrument_result_mappings(self, *, instrument_profile: str = "") -> list[InstrumentResultMappingRecord]:
        normalized_profile = self._normalize_instrument_key(instrument_profile)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.id,
                       m.instrument_profile,
                       m.device_id,
                       m.raw_code,
                       m.raw_name,
                       m.specimen_type,
                       m.panel_hint,
                       m.test_id,
                       t.code AS test_code,
                       t.name AS test_name,
                       m.unit_override,
                       m.reference_range_override,
                       m.is_active,
                       m.value_slice_start,
                       m.value_slice_end,
                       m.value_multiplier,
                       m.decimal_places,
                       m.value_formula
                FROM instrument_result_mappings m
                INNER JOIN tests t ON t.id = m.test_id
                WHERE (? = '' OR m.instrument_profile = ?)
                ORDER BY m.instrument_profile, m.raw_code, m.specimen_type, m.panel_hint, t.name
                """,
                (normalized_profile, normalized_profile),
            ).fetchall()
        return [InstrumentResultMappingRecord(**dict(row)) for row in rows]

    def save_instrument_result_mapping(
        self,
        *,
        instrument_profile: str,
        device_id: str,
        raw_code: str,
        raw_name: str = "",
        specimen_type: str = "",
        panel_hint: str = "",
        test_id: int,
        unit_override: str = "",
        reference_range_override: str = "",
        value_slice_start: int | None = None,
        value_slice_end: int | None = None,
        value_multiplier: float | None = None,
        decimal_places: int | None = None,
        value_formula: str | None = None,
    ) -> None:
        normalized_profile = self._normalize_instrument_key(instrument_profile)
        normalized_device = self._normalize_optional_instrument_key(device_id)
        normalized_code = self._normalize_instrument_code(raw_code)
        normalized_specimen = self._normalize_optional_instrument_key(specimen_type)
        normalized_panel = self._normalize_optional_instrument_key(panel_hint)
        if not normalized_profile or not normalized_code:
            raise sqlite3.IntegrityError("Instrument profile and raw code are required.")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO instrument_result_mappings (
                    instrument_profile, device_id, raw_code, raw_name, specimen_type, panel_hint,
                    test_id, unit_override, reference_range_override,
                    value_slice_start, value_slice_end, value_multiplier, decimal_places, value_formula,
                    is_active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(instrument_profile, device_id, raw_code, specimen_type, panel_hint)
                DO UPDATE SET
                    raw_name = excluded.raw_name,
                    test_id = excluded.test_id,
                    unit_override = excluded.unit_override,
                    reference_range_override = excluded.reference_range_override,
                    value_slice_start = excluded.value_slice_start,
                    value_slice_end = excluded.value_slice_end,
                    value_multiplier = excluded.value_multiplier,
                    decimal_places = excluded.decimal_places,
                    value_formula = excluded.value_formula,
                    is_active = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    normalized_profile,
                    normalized_device or "",
                    normalized_code,
                    raw_name.strip() or None,
                    normalized_specimen or "",
                    normalized_panel or "",
                    int(test_id),
                    unit_override.strip() or None,
                    reference_range_override.strip() or None,
                    value_slice_start,
                    value_slice_end,
                    value_multiplier,
                    decimal_places,
                    value_formula.strip() if value_formula and value_formula.strip() else None,
                ),
            )

    def resolve_instrument_result_mapping(
        self,
        *,
        instrument_profile: str,
        device_id: str,
        raw_code: str,
        specimen_type: str = "",
        panel_hint: str = "",
    ) -> InstrumentResultMappingRecord | None:
        normalized_profile = self._normalize_instrument_key(instrument_profile)
        normalized_device = self._normalize_optional_instrument_key(device_id)
        normalized_code = self._normalize_instrument_code(raw_code)
        normalized_specimen = self._normalize_optional_instrument_key(specimen_type)
        normalized_panel = self._normalize_optional_instrument_key(panel_hint)
        if not normalized_profile or not normalized_code:
            return None
        # For TCP server captures the device_id includes the ephemeral source port
        # (e.g. "10.0.0.3:51234"). Also try matching on the IP-only portion so that
        # mappings saved with a fixed port ("10.0.0.3:5100") still resolve.
        device_ip_only = normalized_device.rsplit(":", 1)[0] if normalized_device and ":" in normalized_device else None
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.id,
                       m.instrument_profile,
                       m.device_id,
                       m.raw_code,
                       m.raw_name,
                       m.specimen_type,
                       m.panel_hint,
                       m.test_id,
                       t.code AS test_code,
                       t.name AS test_name,
                       m.unit_override,
                       m.reference_range_override,
                       m.is_active,
                       m.value_slice_start,
                       m.value_slice_end,
                       m.value_multiplier,
                       m.decimal_places,
                       m.value_formula
                FROM instrument_result_mappings m
                INNER JOIN tests t ON t.id = m.test_id
                WHERE m.is_active = 1
                  AND m.instrument_profile = ?
                  AND m.raw_code = ?
                  AND (m.device_id = ? OR (? IS NOT NULL AND m.device_id LIKE ? || ':%') OR m.device_id = '' OR m.device_id IS NULL)
                  AND (m.specimen_type = ? OR m.specimen_type = '' OR m.specimen_type IS NULL)
                  AND (m.panel_hint = ? OR m.panel_hint = '' OR m.panel_hint IS NULL)
                ORDER BY
                  CASE WHEN m.device_id = ? THEN 0 ELSE 1 END,
                  CASE WHEN m.specimen_type = ? THEN 0 ELSE 1 END,
                  CASE WHEN m.panel_hint = ? THEN 0 ELSE 1 END,
                  m.id DESC
                LIMIT 1
                """,
                (
                    normalized_profile,
                    normalized_code,
                    normalized_device,
                    device_ip_only,
                    device_ip_only,
                    normalized_specimen,
                    normalized_panel,
                    normalized_device,
                    normalized_specimen,
                    normalized_panel,
                ),
            ).fetchall()
        if not rows:
            return None
        return InstrumentResultMappingRecord(**dict(rows[0]))

    def list_instrument_profiles(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT instrument_profile FROM instrument_result_mappings ORDER BY instrument_profile"
            ).fetchall()
        return [str(row["instrument_profile"]) for row in rows]

    def delete_instrument_result_mapping(self, mapping_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM instrument_result_mappings WHERE id = ?", (mapping_id,))

    def toggle_instrument_result_mapping_active(self, mapping_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE instrument_result_mappings SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (mapping_id,),
            )

    def update_instrument_result_mapping_profile(self, mapping_id: int, instrument_profile: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE instrument_result_mappings SET instrument_profile = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (instrument_profile, mapping_id),
            )

    def find_order_by_instrument_ids(
        self,
        *,
        sample_id: str = "",
        accession_id: str = "",
        order_number: str = "",
        patient_id: str = "",
    ) -> int | None:
        sample_id = (sample_id or "").strip()
        accession_id = (accession_id or "").strip()
        order_number = (order_number or "").strip()
        patient_id = (patient_id or "").strip()
        if not sample_id and not accession_id and not order_number and not patient_id:
            return None
        with self.connect() as connection:
            _open = "status NOT IN ('finalized', 'cancelled') AND COALESCE(is_preallocated, 0) = 0"
            for col, val in [
                ("sample_id", sample_id),
                ("accession_id", accession_id),
                ("order_number", order_number),
                ("order_number", patient_id),
            ]:
                if not val:
                    continue
                row = connection.execute(
                    f"SELECT id FROM orders WHERE {col} = ? AND {_open} ORDER BY created_at DESC LIMIT 1",
                    (val,),
                ).fetchone()
                if row is not None:
                    return int(row["id"])
        return None

    def get_instrument_order_match(self, profile_id: str) -> InstrumentOrderMatchRecord | None:
        profile_id = (profile_id or "").strip()
        if not profile_id:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT instrument_profile, instrument_field, order_field, auto_import, broadcast_enabled, broadcast_protocol, broadcast_encoding, broadcast_patient_id, broadcast_patient_name, broadcast_dob, broadcast_age, broadcast_sex, broadcast_doctor FROM instrument_order_match_config WHERE instrument_profile = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            return None
        return InstrumentOrderMatchRecord(
            instrument_profile=str(row["instrument_profile"]),
            instrument_field=str(row["instrument_field"]),
            order_field=str(row["order_field"]),
            auto_import=int(row["auto_import"]),
            broadcast_enabled=int(row["broadcast_enabled"] or 0),
            broadcast_protocol=str(row["broadcast_protocol"] or "hl7_orm"),
            broadcast_encoding=str(row["broadcast_encoding"] or "ascii"),
            broadcast_patient_id=int(row["broadcast_patient_id"] or 1),
            broadcast_patient_name=int(row["broadcast_patient_name"] or 1),
            broadcast_dob=int(row["broadcast_dob"] or 1),
            broadcast_age=int(row["broadcast_age"] or 1),
            broadcast_sex=int(row["broadcast_sex"] or 1),
            broadcast_doctor=int(row["broadcast_doctor"] or 1),
        )

    def save_instrument_order_match(
        self,
        profile_id: str,
        instrument_field: str,
        order_field: str,
        *,
        auto_import: bool = True,
        broadcast_enabled: bool = False,
        broadcast_protocol: str = "hl7_orm",
        broadcast_encoding: str = "ascii",
        broadcast_patient_id: bool = True,
        broadcast_patient_name: bool = True,
        broadcast_dob: bool = True,
        broadcast_age: bool = True,
        broadcast_sex: bool = True,
        broadcast_doctor: bool = True,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO instrument_order_match_config (
                    instrument_profile, instrument_field, order_field, auto_import,
                    broadcast_enabled, broadcast_protocol, broadcast_encoding, broadcast_patient_id,
                    broadcast_patient_name, broadcast_dob, broadcast_age, broadcast_sex, broadcast_doctor,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (instrument_profile) DO UPDATE SET
                    instrument_field = excluded.instrument_field,
                    order_field = excluded.order_field,
                    auto_import = excluded.auto_import,
                    broadcast_enabled = excluded.broadcast_enabled,
                    broadcast_protocol = excluded.broadcast_protocol,
                    broadcast_encoding = excluded.broadcast_encoding,
                    broadcast_patient_id = excluded.broadcast_patient_id,
                    broadcast_patient_name = excluded.broadcast_patient_name,
                    broadcast_dob = excluded.broadcast_dob,
                    broadcast_age = excluded.broadcast_age,
                    broadcast_sex = excluded.broadcast_sex,
                    broadcast_doctor = excluded.broadcast_doctor,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    profile_id, instrument_field, order_field, 1 if auto_import else 0,
                    1 if broadcast_enabled else 0, broadcast_protocol or "hl7_orm",
                    broadcast_encoding or "ascii",
                    1 if broadcast_patient_id else 0, 1 if broadcast_patient_name else 0,
                    1 if broadcast_dob else 0, 1 if broadcast_age else 0, 1 if broadcast_sex else 0,
                    1 if broadcast_doctor else 0,
                ),
            )

    def list_instrument_order_match_configs(self) -> list[InstrumentOrderMatchRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT instrument_profile, instrument_field, order_field, auto_import, broadcast_enabled, broadcast_protocol, broadcast_encoding, broadcast_patient_id, broadcast_patient_name, broadcast_dob, broadcast_age, broadcast_sex, broadcast_doctor FROM instrument_order_match_config ORDER BY instrument_profile"
            ).fetchall()
        return [
            InstrumentOrderMatchRecord(
                instrument_profile=str(row["instrument_profile"]),
                instrument_field=str(row["instrument_field"]),
                order_field=str(row["order_field"]),
                auto_import=int(row["auto_import"]),
                broadcast_enabled=int(row["broadcast_enabled"] or 0),
                broadcast_protocol=str(row["broadcast_protocol"] or "hl7_orm"),
            broadcast_encoding=str(row["broadcast_encoding"] or "ascii"),
                broadcast_patient_id=int(row["broadcast_patient_id"] or 1),
                broadcast_patient_name=int(row["broadcast_patient_name"] or 1),
                broadcast_dob=int(row["broadcast_dob"] or 1),
                broadcast_sex=int(row["broadcast_sex"] or 1),
                broadcast_doctor=int(row["broadcast_doctor"] or 1),
            )
            for row in rows
        ]

    @staticmethod
    def _payload_has_data(payload: dict[str, Any]) -> bool:
        text = str(payload.get("normalized_text") or payload.get("decoded_text") or "")
        visible = "".join(c for c in text if c.isprintable()).strip()
        return len(visible) > 1

    def load_instrument_captures_cache(self) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT capture_id, payload_json FROM (
                    SELECT capture_id, payload_json FROM instrument_captures_cache
                    WHERE has_data = 1 ORDER BY received_at DESC LIMIT 500
                )
                UNION ALL
                SELECT capture_id, payload_json FROM (
                    SELECT capture_id, payload_json FROM instrument_captures_cache
                    WHERE has_data = 0 ORDER BY received_at DESC LIMIT 10
                )
                """
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                data = json.loads(row["payload_json"])
                if isinstance(data, dict):
                    result[str(row["capture_id"])] = data
            except json.JSONDecodeError:
                pass
        return result

    def upsert_instrument_captures_cache(self, captures: list[dict[str, Any]]) -> None:
        if not captures:
            return
        with self.connect() as connection:
            for capture in captures:
                cid = str(capture.get("id") or "").strip()
                if not cid:
                    continue
                received_at = str(capture.get("received_at") or "")
                has_data = 1 if self._payload_has_data(capture) else 0
                connection.execute(
                    """
                    INSERT INTO instrument_captures_cache (capture_id, received_at, payload_json, cached_at, has_data)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                    ON CONFLICT (capture_id) DO UPDATE SET
                        received_at = excluded.received_at,
                        payload_json = excluded.payload_json,
                        cached_at = CURRENT_TIMESTAMP,
                        has_data = excluded.has_data
                    """,
                    (cid, received_at, json.dumps(capture), has_data),
                )
            connection.execute(
                """
                DELETE FROM instrument_captures_cache
                WHERE has_data = 1 AND capture_id NOT IN (
                    SELECT capture_id FROM instrument_captures_cache
                    WHERE has_data = 1
                    ORDER BY received_at DESC, cached_at DESC
                    LIMIT 500
                )
                """
            )
            connection.execute(
                """
                DELETE FROM instrument_captures_cache
                WHERE has_data = 0 AND capture_id NOT IN (
                    SELECT capture_id FROM instrument_captures_cache
                    WHERE has_data = 0
                    ORDER BY received_at DESC, cached_at DESC
                    LIMIT 10
                )
                """
            )

    def get_order_receipt_lines(self, order_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT o.order_number,
                       TRIM(p.first_name || ' ' || p.last_name) AS patient_name,
                       p.sex AS patient_sex,
                       p.age_value,
                       p.age_unit,
                       COALESCE(o.ordered_at, o.created_at) AS order_date,
                       COALESCE(ot.display_name, t.name) AS test_name,
                       COALESCE(t.price, 0.0) AS price,
                       t.code
                FROM order_tests ot
                INNER JOIN orders o ON o.id = ot.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE ot.order_id = ?
                  AND t.code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                ORDER BY ot.sort_order, ot.id
                """,
                (order_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_order_label_entries(self, order_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT ot.id AS order_test_id,
                       o.order_number,
                       o.accession_id,
                       o.sample_id,
                       o.client_id,
                       TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name,
                       p.sex AS patient_sex,
                       p.age_value,
                       p.age_unit,
                       COALESCE(ot.display_name, t.name) AS display_name,
                       t.name AS test_name,
                       t.specimen_type,
                       t.code AS test_code,
                       CASE WHEN t.code = '__PANEL_HEADING__' THEN 'heading'
                            WHEN t.code = '__PANEL_COMMENT__' THEN 'comment'
                            ELSE 'test'
                       END AS item_type,
                       o.created_at
                FROM order_tests ot
                INNER JOIN orders o ON o.id = ot.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                INNER JOIN tests t ON t.id = ot.test_id
                WHERE ot.order_id = ?
                ORDER BY ot.sort_order, ot.id
                """,
                (order_id,),
            ).fetchall()
        labels: list[dict[str, Any]] = []
        current_group = ''
        for row in rows:
            data = dict(row)
            item_type = data.get('item_type')
            if item_type == 'heading':
                current_group = str(data.get('display_name') or '').strip()
                continue
            if item_type == 'comment':
                continue
            specimen_type = str(data.get('specimen_type') or '')
            labels.append({
                'order_test_id': data.get('order_test_id'),
                'order_number': data.get('order_number'),
                'accession_id': data.get('accession_id') or '',
                'sample_id': data.get('sample_id') or '',
                'client_id': data.get('client_id'),
                'patient_name': data.get('patient_name'),
                'patient_sex': data.get('patient_sex'),
                'age_value': data.get('age_value'),
                'age_unit': data.get('age_unit'),
                'test_name': data.get('display_name') or data.get('test_name'),
                'specimen_type': specimen_type,
                'specimen_code': self._specimen_code(specimen_type),
                'test_code': data.get('test_code') or '',
                'group_label': current_group,
                'created_at': data.get('created_at'),
            })
        return labels

    def get_live_report_preview(self, order_id: int) -> dict[str, Any] | None:
        context = self._get_report_context(order_id)
        if context is None:
            return None
        entries = self.get_order_result_entries(order_id)
        settings = self.get_lab_settings()
        outsourced_order_test_ids = self._get_outsourced_order_test_ids(order_id)
        preview_items = [
            {
                "order_test_id": entry.order_test_id,
                "test_id": entry.test_id,
                "item_type": entry.item_type,
                "test_name": entry.test_name,
                "result_value": entry.result_value,
                "unit": entry.unit,
                "reference_text": entry.reference_text,
                "lower_value": entry.lower_value,
                "upper_value": entry.upper_value,
                "flag": entry.flag,
                "comments": entry.comments,
                "sort_order": index,
                "source_label": entry.source_label,
            }
            for index, entry in enumerate(entries)
            if entry.order_test_id not in outsourced_order_test_ids
            and not (entry.item_type in {"heading", "comment"} and not (entry.source_label or "").strip())
        ]
        return {
            **self.get_report_layout_settings(),
            "source": "live",
            "report_status": "draft",
            "report_version": None,
            "finalized_at": None,
            "order_id": context["order_id"],
            "order_number": context["order_number"],
            "accession_id": context["accession_id"],
            "sample_id": context["sample_id"],
            "ordered_at": context["ordered_at"],
            "reported_at": context["reported_at"],
            "order_status": context["order_status"],
            "patient_name": context["patient_name"],
            "patient_sex": context["patient_sex"],
            "patient_dob": context["patient_dob"],
            "patient_age_value": context["patient_age_value"],
            "patient_age_unit": context["patient_age_unit"],
            "doctor_name": context["doctor_name"],
            "client_name": context["client_name"],
            "lab_name": settings.lab_name,
            "lab_address": settings.address,
            "lab_phone": settings.phone,
            "lab_email": settings.email,
            "director_name": settings.director_name,
            "director_license": settings.director_license,
            "footer_text": settings.report_footer,
            "header_image_path": settings.header_image_path,
            "footer_signature_image_path": settings.footer_signature_image_path,
            "general_comments": context["notes"],
            "outsourced_panels": self.get_outsourced_panel_preview_sections(order_id),
            "items": self._inject_panel_title_rows(
                self._restore_panel_catalog_structure(preview_items),
                self.get_panel_report_metadata_by_name(),
            ),
        }

    def get_saved_report_preview(self, order_id: int) -> dict[str, Any] | None:
        current_settings = self.get_lab_settings()
        with self.connect() as connection:
            report_row = connection.execute(
                """
                SELECT r.id,
                       r.order_id,
                       r.report_version,
                       r.status,
                       r.finalized_at,
                       r.patient_snapshot_name,
                       r.patient_snapshot_sex,
                       r.patient_snapshot_dob,
                       r.doctor_snapshot_name,
                       r.lab_snapshot_name,
                       r.lab_snapshot_address,
                       r.lab_snapshot_phone,
                       r.lab_snapshot_email,
                       r.director_snapshot_name,
                       r.director_snapshot_license,
                       r.footer_snapshot_text,
                       r.header_image_snapshot_path,
                       r.footer_signature_snapshot_path,
                       r.general_comments,
                       o.order_number,
                       o.accession_id,
                       o.sample_id,
                       o.ordered_at,
                       o.reported_at,
                       o.status AS order_status,
                       c.name AS client_name,
                       p.age_value AS patient_age_value,
                       p.age_unit AS patient_age_unit
                FROM reports r
                INNER JOIN orders o ON o.id = r.order_id
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN clients c ON c.id = o.client_id
                WHERE r.order_id = ?
                """,
                (order_id,),
            ).fetchone()
            if report_row is None:
                return None
            item_rows = connection.execute(
                """
                SELECT order_test_id,
                       item_type_snapshot,
                       test_name_snapshot,
                       result_value_snapshot,
                       unit_snapshot,
                       reference_text_snapshot,
                       lower_value_snapshot_text,
                       upper_value_snapshot_text,
                       flag_snapshot,
                       comments_snapshot,
                       sort_order
                FROM report_items
                WHERE report_id = ?
                ORDER BY sort_order, id
                """,
                (report_row["id"],),
            ).fetchall()
            outsourced_rows = connection.execute(
                """
                SELECT panel_label,
                       source_pdf_path,
                       row_index,
                       col_1,
                       col_2,
                       col_3,
                       col_4,
                       col_5
                FROM report_outsourced_rows
                WHERE report_id = ?
                ORDER BY panel_label, row_index, id
                """,
                (report_row["id"],),
            ).fetchall()
        current_outsourced_sections = self.get_outsourced_panel_preview_sections(int(report_row["order_id"]))
        outsourced_sections = current_outsourced_sections or self._group_outsourced_rows(outsourced_rows)
        saved_items = [
            {
                "order_test_id": row["order_test_id"],
                "item_type": row["item_type_snapshot"] or "test",
                "test_name": row["test_name_snapshot"],
                "result_value": row["result_value_snapshot"],
                "unit": row["unit_snapshot"],
                "reference_text": row["reference_text_snapshot"],
                "lower_value": row["lower_value_snapshot_text"],
                "upper_value": row["upper_value_snapshot_text"],
                "flag": row["flag_snapshot"],
                "comments": row["comments_snapshot"],
                "sort_order": row["sort_order"],
            }
            for row in item_rows
        ]
        live_preview = self.get_live_report_preview(int(report_row["order_id"]))
        rendered_items = self._merge_saved_result_values_into_live_items(
            saved_items,
            list((live_preview or {}).get("items") or []),
        )
        # Prefer live patient/order data over the snapshot so edits are reflected
        # immediately without having to re-finalize. Snapshots are the fallback.
        live_ctx = live_preview or {}
        return {
            **self.get_report_layout_settings(),
            "source": "saved",
            "report_status": report_row["status"],
            "report_version": report_row["report_version"],
            "finalized_at": report_row["finalized_at"],
            "order_id": report_row["order_id"],
            "order_number": live_ctx.get("order_number") or report_row["order_number"],
            "accession_id": live_ctx.get("accession_id") or report_row["accession_id"],
            "sample_id": live_ctx.get("sample_id") or report_row["sample_id"],
            "ordered_at": live_ctx.get("ordered_at") or report_row["ordered_at"],
            "reported_at": live_ctx.get("reported_at") or report_row["reported_at"],
            "order_status": live_ctx.get("order_status") or report_row["order_status"],
            "patient_name": live_ctx.get("patient_name") or report_row["patient_snapshot_name"],
            "patient_sex": live_ctx.get("patient_sex") or report_row["patient_snapshot_sex"],
            "patient_dob": live_ctx.get("patient_dob") or report_row["patient_snapshot_dob"],
            "patient_age_value": live_ctx.get("patient_age_value") or report_row["patient_age_value"],
            "patient_age_unit": live_ctx.get("patient_age_unit") or report_row["patient_age_unit"],
            "doctor_name": live_ctx.get("doctor_name") or report_row["doctor_snapshot_name"],
            "client_name": live_ctx.get("client_name") or report_row["client_name"],
            "lab_name": report_row["lab_snapshot_name"],
            "lab_address": report_row["lab_snapshot_address"],
            "lab_phone": report_row["lab_snapshot_phone"],
            "lab_email": report_row["lab_snapshot_email"],
            "director_name": report_row["director_snapshot_name"],
            "director_license": report_row["director_snapshot_license"],
            "footer_text": report_row["footer_snapshot_text"],
            "header_image_path": report_row["header_image_snapshot_path"] or current_settings.header_image_path,
            "footer_signature_image_path": report_row["footer_signature_snapshot_path"] or current_settings.footer_signature_image_path,
            "general_comments": report_row["general_comments"],
            "outsourced_panels": self.get_outsourced_panel_preview_sections(order_id),
            "items": rendered_items,
        }

    @staticmethod
    def _merge_saved_result_values_into_live_items(
        saved_items: list[dict[str, Any]],
        live_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not live_items:
            return saved_items
        saved_by_order_test_id = {
            item.get("order_test_id"): item
            for item in saved_items
            if item.get("order_test_id") is not None
        }
        merged: list[dict[str, Any]] = []
        for live_item in live_items:
            item = dict(live_item)
            saved_item = saved_by_order_test_id.get(item.get("order_test_id"))
            if saved_item is not None:
                for key in ("result_value", "unit", "reference_text", "lower_value", "upper_value", "flag", "comments"):
                    item[key] = saved_item.get(key)
            merged.append(item)
        return merged

    def _restore_panel_catalog_structure(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        structures = self._panel_catalog_structures()
        if not structures:
            return items
        grouped_order_items: dict[str, list[dict[str, Any]]] = {}
        group_order: list[str] = []
        passthrough: list[dict[str, Any]] = []
        for item in items:
            raw_label = self._normalize_report_panel_label(str(item.get("source_label") or ""))
            structure = structures.get(raw_label.casefold())
            label = str((structure or {}).get("name") or raw_label).strip()
            if not label:
                passthrough.append(item)
                continue
            if label not in grouped_order_items:
                group_order.append(label)
            grouped_order_items.setdefault(label, []).append(item)
        if not grouped_order_items:
            return items
        restored: list[dict[str, Any]] = []
        restored.extend(passthrough)
        for label in group_order:
            order_items = grouped_order_items[label]
            structure = structures.get(label.casefold())
            if structure is None:
                restored.extend(self._normalize_panel_source_items(order_items, label, structures))
                continue
            if any(str(item.get("item_type") or "test") in {"heading", "comment"} for item in order_items):
                restored.extend(self._normalize_panel_source_items(order_items, structure["name"], structures))
                continue
            by_test_id = {
                int(item["test_id"]): item
                for item in order_items
                if item.get("test_id") is not None
            }
            used_test_ids: set[int] = set()
            for panel_item in structure["items"]:
                item_type = str(panel_item.get("item_type") or "test")
                if item_type in {"heading", "comment"}:
                    restored.append(
                        {
                            "order_test_id": None,
                            "test_id": None,
                            "item_type": item_type,
                            "test_name": str(panel_item.get("heading_text") or panel_item.get("label") or ""),
                            "result_value": "",
                            "unit": "",
                            "reference_text": "",
                            "lower_value": "",
                            "upper_value": "",
                            "flag": "",
                            "comments": "",
                            "source_label": structure["name"],
                        }
                    )
                    continue
                test_id = panel_item.get("test_id")
                if test_id is None:
                    continue
                matched = by_test_id.get(int(test_id))
                if matched is None:
                    continue
                normalized = dict(matched)
                normalized["source_label"] = structure["name"]
                restored.append(normalized)
                used_test_ids.add(int(test_id))
            for item in order_items:
                test_id = item.get("test_id")
                if test_id is None or int(test_id) not in used_test_ids:
                    normalized = dict(item)
                    normalized["source_label"] = structure["name"]
                    restored.append(normalized)
        return restored

    def _normalize_panel_source_items(
        self,
        items: list[dict[str, Any]],
        label: str,
        structures: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        structure = structures.get(label.casefold())
        resolved_label = str((structure or {}).get("name") or label).strip()
        normalized_items: list[dict[str, Any]] = []
        for item in items:
            normalized = dict(item)
            normalized["source_label"] = resolved_label
            normalized_items.append(normalized)
        return normalized_items

    def _panel_catalog_structures(self) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            panel_rows = connection.execute("SELECT id, code, name FROM test_panels WHERE is_active = 1").fetchall()
            item_rows = connection.execute(
                "SELECT panel_id, item_type, test_id, heading_text, sort_order FROM test_panel_items ORDER BY panel_id, sort_order, id"
            ).fetchall()
        items_by_panel_id: dict[int, list[dict[str, Any]]] = {}
        for row in item_rows:
            items_by_panel_id.setdefault(int(row["panel_id"]), []).append(dict(row))
        structures: dict[str, dict[str, Any]] = {}
        for row in panel_rows:
            name = str(row["name"] or "").strip()
            code = str(row["code"] or "").strip()
            if not name:
                continue
            structure = {
                "name": name,
                "code": code,
                "items": items_by_panel_id.get(int(row["id"]), []),
            }
            for key in {name, code, self._normalize_report_panel_label(f"{name} ({code})"), self._normalize_report_panel_label(f"{name} ({code}) - 1 tests")}:
                normalized_key = str(key or "").strip()
                if normalized_key:
                    structures[normalized_key.casefold()] = structure
        return structures

    def _inject_panel_title_rows(self, items: list[dict[str, Any]], panel_metadata: dict[str, dict[str, str]] | None = None) -> list[dict[str, Any]]:
        panel_counts: dict[str, int] = {}
        for item in items:
            label = self._normalize_report_panel_label(str(item.get("source_label") or ""))
            if not label or str(item.get("item_type") or "test") != "test":
                continue
            panel_counts[label] = panel_counts.get(label, 0) + 1

        rendered: list[dict[str, Any]] = []
        active_panel = ""
        next_sort_order = 0
        metadata = panel_metadata or {}

        def append_panel_meta(panel_name: str) -> None:
            nonlocal next_sort_order
            values = metadata.get(panel_name) or {}
            specimen_type = str(values.get("specimen_type") or "").strip()
            method = str(values.get("method") or "").strip()
            if not specimen_type and not method:
                return
            rendered.append(
                {
                    "order_test_id": None,
                    "item_type": "panel_meta",
                    "test_name": "",
                    "result_value": "",
                    "unit": "",
                    "reference_text": "",
                    "lower_value": "",
                    "upper_value": "",
                    "flag": "",
                    "comments": f"{tr('Methodology')}: {method} | {tr('Specimen Type')}: {specimen_type}",
                    "sort_order": next_sort_order,
                }
            )
            next_sort_order += 1

        for item in items:
            normalized = dict(item)
            item_type = str(normalized.get("item_type") or "test")
            label = self._normalize_report_panel_label(str(normalized.get("source_label") or ""))
            normalized["source_label"] = label
            if item_type in {"test", "heading", "comment"} and label and label != active_panel:
                if active_panel:
                    append_panel_meta(active_panel)
                rendered.append(
                    {
                        "order_test_id": None,
                        "item_type": "heading",
                        "test_name": label,
                        "result_value": "",
                        "unit": "",
                        "reference_text": "",
                        "lower_value": "",
                        "upper_value": "",
                        "flag": "",
                        "comments": "",
                        "sort_order": next_sort_order,
                    }
                )
                next_sort_order += 1
                active_panel = label
            normalized["sort_order"] = next_sort_order
            rendered.append(normalized)
            next_sort_order += 1
            if item_type == "heading" and not label:
                active_panel = ""
        if active_panel:
            append_panel_meta(active_panel)
        return rendered

    @staticmethod
    def _normalize_report_panel_label(value: str) -> str:
        label = value.strip()
        if not label:
            return ""
        label = re.sub(r"\s*-\s*\d+\s+tests\s*$", "", label, flags=re.IGNORECASE).strip()
        return re.sub(r"\s+\([A-Z0-9_-]{1,20}\)$", "", label).strip()

    def finalize_report(
        self,
        order_id: int,
        *,
        header_image_path: str | None = None,
        footer_signature_image_path: str | None = None,
        preview_override: dict[str, Any] | None = None,
    ) -> int:
        preview = dict(preview_override) if preview_override is not None else self.get_live_report_preview(order_id)
        if preview is None:
            raise sqlite3.IntegrityError("Order not found.")
        preview["items"] = [dict(item) for item in list(preview.get("items") or [])]
        preview["outsourced_panels"] = [
            {
                "panel_label": str(section.get("panel_label") or ""),
                "source_pdf_path": str(section.get("source_pdf_path") or ""),
                "rows": [
                    {
                        "row_index": int(row.get("row_index") or index),
                        "col_1": str(row.get("col_1") or ""),
                        "col_2": str(row.get("col_2") or ""),
                        "col_3": str(row.get("col_3") or ""),
                        "col_4": str(row.get("col_4") or ""),
                        "col_5": str(row.get("col_5") or ""),
                    }
                    for index, row in enumerate(list(section.get("rows") or []))
                ],
            }
            for section in list(preview.get("outsourced_panels") or [])
        ]
        if header_image_path is not None:
            preview["header_image_path"] = self._copy_report_branding_asset(header_image_path, "header") if header_image_path.strip() else ""
        if footer_signature_image_path is not None:
            preview["footer_signature_image_path"] = self._copy_report_branding_asset(footer_signature_image_path, "footer") if footer_signature_image_path.strip() else ""
        for index, item in enumerate(preview["items"]):
            item["sort_order"] = index
        reportable_items = [item for item in preview["items"] if item["item_type"] != "heading"]
        outsourced_sections = [section for section in preview["outsourced_panels"] if list(section.get("rows") or [])]
        if not reportable_items and not outsourced_sections:
            raise sqlite3.IntegrityError("The selected order has no reportable items.")
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id, report_version FROM reports WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            next_version = int(existing["report_version"]) + 1 if existing is not None else 1
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO reports (
                        order_id, report_version, status, finalized_at, patient_snapshot_name, patient_snapshot_sex,
                        patient_snapshot_dob, doctor_snapshot_name, lab_snapshot_name, lab_snapshot_address,
                        lab_snapshot_phone, lab_snapshot_email, director_snapshot_name, director_snapshot_license,
                        footer_snapshot_text, header_image_snapshot_path, footer_signature_snapshot_path, general_comments
                    ) VALUES (?, ?, 'final', CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    ,
                    (
                        order_id,
                        next_version,
                        preview["patient_name"],
                        preview["patient_sex"],
                        preview["patient_dob"],
                        preview["doctor_name"],
                        preview["lab_name"],
                        preview["lab_address"],
                        preview["lab_phone"],
                        preview["lab_email"],
                        preview["director_name"],
                        preview["director_license"],
                        preview["footer_text"],
                        preview["header_image_path"],
                        preview["footer_signature_image_path"],
                        preview["general_comments"],
                    ),
                )
                report_id = int(cursor.lastrowid)
            else:
                report_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE reports
                    SET report_version = ?,
                        status = 'final',
                        finalized_at = CURRENT_TIMESTAMP,
                        patient_snapshot_name = ?,
                        patient_snapshot_sex = ?,
                        patient_snapshot_dob = ?,
                        doctor_snapshot_name = ?,
                        lab_snapshot_name = ?,
                        lab_snapshot_address = ?,
                        lab_snapshot_phone = ?,
                        lab_snapshot_email = ?,
                        director_snapshot_name = ?,
                        director_snapshot_license = ?,
                        footer_snapshot_text = ?,
                        header_image_snapshot_path = ?,
                        footer_signature_snapshot_path = ?,
                        general_comments = ?
                    WHERE id = ?
                    """
                    ,
                    (
                        next_version,
                        preview["patient_name"],
                        preview["patient_sex"],
                        preview["patient_dob"],
                        preview["doctor_name"],
                        preview["lab_name"],
                        preview["lab_address"],
                        preview["lab_phone"],
                        preview["lab_email"],
                        preview["director_name"],
                        preview["director_license"],
                        preview["footer_text"],
                        preview["header_image_path"],
                        preview["footer_signature_image_path"],
                        preview["general_comments"],
                        report_id,
                    ),
                )
                connection.execute("DELETE FROM report_items WHERE report_id = ?", (report_id,))
                connection.execute("DELETE FROM report_outsourced_rows WHERE report_id = ?", (report_id,))
            for item in preview["items"]:
                order_test_id = item.get("order_test_id")
                if not order_test_id:
                    order_test_id = self._resolve_report_item_order_test_id(connection, order_id, item)
                connection.execute(
                    """
                    INSERT INTO report_items (
                        report_id, order_test_id, test_name_snapshot, result_value_snapshot, unit_snapshot,
                        reference_text_snapshot, lower_value_snapshot, upper_value_snapshot,
                        lower_value_snapshot_text, upper_value_snapshot_text, flag_snapshot,
                        comments_snapshot, sort_order, item_type_snapshot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    ,
                    (
                        report_id,
                        order_test_id or None,
                        item["test_name"],
                        item["result_value"] or None,
                        item["unit"] or None,
                        item["reference_text"] or None,
                        self._decimal_to_float(item["lower_value"]),
                        self._decimal_to_float(item["upper_value"]),
                        item["lower_value"] or None,
                        item["upper_value"] or None,
                        item["flag"] or None,
                        item["comments"] or None,
                        item["sort_order"],
                        item["item_type"],
                    ),
                )
            for section in outsourced_sections:
                for row in list(section.get("rows") or []):
                    connection.execute(
                        """
                        INSERT INTO report_outsourced_rows (
                            report_id, panel_label, source_pdf_path, row_index, col_1, col_2, col_3, col_4, col_5
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            report_id,
                            section.get("panel_label") or "",
                            section.get("source_pdf_path") or "",
                            int(row.get("row_index") or 0),
                            row.get("col_1") or None,
                            row.get("col_2") or None,
                            row.get("col_3") or None,
                            row.get("col_4") or None,
                            row.get("col_5") or None,
                        ),
                    )
            connection.execute(
                """
                UPDATE order_tests
                SET status = 'reported'
                WHERE order_id = ?
                  AND test_id IN (
                      SELECT id FROM tests WHERE code NOT IN ('__PANEL_HEADING__', '__PANEL_COMMENT__')
                  )
                """,
                (order_id,),
            )
            connection.execute(
                "UPDATE orders SET status = 'finalized', reported_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (order_id,),
            )
        return report_id

    def save_result_entry(self, order_test_id: int, result_value: str, unit: str, lower_value: str | None, upper_value: str | None, reference_text: str, comments: str, result_kind: str) -> None:
        normalized_value = result_value.strip()
        if result_kind == "numeric":
            normalized_value = normalized_value.replace(",", "")
        normalized_unit = unit.strip()
        normalized_reference = reference_text.strip()
        normalized_comments = comments.strip()
        flag = self._calculate_flag(result_kind, normalized_value, lower_value, upper_value)
        with self.connect() as connection:
            existing = connection.execute("SELECT id FROM results WHERE order_test_id = ?", (order_test_id,)).fetchone()
            if existing:
                connection.execute("UPDATE results SET result_value = ?, unit = ?, lower_value = ?, upper_value = ?, lower_value_text = ?, upper_value_text = ?, flag = ?, reference_text = ?, comments = ?, entered_at = CURRENT_TIMESTAMP WHERE order_test_id = ?", (normalized_value or None, normalized_unit or None, self._decimal_to_float(lower_value), self._decimal_to_float(upper_value), lower_value, upper_value, flag, normalized_reference or None, normalized_comments or None, order_test_id))
            else:
                connection.execute("INSERT INTO results (order_test_id, result_value, unit, lower_value, upper_value, lower_value_text, upper_value_text, flag, reference_text, comments, entered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)", (order_test_id, normalized_value or None, normalized_unit or None, self._decimal_to_float(lower_value), self._decimal_to_float(upper_value), lower_value, upper_value, flag, normalized_reference or None, normalized_comments or None))
            connection.execute("UPDATE order_tests SET status = 'entered' WHERE id = ?", (order_test_id,))
            connection.execute("UPDATE orders SET status = 'in_progress', updated_at = CURRENT_TIMESTAMP WHERE id = (SELECT order_id FROM order_tests WHERE id = ?)", (order_test_id,))

    def _save_test_reference_ranges(self, connection: sqlite3.Connection, test_id: int, reference_ranges: list[dict[str, Any]]) -> None:
        for reference in reference_ranges:
            connection.execute(
                "INSERT INTO test_reference_ranges (test_id, sex, age_min_days, age_max_days, lower_value, upper_value, lower_value_text, upper_value_text, unit, reference_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    test_id,
                    reference.get("sex") or None,
                    reference.get("age_min_days"),
                    reference.get("age_max_days"),
                    self._decimal_to_float(reference.get("lower_value")),
                    self._decimal_to_float(reference.get("upper_value")),
                    reference.get("lower_value"),
                    reference.get("upper_value"),
                    reference.get("unit") or "",
                    reference.get("reference_text") or None,
                ),
            )

    def _save_panel_items(self, connection: sqlite3.Connection, panel_id: int, panel_items: list[dict[str, Any]]) -> None:
        seen_test_ids: set[int] = set()
        sort_index = 0
        for item in panel_items:
            item_type = item.get("item_type", "test")
            if item_type in {"heading", "comment"}:
                heading_text = (item.get("heading_text") or item.get("label") or "").strip()
                if not heading_text:
                    continue
                connection.execute(
                    "INSERT INTO test_panel_items (panel_id, test_id, item_type, heading_text, sort_order) VALUES (?, NULL, ?, ?, ?)",
                    (panel_id, item_type, heading_text, sort_index),
                )
                sort_index += 1
                continue
            test_id = item.get("test_id")
            if test_id is None or int(test_id) in seen_test_ids:
                continue
            seen_test_ids.add(int(test_id))
            connection.execute(
                "INSERT INTO test_panel_items (panel_id, test_id, item_type, heading_text, sort_order) VALUES (?, ?, 'test', NULL, ?)",
                (panel_id, int(test_id), sort_index),
            )
            sort_index += 1

    def _copy_asset(self, raw_path: str, stem: str) -> str:
        if not raw_path:
            return ""
        source = Path(raw_path)
        if not source.exists():
            return raw_path
        target = self.assets_dir / f"{stem}{source.suffix.lower()}"
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return str(target)

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
        try:
            parsed = int(str(value))
        except (TypeError, ValueError):
            return fallback
        return max(minimum, min(maximum, parsed))

    def _copy_report_branding_asset(self, raw_path: str, kind: str) -> str:
        if not raw_path:
            return ""
        source = Path(raw_path)
        if not source.exists():
            return raw_path
        normalized_stem = ''.join(char.lower() if char.isalnum() else '_' for char in source.stem).strip('_') or kind
        suffix = source.suffix.lower()
        target = self.assets_dir / f"report_{kind}_{normalized_stem}{suffix}"
        if source.resolve() == target.resolve():
            return str(target)
        counter = 2
        while target.exists():
            try:
                if source.read_bytes() == target.read_bytes():
                    return str(target)
            except OSError:
                pass
            target = self.assets_dir / f"report_{kind}_{normalized_stem}_{counter}{suffix}"
            counter += 1
        shutil.copy2(source, target)
        return str(target)

    @staticmethod
    def _normalize_report_branding_paths(raw_value: Any, fallback: str = "") -> list[str]:
        paths: list[str] = []
        if isinstance(raw_value, list):
            for item in raw_value:
                candidate = str(item or '').strip()
                if candidate and candidate not in paths:
                    paths.append(candidate)
        fallback_value = fallback.strip()
        if fallback_value and fallback_value not in paths:
            paths.insert(0, fallback_value)
        return paths

    @staticmethod
    def _normalize_instrument_key(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    @classmethod
    def _normalize_optional_instrument_key(cls, value: str) -> str | None:
        normalized = cls._normalize_instrument_key(value)
        return normalized or None

    @staticmethod
    def _normalize_instrument_code(value: str) -> str:
        return "".join(character for character in str(value or "").upper().strip() if character.isalnum() or character in {"-", "_", "%", "#"})

    def _get_or_create_category(self, connection: sqlite3.Connection, category_name: str) -> int | None:
        normalized = category_name.strip()
        if not normalized:
            return None
        row = connection.execute("SELECT id FROM test_categories WHERE name = ?", (normalized,)).fetchone()
        if row:
            return int(row["id"])
        cursor = connection.execute("INSERT INTO test_categories (name) VALUES (?)", (normalized,))
        return int(cursor.lastrowid)

    def _migrate_orders_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(orders)").fetchall()}
        if "client_id" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN client_id INTEGER REFERENCES clients(id)")
        if "accession_id" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN accession_id TEXT")
        if "sample_id" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN sample_id TEXT")
        if "is_preallocated" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN is_preallocated INTEGER NOT NULL DEFAULT 0")
        order_test_columns = {row["name"] for row in connection.execute("PRAGMA table_info(order_tests)").fetchall()}
        if "is_outsourced" not in order_test_columns:
            connection.execute("ALTER TABLE order_tests ADD COLUMN is_outsourced INTEGER NOT NULL DEFAULT 0")
        if "source_label" not in order_test_columns:
            connection.execute("ALTER TABLE order_tests ADD COLUMN source_label TEXT")

    def _migrate_reports_table(self, connection: sqlite3.Connection) -> None:
        report_item_columns = {row["name"] for row in connection.execute("PRAGMA table_info(report_items)").fetchall()}
        if "item_type_snapshot" not in report_item_columns:
            connection.execute("ALTER TABLE report_items ADD COLUMN item_type_snapshot TEXT NOT NULL DEFAULT 'test'")

    def _migrate_outsourced_panel_tables(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS outsourced_panel_tables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                panel_label TEXT NOT NULL,
                source_pdf_path TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (order_id, panel_label),
                FOREIGN KEY (order_id) REFERENCES orders(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS outsourced_panel_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                outsourced_panel_table_id INTEGER NOT NULL,
                row_index INTEGER NOT NULL,
                col_1 TEXT,
                col_2 TEXT,
                col_3 TEXT,
                col_4 TEXT,
                col_5 TEXT,
                FOREIGN KEY (outsourced_panel_table_id) REFERENCES outsourced_panel_tables(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS report_outsourced_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                panel_label TEXT NOT NULL,
                source_pdf_path TEXT NOT NULL,
                row_index INTEGER NOT NULL,
                col_1 TEXT,
                col_2 TEXT,
                col_3 TEXT,
                col_4 TEXT,
                col_5 TEXT,
                FOREIGN KEY (report_id) REFERENCES reports(id)
            )
            """
        )

    def _migrate_instrument_result_mappings_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS instrument_result_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_profile TEXT NOT NULL,
                device_id TEXT,
                raw_code TEXT NOT NULL,
                raw_name TEXT,
                specimen_type TEXT,
                panel_hint TEXT,
                test_id INTEGER NOT NULL,
                unit_override TEXT,
                reference_range_override TEXT,
                value_slice_start INTEGER,
                value_slice_end INTEGER,
                value_multiplier REAL,
                value_formula TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (test_id) REFERENCES tests(id),
                UNIQUE (
                    instrument_profile,
                    device_id,
                    raw_code,
                    specimen_type,
                    panel_hint
                )
            )
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(instrument_result_mappings)").fetchall()}
        if "value_slice_start" not in columns:
            connection.execute("ALTER TABLE instrument_result_mappings ADD COLUMN value_slice_start INTEGER")
        if "value_slice_end" not in columns:
            connection.execute("ALTER TABLE instrument_result_mappings ADD COLUMN value_slice_end INTEGER")
        if "value_multiplier" not in columns:
            connection.execute("ALTER TABLE instrument_result_mappings ADD COLUMN value_multiplier REAL")
        if "decimal_places" not in columns:
            connection.execute("ALTER TABLE instrument_result_mappings ADD COLUMN decimal_places INTEGER")
        if "value_formula" not in columns:
            connection.execute("ALTER TABLE instrument_result_mappings ADD COLUMN value_formula TEXT")

    def _get_report_context(self, order_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT o.id AS order_id,
                       o.order_number,
                       o.accession_id,
                       o.sample_id,
                       o.ordered_at,
                       o.reported_at,
                       o.status AS order_status,
                       o.notes,
                       TRIM(p.first_name || ' ' || p.last_name || CASE WHEN p.middle_name IS NOT NULL AND p.middle_name != '' THEN ' ' || p.middle_name ELSE '' END) AS patient_name,
                       p.sex AS patient_sex,
                       p.date_of_birth AS patient_dob,
                       p.age_value AS patient_age_value,
                       p.age_unit AS patient_age_unit,
                       d.full_name AS doctor_name,
                       c.name AS client_name
                FROM orders o
                INNER JOIN patients p ON p.id = o.patient_id
                LEFT JOIN doctors d ON d.id = o.doctor_id
                LEFT JOIN clients c ON c.id = o.client_id
                WHERE o.id = ?
                """,
                (order_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def _resolve_report_item_order_test_id(self, connection: sqlite3.Connection, order_id: int, item: dict[str, Any]) -> int:
        item_type = str(item.get("item_type") or "test")
        if item_type in {"heading", "comment", "panel_meta"} or not item.get("order_test_id"):
            return self._ensure_report_placeholder_order_test(connection, order_id, item_type, str(item.get("test_name") or ""), int(item.get("sort_order") or 0))
        return self._resolve_report_order_test_id(connection, order_id, int(item.get("sort_order") or 0))

    def _ensure_report_placeholder_order_test(self, connection: sqlite3.Connection, order_id: int, item_type: str, label: str, sort_order: int) -> int:
        test_id = self._ensure_panel_heading_test(connection) if item_type == "heading" else self._ensure_panel_comment_test(connection)
        row = connection.execute(
            "SELECT id FROM order_tests WHERE order_id = ? AND test_id = ? ORDER BY id LIMIT 1",
            (order_id, test_id),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        cursor = connection.execute(
            "INSERT INTO order_tests (order_id, test_id, status, is_outsourced, source_label, display_name, sort_order) VALUES (?, ?, 'pending', 0, NULL, ?, ?)",
            (order_id, test_id, label.strip() or item_type.title(), sort_order),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _resolve_report_order_test_id(connection: sqlite3.Connection, order_id: int, sort_order: int) -> int:
        row = connection.execute(
            "SELECT id FROM order_tests WHERE order_id = ? ORDER BY sort_order, id LIMIT 1 OFFSET ?",
            (order_id, sort_order),
        ).fetchone()
        if row is None:
            raise sqlite3.IntegrityError("Could not resolve report item order.")
        return int(row["id"])

    def _get_outsourced_order_test_ids(self, order_id: int) -> set[int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM order_tests
                WHERE order_id = ?
                  AND COALESCE(is_outsourced, 0) = 1
                """,
                (order_id,),
            ).fetchall()
        return {int(row["id"]) for row in rows}

    def _migrate_patients_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(patients)").fetchall()}
        if "age_value" not in columns:
            connection.execute("ALTER TABLE patients ADD COLUMN age_value INTEGER")
        if "age_unit" not in columns:
            connection.execute("ALTER TABLE patients ADD COLUMN age_unit TEXT CHECK (age_unit IN ('days', 'months', 'years'))")
        if "is_active" not in columns:
            connection.execute("ALTER TABLE patients ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

    def _migrate_clients_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(clients)").fetchall()}
        if "tax_id" not in columns:
            connection.execute("ALTER TABLE clients ADD COLUMN tax_id TEXT")
        if "fiscal_regime" not in columns:
            connection.execute("ALTER TABLE clients ADD COLUMN fiscal_regime TEXT")
        if "postal_code" not in columns:
            connection.execute("ALTER TABLE clients ADD COLUMN postal_code TEXT")
        if "cfdi_use" not in columns:
            connection.execute("ALTER TABLE clients ADD COLUMN cfdi_use TEXT")
        if "is_active" not in columns:
            connection.execute("ALTER TABLE clients ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

    def _migrate_doctors_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(doctors)").fetchall()}
        if "is_active" not in columns:
            connection.execute("ALTER TABLE doctors ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

    def _migrate_inventory_items_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(inventory_items)").fetchall()}
        if not columns:
            return
        if "unit_cost" not in columns:
            connection.execute("ALTER TABLE inventory_items ADD COLUMN unit_cost REAL NOT NULL DEFAULT 0")

    def _migrate_invoices_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(invoices)").fetchall()}
        if not columns:
            return
        if "cfdi_use" not in columns:
            connection.execute("ALTER TABLE invoices ADD COLUMN cfdi_use TEXT")
        if "payment_form" not in columns:
            connection.execute("ALTER TABLE invoices ADD COLUMN payment_form TEXT")
        if "payment_method" not in columns:
            connection.execute("ALTER TABLE invoices ADD COLUMN payment_method TEXT")
        if "currency" not in columns:
            connection.execute("ALTER TABLE invoices ADD COLUMN currency TEXT NOT NULL DEFAULT 'MXN'")
        if "xml_path" not in columns:
            connection.execute("ALTER TABLE invoices ADD COLUMN xml_path TEXT")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invoice_order_links (
                invoice_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL UNIQUE,
                PRIMARY KEY (invoice_id, order_id),
                FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_number TEXT NOT NULL UNIQUE,
                order_id INTEGER NOT NULL UNIQUE,
                receipt_date DATE NOT NULL,
                total_amount REAL NOT NULL DEFAULT 0,
                notes TEXT,
                payment_form TEXT,
                payment_method TEXT,
                currency TEXT NOT NULL DEFAULT 'MXN',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            )
            """
        )

    def _migrate_suppliers_table(self, connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, phone TEXT, email TEXT, tax_id TEXT, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        connection.execute("CREATE TABLE IF NOT EXISTS inventory_movements (id INTEGER PRIMARY KEY AUTOINCREMENT, inventory_item_id INTEGER NOT NULL, supplier_id INTEGER, movement_type TEXT NOT NULL CHECK (movement_type IN ('purchase', 'adjustment_in', 'adjustment_out', 'consumption')), quantity REAL NOT NULL, unit_cost REAL NOT NULL DEFAULT 0, movement_date DATE NOT NULL, notes TEXT, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (inventory_item_id) REFERENCES inventory_items(id), FOREIGN KEY (supplier_id) REFERENCES suppliers(id))")

    def _migrate_lab_settings_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(lab_settings)").fetchall()}
        if "ui_language" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN ui_language TEXT NOT NULL DEFAULT 'es'")
        connection.execute("UPDATE lab_settings SET ui_language = 'es' WHERE ui_language IS NULL OR ui_language = '' OR ui_language = 'en'")
        if "ui_state" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN ui_state TEXT NOT NULL DEFAULT '{}'")
        if "sat_rfc" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN sat_rfc TEXT NOT NULL DEFAULT ''")
        if "sat_fiscal_regime" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN sat_fiscal_regime TEXT NOT NULL DEFAULT ''")
        if "sat_postal_code" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN sat_postal_code TEXT NOT NULL DEFAULT ''")
        if "sat_certificate_path" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN sat_certificate_path TEXT NOT NULL DEFAULT ''")
        if "sat_key_path" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN sat_key_path TEXT NOT NULL DEFAULT ''")
        if "report_flag_style" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_flag_style TEXT NOT NULL DEFAULT 'arrows'")
        if "keep_panels_together" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN keep_panels_together INTEGER NOT NULL DEFAULT 0")
        if "report_font_family" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_font_family TEXT NOT NULL DEFAULT 'Segoe UI'")
        if "report_font_size" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_font_size INTEGER NOT NULL DEFAULT 12")
        if "report_font_bold" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_font_bold INTEGER NOT NULL DEFAULT 0")
        if "report_abnormal_bold" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_abnormal_bold INTEGER NOT NULL DEFAULT 0")
        if "report_subheading_font_family" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_subheading_font_family TEXT NOT NULL DEFAULT 'Segoe UI'")
        if "report_subheading_font_size" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_subheading_font_size INTEGER NOT NULL DEFAULT 13")
        if "report_subheading_font_bold" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_subheading_font_bold INTEGER NOT NULL DEFAULT 1")
        if "report_footer_gap_mm" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_footer_gap_mm INTEGER NOT NULL DEFAULT 8")
        if "report_sex_format" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_sex_format TEXT NOT NULL DEFAULT 'short'")
        if "report_date_format" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_date_format TEXT NOT NULL DEFAULT 'auto'")
        if "report_show_doctor" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_show_doctor INTEGER NOT NULL DEFAULT 1")
        if "report_show_client" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_show_client INTEGER NOT NULL DEFAULT 1")
        if "report_show_sex" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_show_sex INTEGER NOT NULL DEFAULT 1")
        if "report_show_age" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_show_age INTEGER NOT NULL DEFAULT 1")
        if "report_show_dob" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_show_dob INTEGER NOT NULL DEFAULT 1")
        if "report_show_ordered_at" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_show_ordered_at INTEGER NOT NULL DEFAULT 1")
        if "report_show_reported_at" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_show_reported_at INTEGER NOT NULL DEFAULT 1")
        if "report_doctor_col" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_doctor_col TEXT NOT NULL DEFAULT 'left'")
        if "report_client_col" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_client_col TEXT NOT NULL DEFAULT 'left'")
        if "report_sex_col" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_sex_col TEXT NOT NULL DEFAULT 'left'")
        if "report_age_col" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_age_col TEXT NOT NULL DEFAULT 'right'")
        if "report_dob_col" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_dob_col TEXT NOT NULL DEFAULT 'right'")
        if "report_ordered_at_col" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_ordered_at_col TEXT NOT NULL DEFAULT 'right'")
        if "report_reported_at_col" not in columns:
            connection.execute("ALTER TABLE lab_settings ADD COLUMN report_reported_at_col TEXT NOT NULL DEFAULT 'right'")

    def _migrate_tests_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(tests)").fetchall()}
        if "select_options" not in columns:
            connection.execute("ALTER TABLE tests ADD COLUMN select_options TEXT")
        if "default_result_value" not in columns:
            connection.execute("ALTER TABLE tests ADD COLUMN default_result_value TEXT")
        if "price" not in columns:
            connection.execute("ALTER TABLE tests ADD COLUMN price REAL NOT NULL DEFAULT 0")
        if "result_multiplier" not in columns:
            connection.execute("ALTER TABLE tests ADD COLUMN result_multiplier REAL")

    def _migrate_client_test_prices_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_test_prices (
                client_id INTEGER NOT NULL,
                test_id INTEGER NOT NULL,
                price REAL NOT NULL,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (client_id, test_id),
                FOREIGN KEY (client_id) REFERENCES clients(id),
                FOREIGN KEY (test_id) REFERENCES tests(id)
            )
            """
        )

    def _migrate_precision_text_columns(self, connection: sqlite3.Connection) -> None:
        reference_columns = {row["name"] for row in connection.execute("PRAGMA table_info(test_reference_ranges)").fetchall()}
        if "lower_value_text" not in reference_columns:
            connection.execute("ALTER TABLE test_reference_ranges ADD COLUMN lower_value_text TEXT")
            connection.execute("UPDATE test_reference_ranges SET lower_value_text = CAST(lower_value AS TEXT) WHERE lower_value IS NOT NULL AND (lower_value_text IS NULL OR lower_value_text = '')")
        if "upper_value_text" not in reference_columns:
            connection.execute("ALTER TABLE test_reference_ranges ADD COLUMN upper_value_text TEXT")
            connection.execute("UPDATE test_reference_ranges SET upper_value_text = CAST(upper_value AS TEXT) WHERE upper_value IS NOT NULL AND (upper_value_text IS NULL OR upper_value_text = '')")
        result_columns = {row["name"] for row in connection.execute("PRAGMA table_info(results)").fetchall()}
        if "lower_value_text" not in result_columns:
            connection.execute("ALTER TABLE results ADD COLUMN lower_value_text TEXT")
            connection.execute("UPDATE results SET lower_value_text = CAST(lower_value AS TEXT) WHERE lower_value IS NOT NULL AND (lower_value_text IS NULL OR lower_value_text = '')")
        if "upper_value_text" not in result_columns:
            connection.execute("ALTER TABLE results ADD COLUMN upper_value_text TEXT")
            connection.execute("UPDATE results SET upper_value_text = CAST(upper_value AS TEXT) WHERE upper_value IS NOT NULL AND (upper_value_text IS NULL OR upper_value_text = '')")
        report_item_columns = {row["name"] for row in connection.execute("PRAGMA table_info(report_items)").fetchall()}
        if "lower_value_snapshot_text" not in report_item_columns:
            connection.execute("ALTER TABLE report_items ADD COLUMN lower_value_snapshot_text TEXT")
            connection.execute("UPDATE report_items SET lower_value_snapshot_text = CAST(lower_value_snapshot AS TEXT) WHERE lower_value_snapshot IS NOT NULL AND (lower_value_snapshot_text IS NULL OR lower_value_snapshot_text = '')")
        if "upper_value_snapshot_text" not in report_item_columns:
            connection.execute("ALTER TABLE report_items ADD COLUMN upper_value_snapshot_text TEXT")
            connection.execute("UPDATE report_items SET upper_value_snapshot_text = CAST(upper_value_snapshot AS TEXT) WHERE upper_value_snapshot IS NOT NULL AND (upper_value_snapshot_text IS NULL OR upper_value_snapshot_text = '')")

    def _migrate_test_panels_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(test_panels)").fetchall()}
        if "specimen_type" not in columns:
            connection.execute("ALTER TABLE test_panels ADD COLUMN specimen_type TEXT")
        if "method" not in columns:
            connection.execute("ALTER TABLE test_panels ADD COLUMN method TEXT")
        columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(test_panels)").fetchall()}
        if "is_active" not in columns:
            connection.execute("ALTER TABLE test_panels ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        index_rows = connection.execute("PRAGMA index_list(test_panels)").fetchall()
        name_is_unique = False
        for index_row in index_rows:
            if not index_row["unique"]:
                continue
            index_name = index_row["name"]
            index_columns = [info_row["name"] for info_row in connection.execute(f"PRAGMA index_info('{index_name}')").fetchall()]
            if index_columns == ["name"]:
                name_is_unique = True
                break
        if not name_is_unique:
            return
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("ALTER TABLE test_panels RENAME TO test_panels_legacy")
        connection.execute(
            """
            CREATE TABLE test_panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                specimen_type TEXT,
                method TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO test_panels (id, code, name, specimen_type, method, is_active, created_at)
            SELECT id, code, name, specimen_type, method, COALESCE(is_active, 1), created_at
            FROM test_panels_legacy
            """
        )
        connection.execute("ALTER TABLE test_panel_items RENAME TO test_panel_items_legacy")
        connection.execute(
            """
            CREATE TABLE test_panel_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                panel_id INTEGER NOT NULL,
                test_id INTEGER,
                item_type TEXT NOT NULL DEFAULT 'test' CHECK (item_type IN ('test', 'heading', 'comment')),
                heading_text TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (panel_id) REFERENCES test_panels(id) ON DELETE CASCADE,
                FOREIGN KEY (test_id) REFERENCES tests(id)
            )
            """
        )
        legacy_item_columns = {row["name"] for row in connection.execute("PRAGMA table_info(test_panel_items_legacy)").fetchall()}
        if {"item_type", "heading_text"}.issubset(legacy_item_columns):
            connection.execute(
                """
                INSERT INTO test_panel_items (id, panel_id, test_id, item_type, heading_text, sort_order)
                SELECT
                    id,
                    panel_id,
                    test_id,
                    CASE WHEN item_type IN ('test', 'heading', 'comment') THEN item_type ELSE 'test' END,
                    heading_text,
                    sort_order
                FROM test_panel_items_legacy
                """
            )
        else:
            connection.execute(
                """
                INSERT INTO test_panel_items (id, panel_id, test_id, item_type, heading_text, sort_order)
                SELECT id, panel_id, test_id, 'test', NULL, sort_order
                FROM test_panel_items_legacy
                """
            )
        connection.execute("DROP TABLE test_panel_items_legacy")
        connection.execute("DROP TABLE test_panels_legacy")
        connection.execute("PRAGMA foreign_keys = ON")

    def _migrate_test_panel_items_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"]: dict(row) for row in connection.execute("PRAGMA table_info(test_panel_items)").fetchall()}
        table_sql_row = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'test_panel_items'").fetchone()
        table_sql = (table_sql_row["sql"] if table_sql_row is not None and table_sql_row["sql"] else "") if columns else ""
        needs_rebuild = (
            not columns
            or "item_type" not in columns
            or "heading_text" not in columns
            or columns.get("test_id", {}).get("notnull") == 1
            or "'comment'" not in table_sql
        )
        if not needs_rebuild:
            return
        connection.execute("ALTER TABLE test_panel_items RENAME TO test_panel_items_legacy")
        connection.execute("CREATE TABLE test_panel_items (id INTEGER PRIMARY KEY AUTOINCREMENT, panel_id INTEGER NOT NULL, test_id INTEGER, item_type TEXT NOT NULL DEFAULT 'test' CHECK (item_type IN ('test', 'heading', 'comment')), heading_text TEXT, sort_order INTEGER NOT NULL DEFAULT 0, FOREIGN KEY (panel_id) REFERENCES test_panels(id) ON DELETE CASCADE, FOREIGN KEY (test_id) REFERENCES tests(id))")
        if columns:
            legacy_columns = {row["name"] for row in connection.execute("PRAGMA table_info(test_panel_items_legacy)").fetchall()}
            if {"item_type", "heading_text"}.issubset(legacy_columns):
                connection.execute("INSERT INTO test_panel_items (id, panel_id, test_id, item_type, heading_text, sort_order) SELECT id, panel_id, test_id, CASE WHEN item_type IN ('test', 'heading', 'comment') THEN item_type ELSE 'test' END, heading_text, sort_order FROM test_panel_items_legacy")
            else:
                connection.execute("INSERT INTO test_panel_items (id, panel_id, test_id, item_type, heading_text, sort_order) SELECT id, panel_id, test_id, 'test', NULL, sort_order FROM test_panel_items_legacy")
        connection.execute("DROP TABLE test_panel_items_legacy")

    def _migrate_equipment_table(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(equipment)").fetchall()}
        if not columns:
            return
        if "notes" not in columns:
            connection.execute("ALTER TABLE equipment ADD COLUMN notes TEXT")

    def _migrate_instrument_order_match_config_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS instrument_order_match_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_profile TEXT NOT NULL UNIQUE,
                instrument_field TEXT NOT NULL DEFAULT 'sample_id',
                order_field TEXT NOT NULL DEFAULT 'sample_id',
                auto_import INTEGER NOT NULL DEFAULT 1,
                broadcast_enabled INTEGER NOT NULL DEFAULT 0,
                broadcast_protocol TEXT NOT NULL DEFAULT 'hl7_orm',
                broadcast_encoding TEXT NOT NULL DEFAULT 'ascii',
                broadcast_patient_id INTEGER NOT NULL DEFAULT 1,
                broadcast_patient_name INTEGER NOT NULL DEFAULT 1,
                broadcast_dob INTEGER NOT NULL DEFAULT 1,
                broadcast_age INTEGER NOT NULL DEFAULT 1,
                broadcast_sex INTEGER NOT NULL DEFAULT 1,
                broadcast_doctor INTEGER NOT NULL DEFAULT 1,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(instrument_order_match_config)").fetchall()}
        if "auto_import" not in columns:
            connection.execute("ALTER TABLE instrument_order_match_config ADD COLUMN auto_import INTEGER NOT NULL DEFAULT 1")
        if "broadcast_enabled" not in columns:
            connection.execute("ALTER TABLE instrument_order_match_config ADD COLUMN broadcast_enabled INTEGER NOT NULL DEFAULT 0")
        if "broadcast_protocol" not in columns:
            if "broadcast_language" in columns:
                connection.execute("ALTER TABLE instrument_order_match_config RENAME COLUMN broadcast_language TO broadcast_protocol")
                connection.execute("UPDATE instrument_order_match_config SET broadcast_protocol = 'hl7_orm' WHERE broadcast_protocol IN ('es', 'en', '')")
            else:
                connection.execute("ALTER TABLE instrument_order_match_config ADD COLUMN broadcast_protocol TEXT NOT NULL DEFAULT 'hl7_orm'")
        if "broadcast_encoding" not in columns:
            connection.execute("ALTER TABLE instrument_order_match_config ADD COLUMN broadcast_encoding TEXT NOT NULL DEFAULT 'ascii'")
        if "broadcast_patient_id" not in columns:
            connection.execute("ALTER TABLE instrument_order_match_config ADD COLUMN broadcast_patient_id INTEGER NOT NULL DEFAULT 1")
        if "broadcast_patient_name" not in columns:
            connection.execute("ALTER TABLE instrument_order_match_config ADD COLUMN broadcast_patient_name INTEGER NOT NULL DEFAULT 1")
        if "broadcast_dob" not in columns:
            connection.execute("ALTER TABLE instrument_order_match_config ADD COLUMN broadcast_dob INTEGER NOT NULL DEFAULT 1")
        if "broadcast_sex" not in columns:
            connection.execute("ALTER TABLE instrument_order_match_config ADD COLUMN broadcast_sex INTEGER NOT NULL DEFAULT 1")
        if "broadcast_age" not in columns:
            connection.execute("ALTER TABLE instrument_order_match_config ADD COLUMN broadcast_age INTEGER NOT NULL DEFAULT 1")
        if "broadcast_doctor" not in columns:
            connection.execute("ALTER TABLE instrument_order_match_config ADD COLUMN broadcast_doctor INTEGER NOT NULL DEFAULT 1")

    def _migrate_instrument_captures_cache_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS instrument_captures_cache (
                capture_id TEXT PRIMARY KEY,
                received_at TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                cached_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                has_data INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(instrument_captures_cache)").fetchall()}
        if "has_data" not in columns:
            connection.execute("ALTER TABLE instrument_captures_cache ADD COLUMN has_data INTEGER NOT NULL DEFAULT 0")
            rows = connection.execute("SELECT capture_id, payload_json FROM instrument_captures_cache").fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                    if isinstance(payload, dict) and self._payload_has_data(payload):
                        connection.execute("UPDATE instrument_captures_cache SET has_data = 1 WHERE capture_id = ?", (row["capture_id"],))
                except Exception:
                    pass

    @staticmethod
    def _specimen_code(specimen_type: str) -> str:
        normalized = ''.join(character for character in specimen_type.upper() if character.isalnum() or character == ' ')
        mapping = {
            'SERUM': 'SER',
            'PLASMA': 'PLA',
            'WHOLE BLOOD': 'WBL',
            'BLOOD': 'BLD',
            'URINE': 'URI',
            'SWAB': 'SWB',
            'STOOL': 'STL',
        }
        if normalized in mapping:
            return mapping[normalized]
        parts = [part for part in normalized.split() if part]
        if not parts:
            return 'SPC'
        if len(parts) == 1:
            return parts[0][:3]
        return ''.join(part[0] for part in parts)[:4]

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        normalized = str(value).strip().replace(",", "")
        if not normalized:
            return None
        try:
            return Decimal(normalized)
        except InvalidOperation:
            return None

    @classmethod
    def _decimal_to_float(cls, value: Any) -> float | None:
        decimal_value = cls._to_decimal(value)
        return float(decimal_value) if decimal_value is not None else None

    @staticmethod
    def _normalize_optional_text(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _serialize_select_options(options: Any) -> str | None:
        if isinstance(options, str):
            try:
                parsed = json.loads(options)
            except json.JSONDecodeError:
                parsed = [line.strip() for line in options.splitlines() if line.strip()]
            else:
                options = parsed
        if not isinstance(options, list):
            return None
        normalized = [str(option).strip() for option in options if str(option).strip()]
        return json.dumps(normalized, ensure_ascii=True) if normalized else None

    @staticmethod
    def deserialize_select_options(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return [line.strip() for line in raw_value.splitlines() if line.strip()]
        if not isinstance(parsed, list):
            return []
        return [str(option).strip() for option in parsed if str(option).strip()]

    def _ensure_panel_heading_test(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT id FROM tests WHERE code = '__PANEL_HEADING__'").fetchone()
        if row is not None:
            return int(row["id"])
        cursor = connection.execute("INSERT INTO tests (code, name, category_id, specimen_type, method, result_kind, is_active, sort_order) VALUES ('__PANEL_HEADING__', 'Panel Heading', NULL, NULL, NULL, 'text', 0, 0)")
        return int(cursor.lastrowid)

    def _ensure_panel_comment_test(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT id FROM tests WHERE code = '__PANEL_COMMENT__'").fetchone()
        if row is not None:
            return int(row["id"])
        cursor = connection.execute("INSERT INTO tests (code, name, category_id, specimen_type, method, result_kind, is_active, sort_order) VALUES ('__PANEL_COMMENT__', 'Panel Comment', NULL, NULL, NULL, 'text', 0, 0)")
        return int(cursor.lastrowid)

    def _ensure_urinalysis_strip_tests(self, connection: sqlite3.Connection) -> None:
        category_id = self._get_or_create_category(connection, "Urinalysis")
        for code, name, _category, specimen_type, method, result_kind, unit in self.URINALYSIS_STRIP_TESTS:
            row = connection.execute("SELECT id FROM tests WHERE code = ?", (code,)).fetchone()
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO tests (
                        code, name, category_id, specimen_type, method, result_kind,
                        select_options, default_result_value, price, is_active
                    )
                    VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0, 1)
                    """,
                    (code, name, category_id, specimen_type, method, result_kind),
                )
                test_id = int(cursor.lastrowid)
            else:
                test_id = int(row["id"])
                connection.execute(
                    """
                    UPDATE tests
                    SET category_id = COALESCE(category_id, ?),
                        specimen_type = COALESCE(NULLIF(specimen_type, ''), ?),
                        method = COALESCE(NULLIF(method, ''), ?),
                        result_kind = CASE WHEN result_kind IN ('numeric', 'text', 'select') THEN result_kind ELSE ? END,
                        is_active = 1
                    WHERE id = ?
                    """,
                    (category_id, specimen_type, method, result_kind, test_id),
                )
            if unit:
                existing_range = connection.execute(
                    "SELECT id FROM test_reference_ranges WHERE test_id = ? AND unit = ?",
                    (test_id, unit),
                ).fetchone()
                if existing_range is None:
                    connection.execute(
                        """
                        INSERT INTO test_reference_ranges (
                            test_id, sex, age_min_days, age_max_days,
                            lower_value, upper_value, lower_value_text,
                            upper_value_text, unit, reference_text
                        )
                        VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, '')
                        """,
                        (test_id, unit),
                    )

    def _resolve_reference_range(self, connection: sqlite3.Connection, test_id: int, patient_sex: str | None, patient_age_days: int | None) -> sqlite3.Row | None:
        rows = connection.execute("SELECT sex, age_min_days, age_max_days, COALESCE(lower_value_text, CAST(lower_value AS TEXT)) AS lower_value, COALESCE(upper_value_text, CAST(upper_value AS TEXT)) AS upper_value, unit, reference_text FROM test_reference_ranges WHERE test_id = ? ORDER BY CASE WHEN sex IS NULL OR sex = '' THEN 1 ELSE 0 END, CASE WHEN age_min_days IS NULL THEN 1 ELSE 0 END, age_min_days, CASE WHEN age_max_days IS NULL THEN 1 ELSE 0 END, age_max_days", (test_id,)).fetchall()
        for row in rows:
            sex = row["sex"]
            if sex and patient_sex and sex != patient_sex:
                continue
            if sex and not patient_sex:
                continue
            min_days = row["age_min_days"]
            max_days = row["age_max_days"]
            if patient_age_days is not None:
                if min_days is not None and patient_age_days < min_days:
                    continue
                if max_days is not None and patient_age_days > max_days:
                    continue
            return row
        return None

    @staticmethod
    def _resolve_age_days(date_of_birth: str | None, age_value: int | None, age_unit: str | None) -> int | None:
        if date_of_birth:
            try:
                dob = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
                return max((date.today() - dob).days, 0)
            except ValueError:
                return None
        if age_value is None or not age_unit:
            return None
        if age_unit == "days":
            return age_value
        if age_unit == "months":
            return age_value * 30
        if age_unit == "years":
            return age_value * 365
        return None

    @staticmethod
    def _calculate_flag(result_kind: str, result_value: str, lower_value: str | None, upper_value: str | None) -> str:
        if result_kind != "numeric" or not result_value:
            return "none"
        numeric_value = Database._to_decimal(result_value)
        if numeric_value is None:
            return "none"
        lower_decimal = Database._to_decimal(lower_value)
        upper_decimal = Database._to_decimal(upper_value)
        if lower_decimal is not None and numeric_value < lower_decimal:
            return "low"
        if upper_decimal is not None and numeric_value > upper_decimal:
            return "high"
        if lower_decimal is not None or upper_decimal is not None:
            return "normal"
        return "none"

    @staticmethod
    def _format_patient_label(first_name: str, last_name: str, middle_name: str | None, age_value: int | None, age_unit: str | None) -> str:
        full_name = " ".join(part for part in [first_name, last_name, middle_name or ""] if part).strip()
        age_part = f' - {age_value} {age_unit}' if age_value is not None and age_unit else ''
        return f'{full_name}{age_part}'

