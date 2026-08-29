import json, sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    sched = json.load(f)
trips = sorted(sched.get("records", []), key=lambda t: t['starts_on'])

with open('outputs/agoda-card-accounting-draft-v3-windowless-v3-20260826.detail.json', encoding='utf-8') as f:
    data = json.load(f)
unassigned = [r for r in data['rows'] if r.get('target_match_status') == 'authority_missing']

def parse(d):
    return datetime.strptime(d, "%Y-%m-%d").date()

print("=== trip_schedule 간 간격(pause) 분석 ===\n")
for i in range(len(trips)-1):
    t1_end = parse(trips[i]['ends_on'])
    t2_start = parse(trips[i+1]['starts_on'])
    gap = (t2_start - t1_end).days
    if gap > 1:
        print(f"  {trips[i]['trip_code']} ends {trips[i]['ends_on']}")
        print(f"    -> {trips[i+1]['trip_code']} starts {trips[i+1]['starts_on']}")
        print(f"    gap = {gap} days (gap start: {(t1_end + timedelta(1)).isoformat()} ~ {(t2_start - timedelta(1)).isoformat()})")
        print()

print("\n=== 미배정 숙박이 'gap' 기간에 위치하는지 확인 ===\n")
for r in unassigned:
    svc_start = parse(r['service_start_on'])
    svc_end = parse(r['service_end_on'])
    
    in_gap = None
    for i in range(len(trips)-1):
        t1_end = parse(trips[i]['ends_on'])
        t2_start = parse(trips[i+1]['starts_on'])
        if svc_start >= t1_end and svc_end <= t2_start:
            in_gap = f"{trips[i]['trip_code']}~{trips[i+1]['trip_code']}"
            break
    
    tag = f"GAP: {in_gap}" if in_gap else "NO-GAP"
    print(f"  {r['booking_number']} | {r['service_start_on']}~{r['service_end_on']} | {tag}")
