from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spdxlims.service_base import ServiceBase


def _subjects_payload(subjects: list[tuple[str, Any]] | None) -> list[list[Any]]:
    payload: list[list[Any]] = []
    for kind, value in subjects or []:
        if isinstance(value, (list, tuple)):
            payload.append([str(kind), [str(v) for v in value]])
        else:
            payload.append([str(kind), None if value is None else str(value)])
    return payload


@dataclass(slots=True)
class StatisticsService(ServiceBase):
    """Operational/analytics reports, backed by local SQLite or the server API."""

    def _report(self, path: str, date_from: str, date_to: str, client_id: Any, subjects: Any) -> list[dict[str, Any]]:
        body = {
            "date_from": date_from or "",
            "date_to": date_to or "",
            "client_id": None if client_id in (None, "") else str(client_id),
            "subjects": _subjects_payload(subjects),
        }
        payload = self.deployment_service.request_json("POST", path, body)
        return [dict(item) for item in payload] if isinstance(payload, list) else []

    def report_test_volume(self, date_from: str = "", date_to: str = "", client_id: Any = None, subjects: Any = None) -> list[dict[str, Any]]:
        if self._is_local():
            return self.database.report_test_volume(date_from, date_to, client_id=client_id, subjects=subjects)
        return self._report("/api/statistics/test-volume", date_from, date_to, client_id, subjects)

    def report_panel_volume(self, date_from: str = "", date_to: str = "", client_id: Any = None, subjects: Any = None) -> list[dict[str, Any]]:
        if self._is_local():
            return self.database.report_panel_volume(date_from, date_to, client_id=client_id, subjects=subjects)
        return self._report("/api/statistics/panel-volume", date_from, date_to, client_id, subjects)

    def report_client_volume(self, date_from: str = "", date_to: str = "", subjects: Any = None) -> list[dict[str, Any]]:
        if self._is_local():
            return self.database.report_client_volume(date_from, date_to, subjects=subjects)
        return self._report("/api/statistics/client-volume", date_from, date_to, None, subjects)

    def report_doctor_volume(self, date_from: str = "", date_to: str = "", subjects: Any = None) -> list[dict[str, Any]]:
        if self._is_local():
            return self.database.report_doctor_volume(date_from, date_to, subjects=subjects)
        return self._report("/api/statistics/doctor-volume", date_from, date_to, None, subjects)

    def report_inventory_usage(self, date_from: str = "", date_to: str = "") -> list[dict[str, Any]]:
        if self._is_local():
            return self.database.report_inventory_usage(date_from, date_to)
        # Inventory is not yet available over the server API; return nothing rather
        # than reading this workstation's local database.
        return []

    def list_client_choices(self, *, active_only: bool = False) -> list[tuple[Any, str]]:
        if self._is_local():
            return self.database.list_client_choices(active_only=active_only)
        payload = self.deployment_service.request_json(
            "GET", f"/api/statistics/clients?active_only={'true' if active_only else 'false'}"
        )
        return [(item.get("id"), str(item.get("label") or "")) for item in payload] if isinstance(payload, list) else []

    def list_doctor_choices(self, *, active_only: bool = False) -> list[tuple[Any, str]]:
        if self._is_local():
            return self.database.list_doctor_choices(active_only=active_only)
        payload = self.deployment_service.request_json(
            "GET", f"/api/statistics/doctors?active_only={'true' if active_only else 'false'}"
        )
        return [(item.get("id"), str(item.get("label") or "")) for item in payload] if isinstance(payload, list) else []

    def list_test_choices(self) -> list[tuple[Any, str]]:
        if self._is_local():
            return self.database.list_test_choices()
        payload = self.deployment_service.request_json("GET", "/api/statistics/tests")
        return [(item.get("id"), str(item.get("label") or "")) for item in payload] if isinstance(payload, list) else []

    def list_panel_filter_options(self) -> list[tuple[list[str], str]]:
        if self._is_local():
            return self.database.list_panel_filter_options()
        payload = self.deployment_service.request_json("GET", "/api/statistics/panel-filter-options")
        if not isinstance(payload, list):
            return []
        return [([str(f) for f in (item.get("forms") or [])], str(item.get("label") or "")) for item in payload]
