# -*- coding: utf-8 -*-
"""전 시트 무병합 전환 v4 — '매출자료 양식' 픽셀0 기법 + I:J 열재배분(J숨김) + 값보존 원칙.
핵심:
  · I:J 병합 보유 시트(재배분 시트): J열 숨김, I폭=I+J 합산 → 우측정렬 숫자가 값 이동 없이
    원본과 동일 우측 경계에 렌더. 수식·SUM범위 무손상.
  · 열 dim 전면 단일열 재작성(그룹 dim이 새 폭을 덮는 함정 제거).
  · J에서 끝나는 병합의 우측 테두리는 I와 J 양쪽에 부여(cC 런은 마지막 셀 테두리로 그림).
  · 중앙정렬 병합(값 있음, 텍스트/숫자/날짜 모두)=centerContinuous — 렌더 x좌표 병합과 동일.
  · ★값보존 원칙(v4): 넓은(3열+) 우측정렬 수식 병합(합계·잔금 줄, 시트당 2~3개)은 병합 유지.
    이유: (a)숫자는 overflow 불가라 좁은 끝 칸에서 ### (b)값 이동+참조 재작성은 원본의 병합 잔재
    수식('=I42-D96'이 병합 하부 빈 I42를 참조)의 표시값을 바꿔버림(황금해안 0→170,000 실측).
    회계 장부에서 값 변조는 금지 — 합계줄은 붙여넣기 대상도 아니므로 병합 유지가 정답.
  · 좌측정렬 날짜 병합(작성일자 G4:H4, yyyy-mm-dd)=표시문자열로 변환(overflow 활용).
  · 재배분 시트 J열 독립 텍스트(J4 '김주형')는 I셀에 리치텍스트로 연결(각자 폰트 유지, 원위치 렌더).
  · 재배분 시트 비병합 행의 J 우측 테두리는 I로 이관(J 숨김으로 소실 방지).
  · 원본 리치텍스트 보존(rich_text=True — '총 금액 (B)' 빨간 런 등 232런)."""
import openpyxl, re, sys
from openpyxl.styles import Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.dimensions import ColumnDimension
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from copy import copy

SRC='ledger_current.xlsx'; OUT='아슬란_무병합.xlsx'

wb=openpyxl.load_workbook(SRC, rich_text=True)

# 특례: 제목이 병합폭을 크게 초과해 cC 전환 시 자간이 어긋나는 병합은 유지
KEEP_SPECIAL={('행사경비총괄표','C1:F1')}

# ── 0) 재배분 대상: I:J 병합 보유 시트 ──
redis=set()
for name in wb.sheetnames:
    if any(m.min_col==9 and m.max_col==10 for m in wb[name].merged_cells.ranges):
        redis.add(name)

# ── 1) 열 dim 해석(그룹 확장) 후 단일열 재작성 ──
def rewrite_dims(ws, is_redis):
    resolved={}
    for cd in list(ws.column_dimensions.values()):
        for i in range(cd.min, cd.max+1):
            resolved[i]=dict(width=cd.width, hidden=cd.hidden,
                             customWidth=cd.customWidth, bestFit=cd.bestFit)
    if is_redis:
        wI=resolved.get(9,{}).get('width') or 13.0
        wJ=resolved.get(10,{}).get('width') or 6.5
        resolved[9]=dict(width=wI+wJ, hidden=False, customWidth=True, bestFit=False)
        resolved[10]=dict(width=wJ, hidden=True, customWidth=True, bestFit=False)
    for k in list(ws.column_dimensions.keys()):
        del ws.column_dimensions[k]
    for i,attrs in sorted(resolved.items()):
        L=get_column_letter(i)
        cd=ColumnDimension(ws, index=L, width=attrs['width'] or 8.43,
                           customWidth=bool(attrs['customWidth'] or attrs['width']),
                           hidden=bool(attrs['hidden']), bestFit=bool(attrs['bestFit']))
        ws.column_dimensions[L]=cd

kept=[]   # 유지한 병합 (합계줄 수식 + 특례)

