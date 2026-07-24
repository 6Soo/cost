# -*- coding: utf-8 -*-
"""장부 열 재구조 v6 (사용자 확정 설계, 2026-07-22):
  근본 원인: 수입(내용 F:H, 금액 I)과 지출(내용 F:G, 증빙 H, 금액 I)의 열 어긋남.
  새 구조: ★H=금액(수입·지출 통일) ★I=증빙유형(카드번호 병기: 국민_8835) ★K=예약번호 신설.
  효과: 3열 병합 소멸 + H폭 확대로 합계 수식 ### 해소 → 합계줄 병합 83개도 전부 해제.
입력: 아슬란_무병합.xlsx(v5) → 출력: 아슬란_무병합_v6.xlsx
규칙(행 단위):
  - 지출행(H값+I금액): H⇄I 셀 통째 스왑(값·서식·테두리) 후 I에 카드번호 병기
  - 수입행(H빈칸+I금액): H←I, I←공백화, F(내용박스) 우측 테두리 복원
  - 합계줄 병합(D:J/D:I 우측수식): 해제 → 수식을 H로(폭 14.5라 ### 없음)
  - 수식 참조: 이동 좌표 재작성 + I열 전용 범위(Ix:Iy)→H 재작성
검증: 이동 전후 금액 보존 assert, 병합 잔존=비표준 시트만, 참조 재작성 로그."""
import openpyxl, re, csv
from openpyxl.styles import Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter, column_index_from_string as cix
from copy import copy
from collections import defaultdict

SRC='아슬란_무병합.xlsx'; OUT='아슬란_무병합_v6.xlsx'
SKIP={'메일수집','프리랜서 지급대장','행사경비총괄표','0823_화순','매출자료 개선판'}

# ── 카드번호 병기 준비: (카드사, 금액) → card4 (v14, 유일할 때만) ──
CO={'KBD':'국민','KBO':'국민','HAN':'하나','CORP':'기업'}
v14=list(csv.DictReader(open('classified_v14.csv')))
by_amt=defaultdict(set)
for r in v14:
    co=CO.get(r['src']); c4=re.sub(r'\.0$','',r['card4'] or '')
    try: amt=abs(int(round(float(r['krw'] or 0))))
    except: amt=0
    if co and c4 and amt: by_amt[(co,amt)].add(c4)
C4CO={}
for r in v14:
    co=CO.get(r['src']); c4=re.sub(r'\.0$','',r['card4'] or '')
    if co and c4: C4CO.setdefault(c4,set()).add(co)
def annotate(evi, amount):
    s=str(evi).strip()
    sd=re.sub(r'\.0$','',s)
    if sd.isdigit() and len(sd)>=4:                     # 끝4자리 표기 관행
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
def cell_blank(c):
    c.value=None; c.number_format='General'
    c.border=Border(); c.fill=copy(BLANKFILL); c.alignment=Alignment()

wb=openpyxl.load_workbook(SRC, rich_text=True)
from openpyxl.styles import PatternFill
BLANKFILL=PatternFill()

moves={}; movelog=[]; amount_check=[]

def isnumlike(v):
    return (isinstance(v,(int,float)) and not isinstance(v,bool)) or \
           (isinstance(v,str) and v.startswith('='))

