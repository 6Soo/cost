import sys
sys.path.insert(0, '.')
import sqlite3
import json
import pathlib
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.execute("SELECT source_key, payload_json FROM direct_source_records WHERE source_kind='ota_lodging_fact' LIMIT 3")
for r in cur.fetchall():
    p = json.loads(r[1])
    print(p.get('property_name', '?'), p.get('check_in'), p.get('check_out'), 'target:', p.get('target_code'), 'region:', p.get('region', '?'))
db.close()