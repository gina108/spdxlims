from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Patient(Base):
    __tablename__ = "patient"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mrn: Mapped[str | None] = mapped_column(String(64), unique=True)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(120))
    dob: Mapped[date | None] = mapped_column(Date)
    age_value: Mapped[int | None] = mapped_column(Integer)
    age_unit: Mapped[str | None] = mapped_column(String(16))
    sex: Mapped[str | None] = mapped_column(String(1))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TestCatalog(Base):
    __tablename__ = "test_catalog"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_name: Mapped[str | None] = mapped_column(String(255))
    specimen_type: Mapped[str | None] = mapped_column(String(80))
    method: Mapped[str | None] = mapped_column(String(120))
    result_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    select_options: Mapped[str | None] = mapped_column(Text)
    default_result_value: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    unit: Mapped[str | None] = mapped_column(String(32))
    formula: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TestReferenceRange(Base):
    __tablename__ = "test_reference_range"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("test_catalog.id", ondelete="CASCADE"), nullable=False)
    sex: Mapped[str | None] = mapped_column(String(1))
    age_min_days: Mapped[int | None] = mapped_column(Integer)
    age_max_days: Mapped[int | None] = mapped_column(Integer)
    lower_value_text: Mapped[str | None] = mapped_column(String(64))
    upper_value_text: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[str | None] = mapped_column(String(32))
    reference_text: Mapped[str | None] = mapped_column(Text)



class PanelCatalog(Base):
    __tablename__ = "panel_catalog"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PanelCatalogItem(Base):
    __tablename__ = "panel_catalog_item"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    panel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("panel_catalog.id", ondelete="CASCADE"), nullable=False)
    test_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("test_catalog.id"))
    item_type: Mapped[str] = mapped_column(String(16), nullable=False, default="test")
    heading_text: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Provider(Base):
    __tablename__ = "provider"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_type: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), unique=True)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    billing_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProviderPrice(Base):
    __tablename__ = "provider_price"
    __table_args__ = (UniqueConstraint("provider_id", "test_id", "effective_from", name="uq_provider_price"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("provider.id"), nullable=False)
    test_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("test_catalog.id"), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)


class LabProfile(Base):
    __tablename__ = "lab_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lab_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    logo_path: Mapped[str | None] = mapped_column(Text)
    header_image_path: Mapped[str | None] = mapped_column(Text)
    footer_signature_image_path: Mapped[str | None] = mapped_column(Text)
    report_footer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    director_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    director_license: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Report styling/layout preferences (fonts, flag style, shown columns, etc.).
    # Mirrors the desktop's get_report_layout_settings() dict so server-rendered
    # reports match the desktop exactly.
    report_settings: Mapped[dict | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class LabOrder(Base):
    __tablename__ = "lab_order"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patient.id"), nullable=False)
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("provider.id"))
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("provider.id"))
    accession_id: Mapped[str | None] = mapped_column(String(64))
    sample_id: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class OrderItem(Base):
    __tablename__ = "order_item"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lab_order.id", ondelete="CASCADE"), nullable=False)
    test_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("test_catalog.id"), nullable=False)
    group_label: Mapped[str | None] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="routine")
    # Outsourced (send-out) tests rendered from an external PDF rather than
    # in-house results. source_label groups them into their outsourced panel.
    is_outsourced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_label: Mapped[str | None] = mapped_column(String(255))


class Sample(Base):
    __tablename__ = "sample"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lab_order.id", ondelete="CASCADE"), nullable=False)
    barcode: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    specimen_type: Mapped[str] = mapped_column(String(80), nullable=False)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False)


class Result(Base):
    __tablename__ = "result"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_item.id", ondelete="CASCADE"), nullable=False)
    sample_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sample.id"))
    value_text: Mapped[str | None] = mapped_column(Text)
    value_num: Mapped[float | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String(32))
    lower_value_text: Mapped[str | None] = mapped_column(String(64))
    upper_value_text: Mapped[str | None] = mapped_column(String(64))
    reference_text: Mapped[str | None] = mapped_column(Text)
    comments: Mapped[str | None] = mapped_column(Text)
    flag: Mapped[str | None] = mapped_column(String(16))
    entered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"))
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)


