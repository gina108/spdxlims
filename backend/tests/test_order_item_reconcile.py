"""Editing an order must not throw away what is already on it.

update_order used to delete every order_item and re-insert. Results and result
images cascade off order_item, so an edit wiped every result already typed; and
report_item_snapshot holds a plain FK to order_item, so once a report was
finalized the delete raised ForeignKeyViolation and the order could not be
edited at all - that is the 500 behind "subrogar PERFIL TIROIDEO" on order
500011.

These pin the reconcile that replaced it.
"""

from __future__ import annotations

from uuid import uuid4

from app.models.models import OrderItem, ReportSnapshot
from app.routers.orders import _reconcile_order_items


class FakeSession:
    """Answers the two scalars() queries in order, and records the writes."""

    def __init__(self, snapshots: list, existing: list) -> None:
        self._results = [snapshots, existing]
        self.added: list = []
        self.deleted: list = []

    def scalars(self, _statement):
        self._current = self._results.pop(0)
        return self

    def all(self):
        return self._current

    def add(self, obj) -> None:
        self.added.append(obj)

    def delete(self, obj) -> None:
        self.deleted.append(obj)

    def flush(self) -> None:
        pass


class FakeOrder:
    def __init__(self) -> None:
        self.id = uuid4()


def _row(item_type: str, *, test_id=None, display_name=None, sort_order=0) -> OrderItem:
    return OrderItem(
        id=uuid4(),
        test_id=test_id,
        item_type=item_type,
        display_name=display_name,
        sort_order=sort_order,
        is_outsourced=False,
    )


def _asked(item_type: str, *, test_id=None, label=None, source="", outsourced=False) -> dict:
    return {
        "item_type": item_type,
        "test_id": test_id,
        "label": label,
        "source": source,
        "is_outsourced": outsourced,
    }


def test_a_test_already_on_the_order_keeps_its_row():
    """Its results hang off that row id - a new row loses them."""
    test_id = uuid4()
    existing = _row("test", test_id=test_id)
    db = FakeSession([], [existing])
    order = FakeOrder()

    _reconcile_order_items(order, [_asked("test", test_id=test_id, source="PERFIL TIROIDEO")], db)

    assert db.added == []
    assert db.deleted == []
    assert existing.group_label == "PERFIL TIROIDEO"


def test_ticking_subrogado_sets_the_flag_on_the_existing_row():
    test_id = uuid4()
    existing = _row("test", test_id=test_id)
    db = FakeSession([], [existing])

    _reconcile_order_items(
        FakeOrder(),
        [_asked("test", test_id=test_id, source="PERFIL TIROIDEO", outsourced=True)],
        db,
    )

    assert existing.is_outsourced is True
    assert existing.source_label == "PERFIL TIROIDEO"


def test_a_note_is_matched_by_its_text_so_the_typed_comment_survives():
    """The "Observaciones" row under a panel stores the technician's text; a
    fresh row would come back blank."""
    existing = _row("comment", display_name="Observaciones")
    db = FakeSession([], [existing])

    _reconcile_order_items(FakeOrder(), [_asked("comment", label="Observaciones", source="BH")], db)

    assert db.added == []
    assert db.deleted == []


def test_a_newly_added_panel_only_inserts_its_own_rows():
    kept_id = uuid4()
    added_id = uuid4()
    kept = _row("test", test_id=kept_id)
    db = FakeSession([], [kept])

    _reconcile_order_items(
        FakeOrder(),
        [
            _asked("test", test_id=kept_id, source="BIOMETRIA HEMATICA"),
            _asked("test", test_id=added_id, source="PERFIL TIROIDEO", outsourced=True),
        ],
        db,
    )

    assert db.deleted == []
    assert len(db.added) == 1
    assert db.added[0].test_id == added_id
    assert db.added[0].is_outsourced is True


def test_a_test_dropped_from_the_order_is_deleted():
    gone = _row("test", test_id=uuid4())
    db = FakeSession([], [gone])

    _reconcile_order_items(FakeOrder(), [_asked("test", test_id=uuid4())], db)

    assert db.deleted == [gone]


def test_sort_order_follows_the_submitted_list():
    first, second = uuid4(), uuid4()
    rows = [_row("test", test_id=first, sort_order=0), _row("test", test_id=second, sort_order=1)]
    db = FakeSession([], list(rows))

    _reconcile_order_items(
        FakeOrder(),
        [_asked("test", test_id=second), _asked("test", test_id=first)],
        db,
    )

    assert (rows[0].sort_order, rows[1].sort_order) == (1, 0)


def test_the_finalized_report_is_dropped_so_its_snapshot_stops_pinning_the_rows():
    """Matches the desktop: the report no longer matches the order and is
    reissued from the Reports page after the edit."""
    snapshot = ReportSnapshot(id=uuid4(), patient_snapshot_name="X")
    db = FakeSession([snapshot], [])

    _reconcile_order_items(FakeOrder(), [_asked("test", test_id=uuid4())], db)

    assert db.deleted == [snapshot]
