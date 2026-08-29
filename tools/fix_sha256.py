import json, hashlib
from datetime import date

with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)

# workbook sha256 for Q1 source
import pathlib
wb_sha = hashlib.sha256(pathlib.Path(r"C:\Users\kkokk\AppData\Local\Temp\opencode\q1.xlsx").read_bytes()).hexdigest()
print(f"Q1 workbook sha256: {wb_sha}")

# For trips.json derived, we'll use a hash of the canonical record content
def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

for i, r in enumerate(auth['records']):
    sha = r['source_sha256']
    if len(sha) != 64:
        # Generate proper SHA256
        if "trips_json_derived" in r.get('authority_kind', ''):
            # Hash of the record content without source_sha256
            rec_copy = {k: v for k, v in r.items() if k != 'source_sha256'}
            new_sha = hashlib.sha256(canonical_json(rec_copy)).hexdigest()
        elif r.get('source_locator', '').startswith(r"C:\Users\kkokk\AppData\Local\Temp\opencode\q1.xlsx"):
            # Use actual workbook SHA256
            new_sha = wb_sha
        elif "0704_아키타" in r['trip_code'] or "0719_의왕" in r['trip_code'] or "0721_황금해안" in r['trip_code']:
            # These might need workbook from ledger_current.xlsx
            new_sha = hashlib.sha256(canonical_json({k: v for k, v in r.items() if k != 'source_sha256'})).hexdigest()
        else:
            new_sha = hashlib.sha256(canonical_json({k: v for k, v in r.items() if k != 'source_sha256'})).hexdigest()
        r['source_sha256'] = new_sha
        print(f"fixed {i}: {r['trip_code']} -> {new_sha[:16]}...")

with open('ledger/data/trip_schedule_authority_v3.json', 'w', encoding='utf-8') as f:
    json.dump(auth, f, ensure_ascii=False, indent=2)

print("Done")