"""
Fix today's urinalysis LIMS results.

Strategy for each engine observation:
  - If value_raw looks like raw machine output (starts with -, +, or ends with +)
    -> apply the semiquant map to get the correct display value
  - Otherwise value_raw is already the display value
    -> use it as-is

This handles both observations that were already mapped by the engine (non-asterisk
codes, engine ran with updated profile) and observations that weren't (asterisk codes,
or captures from before the profile update).
"""

import sqlite3, json, yaml, shutil
from datetime import datetime, timezone

LIMS      = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\spdxlims.db"
ENGINE    = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\instrument-engine\engine.db"
YAML_PATH = r"C:\Users\Admin\Documents\GitHub\spdxlims\instrument-connectivity\profiles\urinalysis-com6.yaml"

# ── load YAML ────────────────────────────────────────────────────────────────

with open(YAML_PATH) as f:
    profile = yaml.safe_load(f)

mapping   = profile.get("mapping", {})
test_maps: dict[str, dict] = {}
for tm in (mapping.get("test_mappings", []) or []):
    sq = tm.get("semiquant_map")
    if sq:
        test_maps[tm["pattern"]] = sq

# YAML pattern for each normalised instrument code
CODE_TO_PATTERN = {
    "LEU": "LEU", "NIT": "NIT", "URO": "URO", "PRO": "PRO",
    "BLO": "BLO", "KET": "KET", "BIL": "BIL", "GLU": "GLU",
}
# Instrument code -> LIMS test code
CODE_TO_LIMS = {
    "LEU": "LEU", "NIT": "NIT", "URO": "URO", "PRO": "PRO",
    "BLO": "BLO", "KET": "KET", "BIL": "BIL", "GLU": "GLUO",
    "PH": "PH", "SG": "SG",
}

# ── helpers ───────────────────────────────────────────────────────────────────

def extract_qualifier(raw: str) -> str:
    tokens = (raw or "").split()
    if not tokens:
        return ""
    q = tokens[0]
    if q in ("-", "+") and len(tokens) > 1:
        nxt = tokens[1]
        if nxt and not (nxt[0].isdigit() or nxt[0] == "."):
            q += nxt
    return q


def is_raw_machine_value(raw: str) -> bool:
    """True if value looks like unprocessed machine output."""
    q = extract_qualifier(raw)
    if not q:
        return False
    return q.startswith("-") or q.startswith("+") or q.endswith("+")


def apply_semiquant(raw: str, sq_map: dict) -> str | None:
    """Return display string, or None if no key matched (blank for manual entry)."""
    q = extract_qualifier(raw)
    if not q:
        return None
    for key in sorted(sq_map.keys(), key=len, reverse=True):
        if q.lower().startswith(key.lower()):
            return sq_map[key].get("display", "")
    return None


def correct_value_for(norm_code: str, value_raw: str) -> str | None:
    """
    Return the correct LIMS display value for this observation.
    Returns None if the semiquant map defines no match (blank for manual entry).
    """
    # PH, SG: numeric pass-through
    if norm_code in ("PH", "SG"):
        return value_raw

    # URO: cosmetic fix for legacy '.2'
    if norm_code == "URO":
        if value_raw in (".2",):
            return "0.2"
        if not is_raw_machine_value(value_raw):
            return value_raw
        # Fall through to semiquant (key '-' maps '- 0.2 mg/dL' to '0.2')

    pattern = CODE_TO_PATTERN.get(norm_code)
    sq_map  = test_maps.get(pattern, {}) if pattern else {}

    if not sq_map:
        # No semiquant map -> pass value through as-is
        return value_raw

    if is_raw_machine_value(value_raw):
        # Raw machine value -> apply semiquant
        return apply_semiquant(value_raw, sq_map)
    else:
        # Already a display value -> use as-is
        return value_raw


# ── backup ───────────────────────────────────────────────────────────────────

stamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = LIMS + f".backup_{stamp}"
shutil.copy2(LIMS, backup)
print(f"Backup: {backup}\n")

# ── find today's UA linked captures ──────────────────────────────────────────

lims = sqlite3.connect(LIMS)
lims.row_factory = sqlite3.Row

