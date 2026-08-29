"""Add missing trips.json entries to authority_v3 using mm/dd + next-trip-boundary."""

import json, sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding='utf-8')

# Load both
with open('ledger/data/trips.json', encoding='utf-8') as f:
    trips = json.load(f)

with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)

existing = {r['trip_code'] for r in auth['records']}

# Map of tab -> (mm, dd) from trips.json
trip_map = {t['tab']: t for t in trips}

# Build sorted list of all trips by start date (using mm/dd)
all_entries = []
for t in trips:
    mm, dd = t['mm'], t['dd']
    try:
        start = date(2026, mm, dd)
    except ValueError:
        print(f"SKIP {t['tab']}: invalid date 2026-{mm:02d}-{dd:02d}")
        continue
    all_entries.append((start, t['tab']))

all_entries.sort()

# Build date->next_trip mapping
for i, (start, code) in enumerate(all_entries):
    if code in existing:
        continue
    # Next trip start
    if i + 1 < len(all_entries):
        next_start = all_entries[i+1][0]
        end = next_start - timedelta(days=1)
    else:
        # Last trip - use window if available
        t = trip_map[code]
        window = t.get('window', 7)
        end = start + timedelta(days=window - 1)
    
    region = trip_map[code].get('region', '')
    
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
    
    print(f"ADD: {code} | {start.isoformat()} ~ {end.isoformat()} | {region}")

print(f"\n총 {len([t for t in trips if t['tab'] not in existing])}건 추가 예정")
