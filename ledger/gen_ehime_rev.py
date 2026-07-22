# -*- coding: utf-8 -*-
"""매출자료 양식_rev 구조로 0404_에히메 탭 데모 작성 (사용자 지시 2026-07-22):
  수입: B거래일자 C이름 D닉네임 E예약금 F잔금 G추가금 H금액(원)=SUM(E:G)
  지출: B거래일자 C항목 D내용 E기간 F예약번호 G증빙유형 H금액(원)
  규칙4: OTA 확인 항공/숙박/렌터카 → 내용='항공/숙박/렌트'(+인명 등 부가토큰 유지), 기간='0405_0406'
  수입 병합규칙(보수적): 같은 이름이 정확히 {예약금1+잔금1}일 때만 1행 병합, 그 외 기록대로 개별 행.
  '전액'은 잔금 열(완납), 닉네임은 비움(현 이름 필드에 닉네임 혼재 — 분리 판단은 대표님)."""
import openpyxl, re
from openpyxl.styles import Border, Side, Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BLUE=PatternFill('solid', fgColor='DEEAF6'); PEACH=PatternFill('solid', fgColor='FBE4D5')
YELL=PatternFill('solid', fgColor='FFFF00')
THIN=Border(*[Side(style='thin')]*4)
MED=Border(*[Side(style='medium')]*4)
F=lambda **k: Font(name='Malgun Gothic', **k)

# ── 수입(최신 수기, 25행 원기재) ──
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
# 병합: 이름별 {예약금1,잔금1}만
from collections import defaultdict, Counter
groups=defaultdict(list)
for row in INC: groups[row[1]].append(row)
inc_rows=[]  # (거래일자, 이름, 예약금, 잔금, 추가금)
done=set()
for d,nm,kind,amt in INC:
    if nm in done: continue
    g=groups[nm]; kinds=Counter(k for _,_,k,_ in g)
    if kinds=={'예약금':1,'잔금':1}:
        dep=next(x for x in g if x[2]=='예약금'); bal=next(x for x in g if x[2]=='잔금')
        inc_rows.append((dep[0],nm,dep[3],bal[3],None)); done.add(nm)
    else:
        for d2,_,k2,a2 in g:
            if k2=='예약금': inc_rows.append((d2,nm,a2,None,None))
            elif k2=='잔금': inc_rows.append((d2,nm,None,a2,None))
            else: inc_rows.append((d2,nm,None,a2,None))   # 전액→잔금 열(완납)
        done.add(nm)

# ── 지출: v65 워크북 에히메 시트에서 변환 ──
def split_content(s):
    s=str(s)
    m=re.match(r'^(숙박|항공|렌터카|렌트|료칸)(?:_(.*))?$', s)
    cat_map={'렌터카':'렌트','료칸':'숙박'}
    if not m:
        if s in ('항공료',): return '항공',''
        if s in ('숙박비',): return '숙박',''
        return s,''
    cat=cat_map.get(m.group(1), m.group(1)); rest=m.group(2) or ''
    pm=re.match(r'^(\d{4}(?:_\d{4})?)(?:_(.*))?$', rest)
    if pm:
        period=pm.group(1); extra=pm.group(2)
        return (cat+('_'+extra if extra else '')), period
    return (cat+('_'+rest if rest else '')), ''

src=openpyxl.load_workbook('숲길여행_2분기_비용분류_AI_v65.xlsx')
sv=src['0404_에히메']
exp_rows=[]
for r in range(2,200):
    d=sv.cell(r,2).value; item=sv.cell(r,3).value; cont=sv.cell(r,4).value
    amt=sv.cell(r,5).value; evi=sv.cell(r,6).value; book=sv.cell(r,7).value
    if d=='합계' or (item is None and cont is None and amt is None): break
    content,period=split_content(cont)
    exp_rows.append((d or '', str(item or '').strip(), content, period, str(book or ''), evi or '', amt))

# ── 시트 생성 ──
wb=openpyxl.Workbook(); ws=wb.active; ws.title='0404_에히메'
for L,w in (('A',3),('B',12),('C',20),('D',24),('E',13),('F',17),('G',12),('H',13)):
    ws.column_dimensions[L].width=w

