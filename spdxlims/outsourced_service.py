from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from spdxlims.service_base import ServiceBase


@dataclass(slots=True)
class OutsourcedService(ServiceBase):
    """Outsourced-PDF panel authoring, backed by local SQLite or the server API.

    The local paths call the same Database methods (with the historical int()
    coercion) so local behaviour is unchanged; only the server paths are new.
    """

    def list_outsourced_order_choices(self) -> list[tuple[Any, str]]:
        if self._is_local():
            return self.database.list_outsourced_order_choices()
        payload = self.deployment_service.request_json('GET', '/api/outsourced/order-choices')
        if not isinstance(payload, list):
            return []
        return [
            (str(item.get('id')), str(item.get('label') or ''))
            for item in payload
            if isinstance(item, dict) and item.get('id')
        ]

    def list_outsourced_panels_for_order(self, order_id: Any) -> list[str]:
        if self._is_local():
            return self.database.list_outsourced_panels_for_order(int(order_id))
        payload = self.deployment_service.request_json('GET', f'/api/outsourced/orders/{order_id}/panels')
        return [str(item) for item in payload] if isinstance(payload, list) else []

    def list_outsourced_panel_extractions(self, order_id: Any, panel_label: str) -> list[dict[str, Any]]:
        if self._is_local():
            return self.database.list_outsourced_panel_extractions(int(order_id), str(panel_label))
        payload = self.deployment_service.request_json(
            'GET', f'/api/outsourced/orders/{order_id}/extractions?panel_label={quote(str(panel_label))}'
        )
        return [dict(item) for item in payload] if isinstance(payload, list) else []

    def append_outsourced_panel_extraction(
        self, order_id: Any, panel_label: str, source_pdf_path: str, page_label: str, rows: list[list[object]]
    ) -> Any:
        if self._is_local():
            return self.database.append_outsourced_panel_extraction(
                int(order_id), str(panel_label), source_pdf_path, page_label, rows
            )
        body = {
            'panel_label': str(panel_label),
            'source_pdf_path': str(source_pdf_path),
            'page_label': str(page_label or ''),
            'rows': [list(row) for row in rows],
        }
        response = self.deployment_service.request_json('POST', f'/api/outsourced/orders/{order_id}/extractions', body)
        return (response or {}).get('extraction_id') if isinstance(response, dict) else None

    def delete_outsourced_panel_extraction(self, extraction_id: Any) -> None:
        if self._is_local():
            self.database.delete_outsourced_panel_extraction(int(extraction_id))
            return
        self.deployment_service.request_json('DELETE', f'/api/outsourced/extractions/{extraction_id}')

    def replace_outsourced_panel_rows(self, order_id: Any, sections: list[dict[str, Any]]) -> None:
        if self._is_local():
            self.database.replace_outsourced_panel_rows(int(order_id), sections)
            return
        self.deployment_service.request_json(
            'PUT', f'/api/outsourced/orders/{order_id}/rows', {'sections': list(sections or [])}
        )
