"""Allow-list guard: nothing but synthetic, vocabulary-bound values may enter a golden file.

Every input key must be listed in KEYS with a predicate for its value; an unknown key or an
unlisted value fails. Expected outputs get a defensive scan (no long digit runs, mail
addresses or links), because they are derived from the allow-listed inputs by the code.
"""
from __future__ import annotations

import json
import re

CATEGORY_INDUSTRIES = (
    '편의점', '슈퍼마켓', '슈퍼마켓.마트', '한식', '일식', '일식전문점', '중식', '양식', '휴게음식', '제과', '커피', '카페',
    '음식점', '일반음식점', '서양음식', '패스트푸드', '커피/음료전문점', '일반음식점 기타', '일식/생선회집',
    '제과점/아이스크림점', '휴게음식점', '패스트푸드점', '기타식음료품', '커피전문점', '제과.제빵', '서양식전문점',
    '호텔', '숙박', '숙박업', '여관', '모텔', '펜션', '콘도', '리조트', '레저용숙박업소', '호텔(특급외)',
    '택시', '버스', '철도', '지하철', '주유소', '주차장', '고속도로통행료', '시내버스', '고속.시외버스', '여객선',
    '항공사', '항공', '항공운송', '렌터카', '공연장/전시장', 'RF유료도로.터널',
    '인터넷상거래', '전자상거래', '통신판매', '결제대행', '의류', '미등록업종')

# Public business or brand names that the Python rules themselves contain, plus synthetic names.
FAMILY_MERCHANTS = (
    'toyota rent lease syn', 'Hotel Route Inn SYN', 'Live Max Resort SYN', 'hotel front inn syn', '파라타항공',
    '(주)파라타항공', '철도승차권발매', '국립세종수목원', 'toyoko inn syn', '토요코인 서울', 'SYN 국밥', 'SYN 칼국수',
    'SYN 김밥')
PUBLIC_MERCHANTS = FAMILY_MERCHANTS + (
    'AGODA', 'Agoda', 'agoda syn', 'AGODA_NICE-Agoda', 'TRIP.COM', '트립닷컴_이니시스', 'BOOKING.COM', 'KLOOK',
    '어드벤처코리아', 'FUKUTAKE FOUNDATION', 'AMAZON.COM', '카카오T SYN', '카카오택시 SYN', '카카오T 대리 SYN',
    'nottrip.commercial', 'SYN 도쿄 SHOP', 'SYN 오사카 SHOP')

ITEMS = {'', '식비', '숙박비', '항공료', '렌터카', '교통비', '입장료', '여행경비', '현지경비', '기타경비', '편의점', '주차비',
         '택시비', '대중교통', '통행료', '주유비', '분기 기타비용', '취소·환불', '항공권', '수동항목'}
TRIP_ID = re.compile(r'^(T-[A-Z0-9]+|quarter:20\d\d:[1-4]|refunds|unclassified|)$')
SYN_ID = re.compile(r'^(mail:)?syn-[a-z0-9-]+$')
SYN_APPROVAL = re.compile(r'^\s?SYN-[A-Za-z0-9-]+\s?$|^$')
DATE = re.compile(r'^(20(24|25|26|27)-\d\d-\d\d|1900-01-01|)$')
def _origins():
    from app import reconciliation as rc
    return {'', rc.OWNER_BOOKING_ORIGIN, rc.OWNER_AUTHORIZED_INFERENCE_ORIGIN, rc.OWNER_COUNTRY_EXCEPTION_ORIGIN,
            rc.PERIOD_OTA_ORIGIN, rc.OTA_MAIL_ORIGIN, rc.OTA_PORTAL_ORIGIN, rc.GUIDE_AIRFARE_ORIGIN,
            'automatic-trip-priority', 'history-recovery-20261003', 'syn-origin'}


ORIGINS = _origins()
TAILS = {'0001', '0002', '2042', '3820', '9999'}


def _one_of(*values):
    allowed = set(values)
    return lambda v: v in allowed


def _regex(pattern):
    compiled = re.compile(pattern)
    return lambda v: isinstance(v, str) and bool(compiled.match(v))


def _money(v):
    if v is None:
        return True
    if isinstance(v, int) and not isinstance(v, bool):
        return abs(v) < 10_000_000
    return isinstance(v, str) and bool(re.fullmatch(r'-?\d{1,7}', v))


def _merchant(v):
    if not isinstance(v, str):
        return False
    folded = {m.casefold() for m in PUBLIC_MERCHANTS}
    needles = _needles()
    text = v.casefold()
    return (text in folded or text == '*' or bool(re.fullmatch(r'syn[ a-z0-9]*', text))
            or any(text in (n, n + ' syn', 'syn' + n) for n in needles))


