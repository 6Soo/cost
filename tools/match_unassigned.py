import json, sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

# 1. Load trip schedule
with open('ledger/data/trip_schedule_authority_v3.json', encoding='utf-8') as f:
    sched = json.load(f)
trips = sched.get("records", [])

# 2. Load unassigned bookings
with open('outputs/agoda-card-accounting-draft-v3-windowless-v3-20260826.detail.json', encoding='utf-8') as f:
    data = json.load(f)
unassigned = [r for r in data['rows'] if r.get('target_match_status') == 'authority_missing']

# 3. For each unassigned, check overlap with each trip
def parse(d):
    return datetime.strptime(d, "%Y-%m-%d").date()

results = []
for r in unassigned:
    svc_start = parse(r['service_start_on'])
    svc_end_raw = parse(r['service_end_on'])
    svc_end = svc_end_raw - timedelta(days=1)  # last service day = checkout - 1
    
    candidates = []
    for t in trips:
        t_start = parse(t['starts_on'])
        t_end = parse(t['ends_on'])
        # Overlap: svc_start <= t_end AND svc_end >= t_start
        if svc_start <= t_end and svc_end >= t_start:
            candidates.append(t['trip_code'])
    
    results.append({
        'booking': r['booking_number'],
        'pay_date': r['occurred_on'],
        'svc_period': f"{r['service_start_on']}~{r['service_end_on']}",
        'amount': r['amount_krw'],
        'candidates': candidates
    })

# 4. Report
auto_match = [r for r in results if len(r['candidates']) == 1]
multi_match = [r for r in results if len(r['candidates']) > 1]
no_match = [r for r in results if len(r['candidates']) == 0]

print(f"=== 25건 미배정 분류 결과 ===")
print(f"단일 후보 (자동 배정 가능): {len(auto_match)}건")
print(f"복수 후보 (수동 판단 필요): {len(multi_match)}건")
print(f"후보 없음 (일정 미확정): {len(no_match)}건")
print()

if auto_match:
    print("--- 단일 후보 ---")
    for r in auto_match:
        print(f"  {r['booking']} | {r['svc_period']} | KRW {r['amount']:>10,} | -> {r['candidates'][0]}")
    print()

if multi_match:
    print("--- 복수 후보 ---")
    for r in multi_match:
        print(f"  {r['booking']} | {r['svc_period']} | KRW {r['amount']:>10,} | -> {r['candidates']}")
    print()

if no_match:
    print("--- 후보 없음 ---")
    for r in no_match:
        print(f"  {r['booking']} | {r['svc_period']} | KRW {r['amount']:>10,}")
    print()

# Summary
total_auto = sum(r['amount'] for r in auto_match)
total_multi = sum(r['amount'] for r in multi_match)
total_none = sum(r['amount'] for r in no_match)
print(f"금액 합계: 자동={total_auto:,} | 복수={total_multi:,} | 미배정={total_none:,}")
print(f"총 미배정: {sum(r['amount'] for r in results):,}")
