import json
with open('outputs/agoda-card-accounting-draft-v3-v5-final.detail.json', encoding='utf-8') as f:
    d = json.load(f)

# Check the 9 previously ambiguous
for r in d['rows']:
    bid = r['booking_number']
    if bid in ['661776875', '661778779', '1680375476', '1673605517', 
               '1698436218', '1698435672', '1698435971', '1720330717', '1720331103']:
        print(f'{bid} -> {r["target_authority"]} | {r["service_start_on"]}~{r["service_end_on"]} | KRW {r["amount_krw"]} | {r["target_match_status"]}')