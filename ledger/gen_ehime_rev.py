# -*- coding: utf-8 -*-
"""에히메 rev 데모 v3 — 서식 무접촉 원칙:
  Drive에서 받은 실물 장부(ledger_latest.xlsx)의 '매출자료 양식_rev' 시트를 통째로 복제하고
  셀 '값'만 주입한다(폰트·배경·테두리·병합·열폭·행높이 일절 손대지 않음 → 파괴 불가능).
  · '전액' 입금 → 추가금(G) 열 (사용자 확정 2026-07-22)
  · 닉네임 분리(세글자 성씨이름 외 전부 닉네임), 증빙 현금·영수증→현지통화
  · B열은 템플릿이 날짜 셀(yyyy-mm-dd) — 실제 date 값으로 기입
  · H(금액원)=SUM(E:G) 행수식 주입(값 수준), 합계 수식 C42/C96/C98은 템플릿 내장분 그대로"""
import openpyxl, re, datetime
from collections import defaultdict, Counter

SUR=set('김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하곽성차주우구민류나진지엄채원천방공현함변염여추도소석선설마길연위표명기반라왕금옥육인맹제모탁국어은편용예경봉사부엽')
def hangul(t): return bool(t) and all('가'<=ch<='힣' for ch in t)
def is_name(t): return len(t)==3 and hangul(t) and t[0] in SUR
def split_name(s):
    s=s.strip(); toks=s.split()
    if len(toks)>1:
        names=[t for t in toks if is_name(t)]
        if names: return names[0], ' '.join(t for t in toks if t!=names[0])
        return '', s
    t=s
    if is_name(t): return t, ''
    if hangul(t) and len(t)>3:
        if is_name(t[-3:]): return t[-3:], t[:-3]
        if is_name(t[:3]):  return t[:3],  t[3:]
    return '', t

