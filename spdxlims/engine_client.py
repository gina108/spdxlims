"""Reads the instrument engine, directly or through the backend.

The engine binds loopback on the PC wired to the analyzers, so a workstation
has no route to it and shows every instrument as disconnected. The backend runs
on that same PC and the workstation already talks to it over an authenticated,
firewalled port, so on those installs the reads are relayed instead.

Which transport is used is decided by the install, not by probing: a remote
client (server mode against a non-loopback server_url) relays; everything else
talks to the engine directly. See spdxlims.engine_identity.is_remote_client.

Reads only. Opening and closing sessions stays on the machine that owns the
hardware - the relay deliberately exposes no way to do it.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from spdxlims.engine_identity import is_remote_client
from spdxlims.instrument_broadcast import get_engine_url


class EngineUnavailable(RuntimeError):
    """The engine could not be reached, by either route."""


class EngineClient:
    def __init__(self, deployment_service: Any = None, engine_url: str | None = None, *, timeout: float = 6.0) -> None:
        self.deployment_service = deployment_service
        self.engine_url = (engine_url or get_engine_url()).rstrip("/")
        self.timeout = timeout

    @property
    def relayed(self) -> bool:
        """True when reads go through the backend rather than straight to the engine."""
        return self.deployment_service is not None and is_remote_client()

    # ── Direct ───────────────────────────────────────────────────────────

    def _direct(self, path: str, *, method: str = "GET", body: dict | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.engine_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise EngineUnavailable(detail or f"engine returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EngineUnavailable(str(getattr(exc, "reason", exc))) from exc
        try:
            return json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError as exc:
            raise EngineUnavailable("engine returned invalid JSON") from exc

    # ── Relayed ──────────────────────────────────────────────────────────

    def _relayed(self, path: str, *, method: str = "GET", body: dict | None = None) -> Any:
        try:
            return self.deployment_service.request_json(method, f"/api/instruments{path}", body)
        except RuntimeError as exc:
            raise EngineUnavailable(str(exc)) from exc

    def _call(self, path: str, *, method: str = "GET", body: dict | None = None) -> Any:
        if self.relayed:
            return self._relayed(path, method=method, body=body)
        return self._direct(path, method=method, body=body)

    # ── Operations ───────────────────────────────────────────────────────

    def health(self) -> dict | None:
        """The engine's health, or None when it cannot be reached."""
        try:
            payload = self._call("/health") if self.relayed else self._direct("/api/v1/health")
        except EngineUnavailable:
            return None
        if isinstance(payload, dict) and str(payload.get("status") or "") == "offline":
            return None  # the relay reached the backend, but the engine is down
        return payload if isinstance(payload, dict) else None

    def runtime_status(self) -> dict | None:
        payload = self._call("/status") if self.relayed else self._direct("/api/v1/runtime/status")
        return payload if isinstance(payload, dict) else None

    def captures(self, *, limit: int = 100, profile_id: str = "") -> list[dict]:
        query: dict[str, Any] = {"limit": limit}
        if (profile_id or "").strip():
            query["profile_id"] = profile_id.strip()
        encoded = urllib.parse.urlencode(query)
        payload = self._call(f"/captures?{encoded}") if self.relayed else self._direct(f"/api/v1/captures?{encoded}")
        return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []

    def replay(self, capture_id: str, profile_id: str = "") -> Any:
        body = {"capture_id": capture_id, "profile_id": profile_id}
        if self.relayed:
            return self._call("/replay", method="POST", body=body)
        return self._direct("/api/v1/replay", method="POST", body=body)
