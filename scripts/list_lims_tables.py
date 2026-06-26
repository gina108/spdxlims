import sqlite3
conn = sqlite3.connect(r"C:\Users\Admin\Documents\GitHub\spdxlims\data\spdxlims.db")
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
for t in tables:
    print(t[0])
conn.close()
