import json
import sqlite3
import hashlib
import pathlib
import sys
sys.stdout.reconfigure(encoding='utf-8')

db_path = pathlib.Path('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
db = sqlite3.connect(str(db_path))
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)
for r in auth['records']:
    trip_code = r['trip_code']
    payload = dict(r)
    payload['source_doc'] = 'trip_schedule_authority_v3.json'
    payload_str = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    payload_sha = hashlib.sha256(payload_str.encode('utf-8')).hexdigest()
    db.execute('''INSERT OR IGNORE INTO direct_source_records(source_kind, source_key, source_sha256, payload_json, redaction_version) VALUES (?,?,?,?,?)''',
               ('trip_schedule_authority_v3', trip_code, payload_sha, payload_str, 1))
db.commit()
print(f"Authority records inserted: {len(auth['records'])}")
db.close()