class ResultImage(Base):
    __tablename__ = "result_image"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("order_item.id", ondelete="CASCADE"), nullable=False)
    image_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False, default="image/png")
    caption: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ReportItemImageSnapshot(Base):
    __tablename__ = "report_item_image_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("report_snapshot.id", ondelete="CASCADE"), nullable=False)
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("order_item.id"))
    image_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False, default="image/png")
    caption: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReportSnapshot(Base):
    __tablename__ = "report_snapshot"
    __table_args__ = (UniqueConstraint("order_id", name="uq_report_snapshot_order"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lab_order.id", ondelete="CASCADE"), nullable=False)
    report_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="final")
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    patient_snapshot_name: Mapped[str] = mapped_column(String(255), nullable=False)
    patient_snapshot_sex: Mapped[str | None] = mapped_column(String(16))
    patient_snapshot_dob: Mapped[str | None] = mapped_column(String(32))
    doctor_snapshot_name: Mapped[str | None] = mapped_column(String(255))
    client_snapshot_name: Mapped[str | None] = mapped_column(String(255))
    lab_snapshot_name: Mapped[str | None] = mapped_column(String(255))
    lab_snapshot_address: Mapped[str | None] = mapped_column(Text)
    lab_snapshot_phone: Mapped[str | None] = mapped_column(String(64))
    lab_snapshot_email: Mapped[str | None] = mapped_column(String(255))
    director_snapshot_name: Mapped[str | None] = mapped_column(String(255))
    director_snapshot_license: Mapped[str | None] = mapped_column(String(255))
    footer_snapshot_text: Mapped[str | None] = mapped_column(Text)
    header_image_snapshot_path: Mapped[str | None] = mapped_column(Text)
    footer_signature_snapshot_path: Mapped[str | None] = mapped_column(Text)
    general_comments: Mapped[str | None] = mapped_column(Text)


class ReportItemSnapshot(Base):
    __tablename__ = "report_item_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("report_snapshot.id", ondelete="CASCADE"), nullable=False)
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("order_item.id"))
    test_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    result_value_snapshot: Mapped[str | None] = mapped_column(Text)
    unit_snapshot: Mapped[str | None] = mapped_column(String(32))
    reference_text_snapshot: Mapped[str | None] = mapped_column(Text)
    lower_value_snapshot_text: Mapped[str | None] = mapped_column(String(64))
    upper_value_snapshot_text: Mapped[str | None] = mapped_column(String(64))
    flag_snapshot: Mapped[str | None] = mapped_column(String(16))
    comments_snapshot: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_type_snapshot: Mapped[str] = mapped_column(String(16), nullable=False, default="test")
    source_label_snapshot: Mapped[str | None] = mapped_column(String(255))


class ReportOutsourcedRowSnapshot(Base):
    """Immutable snapshot of outsourced-PDF panel rows captured when a report is finalized."""

    __tablename__ = "report_outsourced_row_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("report_snapshot.id", ondelete="CASCADE"), nullable=False)
    panel_label: Mapped[str] = mapped_column(String(255), nullable=False)
    source_pdf_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    row_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    col_1: Mapped[str | None] = mapped_column(Text)
    col_2: Mapped[str | None] = mapped_column(Text)
    col_3: Mapped[str | None] = mapped_column(Text)
    col_4: Mapped[str | None] = mapped_column(Text)
    col_5: Mapped[str | None] = mapped_column(Text)


class OutsourcedPanelTable(Base):
    """Live (editable) outsourced-PDF panel extraction attached to an order."""

    __tablename__ = "outsourced_panel_table"
    __table_args__ = (UniqueConstraint("order_id", "panel_label", name="uq_outsourced_panel_table_order_label"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lab_order.id", ondelete="CASCADE"), nullable=False)
    panel_label: Mapped[str] = mapped_column(String(255), nullable=False)
    source_pdf_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OutsourcedPanelExtraction(Base):
    """One page-level extraction pass feeding an OutsourcedPanelTable."""

    __tablename__ = "outsourced_panel_extraction"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outsourced_panel_table_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("outsourced_panel_table.id", ondelete="CASCADE"), nullable=False)
    source_pdf_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OutsourcedPanelRow(Base):
    """A single extracted row (up to five columns) inside an OutsourcedPanelTable."""

    __tablename__ = "outsourced_panel_row"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outsourced_panel_table_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("outsourced_panel_table.id", ondelete="CASCADE"), nullable=False)
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("outsourced_panel_extraction.id", ondelete="SET NULL"))
    row_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    col_1: Mapped[str | None] = mapped_column(Text)
    col_2: Mapped[str | None] = mapped_column(Text)
    col_3: Mapped[str | None] = mapped_column(Text)
    col_4: Mapped[str | None] = mapped_column(Text)
    col_5: Mapped[str | None] = mapped_column(Text)


