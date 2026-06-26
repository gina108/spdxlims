from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
        raise RuntimeError('Filtered report generation is currently available only in local mode.')

    def get_live_report_preview(self, order_id: int | str) -> dict[str, Any] | None:
        if self._is_local():
            return self.database.get_live_report_preview(int(order_id))
        preview = self.deployment_service.request_json('GET', f'/api/reports/orders/{order_id}/live-preview', allow_404=True)
        return preview if isinstance(preview, dict) else None

    def get_saved_report_preview(self, order_id: int | str) -> dict[str, Any] | None:
        if self._is_local():
            return self.database.get_saved_report_preview(int(order_id))
        preview = self.deployment_service.request_json('GET', f'/api/reports/orders/{order_id}/saved-preview', allow_404=True)
        return preview if isinstance(preview, dict) else None

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
        raise RuntimeError('Deleting saved reports is currently available only in local mode.')
