# -*- coding: utf-8 -*-
"""Classification rules: what a rule may match, and what it may do.

A rule has conditions and effects, kept strictly apart.

Conditions are only ever `merchant_normalized`, `card_kind` and
`transaction_direction`, plus two optional narrower ones: an amount range and a
service-period window. Effects are only ever `item`, `description` and
`display_tab_id`.

The separation is the point. A rule cannot restate the source amount, the source
date or the source id, so applying a rule can never invent a price or move a
transaction in time. `normalize_rule` refuses a draft that tries, rather than
quietly dropping the field.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

from .db import CODE_INVALID_INPUT, StoreError, canonical, utc_now
from .normalize import normalize_merchant, to_amount_krw, to_date


TRIP_COUNTRIES = {
    'KR': {'부산','의왕','금오도','호남','군산','화순','영남','경주','통영','황금해안',
           '변산','양평','제주','세종','길상사','박달고치','함양','한티','해남'},
    'TW': {'대만'}, 'MN': {'몽골'},
    'JP': {'에히메','교토','나가센도','아오모리','오사카','알펜루트','북해도',
           '레분토&리시리','묘코','묘코고원','아키타','오제','야마가타','세토우치',
           '야마구치','북큐슈','도고','가루이자와','야쿠시마','도쿄','노리쿠라','다테시나','도쿠시마'},
}


def trip_countries(trip):
    destination = trip.get('destination') or ''
    if destination == '유럽':
        return {'AT', 'IT', 'FR'}
    return {code for code, regions in TRIP_COUNTRIES.items() if destination in regions}


def merchant_country(transaction):
    """현지 구매 규칙용 원본 국가다. 통화나 여행 이름으로 국가를 추정하지 않는다."""
    raw = transaction.get('raw_row') or {}
    explicit = raw.get('country') or raw.get('국가') or raw.get('국가코드')
    if not explicit and transaction.get('issuer') == '국민':
        candidate = str(raw.get('c8') or '').strip().upper()
        if re.fullmatch('[A-Z]{2,3}', candidate):
            explicit = candidate
    codes={'JPN':'JP','KOR':'KR','TWN':'TW','AUT':'AT','ITA':'IT','FRA':'FR','MNG':'MN',
           'SGP':'SG','NLD':'NL','DEU':'DE','ESP':'ES','CZE':'CZ','GBR':'GB',
           'USA':'US','GEO':'GE','KAZ':'KZ','TUR':'TR','HKG':'HK'}
    country_pattern='JP|KR|TW|AT|IT|FR|MN|SG|NL|DE|ES|CZ|GB|US|GE|KZ|TR|HK|LV'
    if str(explicit or '').strip().upper() in codes:
        return codes[str(explicit).strip().upper()]
    if explicit and re.fullmatch('[A-Z]{2}', str(explicit).strip().upper()):
        return str(explicit).strip().upper()
    suffix = re.search(r'\s('+country_pattern+r')\s*$', str(transaction.get('merchant') or '').upper())
    if suffix:
        return suffix.group(1)
    three=re.search(r'\s('+'|'.join(codes)+r')\s*$',str(transaction.get('merchant') or '').upper())
    if three:
        return codes[three.group(1)]
    if (transaction.get('card_kind')=='해외' or
            any(str(raw.get(field) or '').startswith('해외') for field in ('c1','c11'))):
        # 하나의 고정 폭 해외 가맹점 필드에서 도시명과 국가 코드가 붙은 경우.
        compact=re.search(r'\s{2,}[A-Z0-9 .&/-]+?('+country_pattern+r')\s*$',str(transaction.get('merchant') or '').upper())
        if compact:
            return compact.group(1)
    if str(raw.get('c11') or '').startswith('해외'):
        return ''
    if transaction.get('card_kind') == '국내':
        return 'KR'
    return ''


def is_booking_or_online(transaction):
    """예약·온라인 결제는 사용 국가와 결제일만으로 현지 구매에 배정하지 않는다."""
    merchant=str(transaction.get('merchant') or '').upper()
    markers=('AGODA','BOOKING','TRIP','KLOOK','RAKUTEN','AIRBNB','HOTEL','RYOKAN',
             '아고다','트립닷컴','클룩','부킹닷컴','에어비앤비','트래블로버','나이스정보통신',
             'AIRLINE','GOTOGATE','AIRWAYS','NICE','PAY','이니시스','KCP','항공',
             'AMAZON','GOOGLE','APPLE','MICROSOFT','인터넷상거래','전자상거래',
             '통신판매','어드벤처코리아','결제대행','네이버페이','카카오페이','페이팔')
    category=str(transaction.get('description_raw') or '')
    return (any(marker in merchant for marker in markers) or
            (category.startswith('card-category:') and
             any(marker in category for marker in ('인터넷상거래','전자상거래','통신판매','결제대행'))))

__all__ = [
    "CONDITION_FIELDS", "OPTIONAL_FIELDS", "EFFECT_FIELDS",
    "normalize_rule", "rule_matches", "save_rule", "list_rules",
    "build_rule_from_decision",
]

CONDITION_FIELDS = ("merchant_normalized", "card_kind", "transaction_direction")
OPTIONAL_FIELDS = ("amount_range", "date_or_service_period", "travel_country", "source_hash", "booking_period", "inferred_assignment", "merchant_family")
EFFECT_FIELDS = ("item", "description", "display_tab_id")

# Fields that describe the source. A rule naming any of them is refused.
FROZEN_FIELDS = frozenset({
    "amount_krw", "amount", "foreign_amount", "approval_date", "posting_date",
    "occurred_on", "date", "transaction_id", "approval_number", "source_hash",
    "merchant", "merchant_normalized",
})


def _fail(message: str):
    raise StoreError(CODE_INVALID_INPUT, message)


def normalize_rule(draft: dict) -> dict:
    """Validate one rule and return its canonical form.

    `merchant_normalized` is required: a rule with no merchant condition would
    match every future import of every card.
    """
    if not isinstance(draft, dict):
        _fail("규칙 형식이 달라요")
    unknown = sorted(set(draft) - {"conditions", "optional", "effects", "note",
                                   "origin", "rule_id"})
    if unknown:
        _fail(f"규칙에 쓸 수 없는 항이 있어요: {unknown}")
    if FROZEN_FIELDS & set(draft):
        _fail("규칙은 원천 금액·날짜·거래 ID를 바꿀 수 없어요")

    raw_conditions = draft.get("conditions") or {}
    if not isinstance(raw_conditions, dict):
        _fail("조건 형식이 달라요")
    bad_conditions = sorted(set(raw_conditions) - set(CONDITION_FIELDS))
    if bad_conditions:
        _fail(f"허용되지 않은 조건이에요: {bad_conditions}")
    conditions: dict = {}
    for field, value in raw_conditions.items():
        if field == "merchant_normalized":
            merchant = normalize_merchant(value)
            if not merchant:
                _fail("가맹점 조건이 비어 있어요")
            conditions[field] = merchant
        else:
            text = str(value or "").strip()
            if not text:
                _fail(f"{field} 조건이 비어 있어요")
            conditions[field] = text.casefold() if field == "card_kind" else text
    if "merchant_normalized" not in conditions:
        _fail("가맹점 조건은 반드시 필요해요")

    optional = draft.get("optional") or {}
    if not isinstance(optional, dict):
        _fail("선택 조건 형식이 달라요")
    bad_optional = sorted(set(optional) - set(OPTIONAL_FIELDS))
    if bad_optional:
        _fail(f"허용되지 않은 선택 조건이에요: {bad_optional}")
    if 'merchant_family' in optional:
        if optional['merchant_family']!='agoda' or conditions['merchant_normalized']!='agoda':
            _fail('가맹점 그룹은 확인된 아고다 규칙에만 사용할 수 있습니다')
    if 'travel_country' in optional:
        if optional['travel_country'] not in ('local', 'JP', 'KR', 'TW', 'AT', 'IT', 'FR'):
            _fail('현지 여행 조건의 국가를 확인해 주세요')
    if conditions['merchant_normalized']=='*' and optional.get('travel_country')!='local':
        _fail('전체 가맹점 규칙은 사용 국가와 명시 여행이 일치하는 현지 사용에만 적용할 수 있습니다')
    if 'source_hash' in optional and not re.fullmatch('[0-9a-f]{64}', str(optional['source_hash'])):
        _fail('원본 거래 결속 값이 올바르지 않습니다')
    if 'inferred_assignment' in optional:
        inference = optional['inferred_assignment']
        if (not isinstance(inference, dict) or set(inference) != {'trip_id','basis','confidence'}
                or 'source_hash' not in optional or conditions['merchant_normalized']=='*'
                or inference['confidence'] not in ('높음','중간','낮음')
                or not isinstance(inference['trip_id'], str)
                or not isinstance(inference['basis'], str) or not inference['basis'].strip()
                or len(inference['basis'])>1600
                or any(field in optional for field in ('booking_period','travel_country'))):
            _fail('추론 배정은 해당 원본 거래와 근거, 확신 정도를 함께 저장해야 합니다')
    if 'booking_period' in optional:
        period = optional['booking_period']
        if (not isinstance(period, dict) or set(period) != {'starts_on','ends_on','target_code','source_sha256'}
                or 'source_hash' not in optional
                or not re.fullmatch('[0-9a-f]{64}',str(period.get('source_sha256')))):
            _fail('예약 이용기간과 원본 거래 근거를 확인해 주세요')
        for field in ('starts_on','ends_on'):
            period[field] = to_date(period[field])
        if not period['starts_on'] or not period['ends_on'] or period['ends_on'] < period['starts_on']:
            _fail('예약 이용기간이 올바르지 않습니다')
    if "amount_range" in optional:
        window = optional["amount_range"] or {}
        if not isinstance(window, dict) or sorted(set(window) - {"min", "max"}):
            _fail("금액 범위 형식이 달라요")
        clean = {}
        for bound in ("min", "max"):
            if window.get(bound) in (None, ""):
                continue
            try:
                clean[bound] = to_amount_krw(window[bound], bound)
            except Exception:
                _fail(f"금액 범위 {bound} 값을 읽을 수 없어요")
        if 'min' in clean and 'max' in clean and clean['min'] > clean['max']:
            _fail("금액 범위 최소값이 최대값보다 커요")
        optional["amount_range"] = clean
    if "date_or_service_period" in optional:
        period = optional["date_or_service_period"] or {}
        if not isinstance(period, dict) or sorted(set(period) - {"start", "end"}):
            _fail("기간 형식이 달라요")
        for bound in ("start", "end"):
            if period.get(bound):
                text = to_date(period[bound], f"period_{bound}")
                if not text:
                    _fail(f"기간 {bound} 날짜를 읽을 수 없어요")
                period[bound] = text

    effects_in = draft.get("effects") or {}
    if not isinstance(effects_in, dict) or not effects_in:
        _fail("적용할 항목이나 내용을 입력해 주세요")
    bad_effects = sorted(set(effects_in) - set(EFFECT_FIELDS))
    if bad_effects:
        _fail(f"허용되지 않은 효과예요: {bad_effects}")
    effects = {}
    for field, value in effects_in.items():
        text = str(value or "").strip()
        if not text:
            _fail(f"{field} 효과가 비어 있어요")
        effects[field] = text
    if effects.get('display_tab_id') not in (None, 'unclassified'):
        _fail('가맹점 분류 규칙으로 여행을 자동 배정할 수 없습니다. 거래별로 확인해 주세요')

    note = str(draft.get("note") or "").strip()
    if len(note) > 2000:
        _fail("규칙 메모가 너무 길어요")
    return {
        "conditions": conditions,
        "optional": optional,
        "effects": effects,
        "note": note,
        "origin": str(draft.get("origin") or "").strip()[:200],
        "rule_id": str(draft.get("rule_id") or "").strip()[:200],
    }


def rule_matches(rule: dict, transaction: dict) -> tuple[bool, list]:
    """Does this rule apply to this transaction, and on what grounds.

    Returns (matched, reasons). Every condition present must hold; optional
    windows narrow further. The reasons are recorded so a classification can say
    why it decided what it decided.
    """
    conditions = rule.get("conditions") or {}
    optional = rule.get("optional") or {}
    reasons: list[str] = []

    merchant=normalize_merchant(transaction.get('merchant'))
    if optional.get('merchant_family')=='agoda':
        if not re.match(r'^(?:agoda|아고다)(?:[\s._*\-]|$)',merchant):
            return False, []
    elif conditions.get('merchant_normalized')!='*' and merchant != conditions.get('merchant_normalized'):
        return False, []
    reasons.append('현지 사용 기본 규칙' if conditions.get('merchant_normalized')=='*' else '가맹점 일치')
    if optional.get('source_hash') and transaction.get('source_hash') != optional['source_hash']:
        return False, []
    if optional.get('travel_country'):
        if transaction.get('_verified_travel_country') != optional['travel_country']:
            return False, []
        reasons.append('사용 장소와 검증된 여행 일정 일치')
    if optional.get('booking_period'):
        if not transaction.get('_booking_verified'):
            return False, []
        reasons.append('예약번호·결제금액·결제일과 이용기간 검증')

    if "card_kind" in conditions:
        if str(transaction.get("card_kind") or "").strip().casefold() != \
                conditions["card_kind"]:
            return False, []
        reasons.append("카드 종류 일치")

    if "transaction_direction" in conditions:
        if str(transaction.get("transaction_direction") or "") != \
                conditions["transaction_direction"]:
            return False, []
        reasons.append("거래 방향 일치")

    window = optional.get("amount_range") or {}
    if window:
        amount = transaction.get("amount_krw")
        if amount is None:
            return False, []  # an unreadable amount cannot be inside a range
        if window.get("min") is not None and amount < window["min"]:
            return False, []
        if window.get("max") is not None and amount > window["max"]:
            return False, []
        reasons.append("금액 범위 일치")

    period = optional.get("date_or_service_period") or {}
    if period:
        occurred = transaction.get("approval_date") or ""
        if period.get("start") and occurred < period["start"]:
            return False, []
        if period.get("end") and occurred > period["end"]:
            return False, []
        reasons.append("기간 일치")
    return True, reasons


def build_rule_from_decision(*, merchant: str, card_kind: str,
                             transaction_direction: str, item: str,
                             description: str, display_tab_id: str = "",
                             note: str = "") -> dict:
    """A one-merchant rule from one decision, for `reuse_rule`.

    Built from the decision, not inferred: only the fields the decision actually
    carried become effects.
    """
    effects = {}
    if item:
        effects["item"] = item
    if description:
        effects["description"] = description
    if display_tab_id:
        effects["display_tab_id"] = display_tab_id
    conditions = {"merchant_normalized": normalize_merchant(merchant)}
    if card_kind:
        conditions["card_kind"] = card_kind
    if transaction_direction:
        conditions["transaction_direction"] = transaction_direction
    return normalize_rule({"conditions": conditions, "effects": effects,
                           "note": note, "origin": "decision"})


def save_rule(store, draft: dict) -> dict:
    """Persist a validated rule. Bump the version; never rewrite history."""
    rule = normalize_rule(draft)
    import hashlib
    rule_id = rule["rule_id"] or "rule-" + hashlib.sha256(
        canonical(rule["conditions"]).encode()).hexdigest()[:24]
    body = {"conditions": rule["conditions"], "optional": rule["optional"],
            "effects": rule["effects"]}
    import hashlib
    rule_hash = hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()
    now = utc_now()
    with store.lock:
        found = store.conn.execute(
            "SELECT version, rule_hash FROM cost_classification_rules WHERE rule_id=?",
            (rule_id,)).fetchone()
        if found is None:
            store.conn.execute(
                "INSERT INTO cost_classification_rules(rule_id, version, status,"
                " conditions_json, effects_json, optional_json, note, origin,"
                " rule_hash, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (rule_id, 1, "active", canonical(rule["conditions"]),
                 canonical(rule["effects"]), canonical(rule["optional"]),
                 rule["note"], rule["origin"], rule_hash, now, now))
            version = 1
            action = "created"
        elif found[1] == rule_hash:
            version = found[0]
            action = "unchanged"
        else:
            version = found[0] + 1
            store.conn.execute(
                "UPDATE cost_classification_rules SET version=?, conditions_json=?,"
                " effects_json=?, optional_json=?, note=?, rule_hash=?,"
                " updated_at=? WHERE rule_id=?",
                (version, canonical(rule["conditions"]), canonical(rule["effects"]),
                 canonical(rule["optional"]), rule["note"], rule_hash, now, rule_id))
            action = "revised"
        store.log_change("rule." + action, rule_id,
                         {"version": version, "rule_hash": rule_hash})
    return {"rule_id": rule_id, "version": version, "action": action,
            "rule_hash": rule_hash}


def list_rules(store, *, status: str = "active") -> list:
    rows = store.conn.execute(
        "SELECT rule_id, version, status, conditions_json, effects_json,"
        " optional_json, note, rule_hash, origin FROM cost_classification_rules"
        " WHERE (?='all' OR status=?) ORDER BY rule_id", (status, status)).fetchall()
    return [{"rule_id": r[0], "version": r[1], "status": r[2],
             "conditions": json.loads(r[3]), "effects": json.loads(r[4]),
             "optional": json.loads(r[5]), "note": r[6], "rule_hash": r[7], "origin": r[8]}
            for r in rows]
