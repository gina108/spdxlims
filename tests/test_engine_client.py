from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from spdxlims.engine_client import EngineClient, EngineUnavailable


class FakeDeployment:
    """Captures what the backend relay was asked for."""

    def __init__(self, response=None, error: str | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, str, dict | None]] = []

    def request_json(self, method: str, path: str, body: dict | None = None):
        self.calls.append((method, path, body))
        if self.error:
            raise RuntimeError(self.error)
        return self.response


def _deployment_dir(mode: str, server_url: str) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    data = Path(tmp.name) / "data"
    data.mkdir()
    (data / "deployment.json").write_text(
        json.dumps({"mode": mode, "server_url": server_url}), encoding="utf-8"
    )
    return tmp


@pytest.fixture()
def as_workstation():
    """cwd where deployment.json points at a remote server."""
    tmp = _deployment_dir("server", "http://10.0.0.10:8001")
    cwd = os.getcwd()
    os.chdir(tmp.name)
    yield
    os.chdir(cwd)
    tmp.cleanup()


@pytest.fixture()
def as_lab_pc():
    """cwd where deployment.json is loopback - the machine wired to the analyzers."""
    tmp = _deployment_dir("server", "http://127.0.0.1:8001")
    cwd = os.getcwd()
    os.chdir(tmp.name)
    yield
    os.chdir(cwd)
    tmp.cleanup()


def test_workstation_relays_through_the_backend(as_workstation):
    deployment = FakeDeployment(response=[{"id": "cap_1"}])
    client = EngineClient(deployment, "http://127.0.0.1:9088")
    assert client.relayed is True
    assert client.captures(limit=5) == [{"id": "cap_1"}]
    method, path, _ = deployment.calls[0]
    assert method == "GET"
    assert path.startswith("/api/instruments/captures")
    assert "limit=5" in path


def test_lab_pc_talks_to_the_engine_directly(as_lab_pc):
    """Must not relay: this machine owns the engine and can reach it on loopback."""
    deployment = FakeDeployment(response=[{"id": "relayed"}])
    client = EngineClient(deployment, "http://127.0.0.1:9088")
    assert client.relayed is False

    # Stub the direct transport so the test never touches the network - a real
    # engine may or may not be listening on the machine running these tests.
    seen: list[str] = []
    client._direct = lambda path, **kw: seen.append(path) or [{"id": "direct"}]

    assert client.captures(limit=5) == [{"id": "direct"}]
    assert seen and seen[0].startswith("/api/v1/captures")
    assert deployment.calls == []


def test_no_deployment_service_means_direct(as_workstation):
    """A panel built without a deployment service must not try to relay."""
    assert EngineClient(None, "http://127.0.0.1:9088").relayed is False


def test_profile_filter_is_forwarded(as_workstation):
    deployment = FakeDeployment(response=[])
    EngineClient(deployment, "http://x").captures(limit=10, profile_id="cm250")
    _, path, _ = deployment.calls[0]
    assert "profile_id=cm250" in path


def test_blank_profile_filter_is_omitted(as_workstation):
    deployment = FakeDeployment(response=[])
    EngineClient(deployment, "http://x").captures(limit=10, profile_id="   ")
    _, path, _ = deployment.calls[0]
    assert "profile_id" not in path


def test_replay_is_relayed_as_a_post(as_workstation):
    deployment = FakeDeployment(response={"ok": True})
    EngineClient(deployment, "http://x").replay("cap_1", "cm250")
    method, path, body = deployment.calls[0]
    assert (method, path) == ("POST", "/api/instruments/replay")
    assert body == {"capture_id": "cap_1", "profile_id": "cm250"}


def test_health_returns_none_when_the_relay_says_the_engine_is_offline(as_workstation):
    """The backend answers 200 with status=offline so the client shows offline."""
    deployment = FakeDeployment(response={"status": "offline", "detail": "refused"})
    assert EngineClient(deployment, "http://x").health() is None


def test_health_returns_none_when_the_backend_itself_is_unreachable(as_workstation):
    deployment = FakeDeployment(error="Could not reach server")
    assert EngineClient(deployment, "http://x").health() is None


def test_health_passes_through_a_healthy_engine(as_workstation):
    deployment = FakeDeployment(response={"status": "ok", "api_version": "v1"})
    assert EngineClient(deployment, "http://x").health() == {"status": "ok", "api_version": "v1"}


def test_captures_ignores_a_non_list_payload(as_workstation):
    deployment = FakeDeployment(response={"unexpected": True})
    assert EngineClient(deployment, "http://x").captures() == []


def test_relay_failure_surfaces_as_engine_unavailable(as_workstation):
    deployment = FakeDeployment(error="boom")
    with pytest.raises(EngineUnavailable):
        EngineClient(deployment, "http://x").runtime_status()
