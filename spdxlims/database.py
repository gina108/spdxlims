from __future__ import annotations

from spdxlims.db.records import (
    PatientRecord,
    LabSettingsRecord,
    DoctorRecord,
    ClientRecord,
    BillingCustomerRecord,
    EquipmentRecord,
    TestRecord,
    PanelRecord,
    PanelItemRecord,
    InventoryItemRecord,
    SupplierRecord,
    InventoryMovementRecord,
    InvoiceRecord,
    ReceiptRecord,
    OrderSummaryRecord,
    OrderBrowserRecord,
    ResultWorkflowRecord,
    OutsourcedPanelChoiceRecord,
    OrderLookupRecord,
    OrderEditRecord,
    ResultEntryRecord,
    InstrumentResultMappingRecord,
    InstrumentOrderMatchRecord,
    TestReferenceRangeRecord,
)

from spdxlims.db.schema import SchemaMixin
from spdxlims.db.patients import PatientsMixin
from spdxlims.db.doctors import DoctorsMixin
from spdxlims.db.clients import ClientsMixin
from spdxlims.db.inventory import InventoryMixin
from spdxlims.db.billing import BillingMixin
from spdxlims.db.equipment import EquipmentMixin
from spdxlims.db.settings import SettingsMixin
from spdxlims.db.tests import TestsMixin
from spdxlims.db.panels import PanelsMixin
from spdxlims.db.orders import OrdersMixin
from spdxlims.db.instruments import InstrumentsMixin
from spdxlims.db.results import ResultsMixin
from spdxlims.db.helpers import HelpersMixin


class Database(
    SchemaMixin,
    PatientsMixin,
    DoctorsMixin,
    ClientsMixin,
    InventoryMixin,
    BillingMixin,
    EquipmentMixin,
    SettingsMixin,
    TestsMixin,
    PanelsMixin,
    OrdersMixin,
    InstrumentsMixin,
    ResultsMixin,
    HelpersMixin,
):
    pass


__all__ = [
    "Database",
    "PatientRecord",
    "LabSettingsRecord",
    "DoctorRecord",
    "ClientRecord",
    "BillingCustomerRecord",
    "EquipmentRecord",
    "TestRecord",
    "PanelRecord",
    "PanelItemRecord",
    "InventoryItemRecord",
    "SupplierRecord",
    "InventoryMovementRecord",
    "InvoiceRecord",
    "ReceiptRecord",
    "OrderSummaryRecord",
    "OrderBrowserRecord",
    "ResultWorkflowRecord",
    "OutsourcedPanelChoiceRecord",
    "OrderLookupRecord",
    "OrderEditRecord",
    "ResultEntryRecord",
    "InstrumentResultMappingRecord",
    "InstrumentOrderMatchRecord",
    "TestReferenceRangeRecord",
]
