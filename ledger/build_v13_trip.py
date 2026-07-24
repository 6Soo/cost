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

# ---- 스키마 기반 로딩(2026-07-24, 사용자 지시 "1번 적용") ----
# 컬럼 인덱스(r[5] 등)로 원본을 읽으면 양식이 미세하게 바뀌어도 에러 없이 엉뚱한 값을 읽어
# "유령 데이터"를 만든다(승인취소 유령거래 사례). 헤더를 실제로 검증한 뒤 이름으로 접근한다 —
# 헤더가 어긋나면 조용히 넘어가지 말고 즉시 실패(assert)한다.
SCHEMAS={
 'E':(0,['매입일','승인일','부서번호','부서명','카드번호','이용자명','결제방법','가맹점명','이용국가','도시명','통화코드','현지이용금액','미화환산금액','적용환율','결제원금','수수료','총결제금액']),
 'F':(0,['매입일','승인일','승인시간','부서번호','부서명','카드번호','이용자명','가맹점명','업종명','결제방법','할부개월수','승인금액','부가세','승인구분','승인방식','승인번호','상태','과세유형','가맹점상태','가맹점번호','가맹점사업자등록번호','대표자성명','가맹점주소','가맹점전화번호']),
 'G':(5,['NO','이용일','이용시간','카드번호','승인번호','승인금액','승인취소금액','가맹점명','업종명','가맹점번호','가맹점사업자번호','이용구분','할부기간','매입','매입금액','매출취소금액','매입일','상태','부가세','하위몰정보']),
 'H':(5,['NO','이용일','이용시간','카드번호','승인번호','승인금액','승인취소금액','가맹점명','업종명','가맹점번호','가맹점사업자번호','이용구분','할부기간','매입','매입금액','매출취소금액','매입일','상태','부가세','하위몰정보']),
}
def _norm(h): return re.sub(r'\s+','',h)
def load_named(f):
    hr,cols=SCHEMAS[f]
    raw=load(f)
    got=[_norm(h) for h in raw[hr][:len(cols)]]
    assert got==cols, ('%s 헤더가 예상과 다르다 — 양식 변경 가능성, 컬럼 매핑 재검증 필요.\n예상: %s\n실제: %s'%(f,cols,got))
    return [dict(zip(cols,r)) for r in raw[hr+1:]]
# A_20260720(기업카드)는 원본 자체에 헤더 행이 없다 — 실제 헤더 검증은 불가하지만, 매직넘버
# 대신 이름 있는 상수로 위치를 문서화해둔다(향후 헤더 있는 포맷으로 바뀌면 이 매핑부터 재검증).
A_COLS=['통화구분','국내해외','일시','카드번호','카드명','가맹점명','승인금액','현지금액표기',
        '카드명2','결제방법','할부','미상1','미상2','승인번호','미상3','미상4','미상5','매입일','만료일','사업자번호']

# ★일괄 가시화 헬퍼(2026-07-24 "2번 적용"): 조용히 걸러지는 행이 있어도 로그에 찍혀야
#   사람이 스프레드시트를 열기 전에 이상 유무를 알 수 있다(전 소스에 ground-truth 요약행이
#   있는 건 아니라 G/H처럼 assert는 못 걸어도, 최소한 스캔/편입 건수·합계는 항상 남긴다).
def _report(src, scanned, kept):
    amt=sum(c['amt']*(-1 if c['cx'] else 1) for c in kept)
    print('  %s: 원본 %d행 스캔 → %d건 편입(순액 %s)'%(src, scanned, len(kept), format(amt,',')))

# ---- 통합 카드 인덱스 (정상+취소, 금액→상세) ----
cards=[]
_rows=load_named('E'); _n0=len(cards)
for r in _rows:
    if i(r['총결제금액']):
        cards.append(dict(co='국민',use=d10(r['승인일']) or d10(r['매입일']),c4=r['카드번호'][-4:],amt=i(r['총결제금액']),mer=r['가맹점명'],fx=r['현지이용금액'],cur=r['통화코드'],sub='해외',src='KBO',cx=(r['결제방법']=='취소매출'),appr=''))
