import json
from datetime import date

with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    auth = json.load(f)

# Fix 5월_유럽: actual start is 05/07 based on workbook expenses
for r in auth['records']:
    if '유럽' in r['trip_code'] or '5월' in r['trip_code']:
        print(f'Before: {r["trip_code"]}: {r["starts_on"]} ~ {r["ends_on"]}')
        # Find next trip after 05/07
        new_start = date(2026, 5, 7)
        # Find next trip start after this
        next_starts = []
        for r2 in auth['records']:
            s = date.fromisoformat(r2['starts_on'])
            if s > new_start:
                next_starts.append(s)
        if next_starts:
            next_start = min(next_starts)
            new_end = date.fromisoformat(next_start.isoformat())  # next trip start - 1 day
            from datetime import timedelta
            new_end = next_start - timedelta(days=1)
        else:
            new_end = date(2026, 6, 13)  # keep original end if no next
        r['starts_on'] = new_start.isoformat()
        r['ends_on'] = new_end.isoformat()
        print(f'After: {r["trip_code"]}: {r["starts_on"]} ~ {r["ends_on"]}')

with open('ledger/data/trip_schedule_authority_v3.json', 'w', encoding='utf-8') as f:
    json.dump(auth, f, ensure_ascii=False, indent=2)
print("Done")