"""The payload sent to /api/results/import-instrument must name its capture.

It never did: the parsed capture body has no id of its own, so every import
reached the server with capture_id null. The audit trail recorded null too,
which is why the server could not tell which captures had been used - and why
"linked" had to live in each workstation's own database.

resolve_payload is the one place all three senders go through: the manual link,
the page's auto-import, and the headless instrument_importer.
"""

from __future__ import annotations

from spdxlims.instrument_mapping import resolve_payload


class FakeDatabase:
    """No mappings configured; the observations pass through unresolved."""

    def list_instrument_result_mappings(self, **_kwargs):
        return []

    def resolve_instrument_result_mapping(self, **_kwargs):
        return None


CAPTURE = {"id": "cap_0685caac40c89595", "profile_id": "cm250", "device_id": "dev-1"}
RESULT = {"message": {"observations": [{"instrument_test_code": "GLU", "value": "92"}]}}


def test_the_capture_id_reaches_the_payload():
    payload = resolve_payload(FakeDatabase(), CAPTURE, RESULT)

    assert payload["capture_id"] == "cap_0685caac40c89595"


def test_the_observations_still_come_through():
    """The stamp must not cost the mapping work this function exists for."""
    payload = resolve_payload(FakeDatabase(), CAPTURE, RESULT)

    assert len(payload["message"]["observations"]) == 1


def test_a_payload_that_already_names_its_capture_is_left_alone():
    """A replayed payload knows where it came from; the wrapper around it may
    be a different capture."""
    result = {**RESULT, "capture_id": "cap_original"}

    payload = resolve_payload(FakeDatabase(), CAPTURE, result)

    assert payload["capture_id"] == "cap_original"


def test_a_capture_with_no_id_adds_nothing():
    payload = resolve_payload(FakeDatabase(), {"profile_id": "cm250"}, RESULT)

    assert "capture_id" not in payload


def test_the_id_is_stamped_even_when_there_is_nothing_to_map():
    """resolve_payload returns early for a body with no observations; the id
    still has to be on it or that import goes unrecorded."""
    payload = resolve_payload(FakeDatabase(), CAPTURE, {"message": {"observations": []}})

    assert payload["capture_id"] == "cap_0685caac40c89595"


def test_a_body_with_no_message_still_carries_the_id():
    payload = resolve_payload(FakeDatabase(), CAPTURE, {"raw": "unparsed"})

    assert payload["capture_id"] == "cap_0685caac40c89595"