ws['B2']='㈜숲길여행'; ws['B2'].font=F(sz=12,b=True); ws['B2'].border=MED
c=ws['C2']; c.value='2026년 4월 매출 확인자료_에히메_0404_0407'; c.font=F(sz=14,b=True)
ws['D4']='작성일자 :'; ws['D4'].font=F(sz=12,b=True)
ws['E4']='26.07.22'; ws['E4'].font=F(sz=12,b=True)
ws['G4']='담당자 :'; ws['G4'].font=F(sz=12,b=True)
ws['H4']='김주형'; ws['H4'].font=F(sz=11,b=True)

r=6
ws.cell(r,2,'수입 내용').font=F(sz=12,b=True)
for cc in range(2,9): ws.cell(r,cc).fill=BLUE; ws.cell(r,cc).border=MED
r+=1
for cc,h in zip(range(2,9),['거래일자','이름','닉네임','예약금','잔금','추가금','금액(원)']):
    x=ws.cell(r,cc,h); x.fill=BLUE; x.font=F(sz=11,b=True); x.border=THIN
    x.alignment=Alignment(horizontal='center')
inc_start=r+1
for row in inc_rows:
    r+=1
    d,nm,dep,bal,ext=row
    vals=[d,nm,None,dep,bal,ext,f'=SUM(E{r}:G{r})']
    for cc,v in zip(range(2,9),vals):
        x=ws.cell(r,cc,v); x.fill=BLUE; x.border=THIN; x.font=F(sz=11,b=True)
        if cc in (5,6,7,8): x.number_format='#,##0'; x.alignment=Alignment(horizontal='right')
        else: x.alignment=Alignment(horizontal='center')
inc_end=r
r+=1
ws.cell(r,2,'총 금액 (A)').font=F(sz=11,b=True)
ws.cell(r,2).fill=YELL; ws.cell(r,2).border=MED
tA=ws.cell(r,8,f'=SUM(H{inc_start}:H{inc_end})'); tA.font=F(sz=11,b=True); tA.number_format='#,##0'
tA.border=MED; rowA=r

r+=2
ws.cell(r,2,'지출 내용').font=F(sz=12,b=True)
for cc in range(2,9): ws.cell(r,cc).fill=PEACH; ws.cell(r,cc).border=MED
r+=1
for cc,h in zip(range(2,9),['거래일자','항목','내용','기간','예약번호','증빙유형','금액(원)']):
    x=ws.cell(r,cc,h); x.fill=PEACH; x.font=F(sz=11,b=True); x.border=THIN
    x.alignment=Alignment(horizontal='center')
exp_start=r+1
for row in exp_rows:
    r+=1
    for cc,v in zip(range(2,9),row):
        x=ws.cell(r,cc,v if v!='' else None); x.fill=PEACH; x.border=THIN; x.font=F(sz=11)
        if cc==8: x.number_format='#,##0'; x.alignment=Alignment(horizontal='right')
        elif cc==3: x.alignment=Alignment(horizontal='left')
        else: x.alignment=Alignment(horizontal='center')
exp_end=r
r+=1
ws.cell(r,2,'총 금액 (B)').font=F(sz=11,b=True)
ws.cell(r,2).fill=YELL; ws.cell(r,2).border=MED
tB=ws.cell(r,8,f'=SUM(H{exp_start}:H{exp_end})'); tB.font=F(sz=11,b=True); tB.number_format='#,##0'
tB.border=MED; rowB=r
r+=1
ws.cell(r,2,'(A)-(B) 회사수익인식').font=F(sz=11,b=True)
ws.cell(r,2).fill=YELL; ws.cell(r,2).border=MED
tC=ws.cell(r,8,f'=H{rowA}-H{rowB}'); tC.font=F(sz=11,b=True); tC.number_format='#,##0'; tC.border=MED
r+=1
ws.cell(r,3,'A와 B 합계 잘 확인하기 !!').font=F(sz=11,b=True,color='FF0000')

assert not ws.merged_cells.ranges
wb.save('0404_에히메_rev.xlsx')
print(f'저장: 수입 {len(inc_rows)}행(원기재 {len(INC)}행 중 예약금+잔금 쌍 병합), 지출 {len(exp_rows)}행, 병합 0')
