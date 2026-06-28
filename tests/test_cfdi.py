from __future__ import annotations

import pytest

from spdxlims.cfdi_pac import (
    CfdiConfigError,
    CfdiLineItem,
    CfdiProvider,
    StampedCfdi,
    TAX_EXEMPT,
    TAX_IVA16,
    _folio_from_invoice_number,
    _to_facturama_payload,
    build_cfdi_document,
    validate_for_stamping,
)
from spdxlims.database import Database
from spdxlims.db.records import ClientRecord, InvoiceRecord


def _invoice(**overrides) -> InvoiceRecord:
    base = dict(
        id=1,
        invoice_number="INV-000042",
        client_id=7,
        client_name="Clinica Demo",
        order_id=None,
        order_number=None,
        invoice_date="2026-06-28",
        status="issued",
        total_amount=300.0,
        notes=None,
        cfdi_use="G03",
        payment_form="03",
        payment_method="PUE",
        currency="MXN",
        xml_path=None,
    )
    base.update(overrides)
    return InvoiceRecord(**base)


def _client(**overrides) -> ClientRecord:
    base = dict(
        id=7,
        name="Clinica Demo SA de CV",
        phone=None,
        email=None,
        tax_id="XAXX010101000",
        fiscal_regime="601",
        postal_code="64000",
        cfdi_use="G03",
        is_active=1,
    )
    base.update(overrides)
    return ClientRecord(**base)


def _settings(database: Database):
    database.save_lab_settings(
        {
            "lab_name": "SPDX Lab",
            "sat_rfc": "EKU9003173C9",
            "sat_fiscal_regime": "601",
            "sat_postal_code": "64000",
            "pac_provider": "facturama",
            "pac_environment": "sandbox",
            "pac_username": "demo",
            "pac_password": "secret",
        }
    )
    return database.get_lab_settings()


def test_folio_strips_prefix_and_leading_zeros() -> None:
    assert _folio_from_invoice_number("INV-000042") == "42"
    assert _folio_from_invoice_number("A123") == "123"
    assert _folio_from_invoice_number("") == "1"


def test_pac_settings_persist(tmp_path) -> None:
    database = Database(tmp_path / "lims.db")
    database.initialize()
    settings = _settings(database)
    assert settings.pac_provider == "facturama"
    assert settings.pac_environment == "sandbox"
    assert settings.pac_username == "demo"
    assert settings.pac_password == "secret"
    assert settings.cfdi_tax_treatment == "exempt"


def test_cfdi_tax_treatment_persists(tmp_path) -> None:
    database = Database(tmp_path / "lims.db")
    database.initialize()
    database.save_lab_settings({"lab_name": "SPDX", "cfdi_tax_treatment": "iva16"})
    assert database.get_lab_settings().cfdi_tax_treatment == "iva16"


def test_build_document_uses_line_items_and_exempt_total(tmp_path) -> None:
    database = Database(tmp_path / "lims.db")
    database.initialize()
    settings = _settings(database)
    items = [
        CfdiLineItem(description="Biometria Hematica", quantity=2, unit_price=100.0),
        CfdiLineItem(description="Quimica Sanguinea", quantity=1, unit_price=100.0),
    ]
    document = build_cfdi_document(
        invoice=_invoice(), client=_client(), settings=settings, line_items=items
    )
    assert document.folio == "42"
    assert document.expedition_place == "64000"
    assert document.receiver_rfc == "XAXX010101000"
    assert document.subtotal == 300.0
    assert document.tax_total == 0.0  # exempt by default
    assert document.total == 300.0


def test_build_document_falls_back_to_single_concept(tmp_path) -> None:
    database = Database(tmp_path / "lims.db")
    database.initialize()
    settings = _settings(database)
    document = build_cfdi_document(invoice=_invoice(total_amount=250.0), client=_client(), settings=settings)
    assert len(document.items) == 1
    assert document.items[0].unit_price == 250.0
    assert document.total == 250.0


def test_iva16_adds_tax_to_payload(tmp_path) -> None:
    database = Database(tmp_path / "lims.db")
    database.initialize()
    settings = _settings(database)
    items = [CfdiLineItem(description="Estudio", quantity=1, unit_price=100.0)]
    document = build_cfdi_document(
        invoice=_invoice(), client=_client(), settings=settings, line_items=items, tax_treatment=TAX_IVA16
    )
    assert document.tax_total == 16.0
    assert document.total == 116.0
    payload = _to_facturama_payload(document)
    item = payload["Items"][0]
    assert item["TaxObject"] == "02"
    assert item["Taxes"][0]["Total"] == 16.0
    assert item["Total"] == 116.0


def test_exempt_payload_has_no_taxes(tmp_path) -> None:
    database = Database(tmp_path / "lims.db")
    database.initialize()
    settings = _settings(database)
    document = build_cfdi_document(invoice=_invoice(), client=_client(), settings=settings)
    payload = _to_facturama_payload(document)
    item = payload["Items"][0]
    assert item["TaxObject"] == "01"
    assert "Taxes" not in item


def test_validate_requires_receiver_data(tmp_path) -> None:
    database = Database(tmp_path / "lims.db")
    database.initialize()
    settings = _settings(database)
    document = build_cfdi_document(
        invoice=_invoice(), client=_client(tax_id=""), settings=settings
    )
    with pytest.raises(CfdiConfigError):
        validate_for_stamping(document, settings)


class _FakeProvider(CfdiProvider):
    def stamp(self, document) -> StampedCfdi:
        return StampedCfdi(uuid="UUID-123", provider_id="prov-1", total=document.total)

    def fetch_xml(self, provider_id: str) -> bytes:
        return b"<xml/>"

    def fetch_pdf(self, provider_id: str) -> bytes:
        return b"%PDF-1.4"

    def cancel(self, provider_id: str, *, motive: str = "02", substitution_uuid: str | None = None) -> None:
        return None


def test_record_invoice_stamp_persists_and_transitions_status(tmp_path) -> None:
    database = Database(tmp_path / "lims.db")
    database.initialize()
    invoice_id = database.create_invoice(
        {"invoice_date": "2026-06-28", "status": "draft", "total_amount": 300.0}
    )
    provider = _FakeProvider()
    document = build_cfdi_document(
        invoice=_invoice(), client=_client(), settings=_settings(database)
    )
    stamped = provider.stamp(document)
    database.record_invoice_stamp(
        invoice_id,
        uuid=stamped.uuid,
        provider_id=stamped.provider_id,
        xml_path="x.xml",
        pdf_path="x.pdf",
        stamped_at="2026-06-28T12:00:00",
    )
    saved = database.get_invoice(invoice_id)
    assert saved is not None
    assert saved.cfdi_uuid == "UUID-123"
    assert saved.cfdi_status == "stamped"
    assert saved.status == "issued"  # draft promoted to issued on stamp

    database.mark_invoice_cfdi_cancelled(invoice_id)
    cancelled = database.get_invoice(invoice_id)
    assert cancelled is not None
    assert cancelled.cfdi_status == "cancelled"
    assert cancelled.status == "cancelled"
