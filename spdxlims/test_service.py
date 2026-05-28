from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib import parse

from spdxlims.database import Database, TestRecord
from spdxlims.deployment import DeploymentService


@dataclass(slots=True)
class TestService:
    database: Database
    deployment_service: DeploymentService

    def uses_server_backend(self) -> bool:
        return self.deployment_service.load().mode == 'server'

    def list_tests(self, *, status_filter: str = 'active') -> list[TestRecord]:
        config = self.deployment_service.load()
        if config.mode != 'server':
            return self.database.list_tests(status_filter=status_filter)
        query = parse.urlencode({'status_filter': status_filter})
        payload = self.deployment_service.request_json('GET', f'/api/tests?{query}')
        if not isinstance(payload, list):
            return []
        return [
            TestRecord(
                id=str(item.get('id') or ''),
                code=str(item.get('code') or ''),
                name=str(item.get('name') or ''),
                category_name=item.get('category_name'),
                specimen_type=item.get('specimen_type'),
                method=item.get('method'),
                result_kind=str(item.get('result_kind') or 'text'),
                select_options=item.get('select_options'),
                default_result_value=item.get('default_result_value'),
                price=float(item.get('price') or 0),
                is_active=int(bool(item.get('is_active', True))),
                range_count=int(item.get('range_count') or 0),
            )
            for item in payload if isinstance(item, dict)
        ]

    def get_test_detail(self, test_id: int | str) -> dict[str, Any] | None:
        config = self.deployment_service.load()
        if config.mode != 'server':
            return self.database.get_test_detail(int(test_id))
        payload = self.deployment_service.request_json('GET', f'/api/tests/{test_id}', allow_404=True)
        return payload if isinstance(payload, dict) else None

    def create_test(self, payload: dict[str, Any], reference_ranges: list[dict[str, Any]]) -> None:
        config = self.deployment_service.load()
        if config.mode != 'server':
            self.database.create_test(payload, reference_ranges)
            return
        self.deployment_service.request_json('POST', '/api/tests', self._build_payload(payload, reference_ranges))

    def update_test(self, test_id: int | str, payload: dict[str, Any], reference_ranges: list[dict[str, Any]]) -> None:
        config = self.deployment_service.load()
        if config.mode != 'server':
            self.database.update_test(int(test_id), payload, reference_ranges)
            return
        existing = self.get_test_detail(test_id) or {}
        body = self._build_payload(payload, reference_ranges)
        body['price'] = float(existing.get('price') or 0)
        self.deployment_service.request_json('PUT', f'/api/tests/{test_id}', body)

    def archive_test(self, test_id: int | str) -> None:
        config = self.deployment_service.load()
        if config.mode != 'server':
            self.database.archive_test(int(test_id))
            return
        self.deployment_service.request_json('POST', f'/api/tests/{test_id}/archive', {})

    def unarchive_test(self, test_id: int | str) -> None:
        config = self.deployment_service.load()
        if config.mode != 'server':
            self.database.unarchive_test(int(test_id))
            return
        self.deployment_service.request_json('POST', f'/api/tests/{test_id}/unarchive', {})

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

    def deserialize_select_options(self, raw_value: str | None) -> list[str]:
        return self.database.deserialize_select_options(raw_value)

    def _build_payload(self, payload: dict[str, Any], reference_ranges: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            'code': str(payload.get('code') or '').strip(),
            'name': str(payload.get('name') or '').strip(),
            'category_name': str(payload.get('category_name') or '').strip(),
            'specimen_type': str(payload.get('specimen_type') or '').strip(),
            'method': str(payload.get('method') or '').strip(),
            'result_kind': str(payload.get('result_kind') or 'text'),
            'select_options': [str(option).strip() for option in (payload.get('select_options') or []) if str(option).strip()],
            'default_result_value': str(payload.get('default_result_value') or '').strip(),
            'price': float(payload.get('price') or 0),
            'reference_ranges': [
                {
                    'sex': reference.get('sex'),
                    'age_min_days': reference.get('age_min_days'),
                    'age_max_days': reference.get('age_max_days'),
                    'lower_value': reference.get('lower_value'),
                    'upper_value': reference.get('upper_value'),
                    'unit': reference.get('unit') or '',
                    'reference_text': reference.get('reference_text') or '',
                }
                for reference in reference_ranges
            ],
        }

