import json
from collections import Counter

with open('ledger/data/ota_event_links_verified.json', encoding='utf-8') as f:
    d = json.load(f)

print(f"Type: {type(d).__name__}")
if isinstance(d, dict):
    print(f"Keys: {list(d.keys())[:20]}")
    for k, v in list(d.items())[:15]:
        if isinstance(v, (str, int, float, bool)):
            print(f"  {k}: {v}")
        elif isinstance(v, list):
            print(f"  {k}: list, len={len(v)}")
            if v and isinstance(v[0], dict):
                print(f"    sample: {json.dumps(v[0], ensure_ascii=False, indent=2)[:500]}")
        elif isinstance(v, dict):
            print(f"  {k}: dict, keys={list(v.keys())[:5]}")
elif isinstance(d, list):
    print(f"Total: {len(d)}")
    if d:
        # group by provider
        prov = Counter(r.get('provider', '?') for r in d if isinstance(r, dict))
        print(f"By provider: {dict(prov)}")