"""Where the desktop looks up which captures are already imported.

Local mode keeps it in its own order_ui_state, as always. Server mode has to
ask the server: each workstation has its own SQLite, so a capture linked on
LAB1 showed as pending on LAB2 and could be imported a second time.
"""

from __future__ import annotations

import pytest

from spdxlims.result_service import ResultService


class FakeDatabase:
    def __init__(self, scope: dict | None = None) -> None:
        self.scope = scope or {}
        self.writes: list[tuple] = []

    def get_order_ui_scope(self, _scope):
        return self.scope

    def set_order_ui_value(self, scope, entity_id, value) -> None:
        self.writes.append((scope, entity_id, value))


class FakeConfig:
    def __init__(self, mode: str) -> None:
        self.mode = mode


class FakeDeployment:
    """_is_local() reads deployment_service.load().mode, so the mode is set here."""

    def __init__(self, payload=None, mode: str = "server") -> None:
        self.payload = payload
        self.mode = mode
        self.calls: list[tuple] = []

    def load(self) -> FakeConfig:
        return FakeConfig(self.mode)

    def request_json(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self.payload


def _service(*, local: bool, database=None, deployment=None) -> ResultService:
    deployment = deployment or FakeDeployment()
    deployment.mode = "local" if local else "server"
    return ResultService(database or FakeDatabase(), deployment)


def test_local_mode_reads_its_own_ui_state():
    database = FakeDatabase({"cap_1": {"order_id": 41, "linked_at": "2026-09-21T10:00:00"}})
    deployment = FakeDeployment()

    links = _service(local=True, database=database, deployment=deployment).linked_instrument_captures()

    assert links == {"cap_1": {"order_id": 41, "linked_at": "2026-09-21T10:00:00"}}
    assert deployment.calls == []


def test_local_mode_ignores_junk_rows():
    database = FakeDatabase({"cap_1": "not a dict", "cap_2": {"order_id": 7}})

    links = _service(local=True, database=database).linked_instrument_captures()

    assert list(links) == ["cap_2"]


def test_server_mode_asks_the_server():
    deployment = FakeDeployment([
        {"capture_id": "cap_1", "order_id": "o-1", "order_number": "500011", "linked_at": "2026-09-21T10:00:00"},
        {"capture_id": "cap_2", "order_id": "o-2", "order_number": "500012", "linked_at": None},
    ])

    links = _service(local=False, deployment=deployment).linked_instrument_captures()

    assert deployment.calls == [("GET", "/api/results/instrument-capture-links", None)]
    assert links["cap_1"]["order_id"] == "o-1"
    assert links["cap_1"]["order_number"] == "500011"
    assert links["cap_2"]["linked_at"] == ""


def test_a_server_that_cannot_answer_raises_rather_than_reporting_none_linked():
    """An empty answer would paint every capture as free to import again."""
    with pytest.raises(RuntimeError):
        _service(local=False, deployment=FakeDeployment(None)).linked_instrument_captures()


def test_rows_without_a_capture_id_are_dropped():
    deployment = FakeDeployment([{"order_id": "o-1"}, {"capture_id": "  ", "order_id": "o-2"}])

    assert _service(local=False, deployment=deployment).linked_instrument_captures() == {}


def test_local_mode_writes_the_marker():
    database = FakeDatabase()

    _service(local=True, database=database).mark_instrument_capture_linked("cap_1", 41, "2026-09-21T10:00:00")

    assert database.writes == [
        ("instrument_capture", "cap_1", {"order_id": 41, "linked_at": "2026-09-21T10:00:00"})
    ]


def test_server_mode_does_not_write_a_local_marker():
    """The server records the link as part of the import itself; a local copy
    would just be a second, per-workstation answer to the same question."""
    database = FakeDatabase()

    _service(local=False, database=database).mark_instrument_capture_linked("cap_1", "o-1", "2026-09-21T10:00:00")

    assert database.writes == []


def test_an_empty_capture_id_is_never_written():
    database = FakeDatabase()

    _service(local=True, database=database).mark_instrument_capture_linked("", 41, "2026-09-21T10:00:00")

    assert database.writes == []
