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

    def list_test_choices(self) -> list[tuple[str, str]]:
        """LIS test choices as (id_str, label) for the mapping UI."""
        choices = self._orders.list_test_choices()
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

    def import_order(
        self,
        order: PendingOrder,
        *,
        patient_payload: dict[str, Any],
        lis_test_ids: list[str],
        notes: str,
    ) -> ImportResult:
        if not lis_test_ids:
            raise ValueError("Select at least one LIS test before importing.")

        patient_id = self._patients.create_patient(patient_payload)
        order_items = [{"test_id": tid, "item_type": "test", "source": "Portal"} for tid in lis_test_ids]

        if self._orders.uses_server_backend():
            created = self._orders.create_simple_order(
                patient_id=str(patient_id),
                test_ids=[str(tid) for tid in lis_test_ids],
                items=order_items,
                accession_id=None,
                sample_id=None,
                status="registered",
                notes=notes,
            )
            return ImportResult(order_id=created["id"], order_number=created["order_number"])

        new_id = self.database.create_order(
            order_number=None,
            accession_id=None,
            sample_id=None,
            patient_id=int(patient_id),
            doctor_id=None,
            client_id=None,
            order_items=[{"test_id": int(tid), "item_type": "test", "source": "Portal"} for tid in lis_test_ids],
            status="registered",
            notes=notes,
        )
        edit = self.database.get_order_edit_record(int(new_id))
        order_number = edit.order_number if edit is not None else str(new_id)
        return ImportResult(order_id=str(new_id), order_number=order_number)
