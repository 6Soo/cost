# -*- coding: utf-8 -*-
"""전 시트 무병합 전환 v5 — centerContinuous 전면 폐기(호환성) + 열 재배분 확장.
★v4→v5 전환 사유(사용자 실측 지적): LibreOffice는 '선택영역 가운데 맞춤(cC)'을 지원하지
  않아 파일을 열 때 cC 런을 **진짜 병합으로 변환**한다(왕복 저장 실측 5,722개 병합 생성).
  파일 자체는 무병합이어도 사용자 앱에서 병합이 부활 → cC 사용 금지.
핵심:
  · 표준(B:C 계열) 시트: C·E·G열 숨김+좌측열 폭 합산(B=B+C, D=D+E, F=F+G),
    I:J 보유 시트는 J도 숨김(I=I+J). → 2열 병합(거래일자·항목·내용·금액)은 값 이동 없이
    plain center/left/right로 원본과 동일 위치 렌더. cC 불필요.
  · 3열+(F:H, 제목 D2:J2 등) 중앙정렬 값: 병합 중심에 가장 가까운 가시 열로 배치(plain center).
    F:H는 wH/2(≈4열폭)만큼 중심이 좌측 — 유일한 근사 지점(보고 대상).
  · 넓은(3열+) 우측정렬 수식 병합(합계·잔금)·비표준 시트(프리랜서·행사경비) 병합은 유지
    (값·수식 보존 원칙, 붙여넣기 대상 아님).
  · 예외 시트(0823_화순·매출자료 개선판): C/E/G에 실데이터 → 숨김 없이 단순 무병합
    (값 있는 병합이 거의 없어 시각 영향 미미).
  · 좌측정렬 숫자/날짜 병합은 표시문자열 변환, 앵커가 숨김열이면 첫 가시열로 이동.
  · J4 '김주형'은 I라벨에 리치텍스트 연결. 양식계열 E4 '작성일자 :' 라벨은 D4 우측정렬+후행공백.
  · 이동 셀은 전 워크북 수식 참조 재작성 + 범위 감사. 원본 리치텍스트 보존(rich_text=True)."""
import openpyxl, re, sys
from openpyxl.styles import Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.dimensions import ColumnDimension
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from copy import copy

SRC='ledger_current.xlsx'; OUT='아슬란_무병합.xlsx'
wb=openpyxl.load_workbook(SRC, rich_text=True)

EXC_HIDE={'0823_화순','매출자료 개선판'}          # C/E/G 실데이터 → 숨김 제외
KEEP_SHEET={'프리랜서 지급대장','행사경비총괄표'}   # 비표준 요약 시트 → 병합 전체 유지
PAD_SPACES=6   # E4 라벨 후행공백(렌더 캘리브레이션 대상)

fam=set(); redis=set()
for name in wb.sheetnames:
    ms=wb[name].merged_cells.ranges
    if any(m.min_col==2 and m.max_col==3 for m in ms): fam.add(name)
    if any(m.min_col==9 and m.max_col==10 for m in ms): redis.add(name)

def hidden_cols(name):
    if name in KEEP_SHEET or name not in fam or name in EXC_HIDE: return set()
    h={3,5,7}
    if name in redis: h.add(10)
    return h

# ── 열 dim 해석(그룹 확장) → 재배분 → 단일열 재작성. 반환: 가시폭 맵(숨김=0) ──
def rewrite_dims(ws, hides):
    resolved={}
    for cd in list(ws.column_dimensions.values()):
        for i in range(cd.min, cd.max+1):
            resolved[i]=dict(width=cd.width, hidden=cd.hidden,
                             customWidth=cd.customWidth, bestFit=cd.bestFit)
    for h in sorted(hides):
        wh=resolved.get(h,{}).get('width') or 8.43
        left=h-1
        wl=resolved.get(left,{}).get('width') or 8.43
        resolved[left]=dict(width=wl+wh, hidden=False, customWidth=True, bestFit=False)
        resolved[h]=dict(width=wh, hidden=True, customWidth=True, bestFit=False)
    for k in list(ws.column_dimensions.keys()):
        del ws.column_dimensions[k]
    for i,attrs in sorted(resolved.items()):
        L=get_column_letter(i)
        cd=ColumnDimension(ws, index=L, width=attrs['width'] or 8.43,
                           customWidth=bool(attrs['customWidth'] or attrs['width']),
                           hidden=bool(attrs['hidden']), bestFit=bool(attrs['bestFit']))
        ws.column_dimensions[L]=cd
    return {i:(0.0 if resolved[i].get('hidden') else (resolved[i].get('width') or 8.43))
            for i in resolved}

kept=[]; moves={}; movelog=[]

def infont(f):
    return InlineFont(rFont=f.name, sz=f.sz, b=f.b, i=f.i, color=copy(f.color))
