"""The "Subrogado" tick has to reach the server and come back.

In server mode the tick was built into the order items but dropped on the way
out, and the server never returned it, so ticking Subrogado on a panel looked
like it worked and was gone when the order was reopened - and the outsourced
PDF page then offered no panel to attach the external results to.
"""

from __future__ import annotations

from spdxlims.order_service import OrderService, _build_order_item_payload


def test_the_tick_is_sent_for_a_test_row():
    payload = _build_order_item_payload(
        [{"item_type": "test", "test_id": "t-1", "source": "PERFIL TIROIDEO", "is_outsourced": 1}]
    )
    assert payload == [
        {"item_type": "test", "test_id": "t-1", "source": "PERFIL TIROIDEO", "is_outsourced": 1}
    ]


def test_the_tick_is_sent_for_a_heading_or_note_row():
    """A whole panel is subrogated at once, headings and notes included."""
    payload = _build_order_item_payload(
        [{"item_type": "comment", "label": "Observaciones", "source": "PERFIL TIROIDEO", "is_outsourced": 1}]
    )
    assert payload[0]["is_outsourced"] == 1


def test_an_untitled_tick_defaults_to_off():
    payload = _build_order_item_payload([{"item_type": "test", "test_id": "t-1", "source": "BH"}])
    assert payload[0]["is_outsourced"] == 0


def test_the_tick_comes_back_when_the_order_is_reopened():
    detail = OrderService._parse_order_detail(
        None,
        {
            "id": "o-1",
            "order_number": "500011",
            "status": "reported",
            "items": [
                {"item_type": "test", "test_id": "t-1", "label": "BLANCO", "source": "PERFIL TIROIDEO", "is_outsourced": 1},
                {"item_type": "test", "test_id": "t-2", "label": "Glucosa", "source": "QS6", "is_outsourced": 0},
            ],
        },
    )
    assert [item["is_outsourced"] for item in detail.items] == [1, 0]
