# -*- coding: utf-8 -*-
"""4월분 매출확인자료 일괄 생성 (매출자료 양식_rev 구조, 사용자 지시 2026-07-22):
  · 템플릿(Drive 실물 '매출자료 양식_rev')을 셀 단위 복제 — 서식은 전부 템플릿 것.
  · 슬롯 초과 탭(교토·아오모리·알펜루트)은 슬롯 행 스타일을 복제해 확장,
    합계 수식(SUM 범위)·병합·이하 행 위치를 새 좌표로 재구성.
  · 수입: 이름/닉네임 분리(세글자 성씨이름 규칙), 1인 1행, 다건 입금은 '=a+b' 수식,
    예약금*→예약금 / 잔금·잔액→잔금 / 전액·추가→추가금 / 환불→추가금(음수).
  · 지출: v68 워크북 데이터, 내용/기간 분리(항공·숙박·렌트), 증빙 간소화(국민/하나/기업/영수증),
    포인트·이체 등 수기 원기재 존중, 예약번호 텍스트('@')."""
import openpyxl, re, json, datetime
from copy import copy
from collections import defaultdict, Counter

APRIL=['0501_부산','5월_유럽','0613_북해도','0616_레분토&리시리','0620_묘코','0625_아키타','0630_오제']
TPL='매출자료 양식_rev'
OUT='매출확인자료_5-6월_rev_v2.xlsx'

SUR=set('김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하곽성차주우구민류나진지엄채원천방공현함변염여추도소석선설마길연위표명기반라왕금옥육인맹제모탁국어은편용예경봉사부엽')
def hangul(t): return bool(t) and all('가'<=ch<='힣' for ch in t)
def is_name(t): return len(t)==3 and hangul(t) and t[0] in SUR
def split_name(s):
    s=s.strip()
    # ①명시적 별칭 '실명(별칭)' 우선 추출(5·6월 형식)
    nick=''
    m=re.search(r'\(([^)]+)\)', s)
    if m:
        nick=m.group(1).strip()
        s=re.sub(r'\s*\([^)]*\)\s*',' ',s).strip()
    s=re.sub(r'\s+',' ',s).strip(' ,'); s=re.sub(r'\s*,\s*',', ',s)
    if nick: return s, nick               # 별칭 있으면 나머지 전부 이름
    if ',' in s or '외' in s: return s, '' # 콤마 다수명·'외 N' 그룹 → 이름 그대로
    # ②비괄호 단일/공백 → 기존 April 휴리스틱(성씨 규칙)
    toks=s.split()
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