def d(s):
    m=re.match(r'^(\d\d)\.(\d\d)\.(\d\d)$', s)
    return datetime.date(2000+int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None

INC=[('25.11.22','엽정숙','예약금',380000),('26.03.21','엽정숙','예약금',500000),
     ('25.12.28','클로버박정숙','예약금',380000),('26.03.24','클로버박정숙','잔금',200000),
     ('25.11.22','오종구','예약금',380000),('25.11.22','이종미','예약금',380000),
     ('25.11.22','채인숙','예약금',380000),('25.11.23','윤혜기','예약금',380000),
     ('25.12.20','고운길','예약금',380000),('26.03.31','고운길','잔금',200000),
     ('26.02.20','똘똘이아이비','전액',1160000),('25.11.22','김애식 느티','예약금',380000),
     ('25.11.24','정연숙','예약금',380000),('26.03.22','느티채헤','예약금',380000),
     ('26.03.21','느티8정숙50','잔금',1100000),('25.11.23','김정화','예약금',380000),
     ('25.11.23','고팡 김원복','예약금',380000),('25.11.23','김정화','예약금',380000),
     ('26.03.21','김원복','잔금',1000000),('25.11.22','김효정','예약금',380000),
     ('26.03.21','김효정','잔금',500000)]
parsed=[(x[0],)+split_name(x[1])+(x[2],x[3]) for x in INC]
groups=defaultdict(list)
for row in parsed: groups[row[1] or row[2]].append(row)
# 1인 1행: 예약금/잔금/추가금 열별로 값 수집 — 다건이면 '=a+b' 수식(사용자 지시: 계산값 말고 수식으로)
def cellv(amts):
    if not amts: return None
    if len(amts)==1: return amts[0]
    return '='+'+'.join(str(a) for a in amts)
inc_rows=[]; done=set()
for row in parsed:
    key=row[1] or row[2]
    if key in done: continue
    g=groups[key]
    dep=[x[4] for x in g if x[3]=='예약금']
    bal=[x[4] for x in g if x[3]=='잔금']
    ext=[x[4] for x in g if x[3] not in ('예약금','잔금')]   # 전액→추가금(G)
    first=min(g, key=lambda x: x[0])
    nm=next((x[1] for x in g if x[1]),'')
    nk=next((x[2] for x in g if x[2]),'')
    inc_rows.append((first[0], nm or None, nk or None, cellv(dep), cellv(bal), cellv(ext)))
    done.add(key)

def split_content(s):
    s=str(s); cat_map={'렌터카':'렌트','료칸':'숙박'}
    m=re.match(r'^(숙박|항공|렌터카|렌트|료칸)(?:_(.*))?$', s)
    if not m:
        return ('항공','') if s=='항공료' else (('숙박','') if s=='숙박비' else (s,''))
    cat=cat_map.get(m.group(1), m.group(1)); rest=m.group(2) or ''
    pm=re.match(r'^(\d{4}(?:_\d{4})?)(?:_(.*))?$', rest)
    if pm: return (cat+('_'+pm.group(2) if pm.group(2) else '')), pm.group(1)
    return (cat+('_'+rest if rest else '')), ''

import json
LEDGER_EVID={int(k):v for k,v in json.load(open('/tmp/ehime_evid.json')).items()}
CASHLIKE={'현금/기타','현금','영수증','현지통화'}
src=openpyxl.load_workbook('숲길여행_2분기_비용분류_AI_v68.xlsx')
sv=src['0404_에히메']
exp_rows=[]
for r in range(2,200):
    dt=sv.cell(r,2).value; item=sv.cell(r,3).value; cont=sv.cell(r,4).value
    amt=sv.cell(r,5).value; evi=sv.cell(r,6).value; book=sv.cell(r,7).value
    if dt=='합계' or (item is None and cont is None and amt is None): break
    content,period=split_content(cont)
    evi=re.sub(r'_\d{4}$','',str(evi or ''))   # 카드번호 병기 폐기(사용자 2026-07-22): 국민/하나/기업으로 간소화
    if evi in CASHLIKE:
        # 포인트 결제는 수기 원기재의 사이트명(제주항공 등)이 증빙 — 현금성만 '현지통화'
        orig=LEDGER_EVID.get(int(round(amt)) if isinstance(amt,(int,float)) else -1)
        evi = orig if (orig and orig not in CASHLIKE) else '영수증'
    exp_rows.append((d(str(dt or '')), str(item or '').strip(), content, period, str(book or ''), evi, amt))
assert len(inc_rows)<=23 and len(exp_rows)<=50

# ── 실물 템플릿 복제 + 값 주입 ──
wb=openpyxl.load_workbook('ledger_latest.xlsx', rich_text=True)
for n in list(wb.sheetnames):
    if n!='매출자료 양식_rev': del wb[n]
ws=wb['매출자료 양식_rev']; ws.title='0404_에히메'

before={}   # 서식 무접촉 검증용 스냅샷
def snap(cell): return (cell.font.name, cell.font.sz, cell.font.b,
                        cell.fill.patternType, cell.fill.fgColor.rgb if cell.fill.patternType else None)
for rr in range(1,101):
    for cc in range(1,9): before[(rr,cc)]=snap(ws.cell(rr,cc))

ws['C2']='2026년 4월 매출 확인자료_에히메_0404_0407'
ws['E4']='26.07.22'
for i,row in enumerate(inc_rows):
    r=8+i   # 수입 슬롯 8~30
    dt,nm,nk,dep,bal,ext=row
    for cc,v in zip(range(2,9),[d(dt),nm or None,nk or None,dep,bal,ext,f'=SUM(E{r}:G{r})']):
        ws.cell(r,cc).value=v
for i,row in enumerate(exp_rows):
    r=35+i   # 지출 슬롯 35~84
    for cc,v in zip(range(2,9),row):
        if cc==6 and v not in ('',None):
            # 예약번호: 텍스트 서식('@')+문자열 — 구글시트 어포스트로피 이스케이프 방지, 16자리 정밀도 보존
            ws.cell(r,cc).number_format='@'
            ws.cell(r,cc).value=str(v)
        else:
            ws.cell(r,cc).value=(v if v not in ('',None) else None)

after={}
for rr in range(1,101):
    for cc in range(1,9): after[(rr,cc)]=snap(ws.cell(rr,cc))
diff=[k for k in before if before[k]!=after[k]]
assert not diff, f'서식 변경 감지: {diff[:5]}'

wb.save('0404_에히메_rev3.xlsx')
print(f'저장: 수입 {len(inc_rows)}행, 지출 {len(exp_rows)}행 | 서식 변경 0 (스냅샷 대조), 병합 {len(ws.merged_cells.ranges)}개 원본 그대로')
