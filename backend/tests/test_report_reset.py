"""Deleting a saved report takes the order back out of "reported".

Mirrors the desktop's Database.delete_saved_report. Finalizing sets the order to
'reported' with a reported_at; throwing the report away has to undo both, or the
order keeps a status that says a report exists when none does.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.routers.reports import reopen_order_after_report_delete


class FakeOrder:
    def __init__(self, status: str, reported_at=None):
        self.status = status
        self.reported_at = reported_at


def test_a_reported_order_goes_back_to_in_lab():
    order = FakeOrder("reported", datetime(2026, 9, 19, 14, 8))

    reopen_order_after_report_delete(order)

    assert order.status == "in_lab"
    assert order.reported_at is None


@pytest.mark.parametrize("status", ["registered", "in_lab", "cancelled"])
def test_any_other_status_is_left_alone(status):
    order = FakeOrder(status, None)

    reopen_order_after_report_delete(order)

    assert order.status == status


def test_a_missing_order_is_not_an_error():
    reopen_order_after_report_delete(None)
