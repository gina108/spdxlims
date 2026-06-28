"""Provider-agnostic CFDI 4.0 stamping (timbrado) through an authorized PAC.

A "real" factura is a CFDI that has been sealed with the issuer's CSD and
stamped by a PAC (Proveedor Autorizado de Certificacion), which returns the
official UUID / Folio Fiscal. That step cannot happen locally -- it requires a
PAC web service.

This module keeps the document modelling and the totals maths in pure,
testable code (``build_cfdi_document`` / ``CfdiDocument``) and isolates the
network behind the ``CfdiProvider`` interface. ``FacturamaProvider`` is the
first concrete implementation; others (Finkok, SW Sapien) can be added without
touching the rest of the app.

Facturama is used in its hosted-CSD model: the lab registers its RFC + CSD in
Facturama once, then this app only POSTs invoice JSON and receives the stamped
UUID, XML and PDF. We therefore never handle the .key/.cer sealing ourselves.
"""
from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib import error as urllib_error
from urllib import request as urllib_request

if TYPE_CHECKING:
    from spdxlims.db.records import ClientRecord, InvoiceRecord, LabSettingsRecord

# Default SAT product/service key for clinical-laboratory services.
DEFAULT_PRODUCT_CODE = "85121800"
DEFAULT_UNIT_CODE = "ACT"
DEFAULT_UNIT = "Actividad"

# Tax treatments. Clinical-lab analysis is commonly IVA-exento in Mexico, so
# that is the default; confirm the correct treatment with an accountant.
TAX_EXEMPT = "exempt"
TAX_IVA16 = "iva16"
TAX_ZERO = "zero"
TAX_TREATMENTS = (TAX_EXEMPT, TAX_IVA16, TAX_ZERO)

_IVA_RATE = 0.16

# Facturama REST endpoints.
_FACTURAMA_PROD = "https://api.facturama.mx"
_FACTURAMA_SANDBOX = "https://apisandbox.facturama.mx"


class CfdiError(Exception):
    """A stamping/cancellation failure with a human-readable message.

    ``detail`` carries any structured validation messages returned by the PAC
    so the UI can show exactly what SAT rejected.
    """

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class CfdiConfigError(CfdiError):
    """Raised when PAC/issuer configuration is incomplete before stamping."""


@dataclass(slots=True)
class CfdiLineItem:
    description: str
    quantity: float
    unit_price: float
    product_code: str = DEFAULT_PRODUCT_CODE
    unit_code: str = DEFAULT_UNIT_CODE
    unit: str = DEFAULT_UNIT

    @property
    def amount(self) -> float:
        return round(self.quantity * self.unit_price, 2)


@dataclass(slots=True)
class CfdiDocument:
    """A CFDI ready to be mapped to a provider request and stamped."""

    serie: str
    folio: str
    cfdi_type: str
    currency: str
    expedition_place: str
    payment_form: str
    payment_method: str
    receiver_rfc: str
    receiver_name: str
    receiver_cfdi_use: str
    receiver_fiscal_regime: str
    receiver_zip: str
    items: list[CfdiLineItem] = field(default_factory=list)
    tax_treatment: str = TAX_EXEMPT

    @property
    def subtotal(self) -> float:
        return round(sum(item.amount for item in self.items), 2)

    @property
    def tax_total(self) -> float:
        if self.tax_treatment != TAX_IVA16:
            return 0.0
        return round(self.subtotal * _IVA_RATE, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.tax_total, 2)


@dataclass(slots=True)
class StampedCfdi:
    uuid: str
    provider_id: str
    total: float


def _folio_from_invoice_number(invoice_number: str) -> str:
    digits = "".join(ch for ch in (invoice_number or "") if ch.isdigit())
    return str(int(digits)) if digits else (invoice_number or "1")


