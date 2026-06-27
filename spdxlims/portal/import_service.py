"""Turn a portal pending order into a LIS patient + lab order.

Reuses the existing PatientService / OrderService so it works identically in
local (SQLite) and server (PostgreSQL API) modes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spdxlims.database import Database
from spdxlims.deployment import DeploymentService
from spdxlims.order_service import OrderService
from spdxlims.panel_service import PanelService
from spdxlims.patient_service import PatientService
from spdxlims.portal.client import PendingOrder

_GENDER_TO_SEX = {
    "femenino": "F",
    "female": "F",
    "f": "F",
    "masculino": "M",
    "male": "M",
    "m": "M",
}


@dataclass(slots=True)
class ImportResult:
    order_id: str
    order_number: str


@dataclass
class PortalImportService:
    database: Database
    deployment_service: DeploymentService

    def __post_init__(self) -> None:
        self._patients = PatientService(self.database, self.deployment_service)
        self._orders = OrderService(self.database, self.deployment_service)
        self._panels = PanelService(self.database, self.deployment_service)

    def list_panel_choices(self) -> list[tuple[str, str]]:
        """LIS panel choices as (id_str, label) for the mapping UI."""
        choices = self._panels.list_panel_choices()
        return [(str(value), str(label)) for value, label in choices]

    @staticmethod
    def split_name(full_name: str) -> tuple[str, str]:
        parts = [p for p in full_name.strip().split() if p]
        if not parts:
            return ("", "")
        if len(parts) == 1:
            return (parts[0], parts[0])
        # First token is the given name, the rest is the family name(s).
        return (parts[0], " ".join(parts[1:]))

    @staticmethod
    def gender_to_sex(gender: str) -> str | None:
        return _GENDER_TO_SEX.get(gender.strip().lower())

    def build_patient_payload(self, order: PendingOrder) -> dict[str, Any]:
        first_name, last_name = self.split_name(order.patient_name)
        payload: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "sex": self.gender_to_sex(order.patient_gender),
            "phone": order.patient_phone,
        }
        if order.patient_age is not None:
            payload["age_value"] = order.patient_age
            payload["age_unit"] = "years"
        return payload

    def _build_panel_order_items(self, lis_panel_ids: list[str]) -> list[dict[str, Any]]:
        """Expand each linked LIS panel into its *test* order items, sourced by the
        panel name. Headings and comments are intentionally dropped: they all share
        a single placeholder test_id, and order_tests is UNIQUE(order_id, test_id),
        so emitting one per panel would collide -- the same reason the bulk import
        path keeps only tests (see OrdersPage._order_import_items). A test may also
        appear in more than one selected panel, so keep only its first occurrence
        (panel grouping is preserved via each test's ``source`` label)."""
        panel_names = {str(panel.id): panel.name for panel in self._panels.list_panels(status_filter="all")}
        order_items: list[dict[str, Any]] = []
        seen_test_ids: set[str] = set()
        for panel_id in lis_panel_ids:
            panel_name = panel_names.get(str(panel_id), "")
            for entry in self._orders.get_panel_order_items(panel_id):
                if str(entry.get("item_type") or "test") != "test":
                    continue
                test_id = entry.get("test_id")
                if test_id is None or str(test_id) in seen_test_ids:
                    continue
                seen_test_ids.add(str(test_id))
                order_items.append(
                    {
                        "item_type": "test",
                        "test_id": test_id,
                        "label": str(entry.get("label") or ""),
                        "source": panel_name,
                        "is_outsourced": 0,
                    }
                )
        return order_items

    def import_order(
        self,
        order: PendingOrder,
        *,
        patient_payload: dict[str, Any],
        lis_panel_ids: list[str],
        notes: str,
    ) -> ImportResult:
        if not lis_panel_ids:
            raise ValueError("Select at least one LIS panel before importing.")

        order_items = self._build_panel_order_items(lis_panel_ids)
        test_items = [item for item in order_items if item["item_type"] == "test"]
        if not test_items:
            raise ValueError("The selected panels do not contain any tests to import.")

        patient_id = self._patients.create_patient(patient_payload)

        if self._orders.uses_server_backend():
            created = self._orders.create_simple_order(
                patient_id=str(patient_id),
                test_ids=[str(item["test_id"]) for item in test_items],
                items=[{"test_id": item["test_id"], "source": item["source"]} for item in test_items],
                accession_id=None,
                sample_id=None,
                status="registered",
                notes=notes,
            )
            return ImportResult(order_id=created["id"], order_number=created["order_number"])

        # Local (SQLite) orders use a different status vocabulary than the server
        # API ('draft'/'in_progress'/'finalized'/'cancelled' vs the server's
        # 'registered'/...), so a new local order starts as 'draft' -- the same
        # status the normal OrdersPage uses when creating an order.
        new_id = self.database.create_order(
            order_number=None,
            accession_id=None,
            sample_id=None,
            patient_id=int(patient_id),
            doctor_id=None,
            client_id=None,
            order_items=order_items,
            status="draft",
            notes=notes,
        )
        edit = self.database.get_order_edit_record(int(new_id))
        order_number = edit.order_number if edit is not None else str(new_id)
        return ImportResult(order_id=str(new_id), order_number=order_number)
