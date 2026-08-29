import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('outputs/agoda-card-accounting-draft-v5-ota-extended.detail.json', encoding='utf-8') as f:
    d = json.load(f)

print(f"=== 30건 미배정 상세 ===")
for r in d['rows']:
    if r['target_match_status'] == 'authority_missing':
        print(f"{r['booking_id']:>4} | svc={r['service_start_on']}~{r['service_end_on']} | {r['merchant'][:40]:40s} | KRW {r['amount_krw']:>10,} | {r['occurred_on']}")