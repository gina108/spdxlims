from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib import parse

from spdxlims.database import ResultWorkflowRecord
from spdxlims.service_base import ServiceBase


@dataclass(slots=True)
class ReportService(ServiceBase):

    def find_report_order_id_by_barcode(self, barcode: str) -> int | str | None:
        normalized = barcode.strip()
        if not normalized:
            return None
        if self._is_local():
            lookup = self.database.find_order_by_number(normalized)
            return lookup.id if lookup is not None else None
        payload = self.deployment_service.request_json('GET', f'/api/orders/by-number/{normalized}', allow_404=True)
        if not isinstance(payload, dict):
            return None
        order_id = payload.get('id')
        return str(order_id) if order_id else None

    def list_report_order_choices(self) -> list[tuple[str, str]] | list[tuple[int, str]]:
        if self._is_local():
            return self.database.list_report_order_choices()
        payload = self.deployment_service.request_json('GET', '/api/reports/order-choices')
        if not isinstance(payload, list):
            return []
        return [
            (str(item.get('id') or ''), str(item.get('label') or ''))
            for item in payload
            if isinstance(item, dict) and item.get('id') and item.get('label')
        ]

    def list_filtered_report_order_choices(
        self,
        *,
        client_id: int | None = None,
        test_id: int | None = None,
        date_from: str = "",
        date_to: str = "",
    ) -> list[tuple[str, str]] | list[tuple[int, str]]:
        if self._is_local():
            return self.database.list_filtered_report_order_choices(
                client_id=client_id,
                test_id=test_id,
                date_from=date_from,
                date_to=date_to,
            )
        query = parse.urlencode(
            {
                key: value
                for key, value in (
                    ("client_id", "" if client_id is None else str(client_id)),
                    ("test_id", "" if test_id is None else str(test_id)),
                    ("date_from", date_from or ""),
                    ("date_to", date_to or ""),
                )
                if value
            }
        )
        path = "/api/reports/order-choices" + (f"?{query}" if query else "")
        payload = self.deployment_service.request_json("GET", path)
        if not isinstance(payload, list):
            return []
        return [
            (str(item.get("id") or ""), str(item.get("label") or ""))
            for item in payload
            if isinstance(item, dict) and item.get("id") and item.get("label")
        ]

    def list_results_workflow_orders(self) -> list[ResultWorkflowRecord]:
        """Orders for the Resultados workflow table. Local mode reads SQLite; server
        mode fetches from the backend so the rows carry the server's UUID order ids
        (which the preview/finalize endpoints require)."""
        if self._is_local():
            return self.database.list_results_workflow_orders()
        payload = self.deployment_service.request_json('GET', '/api/reports/results-workflow')
        if not isinstance(payload, list):
            return []
        records: list[ResultWorkflowRecord] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            records.append(
                ResultWorkflowRecord(
                    id=str(item.get('id') or ''),
                    order_number=str(item.get('order_number') or ''),
                    order_date=str(item.get('order_date') or ''),
                    patient_name=str(item.get('patient_name') or ''),
                    patient_phone=item.get('patient_phone'),
                    doctor_name=item.get('doctor_name'),
                    client_name=item.get('client_name'),
                    client_phone=item.get('client_phone'),
                    report_version=item.get('report_version'),
                    report_finalized_at=item.get('report_finalized_at'),
                    result_count=int(item.get('result_count') or 0),
                    completed_result_count=int(item.get('completed_result_count') or 0),
                    report_outdated=int(item.get('report_outdated') or 0),
                )
            )
        return records

    def get_live_report_preview(self, order_id: int | str) -> dict[str, Any] | None:
        if self._is_local():
            return self.database.get_live_report_preview(int(order_id))
        preview = self.deployment_service.request_json('GET', f'/api/reports/orders/{order_id}/live-preview', allow_404=True)
        return self._normalize_server_preview(preview)

    def get_saved_report_preview(self, order_id: int | str) -> dict[str, Any] | None:
        if self._is_local():
            return self.database.get_saved_report_preview(int(order_id))
        preview = self.deployment_service.request_json('GET', f'/api/reports/orders/{order_id}/saved-preview', allow_404=True)
        return self._normalize_server_preview(preview)

    @staticmethod
    def _normalize_server_preview(preview: Any) -> dict[str, Any] | None:
        """Flatten the server's nested report_settings into the top-level preview
        dict so the shared report renderer (which reads styling keys at the top
        level) works identically in local and server mode."""
        if not isinstance(preview, dict):
            return None
        settings = preview.pop('report_settings', None)
        if isinstance(settings, dict):
            for key, value in settings.items():
                preview.setdefault(key, value)
        return preview

    def finalize_report(
        self,
        order_id: int | str,
        *,
        header_image_path: str | None = None,
        footer_signature_image_path: str | None = None,
        preview_override: dict[str, Any] | None = None,
    ) -> None:
        if self._is_local():
            self.database.finalize_report(
                int(order_id),
                header_image_path=header_image_path,
                footer_signature_image_path=footer_signature_image_path,
                preview_override=preview_override,
            )
            return
        body: dict[str, Any] = {
            'header_image_path': header_image_path,
            'footer_signature_image_path': footer_signature_image_path,
        }
        if preview_override is not None:
            body['preview_override'] = preview_override
        self.deployment_service.request_json('POST', f'/api/reports/orders/{order_id}/finalize', body)

    def delete_saved_report(self, order_id: int | str) -> None:
        if self._is_local():
            self.database.delete_saved_report(int(order_id))
            return
        self.deployment_service.request_json('DELETE', f'/api/reports/orders/{order_id}')
