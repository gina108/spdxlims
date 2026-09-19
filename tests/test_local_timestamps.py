"""Every timestamp the app stores or prints is the lab's own wall clock.

SQLite's CURRENT_TIMESTAMP is UTC, which put every stored time six hours ahead
here and rolled the date over at 18:00 local. The database layer writes
datetime('now','localtime') instead, and nothing may reintroduce the UTC form.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spdxlims.database import Database
from spdxlims.report_layout import _format_date, _format_datetime

DB_PACKAGE = Path(__file__).resolve().parent.parent / "spdxlims" / "db"


def _patient(database: Database) -> int:
    return database.create_patient(
        {
            "first_name": "Ana",
            "last_name": "Ruiz",
            "middle_name": "",
            "sex": "F",
            "date_of_birth": "",
            "age_value": 30,
            "age_unit": "years",
            "phone": "",
        }
    )


def _order_with_a_result(database: Database) -> int:
    patient_id = _patient(database)
    database.create_test(
        {
            "code": "GLU",
            "name": "Glucosa",
            "category_name": "Chemistry",
            "specimen_type": "Suero",
            "method": "",
            "result_kind": "text",
            "select_options": [],
            "default_result_value": "",
            "price": 0,
        },
        [],
    )
    test_id = database.get_test_id_by_code("GLU")
    order_id = database.create_order(
        None, None, None, patient_id, None, None,
        [{"item_type": "test", "test_id": test_id, "label": "Glucosa", "source": ""}],
        "draft", "",
    )
    entry = database.get_order_result_entries(order_id)[0]
    database.save_result_entry(entry.order_test_id, "90", "", None, None, "", "", "text")
    return order_id


def _is_local(stored: str) -> bool:
    """True when a stored timestamp is this machine's wall clock, not UTC."""
    written = datetime.strptime(str(stored)[:19], "%Y-%m-%d %H:%M:%S")
    return abs(written - datetime.now()) < timedelta(minutes=2)


def test_no_module_writes_the_utc_current_timestamp():
    offenders = [
        path.name
        for path in DB_PACKAGE.rglob("*.py")
        if "CURRENT_TIMESTAMP" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_a_new_database_stores_local_time(tmp_path):
    database = Database(tmp_path / "lims.db")
    database.initialize()
    order_id = _order_with_a_result(database)

    with sqlite3.connect(tmp_path / "lims.db") as raw:
        stored = raw.execute(
            "SELECT ordered_at, created_at, updated_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        entered_at = raw.execute("SELECT entered_at FROM results").fetchone()[0]

    assert all(_is_local(value) for value in stored), stored
    assert _is_local(entered_at), entered_at


def test_an_older_database_keeps_its_utc_defaults_but_is_not_filled_from_them(tmp_path):
    """The table definitions of an existing install still say CURRENT_TIMESTAMP.

    SQLite cannot alter a column default, so every insert names its timestamp
    columns and supplies the local value rather than letting the default fire.
    """
    path = tmp_path / "old.db"
    database = Database(path)
    database.initialize()
    with sqlite3.connect(path) as raw:
        raw.execute("PRAGMA writable_schema = ON")
        for name, sql in raw.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql LIKE '%localtime%'"
        ).fetchall():
            raw.execute(
                "UPDATE sqlite_master SET sql = ? WHERE name = ?",
                (re.sub(r"\(datetime\('now','localtime'\)\)", "CURRENT_TIMESTAMP", sql), name),
            )
        raw.execute("PRAGMA writable_schema = OFF")

    database = Database(path)
    order_id = _order_with_a_result(database)
    with sqlite3.connect(path) as raw:
        stored = raw.execute(
            "SELECT ordered_at, created_at, updated_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()

    assert all(_is_local(value) for value in stored), stored


@pytest.mark.parametrize(
    "stored, expected_hour",
    [
        ("2026-09-19 08:40:34", "08:40"),                  # local mode
        ("2026-09-19T08:40:34-06:00", "08:40"),            # server mode, same zone
    ],
)
def test_a_report_prints_the_wall_clock(stored, expected_hour):
    assert _format_datetime(stored).endswith(expected_hour)


def test_a_utc_timestamp_on_a_report_is_converted_not_printed_raw():
    utc = datetime.now(timezone.utc).replace(microsecond=0)
    printed = _format_datetime(utc.isoformat().replace("+00:00", "Z"))

    assert printed == utc.astimezone().strftime("%d/%m/%Y %H:%M")
    assert _format_date(utc.isoformat().replace("+00:00", "Z")) == utc.astimezone().strftime("%d/%m/%Y")
