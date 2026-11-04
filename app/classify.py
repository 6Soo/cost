# -*- coding: utf-8 -*-
"""Decide what a transaction is, and record honestly when that is not knowable.

Order of precedence, highest first:

1. a previous decision on *this* transaction, which is never overwritten;
2. an active rule that matches;
3. an unambiguous item pattern.

Everything else is `needs_review`. That is the honest answer for a row with an
unreadable amount, no rule and no recognizable merchant, and it is the answer
that keeps a guess out of the ledger.

Three things this module will not do, each because the guess would move real
money:

* **It does not assign a trip from an OTA name.** `AGODA` is a merchant, not a
  trip. A rule or a pattern may set an *item*, and the caller may pass a trip
  that the web app has already validated against an authoritative schedule, but
  nothing here derives one from the merchant text.
* **It does not turn a card posting date into a service period.** A card date is
  when the charge happened, which is frequently not when the service happened.
* **It never overwrites a user's answer.** Only `save_decision` records one,
  and only a caller can call it.
"""

from __future__ import annotations

import re

from .db import decided_sql
from .normalize import normalize_merchant
from .reconciliation import (CONFIRMED_STATUSES, GUIDE_AIRFARE_ORIGIN, OTA_MAIL_ORIGIN, OTA_PORTAL_ORIGIN,
                             OWNER_AUTHORIZED_INFERENCE_ORIGIN, OWNER_BOOKING_ORIGIN, OWNER_COUNTRY_EXCEPTION_ORIGIN,
                             PERIOD_OTA_ORIGIN)
from .rules import rule_matches, is_booking_or_online
from .provisional_assignment import provisional_trip_decision

__all__ = ["classify_transaction", "classify_batch", "CLEAR_PATTERNS",
           "STATE_NEEDS_REVIEW", "STATE_CLASSIFIED"]


STATE_NEEDS_REVIEW = "needs_review"
STATE_CLASSIFIED = "classified"

# Only patterns that are unambiguous on their own. Each is (needle, item,
# description, tabs). A merchant that merely contains a word is not enough: the
# needle must be the merchant, or the merchant must start with it.
CLEAR_PATTERNS = (
    ("주차", "주차비", "주차장 이용", ("T-주차", "T-기타", "T-식비")),
    ("편의점", "편의점", "편의점 구매", ("T-식비",)),
    ("gs25", "편의점", "편의점 구매", ("T-식비",)),
    ("cu", "편의점", "편의점 구매", ("T-식비",)),
    ("세븐일레븐", "편의점", "편의점 구매", ("T-식비",)),
    ("seven-eleven", "편의점", "편의점 구매", ("T-식비",)),
    ("familymart", "편의점", "편의점 구매", ("T-식비",)),
    ("lawson", "편의점", "편의점 구매", ("T-식비",)),
    ("eneos-ss", "교통비", "주유소 이용", ("T-교통",)),
    ("eneos", "교통비", "주유소 이용", ("T-교통",)),
    ("idemitsu", "교통비", "주유소 이용", ("T-교통",)),
    ("taxi", "택시비", "택시 이용", ("T-교통",)),
    ("택시", "택시비", "택시 이용", ("T-교통",)),
    ("지하철", "대중교통", "교통비", ("T-교통",)),
    ("버스", "대중교통", "교통비", ("T-교통",)),
)

DEFAULT_TAB = 'unclassified'


