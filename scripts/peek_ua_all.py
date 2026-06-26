import sqlite3, json
from datetime import datetime, timezone

db = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\instrument-engine\engine.db"
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

conn = sqlite3.connect(db)
rows = conn.execute(
    "SELECT analyzer_run_id, observations_json, updated_at FROM results "
    "WHERE profile_id='urinalysis-com6' AND date(updated_at)=? ORDER BY updated_at DESC",
    (today,)
).fetchall()

print(f"Results today: {len(rows)}\n")
for run_id, obs_json, updated_at in rows:
    obs_list = json.loads(obs_json)
    print(f"Run: {run_id}  ({updated_at})")
    for obs in obs_list:
        code  = obs.get("instrument_test_code", "")
        raw   = obs.get("value_raw", "")
        text  = obs.get("value_text", "")
        num   = obs.get("value_numeric")
        units = obs.get("units_raw", "")
        print(f"  {code:6s}  raw={raw!r:30s}  text={text!r:30s}  num={num}  units={units!r}")
    print()
conn.close()
