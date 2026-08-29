import json
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    d = json.load(f)

# Valid kinds
VALID_AUTH = {'explicit_trip_registry', 'official_event_schedule', 'user_confirmed_schedule'}

for r in d['records']:
    if r['authority_kind'] not in VALID_AUTH:
        # Q1 workbook trips (0-10) use explicit_trip_registry
        if r.get('source_locator', '').startswith(r"C:\Users\kkokk\AppData\Local\Temp\opencode\q1.xlsx"):
            new_kind = 'explicit_trip_registry'
        else:
            new_kind = 'user_confirmed_schedule'
        print(f"fixing {r['trip_code']}: {r['authority_kind']} -> {new_kind}")
        r['authority_kind'] = new_kind

with open('ledger/data/trip_schedule_authority_v3.json', 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
print("Done")