def _pattern_for(merchant_normalized: str):
    for needle, item, description, tabs in CLEAR_PATTERNS:
        if merchant_normalized == needle or merchant_normalized.startswith(needle + " "):
            return item, description, tabs
    # 호텔 브랜드 뒤의 지점명, 띄어쓰기, 연결 기호는 달라도 같은 숙박업으로 본다.
    # 다른 사업체 이름에 브랜드 글자가 우연히 포함된 경우는 제외한다.
    name = re.sub(r'[\s._()\-·,]+', '', merchant_normalized.casefold())
    # 지역명이 붙은 해외 렌터카·호텔 브랜드는 업체의 용도를 분명히 알 수 있다.
    if re.match(r'^toyotarent(?:and)?lease[a-z0-9]*$', name):
        return '렌터카', '렌터카 이용', ('T-교통',)
    if re.match(r'^(?:hotelrouteinn|livemaxresort)[a-z0-9]*$', name):
        return '숙박비', '호텔 숙박', ('T-숙박',)
    if re.match(r'^(?:hotelfrontinn|motosuphoenixhotel|rakutenpayhotelsol|'
                r'twinlinehotel|washingtonhotelplaza|yumotokankohotel)', name):
        return '숙박비', '호텔 숙박', ('T-숙박',)
    if re.fullmatch(r'(?:주)?파라타항공', name):
        return '항공료', '항공권 구매', ('T-교통',)
    if name == '철도승차권발매':
        return '교통비', '철도 승차권', ('T-교통',)
    if name == '국립세종수목원':
        return '입장료', '수목원 이용', ('T-기타',)
    # 한글/영문 브랜드 및 지점 표기 차이를 흡수하되 다른 상호로 번지지 않게 한다.
    if re.fullmatch(
        r'(?:토요코인|토요코인호텔|toyokoinn|toyokoinnhotel)'
        r'(?:(?:서울|대구|부산|인천|대전|울산|광주|제주|수원|창원|강남|동성로|'
        r'daegu|seoul|busan|incheon|daejeon|ulsan|gwangju|jeju|suwon|changwon)'
        r'[가-힣a-z0-9]*)?', name,
    ):
        return '숙박비', '호텔 숙박', ('T-숙박',)
    if re.search(r'(?:국밥|칼국수|김밥|설렁탕|순대국|냉면|코다리)$', name):
        return '식비', '식당 식사', ('T-식비',)
    return None


def _verified_local_trip(transaction, item, trip_resolver):
    """현지 구매로 판단되는 항목만 검증된 여행 일정에 배정한다.

    숙박·교통편 예약 등의 카드 결제일은 이용일이 아닐 수 있으므로 제외한다.
    """
    if (not trip_resolver or not transaction.get('approval_date')
            or transaction.get('transaction_direction') != 'purchase'
            or item in ('숙박비', '항공료', '렌터카')
            or '승차권' in str(transaction.get('merchant') or '')
            or is_booking_or_online(transaction)):
        return ''
    from .rules import transaction_region
    country = transaction_region(transaction)
    return trip_resolver(transaction, country) if country else ''


