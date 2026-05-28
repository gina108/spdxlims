from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

DEFAULT_SQLITE_PATH = BACKEND_ROOT.parent / "data" / "spdxlims.db"


@dataclass(frozen=True)
class CountCheck:
    label: str
    sqlite_sql: str
    postgres_sql: str
    required: bool = True


COUNT_CHECKS = [
    CountCheck("patients", "select count(*) from patients", "select count(*) from patient"),
    CountCheck("doctors", "select count(*) from doctors", "select count(*) from provider where provider_type = 'doctor'"),
    CountCheck("clients", "select count(*) from clients", "select count(*) from provider where provider_type = 'clinic'"),
    CountCheck("tests", "select count(*) from tests", "select count(*) from test_catalog"),
    CountCheck("reference_ranges", "select count(*) from test_reference_ranges", "select count(*) from test_reference_range"),
    CountCheck("panels", "select count(*) from test_panels", "select count(*) from panel_catalog"),
    CountCheck("orders", "select count(*) from orders", "select count(*) from lab_order"),
    CountCheck("order_items", "select count(*) from order_tests where test_id is not null", "select count(*) from order_item"),
    CountCheck("results", "select count(*) from results", "select count(*) from result"),
    CountCheck("reports", "select count(*) from reports", "select count(*) from report_snapshot"),
    CountCheck("report_items", "select count(*) from report_items", "select count(*) from report_item_snapshot"),
    CountCheck("lab_profile", "select count(*) from lab_settings", "select count(*) from lab_profile"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare legacy SQLite data counts with migrated PostgreSQL data.")
    parser.add_argument("--sqlite", default=str(DEFAULT_SQLITE_PATH), help="Path to legacy SQLite database.")
    parser.add_argument("--database-url", default="", help="PostgreSQL SQLAlchemy URL. Defaults to DATABASE_URL.")
    parser.add_argument("--allow-extra-users", action="store_true", help="Do not fail because PostgreSQL has app users.")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")

    database_url = args.database_url or __import__("os").environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required. Set it or pass --database-url.")

    sqlite_db = sqlite3.connect(str(sqlite_path))
    engine = create_engine(database_url, future=True)
    failures: list[str] = []
    rows: list[tuple[str, int, int, str]] = []
    try:
        with engine.connect() as pg:
            for check in COUNT_CHECKS:
                sqlite_count = _sqlite_count(sqlite_db, check.sqlite_sql)
                try:
                    postgres_count = _postgres_count(pg, check.postgres_sql)
                except SQLAlchemyError as exc:
                    pg.rollback()
                    failures.append(f"{check.label}: PostgreSQL query failed. Did you run migrations/import first? {exc.__class__.__name__}")
                    rows.append((check.label, sqlite_count, -1, "ERROR"))
                    continue
                status = "OK" if sqlite_count == postgres_count else "MISMATCH"
                rows.append((check.label, sqlite_count, postgres_count, status))
                if check.required and sqlite_count != postgres_count:
                    failures.append(f"{check.label}: SQLite={sqlite_count}, PostgreSQL={postgres_count}")

            try:
                app_user_count = _postgres_count(pg, "select count(*) from app_user")
            except SQLAlchemyError:
                pg.rollback()
                app_user_count = 0
                failures.append("app_user: PostgreSQL app_user table is missing. Run migrations first.")
            if app_user_count < 1 and "app_user: PostgreSQL app_user table is missing. Run migrations first." not in failures:
                failures.append("app_user: PostgreSQL has no app users; server login will not work.")
            elif not args.allow_extra_users:
                rows.append(("app_users", 0, app_user_count, "INFO"))
    finally:
        sqlite_db.close()
        engine.dispose()

    _print_rows(rows)
    if failures:
        print("")
        print("Migration verification failed:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("")
    print("Migration verification passed.")


def _sqlite_count(db: sqlite3.Connection, sql: str) -> int:
    return int(db.execute(sql).fetchone()[0])


def _postgres_count(connection, sql: str) -> int:
    return int(connection.execute(text(sql)).scalar_one())


def _print_rows(rows: list[tuple[str, int, int, str]]) -> None:
    print(f"{'Entity':<18} {'SQLite':>10} {'PostgreSQL':>12}  Status")
    print("-" * 52)
    for label, sqlite_count, postgres_count, status in rows:
        pg_value = "ERROR" if postgres_count < 0 else str(postgres_count)
        print(f"{label:<18} {sqlite_count:>10} {pg_value:>12}  {status}")


if __name__ == "__main__":
    main()
