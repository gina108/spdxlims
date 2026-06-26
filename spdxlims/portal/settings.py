"""On-disk settings and test-id mapping for the PORTAL integration.

Stored under ``<data_dir>/portal/`` so it lives beside the rest of the app's
local state. The shared secret is kept here (the file is in the app data dir,
not in source control) mirroring how server credentials are handled elsewhere.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class PortalSettings:
    base_url: str = ""
    shared_secret: str = ""
    poll_interval_seconds: int = 60

    def is_configured(self) -> bool:
        return bool(self.base_url.strip()) and bool(self.shared_secret.strip())


class PortalStore:
    """Reads/writes portal settings and the portal->LIS test-id mapping."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir) / "portal"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._settings_path = self._dir / "settings.json"
        self._mapping_path = self._dir / "test_mapping.json"

    # -- settings ----------------------------------------------------------
    def load_settings(self) -> PortalSettings:
        data = self._read_json(self._settings_path)
        if not isinstance(data, dict):
            return PortalSettings()
        return PortalSettings(
            base_url=str(data.get("base_url") or ""),
            shared_secret=str(data.get("shared_secret") or ""),
            poll_interval_seconds=int(data.get("poll_interval_seconds") or 60),
        )

    def save_settings(self, settings: PortalSettings) -> None:
        self._write_json(self._settings_path, asdict(settings))

    # -- test-id mapping ---------------------------------------------------
    def load_mapping(self) -> dict[str, str]:
        """Returns {portal_test_id (str): lis_test_id (str)}."""
        data = self._read_json(self._mapping_path)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items() if v not in (None, "")}

    def save_mapping(self, mapping: dict[str, str]) -> None:
        self._write_json(self._mapping_path, {str(k): str(v) for k, v in mapping.items()})

    def update_mapping(self, additions: dict[str, str]) -> dict[str, str]:
        mapping = self.load_mapping()
        for portal_id, lis_id in additions.items():
            if lis_id:
                mapping[str(portal_id)] = str(lis_id)
        self.save_mapping(mapping)
        return mapping

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _read_json(path: Path) -> object:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