_report('E(국민해외)', len(_rows), cards[_n0:])
_rows=load_named('F'); _n0=len(cards)
for r in _rows:
    if i(r['승인금액']):
        _m=re.match(r'^\s*(\d+)\((\d+)\)\s*$', str(r['승인번호']).strip())
        _ap,_og=(_m.group(1),_m.group(2)) if _m else (re.sub(r'\D','',r['승인번호']),'')
        cards.append(dict(co='국민',use=d10(r['승인일']),c4=r['카드번호'][-4:],amt=abs(i(r['승인금액'])),mer=r['가맹점명'],fx='',cur='',sub='국내',src='KBD',cx=(i(r['승인금액'])<0),appr=_ap,orig=_og))
_report('F(국민국내)', len(_rows), cards[_n0:])
for f in ('G','H'):
    _n0=len(cards); _rows=load_named(f)
    for r in _rows:
        if r['NO'] and r['NO']!='NO' and i(r['승인금액']):
            # ★2026-07-24 RESIDHOTEL 실측 발견: 상태='승인취소'는 매입 자체가 안 된(미매입) 승인 취소 —
            #   실청구 0(전액상쇄, "매출취소"와 다름: 저건 매입 후 진짜 환불). 이 상태를 무시하고
            #   매입금액(0)→승인금액 폴백(or)을 적용하면 실체없는 "-178,948원 취소" 유령거래가 생겨
            #   카드사용내역_미배정에 가짜 비용누락으로 잡힌다(H파일 89건 7,753,748원·G파일 2건 454,176원 실측).
            if r['상태']=='승인취소': continue
            gu='해외' if '해외' in (r['이용구분'] or '') else '국내'
            cards.append(dict(co='하나',use=d10(r['이용일']),c4=r['카드번호'][-4:],amt=i(r['매입금액']) or i(r['승인금액']),mer=r['가맹점명'],fx='',cur='',sub=gu,src='HAN',cx=(i(r['승인취소금액'])!=0),appr=re.sub(r'\D','',r['승인번호'])))
    # ★불변조건 체크(2026-07-24, "2번 적용"): G/H 원본 자체에 승인/매입/승인취소 건수가 요약돼 있다
    #   (row1~3). 승인건수-승인취소건수=매입 대상 건수와 실제 편입건수를 대조 — 조용히 안 맞으면
    #   사람이 스프레드시트를 열기 전에 여기서 먼저 경고한다.
    _raw=load(f); _sumrow=lambda label: next((c for row in _raw[:4] for j,c in enumerate(row) if isinstance(c,str) and label in c and j+1<len(row)), None)
    def _cnt(label):
        for row in _raw[:4]:
            for j,c in enumerate(row):
                if isinstance(c,str) and label in c and j+1<len(row):
                    m=re.search(r'[\d,]+', str(row[j+1]))
                    if m: return int(m.group().replace(',',''))
        return None
    # ★실측 확인(2026-07-24): 원본 "승인건수"는 이미 승인취소(상태='승인취소')를 제외한 수치다
    #   (정상+매출취소만 포함) — 승인건수-승인취소건수가 아니라 승인건수 자체가 기대 편입건수.
    _appr_cnt=_cnt('승인\n건수') or _cnt('승인건수')
    _got=len(cards)-_n0
    if _appr_cnt is not None:
        if _got!=_appr_cnt:
            print('⚠️ 불변조건 위반: %s 원본 승인건수=%d인데 실제 편입 %d건(차이 %+d) — 원본 재확인 필요'%(f,_appr_cnt,_got,_got-_appr_cnt))
        else:
            print('✓ %s 불변조건 통과: 원본 승인건수=편입건수=%d건'%(f,_got))
    _report('%s(하나)'%f, len(_rows), cards[_n0:])
_rawA=load('A_20260720'); _n0=len(cards)
for raw in _rawA:
    r=dict(zip(A_COLS,raw))
    if i(r['승인금액']):
        gu='해외' if r['국내해외'].startswith('해외') else '국내'
        cards.append(dict(co='기업',use=r['일시'][:10],c4=r['카드번호'][-4:],amt=i(r['승인금액']),mer=r['가맹점명'],fx=(r['현지금액표기'] or '').split()[0] if r['현지금액표기'] else '',cur='JPY' if 'JPY' in (r['현지금액표기'] or '') else '',sub=gu,src='CORP',cx=(r['통화구분']=='취소또는할인'),appr=re.sub(r'\D','',r['승인번호'])))
_report('A(기업)', len(_rawA), cards[_n0:])
byamt=defaultdict(list)
for c in cards: byamt[(c['amt'],c['cx'])].append(c)
amts=sorted(set(a for a,_ in byamt))
_used_card=set()   # 소비형: 한 카드 레코드는 한 수기행에만 배정(같은 승인 재사용·도용 방지)
KEYWORDS=[('AGODA','아고다'),('BOOKING','부킹'),('BKG','부킹'),('TRIP.COM','트립닷컴'),('트립','트립닷컴'),
          ('MERCURE','머큐르'),('HOTEL','호텔'),('료칸','ryokan')]
