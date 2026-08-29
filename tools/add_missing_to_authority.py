"""Add 8 missing trips.json entries to authority_v3."""

import json, sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding='utf-8')

with open('ledger/data/trips.json', encoding='utf-8') as f:
    trips = json.load(f)

with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)

existing = {r['trip_code'] for r in auth['records']}

# Year overrides for specific trips
YEAR_OVERRIDE = {
    "0206_오쿠타다미": 2027,
}

# Build sorted list of all trips by (year, month, day)
all_entries = []
for t in trips:
    mm, dd = t['mm'], t['dd']
    year = YEAR_OVERRIDE.get(t['tab'], 2026)
    try:
        start = date(year, mm, dd)
    except ValueError:
        print(f"SKIP {t['tab']}: invalid date {year}-{mm:02d}-{dd:02d}")
        continue
    all_entries.append((start, t['tab'], t))

all_entries.sort()

# Find gaps for missing trips
new_records = []
for i, (start, code, t) in enumerate(all_entries):
    if code in existing:
        continue
    
    # Find next trip
    next_start = None
    for j in range(i+1, len(all_entries)):
        next_start = all_entries[j][0]
        break
    
    if next_start:
        end = next_start - timedelta(days=1)
    else:
        window = t.get('window', 7)
        end = start + timedelta(days=window - 1)
    
    region = t.get('region', '')
    
    record = {
        "trip_code": code,
        "event_year": start.year,
        "starts_on": start.isoformat(),
        "ends_on": end.isoformat(),
        "region": region,
        "authority_kind": "trips_json_derived",
        "source_locator": "trips.json",
        "source_sha256": "",
        "authority_status": "authoritative",
        "end_semantics": "exclusive_next_trip_start",
    }
    new_records.append(record)
    print(f"  {code} | {start.year}-{start.month:02d}-{start.day:02d} ~ {end.isoformat()} | {region}")

# Add to authority
auth['records'].extend(new_records)

# Sort by starts_on
auth['records'].sort(key=lambda r: r['starts_on'])

# Write back
with open('ledger/data/trip_schedule_authority_v3.json', 'w', encoding='utf-8') as f:
    json.dump(auth, f, ensure_ascii=False, indent=2)

print(f"\n추가 완료: {len(new_records)}건")
print(f"전체: {len(auth['records'])}건")
