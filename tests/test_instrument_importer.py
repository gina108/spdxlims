from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from spdxlims.database import Database
from spdxlims.instrument_importer import (
    CAPTURE_SCOPE,
    InstrumentImporter,
    heartbeat_path,
    importer_is_running,
)


class FakeDeployment:
    """Stands in for DeploymentService without touching a real server."""

    def __init__(self, *, authenticated: bool = True, server_url: str = "http://127.0.0.1:8001") -> None:
        self._authenticated = authenticated
        self.server_url = server_url
        self.login_calls = 0

    class _Config:
        def __init__(self, server_url: str) -> None:
            self.server_url = server_url
            self.mode = "server"

    def load(self):
        return self._Config(self.server_url)

    def is_authenticated(self) -> bool:
        return self._authenticated

    def try_auto_login(self) -> bool:
        self.login_calls += 1
        self._authenticated = True
        return True

    def logout(self) -> None:
        self._authenticated = False

    @property
    def access_token(self):
        return "token" if self._authenticated else None


def _capture(
    capture_id: str,
    *,
    profile_id: str = "mindray-bc30s",
    observations=None,
    parsed=True,
    age_hours: float = 0.0,
) -> dict:
    received = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    payload: dict = {"id": capture_id, "profile_id": profile_id, "received_at": received.isoformat()}
    if parsed:
        payload["parsed_json"] = {
            "capture_id": capture_id,
            "message": {
                "source_profile_id": profile_id,
                "sample_id": "S-1",
                "observations": observations if observations is not None else [{"instrument_test_code": "WBC"}],
            },
        }
    return payload


@pytest.fixture()
def importer(tmp_path):
    database = Database(tmp_path / "spdxlims.db")
    database.initialize()
    return InstrumentImporter(database, FakeDeployment(), data_dir=tmp_path)


def _run(importer, captures, responses):
    """Run one cycle with fetch/post stubbed. responses is a list of (status, payload)."""
    calls = []
    importer.fetch_captures = lambda: captures

    def fake_post(result):
        calls.append(result)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    importer._post_import = fake_post
    return importer.run_once(), calls


def test_imports_a_new_capture_and_marks_it_linked(importer):
    summary, calls = _run(
        importer,
        [_capture("cap_1")],
        [(200, {"imported_count": 2, "order_id": "ord-1", "order_number": "000123", "matched_by": "sample_id"})],
    )
    assert (summary.imported, summary.results_written, summary.failed) == (1, 2, 0)
    assert len(calls) == 1
    assert "cap_1" in importer.linked_capture_ids()


def test_already_linked_capture_is_not_posted_again(importer):
    importer.mark_linked("cap_1", "ord-1")
    summary, calls = _run(importer, [_capture("cap_1")], [(200, {"imported_count": 1})])
    assert calls == []
    assert summary.considered == 0


@pytest.mark.parametrize("status", [400, 409])
def test_unmatched_captures_are_skipped_not_failed(importer, status):
    """400 = no order matched, 409 = no test codes matched. Both are ordinary."""
    summary, _ = _run(importer, [_capture("cap_1")], [(status, None)])
    assert (summary.skipped, summary.failed) == (1, 0)
    assert summary.errors == []
    assert "cap_1" not in importer.linked_capture_ids()


def test_unexpected_status_is_reported_as_a_failure(importer):
    summary, _ = _run(importer, [_capture("cap_1")], [(500, None)])
    assert (summary.failed, summary.skipped) == (1, 0)
    assert summary.errors


def test_zero_imported_count_does_not_mark_linked(importer):
    summary, _ = _run(importer, [_capture("cap_1")], [(200, {"imported_count": 0})])
    assert summary.imported == 0
    assert "cap_1" not in importer.linked_capture_ids()


def test_expired_token_triggers_one_reauth_then_retries(importer):
    statuses = [(401, None), (200, {"imported_count": 1, "order_id": "ord-1"})]
    calls = []

    def fake_post(result):
        calls.append(result)
        return statuses[len(calls) - 1]

    importer.fetch_captures = lambda: [_capture("cap_1")]
    importer._post_import = fake_post

    summary = importer.run_once()
    assert len(calls) == 2  # the 401, then the retry
    assert importer.deployment_service.login_calls == 1
    assert summary.imported == 1


def test_capture_without_observations_is_ignored(importer):
    summary, calls = _run(importer, [_capture("cap_1", observations=[])], [(200, {"imported_count": 1})])
    assert calls == []
    assert summary.considered == 0


def test_unparsed_capture_is_ignored(importer):
    summary, calls = _run(importer, [_capture("cap_1", parsed=False)], [(200, {"imported_count": 1})])
    assert calls == []
    assert summary.considered == 0