for name in wb.sheetnames:
    if name in SKIP: continue
    ws=wb[name]
    # 1) 합계줄 병합 해제 → 수식 H로
    for m in list(ws.merged_cells.ranges):
        r=m.min_row; c1,c2=m.min_col,m.max_col
        tl=ws.cell(r,c1)
        val=tl.value; nf=tl.number_format; fnt=copy(tl.font); al=copy(tl.alignment)
        ws.unmerge_cells(str(m))
        tl.value=None
        h=ws.cell(r,8)
        h.value=val; h.number_format=nf; h.font=fnt
        h.alignment=Alignment(horizontal='right', vertical=al.vertical)
        moves[(name,f'{get_column_letter(c1)}{r}')]=f'H{r}'
        movelog.append((name,f'{get_column_letter(c1)}{r}',f'H{r}',str(val)[:24]))
    # 2) 행 단위 H/I 재배치
    for r in range(1, ws.max_row+1):
        H=ws.cell(r,8); I=ws.cell(r,9)
        hv, iv = H.value, I.value
        h_has = hv is not None and str(hv)!=''
        i_has = iv is not None and str(iv)!=''
        if not i_has: continue
        hdr = (str(iv).strip()=='금액(원)')
        if not (isnumlike(iv) or hdr): continue
        pre_amt = iv if isnumlike(iv) else None
        pH, pI = cell_pack(H), cell_pack(I)
        if h_has:      # 지출행/지출헤더: 스왑
            cell_put(H, pI); cell_put(I, pH)
            if isnumlike(pre_amt) or hdr:
                if str(pH['v']).strip()=='증빙유형':
                    # K 헤더 신설(증빙유형 헤더 스타일 복제)
                    K=ws.cell(r,11)
                    cell_put(K, pH); K.value='예약번호'
                elif not str(pH['v']).startswith('='):
                    I.value=annotate(pH['v'], pre_amt if isinstance(pre_amt,(int,float)) else 0)
        else:          # 수입행: 금액만 H로, I 공백화, 내용박스 우측 테두리 복원
            cell_put(H, pI)
            cell_blank(I)
            F=ws.cell(r,6)
            fb=F.border
            if not (fb.right and fb.right.style):
                hr=pH['b'].right if (pH['b'].right and pH['b'].right.style) else pI['b'].left
                F.border=Border(left=copy(fb.left), right=copy(hr) if hr else Side(style='thin'),
                                top=copy(fb.top), bottom=copy(fb.bottom))
        if isnumlike(pre_amt) and not str(pre_amt).startswith('='):
            amount_check.append((name,r,pre_amt,ws.cell(r,8).value))
        moves[(name,f'I{r}')]=f'H{r}'
        # K 예약번호 정규화(기존 값 float→정수문자열)
        K=ws.cell(r,11)
        if isinstance(K.value,float) and K.value==int(K.value):
            K.value=str(int(K.value))
    # 3) 열폭: H=구I(넓음), I=10.5, K=14
    dims=ws.column_dimensions
    wI=dims['I'].width if dims.get('I') else 14.5
    from openpyxl.worksheet.dimensions import ColumnDimension
    for L,wd in (('H',wI),('I',10.5),('K',14.0)):
        old=dims.get(L)
        dims[L]=ColumnDimension(ws, index=L, width=wd, customWidth=True,
                                hidden=bool(old.hidden) if old else False)

# ── 금액 보존 assert ──
for name,r,pre,post in amount_check:
    assert pre==post, f'금액 소실 {name} 행{r}: {pre} vs {post}'

# ── 수식 참조 재작성: 이동 좌표 + I열 전용 범위 ──
rw=0
restruct=set(wb.sheetnames)-SKIP
for name in wb.sheetnames:
    ws=wb[name]
    for row in ws.iter_rows():
        for c in row:
            if not (isinstance(c.value,str) and c.value.startswith('=')): continue
            f=c.value; orig=f
            # I열 범위(Ix:Iy, Ix:Jy) → Hx:Hy  (재구조 시트 내부/참조)
            def rngsub(mm):
                a,b,d,e=mm.group(1),mm.group(2),mm.group(3),mm.group(4)
                if a=='I' and d in ('I','J'): return f'H{b}:H{e}'
                return mm.group(0)
            if name in restruct:
                f=re.sub(r'(?<![A-Z0-9_$:])\$?([A-Z])\$?(\d+):\$?([A-Z])\$?(\d+)', rngsub, f)
            for (sn,old),new in moves.items():
                cp=re.match(r"[A-Z]+",old).end()
                pat=r'\$?'+old[:cp]+r'\$?'+old[cp:]+r'(?![0-9])'
                if sn==name:
                    f=re.sub(r'(?<![A-Z0-9_$:])'+pat, new, f)
                f=re.sub(r"('"+re.escape(sn)+r"'!|"+re.escape(sn)+r"!)"+pat, r"\g<1>"+new, f)
            if f!=orig: c.value=f; rw+=1

# 잔존 I열 참조 감사(재구조 시트)
res=0
for name in restruct:
    ws=wb[name]
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value,str) and c.value.startswith('=') and re.search(r'(?<![A-Z$:])I\d+',c.value.replace('$','')):
                print(f'⚠ I참조 잔존: {name}!{c.coordinate} {c.value[:60]}'); res+=1

tot=sum(len(wb[n].merged_cells.ranges) for n in wb.sheetnames)
wb.save(OUT)
print(f'저장 {OUT} | 병합 잔존 {tot}(비표준 시트만), 이동 {len(moves)}건, 금액검증 {len(amount_check)}행 통과, 참조 재작성 {rw}, I참조 잔존 {res}')
for mv in movelog[:8]: print('  합계이동:',mv)
