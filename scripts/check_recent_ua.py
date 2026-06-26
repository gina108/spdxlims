import sqlite3, json
from datetime import datetime, timezone, timedelta

MX = timezone(timedelta(hours=-6))
ENGINE = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\instrument-engine\engine.db"
LIMS   = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\spdxlims.db"

eng = sqlite3.connect(ENGINE)
eng.row_factory = sqlite3.Row

print("=== Engine: last 10 UA captures (all profiles) ===")
rows = eng.execute(
    "SELECT id, profile_id, received_at FROM captures ORDER BY received_at DESC LIMIT 10"
).fetchall()
for r in rows:
    utc = datetime.fromisoformat(r["received_at"].replace("Z","")).replace(tzinfo=timezone.utc)
    local = utc.astimezone(MX).strftime("%H:%M:%S")
    print(f"  {local} MX  {r['received_at']}  {r['profile_id']}  {r['id']}")

eng.close()

print()
print("=== LIMS cache: last 10 captures ===")
lims = sqlite3.connect(LIMS)
lims.row_factory = sqlite3.Row
rows2 = lims.execute(
    "SELECT capture_id, received_at FROM instrument_captures_cache ORDER BY received_at DESC LIMIT 10"
).fetchall()
for r in rows2:
    utc = datetime.fromisoformat(r["received_at"].replace("Z","")).replace(tzinfo=timezone.utc)
    local = utc.astimezone(MX).strftime("%H:%M:%S")
    print(f"  {local} MX  {r['received_at']}  {r['capture_id']}")
lims.close()
