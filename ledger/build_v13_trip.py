# -*- coding: utf-8 -*-
"""여행(실체) 기준 재구성: 기존 워크북(classified_v12, 카드검증 완료) +
수기장부(여행 마스터) 미포함건을 카드매칭으로 추가 → classified_v13.
금액은 카드 우선(rule A1), 탭·성격은 수기. 비카드는 증빙유형 표기."""
import openpyxl, csv, re
from collections import Counter, defaultdict

def i(x):
    try: return int(round(float(str(x).replace(',','').replace('원','').strip())))
    except: return 0
def load(f):
    wb=openpyxl.load_workbook('newcard/conv/%s.xlsx'%f,read_only=True); ws=wb[wb.sheetnames[0]]
    return [[('' if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]

def d10(s):
    s=str(s).replace('.','-')
    m=re.search(r'(\d{2,4})-(\d{2})-(\d{2})',s)
    if not m: return ''
    y=m.group(1);  y='20'+y if len(y)==2 else y
    return '%s-%s-%s'%(y,m.group(2),m.group(3))

# ---- 통합 카드 인덱스 (정상+취소, 금액→상세) ----
cards=[]
for r in load('E')[1:]:
    if len(r)>16 and i(r[16]):
        cards.append(dict(co='국민',use=d10(r[1]) or d10(r[0]),c4=r[4][-4:],amt=i(r[16]),mer=r[7],fx=r[11],cur=r[10],sub='해외',src='KBO',cx=(r[6]=='취소매출'),appr=''))
for r in load('F')[1:]:
    if len(r)>15 and i(r[11]):
        _m=re.match(r'^\s*(\d+)\((\d+)\)\s*$', str(r[15]).strip())
        _ap,_og=(_m.group(1),_m.group(2)) if _m else (re.sub(r'\D','',r[15]),'')
        cards.append(dict(co='국민',use=d10(r[1]),c4=r[5][-4:],amt=abs(i(r[11])),mer=r[7],fx='',cur='',sub='국내',src='KBD',cx=(i(r[11])<0),appr=_ap,orig=_og))
for f in ('G','H'):
    for r in load(f)[6:]:
        if len(r)>14 and r[0] and r[0]!='NO' and i(r[5]):
            gu='해외' if '해외' in (r[11] or '') else '국내'
            cards.append(dict(co='하나',use=d10(r[1]),c4=r[3][-4:],amt=i(r[14]) or i(r[5]),mer=r[7],fx='',cur='',sub=gu,src='HAN',cx=(i(r[6])!=0),appr=re.sub(r'\D','',r[4])))
for r in load('A_20260720'):
    if len(r)>13 and i(r[6]):
        gu='해외' if r[1].startswith('해외') else '국내'
        cards.append(dict(co='기업',use=str(r[2])[:10],c4=r[3][-4:],amt=i(r[6]),mer=r[5],fx=(r[7] or '').split()[0] if r[7] else '',cur='JPY' if 'JPY' in (r[7] or '') else '',sub=gu,src='CORP',cx=(r[0]=='취소또는할인'),appr=re.sub(r'\D','',r[13])))
byamt=defaultdict(list)
for c in cards: byamt[(c['amt'],c['cx'])].append(c)
amts=sorted(set(a for a,_ in byamt))
_used_card=set()   # 소비형: 한 카드 레코드는 한 수기행에만 배정(같은 승인 재사용·도용 방지)
def card_match(a, co, want_cx=False):
    # ★부호(취소여부) 일치 + 카드사 일치 필수(타사 폴백 금지) + 소비형(1카드=1행).
    cand=byamt.get((a,want_cx),[])
    if not cand:
        lo,hi=a*0.98,a*1.02
        cand=[c for x in amts if lo<=x<=hi for c in byamt.get((x,want_cx),[])]
    pool=[c for c in cand if c['co']==co and id(c) not in _used_card]
    if not pool: return None
    best=min(pool,key=lambda c:abs(c['amt']-a))
    _used_card.add(id(best))
    return best

# ---- 기존 워크북 (classified_v12) ----
FN=['uid','src','use_date','post_date','card4','user','merchant','biz','country','currency','foreign','krw','vat','tax_type','status','biz_no','extra','bucket','account','cancel','cost_type','vat_tag','confidence','note','tax_conf','appr','orig_appr']
cls=list(csv.DictReader(open('data/classified_v12.csv',encoding='utf-8')))
# 내가 v52에서 여행_미배정에 둔 ¥7,439(KBO-9002)는 수기(0417_아오모리)로 통합되므로 base에서 제거
cls=[r for r in cls if r['uid']!='KBO-9002']
# ★base 선소비: base가 이미 대응하는 카드 레코드를 _used_card에 등록(승인번호 우선, 없으면 카드사+금액+부호 첫 건).
#   부산 하나건처럼 base가 이미 ⇄수기 매칭한 거래를 TRIP이 또 추가(appr 도용·이중계상)하는 것 방지.
_co_of={'KBD':'국민','KBO':'국민','HAN':'하나','CORP':'기업'}
_by_appr={}
for c in cards:
    if c.get('appr'): _by_appr.setdefault((c['co'],c['appr']),c)
for _b in cls:
    _co=_co_of.get(_b['src'],'')
    if not _co: continue
    try: _k=int(round(float(str(_b['krw']).replace(',','') or 0)))
    except: _k=0
    if not _k: continue
    _cx=_k<0
    _ap=re.sub(r'\D','',_b.get('appr') or '')
    c=_by_appr.get((_co,_ap)) if _ap else None
    if c is None:
        for cc2 in byamt.get((abs(_k),_cx),[]):
            if cc2['co']==_co and id(cc2) not in _used_card: c=cc2; break
    if c is not None: _used_card.add(id(c))

# base에 이미 담긴 예약참조(숫자+알파PNR) — dedup 안전장치
book_in=set()
for r in cls:
    blob=(r['note'] or '')+' '+(r['appr'] or '')
    for m in re.findall(r'\d{8,}', blob): book_in.add(m)
    for m in re.findall(r'\b[A-Z0-9]{5,7}\b', blob):
        if re.search(r'[A-Z]',m) and re.search(r'[0-9]',m): book_in.add(m)

# ---- 수기장부 ----
man=list(csv.DictReader(open('data/manual_v3.csv',encoding='utf-8')))
# 수기장부 실제 행번호 인덱스(manual_v4.csv=재파싱, row열 보유). 탭명 변형 정규화 후 tab+date+item+금액으로 매칭.
TABMAP={'0630_오제_A':'0630_오제','0704_야마가타':'0704_아키타'}
def normtab(t): return TABMAP.get(t, t)
rowidx={}; bookidx={}
try:
    for r4 in csv.DictReader(open('data/manual_v4.csv',encoding='utf-8')):
        try: a4=round(float(r4['amount']))
        except: continue
        rowidx.setdefault((normtab(r4['tab']), r4['date'], r4['item'], a4), []).append(r4['row'])
        b4=(r4.get('book') or '').strip()
        if b4: bookidx.setdefault((normtab(r4['tab']), b4), []).append(r4['row'])
except FileNotFoundError:
    pass
def manrow(r):
    # ★예약번호 우선(다객실 동일가에서 유일 식별) + 소비형(같은 키 재사용 금지 — 태그 오배정 방지)
    b=(r.get('book') or '').strip()
    if b:
        hit=bookidx.get((normtab(r['tab']), b))
        if hit: return hit.pop(0)
    try: a=round(float(r['amount']))
    except: return ''
    hit=rowidx.get((normtab(r['tab']), r['date'], r['item'], a))
    return hit.pop(0) if hit else ''
def is_q2(tab):
    m=re.match(r'(\d{2})(\d{2})',tab or ''); mm=re.match(r'(\d+)월',tab or '')
    if m: return 4<=int(m.group(1))<=6
    if mm: return 4<=int(mm.group(1))<=6
    return False

def account_of(item,desc):
    s=(desc or '')+' '+(item or '')
    if '항공' in s or '航空' in s: return '항공료'
    if '숙박' in s or '료칸' in s or 'ryokan' in s.lower(): return '숙박비'
    if '렌터카' in s or 'RENT' in s.upper(): return '렌터카'
    if '통행' in s: return '통행료'
    if '교통' in s or 'TRAIN' in s.upper() or 'BUS' in s.upper(): return '교통비'
    if '식' in s or 'FAMILYMART' in s.upper(): return '식비'
    if '입장' in s: return '입장료'
    if '보험' in s or '트래블로버' in s or '트래블로버' in item: return '여행자보험'
    # 브랜드 기반
    if any(k in item for k in ['AGODA','Agoda','아고다','Booking','BOOKING','트립닷컴','Trip.com','Mercure','Hotel','HOTEL','호텔']): return '숙박비'
    if any(k in item for k in ['마이트립','고투게이트','제주항공','대한항공','아시아나','ANA','진에어','스카이티켓','에어']): return '항공료'
    return '숙박비'
def src_of(card,item,acct):
    if card=='하나' or re.match(r'4595|5483|3923|4140|4336',card or ''): return 'HAN','하나'
    if card=='기업' or re.match(r'4971|4985|8972',card or ''): return 'CORP','기업'
    if card=='국민' or re.match(r'8835|3804|3820|4886|8895|0906',card or ''):
        # 국내 PG(원화결제) vs 해외
        if any(k in item for k in ['NICE','마이트립','이니시스','고투게이트','_NICE','제주항공','대한항공','진에어','아시아나','(주)']): return 'KBD','국민'
        return 'KBO','국민'
    return 'MAN', (card or '기타')  # 현금/이체/영수증

CARDSET={'국민','하나','기업'}
def is_card(cd): return cd in CARDSET or bool(re.match(r'\d{4}',cd or ''))

new=[]; n=0; addtot=0; cashtot=0
percard=Counter(); pertab=defaultdict(float)
for r in man:
    if not is_q2(r['tab']): continue
    a=i(r['amount'])
    if a==0: continue
    book=str(r.get('book','')).strip()
    sd=d10(r['date'])   # 수기 결제(승인)일
    # 연도 오기 보정: 미래 날짜(오늘 이후)는 전년도 결제의 오타('26.12.31'→2025-12-31 실카드 확인됨)
    if sd and sd>'2026-07-20':
        sd=str(int(sd[:4])-1)+sd[4:]
    # dedup 안전장치: 예약참조가 base에 이미 있으면 skip
    if book and book in book_in: continue
    # 결제일 규칙(2026-07-22 구조 수정): 카드건은 '수기 기재일'이 아니라 '카드 매칭 실재'로 판정.
    #   base(승인-Q2) 카드는 선소비 잠금으로 여기서 매칭 자체가 불가 → 매칭되면 비-base(Q1 선결제) 실거래.
    #   ★경계 공백 실측(에히메 아고다 2건 332,038): 승인 3/31(Q1)+수기 기재 4/1 → 구가정(기재일<4/1만 추가)에서 누락.
    cm=None
    if is_card(r['card']):
        # ★끝4자리 카드열(8835 등)을 발급사로 변환해 매칭 확장하는 시도는 2026-07-22 기각:
        #   ±2% 퍼지 매칭이 THB 거래(유럽 Adria)·동일금액 APA 4건 중 2건 등 오매칭 양산 실측.
        #   금액 변경 없는 명칭 카드열(국민/하나/기업)만 매칭 — 끝4자리 무일자 건은 수기 그대로 두고 보고.
        cm=card_match(abs(a), {'국민':'국민','하나':'하나','기업':'기업'}.get(r['card'],''), want_cx=(a<0))
        if sd and sd>='2026-04-01':
            # 구제 조건: 매칭 카드가 Q1 승인 + 수기 기재일과 근접(±14일)일 때만(경계 케이스).
            # ★근접 제한 없으면 동액 우연일치 원거리 카드(작년 카카오T 10,500가 커피빈 4/4에 매칭)로
            #   가짜 구제→①B dedup이 진짜 현금건(HIMESO)까지 오인 제거하는 2차 사고 실측(2026-07-22).
            import datetime as _dt
            def _dd(x,y):
                try:
                    return abs((_dt.date.fromisoformat(x)-_dt.date.fromisoformat(y)).days)
                except Exception:
                    return 9999
            near = cm and cm.get('use') and cm['use']<'2026-04-01' and _dd(cm['use'], sd)<=14
            if not near:
                if cm: _used_card.discard(id(cm))   # 오매칭 소비 롤백
                continue   # base(승인-Q2)에 이미 존재
    # === 미포함(Q1 선결제 or 현금) → 추가 ===
    n+=1
    acct=account_of(r['item'],r['desc'])
    src,issuer=src_of(r['card'],r['item'],acct)
    cardcell = a  # 금액: 카드 우선
    fx='';cur='';country='해외'; ap=''; oap=''
    if is_card(r['card']):
        if cm:
            cardcell = cm['amt'] if a>=0 else -cm['amt']
            fx=cm['fx']; cur=cm['cur']; ap=cm.get('appr','')
            if cm['sub']=='국내': country='KR'
            # ★규칙(사용자 확정): 환불→원거래 연결은 '승인번호' 기준. 국민국내=괄호형 원승인, 하나=동일행 승인번호.
            if a<0: oap=cm.get('orig','') or (ap if cm.get('src')=='HAN' else '')
        percard[issuer]+=1
    else:
        cashtot+=abs(a); country='KR'
    # VAT/원가: 해외여행 원가 대부분 불공제_해외 (부가세 영향 0). 국내(부산 등)만 확인.
    dom = r['tab'].endswith('부산') or (src=='MAN')
    vat_tag='확인' if (dom and src!='MAN') else ('불공제_국내' if src=='MAN' else '불공제_해외')
    if src=='MAN': vat_tag='불공제_현금'
    cancel = a<0
    row={k:'' for k in FN}
    mr=manrow(r)
    rowtag='수기%s행 | '%mr if mr else ''
    # 예약번호→체크인일 오버라이드(2026-07-22 사용자 확정서 제공): 무일자 6건 — 현지결제 APA/카즈베기는
    #   체크인=결제일, 아드리아는 선결제라 체크인일 대용. 확정서 금액은 수기값과 일치 확인됨.
    BOOK_DATE={'1721756989':'2026-04-26','1721757952':'2026-04-26','1721758806':'2026-04-26','1721761805':'2026-04-26',
               '1715820607':'2026-05-10','1717093956':'2026-05-15'}
    # 날짜 fallback: 수기 기재일이 깨졌으면(에히메 55행 '25.0' 실측) 매칭 카드 승인일 사용
    row.update(uid='TRIP-%04d'%n, src=src, use_date=BOOK_DATE.get(book, sd or d10(r['date']) or (cm.get('use','') if cm else '')), post_date='', card4=(r['card'] if re.match(r'\d{4}',r['card'] or '') else ''),
        merchant=r['item'], country=country, currency=cur or ('KRW' if is_card(r['card']) else ''), foreign=fx or '0',
        krw=str(cardcell), vat='0.0', status=('취소' if cancel else '정상'), extra='', bucket=r['tab'], account=acct,
        cancel=str(cancel), cost_type='여행원가', vat_tag=vat_tag, confidence='상',
        note='%s수기장부 선결제 반영(%s) | %s%s'%(rowtag, issuer, r['desc'], ' 예약'+book if book else ''),
        tax_conf='상', appr=(ap if not cancel else ''), orig_appr=oap)
    new.append(row); addtot+=cardcell; pertab[r['tab']]+=cardcell

out=cls+new
with open('data/classified_v13.csv','w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=FN); w.writeheader(); w.writerows(out)
oldtot=sum(abs(i(r['krw'])) for r in cls); newtot=sum(i(r['krw']) for r in out)
print('추가 %d건 (증빙별 %s), 현금계열 합 %s'%(n, dict(percard), format(cashtot,',')))
print('classified_v13: %d행, krw합 %s (기존 221,040,838 → 증가 %s)'%(len(out), format(newtot,','), format(newtot-221040838,'+,')))
print('-- 여행탭별 추가액 --')
for t,s in sorted(pertab.items(),key=lambda x:-x[1]):
    print('  {:16} {:+,}'.format(t,round(s)))
