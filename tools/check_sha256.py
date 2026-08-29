import json
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    d = json.load(f)
for i, r in enumerate(d['records']):
    sha = r['source_sha256']
    if len(sha) != 64:
        print(f'record {i} ({r["trip_code"]}): sha256 len={len(sha)} -> {sha}')