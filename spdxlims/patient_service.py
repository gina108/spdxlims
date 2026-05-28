from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib import parse

from spdxlims.database import Database, PatientRecord
from spdxlims.deployment import DeploymentService


@dataclass(slots=True)
class PatientService:
    database: Database
    deployment_service: DeploymentService

    def list_patients(self, *, status_filter: str = "active") -> list[PatientRecord]:
        config = self.deployment_service.load()
        if config.mode != "server":
            return self.database.list_patients(status_filter=status_filter)
        payload = self.deployment_service.request_json("GET", f"/api/patients?status_filter={parse.quote(status_filter)}")
        if not isinstance(payload, list):
            return []
        return [self._to_record(item) for item in payload if isinstance(item, dict)]

    def list_patient_choices(self) -> list[tuple[int | str, str]]:
        records = self.list_patients(status_filter="active")
        return [(record.id, self._format_label(record)) for record in records]

    def get_patient(self, patient_id: int | str) -> dict[str, Any] | None:
        config = self.deployment_service.load()
        if config.mode != "server":
            return self.database.get_patient(int(patient_id))
        payload = self.deployment_service.request_json("GET", f"/api/patients/{patient_id}")
        return self._to_local_dict(payload) if isinstance(payload, dict) else None

    def create_patient(self, payload: dict[str, Any]) -> int | str:
        config = self.deployment_service.load()
        if config.mode != "server":
            return self.database.create_patient(payload)
        response = self.deployment_service.request_json("POST", "/api/patients", self._to_remote_payload(payload))
        if not isinstance(response, dict) or "id" not in response:
            raise RuntimeError("Server did not return a patient id.")
        return str(response["id"])

    def update_patient(self, patient_id: int | str, payload: dict[str, Any]) -> None:
        config = self.deployment_service.load()
        if config.mode != "server":
            self.database.update_patient(int(patient_id), payload)
            return
        self.deployment_service.request_json("PUT", f"/api/patients/{patient_id}", self._to_remote_payload(payload))

    def archive_patient(self, patient_id: int | str) -> None:
        config = self.deployment_service.load()
        if config.mode != "server":
            self.database.archive_patient(int(patient_id))
            return
        self.deployment_service.request_json("POST", f"/api/patients/{patient_id}/archive")

    def unarchive_patient(self, patient_id: int | str) -> None:
        config = self.deployment_service.load()
        if config.mode != "server":
            self.database.unarchive_patient(int(patient_id))
            return
        self.deployment_service.request_json("POST", f"/api/patients/{patient_id}/unarchive")

    @staticmethod
    def _to_remote_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "mrn": payload.get("patient_code") or None,
            "first_name": str(payload.get("first_name") or "").strip(),
            "last_name": str(payload.get("last_name") or "").strip(),
            "middle_name": str(payload.get("middle_name") or "").strip() or None,
            "sex": payload.get("sex") or None,
            "dob": str(payload.get("date_of_birth") or "").strip() or None,
            "age_value": payload.get("age_value"),
            "age_unit": payload.get("age_unit") or None,
            "phone": str(payload.get("phone") or "").strip() or None,
            "email": str(payload.get("email") or "").strip() or None,
            "address": str(payload.get("address") or "").strip() or None,
            "is_active": True,
        }

    @staticmethod
    def _to_record(payload: dict[str, Any]) -> PatientRecord:
        return PatientRecord(
            id=str(payload.get("id") or ""),
            patient_code=payload.get("mrn"),
            first_name=str(payload.get("first_name") or ""),
            last_name=str(payload.get("last_name") or ""),
            middle_name=payload.get("middle_name"),
            sex=payload.get("sex"),
            date_of_birth=payload.get("dob"),
            age_value=payload.get("age_value"),
            age_unit=payload.get("age_unit"),
            phone=payload.get("phone"),
            is_active=1 if payload.get("is_active", True) else 0,
        )

    @staticmethod
    def _to_local_dict(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(payload.get("id") or ""),
            "patient_code": payload.get("mrn"),
            "first_name": payload.get("first_name"),
            "last_name": payload.get("last_name"),
            "middle_name": payload.get("middle_name"),
            "sex": payload.get("sex"),
            "date_of_birth": payload.get("dob"),
            "age_value": payload.get("age_value"),
            "age_unit": payload.get("age_unit"),
            "phone": payload.get("phone"),
            "email": payload.get("email"),
            "address": payload.get("address"),
            "is_active": 1 if payload.get("is_active", True) else 0,
        }

    @staticmethod
    def _format_label(record: PatientRecord) -> str:
        full_name = " ".join(part for part in [record.first_name, record.last_name, record.middle_name or ""] if part).strip()
        age_part = f" - {record.age_value} {record.age_unit}" if record.age_value is not None and record.age_unit else ""
        return f"{full_name}{age_part}".strip()
