import json
from collections import Counter

with open('ledger/data/ota_lodging_facts_v2.json', encoding='utf-8') as f:
    d = json.load(f)

print(f"artifact_type: {d['artifact_type']}")
print(f"acquisition_scope: {d['acquisition_scope']}")
print(f"record_count: {d['record_count']}")
print(f"eligible_count: {d['eligible_count']}")
print(f"withheld_count: {d['withheld_count']}")
print(f"\nSample record keys: {list(d['records'][0].keys())}")
print(f"\nFirst record:")
print(json.dumps(d['records'][0], ensure_ascii=False, indent=2)[:1500])

# Group by provider
providers = Counter()
for r in d['records']:
    p = r.get('provider', '?')
    providers[p] += 1
print(f"\n=== provider 분포 ===")
for p, c in providers.most_common():
    print(f"  {p}: {c}건")