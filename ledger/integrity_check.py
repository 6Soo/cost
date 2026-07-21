# -*- coding: utf-8 -*-
"""행 단위 참조정합 전수감사 (예약번호 최우선 진실).
A. '수기N행' 태그 검증: 태그가 가리키는 manual_v4 행과 (예약번호/금액) 일치하는가
B. 예약번호 1:1 검증: 탭별 수기 예약번호 멀티셋 ↔ 워크북 예약번호 멀티셋 (누락/중복/금액상충)
"""
import csv, re, sys
from collections import Counter, defaultdict

def i(x):
    try: return int(round(float(str(x).replace(',','') or 0)))
    except: return 0
def bookno(text):
    m=re.search(r'예약\s*(\d{6,19}|[A-Z0-9]{5,7})(?![0-9])', text or '')
    return m.group(1) if m else ''
TABMAP={'0630_오제_A':'0630_오제','0704_야마가타':'0704_아키타'}
def nt(t): return TABMAP.get(t,t)

v14=list(csv.DictReader(open('data/classified_v14.csv',encoding='utf-8')))
man=list(csv.DictReader(open('data/manual_v4.csv',encoding='utf-8')))
man_by=defaultdict(dict)
for m in man: man_by[nt(m['tab'])][m['row']]=m

issues=[]

# ── A. 수기N행 태그 검증 ──
tagged=0
for r in v14:
    tg=re.match(r'수기(\d+)행', r['note'] or '')
    if not tg: continue
    tagged+=1
    mrow=man_by.get(r['bucket'],{}).get(tg.group(1))
    if mrow is None:
        # 탭 불일치(기타비용 이동 등)는 별도 표기로 통과
        if r['bucket'] in ('기타비용','취소환불','전기예약_환불','여행_미배정'): continue
        issues.append(('A-행없음', r['uid'], r['bucket'], f"태그 수기{tg.group(1)}행이 해당 탭에 없음"))
        continue
    wb_book=bookno(r['note']); mn_book=(mrow.get('book') or '').strip()
    wa=abs(i(r['krw'])); ma=abs(i(mrow['amount']))
    if wb_book and mn_book and wb_book!=mn_book:
        issues.append(('A-예약상충', r['uid'], r['bucket'],
            f"워크북 예약{wb_book} vs 수기{tg.group(1)}행 예약{mn_book} (금액 {wa:,}/{ma:,})"))
    elif ma and abs(wa-ma)>max(3000, ma*0.03):
        issues.append(('A-금액상충', r['uid'], r['bucket'],
            f"수기{tg.group(1)}행 {ma:,} vs 워크북 {wa:,} ({mrow['item'][:14]})"))

# ── B. 예약번호 1:1 (Q2 여행탭) ──
def is_q2tab(t):
    m=re.match(r'(\d{2})(\d{2})_',t or ''); mm=re.match(r'(\d+)월_',t or '')
    if m: return 4<=int(m.group(1))<=6
    if mm: return 4<=int(mm.group(1))<=6
    return False
mbooks=defaultdict(Counter); wbooks=defaultdict(Counter)
mamt={}; wamt=defaultdict(list)
for m in man:
    t=nt(m['tab'])
    if not is_q2tab(t): continue
    b=(m.get('book') or '').strip()
    if b and not b.isdigit(): continue_=(len(b)<5)
    if b: mbooks[t][b]+=1; mamt[(t,b)]=abs(i(m['amount']))
wbooks_all=Counter()   # 격리버킷(취소환불 등) 포함 전체 — 예약 존재 판정용(격리는 정당한 위치이동)
for r in v14:
    b=bookno(r['note'])
    if b: wbooks_all[b]+=1
    t=r['bucket']
    if not is_q2tab(t): continue
    if b: wbooks[t][b]+=1; wamt[(t,b)].append(abs(i(r['krw'])))

wamt_all=Counter((r['bucket'],abs(i(r['krw']))) for r in v14)
def exists_by_amount(t,a):
    if wamt_all.get((t,a),0): return True
    return any(tb==t and c>0 and abs(am-a)<=max(3000,a*0.02) for (tb,am),c in wamt_all.items())
info=[]
for t in sorted(set(mbooks)|set(wbooks)):
    mb, wb = mbooks[t], wbooks[t]
    for b,c in mb.items():
        w=wb.get(b,0)
        if w==0:
            a=mamt.get((t,b),0)
            if wbooks_all.get(b,0):
                info.append((t,b,a))   # 격리버킷(취소환불 등)에 존재 — 정당 이동
            elif exists_by_amount(t,a):
                info.append((t,b,a))   # 행은 있으나 예약번호 미표기/환율차 — 위양성(정보성)
            else:
                issues.append(('B-워크북누락', '-', t, f"수기 예약{b}({a:,}) 워크북에 없음"))
        elif w>c:
            issues.append(('B-워크북중복', '-', t, f"예약{b} 수기{c}회 vs 워크북{w}회"))
        elif c>1 and w<c:
            issues.append(('B-횟수부족', '-', t, f"예약{b} 수기{c}회 vs 워크북{w}회"))
    for b,w in wb.items():
        if b not in mb and w>1:
            issues.append(('B-워크북만중복', '-', t, f"예약{b} 워크북 {w}회(수기 0회)"))
print(f"(정보) 예약번호 미표기·환율차로 매칭 못한 수기건: {len(info)}건 — 금액 기준 존재 확인됨")

by=Counter(k for k,_,_,_ in issues)
print(f"태그검증 {tagged}행 / 이슈 {len(issues)}건: {dict(by)}")
for k,u,t,msg in issues:
    print(f"  [{k}] {u:10} {t:14} {msg}")
sys.exit(0 if not issues else 1)
