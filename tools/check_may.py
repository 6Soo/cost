import json
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    d = json.load(f)
for r in d['records']:
    if '0501' in r['trip_code'] or '유럽' in r['trip_code']:
        print(f'{r["trip_code"]}: {r["starts_on"]} ~ {r["ends_on"]}')