def build_cfdi_document(
    *,
    invoice: "InvoiceRecord",
    client: "ClientRecord",
    settings: "LabSettingsRecord",
    line_items: list[CfdiLineItem] | None = None,
    serie: str = "A",
    tax_treatment: str = TAX_EXEMPT,
) -> CfdiDocument:
    """Assemble a :class:`CfdiDocument` from an invoice and its parties.

    When ``line_items`` is omitted (or empty) a single concept covering the
    whole invoice total is used, so an invoice can always be stamped even when
    per-panel detail is unavailable.
    """
    if tax_treatment not in TAX_TREATMENTS:
        raise ValueError(f"Unknown tax treatment: {tax_treatment!r}")

    items = list(line_items or [])
    if not items:
        items = [
            CfdiLineItem(
                description=(invoice.notes or "").strip()
                or f"Servicios de laboratorio {invoice.order_number or invoice.invoice_number}",
                quantity=1,
                unit_price=round(float(invoice.total_amount or 0), 2),
            )
        ]

    return CfdiDocument(
        serie=serie,
        folio=_folio_from_invoice_number(invoice.invoice_number),
        cfdi_type="I",
        currency=invoice.currency or "MXN",
        expedition_place=(settings.sat_postal_code or "").strip(),
        payment_form=(invoice.payment_form or "99").strip() or "99",
        payment_method=(invoice.payment_method or "PUE").strip() or "PUE",
        receiver_rfc=(client.tax_id or "").strip().upper(),
        receiver_name=(client.name or "").strip(),
        receiver_cfdi_use=(invoice.cfdi_use or client.cfdi_use or "G03").strip() or "G03",
        receiver_fiscal_regime=(client.fiscal_regime or "").strip(),
        receiver_zip=(client.postal_code or "").strip(),
        items=items,
        tax_treatment=tax_treatment,
    )


def validate_for_stamping(document: CfdiDocument, settings: "LabSettingsRecord") -> None:
    """Raise :class:`CfdiConfigError` describing the first missing requirement."""
    missing: list[str] = []
    if not (settings.sat_rfc or "").strip():
        missing.append("issuer RFC (Settings → SAT)")
    if not (settings.sat_fiscal_regime or "").strip():
        missing.append("issuer fiscal regime (Settings → SAT)")
    if not document.expedition_place:
        missing.append("issuer postal code (Settings → SAT)")
    if not document.receiver_rfc:
        missing.append("customer RFC")
    if not document.receiver_name:
        missing.append("customer name")
    if not document.receiver_fiscal_regime:
        missing.append("customer fiscal regime")
    if not document.receiver_zip:
        missing.append("customer postal code")
    if document.total <= 0:
        missing.append("a total greater than zero")
    if missing:
        raise CfdiConfigError(
            "The factura is missing required CFDI data: " + "; ".join(missing) + "."
        )


class CfdiProvider(ABC):
    """A PAC capable of stamping and cancelling CFDI documents."""

    @abstractmethod
    def stamp(self, document: CfdiDocument) -> StampedCfdi:
        ...

    @abstractmethod
    def fetch_xml(self, provider_id: str) -> bytes:
        ...

    @abstractmethod
    def fetch_pdf(self, provider_id: str) -> bytes:
        ...

    @abstractmethod
    def cancel(
        self,
        provider_id: str,
        *,
        motive: str = "02",
        substitution_uuid: str | None = None,
    ) -> None:
        ...


