from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


class ServerAuthError(RuntimeError):
    """The server rejected the token (HTTP 401).

    Subclasses RuntimeError so every existing ``except RuntimeError`` handler
    keeps catching it. It exists so the caller can tell "your token expired,
    log in again" from any other failure - tokens last 8 hours, and an app left
    open across a shift used to keep presenting a dead one until restarted.

    403 is deliberately NOT this: that means authenticated but not permitted,
    and logging in again would only hide a real permissions problem.
    """


@dataclass(slots=True)
class ServerHealthResult:
    ok: bool
    message: str
    status: str | None = None
    environment: str | None = None


@dataclass(slots=True)
class LoginResult:
    access_token: str
    email: str
    user_id: str
    role: str


class ServerClient:
    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self.timeout_seconds = timeout_seconds

    def ping_health(self, server_url: str) -> ServerHealthResult:
        normalized = server_url.strip().rstrip("/")
        if not normalized:
            return ServerHealthResult(ok=False, message="Server URL is required.")
        health_url = parse.urljoin(f"{normalized}/", "health")
        try:
            with request.urlopen(health_url, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return ServerHealthResult(ok=False, message=f"Server responded with HTTP {exc.code}.")
        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            return ServerHealthResult(ok=False, message=f"Could not reach server: {reason}")
        except TimeoutError:
            return ServerHealthResult(ok=False, message="Server health check timed out.")
        except json.JSONDecodeError:
            return ServerHealthResult(ok=False, message="Server response was not valid JSON.")

        status = str(payload.get("status") or "")
        environment = payload.get("env")
        if status.lower() != "ok":
            return ServerHealthResult(
                ok=False,
                message="Server responded, but health status was not ok.",
                status=status,
                environment=environment,
            )
        return ServerHealthResult(
            ok=True,
            message="Server is reachable.",
            status=status,
            environment=str(environment) if environment is not None else None,
        )

    def login(self, server_url: str, email: str, password: str, *, timeout_seconds: float | None = None) -> LoginResult:
        body = parse.urlencode({"username": email.strip(), "password": password}).encode("utf-8")
        payload = self.request_json(
            server_url,
            "POST",
            "/api/auth/login",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise RuntimeError("Server did not return a login token.")
        return LoginResult(
            access_token=str(payload["access_token"]),
            email=str(payload.get("email") or email),
            user_id=str(payload.get("user_id") or ""),
            role=str(payload.get("role") or ""),
        )

    def request_json(
        self,
        server_url: str,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: dict[str, Any] | None = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
        allow_404: bool = False,
    ) -> Any:
        normalized = server_url.strip().rstrip("/")
        if not normalized:
            raise RuntimeError("Server URL is not configured.")
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        data = body
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if token:
            request_headers["Authorization"] = f"Bearer {token}"

        req = request.Request(f"{normalized}{path}", data=data, headers=request_headers, method=method)
        try:
            with request.urlopen(req, timeout=timeout_seconds or self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            detail = exc.read().decode("utf-8", errors="ignore")
            message = self._format_http_error(exc.code, detail)
            if exc.code == 401:
                raise ServerAuthError(message) from exc
            raise RuntimeError(message) from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"Could not reach server: {reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("Server request timed out.") from exc

        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Server returned invalid JSON.") from exc

    @staticmethod
    def _format_http_error(status_code: int, detail: str) -> str:
        parsed_detail = detail
        try:
            payload = json.loads(detail)
            if isinstance(payload, dict) and payload.get("detail"):
                parsed_detail = str(payload["detail"])
        except json.JSONDecodeError:
            pass
        if status_code == 401:
            return parsed_detail or "Login is required or has expired."
        if status_code == 403:
            return parsed_detail or "You do not have permission to perform this action."
        return parsed_detail or f"Server responded with HTTP {status_code}."
