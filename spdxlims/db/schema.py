from __future__ import annotations
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


class SchemaMixin:
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
                    auto_invoice_enabled INTEGER NOT NULL DEFAULT 0,
                    auto_invoice_frequency TEXT,
                    auto_invoice_last_run TEXT,
                    header_image_path TEXT,
                    footer_signature_image_path TEXT,
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
                    result_kind TEXT NOT NULL CHECK (result_kind IN ('numeric', 'text', 'select', 'image')),
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
                    price REAL NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS client_panel_prices (
                    client_id INTEGER NOT NULL,
                    panel_id INTEGER NOT NULL,
                    price REAL NOT NULL,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (client_id, panel_id),
                    FOREIGN KEY (client_id) REFERENCES clients(id),
                    FOREIGN KEY (panel_id) REFERENCES test_panels(id)
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
                    is_archived INTEGER NOT NULL DEFAULT 0,
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

                CREATE TABLE IF NOT EXISTS result_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_test_id INTEGER NOT NULL,
                    image_data BLOB NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'image/png',
                    caption TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (order_test_id) REFERENCES order_tests(id)
                );

                CREATE TABLE IF NOT EXISTS report_item_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id INTEGER NOT NULL,
                    order_test_id INTEGER NOT NULL,
                    image_data BLOB NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'image/png',
                    caption TEXT,
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

                CREATE TABLE IF NOT EXISTS outsourced_panel_extractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    outsourced_panel_table_id INTEGER NOT NULL,
                    source_pdf_path TEXT NOT NULL DEFAULT '',
                    page_label TEXT NOT NULL DEFAULT '',
                    row_count INTEGER NOT NULL DEFAULT 0,
                    extracted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (outsourced_panel_table_id) REFERENCES outsourced_panel_tables(id)
                );

                CREATE TABLE IF NOT EXISTS outsourced_panel_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    outsourced_panel_table_id INTEGER NOT NULL,
                    extraction_id INTEGER,
                    row_index INTEGER NOT NULL,
                    col_1 TEXT,
                    col_2 TEXT,
                    col_3 TEXT,
                    col_4 TEXT,
                    col_5 TEXT,
                    FOREIGN KEY (outsourced_panel_table_id) REFERENCES outsourced_panel_tables(id),
                    FOREIGN KEY (extraction_id) REFERENCES outsourced_panel_extractions(id)
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
            self._migrate_tests_result_kind_image(connection)
            self._repair_tests_legacy_references(connection)
            self._migrate_result_images_tables(connection)
            self._migrate_client_test_prices_table(connection)
            self._migrate_client_panel_prices_table(connection)
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
                       c.name AS client_name,
                       c.header_image_path AS client_header_image_path,
                       c.footer_signature_image_path AS client_footer_signature_image_path
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
        if "is_archived" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
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
            CREATE TABLE IF NOT EXISTS outsourced_panel_extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                outsourced_panel_table_id INTEGER NOT NULL,
                source_pdf_path TEXT NOT NULL DEFAULT '',
                page_label TEXT NOT NULL DEFAULT '',
                row_count INTEGER NOT NULL DEFAULT 0,
                extracted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (outsourced_panel_table_id) REFERENCES outsourced_panel_tables(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS outsourced_panel_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                outsourced_panel_table_id INTEGER NOT NULL,
                extraction_id INTEGER,
                row_index INTEGER NOT NULL,
                col_1 TEXT,
                col_2 TEXT,
                col_3 TEXT,
                col_4 TEXT,
                col_5 TEXT,
                FOREIGN KEY (outsourced_panel_table_id) REFERENCES outsourced_panel_tables(id),
                FOREIGN KEY (extraction_id) REFERENCES outsourced_panel_extractions(id)
            )
            """
        )
        try:
            connection.execute("ALTER TABLE outsourced_panel_rows ADD COLUMN extraction_id INTEGER")
        except Exception:  # noqa: BLE001
            pass
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
        if "auto_invoice_enabled" not in columns:
            connection.execute("ALTER TABLE clients ADD COLUMN auto_invoice_enabled INTEGER NOT NULL DEFAULT 0")
        if "auto_invoice_frequency" not in columns:
            connection.execute("ALTER TABLE clients ADD COLUMN auto_invoice_frequency TEXT")
        if "auto_invoice_last_run" not in columns:
            connection.execute("ALTER TABLE clients ADD COLUMN auto_invoice_last_run TEXT")
        if "header_image_path" not in columns:
            connection.execute("ALTER TABLE clients ADD COLUMN header_image_path TEXT")
        if "footer_signature_image_path" not in columns:
            connection.execute("ALTER TABLE clients ADD COLUMN footer_signature_image_path TEXT")

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
        if "formula" not in columns:
            connection.execute("ALTER TABLE tests ADD COLUMN formula TEXT")

    def _migrate_tests_result_kind_image(self, connection: sqlite3.Connection) -> None:
        # SQLite cannot ALTER a CHECK constraint, so rebuild the tests table when
        # the existing constraint predates the 'image' result kind.
        table_sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'tests'"
        ).fetchone()
        table_sql = (table_sql_row["sql"] or "") if table_sql_row is not None else ""
        if not table_sql or "result_kind" not in table_sql:
            return
        if "'image'" in table_sql:
            return
        legacy_columns = [row["name"] for row in connection.execute("PRAGMA table_info(tests)").fetchall()]
        new_columns = [
            "id", "code", "name", "category_id", "specimen_type", "method",
            "result_kind", "select_options", "default_result_value", "price",
            "result_multiplier", "is_active", "sort_order", "formula",
        ]
        shared_columns = [column for column in new_columns if column in legacy_columns]
        column_list = ", ".join(shared_columns)
        # Rebuild via a temp table that is renamed INTO place, per the official
        # SQLite procedure. Renaming the live `tests` table out of the way would
        # make SQLite rewrite every child table's FK to point at the temp name;
        # dropping the temp table then leaves those children with dangling
        # references. Creating the replacement first and renaming it last keeps
        # the children's `REFERENCES tests(id)` valid throughout.
        #
        # `PRAGMA foreign_keys` is ignored while a transaction is open, and
        # earlier migrations have already opened one, so commit before toggling.
        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE IF EXISTS tests_new")
        connection.execute(
            """
            CREATE TABLE tests_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category_id INTEGER,
                specimen_type TEXT,
                method TEXT,
                result_kind TEXT NOT NULL CHECK (result_kind IN ('numeric', 'text', 'select', 'image')),
                select_options TEXT,
                default_result_value TEXT,
                price REAL NOT NULL DEFAULT 0,
                result_multiplier REAL,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                formula TEXT,
                FOREIGN KEY (category_id) REFERENCES test_categories(id)
            )
            """
        )
        connection.execute(
            f"INSERT INTO tests_new ({column_list}) SELECT {column_list} FROM tests"
        )
        connection.execute("DROP TABLE tests")
        connection.execute("ALTER TABLE tests_new RENAME TO tests")
        # Commit the rebuild while enforcement is still off, then restore it for
        # the remaining migrations (pragma changes are ignored mid-transaction).
        connection.commit()
        connection.execute("PRAGMA foreign_keys = ON")

    def _repair_tests_legacy_references(self, connection: sqlite3.Connection) -> None:
        # Earlier builds rebuilt the `tests` table by renaming it to
        # `tests_legacy` and dropping it, which left child tables' foreign keys
        # pointing at the now-missing `tests_legacy`. Any INSERT into those
        # children (e.g. saving an order) then fails. Rewrite the stored DDL so
        # those references point back at `tests`.
        broken = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND sql LIKE '%tests_legacy%'"
        ).fetchall()
        if not broken:
            return
        connection.commit()
        connection.execute("PRAGMA writable_schema = ON")
        connection.execute(
            "UPDATE sqlite_master "
            "SET sql = replace(sql, 'tests_legacy', 'tests') "
            "WHERE type = 'table' AND sql LIKE '%tests_legacy%'"
        )
        connection.execute("PRAGMA writable_schema = RESET")
        connection.commit()

    def _migrate_result_images_tables(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS result_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_test_id INTEGER NOT NULL,
                image_data BLOB NOT NULL,
                mime_type TEXT NOT NULL DEFAULT 'image/png',
                caption TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_test_id) REFERENCES order_tests(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS report_item_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                order_test_id INTEGER NOT NULL,
                image_data BLOB NOT NULL,
                mime_type TEXT NOT NULL DEFAULT 'image/png',
                caption TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (report_id) REFERENCES reports(id),
                FOREIGN KEY (order_test_id) REFERENCES order_tests(id)
            )
            """
        )

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

    def _migrate_client_panel_prices_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS client_panel_prices (
                client_id INTEGER NOT NULL,
                panel_id INTEGER NOT NULL,
                price REAL NOT NULL,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (client_id, panel_id),
                FOREIGN KEY (client_id) REFERENCES clients(id),
                FOREIGN KEY (panel_id) REFERENCES test_panels(id)
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
        if "price" not in columns:
            connection.execute("ALTER TABLE test_panels ADD COLUMN price REAL NOT NULL DEFAULT 0")
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
                price REAL NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            INSERT INTO test_panels (id, code, name, specimen_type, method, price, is_active, created_at)
            SELECT id, code, name, specimen_type, method, COALESCE(price, 0), COALESCE(is_active, 1), created_at
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
                    _log.warning("Failed to migrate instrument_captures_cache row %s", row["capture_id"], exc_info=True)
