# -*- coding: utf-8 -*-
"""0404_에히메 rev 데모 v2 (사용자 교정 2026-07-22 반영):
  ①무병합 규칙 폐기 — 대표님이 만든 rev 양식 구조를 병합 포함 그대로 재현:
    제목 C2:H2 / 섹션바 B6:H6·B44:H44 / 합계값 C42:H42·C96:H96·C98:H98 병합, 데이터행 무병합,
    수입 슬롯 8~41행(34), 지출 슬롯 46~95행(50), H4='담당자 : 김주형' 단일 셀.
  ②닉네임 분리: 일반적인 한국 세글자 이름(성씨 시작)을 벗어나는 부분은 전부 닉네임.
    분리된 이름 기준으로 예약금+잔금 쌍 재병합(고팡 김원복 ↔ 김원복 = 동일인).
  ③증빙유형 현금·영수증 → '현지통화' 통일."""
import openpyxl, re
from openpyxl.styles import Border, Side, Alignment, Font, PatternFill

BLUE=PatternFill('solid', fgColor='DEEAF6'); PEACH=PatternFill('solid', fgColor='FBE4D5')
YELL=PatternFill('solid', fgColor='FFFF00')
THIN=Border(*[Side(style='thin')]*4)
MED=Border(*[Side(style='medium')]*4)
F=lambda **k: Font(name='Malgun Gothic', **k)

SUR=set('김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하곽성차주우구민류나진지엄채원천방공현함변염여추도소석선설마길연위표명기반라왕금옥육인맹제모탁국어은편용예경봉사부엽')
def hangul(t): return bool(t) and all('가'<=ch<='힣' for ch in t)
def is_name(t): return len(t)==3 and hangul(t) and t[0] in SUR
def split_name(s):
    s=s.strip()
    toks=s.split()
    if len(toks)>1:
        names=[t for t in toks if is_name(t)]
        if names:
            nick=' '.join(t for t in toks if t!=names[0])
            return names[0], nick
        return '', s
    t=s
    if is_name(t): return t, ''
    if hangul(t) and len(t)>3:
        if is_name(t[-3:]): return t[-3:], t[:-3]     # 클로버박정숙 → 박정숙/클로버
        if is_name(t[:3]):  return t[:3],  t[3:]
    return '', t                                       # 세글자 이름 아님 → 전부 닉네임

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
from collections import defaultdict, Counter
parsed=[(d,)+split_name(nm)+(k,a) for d,nm,k,a in INC]   # (일자, 이름, 닉, 종류, 금액)
groups=defaultdict(list)
for row in parsed:
    key=row[1] if row[1] else row[2]                     # 이름 없으면 닉네임으로 그룹
    groups[key].append(row)
inc_rows=[]; done=set()
for row in parsed:
    key=row[1] if row[1] else row[2]
    if key in done: continue
    g=groups[key]; kinds=Counter(x[3] for x in g)
    if kinds=={'예약금':1,'잔금':1}:
        dep=next(x for x in g if x[3]=='예약금'); bal=next(x for x in g if x[3]=='잔금')
        nick=dep[2] or bal[2]
        inc_rows.append((dep[0], dep[1] or bal[1], nick, dep[4], bal[4], None))
    else:
        for d2,nm2,nk2,k2,a2 in g:
            if k2=='예약금': inc_rows.append((d2,nm2,nk2,a2,None,None))
            else:            inc_rows.append((d2,nm2,nk2,None,a2,None))   # 잔금·전액→잔금 열
    done.add(key)

def split_content(s):
    s=str(s)
    cat_map={'렌터카':'렌트','료칸':'숙박'}
    m=re.match(r'^(숙박|항공|렌터카|렌트|료칸)(?:_(.*))?$', s)
    if not m:
        return ('항공','') if s=='항공료' else (('숙박','') if s=='숙박비' else (s,''))
    cat=cat_map.get(m.group(1), m.group(1)); rest=m.group(2) or ''
    pm=re.match(r'^(\d{4}(?:_\d{4})?)(?:_(.*))?$', rest)
    if pm:
        return (cat+('_'+pm.group(2) if pm.group(2) else '')), pm.group(1)
    return (cat+('_'+rest if rest else '')), ''

src=openpyxl.load_workbook('숲길여행_2분기_비용분류_AI_v66.xlsx')
sv=src['0404_에히메']
exp_rows=[]
for r in range(2,200):
    d=sv.cell(r,2).value; item=sv.cell(r,3).value; cont=sv.cell(r,4).value
    amt=sv.cell(r,5).value; evi=sv.cell(r,6).value; book=sv.cell(r,7).value
    if d=='합계' or (item is None and cont is None and amt is None): break
    content,period=split_content(cont)
    evi=str(evi or '')
    if evi in ('현금/기타','현금','영수증'): evi='현지통화'
    exp_rows.append((d or '', str(item or '').strip(), content, period, str(book or ''), evi, amt))
assert len(exp_rows)<=50, '지출 슬롯(50행) 초과'

