import json
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    d = json.load(f)

for r in d['records']:
    if r['end_semantics'] != 'inclusive_last_service_date':
        print(f"fixing {r['trip_code']}: {r['end_semantics']} -> inclusive_last_service_date")
        r['end_semantics'] = 'inclusive_last_service_date'

with open('ledger/data/trip_schedule_authority_v3.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
print("Done")