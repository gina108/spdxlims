"""Copy each panel's specimen type and method from the live SQLite into Postgres.

panel_catalog only gained these columns in 20260919_0022, so every panel already
imported has them empty and a server-rendered report prints no methodology line.
import_sqlite.py carries them from now on; this fills in what is already there,
without touching anything else.

Matches on panel code, updates only the two columns, and leaves a panel alone
when the source has neither value.

    python backend/scripts/backfill_panel_metadata.py --sqlite C:\\SPDXLIMS\\data\\spdxlims.db
    python backend/scripts/backfill_panel_metadata.py --sqlite ... --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.models import PanelCatalog  # noqa: E402


def _clean(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, type=Path, help="path to the live spdxlims.db")
    parser.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = parser.parse_args(argv)

    if not args.sqlite.exists():
        print(f"SQLite database not found: {args.sqlite}", file=sys.stderr)
        return 2

    source = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    by_code = {
        str(row["code"]).strip(): row
        for row in source.execute("SELECT code, name, specimen_type, method FROM test_panels")
        if str(row["code"] or "").strip()
    }
    source.close()

    updated = 0
    unchanged = 0
    missing: list[str] = []
    session = SessionLocal()
    try:
        for panel in session.scalars(select(PanelCatalog)).all():
            row = by_code.get((panel.code or "").strip())
            if row is None:
                missing.append(panel.code)
                continue
            specimen_type = _clean(row["specimen_type"])
            method = _clean(row["method"])
            if specimen_type is None and method is None:
                unchanged += 1
                continue
            if panel.specimen_type == specimen_type and panel.method == method:
                unchanged += 1
                continue
            print(f"  {panel.code:<20} muestra={specimen_type or '-':<22} metodo={method or '-'}")
            panel.specimen_type = specimen_type
            panel.method = method
            updated += 1
        if args.dry_run:
            session.rollback()
            print(f"\nDRY RUN - {updated} panel(s) would change, {unchanged} already correct or empty.")
        else:
            session.commit()
            print(f"\nUpdated {updated} panel(s); {unchanged} already correct or empty.")
        if missing:
            print(f"{len(missing)} panel(s) in Postgres have no matching code in SQLite: {', '.join(missing[:10])}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