class FacturamaProvider(CfdiProvider):
    """Stamping via the Facturama REST API (hosted-CSD model)."""

    def __init__(self, username: str, password: str, *, sandbox: bool = True, timeout: float = 60.0) -> None:
        if not username or not password:
            raise CfdiConfigError("Facturama username and password are required (Settings → SAT).")
        self._username = username
        self._password = password
        self._base = _FACTURAMA_SANDBOX if sandbox else _FACTURAMA_PROD
        self._timeout = timeout

    # -- request helpers ---------------------------------------------------
    def _auth_header(self) -> str:
        token = base64.b64encode(f"{self._username}:{self._password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self._base}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib_request.Request(url, data=data, method=method)
        req.add_header("Authorization", self._auth_header())
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib_request.urlopen(req, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:  # PAC validation / auth errors
            raise CfdiError(self._http_error_message(exc), detail=self._read_error_body(exc)) from exc
        except urllib_error.URLError as exc:
            raise CfdiError(f"Could not reach the PAC: {exc.reason}") from exc
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CfdiError("The PAC returned an unexpected (non-JSON) response.") from exc

    @staticmethod
    def _read_error_body(exc: urllib_error.HTTPError) -> str | None:
        try:
            return exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001 - best effort diagnostic only
            return None

    def _http_error_message(self, exc: urllib_error.HTTPError) -> str:
        body = self._read_error_body(exc)
        if exc.code in (401, 403):
            return "The PAC rejected the credentials (check the Facturama username/password and environment)."
        detail = ""
        if body:
            try:
                parsed = json.loads(body)
                detail = parsed.get("Message") or parsed.get("message") or ""
                model_state = parsed.get("ModelState") or parsed.get("modelState")
                if isinstance(model_state, dict):
                    flat = [str(m) for messages in model_state.values() for m in (messages or [])]
                    if flat:
                        detail = (detail + " " + "; ".join(flat)).strip()
            except json.JSONDecodeError:
                detail = body[:500]
        return f"The PAC rejected the factura (HTTP {exc.code}). {detail}".strip()

    # -- provider interface ------------------------------------------------
    def stamp(self, document: CfdiDocument) -> StampedCfdi:
        payload = _to_facturama_payload(document)
        result = self._request("POST", "/3/cfdis", payload)
        provider_id = str(result.get("Id") or "")
        complement = result.get("Complement") or {}
        tax_stamp = complement.get("TaxStamp") or {}
        uuid = str(tax_stamp.get("Uuid") or result.get("Uuid") or "")
        if not uuid or not provider_id:
            raise CfdiError(
                "The PAC accepted the request but did not return a UUID.",
                detail=json.dumps(result)[:500],
            )
        return StampedCfdi(uuid=uuid, provider_id=provider_id, total=document.total)

    def _fetch_file(self, kind: str, provider_id: str) -> bytes:
        result = self._request("GET", f"/cfdi/{kind}/issued/{provider_id}")
        content = result.get("Content") if isinstance(result, dict) else None
        if not content:
            raise CfdiError(f"The PAC did not return the {kind.upper()} for this factura.")
        return base64.b64decode(content)

    def fetch_xml(self, provider_id: str) -> bytes:
        return self._fetch_file("xml", provider_id)

    def fetch_pdf(self, provider_id: str) -> bytes:
        return self._fetch_file("pdf", provider_id)

    def cancel(
        self,
        provider_id: str,
        *,
        motive: str = "02",
        substitution_uuid: str | None = None,
    ) -> None:
        path = f"/cfdi/{provider_id}?type=issued&motive={motive}"
        if substitution_uuid:
            path += f"&uuidReplacement={substitution_uuid}"
        self._request("DELETE", path)


def _to_facturama_payload(document: CfdiDocument) -> dict:
    items: list[dict] = []
    for item in document.items:
        entry: dict = {
            "ProductCode": item.product_code,
            "Description": item.description,
            "Unit": item.unit,
            "UnitCode": item.unit_code,
            "Quantity": item.quantity,
            "UnitPrice": item.unit_price,
            "Subtotal": item.amount,
        }
        if document.tax_treatment == TAX_EXEMPT:
            entry["TaxObject"] = "01"
            entry["Total"] = item.amount
        else:
            rate = _IVA_RATE if document.tax_treatment == TAX_IVA16 else 0.0
            tax = round(item.amount * rate, 2)
            entry["TaxObject"] = "02"
            entry["Total"] = round(item.amount + tax, 2)
            entry["Taxes"] = [
                {
                    "Name": "IVA",
                    "Rate": rate,
                    "Total": tax,
                    "Base": item.amount,
                    "IsRetention": False,
                    "IsFederalTax": True,
                }
            ]
        items.append(entry)
    return {
        "Serie": document.serie,
        "Folio": document.folio,
        "CfdiType": document.cfdi_type,
        "Currency": document.currency,
        "ExpeditionPlace": document.expedition_place,
        "PaymentForm": document.payment_form,
        "PaymentMethod": document.payment_method,
        "Receiver": {
            "Rfc": document.receiver_rfc,
            "Name": document.receiver_name,
            "CfdiUse": document.receiver_cfdi_use,
            "FiscalRegime": document.receiver_fiscal_regime,
            "TaxZipCode": document.receiver_zip,
        },
        "Items": items,
    }


def create_provider(settings: "LabSettingsRecord") -> CfdiProvider:
    """Build the configured PAC provider from lab settings."""
    provider = (getattr(settings, "pac_provider", "") or "facturama").strip().lower()
    environment = (getattr(settings, "pac_environment", "") or "sandbox").strip().lower()
    username = (getattr(settings, "pac_username", "") or "").strip()
    password = getattr(settings, "pac_password", "") or ""
    if provider in ("", "facturama"):
        return FacturamaProvider(username, password, sandbox=environment != "production")
    raise CfdiConfigError(f"Unsupported PAC provider: {provider!r}.")
