import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('ledger/data/booking_info.json', encoding='utf-8') as f:
    d = json.load(f)

print(f"Total bookings: {len(d)}")
# Show first 3
for k in list(d.keys())[:3]:
    print(f"\n{k}:")
    val = d[k]
    if isinstance(val, dict):
        print(json.dumps(val, ensure_ascii=False, indent=2)[:800])
    else:
        print(repr(val)[:500])

# Provider stats
providers = {}
for k, v in d.items():
    p = 'unknown'
    if isinstance(v, dict):
        p = v.get('provider', v.get('source', 'unknown'))
    providers[p] = providers.get(p, 0) + 1
print(f"\n=== Provider 분포 ===")
for p, c in providers.items():
    print(f"  {p}: {c}건")