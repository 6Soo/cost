import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('ledger/data/trips.json', encoding='utf-8') as f:
    trips = json.load(f)

with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)

trips_codes = {t['tab'] for t in trips}
auth_codes = {r['trip_code'] for r in auth['records']}

print(f"trips.json: {len(trips_codes)}건")
print(f"authority_v3: {len(auth_codes)}건")
print()

only_trips = trips_codes - auth_codes
only_auth = auth_codes - trips_codes
both = trips_codes & auth_codes

print(f"=== trips에만 있는 것 (authority에 누락): {len(only_trips)}건 ===")
for code in sorted(only_trips):
    t = next(x for x in trips if x['tab'] == code)
    print(f"  {code} | mm={t['mm']} dd={t['dd']} region={t['region']} window={t.get('window')}")

print()
print(f"=== authority에만 있는 것: {len(only_auth)}건 ===")
for code in sorted(only_auth):
    r = next(x for x in auth['records'] if x['trip_code'] == code)
    print(f"  {code} | {r['starts_on']}~{r['ends_on']} {r['region']}")

print()
print(f"=== 둘 다 있는 것: {len(both)}건 ===")
