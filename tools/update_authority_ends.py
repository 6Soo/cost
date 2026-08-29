import json
from datetime import date, timedelta

with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)

for r in auth['records']:
    ends_str = r['ends_on']
    ends_date = date.fromisoformat(ends_str)
    new_ends = ends_date + timedelta(days=1)
    r['ends_on'] = new_ends.isoformat()

with open('ledger/data/trip_schedule_authority_v3.json', 'w', encoding='utf-8') as f:
    json.dump(auth, f, ensure_ascii=False, indent=2)

print(f'총 {len(auth["records"])}건 ends_on +1일 갱신 완료')

# 일부 확인
for r in auth['records'][:5]:
    print(f"  {r['trip_code']}: starts={r['starts_on']}, ends={r['ends_on']}")