# ── rev 템플릿 구조 그대로 생성 ──
wb=openpyxl.Workbook(); ws=wb.active; ws.title='0404_에히메'
for L,w in (('A',3),('B',12),('C',13),('D',22),('E',12),('F',17),('G',12),('H',13)):
    ws.column_dimensions[L].width=w

ws['B2']='㈜숲길여행'; ws['B2'].font=F(sz=12,b=True); ws['B2'].border=MED
ws['C2']='2026년 4월 매출 확인자료_에히메_0404_0407'
ws['C2'].font=F(sz=14,b=True); ws['C2'].alignment=Alignment(horizontal='center')
for cc in range(3,9): ws.cell(2,cc).border=MED
ws.merge_cells('C2:H2')
ws['D4']='작성일자 :'; ws['D4'].font=F(sz=12,b=True)
ws['E4']='26.07.22'; ws['E4'].font=F(sz=12,b=True)
ws['H4']='담당자 : 김주형'; ws['H4'].font=F(sz=11,b=True)

ws['B6']='수입 내용'; ws['B6'].font=F(sz=12,b=True)
for cc in range(2,9): ws.cell(6,cc).fill=BLUE; ws.cell(6,cc).border=MED
ws.merge_cells('B6:H6')
for cc,h in zip(range(2,9),['거래일자','이름','닉네임','예약금','잔금','추가금','금액(원)']):
    x=ws.cell(7,cc,h); x.fill=BLUE; x.font=F(sz=11,b=True); x.border=THIN
    x.alignment=Alignment(horizontal='center')
for i in range(34):                       # 슬롯 8~41
    r=8+i
    row=inc_rows[i] if i<len(inc_rows) else None
    vals=(row[0],row[1],row[2],row[3],row[4],row[5],f'=SUM(E{r}:G{r})') if row else (None,)*6+(None,)
    for cc,v in zip(range(2,9),vals):
        x=ws.cell(r,cc,v); x.fill=BLUE; x.border=THIN; x.font=F(sz=11,b=True)
        if cc in (5,6,7,8): x.number_format='#,##0'; x.alignment=Alignment(horizontal='right')
        else: x.alignment=Alignment(horizontal='center')
ws['B42']='총 금액 (A)'; ws['B42'].font=F(sz=11,b=True); ws['B42'].fill=YELL; ws['B42'].border=MED
ws['C42']='=SUM(H8:H41)'; ws['C42'].font=F(sz=11,b=True); ws['C42'].number_format='#,##0'
ws['C42'].alignment=Alignment(horizontal='right')
for cc in range(3,9): ws.cell(42,cc).border=MED
ws.merge_cells('C42:H42')

ws['B44']='지출 내용'; ws['B44'].font=F(sz=12,b=True)
for cc in range(2,9): ws.cell(44,cc).fill=PEACH; ws.cell(44,cc).border=MED
ws.merge_cells('B44:H44')
for cc,h in zip(range(2,9),['거래일자','항목','내용','기간','예약번호','증빙유형','금액(원)']):
    x=ws.cell(45,cc,h); x.fill=PEACH; x.font=F(sz=11,b=True); x.border=THIN
    x.alignment=Alignment(horizontal='center')
for i in range(50):                       # 슬롯 46~95
    r=46+i
    row=exp_rows[i] if i<len(exp_rows) else ('',)*6+(None,)
    for cc,v in zip(range(2,9),row):
        x=ws.cell(r,cc,v if v!='' else None); x.fill=PEACH; x.border=THIN; x.font=F(sz=11)
        if cc==8: x.number_format='#,##0'; x.alignment=Alignment(horizontal='right')
        elif cc==3: x.alignment=Alignment(horizontal='left')
        else: x.alignment=Alignment(horizontal='center')
ws['B96']='총 금액 (B)'; ws['B96'].font=F(sz=11,b=True); ws['B96'].fill=YELL; ws['B96'].border=MED
ws['C96']='=SUM(H46:H95)'; ws['C96'].font=F(sz=11,b=True); ws['C96'].number_format='#,##0'
ws['C96'].alignment=Alignment(horizontal='right')
for cc in range(3,9): ws.cell(96,cc).border=MED
ws.merge_cells('C96:H96')
ws['B98']='(A)-(B) 회사수익인식'; ws['B98'].font=F(sz=11,b=True); ws['B98'].fill=YELL; ws['B98'].border=MED
ws['C98']='=C42-C96'; ws['C98'].font=F(sz=11,b=True); ws['C98'].number_format='#,##0'
ws['C98'].alignment=Alignment(horizontal='right')
for cc in range(3,9): ws.cell(98,cc).border=MED
ws.merge_cells('C98:H98')
ws['C100']='A와 B 합계 잘 확인하기 !!'; ws['C100'].font=F(sz=11,b=True,color='FF0000')

wb.save('0404_에히메_rev2.xlsx')
nick_demo=[(r[1],r[2]) for r in inc_rows if r[2]]
print(f'저장: 수입 {len(inc_rows)}행, 지출 {len(exp_rows)}행, 병합 {len(ws.merged_cells.ranges)}개(rev 양식 그대로)')
print('닉네임 분리:', nick_demo)
