import json
with open('outputs/agoda-card-accounting-draft-v3-v5-final.detail.json', encoding='utf-8') as f:
    d = json.load(f)

# Missing
for r in d['rows']:
    if r.get('target_match_status') == 'authority_missing':
        print(f'MISSING: {r["booking_number"]} | {r["service_start_on"]}~{r["service_end_on"]} | KRW {r["amount_krw"]} | merchant={r.get("merchant_name", "?")} | card={r.get("card_last4", "?")}')

# Ambiguous
for r in d['rows']:
    if r.get('target_match_status') == 'authority_ambiguous':
        print(f'AMBIGUOUS: {r["booking_number"]} | {r["service_start_on"]}~{r["service_end_on"]} | KRW {r["amount_krw"]} | merchant={r.get("merchant_name", "?")} | card={r.get("card_last4", "?")}')