def classify_transaction(transaction: dict, *, rules: list,
                         prior_decision: dict | None = None, trip_resolver=None,allow_defaults=True,
                         residual_policy=False) -> dict:
    """규칙 근거를 먼저 적용하고 사용자 허용 추론은 원본 거래에만 적용한다."""
    inferred = [r for r in rules if r.get('optional',{}).get('inferred_assignment')]
    regular = [r for r in rules if r not in inferred]
    verdict = _classify_transaction(transaction,rules=regular,prior_decision=prior_decision,
                                    trip_resolver=trip_resolver,allow_defaults=allow_defaults)
    from .trip_selection import is_fukutake_purchase, FUKUTAKE_BASIS
    if (trip_resolver and is_fukutake_purchase(transaction) and not prior_decision
            and verdict['classification_source'] not in ('rule_conflict', 'owner_booking', 'user_exception')
            and not any(r.get('origin') == OWNER_BOOKING_ORIGIN and rule_matches(r, transaction)[0]
                        for r in inferred)):
        target = trip_resolver(transaction, {'fukutake_setouchi': True})
        return dict(verdict, classification_state=STATE_CLASSIFIED,
                    classification_source='rule', classification_basis=FUKUTAKE_BASIS,
                    item='입장료', display_tab_id=target or 'unclassified',
                    trip_id=target, rule_id='owner-fukutake-next-setouchi')
    if residual_policy and not prior_decision:
        exception = _card3820_singapore(transaction, verdict, trip_resolver)
        if exception is not None:
            return exception
    if prior_decision or transaction.get('parse_error') or verdict['trip_id'] or verdict['classification_source']=='rule_conflict':
        return verdict
    matches = [r for r in inferred if rule_matches(r,transaction)[0]]
    if not matches:
        matching_rule = next((r for r in regular if r.get('rule_id') == verdict.get('rule_id')), None)
        if (verdict.get('classification_source') == 'rule' and matching_rule
                and not matching_rule.get('effects', {}).get('display_tab_id')):
            trip = _verified_local_trip(transaction, verdict.get('item', ''), trip_resolver)
            if trip:
                verdict = dict(verdict, trip_id=trip, display_tab_id=trip,
                               classification_basis=verdict['classification_basis'] + ' · 검증된 여행 기간의 현지 사용')
        if residual_policy:
            return _card3820_residual(transaction, verdict)
        return verdict
    # 사용자가 예약마다 고른 여행은 원본 거래의 자동 추론보다 앞선다.
    owned = [r for r in matches if r.get('origin') == OWNER_BOOKING_ORIGIN]
    if owned:
        matches = owned
    # 확정 예약 메일의 이용기간·항목은 과거 장부에서 복원한 추론보다 앞선다.
    booked = [r for r in matches if r.get('origin') == PERIOD_OTA_ORIGIN]
    if booked and not owned:
        matches = booked
    import json
    if len({json.dumps([r['effects'].get('item'),r['effects'].get('display_tab_id',''),
                        r['optional']['inferred_assignment']['trip_id']],sort_keys=True) for r in matches})!=1:
        return dict(verdict,classification_state=STATE_NEEDS_REVIEW,classification_source='inference_conflict',
                    classification_basis='추론 배정안이 서로 달라 확인이 필요합니다')
    rule=min(matches,key=lambda r:(-{'낮음':0,'중간':1,'높음':2}.get(
        r['optional']['inferred_assignment']['confidence'],0),r.get('rule_id','')))
    inference=rule['optional']['inferred_assignment']
    target=inference['trip_id']
    if target and (not trip_resolver or trip_resolver(transaction,{'inferred_trip_id':target,'origin':rule.get('origin','')})!=target):
        if rule.get('origin') == OWNER_BOOKING_ORIGIN:
            return dict(verdict,classification_state=STATE_NEEDS_REVIEW,
                        classification_basis='사용자가 고른 여행의 일정 원본을 다시 확인해야 합니다')
        # 근거가 맞지 않는 추론은 여행 없이 둔다. 다른 여행을 제시하지 않는다.
        return verdict
    exception=rule.get('origin')==OWNER_COUNTRY_EXCEPTION_ORIGIN
    if rule.get('origin')==GUIDE_AIRFARE_ORIGIN:
        return dict(classification_state=STATE_CLASSIFIED,classification_source='guide_airfare_evidence',
                    classification_basis='대장·가이드 항공권 근거 · '+inference['basis'],
                    item=rule['effects']['item'],description=rule['effects'].get('description',''),
                    display_tab_id=target,trip_id=target,rule_id=rule.get('rule_id',''))
    if rule.get('origin')==OWNER_BOOKING_ORIGIN:
        return dict(classification_state=STATE_CLASSIFIED,classification_source='owner_booking',
                    classification_basis='예약 배정 · '+inference['basis'],
                    item=rule['effects']['item'],description=rule['effects'].get('description',''),
                    display_tab_id=target,trip_id=target,rule_id=rule.get('rule_id',''))
    if rule.get('origin') == 'automatic-trip-priority':
        # 여행 후보만 보완한다. 현재 적용되는 업종/사용자 규칙의 항목과 설명은 유지한다.
        decision = provisional_trip_decision(target, basis=inference['basis'],
                                             confidence=inference['confidence'])
        return dict(verdict, classification_state=STATE_CLASSIFIED, classification_source='inference',
                    classification_basis='추론 배정 · 낮음 · ' + inference['basis'],
                    item=verdict.get('item') or rule['effects']['item'],
                    display_tab_id=target, trip_id=target, rule_id=rule.get('rule_id', ''),
                    provisional_assignment=decision)
    return dict(classification_state=STATE_CLASSIFIED,classification_source='user_exception' if exception else 'inference',
                classification_basis=('사용자 예외 · ' if exception else '추론 배정 · '+inference['confidence']+' · ')+inference['basis'],
                item=rule['effects']['item'],description=rule['effects'].get('description',''),
                display_tab_id=target or 'unclassified',trip_id=target,rule_id=rule.get('rule_id',''))


