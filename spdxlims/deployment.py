from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from spdxlims.server_client import LoginResult, ServerClient, ServerHealthResult


@dataclass(slots=True)
class DeploymentConfig:
    mode: str = "local"
    server_url: str = "http://127.0.0.1:8001"
    api_timeout_seconds: float = 5.0

    @classmethod
    def from_dict(cls, raw: dict[str, object] | None) -> "DeploymentConfig":
        raw = raw or {}
        mode = str(raw.get("mode") or "local").strip().lower()
        if mode not in {"local", "server"}:
            mode = "local"
        server_url = str(raw.get("server_url") or "http://127.0.0.1:8001").strip() or "http://127.0.0.1:8001"
        timeout_raw = raw.get("api_timeout_seconds", 5.0)
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError):
            timeout = 5.0
        return cls(mode=mode, server_url=server_url.rstrip("/"), api_timeout_seconds=max(timeout, 1.0))


class DeploymentService:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._client = ServerClient()
        self._access_token: str | None = None
        self._session_email: str | None = None
        self._session_role: str | None = None

    def load(self) -> DeploymentConfig:
        if not self.config_path.exists():
            return DeploymentConfig()
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DeploymentConfig()
        return DeploymentConfig.from_dict(payload if isinstance(payload, dict) else None)

    def save(self, config: DeploymentConfig) -> DeploymentConfig:
        normalized = DeploymentConfig.from_dict(asdict(config))
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(asdict(normalized), indent=2), encoding="utf-8")
        return normalized

    def ping(self, server_url: str, timeout_seconds: float | None = None) -> ServerHealthResult:
        client = self._client if timeout_seconds is None else ServerClient(timeout_seconds=timeout_seconds)
        return client.ping_health(server_url)

    def login(self, email: str, password: str) -> LoginResult:
        config = self.load()
        result = self._client.login(
            config.server_url,
            email,
            password,
            timeout_seconds=config.api_timeout_seconds,
        )
        self._access_token = result.access_token
        self._session_email = result.email
        self._session_role = result.role
        return result

    def logout(self) -> None:
        self._access_token = None
        self._session_email = None
        self._session_role = None

    def is_authenticated(self) -> bool:
        return bool(self._access_token)

    def session_label(self) -> str:
        if not self._session_email:
            return ""
        role_suffix = f" ({self._session_role})" if self._session_role else ""
        return f"{self._session_email}{role_suffix}"

    def session_role(self) -> str:
        return self._session_role or ""

    def has_any_role(self, *roles: str) -> bool:
        return bool(self._session_role and self._session_role in roles)

    def request_json(self, method: str, path: str, body: dict[str, object] | None = None, *, allow_404: bool = False):
        config = self.load()
        if config.mode == "server" and not self._access_token:
            raise RuntimeError("Log in to the server from Settings before using server mode.")
        return self._client.request_json(
            config.server_url,
            method,
            path,
            token=self._access_token,
            json_body=body,
            timeout_seconds=config.api_timeout_seconds,
            allow_404=allow_404,
        )
