import json
import sqlite3
import hashlib
import pathlib
import sys
sys.stdout.reconfigure(encoding='utf-8')

db_path = pathlib.Path('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
db = sqlite3.connect(str(db_path))

# Wipe existing trip_schedule_authority_v3 records (already loaded)
db.execute("DELETE FROM direct_source_records WHERE source_kind='trip_schedule_authority_v3'")

# Load v3 authority and insert as trip_schedule source
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)

inserted = 0
for r in auth['records']:
    trip_code = r['trip_code']
    # Convert to explicit_shape format
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
    payload_str = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    payload_sha = hashlib.sha256(payload_str.encode('utf-8')).hexdigest()
    db.execute('''INSERT OR IGNORE INTO direct_source_records(source_kind, source_key, source_sha256, payload_json, redaction_version) VALUES (?,?,?,?,?)''',
               ('trip_schedule', trip_code, payload_sha, payload_str, 1))
    inserted += 1

db.commit()
print(f"Authority records inserted as trip_schedule: {inserted}")

# Verify
cur = db.execute("SELECT source_kind, COUNT(*) FROM direct_source_records GROUP BY source_kind")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")
db.close()