import json
with open('outputs/agoda-card-accounting-draft-v3-v5-final.detail.json', encoding='utf-8') as f:
    d = json.load(f)

for r in d['rows']:
    if r.get('target_match_status') == 'authority_ambiguous':
        print(f'  AMBIGUOUS: {r["booking_number"]} | {r["service_start_on"]}~{r["service_end_on"]} | KRW {r["amount_krw"]} | targets={r.get("target_trip_candidates", [])}')