# -*- coding: utf-8 -*-
"""trip-first 엔진용 카드 인덱스 + 업종기반 계정분류.
각 카드결제를 승인번호·이용일·업종·청구금액·상태까지 정규화."""
import openpyxl, re
from pathlib import Path
from collections import defaultdict
from ledger.domain.han_normalizer import (HAN_NORMALIZER_CONTRACT_SHA256,
    HAN_NORMALIZER_VERSION, is_han_transaction, normalize_han_components, parse_han_amounts,
    normalize_han_identity_text, validate_han_header)

def i(x):
    try: return int(round(float(str(x).replace(',','').replace('원','').strip())))
    except: return 0
def d10(s):
    m=re.search(r'(\d{4})[.\-](\d\d)[.\-](\d\d)',str(s)); return '%s-%s-%s'%(m.group(1),m.group(2),m.group(3)) if m else ''
DEFAULT_LEDGER_DIR = Path(__file__).resolve().parent

def load(f, *, ledger_dir=None):
    root = Path(ledger_dir) if ledger_dir is not None else DEFAULT_LEDGER_DIR
    wb = openpyxl.load_workbook(root / 'newcard' / 'conv' / (f + '.xlsx'), read_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        return [[('' if c is None else str(c)) for c in r]
                for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()

def build_cards(*, ledger_dir=None):
    root = Path(ledger_dir) if ledger_dir is not None else DEFAULT_LEDGER_DIR
    cards=[]
    # 국민국내 F: 승인일1 카드5 가맹7 업종8 승인금11 부가세12 승인번호15 상태16 매입일0
    #   취소전표 승인번호는 '취소번호(원승인번호)' 괄호형(195/195 실측) → orig에 원승인 분리 저장
    for row_number, r in enumerate(load('F', ledger_dir=root)[1:], start=2):
        if len(r)>16 and i(r[11]):
            _m=re.match(r'^\s*(\d+)\((\d+)\)\s*$', str(r[15]).strip())
            _ap,_orig=(_m.group(1),_m.group(2)) if _m else (re.sub(r'\D','',r[15]),'')
            cards.append(dict(co='국민',src='KBD',raw_record_id=f'F:{row_number}',c4=r[5][-4:],appr=_ap,orig=_orig,
                use=d10(r[1]),bill=d10(r[0]),mer=r[7],uptype=r[8],krw=i(r[11]),vat=i(r[12]),
                cur='KRW',fx=0,sub='국내',cancel=('취소' in (r[16] or '')),status=r[16]))
    # 국민해외 E: 승인일1 카드4 가맹7 통화10 현지11 총결제16 결제방법6 매입일0 (승인번호 없음)
    for row_number, r in enumerate(load('E', ledger_dir=root)[1:], start=2):
        if len(r)>16 and i(r[16]):
            cards.append(dict(co='국민',src='KBO',raw_record_id=f'E:{row_number}',c4=r[4][-4:],appr='',orig='',
                use=d10(r[1]) or d10(r[0]),bill=d10(r[0]),mer=r[7],uptype='해외',krw=i(r[16]),vat=0,
                cur=r[10],fx=r[11],sub='해외',cancel=(r[6]=='취소매출'),status=r[6]))
    # 하나 G/H: 이용일1 카드3 승인번호4 승인금5 승인취소6 가맹7 업종8 이용구분11 매입금14 매입일16 상태17 부가세18
    for f in ('G','H'):
        rows=load(f, ledger_dir=root); columns=validate_han_header(rows[5] if len(rows)>5 else ())
        for row_number, r in enumerate(rows[6:], start=7):
            card_identity=normalize_han_identity_text(r[3]) if len(r)>3 else ""
            approval_identity=normalize_han_identity_text(r[4]) if len(r)>4 else ""
            identity_present=bool(card_identity or approval_identity)
            amounts=parse_han_amounts(r,columns) if identity_present else None
            populated=is_han_transaction(amounts,identity_present=True) if amounts is not None else False
            if len(r)>17 and amounts and populated:
                gu='해외' if '해외' in (r[11] or '') else '국내'
                components=normalize_han_components(amounts)
                cards.append(dict(co='하나',src='HAN',raw_record_id=f'{f}:{row_number}',c4=card_identity[-4:],appr=re.sub(r'\D','',approval_identity),orig=re.sub(r'\D','',approval_identity),
                    use=d10(r[1]),bill=d10(r[16]),mer=r[7],uptype=r[8],krw=components[0].signed_amount_krw,
                    approval_amount=amounts.approval_amount,cancel_amount=amounts.cancel_amount,purchase_amount=amounts.purchase_amount,
                    amount_selection_reason=components[0].selection_reason,
                    han_components=tuple((x.role,x.signed_amount_krw,x.transaction_type,x.selection_reason) for x in components),
                    han_normalizer_version=HAN_NORMALIZER_VERSION,han_contract_sha256=HAN_NORMALIZER_CONTRACT_SHA256,
                    vat=i(r[18]),cur='KRW',fx=0,sub=gu,cancel=bool(amounts.cancel_amount),status=r[17]))
    # 기업 A(헤더없음): 거래구분0 유형1 일시2 카드3 가맹5 금액6 외화7 승인번호13
    for row_number, r in enumerate(load('A_20260720', ledger_dir=root), start=1):
        if len(r)>13 and i(r[6]) and re.match(r'\d{4}-\d\d-\d\d',r[2] or ''):
            gu='해외' if (r[1] or '').startswith('해외') else '국내'
            cards.append(dict(co='기업',src='CORP',raw_record_id=f'A_20260720:{row_number}',c4=r[3][-4:],appr=re.sub(r'\D','',r[13]),orig='',
                use=r[2][:10],bill=r[2][:10],mer=r[5],uptype='',krw=i(r[6]),vat=0,
                cur='JPY' if 'JPY' in (r[7] or '') else '',fx=(r[7] or '').split()[0] if r[7] else 0,
                sub=gu,cancel=(r[0]=='취소또는할인'),status=r[0]))
    return cards

# 업종명 → 계정 (카드사 업종 우선, 없으면 브랜드/desc)
FOOD={'편의점','슈퍼마켓','슈퍼마켓.마트','한식','일식','일식전문점','중식','양식','음식','휴게음식','제과','커피','카페','유흥','food','restaurant'}
def account(uptype, merchant, desc):
    u=uptype or ''; s=(desc or '')+' '+(merchant or ''); su=s.upper()
    # 1) desc 명시 키워드 최우선(수기 의도)
    if '항공' in s: return '항공료'
    if '숙박' in s or '료칸' in s: return '숙박비'
    if '렌터카' in s or '렌트' in s: return '렌터카'
    if '통행' in s: return '통행료'
    if '입장' in s or '입장료' in s: return '입장료'
    if '보험' in s or '트래블로버' in s: return '여행자보험'
    if '교통' in s: return '교통비'
    if '식비' in s or '식대' in s: return '식비'
    # 2) 카드 업종명
    if '항공' in u: return '항공료'
    if any(k in u for k in ['숙박','호텔','콘도','리조트','펜션','여관','모텔']): return '숙박비'
    if '택시' in u or '버스' in u or '철도' in u or '지하철' in u or '고속' in u: return '교통비'
    if '주유' in u or '주차' in u or 'LPG' in u.upper(): return '교통비'
    if any(k in u for k in FOOD): return '식비'
    if '렌터카' in u or '렌트' in u: return '렌터카'
    # 3) 브랜드
    if any(k in su for k in ['ENEOS','IDEMITSU','GASSTAND','GAS ','JA-SS','JASS','ESSO','SHELL','TOTAL','SINOOIL','AZS']): return '교통비'  # 주유
    if 'REPARK' in su or 'PARK' in su and 'HOTEL' not in su: return '교통비'  # 주차
    if any(k in su for k in ['SEVEN','LAWSON','FAMILYMART','MART','CU','GS25','MONOP','CARREFOUR','SUPERMERC','STARBUCKS','MCDON','BURGER','CAFE','KING']): return '식비'
    if any(k in su for k in ['마이트립','고투게이트','제주항공','대한항공','아시아나','ANA','진에어','스카이티켓','어드벤처코리아','VOLOTEA','FLIX','SNCF','에어','AIR']): return '항공료'
    if any(k in su for k in ['HOTEL','호텔','AGODA','아고다','BOOKING','부킹','MERCURE','RESORT','HOSTEL','INN','RYOKAN']): return '숙박비'
    # 4) 트립닷컴 등 OTA PG: desc가 사람이름(한글2~4자)만이면 항공, 아니면 숙박
    if any(k in su for k in ['트립닷컴','TRIP.COM','TRIP','아고다','AGODA']):
        dd=(desc or '').strip()
        if re.fullmatch(r'[가-힣]{2,4}( ?[가-힣]{2,4})*', dd): return '항공료'  # 사람이름 나열=항공권
        return '숙박비'
    if any(k in su for k in ['NICE','이니시스','KCP','PG','전자상거래']): return '숙박비'  # 잔여 PG
    return '기타'

if __name__=='__main__':
    cards=build_cards()
    print('카드 총', len(cards))
    # 테스트: 문제 케이스 계정분류
    tests=[('','트립닷컴','심우경'),('','트립닷컴','항공_0620_윤'),('편의점','SEVEN-ELEVEN',''),
           ('','IDEMITSU','숙박비'),('택시','카카오T',''),('','MITSUIS REPARK',''),
           ('','마이트립_아오모리','원덕자 조영옥'),('','AGODA.COM BUSINESS H','숙박_0416_0417'),
           ('','KYOTO UNIVERSAL HOTEL','')]
    for u,m,d in tests:
        print('  업종[%s] %s / desc[%s] → %s'%(u,m,d,account(u,m,d)))
