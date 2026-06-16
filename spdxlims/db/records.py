from __future__ import annotations
from dataclasses import dataclass
from typing import Any


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
