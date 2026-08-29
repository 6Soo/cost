import sys
sys.path.insert(0, '.')
import sqlite3
import json
import pathlib
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.execute("SELECT payload_json FROM direct_source_records WHERE source_kind='ota_lodging_fact' LIMIT 10")
for r in cur.fetchall():
    p = json.loads(r[0])
    print(p.get('property_name', '?')[:30], p.get('check_in'), p.get('check_out'), 'tokens:', p.get('address_tokens'))
db.close()