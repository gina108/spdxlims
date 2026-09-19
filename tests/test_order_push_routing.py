"""Which installs may put a sample on an analyzer's worklist, and how.

A guard meant to stop a dev checkout writing real .ANA files also stopped the
workstation, so orders placed on LAB2 silently never reached the CM250. These
pin the three cases apart.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from spdxlims import instrument_broadcast


_UNSET = object()


class FakeDeployment:
    def __init__(self, response=_UNSET):
        # A sentinel, not `or`: None is a meaningful response here - it is what
        # request_json returns when the session is not authenticated.
        self.response = {"status": "queued"} if response is _UNSET else response
        self.calls: list[tuple[str, str, dict | None]] = []

    def request_json(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self.response


def _as_install(mode: str, server_url: str = ""):
    """cwd with a deployment.json describing one kind of install."""
    tmp = tempfile.TemporaryDirectory()
    data = Path(tmp.name) / "data"
    data.mkdir()
    payload = {"mode": mode}
    if server_url:
        payload["server_url"] = server_url
    (data / "deployment.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp


@pytest.fixture()
def workstation():
    tmp = _as_install("server", "http://10.0.0.10:8001")
    cwd = os.getcwd()
    os.chdir(tmp.name)
    yield
    os.chdir(cwd)
    tmp.cleanup()


@pytest.fixture()
def checkout_beside_production():
    """Server mode, but the server is this same machine - the dev clone."""
    tmp = _as_install("server", "http://127.0.0.1:8001")
    cwd = os.getcwd()
    os.chdir(tmp.name)
    yield
    os.chdir(cwd)
    tmp.cleanup()


def test_a_workstation_may_push(workstation):
    assert instrument_broadcast.may_push_orders() is True


def test_a_checkout_beside_production_may_not(checkout_beside_production):
    """It can reach the live share directly, so a push would write a real
    worklist from a test environment."""
    assert instrument_broadcast.may_push_orders() is False


def test_a_workstation_push_is_relayed_by_the_backend(workstation):
    deployment = FakeDeployment()
    instrument_broadcast.push_pending_order_to_engine(
        "500009",
        [{"test_code": "GLU L", "test_name": "Glucosa"}],
        patient_name="Paciente",
        profile_id="cm250",
        deployment_service=deployment,
    )
    method, path, body = deployment.calls[0]
    assert (method, path) == ("POST", "/api/instruments/orders/pending")
    assert body["sample_id"] == "500009"
    assert body["profile_id"] == "cm250"
    assert body["tests"][0]["test_code"] == "GLU L"


def test_a_relay_that_answers_nothing_is_an_error(workstation):
    """request_json returns None when the session is not authenticated; the
    order must not be reported as delivered."""
    deployment = FakeDeployment(response=None)
    with pytest.raises(RuntimeError):
        instrument_broadcast.push_pending_order_to_engine(
            "500009", [{"test_code": "GLU L"}], deployment_service=deployment
        )


def test_without_a_deployment_service_the_push_stays_direct(workstation, monkeypatch):
    """No relay available, so it must not silently claim success - it should
    try the engine directly and fail loudly when nothing answers.

    Pointed at a closed port on purpose. An earlier version of this test used
    the configured engine URL and, on the machine that actually runs the
    engine, pushed a real pending order into the live lab.
    """
    monkeypatch.setattr(instrument_broadcast, "_ENGINE_URL", "http://127.0.0.1:9")
    with pytest.raises(RuntimeError):
        instrument_broadcast.push_pending_order_to_engine(
            "TEST-DO-NOT-USE",
            [{"test_code": "GLU L"}],
            deployment_service=None,
            timeout=0.4,
        )
