from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib import parse

from spdxlims.database import ClientRecord, Database, DoctorRecord
from spdxlims.deployment import DeploymentService


@dataclass(slots=True)
class ProviderService:
    database: Database
    deployment_service: DeploymentService

    def uses_server_backend(self) -> bool:
        return self.deployment_service.load().mode == "server"

    def list_doctors(self, *, status_filter: str = "all") -> list[DoctorRecord]:
        if not self.uses_server_backend():
            return self.database.list_doctors(status_filter=status_filter)
        return [
            DoctorRecord(
                id=str(item.get("id") or ""),
                full_name=str(item.get("legal_name") or ""),
                license_number=item.get("code"),
                phone=item.get("phone"),
                email=item.get("email"),
                is_active=1 if item.get("active", True) else 0,
            )
            for item in self._list_providers("doctor", status_filter)
        ]

    def list_clients(self, *, status_filter: str = "all") -> list[ClientRecord]:
        if not self.uses_server_backend():
            return self.database.list_clients(status_filter=status_filter)
        return [
            ClientRecord(
                id=str(item.get("id") or ""),
                name=str(item.get("legal_name") or ""),
                phone=item.get("phone"),
                email=item.get("email"),
                tax_id=item.get("tax_id"),
                fiscal_regime=None,
                postal_code=None,
                cfdi_use=None,
                is_active=1 if item.get("active", True) else 0,
            )
            for item in self._list_providers("clinic", status_filter)
        ]

    def get_doctor(self, doctor_id: int | str) -> dict[str, Any] | None:
        if not self.uses_server_backend():
            doctor = self.database.get_doctor(int(doctor_id))
            if doctor is None:
                return None
            return {
                "id": doctor.id,
                "full_name": doctor.full_name,
                "license_number": doctor.license_number,
                "phone": doctor.phone,
                "email": doctor.email,
                "is_active": doctor.is_active,
            }
        provider = self._get_provider(doctor_id)
        if provider is None:
            return None
        return {
            "id": provider.get("id"),
            "full_name": provider.get("legal_name"),
            "license_number": provider.get("code"),
            "phone": provider.get("phone"),
            "email": provider.get("email"),
            "is_active": 1 if provider.get("active", True) else 0,
        }

    def get_client(self, client_id: int | str) -> dict[str, Any] | None:
        if not self.uses_server_backend():
            client = self.database.get_client(int(client_id))
            if client is None:
                return None
            return {
                "id": client.id,
                "name": client.name,
                "phone": client.phone,
                "email": client.email,
                "tax_id": client.tax_id,
                "fiscal_regime": client.fiscal_regime,
                "postal_code": client.postal_code,
                "cfdi_use": client.cfdi_use,
                "is_active": client.is_active,
            }
        provider = self._get_provider(client_id)
        if provider is None:
            return None
        return {
            "id": provider.get("id"),
            "name": provider.get("legal_name"),
            "phone": provider.get("phone"),
            "email": provider.get("email"),
            "tax_id": provider.get("tax_id"),
            "fiscal_regime": None,
            "postal_code": None,
            "cfdi_use": None,
            "is_active": 1 if provider.get("active", True) else 0,
        }

    def save_doctor(self, payload: dict[str, Any], doctor_id: int | str | None = None) -> int | str:
        if not self.uses_server_backend():
            if doctor_id is None:
                return self.database.create_doctor(payload)
            self.database.update_doctor(int(doctor_id), payload)
            return doctor_id
        body = {
            "provider_type": "doctor",
            "code": str(payload.get("license_number") or "").strip() or None,
            "legal_name": str(payload.get("full_name") or "").strip(),
            "tax_id": None,
            "email": str(payload.get("email") or "").strip() or None,
            "phone": str(payload.get("phone") or "").strip() or None,
            "address": None,
            "billing_terms_days": 30,
            "active": True,
        }
        if doctor_id is None:
            response = self.deployment_service.request_json("POST", "/api/providers", body)
        else:
            existing = self._get_provider(doctor_id) or {}
            body["active"] = bool(existing.get("active", True))
            response = self.deployment_service.request_json("PUT", f"/api/providers/{doctor_id}", body)
        return str(response.get("id") if isinstance(response, dict) else doctor_id)

    def save_client(self, payload: dict[str, Any], client_id: int | str | None = None) -> int | str:
        if not self.uses_server_backend():
            if client_id is None:
                return self.database.create_client(payload)
            self.database.update_client(int(client_id), payload)
            return client_id
        body = {
            "provider_type": "clinic",
            "code": None,
            "legal_name": str(payload.get("name") or "").strip(),
            "tax_id": str(payload.get("tax_id") or "").strip() or None,
            "email": str(payload.get("email") or "").strip() or None,
            "phone": str(payload.get("phone") or "").strip() or None,
            "address": None,
            "billing_terms_days": 30,
            "active": True,
        }
        if client_id is None:
            response = self.deployment_service.request_json("POST", "/api/providers", body)
        else:
            existing = self._get_provider(client_id) or {}
            body["active"] = bool(existing.get("active", True))
            response = self.deployment_service.request_json("PUT", f"/api/providers/{client_id}", body)
        return str(response.get("id") if isinstance(response, dict) else client_id)

    def archive_provider(self, provider_id: int | str) -> None:
        if not self.uses_server_backend():
            raise RuntimeError("Use the local database archive method for local providers.")
        self.deployment_service.request_json("POST", f"/api/providers/{provider_id}/archive", {})

    def unarchive_provider(self, provider_id: int | str) -> None:
        if not self.uses_server_backend():
            raise RuntimeError("Use the local database unarchive method for local providers.")
        self.deployment_service.request_json("POST", f"/api/providers/{provider_id}/unarchive", {})

    def _list_providers(self, provider_type: str, status_filter: str) -> list[dict[str, Any]]:
        query = parse.urlencode({"provider_type": provider_type, "status_filter": status_filter})
        payload = self.deployment_service.request_json("GET", f"/api/providers?{query}")
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def _get_provider(self, provider_id: int | str) -> dict[str, Any] | None:
        payload = self.deployment_service.request_json("GET", f"/api/providers/{provider_id}", allow_404=True)
        return payload if isinstance(payload, dict) else None
