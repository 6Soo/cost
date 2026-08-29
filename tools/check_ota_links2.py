import json
from collections import Counter

with open('ledger/data/ota_event_links_verified.json', encoding='utf-8') as f:
    d = json.load(f)

print(f"Total UID keys: {len(d)}")
print(f"First 5 keys: {list(d.keys())[:5]}")

# Show all unique structures
print("\n=== Sample entries ===")
for k in list(d.keys())[:5]:
    print(f"\n{k}:")
    print(json.dumps(d[k], ensure_ascii=False, indent=2))

# Count categories
cats = Counter()
for k, v in d.items():
    cats[v.get('category', '?')] += 1
print(f"\n=== Category 분포 ===")
for c, cnt in cats.most_common():
    print(f"  {c}: {cnt}건")