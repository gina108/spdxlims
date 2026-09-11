"""Clear all lab data from the PostgreSQL backend, ready for a fresh SQLite import.

``import_sqlite.py`` only inserts, so re-running it against a populated database
duplicates every row. Run this first. Login accounts (``app_user``) and the
alembic revision marker are deliberately preserved so the server stays usable
and migrations are not re-run.

Usage:
    python backend/scripts/truncate_data.py --yes
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.db.session import SessionLocal

# Never cleared: app_user holds the logins people sign in with, and
# alembic_version must keep matching the schema actually on disk.
PRESERVE = {"app_user", "alembic_version"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required. Confirms that every lab data row will be deleted.",
    )
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("Refusing to run without --yes (this deletes all lab data).")

    db = SessionLocal()
    try:
        names = [
            row[0]
            for row in db.execute(
                text(
                    "select tablename from pg_tables "
                    "where schemaname = 'public' order by tablename"
                )
            )
        ]
        targets = [n for n in names if n not in PRESERVE]
        if not targets:
            raise SystemExit("No tables to truncate.")

        before = {n: db.execute(text(f'select count(*) from "{n}"')).scalar() for n in targets}

        quoted = ", ".join(f'"{n}"' for n in targets)
        db.execute(text(f"truncate table {quoted} restart identity cascade"))
        db.commit()
    finally:
        db.close()

    cleared = {n: c for n, c in before.items() if c}
    print(f"Truncated {len(targets)} tables ({len(cleared)} held rows).")
    for name, count in sorted(cleared.items()):
        print(f"  {name:40} -{count}")


if __name__ == "__main__":
    main()
