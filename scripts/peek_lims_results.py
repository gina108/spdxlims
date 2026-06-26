import sqlite3
from datetime import datetime, timezone

DB = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\spdxlims.db"
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT r.order_test_id, r.result_value, r.unit, r.entered_at,
           t.code AS test_code, t.name AS test_name,
           o.order_number, o.id AS order_id
    FROM results r
    INNER JOIN order_tests ot ON ot.id = r.order_test_id
    INNER JOIN tests t ON t.id = ot.test_id
    INNER JOIN orders o ON o.id = ot.order_id
    WHERE date(r.entered_at) = ?
    ORDER BY r.entered_at DESC
""", (today,)).fetchall()

print(f"Results entered today: {len(rows)}\n")
for row in rows:
    print(f"  order={row['order_number']}  test={row['test_code']:20s}  value={row['result_value']!r:30s}  unit={row['unit']!r}  at={row['entered_at']}")

conn.close()
