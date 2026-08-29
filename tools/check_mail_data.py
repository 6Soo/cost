import json
from collections import Counter
import sys
sys.stdout.reconfigure(encoding='utf-8')

# ota_mail_index.json (1802 records, July)
with open('ledger/data/ota_mail_index.json', encoding='utf-8') as f:
    ota = json.load(f)
print(f"=== ota_mail_index.json ({len(ota['records'])}건) ===")
prov = Counter(r.get('provider', '?') for r in ota['records'])
for p, c in prov.most_common():
    print(f"  {p}: {c}건")

# ota_mail_live_index.json (451 records, August)
with open('ledger/data/ota_mail_live_index.json', encoding='utf-8') as f:
    live = json.load(f)
print(f"\n=== ota_mail_live_index.json ({len(live['records'])}건) ===")
prov = Counter(r.get('provider', '?') for r in live['records'])
for p, c in prov.most_common():
    print(f"  {p}: {c}건")

# pg_mail_index.json
with open('ledger/data/pg_mail_index.json', encoding='utf-8') as f:
    pg = json.load(f)
print(f"\n=== pg_mail_index.json ({len(pg['records'])}건) ===")
prov = Counter(r.get('provider', '?') for r in pg['records'])
for p, c in prov.most_common(20):
    print(f"  {p}: {c}건")

# Check bookingRefs
print(f"\n=== OTA mail bookingRefs (sample) ===")
for r in ota['records'][:5]:
    print(f"  {r.get('provider')}: refs={r.get('bookingRefs')} dates={r.get('travelDates')}")

# Count unique bookingRefs
ota_refs = set()
for r in ota['records']:
    for ref in r.get('bookingRefs', []):
        ota_refs.add(ref)
print(f"\nUnique bookingRefs in ota_mail_index: {len(ota_refs)}")

live_refs = set()
for r in live['records']:
    for ref in r.get('bookingRefs', []):
        live_refs.add(ref)
print(f"Unique bookingRefs in ota_mail_live_index: {len(live_refs)}")