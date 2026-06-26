import urllib.request, json

r = urllib.request.urlopen("http://127.0.0.1:9088/api/v1/profiles", timeout=5)
data = json.loads(r.read())

profiles = data.get("profiles") or []
for p in profiles:
    if p.get("id") == "urinalysis-com6":
        mapping = p.get("mapping") or {}
        tms = mapping.get("test_mappings") or []
        print(f"test_mappings count: {len(tms)}")
        for tm in tms:
            print(f"\n  pattern={tm.get('pattern')}")
            print(f"  keys in tm: {list(tm.keys())}")
            sq = tm.get("semiquant_map")
            print(f"  semiquant_map: {sq}")
