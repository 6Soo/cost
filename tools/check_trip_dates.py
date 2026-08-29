import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('outputs/agoda-card-accounting-draft-v5-ota-extended.detail.json', encoding='utf-8') as f:
    d = json.load(f)

# Show Trip.com entries
for r in d['rows']:
    if 'Trip' in r['merchant'] or 'TRIP' in r['merchant']:
        print(f"  payment_id={r['payment_id']} | svc={r['service_start_on']}~{r['service_end_on']} | {r['merchant'][:40]}")