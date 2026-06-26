"""Check result_kind for UA tests in LIMS."""
import sqlite3

LIMS = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\spdxlims.db"
lims = sqlite3.connect(LIMS)
lims.row_factory = sqlite3.Row

ua_tests = ("LEU", "NIT", "URO", "PRO", "PH", "BLO", "SG", "KET", "BIL", "GLUO")
placeholders = ",".join("?" * len(ua_tests))
rows = lims.execute(
    f"SELECT id, code, name, result_kind FROM tests WHERE code IN ({placeholders})",
    ua_tests
).fetchall()
print("UA tests result_kind:")
for r in rows:
    print(f"  id={r['id']}  code={r['code']:6s}  result_kind={r['result_kind']!r:15s}  name={r['name']!r}")

lims.close()
