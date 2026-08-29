import json
from collections import Counter

with open('ledger/data/ota_reconcile_report.json', encoding='utf-8') as f:
    d = json.load(f)

print(f"Type: {type(d).__name__}")
if isinstance(d, dict):
    print(f"Keys: {list(d.keys())[:30]}")
    for k, v in list(d.items())[:10]:
        if isinstance(v, (str, int, float, bool)):
            print(f"  {k}: {v}")
        elif isinstance(v, list):
            print(f"  {k}: list, len={len(v)}")
        elif isinstance(v, dict):
            print(f"  {k}: dict, keys={list(v.keys())[:10]}")
elif isinstance(d, list):
    print(f"Total: {len(d)}")
    if d:
        print(f"Sample: {json.dumps(d[0], ensure_ascii=False, indent=2)[:500]}")