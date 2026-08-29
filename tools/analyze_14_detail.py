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

# Find unmatched 14
remaining = []
for r in unassigned:
    svc_start = parse(r['service_start_on'])
    svc_end_raw = parse(r['service_end_on'])
    svc_end = svc_end_raw - timedelta(days=1)
    
    candidates = []
    for t in trips:
        t_start = parse(t['starts_on'])
        t_end = parse(t['ends_on'])
        if svc_start <= t_end and svc_end >= t_start:
            candidates.append(t['trip_code'])
    
    if len(candidates) == 0:
        # Find nearest trip
        before = None
        after = None
        for t in trips:
            t_start = parse(t['starts_on'])
            t_end = parse(t['ends_on'])
            if t_end < svc_start:
                before = t
            if t_start > svc_end and after is None:
                after = t
        
        remaining.append({
            'booking': r['booking_number'],
            'pay_date': r['occurred_on'],
            'svc_start': r['service_start_on'],
            'svc_end': r['service_end_on'],
            'amount': r['amount_krw'],
            'before_trip': before['trip_code'] if before else None,
            'before_end': before['ends_on'] if before else None,
            'after_trip': after['trip_code'] if after else None,
            'after_start': after['starts_on'] if after else None,
        })

print(f"=== 14건 미매칭 상세 분석 ===\n")

# Group by pattern
pattern_a = []  # trip 시작일 전날 체크인
pattern_b = []  # 아예 trip 없음

for r in remaining:
    svc_end = parse(r['svc_end'])
    after_start = parse(r['after_start']) if r['after_start'] else None
    
    if after_start and (after_start - svc_end).days == 1:
        # 숙박 마지막 이용일 = trip 시작일 - 1 → 딱 1일 차이
        pattern_a.append(r)
    else:
        pattern_b.append(r)

print(f"패턴A: 숙박 마지막 이용일 = trip 시작일 직전 ({len(pattern_a)}건)")
print(f"  → trip 시작 전날 체크아웃 = trip에 포함 가능")
print()
for r in pattern_a:
    gap = (parse(r['after_start']) - svc_end).days if r['after_start'] else '?'
    print(f"  {r['booking']} | 숙박 {r['svc_start']}~{r['svc_end']} | 다음trip {r['after_trip']} ({r['after_start']}) | gap={gap}일 | KRW {r['amount']:>10,}")

print(f"\n패턴B: trip과 겹치지 않는 독립 기간 ({len(pattern_b)}건)")
print()
for r in pattern_b:
    before_info = f"이전trip {r['before_trip']}({r['before_end']})" if r['before_trip'] else "이전trip 없음"
    after_info = f"다음trip {r['after_trip']}({r['after_start']})" if r['after_trip'] else "다음trip 없음"
    
    if r['before_trip'] and r['after_trip']:
        gap_before = (parse(r['svc_start']) - parse(r['before_end'])).days
        gap_after = (parse(r['after_start']) - parse(r['svc_end'])).days
        gap_info = f"gap: 이전trip과 {gap_before}일, 다음trip과 {gap_after}일"
    elif r['before_trip']:
        gap_before = (parse(r['svc_start']) - parse(r['before_end'])).days
        gap_info = f"gap: 이전trip과 {gap_before}일"
    else:
        gap_info = "gap: 다음trip 없음"
    
    print(f"  {r['booking']} | 숙박 {r['svc_start']}~{r['svc_end']} | {before_info} | {after_info} | {gap_info} | KRW {r['amount']:>10,}")
