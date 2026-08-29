import json
import sqlite3
import hashlib
import pathlib
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Wipe previous attempts
db_path = pathlib.Path('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
db = sqlite3.connect(str(db_path))
db.execute("DELETE FROM direct_source_records WHERE source_kind='trip_schedule_authority_v3'")

with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)

inserted = 0
for r in auth['records']:
    trip_code = r['trip_code']
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
    # Compute payload hash using canonical_json
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    payload_sha = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    db.execute('''INSERT OR IGNORE INTO direct_source_records(source_kind, source_key, source_sha256, payload_json, redaction_version) VALUES (?,?,?,?,?)''',
               ('trip_schedule', trip_code, payload_sha, canonical, 1))
    inserted += 1

db.commit()
print(f"Inserted: {inserted}")

# Verify
cur = db.execute("SELECT COUNT(*) FROM direct_source_records WHERE source_kind='trip_schedule'")
print(f"Total trip_schedule: {cur.fetchone()[0]}")
db.close()