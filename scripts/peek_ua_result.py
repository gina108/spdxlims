import sqlite3, json

db = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\instrument-engine\engine.db"
conn = sqlite3.connect(db)
row = conn.execute(
    "SELECT observations_json FROM results WHERE profile_id='urinalysis-com6' ORDER BY updated_at DESC LIMIT 1"
).fetchone()
if row:
    obs = json.loads(row[0])
    print(json.dumps(obs[0] if obs else {}, indent=2))
else:
    print("no rows found")
conn.close()
