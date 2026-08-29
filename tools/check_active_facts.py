import sys
sys.path.insert(0, '.')
import sqlite3
import json
import pathlib
db = sqlite3.connect('outputs/agoda-card-link-candidate-v5-20260826.sqlite')
cur = db.execute("SELECT payload_json FROM direct_verified_lodging_facts WHERE run_id='ota_lodging_run_2026'")
from collections import Counter
prov = Counter()
for r in cur.fetchall():
    p = json.loads(r[0])
    prov[p.get('provider', '?')] += 1
print("Active facts by provider:")
for k, v in prov.most_common():
    print(f"  {k}: {v}")
db.close()