# -*- coding: utf-8 -*-
"""최신 수기장부 기준 매칭 재생성 → matched_fresh.json (빌더의 완전기입/미입력 색칠 근거).
구 matched_uids.json(v10 시절 스냅샷 고정)을 대체 — P8(최신본) 정신을 매칭에도 적용."""
import csv, re, json
from collections import Counter
def i(x):
    try: return int(round(float(str(x).replace(',','') or 0)))
    except: return 0
def bookno(t):
    m=re.search(r'예약\s*(\d{6,19}|[A-Z0-9]{5,7})(?![0-9])', t or '')
    return m.group(1) if m else ''
TABMAP={'0630_오제_A':'0630_오제','0704_야마가타':'0704_아키타'}
man=list(csv.DictReader(open('data/manual_v4.csv',encoding='utf-8')))
books=set((m.get('book') or '').strip() for m in man if (m.get('book') or '').strip())
slots=Counter((TABMAP.get(m['tab'],m['tab']), abs(i(m['amount']))) for m in man if i(m['amount']))
con=Counter(slots)
rows=list(csv.DictReader(open('data/classified_v14.csv',encoding='utf-8')))
out={}
for r in sorted(rows,key=lambda z:(z['bucket'],z['use_date'])):
    uid=r['uid']; n=r['note'] or ''
    if str(r.get('cancel')).lower() in ('true','1') or i(r['krw'])<0:
        out[uid]='cancel'; continue
    if re.search(r'⇄수기|수기기타|^수기\d+행|수기병합', n): out[uid]='matched'; continue
    bk=bookno(n)
    if bk and bk in books: out[uid]='matched'; continue
    k=(r['bucket'], abs(i(r['krw'])))
    if con.get(k,0)>0: con[k]-=1; out[uid]='matched'; continue
    hit=None
    for (tb,am),c in con.items():
        if c>0 and tb==r['bucket'] and abs(am-abs(i(r['krw'])))<=max(3000,abs(i(r['krw']))*0.02):
            hit=(tb,am); break
    if hit: con[hit]-=1; out[uid]='matched'; continue
    out[uid]='unmatched'
json.dump(out, open('data/matched_fresh.json','w',encoding='utf-8'), ensure_ascii=False)
from collections import Counter as C
print('matched_fresh:', dict(C(out.values())))