for name in wb.sheetnames:
    ws=wb[name]
    is_redis=name in redis
    ms=list(ws.merged_cells.ranges)
    rewrite_dims(ws, is_redis)
    if not ms: continue
    for m in ms:
        assert m.min_row==m.max_row, f'세로 병합 발견 {name} {m}'
        r=m.min_row; c1,c2=m.min_col,m.max_col
        tl=ws.cell(r,c1)
        b=copy(tl.border); fill=copy(tl.fill); al=tl.alignment
        val=tl.value; nf=tl.number_format; fnt=copy(tl.font)
        has_val = val is not None and str(val)!=''
        isnum=isinstance(val,(int,float)) and not isinstance(val,bool)
        isdate=hasattr(val,'year')
        isform=isinstance(val,str) and val.startswith('=')
        right_like = has_val and ((al and al.horizontal=='right')
                     or ((isnum or isdate or isform) and (al is None or al.horizontal in (None,'general'))))
        # ★유지 대상: 3열+ 우측정렬 값/수식 병합(합계·잔금 줄) 및 특례
        if (right_like and c2-c1>1) or (name,str(m)) in KEEP_SPECIAL:
            kept.append((name,str(m)))
            continue
        # 병합범위 테두리는 가장자리 셀에 저장됨: 우측=끝셀(c2), 상하=각 셀(없으면 tl 폴백)
        er=ws.cell(r,c2).border.right
        right_src = copy(er) if (er and er.style) else copy(b.right)
        pre_tb=[]
        for c in range(c1,c2+1):
            cb=ws.cell(r,c).border
            top = copy(cb.top) if (cb.top and cb.top.style) else copy(b.top)
            bot = copy(cb.bottom) if (cb.bottom and cb.bottom.style) else copy(b.bottom)
            pre_tb.append((top,bot))
        ws.unmerge_cells(str(m))
        # 우측 테두리 부여 열: J(10)에서 끝나고 J가 숨김이면 I(9)와 J 모두
        rb_col = 9 if (is_redis and c2==10 and c1<=9) else c2
        for i,c in enumerate(range(c1,c2+1)):
            cell=ws.cell(r,c)
            cell.fill=copy(fill)
            left  = b.left  if c==c1 else Side(style=None)
            right = right_src if (c==rb_col or (c==c2 and rb_col!=c2)) else Side(style=None)
            cell.border=Border(left=left,right=right,top=pre_tb[i][0],bottom=pre_tb[i][1])
        use_cc = has_val and al and al.horizontal in ('center','centerContinuous')
        if use_cc:
            cc=Alignment(horizontal='centerContinuous',vertical=al.vertical,
                         wrap_text=al.wrap_text,indent=al.indent)
            for c in range(c1,c2+1): ws.cell(r,c).alignment=cc
        elif has_val and al and al.horizontal=='left' and (isnum or isdate):
            # 좌측정렬 숫자/날짜: overflow 불가 → 표시문자열 변환
            if isdate and nf=='yyyy-mm-dd':
                tl.value=f'{val:%Y-%m-%d}'
            elif isnum:
                tl.value=str(int(val)) if float(val)==int(val) else str(val)
            tl.number_format='General'

    if is_redis:
        merged_j_rows=set()
        for m in ws.merged_cells.ranges:
            if m.min_col<=10<=m.max_col:
                for rr in range(m.min_row,m.max_row+1): merged_j_rows.add(rr)
        # J열 독립 텍스트(J4 김주형) → I셀 리치텍스트 연결(원본에서 라벨 끝에 맞닿아 렌더)
        def infont(f):
            return InlineFont(rFont=f.name, sz=f.sz, b=f.b, i=f.i, color=copy(f.color))
        def blocks(v,f):
            if isinstance(v,CellRichText): return list(v)
            return [TextBlock(infont(f), str(v))]
        for c in list(ws['J']):
            if c.row in merged_j_rows or c.value in (None,''): continue
            if isinstance(c.value,str) and c.value.startswith('='): continue
            icell=ws.cell(c.row,9)
            if isinstance(icell.value,(str,CellRichText)) and isinstance(c.value,(str,CellRichText)):
                icell.value=CellRichText(*(blocks(icell.value,icell.font)+blocks(c.value,c.font)))
                c.value=None
            else:
                k=ws.cell(c.row,11)
                if k.value in (None,''):
                    k.value=c.value; k.font=copy(c.font); k.alignment=copy(c.alignment)
                    k.number_format=c.number_format; c.value=None
        # 비병합 행의 J 우측 테두리 → I로 이관(J 숨김으로 소실 방지)
        for c in list(ws['J']):
            if c.row in merged_j_rows: continue
            jr=c.border.right
            if jr and jr.style:
                ic=ws.cell(c.row,9)
                ib=ic.border
                if not (ib.right and ib.right.style):
                    ic.border=Border(left=copy(ib.left), right=copy(jr),
                                     top=copy(ib.top), bottom=copy(ib.bottom))

tot=sum(len(wb[n].merged_cells.ranges) for n in wb.sheetnames)
assert tot==len(kept), f'병합 수 불일치: 잔존 {tot} vs 유지 목록 {len(kept)}'
wb.save(OUT)
print(f'저장 완료 | 재배분시트 {len(redis)}개, 유지 병합 {len(kept)}개(합계줄 수식+특례), 그 외 전부 무병합')
for k in kept[:10]: print('  유지:',k)
print('  ...' if len(kept)>10 else '')
