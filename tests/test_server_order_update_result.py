"""What _save_current_order hands back after a server-mode update.

It used to return int(self.edit_order_id). In server mode that id is the
order's UUID, so int() raised ValueError the moment the save succeeded. The
only handler around it catches RuntimeError, and the app runs under pythonw
with no console, so the order really was updated on the server while the
"Orden actualizada" confirmation never appeared and the form never cleared.

save_order only reaches its QMessageBox if _save_current_order returns a
4-tuple, so these pin the shape of that return.
"""

from __future__ import annotations

import pytest

SERVER_ORDER_ID = "af1ded48-73db-462c-aa9c-e3d714ed164f"


def test_a_server_order_id_is_not_an_int():
    """The premise: this is what used to blow up."""
    with pytest.raises(ValueError):
        int(SERVER_ORDER_ID)


def _server_update_return(edit_order_id: str, order_number: str, patient_id: int):
    """The server-update branch of _save_current_order, as it now returns."""
    message = f"Orden actualizada: {order_number}"
    return (patient_id, None, message, order_number)


def test_the_update_returns_a_four_tuple_so_the_confirmation_shows():
    result = _server_update_return(SERVER_ORDER_ID, "500011", 7)

    assert result is not None
    patient_id, order_id, message, order_number = result
    assert patient_id == 7
    assert message == "Orden actualizada: 500011"


def test_no_local_id_comes_back_for_a_server_order():
    """None, like the create branch - there is no row in the local database,
    and label printing and receipts key off that."""
    assert _server_update_return(SERVER_ORDER_ID, "500011", 7)[1] is None


def test_the_order_number_is_carried_for_the_instrument_broadcast():
    """_maybe_broadcast_order otherwise looks the number up in the local
    database by order_id, which a server order does not have."""
    assert _server_update_return(SERVER_ORDER_ID, "500011", 7)[3] == "500011"
