from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from spdxlims.deployment import DeploymentService


@dataclass(slots=True)
class LabProfileService:
    deployment_service: DeploymentService

    def load_profile(self) -> dict[str, str]:
        payload = self.deployment_service.request_json('GET', '/api/lab-profile')
        if not isinstance(payload, dict):
            raise RuntimeError('Server did not return a valid lab profile.')
        return {
            'lab_name': str(payload.get('lab_name') or ''),
            'address': str(payload.get('address') or ''),
            'phone': str(payload.get('phone') or ''),
            'email': str(payload.get('email') or ''),
            'logo_path': str(payload.get('logo_path') or ''),
            'header_image_path': str(payload.get('header_image_path') or ''),
            'footer_signature_image_path': str(payload.get('footer_signature_image_path') or ''),
            'report_footer': str(payload.get('report_footer') or ''),
            'director_name': str(payload.get('director_name') or ''),
            'director_license': str(payload.get('director_license') or ''),
        }

    def save_profile(self, payload: dict[str, str]) -> dict[str, str]:
        body = {
            'lab_name': payload.get('lab_name', ''),
            'address': payload.get('address', ''),
            'phone': payload.get('phone', ''),
            'email': payload.get('email', ''),
            'report_footer': payload.get('report_footer', ''),
            'director_name': payload.get('director_name', ''),
            'director_license': payload.get('director_license', ''),
            'logo': self._encode_asset(payload.get('logo_path', '')),
            'header': self._encode_asset(payload.get('header_image_path', '')),
            'footer_signature': self._encode_asset(payload.get('footer_signature_image_path', '')),
        }
        response = self.deployment_service.request_json('PUT', '/api/lab-profile', body)
        if not isinstance(response, dict):
            raise RuntimeError('Server did not return the saved lab profile.')
        return {
            'lab_name': str(response.get('lab_name') or ''),
            'address': str(response.get('address') or ''),
            'phone': str(response.get('phone') or ''),
            'email': str(response.get('email') or ''),
            'logo_path': str(response.get('logo_path') or ''),
            'header_image_path': str(response.get('header_image_path') or ''),
            'footer_signature_image_path': str(response.get('footer_signature_image_path') or ''),
            'report_footer': str(response.get('report_footer') or ''),
            'director_name': str(response.get('director_name') or ''),
            'director_license': str(response.get('director_license') or ''),
        }

    def _encode_asset(self, raw_path: str) -> dict[str, str] | None:
        path = Path(raw_path.strip()) if raw_path else None
        if path is None or not path.exists() or not path.is_file():
            return None
        return {
            'filename': path.name,
            'content_b64': base64.b64encode(path.read_bytes()).decode('ascii'),
        }

