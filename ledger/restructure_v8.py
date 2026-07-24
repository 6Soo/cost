# -*- coding: utf-8 -*-
"""장부 열 재구조 v8 — 스페이서 열 완전 삭제(사용자 지시: "C/G를 왜 hidden으로? 이름이 C로 가야지").
숨김 열은 '원본과 똑같이 보이기' 시절의 잔재 — 구조를 새로 설계한 이상 유지 이유 없음.
최종 배치(연속, 숨김 0): A여백 | B거래일자 | C이름(수입)/항목(지출) | D내용 | E금액 | F증빙유형 | G예약번호
파이프라인(v5 산출물에서 한 번에):
  ① 표준 시트: H/I 스왑(지출)·H←I(수입)·합계병합 해제→H·예약번호 K→J·카드번호 병기 (v7 로직)
  ② 빈 스페이서 열 C(3)·E(5)·G(7)·K(11) 실제 삭제 → 데이터가 B·C·D·E·F·G로 연속 정렬
  ③ 수식 열문자 일괄 재매핑(D→C, F→D, H→E, I→F, J→G — 단일 패스 콜백으로 이중치환 방지)
예외(원형 보존·보고): 메일수집(빈), 프리랜서 지급대장·행사경비총괄표(비표준 요약),
  0823_화순·매출자료 개선판(자체 열 배치: C거래일자·E항목·F~H 예약금/잔금 — v7에서 이들을
  표준으로 오인해 스왑했다가 =sum(F8:H8)이 자기참조 순환이 되는 버그 발생 → v8에서 제외로 교정).
검증: 금액(E) 총합 == v5 금액(I) 총합, LO 왕복 병합 수, 잔금 8건 계산값, I참조 잔존 0."""
import openpyxl, re, csv
from openpyxl.styles import Border, Side, Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.dimensions import ColumnDimension
from copy import copy
from collections import defaultdict

SRC='아슬란_무병합.xlsx'; OUT='아슬란_무병합_v8.xlsx'
SKIP={'메일수집','프리랜서 지급대장','행사경비총괄표','0823_화순','매출자료 개선판'}

CO={'KBD':'국민','KBO':'국민','HAN':'하나','CORP':'기업'}
v14=list(csv.DictReader(open('classified_v14.csv')))
by_amt=defaultdict(set); C4CO={}
for r in v14:
    co=CO.get(r['src']); c4=re.sub(r'\.0$','',r['card4'] or '')
    try: amt=abs(int(round(float(r['krw'] or 0))))
    except: amt=0
    if co and c4 and amt: by_amt[(co,amt)].add(c4)
    if co and c4: C4CO.setdefault(c4,set()).add(co)
def annotate(evi, amount):
    s=str(evi).strip(); sd=re.sub(r'\.0$','',s)
    if sd.isdigit() and len(sd)>=4:
        cos=C4CO.get(sd[-4:])
        return (f'{sorted(cos)[0]}_{sd[-4:]}' if cos and len(cos)==1 else sd[-4:])
    if s in ('국민','하나','기업') and amount:
        c4s=by_amt.get((s,abs(int(amount))), set())
        if len(c4s)==1: return f'{s}_{next(iter(c4s))}'
    return s

def cell_pack(c):
    return dict(v=c.value, nf=c.number_format, f=copy(c.font), b=copy(c.border),
                fl=copy(c.fill), al=copy(c.alignment))
def cell_put(c, p):
    c.value=p['v']; c.number_format=p['nf']; c.font=p['f']; c.border=p['b']
    c.fill=p['fl']; c.alignment=p['al']
BLANKFILL=PatternFill()
def cell_blank(c):
    c.value=None; c.number_format='General'
    c.border=Border(); c.fill=copy(BLANKFILL); c.alignment=Alignment()

wb=openpyxl.load_workbook(SRC, rich_text=True)
moves={}; amount_check=[]

def isnumlike(v):
    return (isinstance(v,(int,float)) and not isinstance(v,bool)) or \
           (isinstance(v,str) and v.startswith('='))

restruct=[n for n in wb.sheetnames if n not in SKIP]