def _card3820_singapore(transaction, verdict, trip_resolver):
    """Explicit owner assignment for this period; no date-based travel inference."""
    day = transaction.get('approval_date') or transaction.get('posting_date') or ''
    if (transaction.get('card_tail') != '3820' or not isinstance(day, str)
            or not '2026-09-19' <= day <= '2026-09-24'
            or transaction.get('parse_error') or not trip_resolver
            or transaction.get('transaction_direction') != 'purchase'
            or any(marker in str(transaction.get('transaction_kind', '')).lower()
                   for marker in ('refund', 'cancel', '취소', '승인'))
            or type(transaction.get('amount_krw')) is not int or transaction['amount_krw'] <= 0):
        return None
    from datetime import date
    try:
        date.fromisoformat(day)
    except ValueError:
        return None
    target = trip_resolver(transaction, {'owner_card3820_singapore': True})
    if not target:
        return None
    return dict(verdict, classification_state=(STATE_NEEDS_REVIEW
                if verdict.get('classification_source') == 'rule_conflict' else STATE_CLASSIFIED),
                classification_source='user_exception',
                classification_basis='사용자 예외: 2026-09-19~2026-09-24 카드 3820 사용내역은 싱가포르 여행에 배정',
                item=verdict.get('item') or '현지경비',
                display_tab_id=target, trip_id=target,
                rule_id='owner-card3820-singapore-20261012')


RESIDUAL_SOURCES = ('', 'pattern', 'card_category', 'booking_evidence_needed', 'inference', 'rule',
                    'travel_location_hold')


def pair_refunds(conn, *, transaction_ids=None) -> int:
    """환불은 원거래 배정을 따른다. 일부 거래 분류에서는 지정된 환불만 처리한다."""
    paired = 0
    refunds = conn.execute(
        "SELECT transaction_id, card_tail, original_approval_number FROM transactions"
        " WHERE transaction_direction='cancellation' AND original_approval_number<>''"
        " AND COALESCE(classification_source,'') NOT LIKE 'user_%'").fetchall()
    for transaction_id, card_tail, original in refunds:
        if transaction_ids is not None and transaction_id not in transaction_ids:
            continue
        source = conn.execute(
            "SELECT classification_state, display_tab_id, trip_id, item, description FROM transactions"
            " WHERE card_tail=? AND approval_number=? AND transaction_direction='purchase'"
            " ORDER BY approval_date DESC LIMIT 1", (card_tail, original)).fetchone()
        if not source or source[0] not in (STATE_CLASSIFIED, STATE_NEEDS_REVIEW) or source[1] in (None, '', 'unclassified'):
            continue
        state, tab, trip, item, description = source
        conn.execute(
            "UPDATE transactions SET classification_state=?, classification_source='refund_original',"
            " classification_basis=?, item=?, description=?, display_tab_id=?, trip_id=? WHERE transaction_id=?",
            (state, f'원거래 승인번호 {original}의 배정을 따름', item, description, tab, trip, transaction_id))
        paired += 1
    return paired


def _card3820_residual(transaction: dict, verdict: dict) -> dict:
    """Owner policy after reconciliation; classification only, never posting."""
    if (transaction.get('card_tail') != '3820'
            or any(marker in str(transaction.get('transaction_kind', '')).lower()
                   for marker in ('refund', 'cancel', '취소', '승인'))
            or transaction.get('transaction_direction') != 'purchase'
            or type(transaction.get('amount_krw')) is not int or transaction['amount_krw'] <= 0
            or verdict['classification_source'] not in RESIDUAL_SOURCES
            # 해외 사용의 위치 보류는 여행 국가 확인이 먼저다. 국내 사용은 여행과 무관하므로 잔여로 본다.
            or (verdict['classification_source'] == 'travel_location_hold' and transaction.get('foreign_currency'))
            or verdict.get('trip_id') or transaction.get('parse_error')):
        return verdict
    from datetime import date
    try:
        day = date.fromisoformat(transaction.get('approval_date') or transaction.get('posting_date') or '')
    except (TypeError, ValueError):
        return verdict
    # A recognized OTA payment descriptor is not evidence of a non-trip residual.
    # Keep the transaction available for booking/payment reconciliation instead
    # of prematurely finalizing it as quarterly miscellaneous expense.
    from .ota_matching_defaults import provider_for_merchant
    if provider_for_merchant(transaction.get('merchant_normalized') or transaction.get('merchant')):
        return verdict
    from .quarter_costs import quarter_of
    year, quarter = quarter_of(day)
    return dict(verdict, classification_state=STATE_CLASSIFIED, classification_source='owner_card_residual',
                classification_basis='사용자 규칙: 기존 대사 후 남은 카드 3820 거래를 분기 기타비용으로 분류',
                item='분기 기타비용', description=f'{year}년 {quarter}분기 기타비용',
                display_tab_id=f'quarter:{year}:{quarter}', trip_id='', rule_id='owner-card3820-residual-20261012')


