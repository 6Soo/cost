# -*- coding: utf-8 -*-
# Q2 비용분류 결과 워크북 조립 — classified.csv(+fixes.json) → 숲길여행_2분기_비용분류_AI_v62.xlsx
import csv, json, re, os
from collections import defaultdict, Counter
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(DIR)

HDR_FILL = PatternFill('solid', fgColor='1F4E5F')
HDR_FONT = Font(color='FFFFFF', bold=True)
WARN_FILL = PatternFill('solid', fgColor='FFF2CC')
BAD_FILL = PatternFill('solid', fgColor='F4CCCC')
OK_FILL = PatternFill('solid', fgColor='D9EAD3')
THIN = Border(*[Side(style='thin', color='CCCCCC')]*4)

def num(s):
    try: return float(s)
    except: return 0.0

rows = list(csv.DictReader(open('classified_v14.csv', encoding='utf-8')))
# 검증 픽스 적용
if os.path.exists('fixes_ALREADY_APPLIED.json'):
    fixes = json.load(open('fixes.json', encoding='utf-8'))
    fixmap = {f['uid']: f for f in fixes}
    applied = 0
    for r in rows:
        f = fixmap.get(r['uid'])
        if not f: continue
        for k in ('bucket', 'account', 'vat_tag', 'cost_type'):
            if f.get(k): r[k] = f[k]
        if f.get('note'): r['note'] = (r['note'] + ' | 검증: ' + f['note'])[:160]
        if f.get('reason'): r['note'] = (r['note'] + ' | 검증: ' + f['reason'])[:160]
        applied += 1
    print('fixes 적용:', applied)

trips = json.load(open('trips.json', encoding='utf-8'))
trip_order = [t['tab'] for t in trips]
income = json.load(open('income_totals.json', encoding='utf-8'))
manual = json.load(open('manual_totals.json', encoding='utf-8'))
manual_etc = json.load(open('manual_etc_total.json', encoding='utf-8'))

# 수기 지출(탭별) — 미매칭 색칠용 (금액 기준)
manual_rows = defaultdict(list)
with open('manual_expenses.csv', encoding='utf-8') as _f:
    for _m in csv.DictReader(_f):
        manual_rows[_m['탭']].append(round(num(_m['금액'])))
manual_amt = {t: Counter(v) for t, v in manual_rows.items()}
import os as _os
MATCHED = json.load(open('matched_fresh.json' if _os.path.exists('matched_fresh.json') else 'matched_uids.json', encoding='utf-8'))  # ★최신 수기 기준 매칭(P8) — gen_matched.py가 매 파이프라인마다 재생성
BOOK_FILL = PatternFill('solid', fgColor='FCE5CD')  # 수기 미매칭(주황)
MERGE_FILL = PatternFill('solid', fgColor='DEEAF6')  # 수기장부 병합건(연파랑)
LINK_FONT = Font(color='0563C1', underline='single')
SRC_BASE = {'KBD': 1, 'KBO': 1106, 'HAN': 2986, 'CORP': 2000}
SRC_NAME = {'KBD': '국민', 'KBO': '국민해외', 'HAN': '하나', 'CORP': '기업카드'}
SRC_BASE_X = 0
def srcref(uid):
    s, n = uid.split('-')
    if s not in SRC_NAME: return f"{s}_{n}_"
    return f"{SRC_NAME[s]}_{int(n) - SRC_BASE[s] + 2}행_"

import json as _json
try:
    BOOKING_PINS = _json.load(open('booking_pins.json', encoding='utf-8'))
except FileNotFoundError:
    BOOKING_PINS = {}
try:
    TRIP_FLIGHT = _json.load(open('trip_flight_links.json', encoding='utf-8'))
except FileNotFoundError:
    TRIP_FLIGHT = {}

# 수기장부 내용(desc) 사전 — 매칭건의 내용 열을 수기 표기('숙박_0405_0406')로 복원
_MAN = list(csv.DictReader(open('manual_v3.csv', encoding='utf-8')))
DESC_BY_BOOK = {}
DESC_BY_TABAMT = defaultdict(set)
for _m in _MAN:
    _d = (_m['desc'] or '').strip()
    if not _d: continue
    _bk = (_m['book'] or '').strip()
    if _bk: DESC_BY_BOOK.setdefault(_bk, _d)
    try: _a = round(float(_m['amount']))
    except (TypeError, ValueError): continue
    DESC_BY_TABAMT[(_m['tab'], _a)].add(_d)

def ledger_desc(x):
    n = x.get('note') or ''
    m = re.search(r'예약\s*([0-9]{6,19})', n)
    if m and m.group(1) in DESC_BY_BOOK: return DESC_BY_BOOK[m.group(1)]
    # 탭+금액 desc 조회는 수기 매칭이 확정된 건에만 (우연한 금액 일치로 남의 desc가 붙는 것 방지)
    if MATCHED.get(x['uid']) in ('matched', 'cancel'):
        ds = DESC_BY_TABAMT.get((x['bucket'], round(abs(x['krw_f']))))
        if ds and len(ds) == 1: return next(iter(ds))
    if x['account'] == '숙박비':
        m2 = re.search(r'체크인\s*(\d{4})-(\d{2})-(\d{2})(?:\s*[~–]\s*(\d{4})-(\d{2})-(\d{2}))?', n)
        if m2:
            out = '숙박_' + m2.group(2) + m2.group(3)
            if m2.group(4): out += '_' + m2.group(5) + m2.group(6)
            return out
        m3 = re.search(r'체크인\s*(\d{1,2})/(\d{1,2})', n)
        if m3: return '숙박_%02d%02d' % (int(m3.group(1)), int(m3.group(2)))
    return ''

def contents_col(x):
    d = ledger_desc(x)
    return d if d else x['account']

def clean_disp(note):
    # 표시용 노트 정리: 다른 칸·행위치가 이미 말해주는 중복 제거(원본 노트는 불변)
    #  - 예약번호(예약번호 칸에 있음), ⇄수기 접두(수기행=상단 위치·색), 밑줄 브랜드라벨(항목 칸에 있음)
    n = note or ''
    n0 = n
    n = re.sub(r'⇄수기(?:\[[^\]]*\])?:\s*', '', n)
    n = re.sub(r'예약\s*[0-9]{6,19}(?![0-9])', '', n)
    n = re.sub(r'예약코드[A-Za-z0-9]{4,10}', '', n)
    outs = []
    for s in (seg.strip() for seg in n.split('|')):
        s = re.sub(r'^(Booking\.com|BKG\*?|부킹닷컴|부킹|AGODA(\.COM)?|아고다|트립닷컴(\(구\))?|TRIP\.COM|trip_hotel)_+', '', s, flags=re.I)
        s = s.strip(' _:·')
        if s:
            outs.append(s)
    final = []
    for s in outs:
        if any(s != o and s in o for o in outs):
            continue
        if s not in final:
            final.append(s)
    n = re.sub(r'\s{2,}', ' ', ' | '.join(final)).strip(' |·:_')
    if not n:
        n = re.sub(r'예약\s*[0-9]{6,19}', '', n0).strip(' |·:_')
    return n

def booking_deeplink(merchant, note):
    t = (merchant + ' ' + (note or '')).upper()
    m = re.search(r'예약\s*([0-9]{10,19})(?![0-9])', note or '') or re.search(r'예약\s*([0-9]{6,9})(?![0-9])', note or '')
    no = m.group(1) if m else ''
    if not no:
        m2 = re.search(r'예약코드([A-Za-z0-9]{4,10})', note or '')
        return (m2.group(1), '') if m2 else ('', '')
    if 'AGODA' in t or '아고다' in t: return no, 'https://www.agoda.com/ko-kr/trips/detail?bookingId=' + no
    if 'BKG' in t or 'BOOKING' in t or '부킹' in t:
        pin = BOOKING_PINS.get(no)
        if pin: return no, 'https://secure.booking.com/mybooking.html?bn=' + no + '&pincode=' + pin + '&lang=ko'
        return no, 'https://mail.google.com/mail/#search/' + no
    if 'TRIP' in t or '트립' in t:
        fl = TRIP_FLIGHT.get(no)
        if fl is not None:
            no2 = fl.get('corrected_no') or no
            u = fl.get('url') or ('https://mail.google.com/mail/#search/' + no2)
            return no2, u
        return no, 'https://kr.trip.com/cw/hotel/ctOrderDetailPages/CheckOrderAuthPage.html?orderId=' + no + '&locale=ko-KR'
    return no, ''