def _kw_of(s):
    u=(s or '').upper()
    return {k for k,ko in KEYWORDS if k in u or ko in (s or '')}
def card_match(a, co, want_cx=False, item=None):
    # ★매칭 우선순위(2026-07-24 사용자 확정): 1순위 예약번호(호출부에서 book_in/bookidx로 별도 처리),
    #   2순위 금액+항목 키워드 일부일치(agoda/트립닷컴 등) — 동일금액 후보가 여럿일 때 키워드로 소거.
    # ★부호(취소여부) 일치 + 카드사 일치 필수(타사 폴백 금지) + 소비형(1카드=1행).
    cand=byamt.get((a,want_cx),[])
    if not cand:
        lo,hi=a*0.98,a*1.02
        cand=[c for x in amts if lo<=x<=hi for c in byamt.get((x,want_cx),[])]
    pool=[c for c in cand if c['co']==co and id(c) not in _used_card]
    if not pool: return None
    if item:
        ikw=_kw_of(item)
        if ikw:
            kw_pool=[c for c in pool if _kw_of(c['mer']) & ikw]
            if kw_pool: pool=kw_pool   # 키워드 일치 후보가 있으면 그쪽만 우선(2순위 적용)
    best=min(pool,key=lambda c:abs(c['amt']-a))
    _used_card.add(id(best))
    return best
def issuer_of(card_field):
    # 원장 카드열이 발급사명(국민/하나/기업)이 아니라 카드번호 뒷4자리(8835 등)로 적힌 경우도 매핑
    # (2026-07-24 발견: 이 매핑이 없어 AGODA APA 4건 등이 card_match 자체를 못 태워 하드코딩 오버라이드로
    #  우회하던 버그 — 근본교정: src_of()와 동일 규칙으로 발급사 판별).
    c=(card_field or '').strip()
    if c in ('국민','하나','기업'): return c
    if re.match(r'8835|3804|3820|4886|8895|0906', c): return '국민'
    if re.match(r'4595|5483|3923|4140|4336', c): return '하나'
    if re.match(r'4971|4985|8972', c): return '기업'
    return ''

# ---- 기존 워크북 (classified_v12) ----
FN=['uid','src','use_date','post_date','card4','user','merchant','biz','country','currency','foreign','krw','vat','tax_type','status','biz_no','extra','bucket','account','cancel','cost_type','vat_tag','confidence','note','tax_conf','appr','orig_appr']
cls=list(csv.DictReader(open('data/classified_v12.csv',encoding='utf-8')))
# 내가 v52에서 여행_미배정에 둔 ¥7,439(KBO-9002)는 수기(0417_아오모리)로 통합되므로 base에서 제거
cls=[r for r in cls if r['uid']!='KBO-9002']
# 2026-07-24 개칭: base(classified_v12)에 옛 이름 '여행_미배정'으로 박제된 행(카드 실체는 있으나
#   여행탭 미확정) 8건도 신규 명명(카드사용내역_미배정)으로 정규화 — 전부 카드/PG 실결제건(수기 없음)이라
#   OTA_미배정이 아니라 카드사용내역_미배정이 맞다.
for _r in cls:
    if _r['bucket']=='여행_미배정': _r['bucket']='카드사용내역_미배정'
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
# ★2026-07-24 발견(수기장부 재생성 직후 실측): book_in은 classified_v12.csv(base)의 note 텍스트를
# 스캔해서 만드는데, patch_v14.py가 나중에(이 스크립트보다 뒤 단계에서) note에 예약번호를 붙이는
# 확정건(예: KBO-0360 롯데 아라이 1740166023)은 base 자체엔 그 번호가 없어 book_in이 놓친다.
# 게다가 원장에 날짜가 아직 공란인 수기행(sd='')은 Q2 날짜기반 dedup(라인 하단)도 건너뛰어 이중
# 안전장치가 둘 다 뚫린다 — 실측: 원장이 금액만 채워지자 TRIP-0393(230,782)이 KBO-0360(222,217)과
# 별개로 또 생겨 이중계상될 뻔함. base에 이미 확정 배치된 걸 아는 예약번호는 명시적으로 book_in에 못박는다.
KNOWN_BASE_BOOKINGS={'1740166023'}   # KBO-0360(묘코 롯데 아라이) — 원장 날짜 공란이라 Q2게이트도 못 잡음
book_in |= KNOWN_BASE_BOOKINGS

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