def _classify_transaction(transaction: dict, *, rules: list,
                          prior_decision=None, trip_resolver=None,allow_defaults=True) -> dict:
    """One transaction's classification, with the reason attached.

    Returns a dict; it does not write. `classify_batch` is what persists.
    """
    if transaction.get("parse_error"):
        return {"classification_state": STATE_NEEDS_REVIEW,
                "classification_source": "unreadable",
                "classification_basis": f"금액을 읽지 못했어요: {transaction['parse_error']}",
                "item": "", "description": "", "display_tab_id": "",
                "trip_id": "", "rule_id": ""}

    if prior_decision:
        return {"classification_state": STATE_CLASSIFIED,
                "classification_source": "previous_decision",
                "classification_basis": "이 거래에 이미 사용자 답변이 있어요",
                "item": prior_decision.get("item", ""),
                "description": prior_decision.get("description", ""),
                "display_tab_id": prior_decision.get("display_tab_id", ""),
                "trip_id": prior_decision.get("trip_id", ""),
                "rule_id": ""}

    merchant_normalized = normalize_merchant(transaction.get("merchant"))
    defaults=[r for r in rules if r.get('conditions',{}).get('merchant_normalized')=='*'] if allow_defaults else []
    if allow_defaults:
        rules=[r for r in rules if r not in defaults]

    # Rules are checked in a stable order so two matching rules cannot silently
    # disagree run to run: the first rule_id wins, and the winner is recorded.
    matches = []
    trip_blocked = None
    for candidate in rules:
        trial = transaction
        target = ''
        country = candidate.get('optional', {}).get('travel_country')
        booking = candidate.get('optional', {}).get('booking_period')
        if country:
            if is_booking_or_online(transaction) and not booking:
                continue
            base = dict(candidate, optional={k:v for k,v in candidate['optional'].items()
                                             if k != 'travel_country'})
            if not rule_matches(base, transaction)[0]:
                continue
            from .rules import transaction_region
            actual_country = transaction_region(transaction) if country=='local' else country
            target = trip_resolver(transaction, actual_country) if trip_resolver and actual_country else ''
            if not target:
                trip_blocked = candidate
                continue
            trial = dict(transaction, _verified_travel_country=country)
        elif booking:
            base = dict(candidate,optional={k:v for k,v in candidate['optional'].items() if k!='booking_period'})
            if not rule_matches(base,transaction)[0]:
                continue
            target = trip_resolver(transaction,booking) if trip_resolver else ''
            if not target:
                trip_blocked = candidate
                continue
            trial = dict(transaction,_booking_verified=True)
        matched, reasons = rule_matches(candidate, trial)
        if matched:
            matches.append((candidate,reasons,target))
    # 과거 업종 기본값의 빈 설명은 같은 원행에서 확인한 예약 설명과 충돌하지 않는다.
    # 사용자가 편집한 규칙이나 다른 항목·여행을 제안한 규칙은 그대로 충돌로 남긴다.
    verified_ota=[entry for entry in matches if entry[0].get('origin') in (OTA_MAIL_ORIGIN,OTA_PORTAL_ORIGIN)
                  and entry[0].get('optional',{}).get('source_hash')]
    if verified_ota:
        # 현재 원행의 예약 증거가 과거 자동 복원 규칙보다 구체적이다.
        # 직접 수정된 규칙과 사용자 결정은 이 우선순위로 제거하지 않는다.
        matches=[entry for entry in matches if not (
            entry[0].get('origin')=='history-recovery-20261003'
            and entry[0].get('version',1)==1)]
    provider_defaults=[entry for entry in matches if entry[0].get('optional',{}).get('merchant_family')]
    if provider_defaults:
        matches=[entry for entry in matches if not (
            entry[0].get('origin')=='history-recovery-20261003' and entry[0].get('version',1)==1
            and entry[0]['effects'].get('item')!=provider_defaults[0][0]['effects'].get('item'))]
        detailed=[entry for entry in matches if entry not in provider_defaults
                  and (entry[0].get('optional',{}).get('source_hash') or entry[2])]
        if any(entry[0]['effects'].get('item')==provider_defaults[0][0]['effects'].get('item') for entry in detailed):
            matches=[entry for entry in matches if entry not in provider_defaults]
    source_bound=[entry for entry in matches if entry[0].get('optional',{}).get('source_hash')]
    matches=[entry for entry in matches if not (
        entry[0].get('origin')=='history-recovery-20261003' and entry[0].get('version',1)==1
        and not entry[0].get('optional',{}).get('source_hash')
        and not entry[0]['effects'].get('description')
        and any(bound[0]['effects'].get('item')==entry[0]['effects'].get('item')
                and (bound[2] or bound[0]['effects'].get('display_tab_id',''))==
                    (entry[2] or entry[0]['effects'].get('display_tab_id','')) for bound in source_bound))]
    import json
    if len({json.dumps([r.get('effects'),t],sort_keys=True) for r,_,t in matches}) > 1:
        return dict(classification_state=STATE_NEEDS_REVIEW,classification_source='rule_conflict',
                    classification_basis='여러 규칙이 서로 다른 항목을 제안합니다. 확인해 주세요',
                    item='',description='',display_tab_id='',trip_id='',rule_id='')
    for rule, reasons, target in sorted(matches, key=lambda pair: pair[0].get('rule_id') or ''):
        effects = rule.get("effects") or {}
        return {"classification_state": STATE_CLASSIFIED,
                "classification_source": "rule",
                "classification_basis": "규칙: " + ", ".join(reasons),
                "item": effects.get("item", ""),
                "description": effects.get("description", ""),
                "display_tab_id": target or effects.get("display_tab_id", ""),
                "trip_id": target, "rule_id": rule.get("rule_id", "")}

    if trip_blocked:
        return dict(classification_state=STATE_NEEDS_REVIEW,classification_source='travel_location_hold',
                    classification_basis=('예약 이용기간에 맞는 여행을 확인해 주세요' if trip_blocked.get('optional',{}).get('booking_period')
                                          else '국내·해외 구분과 여행 기간에 맞는 여행이 없습니다'),
                    item=trip_blocked['effects'].get('item',''),description=trip_blocked['effects'].get('description',''),
                    display_tab_id='',trip_id='',rule_id=trip_blocked.get('rule_id',''))

    pattern = _pattern_for(merchant_normalized)
    category = str(transaction.get('description_raw') or '')
    if category.startswith('card-category:'):
        industry = category.removeprefix('card-category:').strip()
        groups = {
            '식비': {'편의점','슈퍼마켓','슈퍼마켓.마트','한식','일식','일식전문점','중식','양식',
                     '휴게음식','제과','커피','카페','음식점','일반음식점','서양음식','패스트푸드',
                     '커피/음료전문점','일반음식점 기타','일식/생선회집','제과점/아이스크림점',
                     '휴게음식점','패스트푸드점','기타식음료품','커피전문점','제과.제빵','서양식전문점'},
            '숙박비': {'호텔','숙박','숙박업','여관','모텔','펜션','콘도','리조트','레저용숙박업소','호텔(특급외)'},
            '교통비': {'택시','버스','철도','지하철','주유소','주차장','고속도로통행료','시내버스','고속.시외버스','여객선'},
            '항공료': {'항공사','항공','항공운송'},
            '렌터카': {'렌터카'},
        }
        for item, industries in groups.items():
            if industry in industries:
                trip = _verified_local_trip(transaction, item, trip_resolver)
                return dict(classification_state=STATE_CLASSIFIED,classification_source='card_category',
                            classification_basis='카드사 업종: '+industry + (' · 검증된 여행 기간의 현지 사용' if trip else ''),
                            item=item,description='',display_tab_id=trip or DEFAULT_TAB,trip_id=trip,rule_id='')
    if pattern:
        item, description, tabs = pattern
        trip = _verified_local_trip(transaction, item, trip_resolver)
        return {"classification_state": STATE_CLASSIFIED,
                "classification_source": "pattern",
                "classification_basis": "가맹점 업종 자동분류" + (' · 검증된 여행 기간의 현지 사용' if trip else ''),
                "item": item, "description": description,
                "display_tab_id": trip or DEFAULT_TAB, "trip_id": trip, "rule_id": ""}

    # 사용자가 지정한 현지 경비 기본값은 구체적 규칙과 명확한 업종 뒤에만 적용한다.
    # 예약·온라인 공급자의 결제일을 실제 이용일로 바꾸지 않는다.
    if defaults and not is_booking_or_online(transaction):
        return classify_transaction(transaction,rules=defaults,trip_resolver=trip_resolver,allow_defaults=False)

    if is_booking_or_online(transaction):
        return dict(classification_state=STATE_NEEDS_REVIEW,classification_source='booking_evidence_needed',
                    classification_basis='예약 자료로 구매 상품과 이용일을 확인해 주세요',
                    item='',description='',display_tab_id='',trip_id='',rule_id='')

    return {"classification_state": STATE_NEEDS_REVIEW,
            "classification_source": "",
            "classification_basis": "적용할 규칙과 분명한 가맹점 이름이 없어 확인할래요",
            "item": "", "description": "", "display_tab_id": "",
            "trip_id": "", "rule_id": ""}


