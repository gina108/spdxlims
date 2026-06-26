import sqlite3, json

db = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\instrument-engine\engine.db"
conn = sqlite3.connect(db)

print("=== RAW CAPTURES (last 3) ===")
rows = conn.execute(
    "SELECT id, decoded_text, received_at FROM captures "
    "WHERE profile_id='urinalysis-com6' ORDER BY received_at DESC LIMIT 3"
).fetchall()
for row in rows:
    print(f"ID: {row[0]}  at: {row[2]}")
    print(repr(row[1]))
    print()

print("=== PARSED RESULTS (last 2) ===")
rows2 = conn.execute(
    "SELECT analyzer_run_id, observations_json FROM results "
    "WHERE profile_id='urinalysis-com6' ORDER BY updated_at DESC LIMIT 2"
).fetchall()
for run_id, obs_json in rows2:
    print(f"Run: {run_id}")
    for obs in json.loads(obs_json):
        code = obs.get("instrument_test_code", "")
        raw  = obs.get("value_raw", "")
        text = obs.get("value_text", "")
        num  = obs.get("value_numeric")
        print(f"  {code:6s}  raw={raw!r:30s}  text={text!r}  num={num}")
    print()

conn.close()
