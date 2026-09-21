"""Which analyzer capture is already used, shared across workstations.

"Linked" used to live only in each app's own SQLite, so a capture imported on
LAB1 still showed as pending on LAB2 - and could be imported a second time over
a result someone had corrected by hand. The server already knew (it logs
capture_id in the audit trail); it just could not be asked.
"""

from __future__ import annotations

from uuid import uuid4

from app.models.models import InstrumentCaptureLink
from app.routers.results import _record_capture_link


class FakeSession:
    def __init__(self, existing: dict | None = None) -> None:
        self.existing = existing or {}
        self.added: list = []

    def get(self, _model, key):
        return self.existing.get(key)

    def add(self, obj) -> None:
        self.added.append(obj)


def test_a_new_capture_is_recorded_against_its_order():
    db = FakeSession()
    order_id = uuid4()
    actor = uuid4()

    _record_capture_link(db, "cap_0685caac40c89595", order_id, actor)

    assert len(db.added) == 1
    assert db.added[0].capture_id == "cap_0685caac40c89595"
    assert db.added[0].order_id == order_id
    assert db.added[0].linked_by == actor


def test_re_linking_moves_the_capture_instead_of_duplicating_it():
    """One capture is one analyzer run; two rows would leave the workstations
    disagreeing about which order owns it."""
    order_a, order_b = uuid4(), uuid4()
    existing = InstrumentCaptureLink(capture_id="cap_1", order_id=order_a)
    db = FakeSession({"cap_1": existing})

    _record_capture_link(db, "cap_1", order_b, None)

    assert db.added == []
    assert existing.order_id == order_b
    assert existing.linked_at is not None


def test_a_payload_with_no_capture_id_still_imports():
    """A replayed or hand-built payload need not carry one - there is simply
    nothing to mark as used."""
    db = FakeSession()

    _record_capture_link(db, None, uuid4(), None)
    _record_capture_link(db, "   ", uuid4(), None)

    assert db.added == []


def test_surrounding_whitespace_does_not_create_a_second_row():
    existing = InstrumentCaptureLink(capture_id="cap_1", order_id=uuid4())
    db = FakeSession({"cap_1": existing})

    _record_capture_link(db, "  cap_1  ", uuid4(), None)

    assert db.added == []