def blocks(v,f):
    if isinstance(v,CellRichText): return list(v)
    return [TextBlock(infont(f), str(v))]
SPACE_U=0.79   # 공백 1자의 열폭 단위 근사(캘리브레이션 대상)

for name in wb.sheetnames:
    ws=wb[name]
    hides=hidden_cols(name)
    ms=list(ws.merged_cells.ranges)
    vis = rewrite_dims(ws, hides)
    def w(c): return 0.0 if c in hides else vis.get(c, 8.43)
    if not ms: continue
    if name in KEEP_SHEET:
        for m in ms: kept.append((name,str(m)))
        continue
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
        hz = al.horizontal if al else None
        right_like = has_val and (hz=='right' or ((isnum or isdate or isform) and hz in (None,'general')))
        if right_like and c2-c1>1:
            kept.append((name,str(m)))     # 합계·잔금 줄 수식 병합 유지(값 보존)
            continue
        # 테두리 소스 캡처(가장자리 셀) 후 해제
        er=ws.cell(r,c2).border.right
        right_src = copy(er) if (er and er.style) else copy(b.right)
        pre_tb=[]
        for c in range(c1,c2+1):
            cb=ws.cell(r,c).border
            top = copy(cb.top) if (cb.top and cb.top.style) else copy(b.top)
            bot = copy(cb.bottom) if (cb.bottom and cb.bottom.style) else copy(b.bottom)
            pre_tb.append((top,bot))
        ws.unmerge_cells(str(m))
        vis_cols=[c for c in range(c1,c2+1) if c not in hides]
        rb_col = vis_cols[-1] if vis_cols else c2   # 우측 테두리 = 스팬 내 마지막 가시열
        for i,c in enumerate(range(c1,c2+1)):
            cell=ws.cell(r,c)
            cell.fill=copy(fill)
            left  = b.left  if c==c1 else Side(style=None)
            right = right_src if (c==rb_col or c==c2) else Side(style=None)
            cell.border=Border(left=left,right=right,top=pre_tb[i][0],bottom=pre_tb[i][1])
        if not has_val: continue
        # ── 값 배치 ──
        tgt=c1; new_al=copy(al)
        if hz in ('center','centerContinuous'):
            x=0.0; xs={}
            for c in range(c1,c2+1):
                xs[c]=(x, x+w(c)); x+=w(c)
            ctr=x/2.0
            tgt=min(vis_cols, key=lambda c: abs((xs[c][0]+xs[c][1])/2.0-ctr))
            # 4열 이상 비데이터 텍스트(제목·안내문)는 공백 패딩으로 중심 잔차 보정
            delta=ctr-(xs[tgt][0]+xs[tgt][1])/2.0   # +: 우측 보정 필요
            if c2-c1>=3 and isinstance(val,str) and not isform and abs(delta)>0.8:
                k=round(2*abs(delta)/SPACE_U)
                val=(' '*k+val) if delta>0 else (val+' '*k)
            new_al=Alignment(horizontal='center',vertical=al.vertical,
                             wrap_text=al.wrap_text,indent=al.indent)
        elif hz=='left' and (isnum or isdate):
            # overflow 불가 → 표시문자열 변환
            if isdate and nf=='yyyy-mm-dd': val=f'{val:%Y-%m-%d}'
            elif isnum: val=str(int(val)) if float(val)==int(val) else str(val)
            nf='General'
            if c1 in hides: tgt=vis_cols[0]
        else:
            if c1 in hides: tgt=vis_cols[0]
        # 앵커가 숨김열인 좌측 텍스트(작성일자 날짜 등): 좌측 가시 이웃 라벨에 리치텍스트 연결
        #   (숨김열 폭이 좌측 열에 흡수돼 vis_cols[0]의 시작점이 원위치보다 밀리는 문제 해결)
        if c1 in hides and hz in (None,'general','left') and isinstance(val,str):
            lv=[c for c in range(c1-1,0,-1) if c not in hides][0]
            lc=ws.cell(r,lv)
            if isinstance(lc.value,(str,CellRichText)) and str(lc.value)!='':
                gap=' '*2
                lc.value=CellRichText(*(blocks(lc.value,lc.font)+[TextBlock(infont(fnt), gap+val)]))
                ws.cell(r,c1).value=None
                movelog.append((name,f'{get_column_letter(c1)}{r}',f'{get_column_letter(lv)}{r}(연결)',str(val)[:20]))
                continue
        if tgt!=c1:
            ws.cell(r,c1).value=None
            dst=ws.cell(r,tgt)
            dst.value=val; dst.number_format=nf; dst.font=fnt; dst.alignment=new_al
            moves[(name,f'{get_column_letter(c1)}{r}')]=f'{get_column_letter(tgt)}{r}'
            movelog.append((name,f'{get_column_letter(c1)}{r}',f'{get_column_letter(tgt)}{r}',str(val)[:20]))
        else:
            tl.value=val; tl.number_format=nf; tl.alignment=new_al

    # ── 숨김열 독립값·테두리 구조 ──
    if hides:
        merged_rows={h:set() for h in hides}
        for m in ws.merged_cells.ranges:
            for h in hides:
                if m.min_col<=h<=m.max_col:
                    for rr in range(m.min_row,m.max_row+1): merged_rows[h].add(rr)
        def infont(f):
            return InlineFont(rFont=f.name, sz=f.sz, b=f.b, i=f.i, color=copy(f.color))
        def blocks(v,f):
            if isinstance(v,CellRichText): return list(v)
            return [TextBlock(infont(f), str(v))]
        for h in sorted(hides):
            L=get_column_letter(h)
            for c in list(ws[L]):
                if c.row in merged_rows[h]: continue
                jr=c.border.right
                if jr and jr.style:
                    ic=ws.cell(c.row,h-1)
                    ib=ic.border
                    if not (ib.right and ib.right.style):
                        ic.border=Border(left=copy(ib.left), right=copy(jr),
                                         top=copy(ib.top), bottom=copy(ib.bottom))
                if c.value in (None,'') or (isinstance(c.value,str) and c.value.startswith('=')):
                    continue
                icell=ws.cell(c.row,h-1)
                if h==10 and isinstance(icell.value,(str,CellRichText)) and isinstance(c.value,(str,CellRichText)):
                    # J4 김주형: I라벨 끝에 맞닿아 렌더 → 리치텍스트 연결
                    icell.value=CellRichText(*(blocks(icell.value,icell.font)+blocks(c.value,c.font)))
                    c.value=None
                elif h==5 and isinstance(c.value,str) and '작성일자' in c.value and icell.value in (None,''):
                    # 양식계열 E4 라벨 → D4 우측정렬+후행공백(원위치 근사)
                    icell.value=c.value+' '*PAD_SPACES
                    icell.font=copy(c.font)
                    icell.alignment=Alignment(horizontal='right')
                    c.value=None
                    movelog.append((name,f'{L}{c.row}',f'{get_column_letter(h-1)}{c.row}','작성일자 라벨'))
                else:
                    print(f'⚠ 숨김열 독립값 미처리: {name}!{L}{c.row} = {repr(c.value)[:30]}')

