import json
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    d = json.load(f)
for r in d['records']:
    if r['trip_code'] in ['0501_부산', '5월_유럽', '0613_북해도', '0616_레분토&리시리', '0704_아키타', '0712_몽골']:
        print(f'{r["trip_code"]}: {r["starts_on"]} ~ {r["ends_on"]}')