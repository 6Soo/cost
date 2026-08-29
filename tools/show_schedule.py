import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    data = json.load(f)

records = data.get("records", data) if isinstance(data, dict) else data
print(f"行程: {len(records)}건")
for r in records:
    if isinstance(r, dict):
        code = r.get("trip_code", "?")
        start = r.get("starts_on", "?")
        end = r.get("ends_on", "?")
        src = r.get("authority_kind", "?")
        print(f"  {code} | {start} ~ {end} | {src}")