def _needles():
    from app.classify import CLEAR_PATTERNS
    return {needle.casefold() for needle, *_ in CLEAR_PATTERNS}


def _description_raw(v):
    return v == '' or (isinstance(v, str) and v.startswith('card-category:')
                       and v.removeprefix('card-category:') in CATEGORY_INDUSTRIES)


def _bool(v):
    return isinstance(v, bool) or v in (0, 1)


def _item(v):
    return v in ITEMS


def _trip(v):
    return isinstance(v, str) and bool(TRIP_ID.match(v))


KEYS = {
    # identity
    'transaction_id': _regex(r'^syn-[a-z0-9-]+$'), 'ota_event_id': _regex(r'^syn-[a-z0-9-]+$'),
    'source_digest': _regex(r'^syn-[a-z0-9-]+$'), 'source_hash': _regex(r'^syn-[a-z0-9-]+$'),
    'source_ids': _regex(r'^mail:syn-[a-z0-9-]+$'), 'duplicate_of': _regex(r'^syn-[a-z0-9-]+$'),
    'rule_id': _regex(r'^syn-rule-[a-z0-9]+$'), 'transaction_ids': _regex(r'^syn-[a-z0-9-]+$'),
    'overrides': _regex(r'^syn-[a-z0-9-]+$'),
    'approval_number': _regex(SYN_APPROVAL.pattern), 'original_approval_number': _regex(SYN_APPROVAL.pattern),
    'booking_ref': _regex(r'^SYN-BOOK-\d$'), 'authorization_number': _regex(r'^SYN-AUTH-\d$'),
    'authorization_scheme': _one_of('scheme-a'),
    # card and money
    'issuer': _one_of('SYN-BANK', 'SYN-BANK-B'), 'card_issuer': _one_of('SYN-BANK', 'SYN-BANK-B'),
    'card_tail': lambda v: v in TAILS, 'card_last4': lambda v: v is None or v in TAILS,
    'card_kind': _one_of('', '국내', '해외'),
    'amount_krw': _money, 'amount': _money, 'foreign_amount': lambda v: v == '' or _money(v),
    'foreign_currency': _one_of('', 'JPY', 'USD'), 'currency': _one_of('KRW'),
    'min': _money, 'max': _money, 'nets': _money,
    # dates
    'approval_date': _regex(DATE.pattern), 'posting_date': _regex(DATE.pattern),
    'paid_on': lambda v: v is None or bool(DATE.match(v)),
    'starts_on': _regex(DATE.pattern), 'ends_on': _regex(DATE.pattern),
    'start': _regex(DATE.pattern), 'end': _regex(DATE.pattern),
    'decided_at': lambda v: v is None or bool(re.fullmatch(r'2026-\d\d-\d\dT00:00:00Z', v)),
    # merchants
    'merchant': _merchant, 'merchant_normalized': _merchant, 'description_raw': _description_raw,
    'merchant_family': _one_of('agoda'), 'provider': _one_of('trip', 'agoda', 'booking', 'klook'),
    # vocabulary
    'transaction_direction': _one_of('purchase', 'cancellation', 'refund'),
    'transaction_kind': _one_of('승인', '취소', 'purchase'),
    'event_type': _one_of('charge', 'refund'),
    'evidence_status': _one_of('paid_verified', 'refund_verified', 'booking_only'),
    'payment_status': _one_of('paid', 'pending'), 'refund_status': _one_of('refunded'),
    'status': _one_of('active', 'MATCHED_AUTO'),
    'classification_state': _one_of('classified', 'needs_review'),
    'classification_source': _one_of('', 'ai_inference', 'code_inference', 'inference', 'user_decision', 'user_exception',
                                     'rule_conflict', 'refund_original'),
    'parse_error': _one_of('', 'AMOUNT_UNREADABLE'), 'conflict_reason': _one_of('', 'syn conflict'),
    'item': _item, 'confidence': _one_of('높음', '중간', '낮음'),
    'trip_id': _trip, 'display_tab_id': _trip, 'trip_ids': _trip,
    'display_key': _regex(r'^(SYN-[A-Z0-9]+|0909_제주)$'), 'target_code': _regex(r'^(SYN-[A-Z0-9]+|0909_제주)$'),
    'destination': _one_of('도쿄', '제주', '싱가포르', '오사카', '세토우치'),
    'travel_country': _one_of('JP'), 'origin': lambda v: v in ORIGINS,
    'confirmed_by': _one_of('automatic'),
    # fixed synthetic free text
    'description': _one_of('', 'syn', '합성 카페'), 'basis': _one_of('합성 근거', '합성 예약기간'),
    # flags and structure
    'version': _one_of(1), 'archived': _bool, 'residual_policy': _bool, 'reconsider': _bool, 'booking_period': _bool,
    'kind': _one_of('ota', 'refund'),
    # trips
    'op': _one_of('infer_trip', 'candidates', 'stay_trip', 'booking_trip', 'card3820', 'infer_item'),
    'tab_id': _trip, 'check_in': _regex(DATE.pattern), 'check_out': _regex(DATE.pattern),
    'service': _bool, 'deleted': _bool, 'enabled': _bool, 'valid': _bool, 'conflict': _bool, 'period_conflict': _bool,
    'original_id': _regex(r'^syn-[a-z0-9-]+$'), 'inferred': _bool,
    'link_state': _one_of('full', 'partial', 'excess', ''),
    'formal_link': _bool, 'flags': _one_of('PERIOD_ORDER', 'PERIOD_START_MISSING'), 'country': _one_of('JPN'),
}
CONTAINERS = {'cases', 'transaction', 'rules', 'conditions', 'effects', 'optional', 'prior_decision', 'amount_range',
              'date_or_service_period', 'inferred_assignment', 'scenario', 'rows', 'holds', 'exclusions', 'decisions',
              'ledger', 'boards', 'payload', 'trips', 'evidence', 'events', 'transactions', 'existing_links',
              'service_period', 'input', 'row', 'raw_row', 'completed_evidence', 'links'}
