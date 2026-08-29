"""Import v3 authority as trip_schedule source records using proper canonical hash."""

import json
import sqlite3
import pathlib
import sys
sys.stdout.reconfigure(encoding='utf-8')

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.direct_sources import _insert_source
from ledger.domain.direct_verified_ota_lodging import END_SEMANTICS

db_path = pathlib.Path('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
db = sqlite3.connect(str(db_path))

# Wipe previous
db.execute("DELETE FROM direct_source_records WHERE source_kind='trip_schedule_authority_v3'")
db.execute("DELETE FROM direct_source_records WHERE source_key IN (SELECT source_key FROM direct_source_records WHERE source_kind='trip_schedule') AND source_key IN (SELECT source_key FROM (SELECT 'tab' as t))")  # safe

# Actually keep trips.json (35) and just add authority 48
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)

inserted = 0
for r in auth['records']:
    trip_code = r['trip_code']
    # Check if exists from trips.json
    cur = db.execute("SELECT 1 FROM direct_source_records WHERE source_kind='trip_schedule' AND source_key=?", (trip_code,))
    if cur.fetchone():
        # Update to use authority version (better data)
        db.execute("DELETE FROM direct_source_records WHERE source_kind='trip_schedule' AND source_key=?", (trip_code,))

    payload = {
        'tab': trip_code,
        'event_year': r['event_year'],
        'starts_on': r['starts_on'],
        'ends_on': r['ends_on'],
        'region': r['region'],
        'authority_kind': r['authority_kind'],
        'authority_status': r['authority_status'],
        'end_semantics': r['end_semantics'],
    }
    source_id, created = _insert_source(db, 'trip_schedule', trip_code, payload)
    inserted += int(created)

db.commit()
print(f"Inserted: {inserted}")
cur = db.execute("SELECT COUNT(*) FROM direct_source_records WHERE source_kind='trip_schedule'")
print(f"Total trip_schedule: {cur.fetchone()[0]}")
db.close()