def test_parsed_json_as_a_string_is_decoded(importer):
    capture = _capture("cap_1")
    capture["parsed_json"] = json.dumps(capture["parsed_json"])
    summary, calls = _run(importer, [capture], [(200, {"imported_count": 1, "order_id": "ord-1"})])
    assert len(calls) == 1
    assert summary.imported == 1


def test_profile_with_auto_import_disabled_is_skipped(importer):
    importer.database.save_instrument_order_match(
        "mindray-bc30s",
        "sample_id",
        "order_number",
        auto_import=False,
    )
    summary, calls = _run(importer, [_capture("cap_1")], [(200, {"imported_count": 1})])
    assert calls == []
    assert summary.considered == 0


def test_engine_unreachable_is_reported_without_crashing(importer):
    def boom():
        raise OSError("connection refused")

    importer.fetch_captures = boom
    summary = importer.run_once()
    assert summary.errors and summary.imported == 0


def test_failed_authentication_stops_the_cycle(tmp_path):
    database = Database(tmp_path / "spdxlims.db")
    database.initialize()
    deployment = FakeDeployment(authenticated=False)
    deployment.try_auto_login = lambda: False
    importer = InstrumentImporter(database, deployment, data_dir=tmp_path)
    summary = importer.run_once()
    assert summary.errors and summary.considered == 0


# ── Heartbeat: the handshake that keeps the app and the task from both writing ──

def test_heartbeat_absent_means_not_running(tmp_path):
    assert importer_is_running(tmp_path) is False


def test_fresh_heartbeat_means_running(importer, tmp_path):
    importer.write_heartbeat()
    assert importer_is_running(tmp_path) is True


def test_stale_heartbeat_means_not_running(tmp_path):
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    heartbeat_path(tmp_path).write_text(json.dumps({"written_at": old.isoformat()}), encoding="utf-8")
    assert importer_is_running(tmp_path) is False


def test_corrupt_heartbeat_means_not_running(tmp_path):
    heartbeat_path(tmp_path).write_text("not json", encoding="utf-8")
    assert importer_is_running(tmp_path) is False


# ── Throttling: without this the service re-posts every old capture forever ──

def test_captures_older_than_the_cutoff_are_not_posted(importer):
    summary, calls = _run(importer, [_capture("cap_old", age_hours=72)], [(200, {"imported_count": 1})])
    assert calls == []
    assert summary.aged_out == 1


def test_recent_captures_are_still_posted(importer):
    summary, calls = _run(
        importer, [_capture("cap_new", age_hours=1)],
        [(200, {"imported_count": 1, "order_id": "ord-1"})],
    )
    assert len(calls) == 1
    assert summary.imported == 1


def test_cutoff_can_be_disabled(importer):
    importer.max_age_hours = 0
    summary, calls = _run(importer, [_capture("cap_old", age_hours=500)], [(400, None)])
    assert len(calls) == 1


def test_capture_missing_a_timestamp_is_still_attempted(importer):
    capture = _capture("cap_1")
    del capture["received_at"]
    _, calls = _run(importer, [capture], [(400, None)])
    assert len(calls) == 1


def test_unmatched_capture_backs_off_on_the_next_cycle(importer):
    """The whole point: an unmatched capture must not be re-posted every 30s."""
    first, calls_a = _run(importer, [_capture("cap_1")], [(400, None)])
    assert first.skipped == 1 and len(calls_a) == 1

    second, calls_b = _run(importer, [_capture("cap_1")], [(400, None)])
    assert calls_b == []
    assert second.backed_off == 1


def test_backoff_expires_and_the_capture_is_retried(importer):
    _run(importer, [_capture("cap_1")], [(400, None)])
    importer.retry_after_minutes = 0  # window elapsed
    summary, calls = _run(importer, [_capture("cap_1")], [(200, {"imported_count": 1, "order_id": "ord-1"})])
    assert len(calls) == 1
    assert summary.imported == 1


def test_successful_import_clears_the_unmatched_marker(importer):
    _run(importer, [_capture("cap_1")], [(400, None)])
    assert importer.database.get_order_ui_scope("instrument_capture_unmatched")
    importer.retry_after_minutes = 0
    _run(importer, [_capture("cap_1")], [(200, {"imported_count": 1, "order_id": "ord-1"})])
    assert importer.database.get_order_ui_scope("instrument_capture_unmatched") == {}


def test_attempts_accumulate_across_retries(importer):
    _run(importer, [_capture("cap_1")], [(400, None)])
    importer.retry_after_minutes = 0
    _run(importer, [_capture("cap_1")], [(400, None)])
    record = importer.database.get_order_ui_scope("instrument_capture_unmatched")["cap_1"]
    assert record["attempts"] == 2


def test_marks_are_visible_through_the_shared_ui_scope(importer):
    importer.mark_linked("cap_9", "ord-9")
    stored = importer.database.get_order_ui_scope(CAPTURE_SCOPE)
    assert stored["cap_9"]["order_id"] == "ord-9"
