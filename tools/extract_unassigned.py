import json, sys

with open('outputs/agoda-card-accounting-draft-v3-windowless-v3-20260826.detail.json', encoding='utf-8') as f:
    data = json.load(f)

unassigned = [r for r in data['rows'] if r.get('target_match_status') == 'authority_missing']
print(f"미배정: {len(unassigned)}건")
print()

for i, r in enumerate(unassigned, 1):
    print(f"{i:2d}. booking={r['booking_number']} | 결제일={r['occurred_on']} | 숙박={r['service_start_on']}~{r['service_end_on']} | KRW {r['amount_krw']:,} | lane={r['payment_lane']}")