# 예약번호→체크인일 오버라이드(2026-07-22 사용자 확정서 제공): 무일자 6건 — 현지결제 APA/카즈베기는
#   체크인=결제일, 아드리아는 선결제라 체크인일 대용. 확정서 금액은 수기값과 일치 확인됨.
BOOK_DATE={'1721756989':'2026-04-26','1721757952':'2026-04-26','1721758806':'2026-04-26','1721761805':'2026-04-26',
           '1715820607':'2026-05-10','1717093956':'2026-05-15'}
# APA 가나자와 4건 금액교체(2026-07-22 사용자 확정): 편의환율 604,800→실제 카드 총결제 2,287,848÷4=571,962.
#   (카드는 JPY241,920 1건 합산청구, 4행 균등배분. 대표님 다른 국민해외건과 총결제금액 기준 통일.)
BOOK_KRW={'1721756989':571962,'1721757952':571962,'1721758806':571962,'1721761805':571962}

new=[]; n=0; addtot=0; cashtot=0; ota_mi=0
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
        cm=card_match(abs(a), issuer_of(r['card']), want_cx=(a<0), item=r['item'])
        if sd and sd>='2026-04-01' and a>=0:
            # ★2026-07-23 사용자 "Q2필터 없애버려": 선결제는 승인이 수개월~1년 전일 수 있음(예: mercure 승인 2월·여행 6월).
            #   14일 근접창 제거 — 매칭 카드가 Q2 이전(<4/1) 승인이면 승인일 간격 무제한으로 선결제 인정·편입.
            #   Q2 승인(≥4/1) 카드는 base(classified_v12)에 이미 있을 가능성 → 중복방지 위해 skip 유지.
            #   ★취소(-)행(a<0)은 이 블록 자체를 건너뜀(위 `and a>=0`) → 순액처리 위해 항상 편입.
            is_prepay = cm and cm.get('use') and cm['use']<'2026-04-01'
            if not is_prepay:
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
    if book in BOOK_KRW: cardcell = BOOK_KRW[book] if a>=0 else -BOOK_KRW[book]
    # ── OTA_미배정 (2026-07-24 사용자 지시 ③): 수기장부가 카드결제로 표기했는데 실카드 데이터에서
    #   매칭이 안 되는 건 — 예약번호(1순위)·금액+항목키워드(2순위) 재대조로도 실카드를 못 찾은 잔여만 해당.
    #   BOOK_KRW 확정 오버라이드가 있는 건은 실체가 이미 확정된 것이므로 제외.
    ota_gap = is_card(r['card']) and not cm and book not in BOOK_KRW
    bucket = 'OTA_미배정' if ota_gap else r['tab']
    note = ('%s수기장부 선결제 반영(%s) | %s%s'%(rowtag, issuer, r['desc'], ' 예약'+book if book else '')
            if not ota_gap else
            '⚠OTA_미배정: 수기장부 %s결제 표기(%s)이나 실카드 매칭 실패(예약번호·금액+키워드 재대조 후에도) | %s | %s%s'
            %(issuer, r['tab'], rowtag.rstrip('| ') or '수기', r['desc'], ' 예약'+book if book else ''))
    if ota_gap: ota_mi+=1
    # 날짜 fallback: 수기 기재일이 깨졌으면(에히메 55행 '25.0' 실측) 매칭 카드 승인일 사용
    row.update(uid='TRIP-%04d'%n, src=src, use_date=BOOK_DATE.get(book, sd or d10(r['date']) or (cm.get('use','') if cm else '')), post_date='', card4=(r['card'] if re.match(r'\d{4}',r['card'] or '') else ''),
        merchant=r['item'], country=country, currency=cur or ('KRW' if is_card(r['card']) else ''), foreign=fx or '0',
        krw=str(cardcell), vat='0.0', status=('취소' if cancel else '정상'), extra='', bucket=bucket, account=acct,
        cancel=str(cancel), cost_type='여행원가', vat_tag=vat_tag, confidence=('하' if ota_gap else '상'),
        note=note, tax_conf=('하' if ota_gap else '상'), appr=(ap if not cancel else ''), orig_appr=oap)
    new.append(row); addtot+=cardcell
    if not ota_gap: pertab[r['tab']]+=cardcell

