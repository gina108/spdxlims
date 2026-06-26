import sqlite3

db = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\instrument-engine\engine.db"
conn = sqlite3.connect(db)

tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t[0] for t in tables])
for (tbl,) in tables:
    cols = conn.execute(f"PRAGMA table_info({tbl})").fetchall()
    print(f"\n{tbl}: {[c[1] for c in cols]}")

conn.close()