def classify_batch(store, batch_id: str, *, rules: list | None = None, trip_resolver=None, review_from=None, transaction_ids=None, residual_policy=False) -> dict:
    """읽기부터 감사 이력까지 한 번에 처리하고 실패 시 분류 변경을 되돌린다."""
    with store.lock:
        nested=store.conn.in_transaction
        store.conn.execute('SAVEPOINT cost_classify_batch' if nested else 'BEGIN IMMEDIATE')
        try:
            result=_classify_batch(store,batch_id,rules=rules,trip_resolver=trip_resolver,
                                   review_from=review_from,transaction_ids=transaction_ids,residual_policy=residual_policy)
            if nested:
                store.conn.execute('RELEASE SAVEPOINT cost_classify_batch')
            else:
                store.conn.commit()
            return result
        except BaseException:
            if nested:
                store.conn.execute('ROLLBACK TO SAVEPOINT cost_classify_batch')
                store.conn.execute('RELEASE SAVEPOINT cost_classify_batch')
            else:
                store.conn.rollback()
            raise


def _classify_batch(store, batch_id: str, *, rules=None, trip_resolver=None, review_from=None, transaction_ids=None, residual_policy=False) -> dict:
    """Classify every undecided row in a batch.

    A row a human already decided, or that is already on the ledger, is skipped entirely, which is how
    that classification survives the next upload and the next rule change.
    ``review_from`` is retained for API compatibility; date windows scope reads
    and posting previews, never the classification state of an imported row.
    """
    from .db import CODE_NOT_FOUND, StoreError

    active_rules = list_rules_for(store) if rules is None else rules
    selected = None if transaction_ids is None else frozenset(transaction_ids)
    rules_by_merchant = {}
    for rule in active_rules:
        rules_by_merchant.setdefault(rule['conditions']['merchant_normalized'], []).append(rule)
    rows = store.conn.execute(
        "SELECT transaction_id, issuer, card_tail, card_kind,"
        " transaction_direction, transaction_kind, approval_number,"
        " original_approval_number, approval_date, posting_date, merchant,"
        " merchant_normalized, amount_krw, foreign_amount, foreign_currency,"
        " description_raw, row_index, raw_row_json, parse_error, " + decided_sql() + ","
        " classification_state,source_hash,classification_source,classification_basis,item,"
        " description,display_tab_id,trip_id FROM transactions WHERE transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?) ORDER BY row_index",
        (batch_id,)).fetchall()
    if not rows:
        exists = store.conn.execute(
            "SELECT 1 FROM import_batches WHERE batch_id=?", (batch_id,)).fetchone()
        if exists is None:
            raise StoreError(CODE_NOT_FOUND, "없는 접수 건이에요")
        return {"batch_id": batch_id, "counts": {}, "reclassified": 0,
                "protected": 0, "needs_review": 0, "classified": 0}

    counts = {STATE_NEEDS_REVIEW: 0, STATE_CLASSIFIED: 0}
    reclassified = protected = 0
    now = _now()
    with store.lock:
        for row in rows:
            (transaction_id, issuer, card_tail, card_kind, direction, kind,
             approval_number, original_approval, approval_date, posting_date,
             merchant, merchant_normalized, amount_krw, foreign_amount,
             foreign_currency, description_raw, row_index, raw_json, parse_error,
             decided, state, source_hash, current_source, current_basis,
             current_item, current_description, current_tab, current_trip) = row
            if selected is not None and transaction_id not in selected:
                continue
            if current_source == 'ai_inference' and state == STATE_CLASSIFIED:
                counts[state] = counts.get(state, 0) + 1
                protected += 1
                continue
            # 3820 장부 행의 미배정은 규칙으로 다시 대사한다. 사용자가 정한 거래와 배정된 거래는 보호한다.
            reconcile_booked = (decided and residual_policy and card_tail == '3820'
                                and current_tab in (None, '', 'unclassified') and current_source not in ('user_decision', 'user_exception')
                                and store.conn.execute("SELECT decided_at FROM transactions WHERE transaction_id=?",
                                                       (transaction_id,)).fetchone()[0] is None)
            if decided and not reconcile_booked:
                counts[state] = counts.get(state, 0) + 1
                protected += 1
                continue
            transaction = {
                "transaction_id": transaction_id, "issuer": issuer,
                'source_hash':source_hash,
                "card_tail": card_tail, "card_kind": card_kind,
                "transaction_direction": direction, "transaction_kind": kind,
                "approval_number": approval_number,
                "original_approval_number": original_approval,
                "approval_date": approval_date, "posting_date": posting_date,
                "merchant": merchant, "merchant_normalized": merchant_normalized,
                "amount_krw": amount_krw, "foreign_amount": foreign_amount,
                "foreign_currency": foreign_currency,
                "description_raw": description_raw, "parse_error": parse_error,
                'raw_row': __import__('json').loads(raw_json),
            }
            eligible_residual = residual_policy
            if residual_policy and card_tail == '3820':
                duplicate, conflict, booked, excluded = store.conn.execute(
                    'SELECT duplicate_of,conflict_reason,'
                    'EXISTS(SELECT 1 FROM ledger_entries WHERE transaction_id=t.transaction_id),'
                    'EXISTS(SELECT 1 FROM transaction_company_exclusions WHERE transaction_id=t.transaction_id AND excluded=1) '
                    'FROM transactions t WHERE transaction_id=?', (transaction_id,)).fetchone()
                held = store.conn.execute('SELECT 1 FROM transaction_review_holds WHERE transaction_id=?',
                                          (transaction_id,)).fetchone()
                # 장부에 기록됐어도 배정이 비어 있는 거래는 규칙으로 다시 대사한다. 배정된 거래와 사용자 결정은 보호한다.
                unassigned = current_tab in (None, '', 'unclassified')
                if (booked and not unassigned) or excluded or held or current_trip:
                    counts[state] = counts.get(state, 0) + 1
                    protected += 1
                    continue
                eligible_residual = not duplicate and not conflict
            verdict = classify_transaction(transaction, rules=rules_by_merchant.get(merchant_normalized,[])+rules_by_merchant.get('*',[]),
                                           prior_decision=None, trip_resolver=trip_resolver, residual_policy=eligible_residual)
            counts[verdict["classification_state"]] = counts.get(
                verdict["classification_state"], 0) + 1
            if state != verdict["classification_state"]:
                reclassified += 1
            values=(verdict['classification_state'],verdict['classification_source'],
                    verdict['classification_basis'],verdict['item'],verdict['description'],
                    verdict['display_tab_id'],verdict.get('trip_id',''))
            if values==(state,current_source,current_basis,current_item,current_description,current_tab,current_trip):
                continue
            store.conn.execute(
                "UPDATE transactions SET classification_state=?,"
                " classification_source=?, classification_basis=?, item=?,"
                " description=?, display_tab_id=?, trip_id=? WHERE transaction_id=?",
                values+(transaction_id,))
        pair_refunds(store.conn, transaction_ids=selected)
        store.conn.execute(
            "UPDATE import_batches SET parsed_at=?, status='classified'"
            " WHERE batch_id=?", (now, batch_id))
        store.log_change("batch.classified", batch_id, {"counts": counts})
    return {"batch_id": batch_id, "counts": counts, "reclassified": reclassified,
            "protected": protected, "needs_review": counts.get(STATE_NEEDS_REVIEW, 0),
            "classified": counts.get(STATE_CLASSIFIED, 0)}


def list_rules_for(store) -> list:
    from .rules import list_rules
    return list_rules(store)


def _now() -> str:
    from .db import utc_now
    return utc_now()
