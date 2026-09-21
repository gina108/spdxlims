"""Seed instrument_capture_link from what already knows the answer.

The link table is new, so without this every capture imported before it existed
looks unimported on every workstation and invites a second import over results
someone may have corrected by hand.

Two sources:

  audit   - every import writes an audit event. Useful only from 2026-09-21
            onward: before that the desktop never sent capture_id, so the
            events recorded it as null.
  sqlite  - an app's own order_ui_state, scope 'instrument_capture', which is
            where "linked" used to live. Only rows whose order_id is a server
            UUID are usable; the int ones are from the local-mode era and name
            a row in a different database.

  python scripts/backfill_instrument_capture_links.py [--sqlite PATH] [--apply]

Without --apply it only reports what it would write.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.models import AuditEvent, InstrumentCaptureLink, LabOrder  # noqa: E402


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _from_audit(db) -> dict[str, tuple]:
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity == "instrument_result_import", AuditEvent.action == "import")
        .order_by(AuditEvent.created_at.asc())
    ).all()
    # Oldest first, so the newest import of a capture wins - the same rule
    # _record_capture_link follows.
    found: dict[str, tuple] = {}
    for event in events:
        payload = event.after_json if isinstance(event.after_json, dict) else {}
        capture_id = str(payload.get("capture_id") or "").strip()
        order_id = str(payload.get("order_id") or "").strip()
        if capture_id and _is_uuid(order_id):
            found[capture_id] = (order_id, event.actor_user_id, event.created_at)
    print(f"audit : {len(events)} import event(s) -> {len(found)} capture(s)")
    return found


def _from_sqlite(path: Path) -> dict[str, tuple]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT entity_id, value FROM order_ui_state WHERE scope = 'instrument_capture'"
        ).fetchall()
    finally:
        connection.close()
    found: dict[str, tuple] = {}
    for row in rows:
        try:
            value = json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(value, dict):
            continue
        order_id = str(value.get("order_id") or "").strip()
        capture_id = str(row["entity_id"] or "").strip()
        if capture_id and _is_uuid(order_id):
            found[capture_id] = (order_id, None, None)
    print(f"sqlite: {len(rows)} row(s) -> {len(found)} with a server order id")
    return found


def main() -> int:
    apply_changes = "--apply" in sys.argv
    sqlite_path: Path | None = None
    if "--sqlite" in sys.argv:
        sqlite_path = Path(sys.argv[sys.argv.index("--sqlite") + 1]).resolve()

    db = SessionLocal()
    try:
        candidates = _from_audit(db)
        if sqlite_path is not None:
            # The audit trail is the better witness where both have an opinion.
            candidates = {**_from_sqlite(sqlite_path), **candidates}

        known_orders = {str(order_id) for order_id in db.scalars(select(LabOrder.id)).all()}
        existing = {link.capture_id for link in db.scalars(select(InstrumentCaptureLink)).all()}

        written = skipped_existing = skipped_missing_order = 0
        for capture_id, (order_id, actor, linked_at) in sorted(candidates.items()):
            if capture_id in existing:
                skipped_existing += 1
                continue
            if order_id not in known_orders:
                # The order was deleted since; the FK would reject the row.
                skipped_missing_order += 1
                continue
            written += 1
            if apply_changes:
                link = InstrumentCaptureLink(capture_id=capture_id, order_id=order_id, linked_by=actor)
                if linked_at is not None:
                    link.linked_at = linked_at
                db.add(link)
        if apply_changes:
            db.commit()

        print()
        print(f"distinct captures      : {len(candidates)}")
        print(f"links {'written' if apply_changes else 'to write'}         : {written}")
        print(f"already present        : {skipped_existing}")
        print(f"order no longer exists : {skipped_missing_order}")
        if not apply_changes:
            print("\nDry run. Re-run with --apply to write.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
