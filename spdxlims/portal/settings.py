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
    auto_import: bool = False

    def is_configured(self) -> bool:
        return bool(self.base_url.strip()) and bool(self.shared_secret.strip())


class PortalStore:
    """Reads/writes portal settings and the portal->LIS test-id mapping."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir) / "portal"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._settings_path = self._dir / "settings.json"
        self._mapping_path = self._dir / "test_mapping.json"
        self._links_path = self._dir / "imported_orders.json"
        self._pending_dir = self._dir / "pending_results"

    # -- settings ----------------------------------------------------------
    def load_settings(self) -> PortalSettings:
        data = self._read_json(self._settings_path)
        if not isinstance(data, dict):
            return PortalSettings()
        return PortalSettings(
            base_url=str(data.get("base_url") or ""),
            shared_secret=str(data.get("shared_secret") or ""),
            poll_interval_seconds=int(data.get("poll_interval_seconds") or 60),
            auto_import=bool(data.get("auto_import", False)),
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

    # -- import links (LIS order id -> portal order id) --------------------
    def record_import_link(self, lis_order_id: object, portal_order_id: int) -> None:
        links = self._read_json(self._links_path)
        links = links if isinstance(links, dict) else {}
        links[str(lis_order_id)] = int(portal_order_id)
        self._write_json(self._links_path, links)

    def portal_order_id_for(self, lis_order_id: object) -> int | None:
        links = self._read_json(self._links_path)
        if not isinstance(links, dict):
            return None
        value = links.get(str(lis_order_id))
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    # -- pending result uploads (stashed report PDFs) ---------------------
    # A finalized PDF that couldn't be uploaded (portal offline) is stashed here
    # and retried later; the portal order id is resolved from the link map above.
    def stash_pending_result(self, lis_order_id: object, pdf_bytes: bytes) -> None:
        self._pending_dir.mkdir(parents=True, exist_ok=True)
        self._pending_path(lis_order_id).write_bytes(pdf_bytes)

    def clear_pending_result(self, lis_order_id: object) -> None:
        try:
            self._pending_path(lis_order_id).unlink()
        except OSError:
            pass

    def list_pending_results(self) -> list[tuple[str, bytes]]:
        if not self._pending_dir.exists():
            return []
        results: list[tuple[str, bytes]] = []
        for path in sorted(self._pending_dir.glob("*.pdf")):
            try:
                results.append((path.stem, path.read_bytes()))
            except OSError:
                continue
        return results

    def _pending_path(self, lis_order_id: object) -> Path:
        safe = "".join(ch for ch in str(lis_order_id) if ch.isalnum() or ch in ("-", "_")) or "order"
        return self._pending_dir / f"{safe}.pdf"

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
