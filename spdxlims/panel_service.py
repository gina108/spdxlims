from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib import parse

from spdxlims.database import Database, PanelRecord
from spdxlims.deployment import DeploymentService


@dataclass(slots=True)
class PanelService:
    database: Database
    deployment_service: DeploymentService

    def uses_server_backend(self) -> bool:
        return self.deployment_service.load().mode == 'server'

    def list_panels(self, *, status_filter: str = 'active') -> list[PanelRecord]:
        config = self.deployment_service.load()
        if config.mode != 'server':
            return self.database.list_panels(status_filter=status_filter)
        query = parse.urlencode({'status_filter': status_filter})
        payload = self.deployment_service.request_json('GET', f'/api/panels?{query}')
        if not isinstance(payload, list):
            return []
        return [
            PanelRecord(
                id=str(item.get('id') or ''),
                code=str(item.get('code') or ''),
                name=str(item.get('name') or ''),
                specimen_type=str(item.get('specimen_type') or '') or None,
                method=str(item.get('method') or '') or None,
                is_active=int(bool(item.get('is_active', True))),
                test_names=str(item.get('test_names') or ''),
            )
            for item in payload if isinstance(item, dict)
        ]

    def get_panel_detail(self, panel_id: int | str, *, include_inactive: bool = False) -> dict[str, Any] | None:
        config = self.deployment_service.load()
        if config.mode != 'server':
            return self.database.get_panel_detail(int(panel_id), include_inactive=include_inactive)
        query = parse.urlencode({'include_inactive': 'true' if include_inactive else 'false'})
        payload = self.deployment_service.request_json('GET', f'/api/panels/{panel_id}?{query}', allow_404=True)
        return payload if isinstance(payload, dict) else None

    def create_panel(self, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str = "", method: str = "") -> None:
        config = self.deployment_service.load()
        if config.mode != 'server':
            self.database.create_panel(code, name, panel_items, specimen_type=specimen_type, method=method)
            return
        self.deployment_service.request_json('POST', '/api/panels', self._panel_payload(code, name, panel_items, specimen_type, method))

    def update_panel(self, panel_id: int | str, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str = "", method: str = "") -> None:
        config = self.deployment_service.load()
        if config.mode != 'server':
            self.database.update_panel(int(panel_id), code, name, panel_items, specimen_type=specimen_type, method=method)
            return
        self.deployment_service.request_json('PUT', f'/api/panels/{panel_id}', self._panel_payload(code, name, panel_items, specimen_type, method))

    def archive_panel(self, panel_id: int | str) -> None:
        config = self.deployment_service.load()
        if config.mode != 'server':
            self.database.archive_panel(int(panel_id))
            return
        self.deployment_service.request_json('POST', f'/api/panels/{panel_id}/archive', {})

    def unarchive_panel(self, panel_id: int | str) -> None:
        config = self.deployment_service.load()
        if config.mode != 'server':
            self.database.unarchive_panel(int(panel_id))
            return
        self.deployment_service.request_json('POST', f'/api/panels/{panel_id}/unarchive', {})

    def list_test_choices(self) -> list[tuple[str, str]] | list[tuple[int, str]]:
        config = self.deployment_service.load()
        if config.mode != 'server':
            return self.database.list_test_choices()
        payload = self.deployment_service.request_json('GET', '/api/orders/test-choices')
        if not isinstance(payload, list):
            return []
        return [
            (str(item.get('id') or ''), str(item.get('label') or ''))
            for item in payload if isinstance(item, dict) and item.get('id') and item.get('label')
        ]

    def _panel_payload(self, code: str, name: str, panel_items: list[dict[str, Any]], specimen_type: str = "", method: str = "") -> dict[str, Any]:
        return {
            'code': code.strip(),
            'name': name.strip(),
            'specimen_type': specimen_type.strip(),
            'method': method.strip(),
            'items': [
                {
                    'item_type': str(item.get('item_type') or 'test'),
                    'test_id': str(item.get('test_id')) if item.get('test_id') is not None else None,
                    'heading_text': str(item.get('heading_text') or item.get('label') or '').strip() or None,
                    'sort_order': index,
                    'label': str(item.get('label') or ''),
                }
                for index, item in enumerate(panel_items)
            ],
        }