row = lims.execute("SELECT ui_state FROM lab_settings WHERE id=1").fetchone()
ui_state       = json.loads(row["ui_state"] or "{}") if row else {}
linked_caps    = ui_state.get("results_linked_instrument_captures", {})
# linked_at is stored in LOCAL time by the LIMS app.
# Check both today-local and yesterday-local to handle UTC midnight crossover.
local_today     = datetime.now().strftime("%Y-%m-%d")
local_yesterday = datetime.now().replace(day=datetime.now().day - 1).strftime("%Y-%m-%d") \
    if datetime.now().day > 1 else None
date_prefixes = {local_today}
if local_yesterday:
    date_prefixes.add(local_yesterday)

ua_links: dict[str, int] = {}
for cap_id, info in linked_caps.items():
    la = str(info.get("linked_at") or "")
    if any(la.startswith(d) for d in date_prefixes):
        ua_links[cap_id] = int(info["order_id"])

print(f"Today's linked captures: {len(ua_links)}\n")

# ── process each capture ──────────────────────────────────────────────────────

eng = sqlite3.connect(ENGINE)
eng.row_factory = sqlite3.Row
updates: list[tuple[str | None, int, bool]] = []  # (new_val, ot_id, needs_insert)

for cap_id, order_id in ua_links.items():
    eng_row = eng.execute(
        "SELECT profile_id, observations_json FROM results WHERE capture_id=?",
        (cap_id,)
    ).fetchone()
    if eng_row is None:
        # results row may have been overwritten by a run_id reuse; fall back to
        # captures.parsed_json which is keyed by the unique capture id
        cap_row = eng.execute(
            "SELECT profile_id, parsed_json FROM captures WHERE id=?",
            (cap_id,)
        ).fetchone()
        if cap_row is None or cap_row["profile_id"] != "urinalysis-com6":
            continue
        parsed = json.loads(cap_row["parsed_json"] or "{}")
        observations = parsed.get("message", {}).get("observations", [])
    elif eng_row["profile_id"] != "urinalysis-com6":
        continue
    else:
        observations = json.loads(eng_row["observations_json"])
    changes: list[str] = []

    for obs in observations:
        raw_code  = str(obs.get("instrument_test_code") or "")
        norm_code = "".join(c for c in raw_code.lstrip("*").upper().strip()
                            if c.isalnum() or c in {"-", "_"})
        lims_code = CODE_TO_LIMS.get(norm_code)
        if not lims_code:
            continue

        value_raw  = str(obs.get("value_raw") or "").strip()
        new_val    = correct_value_for(norm_code, value_raw)

        # Find the LIMS order_test + current result
        ot_row = lims.execute(
            """
            SELECT ot.id AS ot_id, r.result_value AS cur_val,
                   (r.order_test_id IS NOT NULL) AS has_result
            FROM order_tests ot
            INNER JOIN tests t ON t.id = ot.test_id
            LEFT JOIN results r ON r.order_test_id = ot.id
            WHERE ot.order_id = ? AND t.code = ?
            """,
            (order_id, lims_code)
        ).fetchone()
        if ot_row is None:
            continue

        cur_val    = ot_row["cur_val"]
        ot_id      = int(ot_row["ot_id"])
        has_result = bool(ot_row["has_result"])

        if new_val == cur_val:
            continue

        # Only update if the current LIMS value is still a raw machine value
        # or NULL (couldn't be stored). Leave valid display values alone
        # because they may come from a more recent scan import.
        cur_is_raw = (cur_val is None) or is_raw_machine_value(cur_val)
        if not cur_is_raw:
            changes.append(f"  {lims_code}: {cur_val!r}  (already a display value, skipping)")
            continue

        if new_val is None:
            label = "-> BLANK"
        else:
            label = f"-> {new_val!r}"
        changes.append(f"  {lims_code}: {cur_val!r}  {label}")
        updates.append((new_val, ot_id, not has_result))

    if changes:
        print(f"Order {order_id}  ({cap_id}):")
        for c in changes:
            print(c)
        print()

eng.close()

# ── apply ─────────────────────────────────────────────────────────────────────

if not updates:
    print("No updates needed.")
    lims.close()
    raise SystemExit(0)

print(f"Applying {len(updates)} update(s)...")
with lims:
    for new_val, ot_id, needs_insert in updates:
        if needs_insert:
            lims.execute(
                "INSERT INTO results (order_test_id, result_value, entered_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (ot_id, new_val)
            )
        else:
            lims.execute(
                "UPDATE results SET result_value = ?, entered_at = CURRENT_TIMESTAMP WHERE order_test_id = ?",
                (new_val, ot_id)
            )

lims.close()
print("Done.")