def pdate(s):
    s=str(s).split('~')[0].strip()
    m=re.match(r'^(\d\d)\.(\d\d)\.(\d\d)$', s)
    return datetime.date(2000+int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None

def kindof(ds):
    if ds.startswith('예약금') or '예약' in ds: return 'dep'
    if ds.startswith(('잔금','잔액')): return 'bal'
    if ds.startswith(('전액','추가')): return 'ext'
    if '환불' in ds: return 'ext'
    return 'ext'

def sumexpr(amts):
    if len(amts)==1: return amts[0]
    s=''.join(('+' if v>=0 else '-')+str(abs(v)) for v in amts)
    return '='+s.lstrip('+')

def build_income(rows):
    parsed=[]
    for d,nm,ds,amt in rows:
        n,k=split_name(nm)
        parsed.append((d,n,k,kindof(ds),amt))
    groups=defaultdict(list)
    for row in parsed: groups[row[1] or row[2]].append(row)
    out=[]; done=set()
    for row in parsed:
        key=row[1] or row[2]
        if key in done: continue
        g=groups[key]
        dep=[x[4] for x in g if x[3]=='dep']
        bal=[x[4] for x in g if x[3]=='bal']
        ext=[x[4] for x in g if x[3]=='ext']
        first=min(g, key=lambda x: x[0] or '99')
        nm=next((x[1] for x in g if x[1]),'')
        nk=next((x[2] for x in g if x[2]),'')
        out.append((first[0], nm or None, nk or None,
                    sumexpr(dep) if dep else None, sumexpr(bal) if bal else None,
                    sumexpr(ext) if ext else None))
        done.add(key)
    return out

def split_content(s):
    s=str(s); cat_map={'렌터카':'렌트','료칸':'숙박'}
    m=re.match(r'^(숙박|항공|렌터카|렌트|료칸)(?:_(.*))?$', s)
    if not m:
        return ('항공','') if s=='항공료' else (('숙박','') if s=='숙박비' else (s,''))
    cat=cat_map.get(m.group(1), m.group(1)); rest=m.group(2) or ''
    pm=re.match(r'^(\d{4}(?:_\d{4})?)(?:_(.*))?$', rest)
    if pm: return (cat+('_'+pm.group(2) if pm.group(2) else '')), pm.group(1)
    return (cat+('_'+rest if rest else '')), ''

CASHLIKE={'현금/기타','현금','영수증','현지통화'}
EVID=json.load(open('/tmp/mayjun_evid.json'))
def evid_of(tab, evi, amt):
    e=re.sub(r'_\d{4}$','',str(evi or ''))
    if re.match(r'^\d+(\.0)?$', e):
        e={'8835':'국민','8895':'국민','4886':'국민','3820':'국민','4595':'하나','3923':'하나','0906':'하나','5483':'하나','4971':'기업','4985':'기업','8972':'기업'}.get(re.sub(r'\.0$','',e)[-4:], e)
    if e in CASHLIKE:
        orig=EVID.get(tab,{}).get(str(int(round(amt))) if isinstance(amt,(int,float)) else '')
        e = orig if (orig and orig not in CASHLIKE) else '영수증'
    return e

# ── 데이터 적재 ──
inc_all=json.load(open('/tmp/mayjun_inc.json'))
wb68=openpyxl.load_workbook('숲길여행_2분기_비용분류_AI_v73.xlsx')
def load_exp(tab):
    sv=wb68[tab]; out=[]
    for r in range(2,400):
        dt=sv.cell(r,2).value; item=sv.cell(r,3).value; cont=sv.cell(r,4).value
        amt=sv.cell(r,5).value; evi=sv.cell(r,6).value; book=sv.cell(r,7).value
        if dt=='합계': break
        if isinstance(dt,str) and dt.startswith('▼'): continue   # 워크북 구분줄(병합/미입력 안내) — 장부엔 미포함
        if item is None and cont is None and amt is None: continue
        content,period=split_content(cont)
        out.append((pdate(dt), str(item or '').strip(), content, period,
                    str(book or ''), evid_of(tab, evi, amt), amt))
    return out

# ── 템플릿 로드 및 시트 생성 ──
src=openpyxl.load_workbook('ledger_latest.xlsx', rich_text=True)
tpl=src[TPL]
led=openpyxl.load_workbook('ledger_latest.xlsx', data_only=True)   # 제목·총A 캐시 참조

INC_S,INC_E,TOTA,BAR,HDR,EXP_S,EXP_E,TOTB,PROFIT,NOTE=8,30,31,33,34,35,84,85,87,89
out=openpyxl.Workbook(); out.remove(out.active)

def copy_cell(tc, oc, keep_value=True):
    if keep_value and not isinstance(tc, openpyxl.cell.cell.MergedCell):
        oc.value=tc.value
    oc.font=copy(tc.font); oc.fill=copy(tc.fill); oc.border=copy(tc.border)
    oc.alignment=copy(tc.alignment); oc.number_format=tc.number_format

def build_tab(tab):
    inc=build_income(inc_all.get(tab,[]))
    exp=load_exp(tab)
    # 여백 슬롯 삭제(사용자 지시 2026-07-22): 데이터 행수만큼만 — 공란 색칠행 금지.
    # 0행(오사카 수입 미기재)도 1행은 유지(SUM 범위 성립 + 미기재임이 눈에 보이도록).
    si=max(1, len(inc))
    se=max(1, len(exp))
    ws=out.create_sheet(tab)
    # 행 매핑 구성: (출력행, 템플릿행, 값복사여부)
    rmap=[]
    for r in range(1, INC_S): rmap.append((r, r, True))
    for j in range(si):
        t = INC_E if j==si-1 else (INC_S+j if j < (INC_E-INC_S) else INC_S+1)
        rmap.append((INC_S+j, t, False))
    ta=INC_S+si
    rmap.append((ta, TOTA, True))
    rmap.append((ta+1, TOTA+1, True))
    bar=ta+2; rmap.append((bar, BAR, True))
    hdr=ta+3; rmap.append((hdr, HDR, True))
    es=hdr+1
    for j in range(se):
        t = EXP_E if j==se-1 else (EXP_S+j if j < (EXP_E-EXP_S) else EXP_S+1)
        rmap.append((es+j, t, False))
    tb=es+se
    for off,t in enumerate(range(TOTB, tpl.max_row+1)):
        rmap.append((tb+off, t, True))
    tp=tb+(PROFIT-TOTB)
    note=tb+(NOTE-TOTB)
    # 셀 복사
    for orow, trow, keepv in rmap:
        for c in range(1, 10):
            copy_cell(tpl.cell(trow,c), ws.cell(orow,c), keepv)
        h=tpl.row_dimensions[trow].height if tpl.row_dimensions.get(trow) else None
        if h: ws.row_dimensions[orow].height=h
    for L,dim in tpl.column_dimensions.items():
        nd=ws.column_dimensions[L]
        nd.width=dim.width; nd.hidden=dim.hidden
    # 병합(새 좌표)
    for mr in (f'C2:H2', f'B6:H6', f'B{bar}:H{bar}', f'C{ta}:H{ta}', f'C{tb}:H{tb}', f'C{tp}:H{tp}'):
        ws.merge_cells(mr)
    # 합계 수식
    ws.cell(ta,3).value=f'=SUM(H{INC_S}:H{ta-1})'
    ws.cell(tb,3).value=f'=SUM(H{es}:H{tb-1})'
    ws.cell(tp,3).value=f'=C{ta}-C{tb}'
    # 제목·작성일자(원 탭 제목 재사용)
    lw=led[tab]
    title=None
    for c in range(2,10):
        v=lw.cell(2,c).value
        if isinstance(v,str) and '확인자료' in v: title=v; break
    ws.cell(2,3).value = title or f'2026년 4월 매출 확인자료_{tab}'
    ws.cell(4,5).value='26.07.22'
    # 데이터 주입
    for j,row in enumerate(inc):
        r=INC_S+j
        dt,nm,nk,dep,bal,ext=row
        for cc,v in zip(range(2,9),[pdate(dt),nm,nk,dep,bal,ext,f'=SUM(E{r}:G{r})']):
            ws.cell(r,cc).value=v
    for j,row in enumerate(exp):
        r=es+j
        for cc,v in zip(range(2,9),row):
            if cc==6 and v not in ('',None):
                ws.cell(r,cc).number_format='@'
                ws.cell(r,cc).value=str(v)
            else:
                ws.cell(r,cc).value=(v if v not in ('',None) else None)
    return len(inc), len(exp), ta, tb, tp

report=[]
for tab in APRIL:
    ni,ne,ta,tb,tp=build_tab(tab)
    report.append((tab,ni,ne,ta,tb))
    print(f'{tab}: 수입 {ni}행, 지출 {ne}행 (총A r{ta}, 총B r{tb})')
out.save(OUT)
print('저장:', OUT)
