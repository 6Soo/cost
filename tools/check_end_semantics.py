import json
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    d = json.load(f)
for i, r in enumerate(d['records']):
    if r['end_semantics'] != 'inclusive_last_service_date':
        print(f'{i}: {r["trip_code"]} -> {r["end_semantics"]}')