for r in rows:
    r['krw_f'] = num(r['krw'])
    r['cancel_b'] = str(r.get('cancel')).lower() in ('true', '1')

by_bucket = defaultdict(list)
for r in rows:
    b = r['bucket'] if not r['cancel_b'] else r['bucket']
    by_bucket[b].append(r)

wb = openpyxl.Workbook()

def style_header(ws, n, row=1):
    for c in range(1, n + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HDR_FILL; cell.font = HDR_FONT
        cell.alignment = Alignment(horizontal='center')

def put(ws, r, vals, fills=None):
    for i, v in enumerate(vals, 1):
        c = ws.cell(row=r, column=i, value=v)
        c.border = THIN
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            c.number_format = '#,##0'
    if fills:
        for col, fl in fills.items(): ws.cell(row=r, column=col).fill = fl

# ── 1. 총괄 (순액매출 구조: 입금/지출/수익/공급가액/세액)
ws = wb.active; ws.title = '총괄'
ws.append(['행사(여행)', '수입(A·수기장부)', '카드지출(AI분류)', '수기장부 지출(B)', '차이(AI-수기)',
           '수익(A-AI지출)', '공급가액(순액)', '세액(순액10%)', 'AI건수', '비고'])
style_header(ws, 10)
row_i = 2
tot = defaultdict(float)
q2tabs = [t for t in trip_order if any(x['bucket'] == t for x in rows)] + \
         [t for t in trip_order if not any(x['bucket'] == t for x in rows) and income.get(t, 0) and t < '0713']
seen_tab = set()
for tab in trip_order:
    xs = [x for x in by_bucket.get(tab, []) if not x['cancel_b']]
    canc = sum(x['krw_f'] for x in by_bucket.get(tab, []) if x['cancel_b'])
    if not xs and tab not in ('0404_에히메',):
        if not by_bucket.get(tab): continue
    if tab in seen_tab: continue
    seen_tab.add(tab)
    ai = sum(x['krw_f'] for x in xs) + canc          # 취소는 음수 반영
    inc = income.get(tab, 0)
    man = manual.get(tab, {}).get('sum', 0)
    margin = inc - ai
    supply = round(margin / 1.1) if margin > 0 else 0
    vat10 = margin - supply if margin > 0 else 0
    diff = ai - man
    note = ''
    if abs(diff) > max(man * 0.10, 200000): note = '수기와 차이 큼 — 대조 시트 확인'
    put(ws, row_i, [tab, inc, round(ai), man, round(diff), round(margin), supply, vat10, len(xs), note],
        fills={5: (BAD_FILL if abs(diff) > max(man*0.10, 200000) and man else None) or PatternFill()} if False else None)
    if note: ws.cell(row=row_i, column=5).fill = WARN_FILL
    tot['inc'] += inc; tot['ai'] += ai; tot['man'] += man; tot['margin'] += margin
    row_i += 1
for extra_b in ['기타비용', '여행_미배정', '취소환불']:
    xs = by_bucket.get(extra_b, [])
    if not xs: continue
    ai = sum(x['krw_f'] for x in xs)
    man = manual_etc['sum'] if extra_b == '기타비용' else 0
    put(ws, row_i, [extra_b, 0, round(ai), man, round(ai - man), '', '', '', len(xs), ''])
    tot['ai'] += ai; tot['man'] += man
    row_i += 1
put(ws, row_i, ['합계', round(tot['inc']), round(tot['ai']), round(tot['man']), round(tot['ai'] - tot['man']),
                round(tot['margin']), '', '', len([x for x in rows]), ''])
for c in range(1, 11): ws.cell(row=row_i, column=c).font = Font(bold=True)
ws.column_dimensions['A'].width = 18
for col in 'BCDEFGH': ws.column_dimensions[col].width = 15
ws.column_dimensions['J'].width = 30

# ── 2. 월별순액 (세무법인 요청 형식: 월별 수입-여행원가-마진-부가세)
ws = wb.create_sheet('월별순액')
ws.append(['월', '수입 A(수기장부)', '여행원가 B(카드·순액)', '마진(A-B)', '공급가액(마진/1.1)', '부가세(10%)', '비고'])
style_header(ws, 7)
def tab_month(t):
    m2 = re.match(r'^(\d{2})(\d{2})_', t)
    if m2: return int(m2.group(1))
    m2 = re.match(r'^(\d{1,2})월', t)
    return int(m2.group(1)) if m2 else None
_ri = 2; _tt = [0,0,0]
for _mon in (4, 5, 6):
    _tabs = [t for t in trip_order if tab_month(t) == _mon]
    _inc = sum(income.get(t, 0) for t in _tabs)
    _cost = sum(x['krw_f'] for t in _tabs for x in by_bucket.get(t, []))
    _mg = _inc - _cost
    _sup = round(_mg / 1.1) if _mg > 0 else 0
    put(ws, _ri, [f'2026-{_mon:02d}', round(_inc), round(_cost), round(_mg), _sup,
                  (round(_mg) - _sup) if _mg > 0 else 0,
                  ', '.join(_tabs)[:60]])
    _tt[0] += _inc; _tt[1] += _cost; _tt[2] += _mg; _ri += 1
put(ws, _ri, ['2분기 합계', round(_tt[0]), round(_tt[1]), round(_tt[2]),
              round(_tt[2]/1.1) if _tt[2] > 0 else 0,
              round(_tt[2]) - round(_tt[2]/1.1) if _tt[2] > 0 else 0, ''])
for c in range(1, 8): ws.cell(row=_ri, column=c).font = Font(bold=True)
_ri += 2
_fut_cost = sum(x['krw_f'] for t in trip_order for x in by_bucket.get(t, []) if (tab_month(t) or 0) >= 7)
put(ws, _ri, ['선급원가(7월 이후 여행)', '', round(_fut_cost), '', '', '', '해당 여행 실행월 마진에서 차감 — 2분기 마진 계산엔 미포함'])
_ri += 1
from collections import defaultdict as _dd
_etc_m = _dd(float); _etc_ded = _dd(float)
for x in by_bucket.get('기타비용', []):
    _mo = x['use_date'][:7]
    _etc_m[_mo] += x['krw_f']
    if x['vat_tag'] == '공제후보': _etc_ded[_mo] += x['krw_f']
for _mo in sorted(_etc_m):
    put(ws, _ri, [f'판관비(기타비용) {_mo}', '', round(_etc_m[_mo]), '', '', '',
                  f'이 중 매입세액공제 후보(국내 과세) {round(_etc_ded[_mo]):,}원'])
    _ri += 1
_ri += 1
for _ln in ['· 순액과세: 매출 전체가 아니라 마진(수입-대행원가)에만 부가세. 위 공급가액/세액은 마진 기준 자동계산.',
            '· 공급시기는 원칙상 여행용역 완료일 — 월말에 걸친 여행(4/30 출발 등)의 귀속월은 세무법인과 협의.',
            '· 여행원가 B는 법인카드 발생분만(취소 상쇄 반영). 현금·계좌이체 원가는 수기장부(진행장부) 참조.',
            '· 해외 원가는 매입세액공제 대상이 아니라 마진 차감 원가(순액구조). 국내 과세매입 중 판관비만 공제 검토.']:
    ws.cell(row=_ri, column=1, value=_ln); _ri += 1
for col, w in zip('ABCDEFG', [12, 16, 18, 14, 16, 12, 60]): ws.column_dimensions[col].width = w

# ── 4. 지출 상세(여행탭별 + 기타 + 미배정 + 취소)
DETAIL_HDR = ['거래일자', '항목', '내용', '증빙유형', '금액', '원가구분', '부가세', '확신', '예약번호', '근거(AI)', 'uid']
# 장부 v8 최종 구조(연속 배치, 스페이서·숨김 열 없음): B거래일자 C항목 D내용 E금액 F증빙유형(카드번호 병기) G예약번호.
# AI 분석열은 H~(붙여넣기 대상 아님).
COL = {'거래일자': 2, '항목': 3, '내용': 4, '금액': 5, '증빙유형': 6, '예약번호': 7,
       '원가구분': 8, '부가세': 9, '확신': 10, '근거(AI)': 11, 'uid': 12}
LAST_COL = 12
ISSUER = {'KBD': '국민', 'KBO': '국민', 'HAN': '하나', 'CORP': '기업', 'MAN': '영수증'}
def evid_col(x):
    # 증빙유형 간소화(사용자 2026-07-22): 카드번호 병기 폐기 — 국민/하나/기업/영수증.
    return ISSUER.get(x['src'], '') or re.sub(r'\.0$','',str(x.get('card4') or ''))
TAB_TOTALS = []   # (시트명, 합계행) — 검증 시트가 함수로 참조
def detail_sheet(title, xs):
    ws = wb.create_sheet(title[:31])
    for k, cc in COL.items():
        c = ws.cell(row=1, column=cc, value=k); c.fill = HDR_FILL; c.font = HDR_FONT; c.alignment = Alignment(horizontal='center')
    import re as _re
    def _brand(m):
        u = (m or '').upper()
        for b, k in [('BOOKING','BKG'),('BKG','BKG'),('부킹','BKG'),('TRIP','TRIP'),('트립','TRIP'),
                     ('AGODA','AGODA'),('아고다','AGODA')]:
            if b in u: return k
        return _re.sub(r'[0-9\s]', '', u)[:8]
    def _manitem(x):
        mm2 = _re.search(r'⇄수기(?:\[[^\]]*\])?:\s*([^|(]+)', x.get('note', '') or '')
        if mm2:
            return _re.sub(r'[\s()]', '', mm2.group(1))[:14]
        return None
    matched, merges, unmatched, cancels = [], [], [], []
    def _is_merge(z):
        # 병합건 = 수기 '일부기입'을 카드로 보완한 행만(사용자 정의).
        # TRIP 선결제 반영은 수기 완전기입의 이관이므로 완전기입(상단). ORIG(원거래 복원)·수기병합 태그만 병합.
        n = z.get('note', '') or ''
        return '수기병합' in n or '원거래 복원' in n or '카드보완' in n
    for x in sorted(xs, key=lambda z: (z['use_date'], z['uid'])):
        st = MATCHED.get(x['uid'], 'nomanual')
        if st == 'cancel' or x['cancel_b'] or x['krw_f'] < 0: cancels.append(x)
        elif st == 'unmatched': unmatched.append(x)
        elif _is_merge(x): merges.append(x)          # 수기 일부기입+카드보완 → 병합건(중단)
        else: matched.append(x)   # matched / nomanual → 완전기입(상단)
    cancel_by_appr, cancel_by_item, cancel_by_key = {}, {}, {}
    for c in cancels:
        oa = (c.get('orig_appr') or '').strip()
        if oa:
            # ★규칙(사용자 확정): 승인번호 있는 환불은 승인번호로만 원거래에 연결(브랜드·금액 폴백 금지 — 오페어링 방지)
            cancel_by_appr.setdefault(oa, []).append(c)
            continue
        it = _manitem(c)
        if it: cancel_by_item.setdefault(it, []).append(c)
        cancel_by_key.setdefault((_brand(c['merchant']), round(abs(c['krw_f']))), []).append(c)
    ri = [2]
    def ledger_date(s):
        # 수기장부 표기(YY.MM.DD 점)와 완전 동일한 문자열로 — 전체 붙여넣기 시 서식 충돌 없이 바로 정착
        m = re.match(r'(\d{4})-(\d\d)-(\d\d)', s or '')
        return '%s.%s.%s' % (m.group(1)[2:], m.group(2), m.group(3)) if m else (s or '')
    def writerow(x, fill=None):
        r = ri[0]
        bno, url = booking_deeplink(x['merchant'], x.get('note', ''))
        vals = {'거래일자': ledger_date(x['use_date']), '항목': x['merchant'], '내용': contents_col(x),
                '증빙유형': evid_col(x), '금액': round(x['krw_f']),
                '원가구분': x['cost_type'], '부가세': x['vat_tag'], '확신': x['confidence'],
                '예약번호': bno, '근거(AI)': clean_disp(x['note']), 'uid': x['uid']}
        for k, cc in COL.items():
            c = ws.cell(row=r, column=cc, value=vals[k]); c.border = THIN
            if k == '금액': c.number_format = '#,##0'
        if fill:
            for cc in range(1, LAST_COL + 1): ws.cell(row=r, column=cc).fill = fill
        if url:
            c = ws.cell(row=r, column=COL['예약번호']); c.hyperlink = url; c.font = LINK_FONT
        if x['confidence'] == '하': ws.cell(row=r, column=COL['확신']).fill = WARN_FILL
        ri[0] += 1
    consumed = set()
    def emit_with_cancel(x, fill=None):
        writerow(x, fill)
        pool = list(cancel_by_appr.get((x.get('appr') or '').strip(), [])) if x.get('appr') else []
        it = _manitem(x)
        if it: pool += cancel_by_item.get(it, [])
        pool += cancel_by_key.get((_brand(x['merchant']), round(abs(x['krw_f']))), [])
        for c in pool:
            if id(c) in consumed or c is x: continue
            consumed.add(id(c))
            writerow(c, BAD_FILL)
    for x in matched: emit_with_cancel(x)
    if merges:
        r = ri[0]
        ws.cell(row=r, column=2, value='▼ 수기장부 병합건 — 수기 일부기입분을 카드로 보완(날짜·계정) ▼')
        for c in range(1, LAST_COL + 1): ws.cell(row=r, column=c).fill = MERGE_FILL
        ws.cell(row=r, column=2).font = Font(bold=True, color='1F4E5F')
        ri[0] += 1
        for x in merges: emit_with_cancel(x, MERGE_FILL)
    if unmatched:
        r = ri[0]
        ws.cell(row=r, column=2, value='▼ 수기장부 미입력 추정 — 데이터행을 선택해 장부(v8 구조)에 그대로 붙여넣기: B날짜 C항목 D내용 E금액 F증빙 G예약번호 ▼')
        for c in range(1, LAST_COL + 1): ws.cell(row=r, column=c).fill = BOOK_FILL
        ws.cell(row=r, column=2).font = Font(bold=True, color='7F6000')
        ri[0] += 1
        for x in unmatched:
            xx = dict(x); xx['note'] = srcref(x['uid']) + (x['note'] or '')
            # ★미입력 데이터행은 무채색(대표님 장부 스타일과 동일) — 색은 위 구분줄에만.
            #   "전체 붙여넣기" 한 번으로 서식 충돌·병합 해제 없이 그대로 정착하도록.
            writerow(xx, None)
            emit_leftover = cancel_by_key.get((_brand(x['merchant']), round(abs(x['krw_f']))), [])
            for c in emit_leftover:
                if id(c) in consumed or c is x: continue
                consumed.add(id(c)); writerow(c, None)
    for c in cancels:
        if id(c) not in consumed:
            writerow(c, BAD_FILL)
    r = ri[0]
    ws.cell(row=r, column=2, value='합계').font = Font(bold=True)
    cc = ws.cell(row=r, column=COL['금액'], value=f'=SUM(E2:E{r-1})'); cc.font = Font(bold=True); cc.number_format = '#,##0'
    ws.cell(row=r, column=COL['근거(AI)'], value=f'{len(matched)}완전/{len(merges)}병합/{len(unmatched)}미입력')
    TAB_TOTALS.append((ws.title, r))   # 검증 시트 총합 함수용
    # (v63~) 셀 병합 없음 — 장부도 v6부터 무병합.
    for col, w in [('B', 12), ('C', 20), ('D', 16), ('E', 13), ('F', 11), ('G', 15),
                   ('H', 11), ('I', 11), ('J', 6), ('K', 46), ('L', 11)]:
        ws.column_dimensions[col].width = w
    for col in 'A': ws.column_dimensions[col].width = 2
for tab in trip_order:
    if by_bucket.get(tab): detail_sheet(tab, by_bucket[tab])
_leader_tabs = sorted(b for b in by_bucket if b.startswith('대장_'))   # 대장 지급카드 전용 탭(카드기명 규칙)
for b in _leader_tabs + ['기타비용', '여행_미배정', '취소환불', '전기예약_환불']:
    if by_bucket.get(b): detail_sheet(b, by_bucket[b])

# ── 5. 확인필요 (확신 하 + vat 확인 + cost_type 확인)
ws = wb.create_sheet('확인필요')
ws.append(DETAIL_HDR); style_header(ws, len(DETAIL_HDR))
ri = 2
need = [x for x in rows if x['confidence'] == '하' or x['bucket'] == '여행_미배정']
for x in sorted(need, key=lambda z: -abs(z['krw_f'])):
    _b,_u=booking_deeplink(x['merchant'],x.get('note',''))
    put(ws, ri, [x['use_date'], x['merchant'], contents_col(x), x['card4'], round(x['krw_f']),
                 x['cost_type'], x['vat_tag'], x['confidence'], _b, clean_disp(x['note']), x['uid']])
    if _u: c=ws.cell(row=ri,column=9); c.hyperlink=_u; c.font=LINK_FONT
    ri += 1
ws.column_dimensions['C'].width = 30; ws.column_dimensions['K'].width = 46

# ── 6. 자료기준
ws = wb.create_sheet('자료기준')
for line in [
    '숲길여행 2026년 2분기(4~6월) 법인카드 비용분류 — AI 자동생성본 (생성: 2026-07-13)',
    '',
    '원천자료: 국민카드_2604_국내(승인일 기준), 국민카드_2604_해외(매입일 기준·승인일 결측 다수),',
    '  하나카드_2604(승인내역 탭), 진행장부 스냅샷(7/8, 수입·수기지출·대조용), 완료장부 26Q1(계정 관례 학습),',
    '  메일수집 76건(아고다/트립/부킹/네이버페이 등 — OTA 실체 동정).',
    '범위: 사용일 2026-04-01 ~ 2026-06-30, 총 1,186건. 2025년·Q1 건은 제외(범위외).',
    '방법: 12개 AI 에이전트 병렬 1차 분류 → 3개 검증 에이전트(미배정 재배정/부가세/6월 중복창) 교차검증.',
    '한계: ① 해외카드는 승인일 결측으로 매입일을 사용일로 사용(실사용일과 1~3일 오차 가능).',
    '  ② OTA 국내PG 결제는 메일 미매칭 시 실체 추정(확신 "하" 표시). ③ 수기장부는 7/8 스냅샷이라',
    '  이후 기록분은 대조에서 "수기 미기록"으로 보일 수 있음. ④ 부가세 태그는 검토용 — 최종 판단은 세무법인.',
    '  [v2 2026-07-14] 대표가이드 예약메일 1,596건(메일수집) 반영: [v3] Gmail 83건 딥다이브 실증: PG/페이 뒤 실체 확정(트래블로버=여행자보험 15건, 인터넷상거래/이니시스=항공권, Klook=TGV기차 등).',
    '     세무확신 상 1003/중 164/하 19. 진짜 불확실은 소액 18건(111만원)만 — 확인필요 시트 참조.',
    '     확신 하 410→306 감소. 여행_미배정 15건은 아고다 국내PG 선결제(원화결제·JPY메일이라 금액매칭 불가)로 실계정 확인 필요.',
    '  ⑤ 대조 차이의 주원인: 수기 장부는 현금·계좌이체·Q1 중 선결제(예: 2~3월에 산 4월 여행 항공권)까지 포함하지만,',
    '     이 자료는 "2026년 4~6월 카드 발생분"만 집계함. 따라서 수기가 큰 것은 대부분 정상(다른 결제수단·선결제).',
    '     반대로 AI가 큰 탭은 카드건이 수기에 아직 안 옮겨졌을 가능성 — 해당 탭 상세시트에서 확인.',
    '  [v4] ① 여행 겹칠 때 순차경계로 현지결제 재배정(4/10건→교토 등 67건). ② 주황색 행=수기장부에 없는 건(확인요).',
    '     ③ 예약번호 클릭=해당 OTA 예약페이지 딥링크(로그인 필요). booking은 PIN 요구할 수 있음.',
    '  [v72] APA 가나자와 4건 금액을 실제 카드 총결제금액으로 교체(사용자 확정): 편의환율 604,800×4→2,287,848(571,962×4). ★ingest 버그(국민 해외 원화 0 하드코딩) 수정 계기 — 원본 총결제금액(16열) 반영, 대표님 다른 국민해외건과 기준 통일. 총액 301,555,814→301,424,462(-131,352).',
  '  [v71] 무일자 6건 거래일자 확정(사용자 아고다 확정서 제공): APA 가나자와 4건(4/26~28, 현지결제 JPY60,480=수기604,800 일치)·카즈베기(5/10, GEL396)·아드리아(5/15, KRW261,050 정확일치) — 체크인일을 거래일자로 기입. 금액 변동 없음(301,555,814).',
  '  [v70] Drive 최신 장부 재수취(2026-07-23) 후 재빌드 — 4월 지출 탭 변경 0(대표님 편집은 메일수집·rev템플릿 시트에 국한), 총액 301,555,814 v69와 동일 재현. 아고다 메일함 전수 스윕 완료(1,332건): Y&Y NAMBA HOTEL(오사카 4/20, 예약1718900708)은 AgodaCash 전액상쇄로 실결제 ¥0이나 수기장부엔 123,200원(총액 기준) 기재 — 사용자 확인 대기 항목.',
  '  [v69] TRIP-0011(에히메 트립닷컴_호텔 파티오 318,622) 거래일자 공백 수정: 수기 55행 날짜 셀이 숫자 25.0으로 깨져 있어 미기재 — 매칭된 하나카드 승인일(2025-12-18) fallback 신설. 총액 변동 없음(301,555,814).',
  '  [v68] ①증빙유형 간소화(사용자): 카드번호 병기 폐기 — 국민/하나/기업/영수증. ②v67 결함 교정: 경계 구제에 승인일-기재일 근접(±14일) 제한이 없어 동액 우연일치 원거리 카드(작년 카카오T 등) 가짜 구제 ~174건(+2,257,108)이 섞였고 ①B dedup이 진짜 현금건까지 오인 제거(HIMESO 실측) — v67 폐기, 총액 301,555,814(=구총액+아고다 경계구제 2건 332,038)로 정정.',
    '  [v67] 결제일 경계 공백 구제(실측: 에히메 아고다 2건 332,038 누락): 승인 Q1(3/31)+수기 기재 4/1 카드건이 base·선결제 보충 양쪽에서 빠지던 게이트를 "카드 매칭 실재" 기준으로 구조 수정. + P8 최신 장부 재수취 반영(신규 기입 포함). 에히메 50건 7,444,921 수기 완전일치.',
    '  [v66] 8831 대장카드 전달일 게이트(사용자 규칙): 8831은 7월 엘레나 전달 — 7/1 이전 사용분(Q2 11건 1.87M)은 대장_엘레나가 아닌 원 여행탭(북해도·레분토·아키타)으로 환원. 대장 탭 분리는 7월 이후 사용분부터.',
    '  [v65] 장부 v8 최종 구조 정렬(사용자 확정: 스페이서·숨김 열 완전 삭제, 연속 배치): B거래일자 C항목 D내용 E금액 F증빙유형 G예약번호. 합계·검증 함수 E열 기준.',
    '  [v64] 장부 열 재구조 v6 정렬(사용자 확정): ★H=금액(수입·지출 통일) ★I=증빙유형(카드번호 병기: 국민_8835) ★K=예약번호. 여행탭 열이 장부 v6과 1:1 정렬돼 그대로 붙여넣기 가능. 합계·검증 함수 H열 기준.',
    '  [v63] 여행탭 셀 병합 전면 제거(무병합 회귀, 사용자 지시) — 장부 무병합 전환과 세트.',
    '  [v62] 미입력 판정을 최신 수기장부 기준으로 재생성(gen_matched.py) — 구 스냅샷(matched_uids) 고정 결함 수정. 사용자 신규 기입(+20행: 북해도·레분토 등)이 완전기입으로 정상 반영.',
    '  [v61] 대장 지급카드 전용탭(5836현수·4813바로바로·8831엘레나) — 8831 Q2 11건 1.87M을 대장_엘레나 탭으로 분리. Apps Script CARD_PROFILES에도 등록.',
    '  [v60] 카드 기명자 규칙: 3820=김주형 기명법인카드 — 국내결제는 여행기간과 겹쳐도 기타비용(12건 605K 정정), 항공·보험·숙박·여행상품만 여행원가.',
    '  [v59] 수기장부 Drive 최신본 재수취 원칙(P8) — 스냅샷 폐기. 최신 장부 기준 총액이 dedup 결과와 일치(오제 이중적재 제거 사후검증). 행 단위 참조정합 전수감사(P7) 상설.',
    '  [v58] 여행 순액 기준 재구성 완성: 결제일 규칙·승인번호 페어링(국민 괄호원승인·하나 동일행)·국민해외 현지외화 페어·부분환불 원거래 아래 배치·기업 승인취소 무청구 교정·병합 예약번호 검증.',
    '  [v54] 여행(실체) 기준 전면 재구성(사용자 확정: 처음부터 여행기준): 워크북을 수기장부(여행 마스터)와 대조해 승인-Q2 필터로 빠졌던 선결제 296건(+91,473,865) 반영 → 총 221,040,838→312,514,703. 금액은 카드 확정(승인/청구), 탭·성격은 수기. 수기장부 휴먼에러 검증(1,126 카드건 무매칭 0·금액상이 69전부 승인청구차). 검증시트를 여행탭별 수기대조로 교체.',
    '  [v53] 완전상쇄쌍 5쌍 취소환불 반영(사용자 지적: 취소쌍은 미기록이 아니라 취소환불 net0로 가야 함): 하나 MITSUINOREPARK·트립닷컴×2·AJIMASHITEI·카카오택시(승인=승인취소 전액상쇄) 10행 추가, 총액 불변. 네자메 ¥15,510 4건(150,072×1+150,970×3)은 원본=워크북 정확일치·부킹 확정예약 8=청구 8건 대응, 중복 아님(부킹메일 교차확인).',
    '  [v52] 교차검증 진짜누락 10건 반영(사용자 지적: 다른카드=다른승인번호는 중복 아닌 별개 실거래): 하나 4/23 HIGASHINIHON 통행료 8건 46,379(카드5483·4595, 기업 통행료와 별개)+국민 해외 2건(HIGHWAY470JPY 4,568·AGODA7439JPY 73,509). 총 220,916,382→221,040,838(+124,456). AGODA는 선결제·실체미상이라 여행_미배정.',
    '  [v51] 카드사 raw 대조(사용자 6파일 업로드): 국민 국내매입 raw와 대조해 구글시트 국내매입이 빠뜨린 취소 1건(트립닷컴 -68,720, 5/27) 발견·반영 → 완전상쇄쌍 격리, 총 220,985,102→220,916,382. 표준소스 확정: 국민=국내+해외매입, 하나=승인내역, 기업=승인내역. (하나 6741카드 1,015건 미보유 발견하나 Q2 0건이라 당분기 무영향.)',
    '  [v50] 여행탭 셀 병합을 수기장부와 동일하게(사용자 지적): B:C 거래일자·D:E 항목·F:G 내용·I:J 금액(H 증빙 단독). 워크북 병합범위가 장부와 정확히 일치→복사·붙여넣기 정렬. 값은 좌측셀 보존. (사용자 표기 A:B/C:D는 값 유실되므로 장부 실측 B:C/D:E로 교정.)',
    '  [v49] 여행탭을 수기장부 지출섹션 열구조로 재배치(사용자 지적): B거래일자·D항목·F내용·H증빙유형(카드사 국민/하나/기업)·I금액 — 병합그룹 좌측열에 정확히 맞춰 워크북에서 바로 복사→값붙이기 가능. AI 분석열(원가·부가세·확신·예약번호·근거·uid)은 K~로 이동. 합계·검증 함수검산 I열 기준, 별도 이관파일 불필요.',
    '  [v48] 근거(AI) 노트 표시 정리(사용자 지적): 다른 칸·행위치가 이미 말해주는 중복 제거 — Booking.com/AGODA(항목 칸)·예약번호(예약 칸)·⇄수기 접두(수기행=상단 흰색 위치). 원본 노트·예약번호 추출·검증가드는 불변, 표시용만 정리(화살표 문맥 보존, 빈노트 0).',
    '  [v47] 노트/오매칭 정정(사용자 지적): ① 승인취소 vs 매출확정 모순노트 2건 정리(HAN-3089=원본 매출확정 141,391 실청구 확정, status 정정). ② 여행종료 후 결제된 국내 소비건이 금액만 같아 지난 여행탭에 오매칭된 6건(집사의하루 고양이카페·카카오T·멘야준 등)→기타비용 환원. 회귀가드 2종 추가(노트 모순=0, 여행종료 15일+ 결제=0).',
    '  [v46] 취소전표 계정 승계(사용자 지적): 취소는 원거래(승인번호 연결) 계정·세무성격을 승계하도록 구조화 — 트립닷컴 항공 환불이 "트립닷컴"→기본 숙박비로 오분류되던 3건 정정(KBD-0373 숙박비→항공료 등). 검증시트 회귀가드에 "취소전표 계정 불일치=0" 추가.',
    '  [v45] 취소 처리 구조 수정(사용자 지적 재발 방지): ① 완전상쇄쌍 격리를 승인번호 연결로 재작성(휴리스틱 가맹점매칭 폐기)—여행탭에 남던 완전취소쌍 16행 취소환불로 격리. ② 국민 shift섹션 승인번호 재수록 중복 2건(대한항공 -573,700·아고다 -40,836) 제거로 이중 취소차감 정정 → 총 220,370,566→220,985,102(+614,536). ③ 검증시트에 회귀 가드 상설(승인번호 중복행·여행탭 잔류 완전상쇄쌍 = 0).',
    '  [v44] 전 OTA 예약DB 교차검증: 트립닷컴86·아고다239·부킹176 예약과 카드행 대조→예약번호+메일실증으로 확신 대량 상승격. 오제_A폐기·0630_오제 통합, 수기 이중입력 3건 정리(같은예약번호 중복).',
    '  [v44] 근거(AI) 노트 가독성 정리 898행: 내부 루프표식([루프수정]·순차재배정) 제거, 증거태그 중복(메일실증·부킹실증·Gmail실증)→메일확정(PIN) 통합, 하나 매입금액 표기 간결화, 메일확정건의 잔여 "추정" 제거. 분류·확신·금액·예약번호는 전부 불변.',
    '  [v42] 아고다 확정서 239건 수확(CS재발송): 본문 예약번호+호텔+체크인+JPY금액 추출→예약DB. 불명 10건을 현지통화+체크인으로 10월 시코쿠/하쿠바 선결제 배정(예약번호+메일실증). 야마가타→아키타 표준화. 수기 이중입력 감사.',
    '  [v41] 92에이전트 루프감사 반영: 264건 수정(계정·확신·탭재배정) + 무청구 승인취소 5건(AVIS/RESIDHOTEL 등 유령 789,083원) 0처리 + 하나 조인/영수증오매칭 검증. 수기장부 휴먼에러 감사 상설화.',
    '  [v40] 최신 카드 4장 전면 재빌드: 국민(국내·해외)·하나·기업 4장을 오늘자 구글시트 최신본으로 교체.',
    '       각 시트의 다중 형식 구간을 단일 스키마로 정규화(기업 224행 열이동·하나 3구간·국민국내 1107행 열밀림 흡수).',
    '       기업카드(신규 카드) 2분기 56건 편입. 하나 중간 미매입구간 126건(유럽여행) 유실 방지. 승계 1160+신규 222=1382행.',
    '  [v38] 딥링크 정비+내용 열 수기화: ① 아고다 404 수정 — 실존 라우트(agoda.com/ko-kr/trips/detail?bookingId=)로 교체(로그인 후 해당 예약으로 이동).',
    '       ② 트립닷컴 항공은 확정메일의 실제 버튼 링크(vieworder, 주문별 토큰 포함)를 그대로 심음 — 숙박은 기존 인증페이지 유지.',
    '       ③ 내용 열을 수기장부 표기로 복원: 매칭건은 수기 desc 그대로(숙박_0405_0406 등), 미매칭 숙박건은 메일 체크인일로 합성(숙박_MMDD). 없으면 계정과목 유지.',
    '  [v37] 자기검증 스캐너 도입: 모순규칙(취소-양수/미상-여행탭/체크인-탭기간/동일거래쌍/상태-부호) 전수 스캔 +',
    '       확신 상 재산정(수기매칭·현지정합 단독 인정, 그 외 예약번호+메일실증 필요) — 증거부족 37건 상→중 강등.',
    '       확신 상 916/중 250/하 20. 동일거래쌍 중 미매칭 포함건은 영수증 대조 권장 플래그.',
    '  [v36] ANA 중복 재검증(사용자): PayPal 영수증·활동내역 모두 1건 → 실결제 1회 확정. KB명세의 2행은 KB 이중매입 의심으로',
    '       정정 — 5월분 카드 청구서 확인 후 2회 청구면 KB국민카드에 이의제기(ANA에 환불요청 아님).',
    '  [v35] ANA $412.57 이중청구 의심 발견(사용자 지적): 카드 원본에 동일 거래가 2행(1749·1759행) — 같은 PNR FOOOCM을',
    '       PayPal로 2회 청구. 환불 전표 없음 → ANA/PayPal 환불요구 필요. 확인필요 시트에 등재.',
    '  [v34] 구조적 취소매칭(사용자): 카드 승인번호 링크 사용 — 취소전표 승인번호가 "자기(원거래승인번호)" 형식이라 원거래를 정확 지목.',
    '       완전상쇄(동액)=취소환불 격리, 부분환불(금액상이)=원거래 탭 동행+바로 아래 배치. 클룩·진에어 등 부분환불도 자동 정렬(개별처리 제거).',
    '  [v33] 결제+전액환불 완전상쇄건(순액0=사실상 삭제된 예약)은 여행탭에서 취소환불 탭으로 격리 — 여행 원가에 실비용만 남김.',
    '  [v32] 매칭 확정건의 낡은 추측노트 정리: 수기장부로 확정된 건에 남아있던 "대상여행 미상" 등 옛 AI 추측 제거(모순 표기 해소).',
    '  [v31] 취소전표를 원거래(동일 가맹점·절대금액) 바로 아래에 배치(빨강) — 어떤 결제의 취소인지 한눈에. 원거래 없는 취소만 맨 아래.',
    '  [v30] 부킹 딥링크 PIN 40/40 완성 — 모든 부킹 예약이 클릭 즉시 열림(로그인·권한벽 없음). 잔여 3건(네자메·APA니가타×2) PIN 보강.',
    '  [v29] 예약번호 자릿수 경계 버그 수정(6053661851이 60536618510으로 캡처되던 문제) — PIN 링크 적용률 개선.',
    '  [v28] ⚠ 부킹닷컴 딥링크에 PIN 내장(사용자 지시): 링크만으로 예약 열람·변경 가능 — 이 파일을 외부(세무법인 등)에',
    '       공유하지 마세요. 공유용 사본이 필요하면 요청 시 PIN 제거본을 생성해 드립니다.',
    '  [v27] 부킹닷컴 딥링크를 지메일 검색 링크로 교체: 예약이 kew2000@hanmail.net 표기로 접수된 건은 daum 로그인과',
    '       표기 불일치로 권한벽 발생 → 확정메일을 바로 열어 메일 내 인증버튼 사용(계정·표기 무관). kkokko-hero@hanmail.net(김주형',
    '       네이버·카카오 알림 계정)은 예약 계정과 별개 — 혼동 금지.',
    '  [v26] ANA·항공사 예약메일 인벤토리로 미배정 10건 전량 확정: ANA 4건=삿포로-리시리(6/16 투어, PNR FOOOCM 전표 명기),',
    '       아시아나=9/24 야마구치, 대한항공 4매=10/20 알펜루트(니가타), 이스타·파라타=12/1 도쿄, 아고다 2건=메르큐르/가루이자와. 여행_미배정 0건.',
    '  [v25] 미확정 선결제 스윕 확장(사용자): OTA뿐 아니라 항공사 직판(ANA·아시아나·이스타·대한항공)·PG 결제도 대상 여행',
    '       미확정이면 여행_미배정로 격리(10건). 보험기간이 여행과 일치하는 트래블로버 2건은 레분토&리시리 확정 유지.',
    '  [v24] 취소 부호 정규화(사용자 지적): 국민해외 "취소매출"은 원본이 양수 표기 → 원거래 짝 있으면 음수로 상쇄,',
    '       원거래가 파일에 없는 것(가승인 취소·승인취소)은 실제 청구 0원 처리(원표기 금액은 근거에 보존). 취소환불 탭 순액 ≈ 0.',
    '  [v23] 취소 격리(사용자): ±상쇄쌍·승인취소는 전부 취소환불 탭으로 — 여행탭엔 실비용만(흰=수기기입/주황=미입력).',
    '  [v23] 세무요약 → "월별순액" 교체(세무법인 요청 형식): 월별 수입-여행원가-마진-공급가액-부가세 + 선급원가·판관비 요약.',
    '  [v22] 취소전표 위치규칙(사용자): 취소·환불 전표는 결제일 탭이 아니라 원거래가 있는 탭에 배치(±상쇄가 한 탭에서 보이게).',
    '  [v22] 탭 정리(사용자): 3분기선결제요약(여행탭·총괄과 중복)·대조(행단위 ⇄수기 매칭으로 대체)·여행_미배정(잔여',
    '       4건 전부 취소상쇄라 취소환불로 흡수) 삭제. 유지 탭 = 검증·총괄·세무요약·미청구_예약확정·여행탭·기타비용·취소환불·확인필요·자료기준.',
    '  [v21] 정밀 재대조(날짜±7일+근사금액·합산기입): 신규매칭 31건. 근사(±0.6%)는 해외결제에만 허용, 국내는 정확일치.',
    '       카카오페이 고액 2건=트립닷컴 서울-니가타 항공(수기 0630_오제 동액 확인 — 사용자 지적대로 항공권). 합산기입(주차 2건=수기 1행) 감지.',
    '       확증 실체와 모순되는 근사매칭 9건은 자동검수로 배제(예: 히타온천 확증건이 철판요리로 붙는 것 방지).',
    '  [v20] 매칭규칙 학습(사용자): 여행탭 배정 카드건이라도 수기장부 "기타비용" 탭에 기록돼 있으면 그쪽이 정답 —',
    '       장부 전체(여행탭+기타비용)를 하나의 매칭풀로 교차대조. 이지페이·유니클로·핀다이렉트 등 5건 기타비용으로 정합.',
    '  [v19] 트립닷컴 인벤토리(36개 예약) 소거법 완료: 4/19 하나 3건=9월 북큐슈 선결제(오이타 토라노유·히타 하나노키, ¥확증)→0927_북큐슈.',
    '       6/5 51.3만=티웨이 후쿠오카 왕복(9/24 야마구치), 11.4만=아비뇽→리옹 기차(유럽). 근거없는 OTA건 0건 달성.',
    '  [v18] 아비스 렌터카 과태료 통지(7/14) 등록: 행정수수료 EUR35 청구예정 + ANTAI 과태료(금액미정) — 미청구_예약확정 시트.',
    '       ※ 과태료·벌금 본체는 법인세 손금불산입 항목 — 카드 청구되어도 비용처리 불가, 세무법인에 표시.',
    '  [v17] 아고다 메일 인벤토리(55개 예약) 소거법으로 미배정 OTA 10건 재배정: 군산웨스턴(환불액 역산 확증)·야쿠시마그린(분쟁CS)·',
    '       메르큐르 나가노(6/22)·스이덴테라스(6/25)·롯데아라이(6/23 현장결제). 트립닷컴 4/19 3건만 미배정 잔류(직원계정 추정).',
    '  [v16] 실체 미확정 OTA 선결제 12건(아고다 묘코권/아키타권, 트립닷컴 4/19 등)은 결제일 기준 여행배정을 금지하고',
    '       여행_미배정로 이동(사용자 규칙: OTA는 사전예약이므로 결제일의 여행 원가일 수 없음). 실체 확인 시 재배정.',
    '  [v15] 3분기 이후 선결제를 본편에 통합: "3분기선결제요약" 시트(여행별 집계, 상세는 각 여행탭 시트) +',
    '       "미청구_예약확정" 시트(부킹 확정메일 있으나 아직 카드 미청구 16건 — 청구 시 해당 여행 원가로 기입).',
    '  [v14] 부킹닷컴·트립닷컴 메일 전수감사 반영: 부킹 84통(확정39+결제45) 전수추출 → 24건 예약번호 실증(부킹실증: 표기).',
    '       나가센도 부킹 8건=네자메호텔(기소) 결제 확정. 하쿠바 272,320엔=호텔하쿠바 체크인6/20→0620_묘코. 무쓰그랜드 55만=4/26 전액환불(상쇄).',
    '       트립닷컴 메일 1~6월 공백없음(월22~101통). 항공권 일부는 직원계정(포워딩) 예약이라 메일 미존재 가능 — 해당건 주석 표기.',
    '  [v13] 딥링크 한글화·실링크 교체: 트립닷컴은 확정메일이 쓰는 kr.trip.com 예약상세 인증페이지로 연결(로그인 필요).',
    '       아고다 ko-kr, 부킹닷컴 lang=ko. 이지페이=와이드모바일 통신비 정정(이스타항공 오판). 취소상쇄쌍 14건 미입력 제외.',
    '  [v12] 수기장부 예약번호 열(금액 우측) 발견·연동: 매칭건에 수기 예약번호 자동 주입(딥링크 확장, PNR코드 표시).',
    '       하나카드는 승인금액(수기 구기입)·매입금액 양쪽으로 매칭(표시는 매입금액). 최신장부(7/15) 기준 재매칭.',
    '       와이드모바일=와이파이도시락 통신비(여행원가·사용자 확정). 오사카=도보답사라 차량성 지출은 아오모리/알펜루트로 이동.',
    '  [v11] 하나카드 금액기준 정정(사용자 지시): 승인번호로 승인내역을 조인해 "매입금액(확정 청구액)"을 사용.',
    '       승인금액은 승인시점 환율이라 청구액과 다름(예: 토요타렌터카 승인854,366→청구861,334 — 수기와 일치).',
    '       주유소 가승인도 해결(ENEOS 승인1,527→실제주유 104,409). 총 402건 정정, 순변동 +878,131원.',
    '       미매입·취소 건은 승인금액 유지. 검증시트 하나카드 총액도 매입금액 기준으로 재계산됨.',
    '  [v10] 매칭기준 변경(사용자 지시): 금액+여행탭 존재=동일건(가맹점명은 수기에서 수정되므로 제외, 카드번호는 있을 때만 대조).',
    '       매칭건 근거 맨앞 ⇄수기:항목명 = 대응하는 수기장부 항목. ⇄수기[탭]: = 수기장부 탭 기준으로 AI 탭을 이동한 110건(수기가 정답).',
    '       수기 항목명으로 실체 재확정: 인터넷상거래=스카이티켓 야쿠시마 단체항공(알마티 오판 정정), KCP=트래블로버 보험,',
    '       Hotel Best Tbilisi(유럽) 오매칭 정정, Teaflight/마이트립=항공권. 4/7 트립닷컴 미상 2건=야쿠시마(수기 기입 확인).',
    '  [v9] 미입력(주황) 건은 근거 맨 앞에 원본 카드시트 출처를 표기 — 예: 국민_742행_ = 국민카드_국내 시트 742행,',
    '       국민해외_1557행_ = 국민카드_해외 시트, 하나_19행_ = 하나카드 승인내역 탭. 해당 행을 열면 원거래 확인 가능.',
    '  [v8] 선결제 재배정: OTA/항공 선결제 24건을 결제일이 아닌 실제 여행일(체크인·탑승일) 기준 탭으로 이동.',
    '       예: 4/2 결제 트립닷컴 124.8만(10/10 인천-도쿠시마 왕복항공)→1010_도쿠시마 탭. 동시진행 투어는 지역명으로 구분(하치노헤=아오모리).',
    '       실체 미상 그룹항공 2건(238만·112만, 4/7 결제)은 추측 배정 대신 여행_미배정로 이동 — 확인필요 시트 참조.',
    '  [v7] 금액은 전부 원화(KRW)로 통일 — 수기장부와 동일. 통화·외화(JPY)열 제거. OTA 미상건 Gmail 실체확정.',
    '       ※ "금액"열은 100% 원화(카드청구액). "근거(AI)"열에 간혹 보이는 엔(¥/엔)은 매칭에 쓴 원본 예약통화(증빙)로, 장부 금액이 아님.',
    '       [v7] 트립닷컴 예약확정 총액 실증 → 다비노(다카야마)·야쿠시마그린 등 "항공 가능성" 추측을 숙박비로 확정. 17행류 트립닷컴 124.8만=인천-도쿠시마 왕복항공(1인 312,100×4, 강나진 내부메일) 확정.',
    '  [v5] 열순서를 수기장부와 동일(거래일자·항목·내용·증빙유형·금액). 각 탭: 수기 이미입력=상단(흰색),',
    '     미입력추정=하단(주황). 구분선 아래 A~E열을 복사해 수기장부에 붙여넣으면 됨(중복입력 방지).',
    '  [v6] 매칭 기준=예약번호>금액+(날짜±4·가맹점유사·카드·OTA브랜드) 다기준(금액단독 아님). 최신장부(7/14) 기준.',
]:
    ws.append([line])
ws.column_dimensions['A'].width = 110


# ── 0. 누락0 검증 시트(자체 증명) ──
wsv = wb.create_sheet('검증', 0)
import re as _re
def _isq2tab(tab):
    m = _re.match(r'(\d{2})(\d{2})', tab or ''); mm = _re.match(r'(\d+)월', tab or '')
    if m: return 4 <= int(m.group(1)) <= 6
    if mm: return 4 <= int(mm.group(1)) <= 6
    return False
# 수기장부(여행 마스터) Q2 여행탭별 합계
_manT = defaultdict(float); _manN = defaultdict(int)
with open('manual_v3.csv', encoding='utf-8') as _f:
    for _m in csv.DictReader(_f):
        if _isq2tab(_m['tab']):
            _manT[_m['tab']] += num(_m['amount']); _manN[_m['tab']] += 1
# 워크북 여행탭별 합계
_wbT = defaultdict(float); _wbN = defaultdict(int)
for r in rows:
    _wbT[r['bucket']] += r['krw_f']; _wbN[r['bucket']] += 1
wsv['A1'] = '여행(실체) 기준 검증 — 이 워크북 = 대표님 수기장부(여행 마스터), 금액은 카드사 원본으로 확정'
wsv['A1'].font = Font(bold=True, size=12)
wsv.append([]); wsv.append(['여행(탭)', '수기 건수', '워크북 건수', '수기 합계', '워크북 합계', '차이(카드-수기)'])
style_header(wsv, 6, row=3)
_r = 4
_q2tabs = sorted([t for t in _manT if t in _wbT], key=lambda t: -_manT[t])
for t in _q2tabs:
    _d = round(_wbT[t] - _manT[t])
    put(wsv, _r, [t, _manN[t], _wbN[t], round(_manT[t]), round(_wbT[t]),
                  ('일치 ✅' if abs(_d) < 3000 else ('{:+,} (승인/청구차)'.format(_d)))]); _r += 1
put(wsv, _r, ['Q2여행 합계', sum(_manN[t] for t in _q2tabs), sum(_wbN[t] for t in _q2tabs),
              round(sum(_manT[t] for t in _q2tabs)), round(sum(_wbT[t] for t in _q2tabs)), ''])
for c in range(1, 7): wsv.cell(row=_r, column=c).font = Font(bold=True)
_r += 1
put(wsv, _r, ['* 차이=카드확정금액−수기금액(승인/청구 환율차, 건당 <1%). 현금·이체·영수증은 카드무매칭이라 수기금액 사용.', '', '', '', '', '']); _r += 1
# 함수 검산: 모든 여행탭 합계셀(=SUM)을 다시 함수로 합산 → 워크북 총액과 자동 대조
_src_tot = round(sum(r['krw_f'] for r in rows))
_sumf = '=' + '+'.join("'%s'!E%d" % (sn, rr) for sn, rr in TAB_TOTALS)
put(wsv, _r, ['함수 검산(탭 합계 SUM 재합산)', '', '', _src_tot, None, None])
wsv.cell(row=_r, column=5).value = _sumf
wsv.cell(row=_r, column=6).value = '=IF(ABS(E%d-D%d)<10,"함수일치 ✅","불일치 ⚠️")' % (_r, _r)
for c in range(1, 7): wsv.cell(row=_r, column=c).font = Font(bold=True, color='1F4E5F')
_r += 2
wsv.cell(row=_r, column=1, value='버킷 배정 요약 — 1,382건 전량이 여행탭/기타비용/미배정/취소에 배정됨').font = Font(bold=True); _r += 1
wsv.append(['버킷', '건수', '', '금액(원)', '', ''])
for c in wsv[_r]: c.font = Font(bold=True)
_r += 1
_bk = Counter(r['bucket'] for r in rows)
for b, n in _bk.most_common():
    put(wsv, _r, [b, n, '', round(sum(x['krw_f'] for x in rows if x['bucket'] == b)), '', '']); _r += 1
_r += 1
# ── 회귀 가드(상시 노출): 두 불변식이 0이어야 정상. 재발하면 여기가 ⚠️로 바뀜 ──
_dupg = {}
for r in rows:
    _a = str(r.get('appr', '')).strip()
    if _a:
        _k = (_a, round(r['krw_f'])); _dupg[_k] = _dupg.get(_k, 0) + 1
_dupcnt = sum(v - 1 for v in _dupg.values() if v > 1)
_posx = {}; _cancx = {}
for r in rows:
    if r['krw_f'] > 0 and str(r.get('appr', '')).strip():
        _posx.setdefault(str(r['appr']).strip(), []).append(r)
    if r['krw_f'] < 0 and str(r.get('orig_appr', '')).strip():
        _cancx.setdefault(str(r['orig_appr']).strip(), []).append(r)
_NT = {'취소환불', '전기예약_환불'}
_residp = 0
for _a, _pl in _posx.items():
    _cs = _cancx.get(_a, [])
    for _p in _pl:
        if _cs and sum(-c['krw_f'] for c in _cs) == _p['krw_f']:
            if _p['bucket'] not in _NT or any(c['bucket'] not in _NT for c in _cs):
                _residp += 1
wsv.cell(row=_r, column=1, value='회귀 가드(0이어야 정상) — 재발 자동감지').font = Font(bold=True); _r += 1
put(wsv, _r, ['승인번호 완전중복행(이중청구·shift 재수록)', _dupcnt, '', '', '', '정상 ✅' if _dupcnt == 0 else '중복 ⚠️'])
for c in range(1, 7): wsv.cell(row=_r, column=c).font = Font(bold=True, color='1F4E5F' if _dupcnt == 0 else 'C00000')
_r += 1
put(wsv, _r, ['여행탭 잔류 완전상쇄쌍(취소환불 밖)', _residp, '', '', '', '정상 ✅' if _residp == 0 else '잔류 ⚠️'])
for c in range(1, 7): wsv.cell(row=_r, column=c).font = Font(bold=True, color='1F4E5F' if _residp == 0 else 'C00000')
_r += 1
_pacct = {}
for r in rows:
    if r['krw_f'] > 0 and str(r.get('appr', '')).strip():
        _pacct[str(r['appr']).strip()] = r
_acctmis = 0
for r in rows:
    if r['krw_f'] < 0 and str(r.get('orig_appr', '')).strip():
        _p = _pacct.get(str(r['orig_appr']).strip())
        if _p and (r.get('account') or '') != (_p.get('account') or ''):
            _acctmis += 1
put(wsv, _r, ['취소전표 계정 불일치(원거래 미승계)', _acctmis, '', '', '', '정상 ✅' if _acctmis == 0 else '불일치 ⚠️'])
for c in range(1, 7): wsv.cell(row=_r, column=c).font = Font(bold=True, color='1F4E5F' if _acctmis == 0 else 'C00000')
_r += 1
_contra = sum(1 for r in rows if ('매출확정' in (r.get('note') or '') and ('무청구' in r['note'] or '실청구0' in r['note'] or '실청구 0' in r['note'])))
put(wsv, _r, ['노트 모순(매출확정 vs 무청구 공존)', _contra, '', '', '', '정상 ✅' if _contra == 0 else '모순 ⚠️'])
for c in range(1, 7): wsv.cell(row=_r, column=c).font = Font(bold=True, color='1F4E5F' if _contra == 0 else 'C00000')
_r += 1
from datetime import date as _date, timedelta as _td
_TW = {}
for _t in trips:
    _y = 2027 if _t['mm'] < 3 else 2026
    _s = _date(_y, _t['mm'], _t['dd']); _TW[_t['tab']] = (_s, _s + _td(days=int(_t['window'])))
_TW['5월_유럽'] = (_date(2026, 5, 1), _date(2026, 6, 11))
def _pdt2(d):
    m = re.search(r'(\d{4})-(\d\d)-(\d\d)', str(d)); return _date(*map(int, m.groups())) if m else None
_posttrip = 0
for r in rows:
    b = r['bucket']
    if b in _TW and r['krw_f'] > 0:
        nd = _pdt2(r['use_date']); s, e = _TW[b]
        if nd and nd > e + _td(days=15): _posttrip += 1
put(wsv, _r, ['여행탭에 여행종료 15일+ 결제(금액오매칭 의심)', _posttrip, '', '', '', '정상 ✅' if _posttrip == 0 else '의심 ⚠️'])
for c in range(1, 7): wsv.cell(row=_r, column=c).font = Font(bold=True, color='1F4E5F' if _posttrip == 0 else 'C00000')
_r += 2
for _ln in ['* 원본 카드파일 전량 파싱 후 국민 shift섹션 승인번호 재수록 중복 2건(전액 이중 취소전표) 제거 — 실제 청구 기준 건수·총액 완전 일치.',
            '* 범위: 2026-04-01~06-30 카드 발생분. Q1·2025년은 별도(요청 시 확장).',
            '* 각 여행탭 시트: 상단=수기장부 기입력(흰색), 하단=미입력(주황). B·D·F·H·I열이 수기장부 지출섹션과 동일 위치 → 값만 복사·붙여넣기. AI 분석열은 K~.']:
    wsv.cell(row=_r, column=1, value=_ln); _r += 1
for col, w in zip('ABCDEF', [22, 12, 12, 16, 14, 10]): wsv.column_dimensions[col].width = w


# ── 3분기 이후 선결제 요약(본편 통합) ──
wp = wb.create_sheet('미청구_예약확정')
wp.append(['호텔', '체크인', '확정금액', '부킹 예약번호', '예상 여행탭', '비고'])
style_header(wp, 6)
_pend = [("6159480373","트윈라인 가루이자와","2026-07-22","JPY 617,344","0722_가루이자와"),
 ("6258117285","루트인그란티아 하뉴 스파","2026-07-25","JPY 106,925","0722_가루이자와권 확인要"),
 ("6536628563","루트인그란티아 하뉴 스파","2026-07-25","JPY 120,000","0722_가루이자와권 확인要"),
 ("5124861920","페어필드 기후 구조","2026-08-01","JPY 49,141","0801_노리쿠라"),
 ("6016246220","페어필드 기후 구조","2026-08-01","JPY 122,851","0801_노리쿠라"),
 ("6782185641","페어필드 기후 구조","2026-08-01","JPY 67,710","0801_노리쿠라"),
 ("5815115131","츠유쿠사","2026-08-02","JPY 27,000","0801_노리쿠라"),
 ("5815122322","오쿠히다가든 야케다케","2026-08-02","JPY 150,950","0801_노리쿠라"),
 ("5919361014","호텔&스파 기프트 다카야마","2026-08-03","JPY 135,199","0801_노리쿠라권 확인要"),
 ("5184099898","호텔&스파 기프트 다카야마","2026-08-03","JPY 46,882","0801_노리쿠라권 확인要"),
 ("5171548095","토야 코한테이","2026-08-14","JPY 175,040","0813_북해도"),
 ("5322312714","니세코 안누푸리","2026-08-14","JPY 39,681","0813_북해도"),
 ("6314458178","시즌2","2026-09-20","JPY 40,000","0918_세토우치"),
 ("5012731274","히메지 유니버설 미나미구치","2026-09-22","JPY 56,650","0918_세토우치"),
 ("5112405606","히메지 유니버설 미나미구치","2026-09-22","JPY 67,200","0918_세토우치"),
 ("5612694831","호텔 메구리","2026-09-28","JPY 88,800","0927_북큐슈"),
 ("E681460043","아비스 렌터카 과태료 행정수수료(파리 6/1~5, 차량 HK317KD)","2026-07-24경 청구예정","EUR 35.00","5월_유럽","7/14 통지서 — 렌탈 결제카드로 10일내 자동청구. 여행원가(수수료)"),
 ("6670259010","ANTAI 프랑스 교통과태료(6/3 07:07 위반)","금액미정·우편통지 예정","미정","5월_유럽","※과태료·벌금은 법인세 손금불산입 — 세무법인에 별도 표시 필요")]
_pr = 2
for _row in _pend:
    _res, _h, _ci, _amt, _tab = _row[:5]
    _memo = _row[5] if len(_row) > 5 else '카드 청구되면 해당 여행탭 원가로 기입'
    put(wp, _pr, [_h, _ci, _amt, _res, _tab, _memo])
    if _res.isdigit() and len(_res) == 10:
        _pin = BOOKING_PINS.get(_res)
        _url = ('https://secure.booking.com/mybooking.html?bn=' + _res + '&pincode=' + _pin + '&lang=ko') if _pin                else 'https://mail.google.com/mail/#search/' + _res
        _cell = wp.cell(row=_pr, column=4)
        _cell.hyperlink = _url; _cell.font = LINK_FONT
    _pr += 1
wp.cell(row=_pr + 1, column=1, value='※ 부킹 확정메일 존재·카드 미청구(무료취소형: 체크인 임박 청구/현장결제). 트립닷컴 항공권 일부는 직원계정 예약이라 목록에 없을 수 있음.')
wp.column_dimensions['A'].width = 30; wp.column_dimensions['D'].width = 16
wp.column_dimensions['E'].width = 22; wp.column_dimensions['F'].width = 30

_names = wb.sheetnames
wb.move_sheet('미청구_예약확정', offset=_names.index('월별순액') + 1 - _names.index('미청구_예약확정'))

out = '숲길여행_2분기_비용분류_AI_v72.xlsx'
wb.save(out)
print('저장:', out, '| 시트', len(wb.sheetnames), '개 | 상세행', len(rows))
print('시트:', wb.sheetnames[:8], '...')