ID_MAPS = {'evidence', 'existing_links', 'links'}
ID_KEY = re.compile(r'^syn-[a-z0-9-]+$')
TRIP_KEY = re.compile(r'^T-[A-Z0-9]+$')
FORBIDDEN_TEXT = re.compile(r'\d{9,}|(?:\d{3,4}[- ]){2,}\d{3,4}|@|https?:|www\.', re.I)
ENVELOPE = {'case_id', 'area', 'command', 'note', 'covers', 'input', 'expected'}
SKIP_SCAN_KEYS = {'digest'}
HEX_DIGEST = re.compile(r'^(?:[a-z_-]+[:-])?[0-9a-f]{12,64}$')


class GoldenViolation(ValueError):
    pass


def validate_input(value, path='input', parent=None):
    """Raise GoldenViolation on the first value or key outside the allow-list."""
    if isinstance(value, dict):
        for key, item in value.items():
            if parent in ID_MAPS:
                if not ID_KEY.match(key):
                    raise GoldenViolation(f'{path}: map key {key!r} is not a synthetic id')
            elif parent == 'nets' or key == 'nets':
                pass
            elif key not in KEYS and key not in CONTAINERS:
                raise GoldenViolation(f'{path}: key {key!r} is not allowed')
            if key == 'nets':
                for trip, amount in item.items():
                    if not TRIP_KEY.match(trip) or not _money(amount):
                        raise GoldenViolation(f'{path}.nets: value not allowed')
                continue
            validate_input(item, f'{path}.{key}', key)
    elif isinstance(value, list):
        for item in value:
            validate_input(item, path + '[]', parent)
    else:
        check = KEYS.get(parent)
        if check is None:
            raise GoldenViolation(f'{path}: bare value under {parent!r}')
        if not check(value):
            raise GoldenViolation(f'{path}: value {value!r} is not allowed')


def scan_text(value, path='', skip=SKIP_SCAN_KEYS):
    """Defensive scan used on notes and expected outputs."""
    if isinstance(value, dict):
        for key, item in value.items():
            scan_text(key, path + '#key', skip)
            if key not in skip:
                scan_text(item, f'{path}.{key}', skip)
    elif isinstance(value, list):
        for item in value:
            scan_text(item, path + '[]', skip)
    elif isinstance(value, str) and not HEX_DIGEST.match(value) and FORBIDDEN_TEXT.search(value):
        raise GoldenViolation(f'{path}: text looks like customer data')


def validate_case(case):
    if set(case) != ENVELOPE:
        raise GoldenViolation(f'envelope keys differ: {sorted(set(case) ^ ENVELOPE)}')
    if not re.fullmatch(r'[a-z_]+-\d{3}', case['case_id']):
        raise GoldenViolation('case_id format')
    if not isinstance(case['note'], str) or len(case['note']) > 120:
        raise GoldenViolation('note too long')
    scan_text(case['note'], 'note')
    text = json.dumps(case['expected'], ensure_ascii=False, sort_keys=True)
    if not isinstance(case['covers'], list) or any(token not in text for token in case['covers']):
        raise GoldenViolation('a covered branch is missing from the expected output')
    validate_input(case['input'])
    scan_text(case['expected'], 'expected')


def validate_text(area, text):
    for number, line in enumerate(text.splitlines(), 1):
        case = json.loads(line)
        if case['area'] != area:
            raise GoldenViolation(f'{area}:{number}: wrong area')
        try:
            validate_case(case)
        except GoldenViolation as exc:
            raise GoldenViolation(f'{area}:{number}: {exc}') from None