# ── ① 스왑·합계 해제·예약번호 이관 (구 좌표계에서) ──
for name in restruct:
    ws=wb[name]
    for m in list(ws.merged_cells.ranges):
        r=m.min_row; c1=m.min_col
        tl=ws.cell(r,c1)
        val=tl.value; nf=tl.number_format; fnt=copy(tl.font); al=copy(tl.alignment)
        ws.unmerge_cells(str(m))
        tl.value=None
        h=ws.cell(r,8)
        h.value=val; h.number_format=nf; h.font=fnt
        h.alignment=Alignment(horizontal='right', vertical=al.vertical)
        moves[(name,f'{get_column_letter(c1)}{r}')]=f'H{r}'
    for r in range(1, ws.max_row+1):
        moves.setdefault((name,f'I{r}'), f'H{r}')   # I열 은퇴(값 유무 무관 블랭킷)
    for r in range(1, ws.max_row+1):
        H=ws.cell(r,8); I=ws.cell(r,9)
        hv, iv = H.value, I.value
        h_has = hv is not None and str(hv)!=''
        i_has = iv is not None and str(iv)!=''
        if i_has and (isnumlike(iv) or str(iv).strip()=='금액(원)'):
            hdr = (str(iv).strip()=='금액(원)')
            pre_amt = iv if isnumlike(iv) else None
            pH, pI = cell_pack(H), cell_pack(I)
            if h_has:
                cell_put(H, pI); cell_put(I, pH)
                if str(pH['v']).strip()=='증빙유형':
                    J=ws.cell(r,10)
                    cell_put(J, cell_pack(I)); J.value='예약번호'
                elif (isnumlike(pre_amt) or hdr) and not str(pH['v']).startswith('='):
                    I.value=annotate(pH['v'], pre_amt if isinstance(pre_amt,(int,float)) else 0)
            else:
                cell_put(H, pI); cell_blank(I)
            if isnumlike(pre_amt) and not str(pre_amt).startswith('='):
                amount_check.append((name,r,pre_amt))
        # 예약번호 K→J + leftover 정리 + ID 문자열 고정
        J=ws.cell(r,10); K=ws.cell(r,11)
        if K.value not in (None,''):
            cell_put(J, cell_pack(K)); cell_blank(K)
        if isinstance(J.value,(int,float)) and not isinstance(J.value,bool):
            J.value=str(int(J.value))
        elif J.value in (None,'') and str(ws.cell(r,10).value or '')!='예약번호':
            if J.value in (None,''): cell_blank(J)

# ── 수식 이동좌표 재작성(구 좌표계) ──
for name in wb.sheetnames:
    ws=wb[name]
    for row in ws.iter_rows():
        for c in row:
            if not (isinstance(c.value,str) and c.value.startswith('=')): continue
            f=c.value
            def rngsub(mm):
                a,b,d,e=mm.group(1),mm.group(2),mm.group(3),mm.group(4)
                if a=='I' and d in ('I','J'): return f'H{b}:H{e}'
                return mm.group(0)
            if name in restruct:
                f=re.sub(r'(?<![A-Z0-9_$:])\$?([A-Z])\$?(\d+):\$?([A-Z])\$?(\d+)', rngsub, f)
            for (sn,old),new in moves.items():
                if sn!=name: continue
                cp=re.match(r"[A-Z]+",old).end()
                pat=r'(?<![A-Z0-9_$:])\$?'+old[:cp]+r'\$?'+old[cp:]+r'(?![0-9])'
                f=re.sub(pat, new, f)
            if f!=c.value: c.value=f

# ── ② 스페이서 열 삭제 + 열폭 재구성 ──
NEWW={'A':3.0}
for name in restruct:
    ws=wb[name]
    dims=ws.column_dimensions
    oldw=lambda L,d: (dims[L].width if dims.get(L) and dims[L].width else d)
    widths={'A':oldw('A',3.0), 'B':oldw('B',18.13), 'C':oldw('D',19.0), 'D':oldw('F',19.13),
            'E':oldw('I',14.5), 'F':10.5, 'G':14.0}
    for col in (11,7,5,3):
        ws.delete_cols(col)
    for k in list(dims.keys()):
        del dims[k]
    for L,wd in widths.items():
        dims[L]=ColumnDimension(ws, index=L, width=wd, customWidth=True)

# ── ③ 수식 열문자 재매핑(단일 패스) ──
CMAP={'B':'B','D':'C','F':'D','H':'E','I':'F','J':'G','L':'H','M':'I','N':'J'}
def remap(f):
    def sub(m):
        pre,L,row=m.group(1),m.group(2),m.group(3)
        return pre+'$'*0+CMAP.get(L,L)+row
    return re.sub(r'(^|[^A-Z0-9_$:])\$?([A-Z])\$?(\d+)(?![0-9A-Z])', lambda m:(m.group(1)+CMAP.get(m.group(2),m.group(2))+m.group(3)), f)
rw=0
for name in restruct:
    ws=wb[name]
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value,str) and c.value.startswith('='):
                nf=remap(c.value)
                if nf!=c.value: c.value=nf; rw+=1

tot=sum(len(wb[n].merged_cells.ranges) for n in wb.sheetnames)
wb.save(OUT)
print(f'저장 {OUT} | 병합잔존 {tot}, 스왑금액 {len(amount_check)}행, 열문자 재매핑 {rw}건, 처리 {len(restruct)}시트(예외 {sorted(SKIP)})')
