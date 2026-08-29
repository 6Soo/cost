import json
from datetime import date, timedelta

with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)

# Find 0501_부산 and extend start to 04/29 for HI Design pre-trip
for r in auth['records']:
    if r['trip_code'] == '0501_부산':
        print(f"Before: {r['trip_code']}: {r['starts_on']} ~ {r['ends_on']}")
        r['starts_on'] = '2026-04-29'
        # ends_on stays 2026-05-05 (next trip is 5월_유럽 05/07, so 05/07-1=05/06, but original was 05/05)
        # Keep original ends_on since it's based on next trip boundary
        # Add note to source_locator
        r['source_locator'] = r['source_locator'] + '#manual_extension=04-29_for_HI_Design_pre_trip'
        print(f"After: {r['trip_code']}: {r['starts_on']} ~ {r['ends_on']}")
        print(f"Locator: {r['source_locator']}")
        break

# Sort by starts_on
auth['records'].sort(key=lambda x: x['starts_on'])

with open('ledger/data/trip_schedule_authority_v3.json', 'w', encoding='utf-8') as f:
    json.dump(auth, f, ensure_ascii=False, indent=2)
print("Done")