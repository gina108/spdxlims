from __future__ import annotations

import json

import pytest

from spdxlims.deployment import DeploymentService
from spdxlims.server_client import LoginResult, ServerAuthError


class FakeClient:
    """Stands in for ServerClient, scripting one response per request."""

    def __init__(self, responses: list, *, login_ok: bool = True) -> None:
        self.responses = responses
        self.login_ok = login_ok
        self.requests: list[tuple[str, str | None]] = []
        self.logins = 0

    def request_json(self, server_url, method, path, *, token=None, json_body=None, timeout_seconds=None, allow_404=False):
        self.requests.append((path, token))
        outcome = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def login(self, server_url, email, password, *, timeout_seconds=None):
        self.logins += 1
        if not self.login_ok:
            raise RuntimeError("bad credentials")
        return LoginResult(access_token=f"token-{self.logins}", email=email, user_id="u1", role="admin")


@pytest.fixture()
def service(tmp_path):
    config = tmp_path / "deployment.json"
    config.write_text(
        json.dumps({
            "mode": "server",
            "server_url": "http://10.0.0.10:8001",
            "email": "admin@example.test",
            "password": "secret",
        }),
        encoding="utf-8",
    )
    return DeploymentService(config)


def test_expired_token_is_replaced_and_the_request_retried(service):
    """The bug this fixes: an app left open past the 8h token lifetime."""
    service._client = FakeClient([ServerAuthError("expired"), {"ok": True}])
    service.login("admin@example.test", "secret")
    stale = service.access_token

    assert service.request_json("GET", "/api/thing") == {"ok": True}

    assert service._client.logins == 2          # original + one re-login
    assert len(service._client.requests) == 2   # original + one retry
    assert service.access_token != stale        # a fresh token is in use
    assert service._client.requests[1][1] == service.access_token


def test_retry_uses_the_new_token_not_the_dead_one(service):
    service._client = FakeClient([ServerAuthError("expired"), {"ok": True}])
    service.login("admin@example.test", "secret")
    service.request_json("GET", "/api/thing")
    sent_tokens = [token for _, token in service._client.requests]
    assert sent_tokens[0] != sent_tokens[1]


def test_auth_error_propagates_when_re_login_fails(service):
    service._client = FakeClient([ServerAuthError("expired")], login_ok=False)
    service._access_token = "stale"
    with pytest.raises(ServerAuthError):
        service.request_json("GET", "/api/thing")


def test_a_successful_request_never_logs_in_again(service):
    service._client = FakeClient([{"ok": True}])
    service.login("admin@example.test", "secret")
    service.request_json("GET", "/api/thing")
    assert service._client.logins == 1
    assert len(service._client.requests) == 1


def test_permission_errors_are_not_retried(service):
    """403 means authenticated but not allowed - re-logging in would mask it."""
    service._client = FakeClient([RuntimeError("You do not have permission")])
    service.login("admin@example.test", "secret")
    with pytest.raises(RuntimeError) as excinfo:
        service.request_json("GET", "/api/thing")
    assert not isinstance(excinfo.value, ServerAuthError)
    assert len(service._client.requests) == 1
    assert service._client.logins == 1


def test_other_server_errors_are_not_retried(service):
    service._client = FakeClient([RuntimeError("boom")])
    service.login("admin@example.test", "secret")
    with pytest.raises(RuntimeError):
        service.request_json("GET", "/api/thing")
    assert len(service._client.requests) == 1


def test_missing_token_triggers_a_login_before_giving_up(service):
    """After a failed re-login the token is gone; the next call must try again."""
    service._client = FakeClient([{"ok": True}])
    assert service.access_token is None
    assert service.request_json("GET", "/api/thing") == {"ok": True}
    assert service._client.logins == 1


def test_missing_token_with_unusable_credentials_returns_none(service):
    service._client = FakeClient([{"ok": True}], login_ok=False)
    assert service.request_json("GET", "/api/thing") is None
    assert service._client.requests == []


def test_local_mode_is_untouched(tmp_path):
    config = tmp_path / "deployment.json"
    config.write_text(json.dumps({"mode": "local"}), encoding="utf-8")
    service = DeploymentService(config)
    service._client = FakeClient([{"ok": True}])
    assert service.request_json("GET", "/api/thing") == {"ok": True}
    assert service._client.logins == 0


def test_auth_error_is_still_caught_as_runtime_error():
    """Existing handlers use `except RuntimeError`; they must keep working."""
    assert issubclass(ServerAuthError, RuntimeError)