# ── 옵션① (사용자 2026-07-23 "1번으로 가야해", 2026-07-24 "카드사용내역_미배정"으로 개칭) ──
#   base(classified_v12)·수기매칭 어디에서도 소비 안 된 카드 = 워크북 어디에도 없는 실결제(진에어30k 등 누락 근본원인).
#   ★이 레포 1순위 목표(사용자 확정 2026-07-24): 모든 카드사용내역은 반드시 어느 탭엔가 배정돼야 한다 —
#     "카드사용내역_미배정"은 곧 비용 누락이므로 이 건수·금액을 0으로 수렴시키는 게 최우선.
#   Q2 승인(2026-04~06)만 대상. 날짜근접 자동귀속은 하지 않고(사용자가 ②를 기각) 별도 탭에 담아 대표님 검토.
_mi=0; misc=[]; misctot=0; miscissuer=Counter()
_ISS={'KBO':'국민','KBD':'국민','HAN':'하나','CORP':'기업'}
for c in cards:
    if id(c) in _used_card: continue
    u=c.get('use') or ''
    if not ('2026-04-01'<=u<='2026-06-30'): continue   # Q2 승인만(Q1 선결제 미매칭은 여기 제외 — 대응 여행탭 불명)
    _mi+=1
    amt = -c['amt'] if c['cx'] else c['amt']
    issuer=_ISS.get(c['src'],'기타'); miscissuer[issuer]+=1
    acct=account_of(c['mer'],'')
    row={k:'' for k in FN}
    row.update(uid='MISC-%04d'%_mi, src=c['src'], use_date=u, post_date='',
        card4=c.get('c4',''), merchant=c['mer'], country=('KR' if c['sub']=='국내' else '해외'),
        currency=c['cur'] or 'KRW', foreign=c['fx'] or '0', krw=str(amt), vat='0.0',
        status=('취소' if c['cx'] else '정상'), bucket='카드사용내역_미배정', account=acct,
        cancel=str(c['cx']), cost_type='여행원가', vat_tag='불공제_해외', confidence='하',
        note='⚠카드사용내역_미배정(비용 누락 가능): 수기 미기재 실카드결제(%s) — 대표님 검토요망: 여행탭 귀속/판관비 판정 필요'%issuer,
        tax_conf='하', appr=c.get('appr',''), orig_appr='')
    misc.append(row); misctot+=amt; _used_card.add(id(c))
print('옵션① 미매칭 Q2 실카드 → 카드사용내역_미배정(=비용누락 후보): %d건 %s (합 %s)'%(_mi, dict(miscissuer), format(misctot,'+,')))
print('OTA_미배정(수기 카드표기·실카드 매칭실패): %d건'%ota_mi)
new += misc

# ── 대사 게이트 (사용자 "왜 계속 누락"): Q2 승인 카드가 base·수기·미배정 어디에도 없으면 누락 → 경고 ──
#   ★1순위 목표 검증 게이트: 카드사용내역_미배정=0건이 이상적. 지금은 위 옵션①로 전량 격리해 가시화만 함
#   (사용자가 자동귀속을 기각했으므로 0으로 만드는 건 대표님의 개별 배정 확인이 필요).
_lost=[c for c in cards if id(c) not in _used_card and '2026-04-01'<=(c.get('use') or '')<='2026-06-30']
if _lost:
    print('⚠️ 대사 실패: Q2 승인 카드 %d건이 어디에도 편입 안 됨(누락):'%len(_lost))
    for c in _lost[:20]: print('   ', c['co'], c['use'], format(c['amt'],','), (c['mer'] or '')[:24])
else:
    print('✓ 대사 통과: 모든 Q2 승인 카드가 base·수기·카드사용내역_미배정에 편입(누락 0)')

out=cls+new
with open('data/classified_v13.csv','w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=FN); w.writeheader(); w.writerows(out)
oldtot=sum(abs(i(r['krw'])) for r in cls); newtot=sum(i(r['krw']) for r in out)
print('추가 %d건 (증빙별 %s), 현금계열 합 %s'%(n, dict(percard), format(cashtot,',')))
print('classified_v13: %d행, krw합 %s (기존 221,040,838 → 증가 %s)'%(len(out), format(newtot,','), format(newtot-221040838,'+,')))
print('-- 여행탭별 추가액 --')
for t,s in sorted(pertab.items(),key=lambda x:-x[1]):
    print('  {:16} {:+,}'.format(t,round(s)))