class Supplier(Base):
    __tablename__ = "supplier"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InventoryItem(Base):
    __tablename__ = "inventory_item"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    min_stock: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    max_stock: Mapped[float | None] = mapped_column(Numeric(14, 3))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InventoryLot(Base):
    __tablename__ = "inventory_lot"
    __table_args__ = (UniqueConstraint("item_id", "lot_number", name="uq_inventory_item_lot"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_item.id"), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("supplier.id"))
    lot_number: Mapped[str] = mapped_column(String(120), nullable=False)
    expiration_date: Mapped[date | None] = mapped_column(Date)
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    unit_cost: Mapped[float | None] = mapped_column(Numeric(12, 4))
    initial_qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    current_qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class InventoryTxn(Base):
    __tablename__ = "inventory_txn"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    txn_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_item.id"), nullable=False)
    lot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_lot.id"))
    txn_type: Mapped[str] = mapped_column(String(24), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    unit_cost: Mapped[float | None] = mapped_column(Numeric(12, 4))
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_id: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False)


class Invoice(Base):
    __tablename__ = "invoice"
    __table_args__ = (UniqueConstraint("provider_id", "period_start", "period_end", name="uq_invoice_period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("provider.id"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    tax: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InvoiceLine(Base):
    __tablename__ = "invoice_line"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoice.id", ondelete="CASCADE"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("lab_order.id"))
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("order_item.id"))
    test_code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)


class MonthEndClose(Base):
    __tablename__ = "month_end_close"
    __table_args__ = (UniqueConstraint("period_start", "period_end", name="uq_month_end_period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    opened_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class MonthEndChecklist(Base):
    __tablename__ = "month_end_checklist"
    __table_args__ = (UniqueConstraint("close_id", "item_key", name="uq_month_end_checklist"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    close_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("month_end_close.id", ondelete="CASCADE"), nullable=False)
    item_key: Mapped[str] = mapped_column(String(64), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    done_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class MonthEndSnapshot(Base):
    __tablename__ = "month_end_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    close_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("month_end_close.id", ondelete="CASCADE"), nullable=False)
    snapshot_type: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InventoryStockItem(Base):
    """Desktop-style stock item (single on-hand quantity, no lots)."""

    __tablename__ = "inventory_stock_item"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    on_hand: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    reorder_level: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class InventorySupplier(Base):
    __tablename__ = "inventory_supplier"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))
    tax_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InventoryMovement(Base):
    __tablename__ = "inventory_movement"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_stock_item.id", ondelete="CASCADE"), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_supplier.id", ondelete="SET NULL"))
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    movement_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"))
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSONB)
    after_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# Basic data integrity constraints
AppUser.__table__.append_constraint(CheckConstraint("role in ('admin','tech','reviewer','lab_manager')", name="ck_app_user_role"))
Patient.__table__.append_constraint(CheckConstraint("sex in ('M','F','O','X') or sex is null", name="ck_patient_sex"))
TestCatalog.__table__.append_constraint(CheckConstraint("result_kind in ('numeric','text','select','image')", name="ck_test_catalog_result_kind"))
TestReferenceRange.__table__.append_constraint(CheckConstraint("sex in ('M','F','O','X') or sex is null", name="ck_test_reference_range_sex"))
Patient.__table__.append_constraint(CheckConstraint("age_unit in ('days','months','years') or age_unit is null", name="ck_patient_age_unit"))
Provider.__table__.append_constraint(CheckConstraint("provider_type in ('doctor','clinic')", name="ck_provider_type"))
LabOrder.__table__.append_constraint(CheckConstraint("status in ('registered','collected','in_lab','completed','reported','amended')", name="ck_lab_order_status"))
OrderItem.__table__.append_constraint(CheckConstraint("priority in ('routine','stat')", name="ck_order_item_priority"))
PanelCatalogItem.__table__.append_constraint(CheckConstraint("item_type in ('test','heading','comment')", name="ck_panel_catalog_item_type"))
Sample.__table__.append_constraint(CheckConstraint("status in ('registered','collected','received','rejected','processed')", name="ck_sample_status"))
Result.__table__.append_constraint(CheckConstraint("status in ('draft','verified','amended')", name="ck_result_status"))
InventoryLot.__table__.append_constraint(CheckConstraint("status in ('active','quarantine','expired','consumed','discarded')", name="ck_inventory_lot_status"))
InventoryTxn.__table__.append_constraint(CheckConstraint("txn_type in ('purchase_in','usage_out','adjustment_plus','adjustment_minus','waste_out','return_out')", name="ck_inventory_txn_type"))
InventoryTxn.__table__.append_constraint(CheckConstraint("qty > 0", name="ck_inventory_txn_qty_positive"))
Invoice.__table__.append_constraint(CheckConstraint("status in ('draft','issued','paid','void')", name="ck_invoice_status"))
MonthEndClose.__table__.append_constraint(CheckConstraint("status in ('open','in_review','closed')", name="ck_month_end_close_status"))
MonthEndSnapshot.__table__.append_constraint(CheckConstraint("snapshot_type in ('billing','inventory','operations')", name="ck_month_end_snapshot_type"))

ReportSnapshot.__table__.append_constraint(CheckConstraint("status in ('final')", name="ck_report_snapshot_status"))
ReportItemSnapshot.__table__.append_constraint(CheckConstraint("item_type_snapshot in ('test','heading','comment','panel_meta')", name="ck_report_item_snapshot_type"))
