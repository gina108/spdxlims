"""Labels for an order that lives on the server.

"Guardar e imprimir etiquetas" printed nothing in server mode: the print path
read the label's details out of local SQLite by order id, and a server order
has no row there, so get_order_label_entries came back empty and the printer
was never called. The details are now taken from the form instead - which has
to happen before clear_order_form() wipes it.
"""

from __future__ import annotations

import pytest

from spdxlims.pages.orders_page import OrdersPage


class FakeCombo:
    def __init__(self, data=None) -> None:
        self._data = data

    def currentData(self):
        return self._data


class FakePatientService:
    def __init__(self, patient=None, raises: bool = False) -> None:
        self._patient = patient
        self._raises = raises

    def get_patient(self, _patient_id):
        if self._raises:
            raise RuntimeError("server unreachable")
        return self._patient


def _page(patient=None, selected_items=None, *, raises: bool = False, client_id=None) -> OrdersPage:
    page = OrdersPage.__new__(OrdersPage)  # no Qt widgets needed for this helper
    page.patient_service = FakePatientService(patient, raises=raises)
    page.client_combo = FakeCombo(client_id)
    page.selected_items = selected_items or []
    return page


PATIENT = {
    "first_name": "Ana",
    "last_name": "Ruiz",
    "middle_name": "Lopez",
    "sex": "F",
    "age_value": 34,
    "age_unit": "años",
}


def test_the_row_carries_what_the_label_actually_prints():
    row, _codes = _page(PATIENT)._server_label_details("uuid-1", "500011")

    assert row["order_number"] == "500011"
    assert row["patient_name"] == "Ana Ruiz Lopez"
    assert row["patient_sex"] == "F"
    assert row["created_at"]


def test_the_barcode_token_comes_out_of_the_row():
    """_build_token reads order_number off this row; an empty one prints a
    label with no usable barcode."""
    from spdxlims.pages.order_labels_dialog import OrderLabelsDialog

    row, _codes = _page(PATIENT)._server_label_details("uuid-1", "500011")

    assert OrderLabelsDialog._build_token(row, "order_only") == "500011"


def test_panels_are_collected_for_the_extra_copies_setting():
    """panel_extra_copies is keyed by the same source label the form carries."""
    items = [
        {"item_type": "test", "test_id": "t1", "source": "BIOMETRIA HEMATICA"},
        {"item_type": "test", "test_id": "t2", "source": "BIOMETRIA HEMATICA"},
        {"item_type": "test", "test_id": "t3", "source": "PERFIL TIROIDEO"},
    ]

    _row, codes = _page(PATIENT, items)._server_label_details("uuid-1", "500011")

    assert codes == ["BIOMETRIA HEMATICA", "PERFIL TIROIDEO"]


def test_headings_and_notes_do_not_count_as_panels():
    """Matches get_order_panel_codes, which excludes the layout rows."""
    items = [
        {"item_type": "heading", "label": "FORMULA ROJA", "source": "BIOMETRIA HEMATICA"},
        {"item_type": "comment", "label": "Observaciones", "source": "SOLO NOTA"},
        {"item_type": "test", "test_id": "t1", "source": "BIOMETRIA HEMATICA"},
    ]

    _row, codes = _page(PATIENT, items)._server_label_details("uuid-1", "500011")

    assert codes == ["BIOMETRIA HEMATICA"]


def test_a_loose_test_with_no_panel_is_skipped():
    items = [{"item_type": "test", "test_id": "t1", "source": ""}]

    _row, codes = _page(PATIENT, items)._server_label_details("uuid-1", "500011")

    assert codes == []


def test_a_patient_lookup_failure_still_prints_the_barcode():
    """The order number is the part that matters; losing the name must not cost
    the whole label."""
    row, _codes = _page(raises=True)._server_label_details("uuid-1", "500011")

    assert row["order_number"] == "500011"
    assert row["patient_name"] == ""


class FakeDatabase:
    """Local SQLite as a server order sees it: no row for this order."""

    def __init__(self) -> None:
        self.label_lookups: list[object] = []

    def get_order_label_entries(self, order_id):
        self.label_lookups.append(order_id)
        return []

    def get_order_panel_codes(self, _order_id):
        return []

    def get_panel_extra_copies(self):
        return {"PERFIL TIROIDEO": 2}


class FakePrinter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def print_label(self, **kwargs) -> None:
        self.calls.append(kwargs)


PREFS = {
    "size": "small_tall",
    "payload": "order_only",
    "copies": "1",
    "density": "4",
    "show_barcode": "1",
    "show_patient_name": "1",
    "show_order_number_text": "1",
    "show_datetime": "0",
}


def _print_page(selected_items=None) -> tuple[OrdersPage, FakeDatabase, FakePrinter]:
    page = _page(PATIENT, selected_items)
    page.database = FakeDatabase()
    return page, page.database, FakePrinter()


def test_the_printer_is_called_for_an_order_with_no_local_row():
    """The regression: with nothing passed in, the lookup came back empty and
    the method returned before printing."""
    page, database, printer = _print_page()
    label_row, panel_codes = page._server_label_details("uuid-1", "500011")

    page._print_order_label_silent(
        None, PREFS, printer, "niimbot:B1", label_row=label_row, panel_codes=panel_codes
    )

    assert len(printer.calls) == 1
    assert printer.calls[0]["barcode_value"] == "500011"
    assert printer.calls[0]["text_lines"] == ["500011", "Ana Ruiz Lopez"]
    assert database.label_lookups == []  # local SQLite was never consulted


def test_a_panel_still_adds_its_extra_copies():
    items = [{"item_type": "test", "test_id": "t1", "source": "PERFIL TIROIDEO"}]
    page, _database, printer = _print_page(items)
    label_row, panel_codes = page._server_label_details("uuid-1", "500011")

    page._print_order_label_silent(
        None, PREFS, printer, "niimbot:B1", label_row=label_row, panel_codes=panel_codes
    )

    assert printer.calls[0]["copies"] == 3  # 1 + 2 extra


def test_local_mode_still_reads_the_database():
    page, database, printer = _print_page()

    page._print_order_label_silent(41, PREFS, printer, "niimbot:B1")

    assert database.label_lookups == [41]
    assert printer.calls == []  # this fake order has no rows, as before
