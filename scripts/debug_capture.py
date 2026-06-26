"""Show current LIMS UA results for June 17 orders."""
import sqlite3, json

LIMS  = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\spdxlims.db"

lims = sqlite3.connect(LIMS)
lims.row_factory = sqlite3.Row

# Show results for UA orders that were updated
ua_order_ids = (219, 221, 226, 227, 233, 235, 237, 239, 240)
rows = lims.execute("""
    SELECT r.result_value, r.unit, r.entered_at,
           t.code, o.id AS order_id, o.order_number
    FROM results r
    INNER JOIN order_tests ot ON ot.id = r.order_test_id
    INNER JOIN tests t ON t.id = ot.test_id
    INNER JOIN orders o ON o.id = ot.order_id
    WHERE t.code IN ('LEU','NIT','URO','PRO','BLO','KET','BIL','GLUO','PH','SG')
      AND o.id IN (219, 221, 226, 227, 233, 235, 237, 239, 240)
    ORDER BY o.order_number, t.code
""").fetchall()

cur_order = None
for r in rows:
    if r["order_number"] != cur_order:
        cur_order = r["order_number"]
        print(f"\nOrder {cur_order}:")
    val = r["result_value"]
    print(f"  {r['code']:6s}  {str(val):20s}")

lims.close()
