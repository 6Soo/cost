import json
with open('outputs/agoda-card-accounting-draft-v3-v5-final.detail.json', encoding='utf-8') as f:
    d = json.load(f)

from collections import Counter
cnt = Counter()
for r in d['rows']:
    cnt[r.get('target_match_status', 'unknown')] += 1
print('Match status counts:', dict(cnt))

print()
for r in d['rows']:
    if r.get('target_match_status') == 'authority_missing':
        print(f'  MISSING: {r["booking_number"]} | {r["service_start_on"]}~{r["service_end_on"]} | KRW {r["amount_krw"]}')