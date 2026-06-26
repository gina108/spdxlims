"""
Retroactively apply urinalysis semiquant mapping to today's results.
Run with the instrument engine STOPPED.
"""

import sqlite3, json, yaml, shutil
from datetime import datetime, timezone

DB   = r"C:\Users\Admin\Documents\GitHub\spdxlims\data\instrument-engine\engine.db"
YAML = r"C:\Users\Admin\Documents\GitHub\spdxlims\instrument-connectivity\profiles\urinalysis-com6.yaml"

# --- load profile ---
with open(YAML) as f:
    profile = yaml.safe_load(f)

mapping = profile.get("mapping", {})
value_norm  = mapping.get("value_normalization", {}) or {}
test_maps   = {tm["pattern"]: tm for tm in (mapping.get("test_mappings", []) or [])}
alias_map   = {}
for canonical, aliases in (mapping.get("test_code_aliases", {}) or {}).items():
    for a in aliases:
        alias_map[a.upper()] = canonical

def qualifier_from_raw(value_raw):
    """Mirror the Go qualifier extraction logic."""
    tokens = value_raw.split()
    if not tokens:
        return ""
    q = tokens[0]
    if q in ("-", "+") and len(tokens) > 1:
        nxt = tokens[1]
        if nxt and not (nxt[0].isdigit() or nxt[0] == "."):
            q += nxt
    return q

def apply_semiquant(obs, semiquant_map):
    """Return updated obs dict, or None if no semiquant_map defined."""
    q = qualifier_from_raw(obs.get("value_raw", "") or "")
    if not q:
        return obs

    # Sort keys longest-first
    for key in sorted(semiquant_map.keys(), key=len, reverse=True):
        if q.lower().startswith(key.lower()):
            entry = semiquant_map[key]
            obs = dict(obs)
            obs["value_text"] = entry.get("display", "")
            obs["value_raw"]  = entry.get("display", "")
            v = entry.get("value")
            obs["value_numeric"] = float(v) if v is not None else None
            return obs

    # No match — blank for manual entry
    obs = dict(obs)
    obs["value_text"]      = ""
    obs["value_raw"]       = ""
    obs["value_numeric"]   = None
    obs["units_raw"]       = ""
    obs["units_normalized"] = ""
    return obs

def apply_value_norm(obs):
    vt = (obs.get("value_text") or "").strip()
    for frm, to in value_norm.items():
        if vt.lower() == frm.lower():
            obs = dict(obs)
            obs["value_text"] = to
            obs["value_raw"]  = to
            obs["value_numeric"] = None
            return obs
    return obs

# --- backup ---
stamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = DB + f".backup_{stamp}"
shutil.copy2(DB, backup)
print(f"Backup: {backup}")

# --- connect ---
conn   = sqlite3.connect(DB)
today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
rows   = conn.execute(
    "SELECT profile_id, analyzer_run_id, observations_json, updated_at "
    "FROM results WHERE profile_id='urinalysis-com6' AND date(updated_at)=?",
    (today,)
).fetchall()

print(f"\nResults to update: {len(rows)}\n")

for profile_id, run_id, obs_json, updated_at in rows:
    observations = json.loads(obs_json)
    updated = []
    changes = []

    for obs in observations:
        code      = obs.get("instrument_test_code", "")
        canonical = alias_map.get(code.upper(), code)
        tm        = test_maps.get(canonical, {})
        sq_map    = tm.get("semiquant_map")

        orig_raw  = obs.get("value_raw", "")

        if sq_map:
            new_obs = apply_semiquant(obs, sq_map)
        else:
            new_obs = apply_value_norm(obs)

        if new_obs.get("value_raw") != orig_raw:
            changes.append(
                f"  {code:6s}  {orig_raw!r:30s} -> {new_obs.get('value_raw')!r}"
            )
        updated.append(new_obs)

    if changes:
        print(f"Run {run_id}:")
        for c in changes:
            print(c)
        conn.execute(
            "UPDATE results SET observations_json=? WHERE profile_id=? AND analyzer_run_id=?",
            (json.dumps(updated), profile_id, run_id)
        )
    else:
        print(f"Run {run_id}: no changes needed")

conn.commit()
conn.close()
print("\nDone.")