# ── 수식 참조 재작성(경계 안전 치환) + 범위 감사 ──
rw=0
for name in wb.sheetnames:
    ws=wb[name]
    for row in ws.iter_rows():
        for c in row:
            if not (isinstance(c.value,str) and c.value.startswith('=')): continue
            f=c.value; orig=f
            for (sn,old),new in moves.items():
                cp=re.match(r"[A-Z]+",old).end()
                pat=r'\$?'+old[:cp]+r'\$?'+old[cp:]+r'(?![0-9])'
                if sn==name:
                    f=re.sub(r'(?<![A-Z0-9_$:])'+pat, new, f)
                f=re.sub(r"('"+re.escape(sn)+r"'!|"+re.escape(sn)+r"!)"+pat, r"\g<1>"+new, f)
            if f!=orig: c.value=f; rw+=1
from openpyxl.utils import column_index_from_string as cix
def in_rng(coord,rng):
    mm=re.match(r'\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)$',rng)
    if not mm: return False
    c=re.match(r'([A-Z]+)(\d+)',coord); cc,cr=cix(c.group(1)),int(c.group(2))
    a,b2,d,e=cix(mm.group(1)),int(mm.group(2)),cix(mm.group(3)),int(mm.group(4))
    return min(a,d)<=cc<=max(a,d) and min(b2,e)<=cr<=max(b2,e)
warn=0
for name in wb.sheetnames:
    ws=wb[name]
    for row in ws.iter_rows():
        for c in row:
            if not (isinstance(c.value,str) and c.value.startswith('=')): continue
            for rng in re.findall(r'\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+', c.value):
                for (sn,old),new in moves.items():
                    if sn==name and in_rng(old,rng)!=in_rng(new,rng):
                        print(f'⚠ 범위감사: {name}!{c.coordinate} {c.value[:50]} 범위 {rng} 이동 {old}→{new}')
                        warn+=1

tot=sum(len(wb[n].merged_cells.ranges) for n in wb.sheetnames)
assert tot==len(kept), f'병합 수 불일치: 잔존 {tot} vs 유지 {len(kept)}'
wb.save(OUT)
print(f'저장 | 표준시트 {len(fam)-len(EXC_HIDE)}개 C/E/G숨김(+J {len(redis)}개), 유지 병합 {len(kept)}, 값 이동 {len(moves)}건, 참조 재작성 {rw}, 범위경고 {warn}')
for mv in movelog[:12]: print('  이동:',mv)
