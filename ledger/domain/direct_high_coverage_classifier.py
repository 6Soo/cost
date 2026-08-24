"""Apply the inherited Q2 operating defaults to the all-period card scope.

This module is deliberately separate from the narrow leave-one-out classifier.
The narrow model proves high-confidence learned matches.  This model closes
the remaining current-card rows with explicit, auditable policy outcomes:

* ordinary domestic spend -> ``기타비용`` / ``판관비``;
* overseas use -> ``여행원가`` and a year-aware trip target when the use date
  identifies one trip;
* OTA, airfare, insurance, and other prepaid travel without a typed service
  period -> ``여행_미배정`` / ``여행원가``.

Historical/manual rows are normally read only as learning material.  The one
explicit exception is a manual *travel-tab classification*: when a current
card event has a one-to-one issuer/date/absolute-amount match to exactly one
valid travel tab, or belongs to a closed issuer/absolute-amount component whose
manual travel tabs all name one target, that tab is used as a strong
classification signal.  The manual row is still never promoted as transaction
evidence: the current card supplies the transaction, the current-card policy
supplies account/cost_type, and the manual tab supplies only allocation_target.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Iterable

from ledger.cardindex import account as card_account
from ledger.domain.direct_validated_purchase_classifier import (
    TRAINING_ROLE,
    TRAINING_SOURCE_SHA256,
    _load_training,
)
from ledger.domain.source_adapters import (
    OTA_LIFECYCLE_PARSER_VERSION,
    OTA_STATUS_RULE_VERSION,
)
from ledger.domain.direct_verified_ota_lodging import load_trip_schedule
from ledger.domain.direct_geographic_trip_context import (
    context_manifest,
    is_taiwan_marker,
    load_geographic_trip_context,
)
from ledger.domain.direct_gmail_payment_evidence import (
    CONTRACT as GMAIL_EVIDENCE_CONTRACT,
    SNAPSHOT_SHA256 as GMAIL_EVIDENCE_SNAPSHOT_SHA256,
    evidence_for_row,
)
from ledger.domain.direct_pg_payment_evidence import (
    evidence_for_row as pg_evidence_for_row,
    load_pg_mail_records,
    load_service_mail_records,
)
from ledger.domain.direct_current_owner_decision import (
    CONTRACT as OWNER_DECISION_CONTRACT,
    assert_single_use,
    decision_for_row,
    load_current_owner_decisions,
)
from ledger.domain.direct_structural_rule_admission import (
    admission_manifest,
    normalize_admitted_rule_paths,
)
from ledger.domain.direct_trip_cluster_registry import (
    ACTIVITY_PLACEHOLDER_PATH,
    ACTIVITY_PLACEHOLDER_TARGET_KIND,
    REGION_COUNTRIES,
    REGION_LABELS,
    REGISTRY_PATH,
    RESERVATION_PLACEHOLDER_PATH,
    RESERVATION_PLACEHOLDER_TARGET_KIND,
    build_reversal_activity_placeholder_registry,
    build_reversal_reservation_placeholder_registry,
    build_split_reversal_activity_placeholder_registry,
    build_trip_cluster_registry,
    build_reservation_placeholder_registry,
    build_split_travel_activity_placeholder_registry,
    registry_manifest,
)


MODEL_CONTRACT = "current-card-high-coverage-policy-v4"
RULE_ID = "current-card-high-coverage-policy-v4"
AXIS_EVIDENCE_CONTRACT = "current-card-axis-evidence-v2"
ACTIVE_DIMENSIONS = ("account", "cost_type", "allocation_target")
TRIP_COST = "여행원가"
OVERHEAD_COST = "판관비"
TRIP_UNASSIGNED = "여행_미배정"
OVERHEAD_TARGET = "기타비용"
REVERSAL_PROVISIONAL_INHERIT_PATH = "current_card_reversal_provisional_inherit"
GMAIL_PAYMENT_TRAVEL_EVIDENCE_PATH = "gmail_payment_travel_type_evidence"
GMAIL_PAYMENT_OVERHEAD_EVIDENCE_PATH = "gmail_payment_overhead_evidence"
GMAIL_PAYMENT_SERVICE_PERIOD_PATH = "gmail_payment_service_period_evidence"
GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH = (
    "gmail_payment_verified_service_period"
)
OWNER_DECISION_CURRENT_SCOPE_PATH = "owner_decision_current_scope"
GMAIL_PAYMENT_SERVICE_PERIOD_PENDING_PATH = (
    "gmail_payment_service_period_pending_review"
)
GMAIL_PAYMENT_APPROVAL_FAMILY_PENDING_PATH = (
    "gmail_payment_approval_family_pending_review"
)
DOMESTIC_GATEWAY_UNVERIFIED_PATH = "domestic_gateway_unverified"
FOREIGN_SERVICE_PERIOD_PENDING_PATH = "foreign_service_period_pending_review"
INFERRED_EXTERNAL_TARGET_PATH = "current_card_inferred_external_target"
INFERRED_EXTERNAL_TARGET_KIND = "inferred_external_target"
INFERRED_EXTERNAL_RULE_ID = "current-card-inferred-external-target-v1"
INFERRED_EXTERNAL_REGISTRY_VERSION = "current-card-inferred-external-target-v1"
FOREIGN_USE_DATE_SCHEDULE_PATH = (
    "current_card_foreign_use_date_schedule_overrides_manual_ambiguity"
)
FOREIGN_USE_DATE_SCHEDULE_EXACT_PATH = (
    "current_card_foreign_use_date_schedule_exact_2026"
)
MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH = "manual_travel_tab_amount_component_exact"
MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH = (
    "manual_travel_tab_amount_component_mn_target_invariant"
)
TRIP_CLUSTER_CANONICAL_EXACT_PATH = "current_card_trip_cluster_canonical_exact"
OTA_MAIL_SERVICE_PERIOD_EXACT_PATH = "ota_mail_service_period_exact"
OTA_MAIL_SERVICE_PERIOD_MN_PATH = "ota_mail_service_period_mn_target_invariant"
OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH = (
    "ota_mail_service_period_amount_tolerance_exact"
)
OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH = (
    "ota_mail_service_period_amount_tolerance_mn_target_invariant"
)
OTA_MAIL_SENT_DATE_AMOUNT_TARGET_PATH = (
    "ota_mail_sent_date_amount_target_candidate"
)
OTA_AMOUNT_TOLERANCE_RATIO = 0.02
OTA_AMOUNT_TOLERANCE_POLICY = "ota-card-amount-tolerance-v1"
OTA_MAIL_SENT_DATE_TOLERANCE_DAYS = 30
OTA_MAIL_SERVICE_PERIOD_PATHS = frozenset({
    OTA_MAIL_SERVICE_PERIOD_EXACT_PATH,
    OTA_MAIL_SERVICE_PERIOD_MN_PATH,
    OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH,
    OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH,
})
OTA_MAIL_SERVICE_PERIOD_EXACT_CARD_PATHS = frozenset({
    OTA_MAIL_SERVICE_PERIOD_EXACT_PATH,
    OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH,
})
OTA_MAIL_SERVICE_PERIOD_MN_CARD_PATHS = frozenset({
    OTA_MAIL_SERVICE_PERIOD_MN_PATH,
    OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH,
})
# A 2025 payment can cross into a 2026 travel tab only when the payment
# itself was uniquely joined to an external mail record and that record
# carries an explicit 2026 service period.  Card geography, a manual tab,
# a payment-date activity cluster, and a reservation placeholder are not
# substitutes for this evidence.
MAIL_SERVICE_SOURCE_KINDS = frozenset({
    "ota_mail",
    "ota_mail_live",
    "pg_mail",
    "pg_mail_supplement",
    "service_mail",
    "gmail_payment_snapshot",
})
MAIL_SERVICE_TARGET_PATHS = frozenset({
    *OTA_MAIL_SERVICE_PERIOD_PATHS,
    GMAIL_PAYMENT_SERVICE_PERIOD_PATH,
    GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH,
    INFERRED_EXTERNAL_TARGET_PATH,
})
KNOWN_DIRECT_TRAVEL_TOKENS = (
    "와이드모바일", "주식회사와이드모바일", "산림휴양시설", "산림치유원",
    "의왕도시공사", "강화리조트", "카카오T로밍", "제주도닷컴",
    "와이페이모어", "마이리얼트립", "어드벤처코리아", "쏘카",
    "놀유니버스",
)
# A card date is treated as a service date only for a deliberately narrow,
# physical-merchant cohort.  Generic overseas merchants and payment rails
# remain service-period unknown.
FOREIGN_DIRECT_USE_MERCHANT_TOKENS = (
    "GASUTO", "TOLL", "PARKING", "PARKINGS", "CAFFE", "CAFE",
    "RESTAURANT", "MCDONALDS", "7ELEVEN", "HYPERMARKET", "SUPERMERCATO",
    "WINES", "TAXI", "CITYCAB", "TOTAL", "NESPRESSO", "AUTOLINEE",
    "ESCOTA", "FLIX", "LIDL", "TPER", "SMTPC",
)
FOREIGN_EUROPE_MERCHANT_MARKERS = (
    "FR", "IT", "DE", "MC", "VENEZIA", "BOLOGNA", "FIRENZE",
    "FLORENCE", "MARSEILLE", "NICE", "BERLIN", "MUNCHEN", "MONACO",
    "AIXENPROVENCE", "SCANDICCI",
)
ADVERSE_TOKENS = ("확인", "미정", "검토", "추정")
FEATURE_NAMES = (
    "source_merchant_biz_currency",
    "source_card_merchant",
    "source_merchant",
    "merchant",
)
TARGET_FEATURE_NAMES = (
    "use_merchant",
    "posted_merchant",
    "source_merchant_biz_currency",
    "source_merchant",
    "merchant",
)
REVERSAL_TYPES = {"cancellation", "refund"}
MANUAL_CARD_SOURCES = {
    "국민": frozenset({"KBD", "KBO"}),
    "하나": frozenset({"HAN"}),
    "기업": frozenset({"CORP"}),
    "기업카드": frozenset({"CORP"}),
}
# The latest owner instruction makes the travel-tab label strong
# classification evidence.  The current card still supplies the transaction
# fact and the account/cost axes; the manual row supplies only the travel
# target.  For M:N matches this confirms the common target only, never an
# individual card-row relation.
CONFIRMED_TRAVEL_TARGET_PATHS = frozenset({
    "manual_travel_tab_exact",
    "manual_travel_tab_mn_target_invariant",
    MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
    MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH,
    OTA_MAIL_SERVICE_PERIOD_EXACT_PATH,
    OTA_MAIL_SERVICE_PERIOD_MN_PATH,
    OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH,
    OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH,
    FOREIGN_USE_DATE_SCHEDULE_EXACT_PATH,
    TRIP_CLUSTER_CANONICAL_EXACT_PATH,
})
MANUAL_REVERSAL_EXACT_PATH = "manual_travel_tab_reversal_exact"
MANUAL_REVERSAL_MN_PATH = "manual_travel_tab_reversal_mn_target_invariant"
PROVISIONAL_TARGET_PATHS = frozenset({
    MANUAL_REVERSAL_EXACT_PATH,
    MANUAL_REVERSAL_MN_PATH,
    "current_card_geography_context_exact_2026",
    REGISTRY_PATH,
    ACTIVITY_PLACEHOLDER_PATH,
    RESERVATION_PLACEHOLDER_PATH,
    REVERSAL_PROVISIONAL_INHERIT_PATH,
    GMAIL_PAYMENT_SERVICE_PERIOD_PATH,
    INFERRED_EXTERNAL_TARGET_PATH,
    FOREIGN_USE_DATE_SCHEDULE_PATH,
})
REVIEW_TARGET_PATHS = frozenset({
    *PROVISIONAL_TARGET_PATHS,
    "manual_travel_tab_ambiguous",
    "manual_geography_conflict",
    GMAIL_PAYMENT_SERVICE_PERIOD_PENDING_PATH,
    GMAIL_PAYMENT_APPROVAL_FAMILY_PENDING_PATH,
    DOMESTIC_GATEWAY_UNVERIFIED_PATH,
    FOREIGN_SERVICE_PERIOD_PENDING_PATH,
})
REGISTRY_BACKED_TARGET_PATHS = frozenset({
    REGISTRY_PATH,
    TRIP_CLUSTER_CANONICAL_EXACT_PATH,
    ACTIVITY_PLACEHOLDER_PATH,
    RESERVATION_PLACEHOLDER_PATH,
})
AUTO_PROVISIONAL_REVIEW_STATUS = "auto_provisional"
OWNER_CONFIRMATION_REVIEW_STATUS = "needs_review"
# A payment gateway name alone is never a travel signal.  These exact pairs
# close known domestic goods/services before the broader domestic-gateway
# overhead policy runs.  Provider/travel markers still remain in the travel
# hold until their service period is known.
EXPLICIT_DOMESTIC_NONTRAVEL = frozenset({
    ("손해보험KCP", "손해보험"),
    ("대법원전자소송법원행정처", "전자상거래PG"),
    ("쿠팡쿠팡", "전자상거래PG"),
    ("쿠팡쿠페이쿠팡쿠페이", "전자상거래PG"),
    ("쿠팡쿠페이나이스", "전자상거래PG"),
    ("카카오T주차주식회사카카오모빌리티", "전자상거래PG"),
    ("주차장KICC하이파킹", "전자상거래PG"),
    ("자판기코세스", "PG일반비인증"),
    ("교보문고인터넷문화비교보문고", "전자상거래PG"),
    ("당근페이당근페이", "전자상거래PG"),
    ("당근선물하기주식회사당근페이", "전자상거래PG상품권"),
    ("카카오선물하기카카오페이주식회사카카오", "전자상거래PG"),
    ("카카오MY구독주식회사카카오", "전자상거래PG"),
    ("네이버페이유니세프한국위원회", "전자상거래PG"),
    ("네이버페이메가MGC인증마포용강점메가MGC커피", "전자상거래PG"),
    ("데일리샷주데일리샷", "전자상거래PG"),
    ("자동결제주데일리샷", "전자상거래PG"),
    ("스마트로세외수입오프강서구청", "전자상거래PG"),
    # These are explicit domestic goods/services.  Their gateway label is
    # not a travel signal and must not hold them in 여행_미배정.
    ("더즌카카오페이주식회사더즌", "전자상거래PG"),
    ("주더즌카카오페이주식회사더즌", "전자상거래PG"),
    ("KCP결제대행주식회사스테이지파이브", "전자상거래PG"),
    ("KCP결제대행주스테이지파이브", "전자상거래PG"),
    ("카카오T간편결제나이스", "PG일반비인증"),
    ("KICC서울시현장서울특별시강서구시설", "전자상거래PG"),
    ("NICE결제대행4문토", "전자상거래PG"),
    ("PAYCO오더엔에이치엔페이코주식회사", "전자상거래PG"),
    ("PAYCO오더엔에이치엔페이코주", "전자상거래PG"),
    ("네이버페이2유니세프한국위원회", "전자상거래PG"),
    ("다우데이타키오스크주식회사스토리페이", "전자상거래PG"),
    ("대표구인증웰컴페이먼츠", "PG일반비인증"),
    ("선물하기쿠카카오페이주식회사카카오선물하기", "전자상거래PG상품권"),
    ("선물하기쿠카카오페이주카카오선물하기", "전자상거래PG상품권"),
    ("자판기1코세스", "PG일반비인증"),
    ("키오스크KICC2", "PG일반비인증"),
    ("키오스크KICC1한두파킹", "전자상거래PG"),
    ("토스페이컨텐츠주식회사비바리퍼블리카", "전자상거래PG"),
    ("토스페이컨텐츠주비바리퍼블리카", "전자상거래PG"),
    ("쿠팡쿠페이나이스", "PG일반비인증"),
    ("결제대행22나이스", "PG일반비인증"),
    ("KSNETN주코엠페이먼츠", "전자상거래PG"),
})

# These markers are intentionally narrower than country-only or currency
# inference.  They identify the unresolved rows in the Malaysia/Europe
# cohorts while leaving the same-card Singapore, Taiwan, and Japan rows out.
MALAYSIA_REGION_MARKERS = frozenset({
    "KUALALUMPUR", "MELAKA", "PAHANG", "BENTONG", "SEPANG",
    "PETALINGJAYA", "PUTRAJAYA", "GOMBAK", "WANGSAMAJU", "KUANTAN",
    "GEMAS", "MALAYSIA",
})
EUROPE_REGION_MARKERS = frozenset({
    "FIRENZE", "FLORENCE", "VENEZIA", "BOLOGNA", "SCANDICCI", "NICE",
})
MALAYSIA_TARGET = "0812_말레이시아"
EUROPE_TARGET = "5월_유럽"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper().strip()
    return re.sub(r"[^0-9A-Z가-힣]+", "", text)


def _adverse(value: object) -> bool:
    text = str(value or "").strip()
    return not text or any(token in text for token in ADVERSE_TOKENS)


def _provider(value: object) -> str:
    text = _norm(value)
    for name, tokens in (
        ("travelrover", ("TRAVELROVER", "트래블로버")),
        ("booking", ("BOOKING", "BKG")),
        ("agoda", ("AGODA", "아고다")),
        ("mytrip", ("MYTRIP", "마이트립")),
        ("trip", ("TRIPCOM", "트립닷컴")),
        ("gotogate", ("GOTOGATE", "고투게이트")),
        ("klook", ("KLOOK", "클룩")),
        ("airbnb", ("AIRBNB", "에어비앤비")),
        ("expedia", ("EXPEDIA", "익스피디아")),
        ("hotels", ("HOTELS.COM", "HOTELS")),
        ("rakuten_travel", ("RAKUTENTRAVEL", "라쿠텐트래블")),
    ):
        if any(_norm(token) in text for token in tokens):
            return name
    return ""


def _ota_service_period_target_path(match_kind: object) -> str:
    paths = {
        "exact": OTA_MAIL_SERVICE_PERIOD_EXACT_PATH,
        "target_invariant": OTA_MAIL_SERVICE_PERIOD_MN_PATH,
        "amount_tolerance_exact": OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH,
        "amount_tolerance_target_invariant": (
            OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH
        ),
    }
    try:
        return paths[str(match_kind)]
    except KeyError as exc:
        raise ValueError(f"ota_match_kind_invalid:{match_kind}") from exc


def _payment_gateway(row: dict[str, object]) -> bool:
    text = _norm(
        str(row.get("merchant") or "") + " " + str(row.get("biz") or "")
    )
    return any(token in text for token in (
        "PG", "전자상거래PG", "NICE", "나이스정보통신", "이니시스",
        "KCP", "KICC", "토스페이먼츠", "PAYCO",
    ))


def _known_direct_travel_service(row: dict[str, object]) -> bool:
    """Return only for explicit current merchant/product travel markers.

    This is intentionally narrower than a payment-gateway test.  The marker
    names a travel service or marketplace in the current card fact; a bare
    NICE/KCP/KICC/ARS row still has no travel classification here.
    """
    text = _norm(
        str(row.get("merchant") or "") + " " + str(row.get("biz") or "")
    )
    return any(_norm(token) in text for token in KNOWN_DIRECT_TRAVEL_TOKENS)


def _explicit_domestic_nontravel(row: dict[str, object]) -> bool:
    return (
        str(row.get("sub") or "") == "국내"
        and (
            _norm(row.get("merchant")), _norm(row.get("biz"))
        ) in EXPLICIT_DOMESTIC_NONTRAVEL
    )


def _feature_key(row: dict[str, object], name: str) -> tuple[str, ...]:
    source = str(row.get("source") or row.get("src") or "")
    merchant = _norm(row.get("merchant") or row.get("mer"))
    biz = _norm(row.get("biz"))
    currency = _norm(row.get("currency") or row.get("cur"))
    card4 = _norm(row.get("card4"))
    occurred = str(row.get("occurred_on") or row.get("use") or "")
    posted = str(row.get("posted_on") or row.get("post") or "")
    if name == "source_merchant_biz_currency":
        return source, merchant, biz, currency
    if name == "source_card_merchant":
        return source, card4, merchant
    if name == "source_merchant":
        return source, merchant
    if name == "use_merchant":
        return occurred, merchant
    if name == "posted_merchant":
        return posted, merchant
    if name == "source_month_merchant":
        return source, occurred[:7], merchant
    return merchant,


def _load_current(db: sqlite3.Connection, run_id: str) -> list[dict[str, object]]:
    rows = db.execute(
        """SELECT d.card_event_id || '#' || d.event_role,p.id,d.amount_krw,
                  p.source_system,p.occurred_on,p.posted_on,p.merchant,
                  p.approval_number,p.transaction_type,pm.last4,s.payload_json,
                  s.source_kind,s.source_key,s.source_sha256,e.evidence_id,
                  e.fact_sha256,p.external_key
           FROM direct_payment_projection_links l
           JOIN payment_transactions p ON p.id=l.payment_id
           JOIN direct_normalized_payments d ON d.id=l.direct_payment_id
           JOIN direct_source_records s ON s.id=d.source_record_id
           JOIN direct_promotion_evidence e
             ON e.run_id=l.run_id AND e.evidence_kind='current_card'
            AND e.authority_status='current_raw'
            AND e.direct_event_key=d.card_event_id || '#' || d.event_role
            AND e.source_kind=s.source_kind AND e.source_key=s.source_key
            AND e.source_sha256=s.source_sha256
           LEFT JOIN payment_methods pm ON pm.id=p.payment_method_id
           WHERE l.run_id=? ORDER BY 1""",
        (run_id,),
    ).fetchall()
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row[0])
        if key in seen:
            raise ValueError("high_classifier_current_event_duplicate")
        seen.add(key)
        try:
            payload = json.loads(str(row[10]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("high_classifier_current_payload_invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("high_classifier_current_payload_invalid")
        result.append({
            "direct_event_key": key,
            "payment_id": int(row[1]),
            "amount_krw": int(row[2]),
            "source": str(row[3]),
            "occurred_on": str(payload.get("use_date") or row[4] or ""),
            "posted_on": str(payload.get("post_date") or row[5] or ""),
            "merchant": str(payload.get("merchant") or row[6] or ""),
            "relation_merchant": str(row[6] or ""),
            "approval": str(payload.get("appr") or row[7] or ""),
            "original_approval": str(payload.get("orig_appr") or ""),
            "transaction_type": str(row[8]),
            "card4": str(payload.get("card4") or row[9] or ""),
            "biz": str(payload.get("biz") or ""),
            "currency": str(payload.get("currency") or ""),
            "foreign": str(payload.get("foreign") or ""),
            "sub": str(payload.get("sub") or ""),
            "source_kind": str(row[11]),
            "source_key": str(row[12]),
            "source_sha256": str(row[13]),
            "current_evidence_id": str(row[14]),
            "current_fact_sha256": str(row[15]),
            "external_key": str(row[16]),
        })
    return result


def _manual_date(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for separator in (".", "/"):
        text = text.replace(separator, "-")
    parts = text.split("-")
    try:
        if len(parts) == 3 and len(parts[0]) == 2:
            parsed = date(2000 + int(parts[0]), int(parts[1]), int(parts[2]))
        elif len(parts) == 3 and len(parts[0]) == 4:
            parsed = date(int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            return None
    except (TypeError, ValueError):
        return None
    return parsed.isoformat()


def _manual_amount(value: object) -> int | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if amount != amount.to_integral_value():
        return None
    parsed = int(amount)
    return parsed if parsed != 0 else None


def _manual_match_key(row: dict[str, object]) -> tuple[str, str, int] | None:
    source = str(row.get("source") or row.get("src") or "").strip().upper()
    occurred_on = str(row.get("occurred_on") or row.get("use") or "").strip()
    try:
        amount = abs(int(row.get("amount_krw") or 0))
    except (TypeError, ValueError):
        return None
    if not source or not occurred_on or amount <= 0:
        return None
    return source, occurred_on, amount


def _load_manual_travel_index(
    db: sqlite3.Connection,
    valid_targets: set[str],
) -> tuple[
    dict[tuple[str, str, int], list[dict[str, object]]],
    dict[tuple[str, int], list[dict[str, object]]],
    list[dict[str, str]],
    str,
]:
    """Index valid manual travel-tab rows by date and amount components.

    The full manual source manifest is returned separately so a skipped row
    cannot silently change the input contract.  Manual sign is retained only
    for audit; the travel-tab classification itself may label a current
    purchase or reversal.  The current-card row remains the transaction fact.
    """
    rows = db.execute(
        """SELECT source_key,source_sha256,payload_json
           FROM direct_source_records
           WHERE source_kind='manual_ledger' ORDER BY source_key"""
    ).fetchall()
    index: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    amount_index: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    manifest: list[dict[str, str]] = []
    for source_key, source_sha256, payload_json in rows:
        source_key_text = str(source_key)
        source_sha_text = str(source_sha256)
        manifest.append({
            "source_key": source_key_text,
            "source_sha256": source_sha_text,
        })
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("manual_travel_payload_invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("manual_travel_payload_invalid")
        tab = str(payload.get("tab") or "").strip()
        manual_date = _manual_date(payload.get("date"))
        manual_amount = _manual_amount(payload.get("amount"))
        card_label = str(payload.get("card") or "").strip()
        sources = MANUAL_CARD_SOURCES.get(card_label, frozenset())
        if (
            not tab or tab not in valid_targets or manual_date is None
            or manual_amount is None or not sources
        ):
            continue
        item = {
            "manual_source_key": source_key_text,
            "manual_source_sha256": source_sha_text,
            "manual_tab": tab,
            "manual_row": str(payload.get("row") or ""),
            "manual_item": str(payload.get("item") or "").strip(),
            "manual_date": manual_date,
            "manual_amount_krw": abs(manual_amount),
            "manual_amount_sign": "positive" if manual_amount > 0 else "negative",
            "manual_card": card_label,
        }
        for source in sources:
            index[(source, manual_date, abs(manual_amount))].append(item)
            amount_index[(source, abs(manual_amount))].append(item)
    manifest.sort(key=lambda item: (item["source_key"], item["source_sha256"]))
    return index, amount_index, manifest, _sha(manifest)


def _manual_travel_match(
    row: dict[str, object],
    manual_index: dict[tuple[str, str, int], list[dict[str, object]]],
    current_purchase_key_counts: Counter[tuple[str, str, int]],
) -> dict[str, object] | None:
    """Return an exact or ambiguous manual-tab classification hint.

    A single current key and a single manual row are required globally.  The
    sign of the manual row is deliberately not used as transaction evidence;
    it is only retained in the audit payload.
    """
    key = _manual_match_key(row)
    if key is None or str(row.get("transaction_type") or "") not in {
        "purchase", *REVERSAL_TYPES,
    }:
        return None
    matches = list(manual_index.get(key, []))
    if not matches:
        return None
    # The issuer/date/amount key can be M:N.  When the current card merchant
    # and the manual travel-tab item identify one side of that component, use
    # the item only as classification evidence.  It never asserts that the
    # manual row is the payment or its transaction evidence.
    current_merchant = _norm(row.get("merchant") or "")
    if current_merchant:
        merchant_discriminated = [
            item for item in matches
            if _norm(item.get("manual_item") or "")
            and (
                _norm(item.get("manual_item") or "") in current_merchant
                or current_merchant in _norm(item.get("manual_item") or "")
            )
        ]
        if merchant_discriminated:
            matches = merchant_discriminated
    target_codes = {
        str(item.get("manual_tab") or "") for item in matches
        if str(item.get("manual_tab") or "")
    }
    if current_purchase_key_counts.get(key, 0) == 1 and len(matches) == 1:
        status = "exact"
    elif len(target_codes) == 1:
        # Several current rows and/or several manual rows can still be a
        # closed M:N *classification* component when every manual candidate
        # points to the same travel tab.  This never asserts a row-by-row
        # transaction pairing and does not make the manual row evidence of
        # payment, cancellation, or amount.
        status = "target_invariant"
    else:
        status = "ambiguous"
    result: dict[str, object] = {
        "status": status,
        "source": key[0],
        "occurred_on": key[1],
        "amount_krw": key[2],
        "matches": sorted(
            matches,
            key=lambda item: (
                str(item["manual_source_key"]),
                str(item["manual_source_sha256"]),
            ),
        ),
    }
    if current_merchant:
        result["merchant_discriminator"] = {
            "current_merchant": current_merchant,
            "manual_items": sorted({
                _norm(item.get("manual_item") or "")
                for item in matches
                if _norm(item.get("manual_item") or "")
            }),
        }
    if status in {"exact", "target_invariant"}:
        result["target"] = next(iter(target_codes))
    return result


def _manual_travel_amount_component_match(
    row: dict[str, object],
    manual_amount_index: dict[tuple[str, int], list[dict[str, object]]],
    current_amount_key_counts: Counter[tuple[str, int]],
) -> dict[str, object] | None:
    """Return a date-independent manual *target* classification component.

    OTA and other prepayments can be posted on a date different from the
    travel-tab date.  A manual row may therefore classify the travel target
    without being a transaction proof.  This path uses the current card's
    source and amount to find the component, optionally narrows it by the
    current-card merchant token, and admits it only when every remaining
    manual row names one target.  It never runs for a reversal and never
    asserts a row-to-row payment match.
    """
    if str(row.get("transaction_type") or "") != "purchase":
        return None
    try:
        amount = abs(int(row.get("amount_krw") or 0))
    except (TypeError, ValueError):
        return None
    source = str(row.get("source") or "").strip().upper()
    if not source or amount <= 0:
        return None
    key = (source, amount)
    matches = list(manual_amount_index.get(key, []))
    if not matches:
        return None
    current_merchant = _norm(row.get("merchant") or "")
    if current_merchant:
        merchant_discriminated = [
            item for item in matches
            if _norm(item.get("manual_item") or "")
            and (
                _norm(item.get("manual_item") or "") in current_merchant
                or current_merchant in _norm(item.get("manual_item") or "")
            )
        ]
        if merchant_discriminated:
            matches = merchant_discriminated
    target_codes = {
        str(item.get("manual_tab") or "") for item in matches
        if str(item.get("manual_tab") or "")
    }
    if len(target_codes) != 1:
        return None
    current_count = int(current_amount_key_counts.get(key, 0))
    status = (
        "amount_component_exact"
        if current_count == 1 and len(matches) == 1
        else "amount_component_target_invariant"
    )
    result: dict[str, object] = {
        "status": status,
        "match_scope": "source_absolute_amount_component",
        "source": source,
        "amount_krw": amount,
        "matches": sorted(
            matches,
            key=lambda item: (
                str(item["manual_source_key"]),
                str(item["manual_source_sha256"]),
            ),
        ),
        "target": next(iter(target_codes)),
        "current_component_count": current_count,
        "manual_component_target_count": len(target_codes),
        "payment_date_used_as_service_date": False,
        "individual_payment_pair_asserted": False,
    }
    if current_merchant:
        result["merchant_discriminator"] = {
            "current_merchant": current_merchant,
            "manual_items": sorted({
                _norm(item.get("manual_item") or "")
                for item in matches
                if _norm(item.get("manual_item") or "")
            }),
        }
    return result


def _load_ota_mail_records(
    db: sqlite3.Connection,
) -> list[dict[str, object]]:
    """Load the redacted OTA mail index as content-addressed evidence.

    The index is intentionally used only to close a classification component.
    It never replaces a card amount, creates a booking relation, or becomes a
    promotion-evidence row.
    """
    records: list[dict[str, object]] = []
    for source_kind, source_key, source_sha256, payload_json in db.execute(
        """SELECT source_kind,source_key,source_sha256,payload_json
           FROM direct_source_records
           WHERE source_kind IN ('ota_mail','ota_mail_live')
           ORDER BY source_kind,source_key"""
    ).fetchall():
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("ota_mail_payload_invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("ota_mail_payload_invalid")
        records.append({
            "source_kind": str(source_kind),
            "source_key": str(source_key),
            "source_sha256": str(source_sha256),
            "payload": payload,
        })
    if not records:
        raise ValueError("ota_mail_source_missing")
    return records


def _ota_mail_mmdd(payload: dict[str, object]) -> set[str]:
    result: set[str] = set()
    values = payload.get("travel_date_candidates", [])
    if not isinstance(values, (list, tuple)):
        return result
    for value in values:
        text = str(value or "").strip()
        if re.fullmatch(r"\d{4}", text):
            result.add(text)
    return result


def _ota_mail_sent_date(payload: dict[str, object]) -> date | None:
    value = str(payload.get("sent_at") or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _ota_mail_full_dates(payload: dict[str, object]) -> set[date]:
    result: set[date] = set()
    values = payload.get("travel_date_candidates", [])
    if not isinstance(values, (list, tuple)):
        return result
    for value in values:
        text = str(value or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            continue
        try:
            result.add(date.fromisoformat(text))
        except ValueError:
            continue
    return result


def _ota_mail_service_years(payload: dict[str, object]) -> set[int]:
    """Return only years supported by mail metadata.

    A bare MMDD is not a service year.  Inferring the year from the message
    sent date (or from the card payment date) can turn a 2025 booking into a
    2026 target.  Only explicit years derived from the mail metadata are
    admitted here; ISO service dates are handled separately by
    ``_ota_mail_full_dates``.
    """
    explicit = payload.get("service_year_candidates", [])
    years = {
        int(value) for value in explicit
        if type(value) is int and 2020 <= int(value) <= 2100
    } if isinstance(explicit, (list, tuple)) else set()
    return years


def _ota_mail_date_variants(payload: dict[str, object]) -> list[set[date]]:
    """Build strict service-date interpretations without using payment date.

    Some exports repeat the message sent day among the MMDD candidates.  We
    test the complete set and, only when that exact sent-day candidate is
    present, a second set with that one metadata date removed.  A target is
    accepted only if all surviving interpretations agree.
    """
    full_dates = _ota_mail_full_dates(payload)
    mmdd = _ota_mail_mmdd(payload)
    years = _ota_mail_service_years(payload)
    variants: list[set[str] | set[date]] = []
    raw_values = set(mmdd)
    # An ISO service date is already year-qualified.  Do not replace it with
    # a weaker MMDD interpretation when an export happens to contain both.
    if full_dates:
        variants.append(full_dates)
    elif raw_values:
        variants.append(raw_values)
        sent = _ota_mail_sent_date(payload)
        if sent is not None and f"{sent.month:02d}{sent.day:02d}" in raw_values:
            trimmed = raw_values - {f"{sent.month:02d}{sent.day:02d}"}
            if trimmed:
                variants.append(trimmed)
    elif full_dates:
        variants.append(full_dates)
    results: list[set[date]] = []
    sent = _ota_mail_sent_date(payload)
    for values in variants:
        if isinstance(values, set) and all(isinstance(item, date) for item in values):
            if values and (sent is None or all(item >= sent for item in values)):
                results.append(set(values))
            continue
        assert isinstance(values, set)
        for year in years:
            service_dates: set[date] = set()
            for value in values:
                try:
                    service_dates.add(date(year, int(value[:2]), int(value[2:])))
                except (TypeError, ValueError):
                    service_dates = set()
                    break
            if service_dates and (
                sent is None or all(item >= sent for item in service_dates)
            ):
                results.append(service_dates)
    return results


def _ota_mail_amounts(payload: dict[str, object]) -> set[int]:
    result: set[int] = set()
    values = payload.get("amount_candidates", [])
    if not isinstance(values, (list, tuple)):
        return result
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            result.add(abs(int(value)))
        except (TypeError, ValueError):
            continue
    return result


def _ota_mail_schedule_targets(
    payload: dict[str, object],
    schedule: dict[str, dict[str, object]],
) -> set[str]:
    """Return canonical targets containing every typed OTA service date.

    The mail index stores month/day candidates.  It is intentionally not
    enough to see one date in a trip window: every candidate date must fit
    the same window, and the result must be unique.  This keeps a payment
    date from being reused as a service date and avoids picking one side of
    overlapping schedule windows.
    """
    interpretations = _ota_mail_date_variants(payload)
    if not interpretations:
        return set()
    interpretation_matches: list[set[str]] = []
    for dates in interpretations:
        matches: set[str] = set()
        for target, trip in schedule.items():
            years = {service_day.year for service_day in dates}
            if len(years) != 1:
                continue
            year = next(iter(years))
            try:
                service_year = int(trip.get("service_year", 2026))
                if service_year != year:
                    continue
                start = date(
                    service_year, int(trip["mm"]), int(trip["dd"]),
                )
                end = start + timedelta(days=int(trip["window"]) - 1)
            except (KeyError, TypeError, ValueError):
                continue
            if all(start <= service_day <= end for service_day in dates):
                matches.add(str(target))
        if len(matches) == 1:
            interpretation_matches.append(matches)
    # Every allowed interpretation must resolve uniquely.  Ignoring a
    # no-match interpretation and intersecting only the successful ones would
    # silently accept a mismatch-only export variant.
    if len(interpretation_matches) != len(interpretations):
        return set()
    if not interpretation_matches:
        return set()
    common = set.intersection(*interpretation_matches)
    return common if len(common) == 1 else set()


def _ota_mail_sent_sort_key(record: dict[str, object]) -> tuple[str, str]:
    payload = record.get("payload")
    sent_at = str(payload.get("sent_at") or "") if isinstance(payload, dict) else ""
    return sent_at, str(record.get("source_key") or "")


def _ota_mail_identity(record: dict[str, object]) -> tuple[str, ...]:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return (str(record.get("source_key") or ""),)
    provider = str(payload.get("provider") or "").lower()
    references = payload.get("booking_ref_candidates", [])
    if isinstance(references, (list, tuple)):
        refs = tuple(sorted({str(value) for value in references if str(value)}))
    else:
        refs = ()
    if refs:
        return (provider, "booking", *refs)
    message_id = str(payload.get("message_id") or record.get("source_key") or "")
    return (provider, "message", message_id)


def _ota_mail_reference_tokens(record: dict[str, object]) -> set[tuple[str, str, str]]:
    """Return lifecycle-link keys without retaining message content."""
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return set()
    provider = str(payload.get("provider") or "").lower()
    if not provider:
        return set()
    tokens: set[tuple[str, str, str]] = set()
    for field, kind in (
        ("booking_ref_candidates", "booking"),
        ("pnr_candidates", "pnr"),
    ):
        values = payload.get(field, [])
        if isinstance(values, (list, tuple)):
            tokens.update(
                (provider, kind, str(value))
                for value in values
                if str(value)
            )
    if not tokens:
        message_id = str(
            payload.get("message_id") or record.get("source_key") or ""
        )
        if message_id:
            tokens.add((provider, "message", message_id))
    return tokens


def _ota_mail_component_groups(
    records: Iterable[dict[str, object]],
) -> list[tuple[tuple[str, ...], list[dict[str, object]]]]:
    """Build connected booking/PNR lifecycle components.

    A refreshed mail can expose ``{A,B}`` while an earlier or later message
    exposes only ``{A}``.  Grouping by the complete reference tuple splits
    those messages and makes a later cancellation invisible.  Unioning
    overlapping booking references and PNRs keeps one lifecycle component
    while still keeping providers separate.
    """
    items = list(records)
    parent = list(range(len(items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    token_owner: dict[tuple[str, str, str], int] = {}
    for index, record in enumerate(items):
        for token in sorted(_ota_mail_reference_tokens(record)):
            previous = token_owner.get(token)
            if previous is not None:
                union(index, previous)
            else:
                token_owner[token] = index

    components: dict[int, list[dict[str, object]]] = defaultdict(list)
    for index, record in enumerate(items):
        components[find(index)].append(record)
    result: list[tuple[tuple[str, ...], list[dict[str, object]]]] = []
    for records_in_component in components.values():
        ordered = sorted(records_in_component, key=_ota_mail_sent_sort_key)
        provider = str(
            (ordered[0].get("payload") or {}).get("provider") or ""
        ).lower()
        component_id = (
            provider,
            "component",
            _sha(sorted(str(item.get("source_key") or "") for item in ordered)),
        )
        result.append((component_id, ordered))
    result.sort(key=lambda item: item[0])
    return result


def _ota_provider_family(value: object) -> str:
    provider = str(value or "").lower()
    # The card feed records the Mytrip/GoToGate confirmations under the
    # shared GoToGate Korea billing merchant.  Treat that pair as one
    # narrowly documented billing family.  Trip.com itself remains separate.
    if provider in {"mytrip", "gotogate"}:
        return "mytrip_gotogate_billing"
    return "trip" if provider == "trip" else provider


def _build_ota_mail_service_period_targets(
    current: Iterable[dict[str, object]],
    baseline_by_payment: dict[int, tuple[str, str, str]],
    ota_mail_records: Iterable[dict[str, object]],
    schedule: dict[str, dict[str, object]],
) -> dict[int, dict[str, object]]:
    """Close unique current-card/OTA-mail service-period components.

    A one-row component needs one provider-compatible mail record, an exact
    absolute KRW amount or one uniquely identified amount within the explicit
    two-percent card-tolerance policy, and one canonical schedule target.  An
    M:N component is admitted only when the card and mail sides have the same
    cardinality and all service periods resolve to the same target; it never
    claims a row-to-row pairing.  Exact matches are preferred over tolerant
    matches.  A tolerant match is rejected when a mail contains more than one
    amount candidate within the tolerance band.  Mail records with the same
    booking reference are deduplicated so a refreshed copy cannot inflate
    cardinality.
    """
    grouped: dict[tuple[str, str, int, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in current:
        payment_id = int(row.get("payment_id") or 0)
        baseline = baseline_by_payment.get(payment_id)
        if (
            str(row.get("transaction_type") or "") == "purchase"
            and int(row.get("amount_krw") or 0) > 0
            and baseline is not None
            and baseline[0] == TRIP_UNASSIGNED
        ):
            provider = _provider(row.get("merchant"))
            if not provider:
                continue
            grouped[
                (
                    str(row.get("source") or ""),
                    str(row.get("occurred_on") or ""),
                    abs(int(row.get("amount_krw") or 0)),
                    str(row.get("card4") or ""),
                    _ota_provider_family(provider),
                )
            ].append(row)

    # A booking identity can have confirmation, change, and follow-up
    # messages.  Use the latest lifecycle state for cancellation, and the
    # latest *non-empty* typed service/amount facts for an active booking.
    # Follow-up messages often contain no dates or amount at all; treating
    # those as a replacement was the reason many known OTA reservations fell
    # back to ``행사기간미상``.
    all_records: list[dict[str, object]] = []
    for record in ota_mail_records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if not str(payload.get("provider") or "").strip():
            continue
        all_records.append(record)
    canonical_records: list[dict[str, object]] = []
    for identity, ordered in _ota_mail_component_groups(all_records):
        lifecycle_latest = ordered[-1]
        if str(lifecycle_latest["payload"].get("message_status") or "") in {
            "cancel", "refund",
        }:
            continue
        service_record = next(
            (
                item for item in reversed(ordered)
                if _ota_mail_date_variants(item["payload"])
            ),
            None,
        )
        amount_record = next(
            (
                item for item in reversed(ordered)
                if _ota_mail_amounts(item["payload"])
            ),
            None,
        )
        if service_record is None or amount_record is None:
            continue
        payload = service_record["payload"]
        targets = _ota_mail_schedule_targets(payload, schedule)
        amounts = _ota_mail_amounts(amount_record["payload"])
        if len(targets) != 1 or not amounts:
            continue
        mail_years = _ota_mail_service_years(payload)
        mail_years.update(
            value.year for value in _ota_mail_full_dates(payload)
        )
        mail_service_year = (
            next(iter(mail_years)) if len(mail_years) == 1 else None
        )
        canonical_records.append({
            "identity": identity,
            "source_key": str(service_record.get("source_key") or ""),
            "source_sha256": str(service_record.get("source_sha256") or ""),
            "amount_source_key": str(amount_record.get("source_key") or ""),
            "amount_source_sha256": str(
                amount_record.get("source_sha256") or ""
            ),
            "provider": _ota_provider_family(payload.get("provider")),
            "amounts": sorted(amounts),
            "travel_dates": sorted(
                str(value) for value in payload.get(
                    "travel_date_candidates", []
                )
            ),
            "service_year": mail_service_year,
            "service_year_candidates": sorted(mail_years),
            "target": next(iter(targets)),
            "lifecycle_latest_source_key": str(
                lifecycle_latest.get("source_key") or ""
            ),
            "lifecycle_latest_source_sha256": str(
                lifecycle_latest.get("source_sha256") or ""
            ),
            "lifecycle_latest_status": str(
                lifecycle_latest["payload"].get("message_status") or "unknown"
            ),
            "lifecycle_parser_version": str(
                payload.get("lifecycle_parser_version")
                or OTA_LIFECYCLE_PARSER_VERSION
            ),
            "message_status_rule_version": str(
                payload.get("message_status_rule_version")
                or OTA_STATUS_RULE_VERSION
            ),
            "message_template_class": str(
                payload.get("message_template_class")
                or payload.get("message_status")
                or "unknown"
            ),
            "message_hash": str(payload.get("message_hash") or ""),
        })

    def amount_match(
        record: dict[str, object], card_amount: int,
    ) -> dict[str, object] | None:
        amounts = sorted({
            abs(int(value)) for value in record.get("amounts", [])
            if isinstance(value, int) and value > 0
        })
        if card_amount in amounts:
            return {
                "method": "exact",
                "matched_amount_krw": card_amount,
                "difference_ratio": 0.0,
            }
        near = [
            (value, abs(card_amount - value) / value)
            for value in amounts
            if abs(card_amount - value) <= value * OTA_AMOUNT_TOLERANCE_RATIO
        ]
        # A mail with two equally plausible amount fields is not safe to use
        # for a tolerant match.  This preserves the old fail-closed behavior
        # for subtotal/tax/total mixtures and incidental amounts.
        if len(near) != 1:
            return None
        matched_amount, difference_ratio = near[0]
        return {
            "method": OTA_AMOUNT_TOLERANCE_POLICY,
            "matched_amount_krw": matched_amount,
            "difference_ratio": round(difference_ratio, 12),
        }

    candidate_components: list[
        tuple[
            tuple[str, str, int, str, str],
            list[dict[str, object]],
            list[dict[str, object]],
        ]
    ] = []
    for group_key, rows in sorted(grouped.items()):
        _, _, amount, _, provider = group_key
        possible: dict[tuple[str, ...], tuple[dict[str, object], dict[str, object]]] = {}
        for record in canonical_records:
            if record["provider"] != provider:
                continue
            match = amount_match(record, amount)
            if match is not None:
                possible[record["identity"]] = (record, match)
        exact = [
            item for item in possible.values()
            if item[1]["method"] == "exact"
        ]
        selected = exact if exact else list(possible.values())
        selected.sort(key=lambda item: item[0]["identity"])
        if len(selected) != len(rows) or not selected:
            continue
        if len({str(item[0]["target"]) for item in selected}) != 1:
            continue
        candidate_components.append((
            group_key,
            rows,
            [
                {
                    **record,
                    "_amount_match": match,
                }
                for record, match in selected
            ],
        ))

    # A mail record cannot silently support two independent card components.
    record_groups: dict[tuple[str, ...], set[int]] = defaultdict(set)
    for index, (_, _, matches) in enumerate(candidate_components):
        for record in matches:
            record_groups[record["identity"]].add(index)

    result: dict[int, dict[str, object]] = {}
    for index, (group_key, rows, matches) in enumerate(candidate_components):
        if any(record_groups[record["identity"]] != {index} for record in matches):
            continue
        target = str(matches[0]["target"])
        service_years = {
            int(record["service_year"])
            for record in matches
            if type(record.get("service_year")) is int
        }
        service_year = (
            next(iter(service_years)) if len(service_years) == 1 else None
        )
        amount_method = str(
            (matches[0].get("_amount_match") or {}).get("method") or ""
        )
        tolerant = amount_method == OTA_AMOUNT_TOLERANCE_POLICY
        match_kind = (
            "amount_tolerance_exact" if tolerant and len(rows) == 1 else
            "amount_tolerance_target_invariant" if tolerant else
            "exact" if len(rows) == 1 else "target_invariant"
        )
        audit_records = [
            {
                "source_kind": "ota_mail",
                "source_key": str(record["source_key"]),
                "source_sha256": str(record["source_sha256"]),
                "amount_source_key": str(record.get("amount_source_key") or ""),
                "amount_source_sha256": str(
                    record.get("amount_source_sha256") or ""
                ),
                "provider": str(record["provider"]),
                "amount_candidates": list(record["amounts"]),
                "amount_match_method": str(
                    (record.get("_amount_match") or {}).get("method") or ""
                ),
                "card_amount_krw": int(group_key[2]),
                "matched_amount_krw": int(
                    (record.get("_amount_match") or {}).get(
                        "matched_amount_krw", 0
                    )
                ),
                "amount_difference_ratio": float(
                    (record.get("_amount_match") or {}).get(
                        "difference_ratio", 0.0
                    )
                ),
                "travel_date_candidates": list(record["travel_dates"]),
                "service_year": service_year,
                "service_year_candidates": list(
                    record.get("service_year_candidates") or []
                ),
                "canonical_target": target,
                "lifecycle_latest_source_key": str(
                    record.get("lifecycle_latest_source_key") or ""
                ),
                "lifecycle_latest_source_sha256": str(
                    record.get("lifecycle_latest_source_sha256") or ""
                ),
                "lifecycle_latest_status": str(
                    record.get("lifecycle_latest_status") or "unknown"
                ),
                "lifecycle_parser_version": str(
                    record.get("lifecycle_parser_version")
                    or OTA_LIFECYCLE_PARSER_VERSION
                ),
                "message_status_rule_version": str(
                    record.get("message_status_rule_version")
                    or OTA_STATUS_RULE_VERSION
                ),
                "message_template_class": str(
                    record.get("message_template_class") or "unknown"
                ),
                "message_hash": str(record.get("message_hash") or ""),
            }
            for record in matches
        ]
        for row in rows:
            result[int(row["payment_id"])] = {
                "target_code": target,
                "match_kind": match_kind,
                "amount_match_method": amount_method,
                "card_amount_krw": int(group_key[2]),
                "matched_amounts_krw": sorted({
                    int((record.get("_amount_match") or {}).get(
                        "matched_amount_krw", 0
                    ))
                    for record in matches
                }),
                "amount_difference_ratio": max(
                    float((record.get("_amount_match") or {}).get(
                        "difference_ratio", 0.0
                    ))
                    for record in matches
                ),
                "amount_tolerance_ratio": OTA_AMOUNT_TOLERANCE_RATIO,
                "amount_tolerance_policy": OTA_AMOUNT_TOLERANCE_POLICY,
                "provider": str(group_key[4]),
                "card_amount_krw": int(group_key[2]),
                "service_dates": sorted({
                    value for record in matches for value in record["travel_dates"]
                }),
                "service_year": service_year,
                "evidence_records": audit_records,
                "card_payment_ids": sorted(int(item["payment_id"]) for item in rows),
                "mail_identities": [list(record["identity"]) for record in matches],
            }
    return result


def _current_source_reference(row: dict[str, object]) -> dict[str, str]:
    return {
        "source_kind": str(row.get("source_kind") or ""),
        "source_key": str(row.get("source_key") or ""),
        "source_sha256": str(row.get("source_sha256") or ""),
        "direct_event_key": str(row.get("direct_event_key") or ""),
        "current_fact_sha256": str(row.get("current_fact_sha256") or ""),
    }


def _row_year(row: dict[str, object]) -> int | None:
    value = row.get("occurred_on")
    if isinstance(value, date):
        return value.year
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text[:10]).year
    except (TypeError, ValueError):
        return None


def _explicit_service_years(ref: dict[str, object]) -> set[int]:
    """Read only years explicitly carried by an external mail fact.

    MMDD values are intentionally ignored unless the mail index also stores
    ``service_year``.  The year is never inferred from the card payment or
    from a message sent date.
    """

    years: set[int] = set()
    service_year = ref.get("service_year")
    if type(service_year) is int and 2020 <= service_year <= 2100:
        years.add(service_year)
    elif isinstance(service_year, str) and service_year.isdigit():
        parsed = int(service_year)
        if 2020 <= parsed <= 2100:
            years.add(parsed)
    for key in ("service_start", "service_end"):
        value = str(ref.get(key) or "").strip()
        try:
            years.add(date.fromisoformat(value[:10]).year)
        except (TypeError, ValueError):
            continue
    for key in ("service_date_candidates", "travel_date_candidates"):
        values = ref.get(key, ())
        if not isinstance(values, (list, tuple, set)):
            continue
        for value in values:
            text = str(value or "").strip()
            if not re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}", text):
                continue
            try:
                years.add(date.fromisoformat(text).year)
            except ValueError:
                continue
    return years


def _mail_service_period_2026_verified(
    target: str,
    target_path: str,
    target_refs: Iterable[dict[str, object]],
) -> tuple[bool, list[str]]:
    """Return whether a target is backed by one explicit 2026 mail period."""

    if target_path not in MAIL_SERVICE_TARGET_PATHS:
        return False, []
    source_kinds: set[str] = set()
    for ref in target_refs:
        if not isinstance(ref, dict):
            continue
        source_kind = str(ref.get("source_kind") or "")
        if source_kind not in MAIL_SERVICE_SOURCE_KINDS:
            continue
        role = str(ref.get("evidence_role") or "")
        if role not in {
            "ota_service_period",
            "gmail_payment_evidence",
            "inferred_target_context",
        }:
            continue
        ref_target = str(
            ref.get("target_code")
            or ref.get("canonical_target")
            or ""
        )
        if ref_target and ref_target != target:
            continue
        years = _explicit_service_years(ref)
        if years == {2026}:
            source_kinds.add(source_kind)
    return bool(source_kinds), sorted(source_kinds)


def _axis_evidence(
    row: dict[str, object],
    *,
    account: str,
    cost_type: str,
    target: str,
    account_path: str,
    target_path: str,
    target_evidence_source: str,
    manual_match: dict[str, object] | None = None,
    ota_service_target: dict[str, object] | None = None,
    geographic_context: Iterable[dict[str, object]] = (),
    target_registry: dict[str, object] | None = None,
    inferred_target: dict[str, object] | None = None,
    gmail_evidence: dict[str, object] | None = None,
    owner_decision: dict[str, object] | None = None,
    reversal_inheritance: str = "",
    admitted_rule_paths: Iterable[str] = (),
) -> dict[str, object]:
    """Serialize auditable evidence for all three active classification axes.

    The current card is always the transaction fact.  Other sources can
    support only the target-classification axis and are labelled by role.  In
    particular, a manual travel tab is strong target classification authority
    under the current owner policy, but it can never prove the card amount,
    sign, merchant, approval, or a card-to-row transaction relation.
    """
    admitted_paths = normalize_admitted_rule_paths(admitted_rule_paths)
    current_ref = _current_source_reference(row)
    target_refs: list[dict[str, object]] = []

    def add_ref(
        source_kind: object,
        source_key: object,
        source_sha256: object,
        role: str,
        **extra: object,
    ) -> None:
        source_kind_text = str(source_kind or "")
        source_key_text = str(source_key or "")
        source_sha_text = str(source_sha256 or "")
        if not source_kind_text or not source_key_text or len(source_sha_text) != 64:
            return
        ref: dict[str, object] = {
            "source_kind": source_kind_text,
            "source_key": source_key_text,
            "source_sha256": source_sha_text,
            "evidence_role": role,
        }
        ref.update(extra)
        target_refs.append(ref)

    # The card fact is attached to every target decision as the transaction
    # anchor, but it is not silently upgraded to a service-period proof.
    add_ref(
        current_ref["source_kind"], current_ref["source_key"],
        current_ref["source_sha256"], "current_card_transaction_fact",
        direct_event_key=current_ref["direct_event_key"],
        current_fact_sha256=current_ref["current_fact_sha256"],
    )
    if isinstance(manual_match, dict):
        for item in manual_match.get("matches", []):
            if not isinstance(item, dict):
                continue
            add_ref(
                "manual_ledger", item.get("manual_source_key"),
                item.get("manual_source_sha256"),
                "classification_target_only",
                target_code=str(item.get("manual_tab") or ""),
            )
    if isinstance(ota_service_target, dict):
        for item in ota_service_target.get("evidence_records", []):
            if not isinstance(item, dict):
                continue
            add_ref(
                item.get("source_kind"), item.get("source_key"),
                item.get("source_sha256"), "ota_service_period",
                amount_match_method=str(
                    item.get("amount_match_method") or ""
                ),
                amount_difference_ratio=item.get(
                    "amount_difference_ratio", 0.0
                ),
                lifecycle_latest_status=str(
                    item.get("lifecycle_latest_status") or ""
                ),
                travel_date_candidates=list(
                    item.get("travel_date_candidates") or []
                ),
                service_year=item.get("service_year"),
                canonical_target=str(item.get("canonical_target") or ""),
            )
            add_ref(
                item.get("source_kind"), item.get("amount_source_key"),
                item.get("amount_source_sha256"), "ota_amount_fact",
                service_source_key=str(item.get("source_key") or ""),
            )
            add_ref(
                item.get("source_kind"), item.get("lifecycle_latest_source_key"),
                item.get("lifecycle_latest_source_sha256"),
                "ota_lifecycle_latest",
                service_source_key=str(item.get("source_key") or ""),
                lifecycle_latest_status=str(
                    item.get("lifecycle_latest_status") or ""
                ),
            )
    if isinstance(inferred_target, dict):
        for item in [
            *inferred_target.get("evidence_records", []),
            *inferred_target.get("anchor_records", []),
        ]:
            if not isinstance(item, dict):
                continue
            add_ref(
                item.get("source_kind"), item.get("source_key"),
                item.get("source_sha256"), "inferred_target_context",
                service_start=str(item.get("service_start") or ""),
                service_end=str(item.get("service_end") or ""),
                service_year=item.get("service_year"),
                target_code=str(
                    item.get("target_code") or item.get("canonical_target") or ""
                ),
            )
    if target_registry is not None:
        add_ref(
            "trip_cluster_registry", target_registry.get("registry_id"),
            target_registry.get("registry_sha256"), "target_registry",
            target_code=str(target_registry.get("target_code") or ""),
            target_kind=str(target_registry.get("target_kind") or ""),
        )
    for item in geographic_context:
        if not isinstance(item, dict) or str(item.get("tab") or "") != target:
            continue
        add_ref(
            "geographic_trip_context", item.get("tab"),
            item.get("source_sha256"), "historical_context_only",
            transaction_evidence_allowed=bool(
                item.get("transaction_evidence_allowed")
            ),
        )
    if isinstance(owner_decision, dict):
        add_ref(
            "current_owner_decision", owner_decision.get("decision_id"),
            owner_decision.get("source_sha256"), "owner_scope_decision",
        )
    if isinstance(gmail_evidence, dict):
        source_kind = str(gmail_evidence.get("source_kind") or "")
        if not source_kind and gmail_evidence.get("evidence_kind"):
            source_kind = "gmail_payment_snapshot"
        source_key = str(
            gmail_evidence.get("source_key") or "gmail-payment-snapshot"
        )
        add_ref(
            source_kind,
            source_key,
            gmail_evidence.get("source_digest"),
            "gmail_payment_evidence",
            service_start=str(gmail_evidence.get("service_start") or ""),
            service_end=str(gmail_evidence.get("service_end") or ""),
            service_evidence_key=str(
                gmail_evidence.get("service_evidence_key") or ""
            ),
            target_code=str(gmail_evidence.get("target_hint") or ""),
        )

    # Keep references deterministic and avoid duplicating the card fact when
    # an independent evidence family also copied it as an anchor.
    ref_by_key = {
        json.dumps(
            {key: value for key, value in item.items()
             if key in {"source_kind", "source_key", "source_sha256", "evidence_role"}},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ): item
        for item in target_refs
    }
    target_refs = [ref_by_key[key] for key in sorted(ref_by_key)]
    card_fact_ref = {
        **current_ref,
        "evidence_role": "current_card_transaction_fact",
    }
    manual_paths = {
        "manual_travel_tab_exact",
        "manual_travel_tab_mn_target_invariant",
        MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
        MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH,
        MANUAL_REVERSAL_EXACT_PATH,
        MANUAL_REVERSAL_MN_PATH,
    }
    manual_used = target_path in manual_paths
    finality_vetoes: list[str] = []
    structural_rule_admitted = target_path in admitted_paths
    mail_service_period_verified, mail_service_source_kinds = (
        _mail_service_period_2026_verified(target, target_path, target_refs)
    )
    if _row_year(row) == 2025 and not mail_service_period_verified:
        finality_vetoes.append("2025_mail_service_period_required")
    if (
        not structural_rule_admitted
        and (target_path in REVIEW_TARGET_PATHS or target_path in PROVISIONAL_TARGET_PATHS)
    ):
        finality_vetoes.append("review_or_provisional_target_path")
    if target in {TRIP_UNASSIGNED, "취소환불"}:
        finality_vetoes.append("target_not_finally_allocable")
    if target_path in manual_paths and not manual_used:
        finality_vetoes.append("manual_target_authority_missing")
    if target_path in manual_paths and not any(
        item.get("evidence_role") == "classification_target_only"
        and item.get("source_kind") == "manual_ledger"
        for item in target_refs
        if isinstance(item, dict)
    ):
        finality_vetoes.append("manual_target_reference_missing")
    if target_path in OTA_MAIL_SERVICE_PERIOD_PATHS:
        if not isinstance(ota_service_target, dict):
            finality_vetoes.append("ota_service_period_evidence_missing")
        else:
            card_ids = {
                int(value) for value in ota_service_target.get(
                    "card_payment_ids", []
                )
            }
            mail_ids = {
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                for value in ota_service_target.get("mail_identities", [])
            }
            statuses = [
                str(item.get("lifecycle_latest_status") or "")
                for item in target_refs
                if isinstance(item, dict)
                and item.get("evidence_role") == "ota_service_period"
            ]
            if not statuses or any(status not in {"confirmation", "change"} for status in statuses):
                finality_vetoes.append("ota_lifecycle_not_closed")
            for item in ota_service_target.get("evidence_records", []):
                if not isinstance(item, dict):
                    finality_vetoes.append("ota_evidence_record_invalid")
                    continue
                if not str(item.get("amount_source_key") or "") or not str(
                    item.get("amount_source_sha256") or ""
                ):
                    finality_vetoes.append("ota_amount_source_binding_missing")
                if not str(item.get("lifecycle_latest_source_key") or "") or not str(
                    item.get("lifecycle_latest_source_sha256") or ""
                ):
                    finality_vetoes.append("ota_lifecycle_source_binding_missing")
            amount_match_method = str(
                ota_service_target.get("amount_match_method") or ""
            )
            if amount_match_method not in {
                "exact", OTA_AMOUNT_TOLERANCE_POLICY,
            }:
                finality_vetoes.append("ota_amount_match_policy_missing")
            tolerance_path = target_path in {
                OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH,
                OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH,
            }
            if tolerance_path and amount_match_method != OTA_AMOUNT_TOLERANCE_POLICY:
                finality_vetoes.append("ota_amount_tolerance_method_mismatch")
            if not tolerance_path and amount_match_method == OTA_AMOUNT_TOLERANCE_POLICY:
                finality_vetoes.append("ota_amount_tolerance_path_missing")
            difference_ratio = ota_service_target.get(
                "amount_difference_ratio"
            )
            if not isinstance(difference_ratio, (int, float)) or isinstance(
                difference_ratio, bool
            ) or difference_ratio < 0 or difference_ratio > OTA_AMOUNT_TOLERANCE_RATIO:
                finality_vetoes.append("ota_amount_difference_ratio_invalid")
            if target_path in OTA_MAIL_SERVICE_PERIOD_EXACT_CARD_PATHS and (
                len(card_ids) != 1 or len(mail_ids) != 1
            ):
                finality_vetoes.append("ota_exact_card_mail_cardinality_invalid")
            if target_path in OTA_MAIL_SERVICE_PERIOD_MN_CARD_PATHS and (
                len(card_ids) < 2
                or len(card_ids) != len(mail_ids)
                or len(mail_ids) != len(ota_service_target.get("mail_identities", []))
            ):
                finality_vetoes.append("ota_mn_card_mail_cardinality_invalid")
    if target_path == "reversal_axis_inherit" and not reversal_inheritance.endswith(
        (":unique_original", ":axis_invariant")
    ):
        finality_vetoes.append("reversal_inheritance_not_exact")
    if target_path == TRIP_CLUSTER_CANONICAL_EXACT_PATH and (
        target_registry is None
        or str(target_registry.get("target_kind") or "") != "canonical_schedule"
    ):
        finality_vetoes.append("canonical_trip_registry_missing")
    ota_card_count = None
    ota_mail_count = None
    ota_lifecycle_statuses: list[str] = []
    if isinstance(ota_service_target, dict):
        ota_card_count = len(ota_service_target.get("card_payment_ids", []))
        ota_mail_count = len(ota_service_target.get("mail_identities", []))
        ota_lifecycle_statuses = sorted({
            str(item.get("lifecycle_latest_status") or "")
            for item in target_refs
            if isinstance(item, dict)
            and item.get("evidence_role") == "ota_service_period"
        })
    return {
        "contract": AXIS_EVIDENCE_CONTRACT,
        "rule_id": RULE_ID,
        "axes": {
            "account": {
                "value": account,
                "source_kind": "current_card_policy",
                "policy_path": account_path,
                "fact_refs": [card_fact_ref],
            },
            "cost_type": {
                "value": cost_type,
                "source_kind": "current_card_policy",
                "policy_path": (
                    "travel_target_implies_trip_cost"
                    if cost_type == TRIP_COST
                    else "explicit_domestic_overhead_policy"
                ),
                "fact_refs": [card_fact_ref],
            },
            "allocation_target": {
                "value": target,
                "source_kind": target_evidence_source,
                "target_path": target_path,
                "target_refs": target_refs,
                "transaction_fact_ref": card_fact_ref,
                "manual_travel_tab_classification_only": manual_used,
                "manual_travel_tab_transaction_evidence": False,
                "reversal_inheritance": reversal_inheritance,
            },
        },
        "current_transaction_ref": current_ref,
        "target_evidence_refs": target_refs,
        "policy": {
            "manual_travel_tab_target_authority": (
                "strong_classification_evidence"
            ),
            "manual_travel_tab_transaction_evidence": False,
            "geographic_context_transaction_evidence": False,
            "ota_payment_date_is_service_date": False,
            "m_to_n_individual_pairing_asserted": False,
        },
        "finality_contract": {
            "predicate": "axis_evidence.row_finality.eligible",
            "review_or_provisional_target_path_is_hard_veto": True,
            "structural_rule_admission": admission_manifest(admitted_paths),
            "target_unassigned_is_hard_veto": True,
            "ota_lifecycle_statuses": ["confirmation", "change"],
            "ota_m_to_n_requires_equal_card_mail_cardinality": True,
            "ota_requires_amount_source_binding": True,
            "ota_requires_lifecycle_latest_source_binding": True,
            "ota_amount_match_policy": OTA_AMOUNT_TOLERANCE_POLICY,
            "ota_amount_tolerance_ratio": OTA_AMOUNT_TOLERANCE_RATIO,
            "reversal_inheritance_requires_exact_or_axis_invariant_relation": True,
            "payment_year_2025_requires_mail_service_period": True,
            "payment_year_2025_non_mail_display_lane": "2025년 결제",
        },
        "conflict_count": 0,
        "row_finality": {
            "status": "final_eligible" if not finality_vetoes else "nonfinal_veto",
            "eligible": not finality_vetoes,
            "vetoes": sorted(set(finality_vetoes)),
            "target_path": target_path,
            "structural_rule_admitted": structural_rule_admitted,
            "ota_card_count": ota_card_count,
            "ota_mail_count": ota_mail_count,
            "ota_lifecycle_statuses": ota_lifecycle_statuses,
            "ota_amount_match_method": (
                str(ota_service_target.get("amount_match_method") or "")
                if isinstance(ota_service_target, dict) else None
            ),
            "ota_amount_difference_ratio": (
                ota_service_target.get("amount_difference_ratio")
                if isinstance(ota_service_target, dict) else None
            ),
            "payment_year": _row_year(row),
            "mail_service_period_verified": mail_service_period_verified,
            "mail_service_period_source_kinds": mail_service_source_kinds,
        },
    }


def _axis_evidence_contract_issues(
    prediction: dict[str, object],
    evidence: object,
    current_row: dict[str, object] | None,
    admitted_rule_paths: Iterable[str] = (),
) -> list[str]:
    """Validate the stored three-axis evidence independently of rebuilding."""
    issues: list[str] = []
    admitted_paths = normalize_admitted_rule_paths(admitted_rule_paths)
    if not isinstance(evidence, dict):
        return ["axis_evidence_not_object"]
    if evidence.get("contract") != AXIS_EVIDENCE_CONTRACT:
        issues.append("axis_evidence_contract_invalid")
    if evidence.get("rule_id") != RULE_ID:
        issues.append("axis_evidence_rule_id_invalid")
    if evidence.get("conflict_count") != 0:
        issues.append("axis_evidence_conflict_nonzero")
    finality_contract = evidence.get("finality_contract")
    if not isinstance(finality_contract, dict) or (
        finality_contract.get("predicate")
        != "axis_evidence.row_finality.eligible"
        or finality_contract.get("review_or_provisional_target_path_is_hard_veto")
        is not True
        or finality_contract.get("target_unassigned_is_hard_veto") is not True
        or finality_contract.get("ota_requires_amount_source_binding") is not True
        or finality_contract.get("ota_requires_lifecycle_latest_source_binding")
        is not True
        or finality_contract.get("ota_amount_match_policy")
        != OTA_AMOUNT_TOLERANCE_POLICY
        or finality_contract.get("ota_amount_tolerance_ratio")
        != OTA_AMOUNT_TOLERANCE_RATIO
        or finality_contract.get("payment_year_2025_requires_mail_service_period")
        is not True
        or finality_contract.get("payment_year_2025_non_mail_display_lane")
        != "2025년 결제"
    ):
        issues.append("axis_evidence_finality_contract_invalid")
    axes = evidence.get("axes")
    if not isinstance(axes, dict) or set(axes) != set(ACTIVE_DIMENSIONS):
        return [*issues, "axis_evidence_axes_invalid"]
    if current_row is None:
        return [*issues, "axis_evidence_current_row_missing"]
    expected_current = _current_source_reference(current_row)
    current_ref = evidence.get("current_transaction_ref")
    if current_ref != expected_current:
        issues.append("axis_evidence_current_fact_mismatch")
    target_axis = axes.get("allocation_target")
    if not isinstance(target_axis, dict):
        issues.append("axis_evidence_target_axis_invalid")
        return issues
    if evidence.get("target_evidence_refs") != target_axis.get("target_refs"):
        issues.append("axis_evidence_target_refs_mismatch")
    for dimension in ACTIVE_DIMENSIONS:
        axis = axes.get(dimension)
        if not isinstance(axis, dict):
            issues.append(f"axis_evidence_{dimension}_invalid")
            continue
        if axis.get("value") != prediction.get(dimension):
            issues.append(f"axis_evidence_{dimension}_value_mismatch")
        refs = axis.get("fact_refs")
        if dimension in {"account", "cost_type"}:
            if not isinstance(refs, list) or expected_current not in [
                {
                    key: value for key, value in item.items()
                    if key in expected_current
                }
                for item in refs if isinstance(item, dict)
            ]:
                issues.append(f"axis_evidence_{dimension}_fact_ref_missing")
    target_refs = evidence.get("target_evidence_refs")
    if not isinstance(target_refs, list) or not target_refs:
        issues.append("axis_evidence_target_evidence_missing")
    target_path = _target_path(prediction.get("rule_path"))
    structural_rule_admitted = target_path in admitted_paths
    manual_paths = {
        "manual_travel_tab_exact",
        "manual_travel_tab_mn_target_invariant",
        MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
        MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH,
        MANUAL_REVERSAL_EXACT_PATH,
        MANUAL_REVERSAL_MN_PATH,
    }
    if target_path in manual_paths:
        manual_refs = [
            item for item in target_refs or []
            if isinstance(item, dict)
            and item.get("source_kind") == "manual_ledger"
            and item.get("evidence_role") == "classification_target_only"
        ]
        if not manual_refs:
            issues.append("axis_evidence_manual_target_ref_missing")
        if target_axis.get("manual_travel_tab_transaction_evidence") is not False:
            issues.append("axis_evidence_manual_transaction_flag_invalid")
    policy = evidence.get("policy")
    if not isinstance(policy, dict):
        issues.append("axis_evidence_policy_invalid")
    else:
        if policy.get("manual_travel_tab_transaction_evidence") is not False:
            issues.append("axis_evidence_policy_manual_transaction_invalid")
        if policy.get("geographic_context_transaction_evidence") is not False:
            issues.append("axis_evidence_policy_geography_transaction_invalid")
        if policy.get("ota_payment_date_is_service_date") is not False:
            issues.append("axis_evidence_policy_ota_date_invalid")
        if policy.get("m_to_n_individual_pairing_asserted") is not False:
            issues.append("axis_evidence_policy_mn_pairing_invalid")
    finality = evidence.get("row_finality")
    if not isinstance(finality, dict):
        issues.append("axis_evidence_row_finality_invalid")
        return issues
    vetoes = finality.get("vetoes")
    eligible = finality.get("eligible")
    status = finality.get("status")
    if finality.get("target_path") != target_path:
        issues.append("axis_evidence_row_finality_path_mismatch")
    expected_mail_verified, expected_mail_sources = (
        _mail_service_period_2026_verified(
            str(prediction.get("allocation_target") or ""),
            target_path,
            target_refs or [],
        )
    )
    if _row_year(current_row) != 2025:
        expected_mail_verified = False if not expected_mail_sources else True
    if finality.get("mail_service_period_verified") is not expected_mail_verified:
        issues.append("axis_evidence_2025_mail_service_period_flag_invalid")
    actual_mail_sources = finality.get("mail_service_period_source_kinds")
    if actual_mail_sources != expected_mail_sources:
        issues.append("axis_evidence_mail_service_source_kinds_invalid")
    if finality.get("payment_year") != _row_year(current_row):
        issues.append("axis_evidence_payment_year_invalid")
    if not isinstance(vetoes, list) or any(
        not isinstance(item, str) or not item for item in vetoes
    ):
        issues.append("axis_evidence_row_finality_vetoes_invalid")
        vetoes = []
    expected_eligible = not bool(vetoes)
    if eligible is not expected_eligible:
        issues.append("axis_evidence_row_finality_eligibility_mismatch")
    expected_status = "final_eligible" if expected_eligible else "nonfinal_veto"
    if status != expected_status:
        issues.append("axis_evidence_row_finality_status_mismatch")
    if (
        target_path in REVIEW_TARGET_PATHS or target_path in PROVISIONAL_TARGET_PATHS
    ) and eligible is True and not structural_rule_admitted:
        issues.append("axis_evidence_provisional_path_marked_final")
    if structural_rule_admitted:
        admission = (
            finality_contract.get("structural_rule_admission")
            if isinstance(finality_contract, dict)
            else None
        )
        if not isinstance(admission, dict):
            issues.append("axis_evidence_structural_rule_admission_missing")
        elif (
            admission.get("contract") != "structural-rule-admission-v1"
            or target_path not in admission.get("admitted_paths", [])
            or admission.get("auto_authorization") is not False
            or admission.get("relationship_question_overlap")
            != "allowed_without_inheritance"
        ):
            issues.append("axis_evidence_structural_rule_admission_invalid")
        if finality.get("structural_rule_admitted") is not True:
            issues.append("axis_evidence_structural_rule_admitted_flag_invalid")
    if prediction.get("allocation_target") in {TRIP_UNASSIGNED, "취소환불"}:
        if eligible is True:
            issues.append("axis_evidence_nonallocable_target_marked_final")
    if target_path in OTA_MAIL_SERVICE_PERIOD_PATHS and eligible is True:
        card_count = finality.get("ota_card_count")
        mail_count = finality.get("ota_mail_count")
        statuses = finality.get("ota_lifecycle_statuses")
        if not isinstance(statuses, list) or not statuses or any(
            item not in {"confirmation", "change"} for item in statuses
        ):
            issues.append("axis_evidence_ota_lifecycle_marked_final_invalid")
        if target_path in OTA_MAIL_SERVICE_PERIOD_EXACT_CARD_PATHS and (
            card_count != 1 or mail_count != 1
        ):
            issues.append("axis_evidence_ota_exact_cardinality_marked_final_invalid")
        if target_path in OTA_MAIL_SERVICE_PERIOD_MN_CARD_PATHS and (
            not isinstance(card_count, int)
            or not isinstance(mail_count, int)
            or card_count < 2
            or card_count != mail_count
        ):
            issues.append("axis_evidence_ota_mn_cardinality_marked_final_invalid")
        amount_method = finality.get("ota_amount_match_method")
        difference_ratio = finality.get("ota_amount_difference_ratio")
        if amount_method not in {"exact", OTA_AMOUNT_TOLERANCE_POLICY}:
            issues.append("axis_evidence_ota_amount_match_method_invalid")
        if not isinstance(difference_ratio, (int, float)) or isinstance(
            difference_ratio, bool
        ) or difference_ratio < 0 or difference_ratio > OTA_AMOUNT_TOLERANCE_RATIO:
            issues.append("axis_evidence_ota_amount_difference_ratio_invalid")
        if target_path in {
            OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH,
            OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH,
        } and amount_method != OTA_AMOUNT_TOLERANCE_POLICY:
            issues.append("axis_evidence_ota_tolerance_method_invalid")
        if target_path not in {
            OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH,
            OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH,
        } and amount_method == OTA_AMOUNT_TOLERANCE_POLICY:
            issues.append("axis_evidence_ota_tolerance_path_invalid")
    if target_path in OTA_MAIL_SERVICE_PERIOD_PATHS:
        service_refs = [
            item for item in target_refs or []
            if isinstance(item, dict)
            and item.get("evidence_role") == "ota_service_period"
        ]
        amount_refs = [
            item for item in target_refs or []
            if isinstance(item, dict)
            and item.get("evidence_role") == "ota_amount_fact"
        ]
        lifecycle_refs = [
            item for item in target_refs or []
            if isinstance(item, dict)
            and item.get("evidence_role") == "ota_lifecycle_latest"
        ]
        for service_ref in service_refs:
            service_key = str(service_ref.get("source_key") or "")
            if not any(
                str(item.get("service_source_key") or "") == service_key
                for item in amount_refs
            ):
                issues.append("axis_evidence_ota_amount_binding_missing")
            if not any(
                str(item.get("service_source_key") or "") == service_key
                for item in lifecycle_refs
            ):
                issues.append("axis_evidence_ota_lifecycle_binding_missing")
            service_method = service_ref.get("amount_match_method")
            service_ratio = service_ref.get("amount_difference_ratio")
            if service_method not in {"exact", OTA_AMOUNT_TOLERANCE_POLICY}:
                issues.append("axis_evidence_ota_service_amount_method_missing")
            if not isinstance(service_ratio, (int, float)) or isinstance(
                service_ratio, bool
            ) or service_ratio < 0 or service_ratio > OTA_AMOUNT_TOLERANCE_RATIO:
                issues.append("axis_evidence_ota_service_amount_ratio_invalid")
    return issues


def _inferred_target_source_key(item: dict[str, object]) -> str:
    return json.dumps(
        {
            key: item.get(key)
            for key in ("source_kind", "source_key", "source_sha256")
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _add_inferred_target(
    target_by_payment: dict[int, dict[str, object]],
    payment_id: int,
    item: dict[str, object],
) -> None:
    """Merge independent hints only when they name the same target.

    KASINA's approval-family hint and the explicit Malaysia card markers both
    resolve to one temporary target.  If two independent hints disagree, the
    row remains in the existing owner-review path instead of choosing one.
    """
    current = target_by_payment.get(payment_id)
    if current is None:
        target_by_payment[payment_id] = {
            **item,
            "candidate_targets": sorted({
                str(value) for value in item.get("candidate_targets", [])
                if str(value)
            }),
            "evidence_records": list(item.get("evidence_records", [])),
            "anchor_records": list(item.get("anchor_records", [])),
            "match_methods": sorted({
                str(value) for value in item.get("match_methods", [])
                if str(value)
            }),
        }
        return
    if str(current.get("target_code") or "") != str(item.get("target_code") or ""):
        # Do not silently resolve a conflict between evidence families.
        return
    current["candidate_targets"] = sorted({
        *[str(value) for value in current.get("candidate_targets", [])],
        *[str(value) for value in item.get("candidate_targets", [])],
    })
    evidence = {
        _inferred_target_source_key(value): value
        for value in [
            *current.get("evidence_records", []),
            *item.get("evidence_records", []),
        ]
        if isinstance(value, dict)
    }
    current["evidence_records"] = [
        evidence[key] for key in sorted(evidence)
    ]
    anchors = {
        _inferred_target_source_key(value): value
        for value in [
            *current.get("anchor_records", []),
            *item.get("anchor_records", []),
        ]
        if isinstance(value, dict)
    }
    current["anchor_records"] = [anchors[key] for key in sorted(anchors)]
    current["match_methods"] = sorted({
        *[str(value) for value in current.get("match_methods", [])],
        *[str(value) for value in item.get("match_methods", [])],
    })


def _ota_mail_inferred_targets(
    current: Iterable[dict[str, object]],
    manual_matches: dict[int, dict[str, object] | None],
    ota_mail_records: Iterable[dict[str, object]],
) -> dict[int, dict[str, object]]:
    """Build only closed OTA/manual M:N classification components.

    A component is eligible when the current-card side and the redacted OTA
    mail side have the same cardinality and the manual travel candidates are
    exactly the same set for every member.  No row-to-row pairing is emitted.
    """
    grouped: dict[tuple[str, str, int, str], list[dict[str, object]]] = defaultdict(list)
    for row in current:
        if (
            str(row.get("transaction_type") or "") == "purchase"
            and int(row.get("amount_krw") or 0) > 0
            and _provider(row.get("merchant")) == "trip"
        ):
            grouped[
                (
                    str(row.get("source") or ""),
                    str(row.get("occurred_on") or ""),
                    abs(int(row.get("amount_krw") or 0)),
                    str(row.get("card4") or ""),
                )
            ].append(row)

    records = [
        record for record in ota_mail_records
        if isinstance(record.get("payload"), dict)
        and str(record["payload"].get("provider") or "").lower() == "trip"
    ]
    result: dict[int, dict[str, object]] = {}
    for group_key, rows in sorted(grouped.items()):
        if len(rows) not in {1, 2}:
            continue
        matches = [manual_matches.get(int(row["payment_id"])) for row in rows]
        if any(
            not isinstance(match, dict)
            or str(match.get("status") or "") != "ambiguous"
            for match in matches
        ):
            continue
        target_codes = sorted({
            str(item.get("manual_tab") or "")
            for match in matches
            if isinstance(match, dict)
            for item in match.get("matches", [])
            if isinstance(item, dict) and str(item.get("manual_tab") or "")
        })
        if len(target_codes) < 2:
            continue
        source, occurred_on, amount, card4 = group_key
        current_mmdd = occurred_on[5:7] + occurred_on[8:10]
        mail_matches = [
            record for record in records
            if amount in {
                int(value) for value in record["payload"].get(
                    "amount_candidates", []
                ) if str(value).lstrip("-").isdigit()
            }
            and current_mmdd in _ota_mail_mmdd(record["payload"])
        ]
        if len(mail_matches) != len(rows):
            continue
        mail_keys = sorted(str(item["source_key"]) for item in mail_matches)
        manual_keys = sorted({
            str(item.get("manual_source_key") or "")
            for match in matches
            if isinstance(match, dict)
            for item in match.get("matches", [])
            if isinstance(item, dict)
        })
        event_keys = sorted(str(row["direct_event_key"]) for row in rows)
        target_code = (
            f"임시여행_MN_{occurred_on.replace('-', '')}_"
            f"{source}_{amount}_{_sha({
                'card4': card4,
                'event_keys': event_keys,
                'mail_keys': mail_keys,
                'manual_keys': manual_keys,
                'candidate_targets': target_codes,
            })[:12]}"
        )
        evidence_records = [
            {
                "source_kind": "ota_mail",
                "source_key": str(record["source_key"]),
                "source_sha256": str(record["source_sha256"]),
                "provider": str(record["payload"].get("provider") or ""),
                "amount_candidates": sorted(
                    int(value) for value in record["payload"].get(
                        "amount_candidates", []
                    ) if str(value).lstrip("-").isdigit()
                ),
                "travel_date_candidates": sorted(
                    _ota_mail_mmdd(record["payload"])
                ),
            }
            for record in mail_matches
        ]
        evidence_records.extend(
            {
                "source_kind": "manual_ledger",
                "source_key": str(item.get("manual_source_key") or ""),
                "source_sha256": str(item.get("manual_source_sha256") or ""),
                "manual_tab": str(item.get("manual_tab") or ""),
                "manual_item": str(item.get("manual_item") or ""),
            }
            for match in matches
            if isinstance(match, dict)
            for item in match.get("matches", [])
            if isinstance(item, dict)
        )
        for row in rows:
            result[int(row["payment_id"])] = {
                "target_code": target_code,
                "candidate_targets": target_codes,
                "country": "JP",
                "region": "manual_ota_candidate_set",
                "basis": "ota_mail_manual_mn_candidate_component",
                "match_methods": ["ota_mail_card_key_cardinality", "manual_candidate_set"],
                "evidence_records": evidence_records,
                "anchor_records": [],
            }
    return result


YAKUSHIMA_PORTAL_COMMIT = "61ea7b9"
YAKUSHIMA_PORTAL_PATH = "ledger/data/agoda_direct_browser_evidence.json"
YAKUSHIMA_PORTAL_FILE_SHA256 = (
    "de9ce5264ee608b6fc1bede2d179c343385120ae13e74fb07fb0354cc9c88cf2"
)
YAKUSHIMA_PORTAL_BOOKING = "662897867"


def _historical_target_learning_targets(
    current: Iterable[dict[str, object]],
    baseline_by_payment: dict[int, tuple[str, str, str]],
    training: Iterable[dict[str, object]],
    schedule: dict[str, dict[str, object]],
) -> dict[int, dict[str, object]]:
    """Use the frozen historical classifier only as a target hint.

    This is intentionally weaker than a transaction match.  The current card
    remains the only transaction fact; the old row contributes a target label
    only when the current source/date/absolute amount has one canonical target
    and at least one old row agrees on card4 or normalized merchant.  A row
    from the old ledger is never copied into the current transaction or
    promotion-evidence tables.
    """
    by_key: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    for item in training:
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        source = str(payload.get("src") or "").strip().upper()
        occurred_on = str(payload.get("use_date") or "").strip()
        target = str(payload.get("bucket") or "").strip()
        if (
            not source or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", occurred_on)
            or target not in schedule
            or str(payload.get("cost_type") or "") != TRIP_COST
            or any(_adverse(payload.get(field)) for field in (
                "bucket", "account", "cost_type",
            ))
        ):
            continue
        try:
            amount = abs(int(payload.get("krw") or 0))
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        by_key[(source, occurred_on, amount)].append({
            "target": target,
            "uid": str(item.get("uid") or ""),
            "source_sha256": str(item.get("row_sha256") or ""),
            "card4": str(payload.get("card4") or "")[-4:],
            "merchant": str(payload.get("merchant") or ""),
            "confidence": str(payload.get("confidence") or ""),
        })

    def eligible_baseline(value: tuple[str, str, str] | None) -> bool:
        return bool(
            value is not None
            and (
                value[0] == TRIP_UNASSIGNED
                or value[1] == RESERVATION_PLACEHOLDER_PATH
            )
        )

    current_rows = [
        row for row in current
        if (
            str(row.get("transaction_type") or "") == "purchase"
            and int(row.get("amount_krw") or 0) > 0
            and str(row.get("occurred_on") or "").startswith("2026-")
            and eligible_baseline(
                baseline_by_payment.get(int(row["payment_id"]))
            )
        )
    ]

    def strong_match(row: dict[str, object], item: dict[str, object]) -> bool:
        current_card4 = str(row.get("card4") or "")[-4:]
        historical_card4 = str(item.get("card4") or "")[-4:]
        if current_card4 and historical_card4 and current_card4 == historical_card4:
            return True
        current_merchant = _norm(row.get("merchant") or "")
        historical_merchant = _norm(item.get("merchant") or "")
        return bool(
            current_merchant and historical_merchant
            and (
                current_merchant in historical_merchant
                or historical_merchant in current_merchant
            )
        )

    result: dict[int, dict[str, object]] = {}
    group_rows: dict[tuple[str, str, str, str], list[dict[str, object]]] = defaultdict(list)
    row_hints: dict[int, tuple[str, list[dict[str, object]]]] = {}
    for row in current_rows:
        key = (
            str(row.get("source") or "").strip().upper(),
            str(row.get("occurred_on") or ""),
            abs(int(row.get("amount_krw") or 0)),
        )
        candidates = by_key.get(key, [])
        target_codes = {str(item["target"]) for item in candidates}
        strong_candidates = [item for item in candidates if strong_match(row, item)]
        if len(target_codes) == 1 and strong_candidates:
            target = next(iter(target_codes))
            row_hints[int(row["payment_id"])] = (target, candidates)
            result[int(row["payment_id"])] = {
                "target_code": target,
                "candidate_targets": [target],
                "country": "JP",
                "region": "historical_target_learning",
                "basis": "historical_target_learning_exact_source_date_amount",
                "match_methods": [
                    "historical_target_hint_card4_or_merchant",
                    "current_card_transaction_fact_only",
                ],
                "evidence_records": [
                    {
                        "source_kind": "classifier_training",
                        "source_key": str(item["uid"]),
                        "source_sha256": str(item["source_sha256"]),
                        "historical_target": str(item["target"]),
                        "historical_card4": str(item["card4"]),
                    }
                    for item in candidates
                    if str(item["source_sha256"])
                ],
                "anchor_records": [],
            }
        group_key = (
            key[0], key[1], str(row.get("card4") or "")[-4:],
            _norm(row.get("merchant") or ""),
        )
        group_rows[group_key].append(row)

    # If several same-day/card/merchant charges form one component, a single
    # historical target hint may safely name the common target.  This is an
    # M:N target invariant only; no old row is paired with an individual card.
    for group_key, rows in group_rows.items():
        hints: list[dict[str, object]] = []
        strong_hint = False
        for row in rows:
            key = (
                str(row.get("source") or "").strip().upper(),
                str(row.get("occurred_on") or ""),
                abs(int(row.get("amount_krw") or 0)),
            )
            candidates = by_key.get(key, [])
            hints.extend(candidates)
            strong_hint = strong_hint or any(
                strong_match(row, item) for item in candidates
            )
        target_codes = {str(item["target"]) for item in hints}
        if len(target_codes) != 1 or not strong_hint:
            continue
        target = next(iter(target_codes))
        for row in rows:
            payment_id = int(row["payment_id"])
            if payment_id in result:
                continue
            result[payment_id] = {
                "target_code": target,
                "candidate_targets": [target],
                "country": "JP",
                "region": "historical_target_learning",
                "basis": "historical_target_learning_group_target_invariant",
                "match_methods": [
                    "historical_target_hint_group_target_invariant",
                    "current_card_transaction_fact_only",
                ],
                "evidence_records": [
                    {
                        "source_kind": "classifier_training",
                        "source_key": str(item["uid"]),
                        "source_sha256": str(item["source_sha256"]),
                        "historical_target": str(item["target"]),
                        "historical_card4": str(item["card4"]),
                    }
                    for item in hints
                    if str(item["source_sha256"])
                ],
                "anchor_records": [],
            }
    return result


def _verified_lodging_fact_targets(
    db: sqlite3.Connection,
    run_id: str,
    current: list[dict[str, object]],
    baseline_by_payment: dict[int, tuple[str, str, str]],
    schedule: dict[str, dict[str, object]],
) -> dict[int, dict[str, object]]:
    """Use only active authenticated lodging facts as temporary target hints."""
    rows = db.execute(
        """SELECT fact_id,source_key,source_sha256,fact_sha256,provider,
                  booking_ref,property_name,check_in,check_out,seoul_sent_on,
                  paid_total_krw,target_code
           FROM direct_verified_lodging_facts
           WHERE run_id=? AND lifecycle_status='active'
           ORDER BY fact_id""",
        (run_id,),
    ).fetchall()
    facts = [
        {
            "fact_id": str(row[0]),
            "source_key": str(row[1]),
            "source_sha256": str(row[2]),
            "fact_sha256": str(row[3]),
            "provider": str(row[4]),
            "booking_ref": str(row[5]),
            "property_name": str(row[6]),
            "check_in": str(row[7]),
            "check_out": str(row[8]),
            "seoul_sent_on": str(row[9]),
            "paid_total_krw": int(row[10]),
            "target": str(row[11]),
        }
        for row in rows
    ]

    def eligible(row: dict[str, object]) -> bool:
        baseline = baseline_by_payment.get(int(row["payment_id"]))
        return bool(
            baseline is not None
            and (
                baseline[0] == TRIP_UNASSIGNED
                or baseline[1] == RESERVATION_PLACEHOLDER_PATH
            )
            and str(row.get("transaction_type") or "") == "purchase"
            and int(row.get("amount_krw") or 0) > 0
            and _provider(row.get("merchant")) == "trip"
        )

    def match(
        fact: dict[str, object], amount: int,
    ) -> dict[str, object] | None:
        paid = int(fact["paid_total_krw"])
        if amount == paid:
            return {
                "method": "exact",
                "matched_amount_krw": paid,
                "difference_ratio": 0.0,
            }
        ratio = abs(amount - paid) / paid
        if ratio <= OTA_AMOUNT_TOLERANCE_RATIO:
            return {
                "method": OTA_AMOUNT_TOLERANCE_POLICY,
                "matched_amount_krw": paid,
                "difference_ratio": round(ratio, 12),
            }
        return None

    grouped: dict[tuple[str, str, int, str], list[dict[str, object]]] = defaultdict(list)
    for row in current:
        if not eligible(row):
            continue
        grouped[
            (
                str(row.get("source") or ""),
                str(row.get("occurred_on") or ""),
                abs(int(row.get("amount_krw") or 0)),
                "trip",
            )
        ].append(row)

    components = []
    for group_key, card_rows in sorted(grouped.items()):
        card_amount = group_key[2]
        candidates = []
        for fact in facts:
            matched = match(fact, card_amount)
            if matched is not None:
                candidates.append((fact, matched))
        exact = [
            item for item in candidates if item[1]["method"] == "exact"
        ]
        selected = exact if exact else candidates
        if len(selected) != len(card_rows) or not selected:
            continue
        if len({str(item[0]["target"]) for item in selected}) != 1:
            continue
        components.append((group_key, card_rows, selected))

    fact_groups: dict[str, set[int]] = defaultdict(set)
    for index, (_, _, selected) in enumerate(components):
        for fact, _ in selected:
            fact_groups[str(fact["fact_id"])].add(index)

    result: dict[int, dict[str, object]] = {}
    for index, (group_key, card_rows, selected) in enumerate(components):
        if any(
            fact_groups[str(fact["fact_id"])] != {index}
            for fact, _ in selected
        ):
            continue
        target = str(selected[0][0]["target"])
        target_trip = schedule.get(target, {})
        region = str(target_trip.get("region") or "").strip()
        country = ""
        for token, code in REGION_COUNTRIES.items():
            if REGION_LABELS.get(token) == region:
                country = code
                break
        if not country:
            country = {
                "유럽": "EU",
                "말레이시아": "MY",
                "싱가포르": "SG",
                "대만": "TW",
            }.get(region, "UNKNOWN")
        if not region:
            # The lodging fact has already passed exact target validation; a
            # missing schedule label is a source-contract problem, not a
            # reason to write an invalid registry row.
            region = target
        methods = {
            "authenticated_lodging_fact",
            "booking_row_pairing_not_asserted",
            "payment_date_is_not_service_date",
        }
        evidence = []
        for fact, matched in selected:
            method = str(matched["method"])
            methods.add(
                "lodging_amount_exact"
                if method == "exact"
                else "lodging_amount_tolerance"
            )
            evidence.append({
                "source_kind": "ota_lodging_fact",
                "source_key": str(fact["source_key"]),
                "source_sha256": str(fact["source_sha256"]),
                "fact_sha256": str(fact["fact_sha256"]),
                "fact_id": str(fact["fact_id"]),
                "provider": str(fact["provider"]),
                "booking_ref": str(fact["booking_ref"]),
                "property_name": str(fact["property_name"]),
                "service_start": str(fact["check_in"]),
                "service_end": str(fact["check_out"]),
                "mail_sent_on": str(fact["seoul_sent_on"]),
                "card_amount_krw": int(group_key[2]),
                "paid_total_krw": int(fact["paid_total_krw"]),
                "matched_amount_krw": int(matched["matched_amount_krw"]),
                "amount_match_method": method,
                "amount_difference_ratio": float(
                    matched["difference_ratio"]
                ),
                "canonical_target": target,
            })
        item = {
            "target_code": target,
            "candidate_targets": [target],
            "country": country,
            "region": region,
            "basis": "ota_verified_lodging_fact_amount_target_candidate",
            "match_methods": sorted(methods),
            "evidence_records": evidence,
            "anchor_records": [],
        }
        for row in card_rows:
            result[int(row["payment_id"])] = item
    return result


def _ota_mail_sent_date_amount_targets(
    current: list[dict[str, object]],
    baseline_by_payment: dict[int, tuple[str, str, str]],
    ota_mail_records: list[dict[str, object]],
    schedule: dict[str, dict[str, object]],
) -> dict[int, dict[str, object]]:
    """Build provisional targets from mail timing and amount, never a pairing."""
    def eligible(row: dict[str, object]) -> bool:
        baseline = baseline_by_payment.get(int(row["payment_id"]))
        return bool(
            baseline is not None
            and (
                baseline[0] == TRIP_UNASSIGNED
                or baseline[1] == RESERVATION_PLACEHOLDER_PATH
            )
            and str(row.get("transaction_type") or "") == "purchase"
            and int(row.get("amount_krw") or 0) > 0
        )

    def date_distance(left: date, right: date) -> int:
        return abs((left - right).days)

    def amount_match(
        payload: dict[str, object],
        card_amount: int,
    ) -> dict[str, object] | None:
        amounts = sorted(_ota_mail_amounts(payload))
        if card_amount in amounts:
            return {
                "method": "exact",
                "matched_amount_krw": card_amount,
                "difference_ratio": 0.0,
            }
        near = [
            (value, abs(card_amount - value) / value)
            for value in amounts
            if value > 0
            and abs(card_amount - value) <= value * OTA_AMOUNT_TOLERANCE_RATIO
        ]
        if len(near) != 1:
            return None
        matched, ratio = near[0]
        return {
            "method": OTA_AMOUNT_TOLERANCE_POLICY,
            "matched_amount_krw": matched,
            "difference_ratio": round(ratio, 12),
        }

    canonical_records: list[dict[str, object]] = []
    eligible_records = [
        record for record in ota_mail_records
        if isinstance(record.get("payload"), dict)
        and str((record["payload"]).get("provider") or "").strip()
    ]
    for identity, ordered in _ota_mail_component_groups(eligible_records):
        active_latest = ordered[-1]
        latest_status = str(
            (active_latest.get("payload") or {}).get("message_status") or ""
        ).lower()
        if latest_status in {"cancel", "refund"}:
            continue
        service_record = None
        service_targets: set[str] = set()
        for record in reversed(ordered):
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            targets = _ota_mail_schedule_targets(payload, schedule)
            if len(targets) == 1:
                service_record = record
                service_targets = targets
                break
        if service_record is None:
            continue
        amount_record = next(
            (
                record for record in reversed(ordered)
                if isinstance(record.get("payload"), dict)
                and _ota_mail_amounts(record["payload"])
            ),
            None,
        )
        if amount_record is None:
            continue
        service_payload = service_record["payload"]
        amount_payload = amount_record["payload"]
        target = next(iter(service_targets))
        sent_dates = [
            value for value in (
                _ota_mail_sent_date(service_payload),
                _ota_mail_sent_date(amount_payload),
            )
            if value is not None
        ]
        if not sent_dates:
            continue
        canonical_records.append({
            "identity": tuple(str(value) for value in identity),
            "identity_key": json.dumps(
                [str(value) for value in identity],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "provider": _ota_provider_family(service_payload.get("provider")),
            "target": target,
            "amounts": sorted(_ota_mail_amounts(amount_payload)),
            "sent_dates": sorted(set(sent_dates)),
            "service_dates": sorted(
                str(value) for value in service_payload.get(
                    "travel_date_candidates", []
                )
            ),
            "service_source": service_record,
            "amount_source": amount_record,
            "latest_source": active_latest,
        })

    grouped: dict[tuple[str, str, int, str], list[dict[str, object]]] = defaultdict(list)
    for row in current:
        if not eligible(row):
            continue
        provider = _provider(row.get("merchant"))
        if not provider:
            continue
        grouped[
            (
                str(row.get("source") or ""),
                str(row.get("occurred_on") or ""),
                abs(int(row.get("amount_krw") or 0)),
                _ota_provider_family(provider),
            )
        ].append(row)

    candidate_components = []
    for group_key, rows in sorted(grouped.items()):
        _, occurred_on, card_amount, provider = group_key
        try:
            payment_day = date.fromisoformat(occurred_on)
        except (TypeError, ValueError):
            continue
        candidates: dict[str, tuple[dict[str, object], dict[str, object], int]] = {}
        for record in canonical_records:
            if str(record["provider"]) != provider:
                continue
            match = amount_match(
                {"amount_candidates": record["amounts"]},
                card_amount,
            )
            if match is None:
                continue
            distance = min(
                date_distance(payment_day, sent_day)
                for sent_day in record["sent_dates"]
            )
            if distance > OTA_MAIL_SENT_DATE_TOLERANCE_DAYS:
                continue
            key = str(record["identity_key"])
            previous = candidates.get(key)
            if previous is None or (
                match["method"] == "exact"
                and previous[1]["method"] != "exact"
            ):
                candidates[key] = (record, match, distance)
        selected = sorted(
            candidates.values(),
            key=lambda item: str(item[0]["identity_key"]),
        )
        if len(selected) != len(rows) or not selected:
            continue
        if len({str(item[0]["target"]) for item in selected}) != 1:
            continue
        candidate_components.append((group_key, rows, selected))

    record_groups: dict[str, set[int]] = defaultdict(set)
    for index, (_, _, matches) in enumerate(candidate_components):
        for record, _, _ in matches:
            record_groups[str(record["identity_key"])].add(index)

    result: dict[int, dict[str, object]] = {}
    for index, (group_key, rows, matches) in enumerate(candidate_components):
        if any(
            record_groups[str(record["identity_key"])] != {index}
            for record, _, _ in matches
        ):
            continue
        target = str(matches[0][0]["target"])
        target_trip = schedule.get(target, {})
        evidence_records: list[dict[str, object]] = []
        methods: set[str] = {
            "ota_mail_sent_date_near_payment",
            "payment_date_is_not_service_date",
            "booking_row_pairing_not_asserted",
        }
        for record, match, distance in matches:
            service_source = record["service_source"]
            amount_source = record["amount_source"]
            service_payload = service_source["payload"]
            amount_payload = amount_source["payload"]
            method = str(match["method"])
            methods.add(
                "ota_mail_amount_exact"
                if method == "exact"
                else "ota_mail_amount_tolerance"
            )
            evidence_records.append({
                "source_kind": str(service_source.get("source_kind") or ""),
                "source_key": str(service_source.get("source_key") or ""),
                "source_sha256": str(service_source.get("source_sha256") or ""),
                "amount_source_kind": str(amount_source.get("source_kind") or ""),
                "amount_source_key": str(amount_source.get("source_key") or ""),
                "amount_source_sha256": str(amount_source.get("source_sha256") or ""),
                "provider": str(record["provider"]),
                "mail_identity": list(record["identity"]),
                "mail_sent_dates": [
                    value.isoformat() for value in record["sent_dates"]
                ],
                "payment_mail_distance_days": distance,
                "card_amount_krw": card_amount,
                "matched_amount_krw": int(match["matched_amount_krw"]),
                "amount_candidates": list(record["amounts"]),
                "amount_match_method": method,
                "amount_difference_ratio": float(match["difference_ratio"]),
                "travel_date_candidates": list(record["service_dates"]),
                "canonical_target": target,
                "message_status": str(service_payload.get("message_status") or ""),
                "amount_message_status": str(amount_payload.get("message_status") or ""),
                "lifecycle_latest_source_key": str(
                    record["latest_source"].get("source_key") or ""
                ),
                "lifecycle_latest_source_sha256": str(
                    record["latest_source"].get("source_sha256") or ""
                ),
            })
        result_item = {
            "target_code": target,
            "candidate_targets": [target],
            "country": str(target_trip.get("country") or ""),
            "region": str(target_trip.get("region") or ""),
            "basis": OTA_MAIL_SENT_DATE_AMOUNT_TARGET_PATH,
            "match_methods": sorted(methods),
            "evidence_records": evidence_records,
            "anchor_records": [],
        }
        for row in rows:
            result[int(row["payment_id"])] = result_item
    return result

def _yakushima_portal_target(
    row: dict[str, object],
    baseline: tuple[str, str, str] | None,
) -> dict[str, object] | None:
    """Return the bounded two-card Yakushima portal target candidate."""
    if baseline is None or not (
        baseline[0] == TRIP_UNASSIGNED
        or baseline[1] == RESERVATION_PLACEHOLDER_PATH
    ):
        return None
    if not (
        str(row.get("transaction_type") or "") == "purchase"
        and str(row.get("source") or "") == "KBO"
        and str(row.get("occurred_on") or "") == "2026-05-26"
        and str(row.get("card4") or "")[-4:] == "8835"
        and str(row.get("currency") or "").upper() == "JPY"
        and str(row.get("foreign") or "").strip().lstrip("-") == "118800"
        and abs(int(row.get("amount_krw") or 0)) == 1150385
        and _norm(row.get("merchant") or "") == "AGODACOMYAKUSHIMA"
    ):
        return None
    return {
        "target_code": "1127_야쿠시마",
        "candidate_targets": ["1127_야쿠시마"],
        "country": "JP",
        "region": "야쿠시마",
        "basis": "authenticated_portal_jpy_118800_mn_target_candidate",
        "match_methods": [
            "portal_card4_currency_foreign_amount_merchant_mn",
            "booking_bijection_not_asserted",
        ],
        "evidence_records": [{
            "source_kind": "authenticated_booking_portal",
            "source_key": (
                f"git:{YAKUSHIMA_PORTAL_COMMIT}:{YAKUSHIMA_PORTAL_PATH}"
                f"#booking:{YAKUSHIMA_PORTAL_BOOKING}"
            ),
            "source_sha256": YAKUSHIMA_PORTAL_FILE_SHA256,
            "provider": "agoda",
            "booking_number": YAKUSHIMA_PORTAL_BOOKING,
            "currency": "JPY",
            "foreign_amount": "118800",
            "service_start": "2026-11-27",
            "service_end": "2026-11-30",
            "individual_match_asserted": False,
        }],
        "anchor_records": [],
    }


def _build_inferred_external_targets(
    current: list[dict[str, object]],
    baseline_by_payment: dict[int, tuple[str, str, str]],
    manual_matches: dict[int, dict[str, object] | None],
    ota_mail_records: list[dict[str, object]],
    training: list[dict[str, object]],
    schedule: dict[str, dict[str, object]],
) -> dict[int, dict[str, object]]:
    """Resolve bounded temporary targets before generic owner-review paths."""
    result: dict[int, dict[str, object]] = {}

    for row in current:
        payment_id = int(row["payment_id"])
        baseline = baseline_by_payment.get(payment_id)
        if baseline is None or baseline[0] != TRIP_UNASSIGNED:
            continue
        evidence = row.get("gmail_payment_evidence")
        if not isinstance(evidence, dict):
            continue
        target_hint = str(evidence.get("target_hint") or "")
        target_status = str(evidence.get("target_status") or "")
        match_method = str(evidence.get("match_method") or "")
        if (
            target_hint == MALAYSIA_TARGET
            and target_status == "inferred_service_label"
            and match_method.endswith(
                "approval_family_source_card_merchant_unverified"
            )
        ):
            _add_inferred_target(result, payment_id, {
                "target_code": MALAYSIA_TARGET,
                "candidate_targets": [MALAYSIA_TARGET],
                "country": "MY",
                "region": "말레이시아",
                "basis": "gmail_approval_family_temporary_target",
                "match_methods": ["gmail_approval_family_temporary_target"],
                "evidence_records": [{
                    "source_kind": "gmail_payment_snapshot",
                    "source_key": "gmail-payment-snapshot",
                    "source_sha256": str(evidence.get("source_digest") or ""),
                    "target_hint": target_hint,
                    "service_start": str(evidence.get("service_start") or ""),
                    "service_end": str(evidence.get("service_end") or ""),
                }],
                "anchor_records": [],
            })
        elif (
            target_hint == "0307_시즈오카"
            and target_status == "inferred_service_label"
            and str(evidence.get("service_start") or "")
        ):
            _add_inferred_target(result, payment_id, {
                "target_code": target_hint,
                "candidate_targets": [target_hint],
                "country": "JP",
                "region": "시즈오카",
                "basis": "gmail_typed_service_label_temporary_target",
                "match_methods": ["gmail_typed_service_label"],
                "evidence_records": [{
                    "source_kind": "gmail_payment_snapshot",
                    "source_key": "gmail-payment-snapshot",
                    "source_sha256": str(evidence.get("source_digest") or ""),
                    "target_hint": target_hint,
                    "service_start": str(evidence.get("service_start") or ""),
                    "service_end": str(evidence.get("service_end") or ""),
                }],
                "anchor_records": [],
            })

    for row in current:
        payment_id = int(row["payment_id"])
        baseline = baseline_by_payment.get(payment_id)
        if baseline is None or baseline[0] != TRIP_UNASSIGNED:
            continue
        text = _norm(f"{row.get('merchant') or ''} {row.get('biz') or ''}")
        source = str(row.get("source") or "")
        card4 = str(row.get("card4") or "")
        occurred_on = str(row.get("occurred_on") or "")
        if (
            source == "HAN" and card4 == "6741"
            and str(row.get("sub") or "") == "해외"
            and "2025-08-12" <= occurred_on <= "2025-08-18"
            and any(_norm(marker) in text for marker in MALAYSIA_REGION_MARKERS)
        ):
            _add_inferred_target(result, payment_id, {
                "target_code": MALAYSIA_TARGET,
                "candidate_targets": [MALAYSIA_TARGET],
                "country": "MY",
                "region": "말레이시아",
                "basis": "current_card_explicit_malaysia_region",
                "match_methods": ["current_card_explicit_region_marker"],
                "evidence_records": [_current_source_reference(row)],
                "anchor_records": [],
            })
        elif (
            source == "HAN" and card4 == "4595"
            and str(row.get("sub") or "") == "해외"
            and "2026-05-30" <= occurred_on <= "2026-06-02"
            and any(_norm(marker) in text for marker in EUROPE_REGION_MARKERS)
        ):
            _add_inferred_target(result, payment_id, {
                "target_code": EUROPE_TARGET,
                "candidate_targets": [EUROPE_TARGET],
                "country": "EU",
                "region": "유럽",
                "basis": "current_card_explicit_europe_region",
                "match_methods": ["current_card_explicit_region_marker"],
                "evidence_records": [_current_source_reference(row)],
                "anchor_records": [],
            })

    for row in current:
        payment_id = int(row["payment_id"])
        baseline = baseline_by_payment.get(payment_id)
        if baseline is None or baseline[0] != TRIP_UNASSIGNED:
            continue
        if not (
            str(row.get("source") or "") == "HAN"
            and str(row.get("card4") or "") == "6741"
            and str(row.get("occurred_on") or "") == "2025-08-18"
            and abs(int(row.get("amount_krw") or 0)) == 73246
            and _norm(row.get("merchant") or "") == "COMFORTCITYCABTAXI"
        ):
            continue
        anchor_records: list[dict[str, str]] = []
        anchor_countries: set[str] = set()
        for anchor in current:
            if int(anchor["payment_id"]) == payment_id:
                continue
            if (
                str(anchor.get("source") or "") != "HAN"
                or str(anchor.get("card4") or "") != "6741"
                or not "2025-08-12" <= str(anchor.get("occurred_on") or "") <= "2025-08-18"
            ):
                continue
            anchor_text = _norm(
                f"{anchor.get('merchant') or ''} {anchor.get('biz') or ''}"
            )
            country = "MY" if any(
                _norm(marker) in anchor_text
                for marker in MALAYSIA_REGION_MARKERS
            ) else "SG" if "SINGAPORE" in anchor_text or "SINGAPROE" in anchor_text else ""
            if not country:
                continue
            anchor_countries.add(country)
            anchor_records.append(_current_source_reference(anchor))
        if anchor_countries == {"MY", "SG"}:
            anchor_records.sort(key=_inferred_target_source_key)
            target_code = f"임시여행활동_MN_20250818_COMFORT_{_sha({
                'payment_id': payment_id,
                'anchors': anchor_records,
                'candidate_countries': sorted(anchor_countries),
            })[:12]}"
            _add_inferred_target(result, payment_id, {
                "target_code": target_code,
                "candidate_targets": ["말레이시아", "싱가포르"],
                "country": "MULTI",
                "region": "말레이시아·싱가포르",
                "basis": "current_card_adjacent_region_candidate_set",
                "match_methods": ["adjacent_explicit_region_anchors"],
                "evidence_records": [_current_source_reference(row)],
                "anchor_records": anchor_records,
            })

    historical_targets = _historical_target_learning_targets(
        current, baseline_by_payment, training, schedule,
    )
    for payment_id, item in historical_targets.items():
        baseline = baseline_by_payment.get(payment_id)
        if baseline is not None and (
            baseline[0] == TRIP_UNASSIGNED
            or baseline[1] == RESERVATION_PLACEHOLDER_PATH
        ):
            _add_inferred_target(result, payment_id, item)

    sent_date_targets = _ota_mail_sent_date_amount_targets(
        current, baseline_by_payment, ota_mail_records, schedule,
    )
    for payment_id, item in sent_date_targets.items():
        _add_inferred_target(result, payment_id, item)

    for row in current:
        portal_target = _yakushima_portal_target(
            row, baseline_by_payment.get(int(row["payment_id"])),
        )
        if portal_target is not None:
            _add_inferred_target(result, int(row["payment_id"]), portal_target)

    ota_targets = _ota_mail_inferred_targets(
        current, manual_matches, ota_mail_records,
    )
    for payment_id, item in ota_targets.items():
        baseline = baseline_by_payment.get(payment_id)
        if baseline is not None and baseline[0] == TRIP_UNASSIGNED:
            _add_inferred_target(result, payment_id, item)
    return result


def _build_inferred_external_registries(
    current: list[dict[str, object]],
    target_by_payment: dict[int, dict[str, object]],
) -> dict[str, object]:
    """Materialize one audit-bound registry per target/source/card component."""
    current_by_id = {int(row["payment_id"]): row for row in current}
    grouped: dict[tuple[str, str, str], list[tuple[dict[str, object], dict[str, object]]]] = defaultdict(list)
    for payment_id, item in target_by_payment.items():
        row = current_by_id.get(payment_id)
        if row is None:
            raise ValueError("inferred_external_target_payment_missing")
        grouped[
            (
                str(item.get("target_code") or ""),
                str(row.get("source") or ""),
                str(row.get("card4") or ""),
            )
        ].append((row, item))

    registries: list[dict[str, object]] = []
    by_payment: dict[int, dict[str, object]] = {}
    for group_key, members_with_items in sorted(grouped.items()):
        target_code, source_system, card4 = group_key
        members = sorted(
            [row for row, _ in members_with_items],
            key=lambda row: str(row["direct_event_key"]),
        )
        event_keys = sorted(str(row["direct_event_key"]) for row in members)
        fact_shas = sorted(str(row["current_fact_sha256"]) for row in members)
        candidate_targets = sorted({
            str(target) for _, item in members_with_items
            for target in item.get("candidate_targets", [])
            if str(target)
        })
        evidence_records = {
            _inferred_target_source_key(record): record
            for _, item in members_with_items
            for record in [
                *item.get("evidence_records", []),
                *item.get("anchor_records", []),
            ]
            if isinstance(record, dict)
        }
        match_methods = sorted({
            str(method)
            for _, item in members_with_items
            for method in item.get("match_methods", [])
            if str(method)
        })
        countries = sorted({
            str(item.get("country") or "")
            for _, item in members_with_items
            if str(item.get("country") or "")
        })
        regions = sorted({
            str(item.get("region") or "")
            for _, item in members_with_items
            if str(item.get("region") or "")
        })
        occurred = sorted(str(row.get("occurred_on") or "") for row in members)
        if not occurred or any(not value for value in occurred):
            raise ValueError("inferred_external_target_payment_date_missing")
        country = countries[0] if len(countries) == 1 else "MULTI"
        region = regions[0] if len(regions) == 1 else "·".join(regions)
        audit = {
            "classification_path": INFERRED_EXTERNAL_TARGET_PATH,
            "source_records": [evidence_records[key] for key in sorted(evidence_records)],
            "candidate_target_set": candidate_targets,
            "candidate_target_set_sha256": _sha(candidate_targets),
            "member_event_keys": event_keys,
            "member_fact_shas": fact_shas,
            "member_fact_set_sha256": _sha(fact_shas),
            "match_methods": match_methods,
            "individual_match_asserted": False,
            "relation_asserted": False,
            "payment_window_is_not_service_period": True,
            "manual_classification_only": any(
                str(record.get("source_kind") or "") == "manual_ledger"
                for record in evidence_records.values()
            ),
            "direct_promotion_evidence_registered": False,
            "allocation_or_plan_created": False,
        }
        core = {
            "registry_version": INFERRED_EXTERNAL_REGISTRY_VERSION,
            "rule_id": INFERRED_EXTERNAL_RULE_ID,
            "source_system": source_system,
            "card_identity_sha256": _sha({
                "source": source_system, "card4": card4,
            }),
            "country": country,
            "region": region,
            "starts_on": occurred[0],
            "ends_on": occurred[-1],
            "target_code": target_code,
            "event_keys": event_keys,
            "fact_shas": fact_shas,
            "target_kind": INFERRED_EXTERNAL_TARGET_KIND,
        }
        payload = {"registry_core": core, "audit": audit}
        registry_sha256 = _sha(payload)
        registry = {
            **core,
            "registry_id": "trip-cluster:" + registry_sha256,
            "registry_sha256": registry_sha256,
            "members": members,
            "classification_path": INFERRED_EXTERNAL_TARGET_PATH,
            "schedule_status": "provisional_external_target",
            "payload_json": _canonical(payload).decode("utf-8"),
        }
        registries.append(registry)
        for row in members:
            by_payment[int(row["payment_id"])] = registry
    registries.sort(key=lambda row: str(row["registry_id"]))
    return {"registries": registries, "by_payment": by_payment}


def _training_indexes(
    training: list[dict[str, object]],
) -> dict[str, dict[tuple[str, ...], list[dict[str, object]]]]:
    indexes: dict[str, dict[tuple[str, ...], list[dict[str, object]]]] = {
        name: defaultdict(list) for name in (
            *FEATURE_NAMES, "use_merchant", "posted_merchant",
        )
    }
    for item in training:
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        if any(_adverse(payload.get(field)) for field in (
            "account", "cost_type", "bucket",
        )):
            continue
        row = {
            "source": str(payload.get("src") or ""),
            "merchant": str(payload.get("merchant") or ""),
            "biz": str(payload.get("biz") or ""),
            "currency": str(payload.get("currency") or ""),
            "card4": str(payload.get("card4") or ""),
            "occurred_on": str(payload.get("use_date") or ""),
            "posted_on": str(payload.get("post_date") or ""),
            "account": str(payload.get("account") or "").strip(),
            "cost_type": str(payload.get("cost_type") or "").strip(),
            "bucket": str(payload.get("bucket") or "").strip(),
            "historical_row_sha256": str(item.get("row_sha256") or ""),
        }
        for name in indexes:
            indexes[name][_feature_key(row, name)].append(row)
    return indexes


def _learned_value(
    row: dict[str, object], axis: str,
    indexes: dict[str, dict[tuple[str, ...], list[dict[str, object]]]],
    names: Iterable[str],
) -> tuple[str, str, int] | None:
    for name in names:
        peers = indexes[name].get(_feature_key(row, name), [])
        values = [str(peer.get(axis) or "").strip() for peer in peers]
        values = [value for value in values if not _adverse(value)]
        if values and len(set(values)) == 1:
            return values[0], name, len(values)
    return None


def _complete_axis_map(values: dict[str, set[str]]) -> dict[str, str] | None:
    if set(values) != set(ACTIVE_DIMENSIONS):
        return None
    if any(len(values[dimension]) != 1 for dimension in ACTIVE_DIMENSIONS):
        return None
    return {
        dimension: next(iter(values[dimension]))
        for dimension in ACTIVE_DIMENSIONS
    }


def _promoted_axis_maps(
    db: sqlite3.Connection, run_id: str,
) -> dict[int, dict[str, str]]:
    grouped: dict[int, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    rows = db.execute(
        """SELECT target_id,dimension,value
           FROM current_independently_promoted_decisions
           WHERE run_id=? AND target_type='payment'
             AND dimension IN ('account','cost_type','allocation_target')
             AND rule_id NOT LIKE 'payment-year-2025-cost-accounting-v1:%'""",
        (run_id,),
    ).fetchall()
    for payment_id, dimension, value in rows:
        grouped[int(payment_id)][str(dimension)].add(str(value))
    result: dict[int, dict[str, str]] = {}
    for payment_id, values in grouped.items():
        axes = _complete_axis_map(values)
        if axes is not None:
            result[payment_id] = axes
    return result


def _relation_group_key(row: dict[str, object]) -> tuple[str, ...]:
    return (
        str(row.get("card4") or ""),
        str(row.get("currency") or ""),
        str(row.get("foreign") or ""),
        str(row.get("relation_merchant") or row.get("merchant") or ""),
    )


def _reversal_relation_data(
    db: sqlite3.Connection,
    run_id: str,
    current: list[dict[str, object]],
) -> tuple[
    dict[int, list[dict[str, object]]],
    dict[str, list[int]],
]:
    """Return current-card reversal relations and verified unordered groups.

    The relation projector deliberately leaves KBO unordered groups without an
    individual purchase id.  Reconstructing the same content-addressed group
    here is safe because it uses only the current card rows and the relation
    hash; a group is usable only when every member has the same three axes.
    """
    relation_rows = db.execute(
        """SELECT r.id,r.transaction_id,r.related_transaction_id,r.relation_type,
                  r.reference_value,r.match_method
           FROM transaction_relations r
           JOIN direct_payment_projection_links l
             ON l.payment_id=r.transaction_id AND l.run_id=?
           WHERE r.relation_status NOT IN ('rejected','superseded')
           ORDER BY r.id""",
        (run_id,),
    ).fetchall()
    current_by_id = {int(row["payment_id"]): row for row in current}
    by_reversal: dict[int, list[dict[str, object]]] = defaultdict(list)
    by_group: dict[str, list[dict[str, object]]] = defaultdict(list)
    for relation_id, transaction_id, related_id, relation_type, reference, method in relation_rows:
        item = {
            "relation_id": int(relation_id),
            "transaction_id": int(transaction_id),
            "related_transaction_id": (
                None if related_id is None else int(related_id)
            ),
            "relation_type": str(relation_type),
            "reference_value": str(reference or ""),
            "match_method": str(method),
        }
        by_reversal[int(transaction_id)].append(item)
        if (
            item["related_transaction_id"] is None
            and item["match_method"]
            == "kbo_card4_currency_foreign_merchant_unordered_group"
            and item["reference_value"]
        ):
            by_group[item["reference_value"]].append(item)

    group_purchases: dict[str, list[int]] = {}
    for reference, members in by_group.items():
        reversal_rows = [
            current_by_id[item["transaction_id"]]
            for item in members
            if item["transaction_id"] in current_by_id
        ]
        if not reversal_rows:
            continue
        key = _relation_group_key(reversal_rows[0])
        if any(_relation_group_key(row) != key for row in reversal_rows):
            continue
        purchases = [
            row for row in current
            if row["transaction_type"] == "purchase"
            and str(row["source"]) == "KBO"
            and _relation_group_key(row) == key
        ]
        if len(purchases) != len(reversal_rows):
            continue
        computed_reference = "kbo-group:" + _sha({
            "key": key,
            "cancellations": sorted(
                str(row["external_key"]) for row in reversal_rows
            ),
            "purchases": sorted(
                str(row["external_key"]) for row in purchases
            ),
        })
        if computed_reference == reference:
            group_purchases[reference] = [
                int(row["payment_id"]) for row in purchases
            ]
    return dict(by_reversal), group_purchases


def _inherited_reversal_axes(
    row: dict[str, object],
    relations_by_reversal: dict[int, list[dict[str, object]]],
    group_purchases: dict[str, list[int]],
    axes_by_payment: dict[int, dict[str, str]],
) -> tuple[dict[str, str], str] | None:
    relations = relations_by_reversal.get(int(row["payment_id"]), [])
    direct_ids = {
        int(item["related_transaction_id"])
        for item in relations
        if item["related_transaction_id"] is not None
    }
    if len(relations) == 1 and len(direct_ids) == 1 and all(
        item["related_transaction_id"] is not None for item in relations
    ):
        related_id = next(iter(direct_ids))
        axes = axes_by_payment.get(related_id)
        if axes is not None:
            method = str(relations[0]["match_method"])
            return axes, f"{method}:unique_original"

    for item in relations:
        reference = str(item["reference_value"])
        purchase_ids = group_purchases.get(reference, [])
        if not purchase_ids:
            continue
        member_axes = [axes_by_payment.get(payment_id) for payment_id in purchase_ids]
        if any(axes is None for axes in member_axes):
            continue
        signatures = {
            tuple(str(axes[dimension]) for dimension in ACTIVE_DIMENSIONS)
            for axes in member_axes
            if axes is not None
        }
        if len(signatures) == 1:
            axes = member_axes[0]
            assert axes is not None
            return axes, "kbo_card4_currency_foreign_merchant_unordered_group:axis_invariant"
    return None


def _provisional_reversal_inheritance(
    row: dict[str, object],
    relations_by_reversal: dict[int, list[dict[str, object]]],
    provisional_axes_by_payment: dict[int, dict[str, str]],
    provisional_predictions_by_payment: dict[int, dict[str, object]],
) -> tuple[dict[str, str], dict[str, object]] | None:
    """Return one exact link to a needs-review original prediction.

    Only a single direct current-card relation is accepted.  Unordered M:N
    groups are intentionally excluded: they require a separate settlement or
    owner decision and must not silently inherit a provisional target.
    """
    relations = relations_by_reversal.get(int(row["payment_id"]), [])
    if len(relations) != 1:
        return None
    relation = relations[0]
    original_id = relation.get("related_transaction_id")
    if original_id is None:
        return None
    method = str(relation.get("match_method") or "")
    if "exact" not in method or "unordered" in method:
        return None
    original_payment_id = int(original_id)
    axes = provisional_axes_by_payment.get(original_payment_id)
    prediction = provisional_predictions_by_payment.get(original_payment_id)
    if axes is None or prediction is None:
        return None
    target = str(axes.get("allocation_target") or "")
    if not target or target in {TRIP_UNASSIGNED, OVERHEAD_TARGET, "취소환불"}:
        return None
    return axes, {
        "relation_id": int(relation["relation_id"]),
        "relation_match_method": method,
        "relation_reference_value": str(relation.get("reference_value") or ""),
        "original_payment_id": original_payment_id,
        "original_prediction_id": str(prediction["prediction_id"]),
        "original_target": target,
        "original_prediction_sha256": str(prediction["prediction_sha256"]),
    }


def _reversal_policy_fallback(
    row: dict[str, object],
    indexes: dict[str, dict[tuple[str, ...], list[dict[str, object]]]],
) -> tuple[dict[str, str], str]:
    """Classify an unlinked reversal without inventing an event date.

    A missing original link does not make the card row unusable.  The same
    current-card merchant policy used for a purchase still tells us whether
    the negative row is ordinary domestic overhead or prepaid/overseas travel.
    The latter stays in 여행_미배정; the reversal date is never treated as a
    service date.
    """
    account, account_path = _account_prediction_with_external_evidence(row, indexes)
    domestic = str(row.get("sub") or "") == "국내"
    ordinary_domestic = domestic and (
        _explicit_domestic_nontravel(row)
        or (
            not _domestic_travel_product(row)
            and not _payment_gateway(row)
        )
    )
    if ordinary_domestic:
        return {
            "account": account,
            "cost_type": OVERHEAD_COST,
            "allocation_target": OVERHEAD_TARGET,
        }, f"policy_fallback:{account_path}:domestic_nontravel"
    return {
        "account": account,
        "cost_type": TRIP_COST,
        "allocation_target": TRIP_UNASSIGNED,
    }, f"policy_fallback:{account_path}:service_period_missing"


def _domestic_travel_product(row: dict[str, object]) -> bool:
    text = _norm(str(row.get("merchant") or "") + " " + str(row.get("biz") or ""))
    return bool(_provider(row.get("merchant"))) or any(
        token in text for token in (
            "항공", "제주항공", "대한항공", "아시아나", "진에어",
            "티웨이", "에어서울", "에어부산", "ANAAIR", "KOREANAIR",
            "ASIANA", "JEJUAIR", "JINAIR", "TWAYAIR", "AIRSEOUL",
            "AIRBUSAN", "티켓", "보험", "투어", "TRAVEL", "여행",
            "하나투어", "모두투어", "여행사", "호텔", "숙박",
        )
    )


def _account_prediction(
    row: dict[str, object],
    indexes: dict[str, dict[tuple[str, ...], list[dict[str, object]]]],
) -> tuple[str, str]:
    learned = _learned_value(row, "account", indexes, FEATURE_NAMES)
    if learned is not None:
        return learned[0], f"learned:{learned[1]}:{learned[2]}"
    taxonomy = str(card_account(
        str(row.get("biz") or ""), str(row.get("merchant") or ""), "",
    ) or "").strip()
    if taxonomy and taxonomy != "기타":
        return taxonomy, "card_taxonomy"
    merchant = _norm(row.get("merchant"))
    provider = _provider(row.get("merchant"))
    if provider == "travelrover":
        return "여행자보험", "provider:travelrover"
    if any(token in merchant for token in (
        "AIR", "항공", "JEJU", "대한항공", "아시아나", "진에어", "고투게이트",
    )):
        return "항공료", "provider:airfare"
    if provider:
        return "숙박비", "provider:lodging_default"
    if str(row.get("sub") or "") == "해외":
        return "식비", "overseas_default"
    return "기타비용", "domestic_default"


def _account_prediction_with_external_evidence(
    row: dict[str, object],
    indexes: dict[str, dict[tuple[str, ...], list[dict[str, object]]]],
) -> tuple[str, str]:
    """Prefer an independently verified mail product kind for the account.

    Historical rows remain learning-only.  When the current row has a
    verified Gmail snapshot, the typed product is stronger than a learned
    merchant account (for example, an airfare must not inherit 식비).
    """
    owner_decision = row.get("current_owner_decision")
    if isinstance(owner_decision, dict):
        return str(owner_decision["account"]), "owner_decision:explicit_axis"
    evidence = row.get("gmail_payment_evidence")
    if (
        isinstance(evidence, dict)
        and str(evidence.get("authority_status") or "") == "verified_external"
        and str(evidence.get("classification") or "") == "overhead"
    ):
        return str(evidence.get("account") or "기타비용"), "gmail:overhead_kind"
    if (
        isinstance(evidence, dict)
        and str(evidence.get("authority_status") or "") == "verified_external"
        and str(evidence.get("classification") or "") == "travel"
    ):
        kind = str(evidence.get("travel_kind") or "")
        if kind == "airfare":
            return "항공료", "gmail:travel_kind:airfare"
        if kind in {"lodging", "lodging_cancellation"}:
            return "숙박비", "gmail:travel_kind:lodging"
        if kind in {"rental", "rental_family"}:
            return "교통비", "gmail:travel_kind:rental"
    return _account_prediction(row, indexes)


def _geographic_context_matches(
    row: dict[str, object],
    geographic_context: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    marker_text = f"{row.get('merchant') or ''} {row.get('biz') or ''}"
    if not is_taiwan_marker(marker_text):
        return []
    try:
        event_day = date.fromisoformat(str(row.get("occurred_on") or ""))
    except (TypeError, ValueError):
        return []
    matches: list[dict[str, object]] = []
    for context in geographic_context:
        try:
            start = date.fromisoformat(str(context["starts_on"]))
            end = date.fromisoformat(str(context["ends_on"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("geographic_context_date_invalid") from exc
        if start.year != 2026 or end.year != 2026:
            raise ValueError("geographic_context_year_invalid")
        if start <= event_day <= end:
            matches.append(context)
    return matches


def _target_path(rule_path: object) -> str:
    parts = str(rule_path or "").split("|")
    return parts[1] if len(parts) >= 2 else ""


def _is_provisional_prediction(
    prediction: dict[str, object], admitted_rule_paths: Iterable[str] = (),
) -> bool:
    admitted_paths = normalize_admitted_rule_paths(admitted_rule_paths)
    target_path = _target_path(prediction.get("rule_path"))
    return (
        target_path not in admitted_paths
        and target_path in PROVISIONAL_TARGET_PATHS
        or _has_row_finality_veto(prediction)
    )


def _is_review_prediction(
    prediction: dict[str, object], admitted_rule_paths: Iterable[str] = (),
) -> bool:
    admitted_paths = normalize_admitted_rule_paths(admitted_rule_paths)
    target_path = _target_path(prediction.get("rule_path"))
    return (
        target_path not in admitted_paths
        and target_path in REVIEW_TARGET_PATHS
        or _has_row_finality_veto(prediction)
    )


def _decision_status_for_prediction(
    prediction: dict[str, object], admitted_rule_paths: Iterable[str] = (),
) -> str:
    admitted_paths = normalize_admitted_rule_paths(admitted_rule_paths)
    if _has_row_finality_veto(prediction):
        return "needs_review"
    if _target_path(prediction.get("rule_path")) in (
        CONFIRMED_TRAVEL_TARGET_PATHS | admitted_paths
    ):
        return "confirmed"
    return (
        "needs_review"
        if _is_review_prediction(prediction, admitted_paths)
        else "confirmed"
    )


def _has_row_finality_veto(prediction: dict[str, object]) -> bool:
    evidence = prediction.get("axis_evidence")
    if not isinstance(evidence, dict):
        # Finality is an explicit admission claim.  A malformed or legacy
        # payload must not become final merely because it omitted the veto
        # block; fail closed and keep the row in review.
        return True
    finality = evidence.get("row_finality")
    return not (
        isinstance(finality, dict)
        and finality.get("eligible") is True
    )


def _direct_foreign_use_date_target(
    row: dict[str, object],
    schedule: dict[str, dict[str, object]],
    *,
    allow_known_foreign_gateway: bool = False,
    allow_generic_foreign: bool = False,
) -> str | None:
    """Use the card date only for an on-site foreign merchant.

    This is deliberately unavailable for OTA/provider/gateway rows: those
    rows are prepaid services and their payment date is not an event date.
    It exists to resolve cases such as an overseas restaurant or gas station
    whose date falls in exactly one trip, even when a historical tab key is
    M:N and ambiguous.
    """
    if str(row.get("sub") or "") != "해외":
        return None
    if _provider(row.get("merchant")) or _domestic_travel_product(row):
        return None
    merchant_text = _norm(
        f"{row.get('merchant') or ''} {row.get('biz') or ''}"
    )
    physical_match = any(
        _norm(token) in merchant_text
        for token in FOREIGN_DIRECT_USE_MERCHANT_TOKENS
    )
    # ``allow_generic_foreign`` is retained for call-site compatibility, but
    # it may not turn a generic online/airfare/OTA row into an on-site use-date
    # event.  A positive physical-merchant token is required in every path.
    if not physical_match:
        return None
    try:
        event_day = date.fromisoformat(str(row.get("occurred_on") or ""))
    except (TypeError, ValueError):
        return None
    if allow_generic_foreign and event_day.year != 2026:
        return None
    if _payment_gateway(row):
        if not allow_known_foreign_gateway or not any(
            _norm(token) in merchant_text
            for token in FOREIGN_DIRECT_USE_MERCHANT_TOKENS
        ):
            return None
    europe_marker = any(
        _norm(token) in merchant_text
        for token in FOREIGN_EUROPE_MERCHANT_MARKERS
    )
    matches = []
    for trip in schedule.values():
        if europe_marker and str(trip.get("region") or "") != "유럽":
            continue
        try:
            service_year = int(trip.get("service_year", 2026))
        except (TypeError, ValueError):
            continue
        if event_day.year != service_year:
            continue
        start = date(service_year, int(trip["mm"]), int(trip["dd"]))
        end = start + timedelta(days=int(trip["window"]) - 1)
        if start <= event_day <= end:
            matches.append(str(trip["tab"]))
    return matches[0] if len(matches) == 1 else None


def _gmail_schedule_target(
    evidence: dict[str, object],
    schedule: dict[str, dict[str, object]],
) -> str | None:
    """Resolve a Gmail service period through the canonical schedule.

    The mail snapshot may contain a target hint, but the hint is not an
    authority.  A target is returned only when the complete typed service
    period is contained by exactly one canonical schedule window and the
    snapshot carries its verified external digest.
    """
    source_contract = str(evidence.get("contract") or "")
    source_digest = str(evidence.get("source_digest") or "")
    trusted_source = (
        source_digest == GMAIL_EVIDENCE_SNAPSHOT_SHA256
        or source_contract == "pg-payment-evidence-v1" and bool(source_digest)
    )
    if (
        str(evidence.get("authority_status") or "") != "verified_external"
        or not trusted_source
        or str(evidence.get("classification") or "") != "travel"
        or str(evidence.get("target_status") or "")
        not in {"schedule_hint", "schedule_target"}
    ):
        return None
    try:
        start = date.fromisoformat(str(evidence.get("service_start") or ""))
        end = date.fromisoformat(str(evidence.get("service_end") or ""))
    except (TypeError, ValueError):
        return None
    if end < start:
        return None
    target_status = str(evidence.get("target_status") or "")
    target_hint = str(evidence.get("target_hint") or "")
    if target_status == "schedule_target" and target_hint:
        hinted_trip = schedule.get(target_hint)
        if isinstance(hinted_trip, dict):
            try:
                hinted_year = int(hinted_trip.get("service_year", 2026))
                if hinted_year != start.year:
                    raise ValueError("gmail_schedule_service_year_mismatch")
                hinted_start = date(
                    hinted_year, int(hinted_trip["mm"]), int(hinted_trip["dd"])
                )
                hinted_end = hinted_start + timedelta(
                    days=int(hinted_trip["window"]) - 1
                )
            except (KeyError, TypeError, ValueError):
                hinted_trip = None
            if (
                hinted_trip is not None
                and hinted_start <= start
                and end <= hinted_end
            ):
                # A verified external target label can disambiguate overlapping
                # calendar windows.  It names only the temporary target; it
                # never establishes a payment↔cancellation relation.
                return target_hint
    matches: list[str] = []
    for trip in schedule.values():
        try:
            service_year = int(trip.get("service_year", 2026))
            if service_year != start.year:
                continue
            trip_start = date(
                service_year, int(trip["mm"]), int(trip["dd"]),
            )
            trip_end = trip_start + timedelta(days=int(trip["window"]) - 1)
        except (KeyError, TypeError, ValueError):
            continue
        if trip_start <= start and end <= trip_end:
            matches.append(str(trip["tab"]))
    return matches[0] if len(matches) == 1 else None


def _verified_gmail_schedule_target(
    evidence: dict[str, object],
    schedule: dict[str, dict[str, object]],
) -> str | None:
    """Resolve only an explicitly auto-confirmed, unique canonical period."""
    if not bool(evidence.get("auto_confirmed")):
        return None
    target_hint = str(evidence.get("target_hint") or "")
    if not target_hint or str(evidence.get("target_status") or "") != "schedule_target":
        return None
    resolved = _gmail_schedule_target(evidence, schedule)
    if resolved != target_hint:
        return None
    try:
        start = date.fromisoformat(str(evidence["service_start"]))
        end = date.fromisoformat(str(evidence["service_end"]))
    except (KeyError, TypeError, ValueError):
        return None
    matches: list[str] = []
    for trip in schedule.values():
        try:
            service_year = int(trip.get("service_year", 2026))
            if service_year != start.year:
                continue
            trip_start = date(
                service_year, int(trip["mm"]), int(trip["dd"]),
            )
            trip_end = trip_start + timedelta(days=int(trip["window"]) - 1)
        except (KeyError, TypeError, ValueError):
            continue
        if trip_start <= start and end <= trip_end:
            matches.append(str(trip.get("tab") or ""))
    return target_hint if matches == [target_hint] else None


def _target_prediction(
    row: dict[str, object],
    indexes: dict[str, dict[tuple[str, ...], list[dict[str, object]]]],
    schedule: dict[str, dict[str, object]],
    geographic_context: Iterable[dict[str, object]] = (),
    *,
    manual_match: dict[str, object] | None = None,
    trip_cluster: dict[str, object] | None = None,
    placeholder: dict[str, object] | None = None,
    inferred_target: dict[str, object] | None = None,
    ota_service_target: dict[str, object] | None = None,
) -> tuple[str, str, str]:
    owner_decision = row.get("current_owner_decision")
    if isinstance(owner_decision, dict):
        return (
            str(owner_decision["allocation_target"]),
            OWNER_DECISION_CURRENT_SCOPE_PATH,
            "not_applicable",
        )
    gmail_evidence = row.get("gmail_payment_evidence")
    if (
        isinstance(gmail_evidence, dict)
        and str(gmail_evidence.get("classification") or "") == "overhead"
    ):
        return OVERHEAD_TARGET, GMAIL_PAYMENT_OVERHEAD_EVIDENCE_PATH, "not_applicable"
    if inferred_target is not None:
        target_code = str(inferred_target.get("target_code") or "")
        if target_code and target_code not in {TRIP_UNASSIGNED, OVERHEAD_TARGET}:
            return target_code, INFERRED_EXTERNAL_TARGET_PATH, "unique_match"
    if (
        isinstance(gmail_evidence, dict)
        and str(gmail_evidence.get("classification") or "") == "travel"
    ):
        if str(gmail_evidence.get("match_method") or "").endswith(
            "approval_family_source_card_merchant_unverified"
        ):
            return (
                TRIP_UNASSIGNED,
                GMAIL_PAYMENT_APPROVAL_FAMILY_PENDING_PATH,
                "ambiguous_match",
            )
        verified_target = _verified_gmail_schedule_target(
            gmail_evidence, schedule,
        )
        if verified_target is not None:
            return (
                verified_target,
                GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH,
                "unique_match",
            )
        resolved_target = _gmail_schedule_target(gmail_evidence, schedule)
        if resolved_target is not None:
            return resolved_target, GMAIL_PAYMENT_SERVICE_PERIOD_PATH, "unique_match"
        if str(gmail_evidence.get("service_start") or ""):
            return (
                TRIP_UNASSIGNED,
                GMAIL_PAYMENT_SERVICE_PERIOD_PENDING_PATH,
                "no_match",
            )
    if manual_match is not None:
        status = str(manual_match.get("status") or "")
        if status not in {
            "exact", "target_invariant",
            "amount_component_exact", "amount_component_target_invariant",
        }:
            ota_target_code = str(
                ota_service_target.get("target_code") or ""
                if isinstance(ota_service_target, dict) else ""
            )
            manual_target_codes = {
                str(item.get("manual_tab") or "")
                for item in manual_match.get("matches", [])
                if isinstance(item, dict) and str(item.get("manual_tab") or "")
            }
            if ota_target_code and (
                not manual_target_codes or ota_target_code in manual_target_codes
            ):
                return (
                    ota_target_code,
                    _ota_service_period_target_path(
                        ota_service_target.get("match_kind")
                    ),
                    "unique_match",
                )
            direct_target_exact = _direct_foreign_use_date_target(
                row, schedule, allow_generic_foreign=True,
            )
            if direct_target_exact is not None and (
                not manual_target_codes or direct_target_exact in manual_target_codes
            ):
                return (
                    direct_target_exact,
                    FOREIGN_USE_DATE_SCHEDULE_EXACT_PATH,
                    "unique_match",
                )
            direct_target = _direct_foreign_use_date_target(row, schedule)
            if direct_target is not None:
                return direct_target, FOREIGN_USE_DATE_SCHEDULE_PATH, "unique_match"
            return TRIP_UNASSIGNED, "manual_travel_tab_ambiguous", "ambiguous_match"
        manual_target = str(manual_match["target"])
        context_matches = _geographic_context_matches(
            row, geographic_context,
        )
        if (
            len(context_matches) == 1
            and str(context_matches[0]["tab"]) != manual_target
        ):
            return TRIP_UNASSIGNED, "manual_geography_conflict", "ambiguous_match"
        path_by_status = {
            "exact": "manual_travel_tab_exact",
            "target_invariant": "manual_travel_tab_mn_target_invariant",
            "amount_component_exact": MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
            "amount_component_target_invariant": MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH,
        }
        return manual_target, path_by_status[status], "unique_match"
    if ota_service_target is not None:
        target_code = str(ota_service_target.get("target_code") or "")
        if target_code and target_code not in {TRIP_UNASSIGNED, OVERHEAD_TARGET}:
            return (
                target_code,
                _ota_service_period_target_path(
                    ota_service_target.get("match_kind")
                ),
                "unique_match",
            )
    direct_target_exact = _direct_foreign_use_date_target(
        row, schedule, allow_generic_foreign=True,
    )
    if direct_target_exact is not None:
        return (
            direct_target_exact,
            FOREIGN_USE_DATE_SCHEDULE_EXACT_PATH,
            "unique_match",
        )
    if _explicit_domestic_nontravel(row):
        return OVERHEAD_TARGET, "domestic_nontravel_allowlist", "not_applicable"
    if trip_cluster is not None:
        cluster_path = (
            TRIP_CLUSTER_CANONICAL_EXACT_PATH
            if str(trip_cluster.get("target_kind") or "") == "canonical_schedule"
            else REGISTRY_PATH
        )
        return (
            str(trip_cluster["target_code"]),
            cluster_path,
            "unique_match",
        )
    if placeholder is not None:
        return (
            str(placeholder["target_code"]),
            str(placeholder["classification_path"]),
            str(placeholder.get("schedule_status") or "not_applicable"),
        )
    if (
        isinstance(gmail_evidence, dict)
        and str(gmail_evidence.get("classification") or "") == "travel"
    ):
        # The evidence establishes a travel-type service, not its service
        # period.  The caller turns this into a reservation placeholder.
        return (
            TRIP_UNASSIGNED,
            GMAIL_PAYMENT_TRAVEL_EVIDENCE_PATH,
            "not_applicable",
        )
    provider = _provider(row.get("merchant"))
    domestic = str(row.get("sub") or "") == "국내"
    travel_product = _domestic_travel_product(row)
    if is_taiwan_marker(f"{row.get('merchant') or ''} {row.get('biz') or ''}"):
        context_matches = _geographic_context_matches(row, geographic_context)
        if len(context_matches) == 1:
            return (
                str(context_matches[0]["tab"]),
                "current_card_geography_context_exact_2026",
                "unique_match",
            )
        if (
            str(row.get("sub") or "") == "해외"
            and not provider
            and not travel_product
            and not _payment_gateway(row)
        ):
            # The merchant itself contains an explicit Taiwan marker.  Keep
            # the row in the same service-period-pending path as other
            # direct foreign purchases; a missing geographic context must
            # not become an implicit destination assignment.
            return TRIP_UNASSIGNED, FOREIGN_SERVICE_PERIOD_PENDING_PATH, "no_match"
        return (
            TRIP_UNASSIGNED,
            "geographic_context_period_missing",
            "not_applicable",
        )
    direct_target = _direct_foreign_use_date_target(
        row, schedule, allow_known_foreign_gateway=True,
    )
    if direct_target is not None:
        return direct_target, FOREIGN_USE_DATE_SCHEDULE_PATH, "unique_match"
    # A domestic gateway is a payment rail, not a business purpose.  Only an
    # explicit ultimate-merchant allowlist above can close it as overhead.
    if domestic and not provider and not travel_product:
        if _payment_gateway(row):
            return TRIP_UNASSIGNED, DOMESTIC_GATEWAY_UNVERIFIED_PATH, "no_match"
        return OVERHEAD_TARGET, "domestic_nontravel_policy", "not_applicable"

    if provider or _payment_gateway(row) or travel_product:
        return (
            TRIP_UNASSIGNED,
            "prepaid_travel_service_period_not_in_card_fact",
            "not_applicable",
        )
    # A generic overseas merchant has no service-period evidence merely
    # because its card date falls inside a trip window.  Keep the row open
    # unless it belongs to the narrow physical cohort above.
    if str(row.get("sub") or "") == "해외":
        return TRIP_UNASSIGNED, FOREIGN_SERVICE_PERIOD_PENDING_PATH, "no_match"
    if domestic and not travel_product:
        return OVERHEAD_TARGET, "domestic_nontravel_policy", "not_applicable"
    try:
        event_day = date.fromisoformat(str(row.get("occurred_on") or ""))
    except (TypeError, ValueError):
        event_day = None
    matches: list[dict[str, object]] = []
    if event_day is not None:
        for trip in schedule.values():
            try:
                service_year = int(trip.get("service_year", 2026))
            except (TypeError, ValueError):
                continue
            if service_year != event_day.year:
                continue
            start = date(service_year, int(trip["mm"]), int(trip["dd"]))
            end = start + timedelta(days=int(trip["window"]) - 1)
            if start <= event_day <= end:
                matches.append({
                    **trip,
                    "starts_on": start.isoformat(),
                    "ends_on": end.isoformat(),
                })
    matches.sort(key=lambda item: str(item["tab"]))
    codes = {str(item["tab"]) for item in matches}
    schedule_status = (
        "unique_match" if len(matches) == 1
        else "ambiguous_match" if len(matches) > 1
        else "no_match"
    )
    if len(matches) == 1:
        return str(matches[0]["tab"]), "year_agnostic_use_date_schedule", schedule_status
    learned = _learned_value(row, "bucket", indexes, TARGET_FEATURE_NAMES)
    if learned is not None and learned[0] in codes:
        return learned[0], f"learned_target:{learned[1]}:{learned[2]}", schedule_status
    if domestic and travel_product:
        return TRIP_UNASSIGNED, "domestic_travel_service_period_missing", schedule_status
    return TRIP_UNASSIGNED, "foreign_service_period_missing", schedule_status


def _activity_placeholder_candidate(
    row: dict[str, object], preliminary_path: str,
) -> bool:
    """Limit activity placeholders to the exact direct-foreign residual path."""
    return (
        str(row.get("transaction_type") or "") == "purchase"
        and int(row.get("amount_krw") or 0) > 0
        and str(row.get("sub") or "") == "해외"
        and not _provider(row.get("merchant"))
        and not _domestic_travel_product(row)
        and not _payment_gateway(row)
        and preliminary_path == FOREIGN_SERVICE_PERIOD_PENDING_PATH
    )


def _build_expected(
    db: sqlite3.Connection,
    run_id: str,
    admitted_rule_paths: Iterable[str] = (),
) -> dict[str, object]:
    admitted_paths = normalize_admitted_rule_paths(admitted_rule_paths)
    training = _load_training(db)
    current = _load_current(db, run_id)
    owner_decisions = load_current_owner_decisions(db)
    # Keep legacy windows available for explainable candidate generation only;
    # direct_projection's allocation path uses explicit authority.
    schedule = load_trip_schedule(db)
    try:
        pg_mail_records = load_pg_mail_records(db)
        service_mail_records = load_service_mail_records(db)
    except ValueError as exc:
        # Focused legacy fixtures may predate the mandatory direct projection
        # inventory.  The production candidate cannot reach this branch
        # because pg_mail and service_mail are required inputs.
        if str(exc) not in {"pg_mail_source_missing", "service_mail_source_missing"}:
            raise
        pg_mail_records = []
        service_mail_records = {}
    for row in current:
        # The unified external-evidence slot accepts both the legacy sanitized
        # Gmail snapshot and the full redacted PG-mail index.  The current card
        # row remains the sole transaction amount/source fact.
        legacy_evidence = evidence_for_row(row)
        pg_evidence = pg_evidence_for_row(
            row, pg_mail_records, service_mail_records, schedule,
        )
        row["pg_payment_evidence"] = pg_evidence
        row["gmail_payment_evidence"] = pg_evidence or legacy_evidence
        row["current_owner_decision"] = decision_for_row(row, owner_decisions)
    assert_single_use([
        row.get("current_owner_decision") for row in current
    ])
    single_use_evidence = Counter(
        str(evidence["approval_number"])
        for row in current
        for evidence in [row.get("gmail_payment_evidence")]
        if isinstance(evidence, dict) and bool(evidence.get("single_use"))
    )
    if any(count > 1 for count in single_use_evidence.values()):
        raise ValueError("gmail_payment_evidence_reused")
    ota_mail_records = _load_ota_mail_records(db)
    indexes = _training_indexes(training)
    geographic_context = load_geographic_trip_context(db)
    (
        manual_index,
        manual_amount_index,
        manual_manifest,
        manual_source_manifest_sha256,
    ) = (
        _load_manual_travel_index(
            db,
            set(schedule) | {
                str(item["tab"]) for item in geographic_context
            },
        )
    )
    current_purchase_key_counts: Counter[tuple[str, str, int]] = Counter()
    current_amount_key_counts: Counter[tuple[str, int]] = Counter()
    for row in current:
        if (
            (
                str(row.get("transaction_type") or "") == "purchase"
                and int(row.get("amount_krw") or 0) > 0
            )
            or (
                str(row.get("transaction_type") or "") in REVERSAL_TYPES
                and int(row.get("amount_krw") or 0) < 0
            )
        ):
            key = _manual_match_key(row)
            if key is not None:
                current_purchase_key_counts[key] += 1
            if str(row.get("transaction_type") or "") == "purchase":
                try:
                    amount_key = (
                        str(row.get("source") or "").strip().upper(),
                        abs(int(row.get("amount_krw") or 0)),
                    )
                except (TypeError, ValueError):
                    amount_key = None
                if amount_key is not None and amount_key[0] and amount_key[1] > 0:
                    current_amount_key_counts[amount_key] += 1
    high_ids = {
        int(row[0]) for row in db.execute(
            """SELECT payment_id
               FROM direct_high_coverage_classifier_predictions
               WHERE run_id=?""", (run_id,),
        ).fetchall()
    }
    existing_ids = {
        int(row[0]) for row in db.execute(
            """SELECT DISTINCT target_id FROM classification_decisions
               WHERE target_type='payment'
                 AND dimension IN ('account','cost_type','allocation_target')
                 AND rule_id NOT LIKE 'payment-year-2025-cost-accounting-v1:%'
                 AND decision_status IN ('proposed','confirmed','needs_review')"""
        ).fetchall()
    } - high_ids
    purchase_candidates = [
        row for row in current
        if row["transaction_type"] == "purchase"
        and int(row["amount_krw"]) > 0
        and int(row["payment_id"]) not in existing_ids
    ]
    purchase_candidates.sort(key=lambda row: str(row["direct_event_key"]))
    reversal_candidates = [
        row for row in current
        if row["transaction_type"] in REVERSAL_TYPES
        and int(row["amount_krw"]) < 0
        and int(row["payment_id"]) not in existing_ids
    ]
    reversal_candidates.sort(key=lambda row: str(row["direct_event_key"]))
    preliminary_cluster_rows: list[dict[str, object]] = []
    preliminary_manual_matches: dict[int, dict[str, object] | None] = {}
    for row in [*purchase_candidates, *reversal_candidates]:
        manual_match = _manual_travel_match(
            row, manual_index, current_purchase_key_counts,
        )
        if manual_match is None:
            manual_match = _manual_travel_amount_component_match(
                row, manual_amount_index, current_amount_key_counts,
            )
        preliminary_manual_matches[int(row["payment_id"])] = manual_match
        if str(row.get("transaction_type") or "") == "purchase":
            _, preliminary_path, _ = _target_prediction(
                row, indexes, schedule, geographic_context,
                manual_match=manual_match,
            )
            if preliminary_path == FOREIGN_SERVICE_PERIOD_PENDING_PATH:
                preliminary_cluster_rows.append(row)
    trip_cluster_state = build_trip_cluster_registry(
        preliminary_cluster_rows, schedule, geographic_context,
    )
    trip_cluster_by_payment = trip_cluster_state["by_payment"]
    assert isinstance(trip_cluster_by_payment, dict)
    preliminary_baseline_by_payment: dict[int, tuple[str, str, str]] = {}
    for row in purchase_candidates:
        payment_id = int(row["payment_id"])
        preliminary_baseline_by_payment[payment_id] = _target_prediction(
            row, indexes, schedule, geographic_context,
            manual_match=preliminary_manual_matches.get(payment_id),
            trip_cluster=trip_cluster_by_payment.get(payment_id),
        )
    ota_service_period_by_payment = _build_ota_mail_service_period_targets(
        purchase_candidates,
        preliminary_baseline_by_payment,
        ota_mail_records,
        schedule,
    )
    activity_placeholder_rows: list[dict[str, object]] = []
    reservation_placeholder_rows: list[dict[str, object]] = []
    for row in purchase_candidates:
        payment_id = int(row["payment_id"])
        manual_match = preliminary_manual_matches[payment_id]
        preliminary_target, preliminary_path, _ = _target_prediction(
            row, indexes, schedule, geographic_context,
            manual_match=manual_match,
            trip_cluster=trip_cluster_by_payment.get(payment_id),
            ota_service_target=ota_service_period_by_payment.get(payment_id),
        )
        if preliminary_target != TRIP_UNASSIGNED:
            continue
        # An ambiguous manual classification is a genuine conflict.  Keep it
        # in the existing owner-review queue instead of hiding the conflict
        # inside a generic placeholder.
        if preliminary_path in {
            "manual_travel_tab_ambiguous", "manual_geography_conflict",
        }:
            continue
        provider = _provider(row.get("merchant"))
        travel_product = _domestic_travel_product(row)
        gmail_evidence = row.get("gmail_payment_evidence")
        gmail_service_period_pending = (
            isinstance(gmail_evidence, dict)
            and str(gmail_evidence.get("classification") or "") == "travel"
            and (
                str(gmail_evidence.get("service_start") or "")
                or str(gmail_evidence.get("match_method") or "").endswith(
                    "approval_family_source_card_merchant_unverified"
                )
            )
        )
        if _activity_placeholder_candidate(row, preliminary_path):
            activity_placeholder_rows.append(row)
        elif (
            not gmail_service_period_pending
            and (
                provider
                or travel_product
                or _known_direct_travel_service(row)
                or (
                    isinstance(gmail_evidence, dict)
                    and str(gmail_evidence.get("classification") or "")
                    == "travel"
                )
            )
        ):
            # A known travel provider/product is enough to say “travel-type
            # payment”, but not enough to say where or when the service was.
            reservation_placeholder_rows.append(row)
        # A bare domestic PG/gateway row is handled by the domestic-gateway
        # overhead policy in _target_prediction; it is not a travel signal.
    activity_placeholder_state = build_split_travel_activity_placeholder_registry(
        activity_placeholder_rows, schedule, geographic_context,
    )
    reservation_placeholder_state = build_reservation_placeholder_registry(
        reservation_placeholder_rows, schedule, geographic_context,
    )
    # A confirmed manual travel target can also make an exactly related
    # reversal safe to inherit.  Do not leave a review-only reversal registry
    # on that same payment, because the confirmed negative allocation would
    # then look like an allocation leak.
    relations_by_reversal, group_purchases = _reversal_relation_data(
        db, run_id, current,
    )
    confirmed_target_by_payment: dict[int, str] = {}
    for row in purchase_candidates:
        payment_id = int(row["payment_id"])
        manual_match = preliminary_manual_matches.get(payment_id)
        prediction = _target_prediction(
            row, indexes, schedule, geographic_context,
            manual_match=manual_match,
            trip_cluster=trip_cluster_by_payment.get(payment_id),
            ota_service_target=ota_service_period_by_payment.get(payment_id),
        )
        if prediction[1] not in CONFIRMED_TRAVEL_TARGET_PATHS:
            continue
        if prediction[0] not in {TRIP_UNASSIGNED, OVERHEAD_TARGET}:
            confirmed_target_by_payment[payment_id] = str(prediction[0])

    def reversal_has_confirmed_manual_original(row: dict[str, object]) -> bool:
        relations = relations_by_reversal.get(int(row["payment_id"]), [])
        direct_originals = {
            int(item["related_transaction_id"])
            for item in relations
            if item.get("related_transaction_id") is not None
        }
        if len(relations) == 1 and len(direct_originals) == 1:
            return next(iter(direct_originals)) in confirmed_target_by_payment
        for item in relations:
            reference = str(item.get("reference_value") or "")
            purchase_ids = group_purchases.get(reference, [])
            targets = {
                confirmed_target_by_payment.get(int(payment_id))
                for payment_id in purchase_ids
            }
            if purchase_ids and None not in targets and len(targets) == 1:
                return True
        return False

    reversal_activity_placeholder_rows = [
        row for row in reversal_candidates
        if (
            str(row.get("sub") or "") == "해외"
            and not _provider(row.get("merchant"))
            and not _domestic_travel_product(row)
            and not _payment_gateway(row)
            and preliminary_manual_matches.get(int(row["payment_id"])) is None
            and not reversal_has_confirmed_manual_original(row)
        )
    ]
    reversal_reservation_placeholder_rows = [
        row for row in reversal_candidates
        if (
            (
                _provider(row.get("merchant"))
                or _domestic_travel_product(row)
            )
            and preliminary_manual_matches.get(int(row["payment_id"])) is None
            and not reversal_has_confirmed_manual_original(row)
        )
    ]
    reversal_activity_placeholder_state = (
        build_split_reversal_activity_placeholder_registry(
            reversal_activity_placeholder_rows, schedule, geographic_context,
        )
    )
    reversal_reservation_placeholder_state = (
        build_reversal_reservation_placeholder_registry(
            reversal_reservation_placeholder_rows, schedule, geographic_context,
        )
    )
    placeholder_by_payment: dict[int, dict[str, object]] = {
        **activity_placeholder_state["by_payment"],
        **reservation_placeholder_state["by_payment"],
        **reversal_activity_placeholder_state["by_payment"],
        **reversal_reservation_placeholder_state["by_payment"],
    }
    baseline_by_payment: dict[int, tuple[str, str, str]] = {}
    for row in purchase_candidates:
        payment_id = int(row["payment_id"])
        baseline_by_payment[payment_id] = _target_prediction(
            row, indexes, schedule, geographic_context,
            manual_match=preliminary_manual_matches.get(payment_id),
            trip_cluster=trip_cluster_by_payment.get(payment_id),
            placeholder=placeholder_by_payment.get(payment_id),
            ota_service_target=ota_service_period_by_payment.get(payment_id),
        )
    inferred_target_by_payment = _build_inferred_external_targets(
        current,
        baseline_by_payment,
        preliminary_manual_matches,
        ota_mail_records,
        training,
        schedule,
    )
    verified_lodging_targets = _verified_lodging_fact_targets(
        db, run_id, current, baseline_by_payment, schedule,
    )
    for payment_id, item in verified_lodging_targets.items():
        _add_inferred_target(inferred_target_by_payment, payment_id, item)
    inferred_external_state = _build_inferred_external_registries(
        current, inferred_target_by_payment,
    )
    inferred_payment_ids = set(inferred_target_by_payment)

    def without_inferred_members(
        registries: Iterable[dict[str, object]],
    ) -> list[dict[str, object]]:
        return [
            registry for registry in registries
            if not any(
                int(member["payment_id"]) in inferred_payment_ids
                for member in registry.get("members", [])
            )
        ]

    all_trip_registries = [
        *without_inferred_members(trip_cluster_state["registries"]),
        *without_inferred_members(activity_placeholder_state["registries"]),
        *without_inferred_members(reservation_placeholder_state["registries"]),
        *without_inferred_members(
            reversal_activity_placeholder_state["registries"]
        ),
        *without_inferred_members(
            reversal_reservation_placeholder_state["registries"]
        ),
        *inferred_external_state["registries"],
    ]

    def registry_for_target_path(
        target_path: str,
        payment_id: int,
    ) -> dict[str, object] | None:
        """Return the registry that actually supports a target path.

        Canonical trip-cluster matches and temporary placeholders share the
        registry table, but they are not interchangeable evidence.  Keeping
        this choice explicit prevents a canonical cluster from accidentally
        being serialized as an activity/reservation placeholder.
        """
        if target_path in {REGISTRY_PATH, TRIP_CLUSTER_CANONICAL_EXACT_PATH}:
            return trip_cluster_by_payment.get(payment_id)
        if target_path in {
            ACTIVITY_PLACEHOLDER_PATH,
            RESERVATION_PLACEHOLDER_PATH,
        }:
            return placeholder_by_payment.get(payment_id)
        return None

    algorithm = {
        "model_contract": MODEL_CONTRACT,
        "rule_id": RULE_ID,
        "training_role": TRAINING_ROLE,
        "historical_features": list(FEATURE_NAMES),
        "target_features": list(TARGET_FEATURE_NAMES),
        "minimum_learning_support": 1,
        "domestic_nontravel": {
            "allocation_target": OVERHEAD_TARGET,
            "cost_type": OVERHEAD_COST,
            "exact_merchant_business_pairs": sorted(
                [list(item) for item in EXPLICIT_DOMESTIC_NONTRAVEL]
            ),
        },
        "ota_without_typed_service_period": TRIP_UNASSIGNED,
        "ota_mail_service_period_exact": {
            "exact_amount_preferred": True,
            "amount_tolerance_policy": OTA_AMOUNT_TOLERANCE_POLICY,
            "amount_tolerance_ratio_max": OTA_AMOUNT_TOLERANCE_RATIO,
            "tolerant_match_requires_one_mail_amount_candidate": True,
            "tolerant_match_requires_unique_card_mail_component": True,
            "provider_compatible_required": True,
            "all_mail_dates_must_fit_one_canonical_schedule_target": True,
            "payment_date_is_not_service_date": True,
            "m_to_n_requires_equal_card_and_mail_cardinalities": True,
            "m_to_n_row_pairing_asserted": False,
        },
        "ota_mail_sent_date_amount_target": {
            "path": OTA_MAIL_SENT_DATE_AMOUNT_TARGET_PATH,
            "candidate_only": True,
            "sent_date_window_days": OTA_MAIL_SENT_DATE_TOLERANCE_DAYS,
            "exact_amount_preferred": True,
            "amount_tolerance_policy": OTA_AMOUNT_TOLERANCE_POLICY,
            "service_date_must_resolve_unique_canonical_target": True,
            "m_to_n_requires_equal_card_and_mail_cardinalities": True,
            "m_to_n_row_pairing_asserted": False,
            "payment_date_is_not_service_date": True,
        },
        "verified_lodging_fact_target": {
            "path": "ota_verified_lodging_fact_amount_target_candidate",
            "source_kind": "direct_verified_lodging_facts",
            "lifecycle_status": "active_only",
            "exact_amount_preferred": True,
            "amount_tolerance_policy": OTA_AMOUNT_TOLERANCE_POLICY,
            "m_to_n_requires_equal_card_and_fact_cardinalities": True,
            "m_to_n_row_pairing_asserted": False,
            "payment_date_is_not_service_date": True,
        },
        "foreign_use_date_schedule_exact_2026": {
            "current_card_only": True,
            "year_required": 2026,
            "ota_provider_and_payment_gateway_excluded": True,
            "one_canonical_schedule_target_required": True,
            "card_use_date_is_event_date_for_physical_use_only": True,
        },
        "axis_evidence_contract": {
            "contract": AXIS_EVIDENCE_CONTRACT,
            "rule_id": RULE_ID,
            "current_transaction_fact_required": True,
            "target_evidence_references_required": True,
            "account": {
                "source_kind": "current_card_policy",
                "manual_travel_tab_used": False,
            },
            "cost_type": {
                "source_kind": "current_card_policy",
                "travel_target_implies_travel_cost": True,
                "vat_dimension": "excluded",
            },
            "allocation_target": {
                "source_kind_for_manual_amount_component": "manual_travel_tab_classification_only",
                "transaction_fact_source": "current_card",
                "manual_travel_tab_is_strong_target_classification": True,
                "manual_travel_tab_transaction_evidence": False,
            },
            "m_to_n_individual_pairing_asserted": False,
        },
        "inferred_external_target": {
            "path": INFERRED_EXTERNAL_TARGET_PATH,
            "rule_id": INFERRED_EXTERNAL_RULE_ID,
            "registry_version": INFERRED_EXTERNAL_REGISTRY_VERSION,
            "registry_count": len(inferred_external_state["registries"]),
            "candidate_set_required": True,
            "individual_match_asserted": False,
            "relation_asserted": False,
            "payment_window_is_not_service_period": True,
            "direct_promotion_evidence_registered": False,
            "allocation_or_plan_created": False,
            "registries": [
                registry_manifest(row)
                for row in inferred_external_state["registries"]
            ],
        },
        "historical_target_learning": {
            "source_kind": "classifier_training",
            "role": TRAINING_ROLE,
            "current_card_transaction_fact_only": True,
            "exact_key": ["source", "occurred_on", "absolute_amount_krw"],
            "year_required": 2026,
            "canonical_target_required": True,
            "card4_or_normalized_merchant_support_required": True,
            "m_to_n_target_invariant_only": True,
            "individual_payment_pairing_asserted": False,
            "promotion_evidence_registered": False,
        },
        "yakushima_portal_target_candidate": {
            "source_kind": "authenticated_booking_portal",
            "portal_commit": YAKUSHIMA_PORTAL_COMMIT,
            "portal_path": YAKUSHIMA_PORTAL_PATH,
            "portal_file_sha256": YAKUSHIMA_PORTAL_FILE_SHA256,
            "booking_number": YAKUSHIMA_PORTAL_BOOKING,
            "card_signature": {
                "source": "KBO",
                "occurred_on": "2026-05-26",
                "card4": "8835",
                "currency": "JPY",
                "foreign_amount": "118800",
                "amount_krw": 1150385,
                "merchant": "AGODA.COM YAKUSHIMA",
            },
            "target": "1127_야쿠시마",
            "card_booking_bijection_asserted": False,
            "promotion_evidence_registered": False,
        },
        "gmail_payment_evidence": {
            "contract": GMAIL_EVIDENCE_CONTRACT,
            "snapshot_sha256": GMAIL_EVIDENCE_SNAPSHOT_SHA256,
            "match_rule": (
                "exact_approval_source_amount_or_exact_source_date_amount_"
                "merchant_token_or_approval_family_source_card_merchant_unverified"
            ),
            "source_digest_required": True,
            "target_resolution": (
                "service_period_contained_by_exactly_one_canonical_schedule_window"
            ),
            "amount_is_transaction_evidence": False,
            "travel_effect": "typed_service_period_only",
            "overhead_effect": "explicit_overhead_classification",
            "verified_service_period_path": GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH,
            "verified_requires_unique_canonical_target": True,
            "verified_requires_auto_confirmed": True,
        },
        "current_owner_decision": {
            "contract": OWNER_DECISION_CONTRACT,
            "source_kind": "current_owner_decision",
            "exact_match": "source+date+approval+amount+merchant_token",
            "single_use": True,
            "scope_status_is_audited": True,
            "manual_ledger_not_used": True,
        },
        "year_aware_schedule": True,
        "payment_date_not_ota_service_date": True,
        "geographic_trip_context": {
            "source_kind": "geographic_trip_context",
            "schema_version": "current-geographic-trip-context-v1",
            "targets": context_manifest(geographic_context),
            "current_card_geography_required": True,
            "transaction_evidence_allowed": False,
            "payment_date_is_service_date": False,
            "marker_rule": "standalone_TW_or_explicit_Taiwan_city_token",
        },
        "manual_travel_tab": {
            "source_kind": "manual_ledger",
            "classification_only": True,
            "transaction_evidence_allowed": False,
            "match_key": [
                "current_source+occurred_on+abs_amount_krw",
                "current_source+abs_amount_krw_component_for_prepaid_service",
            ],
            "payment_date_used_as_service_date": False,
            "requires_one_current_event": False,
            "requires_one_manual_row": False,
            "requires_valid_unique_tab": True,
            "date_independent_component_requires_source_and_amount": True,
            "date_independent_component_target_invariant_allowed": True,
            "individual_payment_pair_asserted": False,
            "manual_amount_sign_used_for_classification": False,
            "ambiguous_action": "travel_unassigned_needs_review",
            "source_manifest_sha256": manual_source_manifest_sha256,
        },
        "trip_cluster_registry": {
            "rule_id": str(trip_cluster_state["rule_id"]),
            "registry_version": str(trip_cluster_state["registry_version"]),
            "registry_count": len(trip_cluster_state["registries"]),
            "registries": [
                registry_manifest(row)
                for row in trip_cluster_state["registries"]
            ],
            "conflicted_registry_count": int(
                trip_cluster_state["conflicted_registry_count"]
            ),
            "canonical_schedule_target_path": TRIP_CLUSTER_CANONICAL_EXACT_PATH,
            "canonical_schedule_target_is_confirmed": True,
            "new_registry_target_is_provisional": True,
        },
        "travel_activity_placeholder": {
            "path": ACTIVITY_PLACEHOLDER_PATH,
            "rule_id": str(activity_placeholder_state["rule_id"]),
            "registry_version": str(
                activity_placeholder_state["registry_version"]
            ),
            "registry_count": len(activity_placeholder_state["registries"]),
            "registries": [
                registry_manifest(row)
                for row in activity_placeholder_state["registries"]
            ],
            "target_completeness": "activity_only",
            "payment_window_is_not_service_period": True,
            "currency_used_to_create_country": False,
        },
        "reservation_placeholder": {
            "path": RESERVATION_PLACEHOLDER_PATH,
            "rule_id": str(reservation_placeholder_state["rule_id"]),
            "registry_version": str(
                reservation_placeholder_state["registry_version"]
            ),
            "registry_count": len(reservation_placeholder_state["registries"]),
            "registries": [
                registry_manifest(row)
                for row in reservation_placeholder_state["registries"]
            ],
            "target_completeness": "reservation_only",
            "service_period_status": "unknown_not_payment_date",
            "payment_window_is_not_service_period": True,
            "gateway_only_excluded": True,
        },
        "reversal_placeholder": {
            "activity_registry_count": len(
                reversal_activity_placeholder_state["registries"]
            ),
            "reservation_registry_count": len(
                reversal_reservation_placeholder_state["registries"]
            ),
            "exact_relation_required_for_original_inheritance": True,
            "payment_window_is_not_service_period": True,
        },
        "reversal_axis_inheritance": {
            "exact_original": True,
            "unordered_group": "only_when_all_purchase_axes_are_identical",
            "unlinked_fallback": (
                "merchant_policy_only; no reversal date as service date"
            ),
        },
        "vat_dimension": "excluded",
    }
    algorithm["structural_rule_admission"] = admission_manifest(admitted_paths)
    model_sha256 = _sha(algorithm)
    model_id = "high-coverage-model:" + model_sha256
    predictions: list[dict[str, object]] = []
    withheld: list[dict[str, str]] = []
    for row in purchase_candidates:
        account, account_path = _account_prediction_with_external_evidence(row, indexes)
        manual_match = preliminary_manual_matches[int(row["payment_id"])]
        target, target_path, schedule_status = _target_prediction(
            row, indexes, schedule, geographic_context,
            manual_match=manual_match,
            trip_cluster=trip_cluster_by_payment.get(int(row["payment_id"])),
            placeholder=placeholder_by_payment.get(int(row["payment_id"])),
            inferred_target=inferred_target_by_payment.get(int(row["payment_id"])),
            ota_service_target=ota_service_period_by_payment.get(
                int(row["payment_id"])
            ),
        )
        cost_type = (
            OVERHEAD_COST
            if target == OVERHEAD_TARGET
            else TRIP_COST
        )
        if not account or not cost_type or not target:
            withheld.append({
                "direct_event_key": str(row["direct_event_key"]),
                "current_evidence_id": str(row["current_evidence_id"]),
                "reason_code": "high_classifier_axis_generation_failed",
                "detail_sha256": _sha(row),
            })
            continue
        rule_path = f"{account_path}|{target_path}|cost:{'overhead' if cost_type == OVERHEAD_COST else 'travel'}"
        confidence = (
            0.99 if target_path == GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH else
            0.99 if target_path == OWNER_DECISION_CURRENT_SCOPE_PATH else
            0.99 if target_path in OTA_MAIL_SERVICE_PERIOD_PATHS else
            0.99 if target_path == FOREIGN_USE_DATE_SCHEDULE_EXACT_PATH else
            0.91 if target_path in {
                "manual_travel_tab_exact",
                "manual_travel_tab_mn_target_invariant",
                MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
                MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH,
            } else
            0.96 if target_path == GMAIL_PAYMENT_SERVICE_PERIOD_PATH else
            0.78 if target_path == INFERRED_EXTERNAL_TARGET_PATH else
            0.94 if target_path == FOREIGN_USE_DATE_SCHEDULE_PATH else
            0.93 if target_path == "current_card_geography_context_exact_2026" else
            0.92 if target_path == TRIP_CLUSTER_CANONICAL_EXACT_PATH else
            0.88 if target_path == REGISTRY_PATH else
            0.56 if target_path == ACTIVITY_PLACEHOLDER_PATH else
            0.54 if target_path == RESERVATION_PLACEHOLDER_PATH else
            0.98 if target_path == "year_agnostic_use_date_schedule"
            and account_path.startswith("learned:") else
            0.92 if target_path == "year_agnostic_use_date_schedule" else
            0.86 if account_path.startswith("learned:") else
            0.62 if target == TRIP_UNASSIGNED else 0.72
        )
        confidence_label = (
            "메일+레거시 복합확정"
            if target_path == GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH else
            "사용자 결정 확정"
            if target_path == OWNER_DECISION_CURRENT_SCOPE_PATH else
            "OTA메일+카드금액+행사기간확정"
            if target_path == OTA_MAIL_SERVICE_PERIOD_EXACT_PATH else
            "OTA메일+카드M:N+공통행사기간확정"
            if target_path == OTA_MAIL_SERVICE_PERIOD_MN_PATH else
            "OTA메일+카드금액 2% 이내+행사기간확정"
            if target_path == OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH else
            "OTA메일+카드M:N 금액 2% 이내+공통행사기간확정"
            if target_path == OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH else
            "해외현장일자+단일행사기간확정"
            if target_path == FOREIGN_USE_DATE_SCHEDULE_EXACT_PATH else
            "수기여행탭-여행대상확정"
            if target_path == "manual_travel_tab_exact" else
            "수기여행탭-M:N대상불변-여행대상확정"
            if target_path == "manual_travel_tab_mn_target_invariant" else
            "수기여행탭-결제일독립-여행대상확정"
            if target_path == MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH else
            "수기여행탭-M:N결제일독립-공통대상확정"
            if target_path == MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH else
            "메일복합일치-행사기간확인-자동임시"
            if target_path == GMAIL_PAYMENT_SERVICE_PERIOD_PATH else
            "외부·지역·M:N후보묶음-자동임시"
            if target_path == INFERRED_EXTERNAL_TARGET_PATH else
            "해외현장일자-수기충돌대체-자동임시"
            if target_path == FOREIGN_USE_DATE_SCHEDULE_PATH else
            "현재카드대만표식-사용자확인대기"
            if target_path == "current_card_geography_context_exact_2026" else
            "카드클러스터+정식일정-여행대상확정"
            if target_path == TRIP_CLUSTER_CANONICAL_EXACT_PATH else
            "카드별지역클러스터-사용자확인대기"
            if target_path == REGISTRY_PATH else
            "해외사용-임시활동-사용자확인대기"
            if target_path == ACTIVITY_PLACEHOLDER_PATH else
            "여행결제-행사기간미상-사용자확인대기"
            if target_path == RESERVATION_PLACEHOLDER_PATH else
            "학습패턴+행사일" if confidence >= 0.9 else
            "카드업종+정책" if confidence >= 0.7 else
            "정책자동-행사일미확정"
        )
        rationale = (
            "현재 카드의 반복 학습패턴·카드업종·국내외 정책을 적용하고, "
            "여행/OTA 결제는 결제일을 행사일로 사용하지 않음"
        )
        if target_path == OWNER_DECISION_CURRENT_SCOPE_PATH:
            owner_decision = row.get("current_owner_decision") or {}
            rationale = (
                f"사용자 결정 원천 {owner_decision.get('decision_id', '')}을 "
                f"카드 원장의 발급원천·이용일·승인번호·금액·가맹점 토큰으로 "
                f"정확히 연결해 {target}으로 확정함. "
                f"scope_status={owner_decision.get('scope_status', '')}. "
                f"{owner_decision.get('rationale', '')}"
            )
        elif target_path == GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH:
            evidence = row.get("gmail_payment_evidence") or {}
            rationale = (
                "Gmail 메일의 승인원천·이용일·금액·가맹점 토큰과 예약 서비스기간이 "
                "정확히 일치하고 canonical 행사기간이 하나뿐이며, 레거시 분류는 "
                f"보조 교차검증으로만 확인됨({evidence.get('legacy_cross_check', '')}). "
                f"행사기간 {evidence.get('service_start', '')}~"
                f"{evidence.get('service_end', '')}, 대상 {target}으로 확정함. "
                "카드 금액은 원장값만 사용하고 메일 본문·개인정보는 저장하지 않음"
            )
        elif target_path in {
            "manual_travel_tab_exact",
            "manual_travel_tab_mn_target_invariant",
            MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
            MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH,
        }:
            manual_items = manual_match.get("matches", []) if manual_match else []
            manual_item = manual_items[0] if manual_items else {}
            manual_keys = ", ".join(
                str(item["manual_source_key"]) for item in manual_items
            )
            if target_path in {
                "manual_travel_tab_exact",
                MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
            }:
                match_scope = str(
                    (manual_match or {}).get("match_scope")
                    or "source_date_absolute_amount"
                )
                date_note = (
                    "결제일과 수기행 날짜가 달라도 서비스일로 사용하지 않고 "
                    "발급원천·절댓값 금액 구성요소로만 연결함"
                    if target_path == MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH
                    else ""
                )
                rationale = (
                    f"현재 카드의 {match_scope}가 수기 여행 탭 {target}과 단일 구성요소로 "
                    f"일치해 여행 대상 {target}으로 확정함(수기행 {manual_keys}, 행해시 "
                    f"{manual_item.get('manual_source_sha256','')}, 카드 "
                    f"{manual_item.get('manual_card','')}, 날짜 "
                    f"{manual_item.get('manual_date','')}, 금액 "
                    f"{manual_item.get('manual_amount_krw','')}). "
                    f"{date_note} 수기 행은 거래 결제증거가 아니며, 금액·가맹점·날짜는 "
                    "현재 카드 원장으로 확인함"
                )
            else:
                rationale = (
                    f"현재 카드·수기 여행 탭의 키가 M:N으로 겹치지만 모든 수기 후보가 "
                    f"동일한 여행 탭 {target}을 가리켜 여행 대상만 확정함(수기행 "
                    f"{manual_keys}). 결제일과 수기행 날짜가 달라도 서비스일로 사용하지 않으며, "
                    "발급원천·절댓값 금액 구성요소가 공통으로 가리키는 대상만 확정함. "
                    "개별 카드행↔수기행 1:1 관계와 수기행의 거래증거성은 "
                    "주장하지 않으며, 카드 원장과 수기 여행 탭이 공통으로 가리키는 대상만 확정함"
                )
        elif target_path in OTA_MAIL_SERVICE_PERIOD_PATHS:
            ota_target = ota_service_period_by_payment[int(row["payment_id"])]
            service_dates = ", ".join(
                str(value) for value in ota_target.get("service_dates", [])
            )
            amount_method = str(
                ota_target.get("amount_match_method") or ""
            )
            amount_difference_ratio = float(
                ota_target.get("amount_difference_ratio") or 0.0
            )
            amount_note = (
                "카드 금액과 메일 금액의 차이가 2% 이내이고, 메일 금액 후보가 "
                "하나뿐인 별도 허용 규칙을 적용해"
                if amount_method == OTA_AMOUNT_TOLERANCE_POLICY
                else "현재 카드의 OTA 가맹점·결제금액과 허용된 OTA 메일의 동일 금액을 정확히 대조해"
            )
            rationale = (
                f"{amount_note} 메일 행사일 전체가 canonical 일정표의 한 여행에만 "
                f"들어가므로 {target}으로 확정함. 행사일 후보 {service_dates}; "
                f"카드 결제일 {row.get('occurred_on', '')}은 행사일로 사용하지 않음. "
                f"금액 차이율 {amount_difference_ratio:.4%}. "
                "M:N인 경우 개별 카드행↔메일행의 1:1 관계는 주장하지 않고 공통 대상만 확정함"
            )
        elif target_path == FOREIGN_USE_DATE_SCHEDULE_EXACT_PATH:
            rationale = (
                "현재 카드가 해외 현장 가맹점으로 기록되고 결제대행·OTA·여행상품이 "
                "아니며, 2026년 카드 이용일이 canonical 일정표의 한 여행기간에만 "
                f"들어가므로 {target}으로 확정함. 카드 이용일 "
                f"{row.get('occurred_on', '')}을 현장 사용일로 사용했고, 결제일과 행사일이 "
                "다를 수 있는 OTA·항공·예약형 가맹점에는 이 경로를 적용하지 않음"
            )
        elif target_path == "current_card_geography_context_exact_2026":
            rationale = (
                "현재 카드 원자료의 대만 지명·국가 표식과 2026년 1월 대만 맥락을 "
                "함께 적용해 임시 배정했으며, 수기·학습자료는 거래 증거로 사용하지 않음. "
                "사용자 확인 전 최종 배정하지 않음"
            )
        elif target_path == GMAIL_PAYMENT_OVERHEAD_EVIDENCE_PATH:
            evidence = row.get("gmail_payment_evidence") or {}
            rationale = (
                "Gmail 결제영수증을 승인번호·발급원천으로 정확히 연결해 실제 가맹점과 "
                f"상품({evidence.get('product', '')})을 확인했으므로 기타비용으로 종결함. "
                "메일 금액은 카드 거래금액을 대체하지 않으며, 메일 본문·개인정보는 저장하지 않음"
            )
        elif target_path == GMAIL_PAYMENT_SERVICE_PERIOD_PATH:
            evidence = row.get("gmail_payment_evidence") or {}
            rationale = (
                "Gmail 메일과 현재 카드의 발급원천·이용일·금액·가맹점 토큰을 함께 "
                "맞춰 여행 서비스와 행사기간을 확인해 임시 배정함. "
                f"행사기간 {evidence.get('service_start', '')}~"
                f"{evidence.get('service_end', '')}, 대상 {target}. "
                "카드 금액은 원장값을 사용했고, 메일 본문·개인정보는 저장하지 않으며 "
                "사용자 확정 전 최종 전기하지 않음"
            )
        elif target_path == INFERRED_EXTERNAL_TARGET_PATH:
            inferred = inferred_target_by_payment.get(int(row["payment_id"]), {})
            candidates = ", ".join(
                str(value) for value in inferred.get("candidate_targets", [])
            )
            rationale = (
                "현재 카드와 외부 메일·지역표식·수기 여행 탭 후보를 하나의 "
                "해시 registry로 묶어 임시 대상을 제안함. 후보 집합은 "
                f"{candidates}이며 개별 행의 1:1 짝짓기·취소관계·행사기간을 "
                "확정하지 않음. 사용자 확인 전 배부·전기하지 않음"
            )
        elif target_path == FOREIGN_USE_DATE_SCHEDULE_PATH:
            rationale = (
                "수기 여행 탭 후보는 서로 충돌하지만, 현재 해외 카드 원장의 이용일이 "
                f"단 하나의 행사기간 {target}에 들어가고 OTA·결제대행 가맹점이 아니어서 "
                "현재 카드 이용일을 직접 행사일로 적용해 임시 배정함. "
                "수기행은 거래증거로 사용하지 않으며 사용자 확정 전 최종 전기하지 않음"
            )
        elif target_path == TRIP_CLUSTER_CANONICAL_EXACT_PATH:
            cluster = trip_cluster_by_payment[int(row["payment_id"])]
            rationale = (
                "현재 카드의 같은 발급원천·카드 식별자·지역에서 이용일 2일 이상, "
                "양수 구매 3건 이상, 실제 가맹점 2곳 이상인 엄격한 클러스터가 "
                f"정식 일정표 {target} 하나와 겹쳐 여행 대상으로 확정함. "
                f"레지스트리 {cluster['registry_id']} / {cluster['starts_on']}~"
                f"{cluster['ends_on']}. 클러스터는 개별 행의 수기 거래증거·결제취소 관계가 "
                "아니며, 계정·비용축은 현재 카드 정책으로 산출함"
            )
        elif target_path == REGISTRY_PATH:
            cluster = trip_cluster_by_payment[int(row["payment_id"])]
            rationale = (
                "같은 발급원천·카드 식별자·지역에서 이용일 2일 이상, 양수 구매 3건 이상, "
                "실제 가맹점 2곳 이상이 7일 안에 묶여 임시 여행으로 제안함. "
                f"레지스트리 {cluster['registry_id']} / {cluster['starts_on']}~"
                f"{cluster['ends_on']} / {cluster['region']}. "
                "임시 대상은 정식 일정표가 아니며 사용자 확인 전 최종 배정하지 않음"
            )
        elif target_path == ACTIVITY_PLACEHOLDER_PATH:
            placeholder = placeholder_by_payment[int(row["payment_id"])]
            rationale = (
                "현재 카드 원자료에서 해외 현장 사용이 확인되어 이용일 묶음으로 "
                "임시활동 대상을 만들었지만, 정식 여행 대상·행사기간은 아직 모름. "
                f"레지스트리 {placeholder['registry_id']} / "
                f"카드 이용창 {placeholder['starts_on']}~{placeholder['ends_on']}. "
                "통화만으로 국가를 정하지 않았고, 사용자 확인 전 배부·전기하지 않음"
            )
        elif target_path == RESERVATION_PLACEHOLDER_PATH:
            placeholder = placeholder_by_payment[int(row["payment_id"])]
            rationale = (
                "현재 카드 가맹점이 OTA·항공·여행상품으로 여행성은 보이지만, "
                "결제일을 행사일로 사용하지 않고 행사기간을 미상으로 둔 임시예약 대상임. "
                f"레지스트리 {placeholder['registry_id']}. "
                "사용자/예약자료 확인 전 배부·전기하지 않음"
            )
        elif target_path == "manual_travel_tab_ambiguous":
            rationale = (
                "수기 여행 탭과 현재 카드의 발급사·이용일·금액 키가 1:1이 아니어서 "
                "여행_미배정으로 보류하며 대만 지리표식으로 우회하지 않음"
            )
        elif target_path == "manual_geography_conflict":
            rationale = (
                "수기 여행 탭과 현재 카드 대만 지리 맥락이 서로 다른 여행을 가리켜 "
                "어느 쪽도 선택하지 않고 여행_미배정으로 보류"
            )
        target_evidence_source = (
            "manual_travel_tab_target_only"
            if target_path in {
                "manual_travel_tab_exact",
                "manual_travel_tab_mn_target_invariant",
                MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
                MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH,
            }
            else target_path
        )
        target_registry = registry_for_target_path(
            target_path, int(row["payment_id"])
        )
        axis_evidence = _axis_evidence(
            row,
            account=account,
            cost_type=cost_type,
            target=target,
            account_path=account_path,
            target_path=target_path,
            target_evidence_source=target_evidence_source,
            manual_match=manual_match,
            ota_service_target=ota_service_period_by_payment.get(
                int(row["payment_id"])
            ),
            geographic_context=geographic_context,
            target_registry=target_registry,
            inferred_target=inferred_target_by_payment.get(
                int(row["payment_id"])
            ),
            gmail_evidence=row.get("gmail_payment_evidence"),
            owner_decision=row.get("current_owner_decision"),
            admitted_rule_paths=admitted_paths,
        )
        rationale = (
            f"축별 근거: 계정={account_path}(현재 카드 정책), 비용={cost_type}"
            "(현재 카드 정책), 여행대상="
            f"{target_evidence_source}(현재 카드 거래사실 유지). {rationale}"
        )
        feature = {
            "source": row["source"], "merchant": _norm(row["merchant"]),
            "biz": _norm(row["biz"]), "currency": _norm(row["currency"]),
            "card4": _norm(row["card4"]), "occurred_on": row["occurred_on"],
            "posted_on": row["posted_on"], "target": target,
            "geographic_context": context_manifest(geographic_context),
            "manual_travel_tab_match": manual_match,
            "gmail_payment_evidence": row.get("gmail_payment_evidence"),
            "ota_mail_service_period_target": ota_service_period_by_payment.get(
                int(row["payment_id"])
            ),
            "current_owner_decision": row.get("current_owner_decision"),
            "axis_evidence": axis_evidence,
            "inferred_external_target": inferred_target_by_payment.get(
                int(row["payment_id"])
            ),
            "trip_cluster_registry": (
                registry_manifest(registry)
                if (registry := registry_for_target_path(
                    target_path, int(row["payment_id"])
                )) is not None else None
            ),
        }
        prediction_core = {
            "model_contract": MODEL_CONTRACT,
            "model_sha256": model_sha256,
            "direct_event_key": row["direct_event_key"],
            "current_fact_sha256": row["current_fact_sha256"],
            "account": account, "cost_type": cost_type,
            "allocation_target": target, "rule_path": rule_path,
            "schedule_status": schedule_status,
            "manual_travel_tab_match": manual_match,
            "gmail_payment_evidence": row.get("gmail_payment_evidence"),
            "ota_mail_service_period_target": ota_service_period_by_payment.get(
                int(row["payment_id"])
            ),
            "inferred_external_target": inferred_target_by_payment.get(
                int(row["payment_id"])
            ),
            "geographic_context_source_sha256": [
                str(item["source_sha256"]) for item in geographic_context
            ],
            "current_owner_decision": row.get("current_owner_decision"),
            "axis_evidence": axis_evidence,
            "trip_cluster_registry_id": (
                str(registry["registry_id"])
                if (registry := registry_for_target_path(
                    target_path, int(row["payment_id"])
                )) is not None else ""
            ),
        }
        prediction_sha256 = _sha(prediction_core)
        prediction_id = "high-coverage-prediction:" + _sha({
            "direct_event_key": row["direct_event_key"],
            "current_fact_sha256": row["current_fact_sha256"],
            "prediction_sha256": prediction_sha256,
        })
        predictions.append({
            "prediction_id": prediction_id, "model_id": model_id,
            "direct_event_key": str(row["direct_event_key"]),
            "current_evidence_id": str(row["current_evidence_id"]),
            "payment_id": int(row["payment_id"]),
            "feature_sha256": _sha(feature),
            "account": account, "cost_type": cost_type,
            "allocation_target": target, "rule_path": rule_path,
            "confidence": confidence, "confidence_label": confidence_label,
            "schedule_status": schedule_status,
            "conflict_count": 0, "prediction_sha256": prediction_sha256,
            "rationale": rationale,
            "manual_travel_tab_match": manual_match,
            "axis_evidence": axis_evidence,
            "trip_cluster_registry_id": (
                str(registry["registry_id"])
                if (registry := registry_for_target_path(
                    target_path, int(row["payment_id"])
                )) is not None else ""
            ),
        })
    axes_by_payment = _promoted_axis_maps(db, run_id)
    # Rebuilding after projection sees the just-inserted confirmed decisions.
    # Keep admitted structural scopes out of the reversal helper map so the
    # admission cannot silently create new reversal inheritance on replay.
    if admitted_paths:
        admitted_high_payment_ids = {
            int(row[0]) for row in db.execute(
                """SELECT payment_id,rule_path
                   FROM direct_high_coverage_classifier_predictions
                   WHERE run_id=?""",
                (run_id,),
            ).fetchall()
            if _target_path(row[1]) in admitted_paths
        }
        for payment_id in admitted_high_payment_ids:
            axes_by_payment.pop(payment_id, None)
    provisional_axes_by_payment: dict[int, dict[str, str]] = {}
    provisional_predictions_by_payment: dict[int, dict[str, object]] = {}
    for prediction in predictions:
        axes = {
            dimension: str(prediction[dimension])
            for dimension in ACTIVE_DIMENSIONS
        }
        if _decision_status_for_prediction(prediction, admitted_paths) == "confirmed":
            # A newly admitted structural scope is allowed to finalize its
            # own three axes, but it must not silently authorize reversal
            # inheritance in the same run.
            if _target_path(prediction.get("rule_path")) not in admitted_paths:
                axes_by_payment[int(prediction["payment_id"])] = axes
        elif _is_provisional_prediction(prediction, admitted_paths):
            provisional_axes_by_payment[int(prediction["payment_id"])] = axes
            provisional_predictions_by_payment[int(
                prediction["payment_id"]
            )] = prediction
    reversal_inheritance_links: list[dict[str, object]] = []
    reversal_expectations: dict[int, dict[str, object]] = {}
    for row in reversal_candidates:
        account, account_path = _account_prediction_with_external_evidence(row, indexes)
        manual_match = preliminary_manual_matches.get(int(row["payment_id"]))
        context_matches = _geographic_context_matches(
            row, geographic_context,
        )
        target_path = ""
        inheritance_path = ""
        provisional_link: dict[str, object] | None = None
        gmail_evidence = row.get("gmail_payment_evidence")
        if (
            isinstance(gmail_evidence, dict)
            and str(gmail_evidence.get("classification") or "") == "travel"
            and str(row.get("transaction_type") or "") == "purchase"
        ):
            resolved_target = _gmail_schedule_target(gmail_evidence, schedule)
            if resolved_target is None:
                return (
                    TRIP_UNASSIGNED,
                    GMAIL_PAYMENT_SERVICE_PERIOD_PENDING_PATH,
                    "no_match",
                )
            axes = {
                "account": account,
                "cost_type": TRIP_COST,
                "allocation_target": resolved_target,
            }
            target_path = GMAIL_PAYMENT_SERVICE_PERIOD_PATH
            inheritance_path = "gmail_service_period_evidence"
        elif manual_match is not None:
            manual_status = str(manual_match.get("status") or "")
            if manual_status not in {"exact", "target_invariant"}:
                axes = {
                    "account": account,
                    "cost_type": TRIP_COST,
                    "allocation_target": TRIP_UNASSIGNED,
                }
                target_path = "manual_travel_tab_ambiguous"
                inheritance_path = target_path
            elif (
                len(context_matches) == 1
                and str(context_matches[0]["tab"])
                != str(manual_match["target"])
            ):
                axes = {
                    "account": account,
                    "cost_type": TRIP_COST,
                    "allocation_target": TRIP_UNASSIGNED,
                }
                target_path = "manual_geography_conflict"
                inheritance_path = target_path
            else:
                axes = {
                    "account": account,
                    "cost_type": TRIP_COST,
                    "allocation_target": str(manual_match["target"]),
                }
                target_path = (
                    MANUAL_REVERSAL_EXACT_PATH
                    if manual_status == "exact"
                    else MANUAL_REVERSAL_MN_PATH
                )
                inheritance_path = target_path
        else:
            # A provisional original may help us find a relationship, but it
            # is not evidence for the reversal's cost axes.  Keep the
            # provisional helper available for isolated legacy tests, while
            # the production classifier deliberately never emits a link.
            inherited = _inherited_reversal_axes(
                row, relations_by_reversal, group_purchases, axes_by_payment,
            )
            if inherited is not None:
                axes, inheritance_path = inherited
                target_path = "reversal_axis_inherit"
            else:
                gmail_pending = (
                    isinstance(gmail_evidence, dict)
                    and str(gmail_evidence.get("classification") or "")
                    == "travel"
                    and (
                        str(gmail_evidence.get("service_start") or "")
                        or str(gmail_evidence.get("match_method") or "").endswith(
                            "approval_family_source_card_merchant_unverified"
                        )
                    )
                )
                placeholder = placeholder_by_payment.get(int(row["payment_id"]))
                placeholder_path = (
                    str(placeholder.get("classification_path"))
                    if placeholder is not None else ""
                )
                gmail_target_only = (
                    _gmail_schedule_target(gmail_evidence, schedule)
                    if isinstance(gmail_evidence, dict)
                    else None
                )
                if gmail_target_only is not None:
                    axes = {
                        "account": account,
                        "cost_type": TRIP_COST,
                        "allocation_target": gmail_target_only,
                    }
                    target_path = GMAIL_PAYMENT_SERVICE_PERIOD_PATH
                    inheritance_path = (
                        "gmail_service_period_target_only_no_original_relation"
                    )
                elif gmail_pending:
                    axes = {
                        "account": account,
                        "cost_type": TRIP_COST,
                        "allocation_target": TRIP_UNASSIGNED,
                    }
                    target_path = (
                        GMAIL_PAYMENT_APPROVAL_FAMILY_PENDING_PATH
                        if str(gmail_evidence.get("match_method") or "").endswith(
                            "approval_family_source_card_merchant_unverified"
                        )
                        else GMAIL_PAYMENT_SERVICE_PERIOD_PENDING_PATH
                    )
                    inheritance_path = target_path
                elif placeholder is not None and placeholder_path in {
                    ACTIVITY_PLACEHOLDER_PATH,
                    RESERVATION_PLACEHOLDER_PATH,
                }:
                    axes = {
                        "account": account,
                        "cost_type": TRIP_COST,
                        "allocation_target": str(placeholder["target_code"]),
                    }
                    target_path = placeholder_path
                    inheritance_path = "direct_reversal_placeholder"
                else:
                    axes, inheritance_path = _reversal_policy_fallback(
                        row, indexes,
                    )
                    target_path = (
                        "domestic_nontravel_policy"
                        if axes["allocation_target"] == OVERHEAD_TARGET
                        else "reversal_policy_fallback"
                    )
        target = str(axes["allocation_target"])
        cost_type = str(axes["cost_type"])
        if target_path in {
            "manual_travel_tab_exact",
            "manual_travel_tab_mn_target_invariant",
            MANUAL_REVERSAL_EXACT_PATH,
            MANUAL_REVERSAL_MN_PATH,
            REVERSAL_PROVISIONAL_INHERIT_PATH,
            ACTIVITY_PLACEHOLDER_PATH,
            RESERVATION_PLACEHOLDER_PATH,
            GMAIL_PAYMENT_SERVICE_PERIOD_PATH,
        }:
            confidence = (
                0.91 if target_path == "manual_travel_tab_exact" else
                0.96 if target_path == GMAIL_PAYMENT_SERVICE_PERIOD_PATH else
                0.97 if target_path == REVERSAL_PROVISIONAL_INHERIT_PATH else
                0.56 if target_path == ACTIVITY_PLACEHOLDER_PATH else
                0.54
            )
            confidence_label = (
                "수기여행탭-여행대상확정"
                if target_path == "manual_travel_tab_exact" else
                "수기여행탭-M:N대상불변-여행대상확정"
                if target_path == "manual_travel_tab_mn_target_invariant" else
                "수기여행탭-환불원거래확인대기"
                if target_path in {MANUAL_REVERSAL_EXACT_PATH, MANUAL_REVERSAL_MN_PATH} else
                "원거래임시축상속-사용자확인대기"
                if target_path == REVERSAL_PROVISIONAL_INHERIT_PATH else
                "메일복합일치-환불대상-자동임시"
                if target_path == GMAIL_PAYMENT_SERVICE_PERIOD_PATH else
                "해외환불-임시활동-사용자확인대기"
                if target_path == ACTIVITY_PLACEHOLDER_PATH else
                "여행환불-임시예약-사용자확인대기"
            )
            if target_path == "manual_travel_tab_exact":
                rationale = (
                    f"현재 카드의 발급사·이용일·절댓값 금액이 수기 여행 탭 "
                    f"{target}과 1:1로 일치하지만 환불·취소의 원거래 관계는 확인되지 않아 "
                    "환불 대상은 보류함. 수기 행은 카드 거래의 원거래·취소 증거가 아님"
                )
            elif target_path == "manual_travel_tab_mn_target_invariant":
                rationale = (
                    f"취소·환불 행과 수기 여행 탭의 M:N 후보가 모두 같은 여행 탭 "
                    f"{target}을 가리키지만 환불·취소의 원거래 관계는 확인되지 않아 "
                    "환불 대상은 보류함. 개별 원거래·취소 행의 1:1 관계와 수기행의 "
                    "거래증거성은 주장하지 않음"
                )
            elif target_path in {MANUAL_REVERSAL_EXACT_PATH, MANUAL_REVERSAL_MN_PATH}:
                rationale = (
                    "수기 여행 탭은 환불·취소의 여행 대상 힌트로만 사용했으나, "
                    "원거래와의 정확한 관계가 확인되지 않아 환불 비용축은 임시 보류함"
                )
            elif target_path == REVERSAL_PROVISIONAL_INHERIT_PATH:
                rationale = (
                    "환불·취소가 현재 카드의 정확히 하나인 원거래 관계를 가리키고, "
                    "원거래의 임시 여행대상을 상속해 제안함. 환불일은 행사일이 아니며 "
                    "별도 상속 연결표로만 기록하고 사용자 확인 전 배부·전기하지 않음"
                )
            elif target_path == GMAIL_PAYMENT_SERVICE_PERIOD_PATH:
                evidence = row.get("gmail_payment_evidence") or {}
                rationale = (
                    "취소 원장과 Gmail의 예약·무료취소·환불 금액을 발급원천·이용일·"
                    "가맹점으로 복합 확인해 행사 대상만 임시 제안함. "
                    f"행사기간 {evidence.get('service_start', '')}~"
                    f"{evidence.get('service_end', '')}, 대상 {target}. "
                    "원거래 1:1 연결을 새로 만들지 않으며 사용자 확정 전 최종 전기하지 않음"
                )
            elif target_path == ACTIVITY_PLACEHOLDER_PATH:
                rationale = (
                    "원거래 연결은 없지만 현재 카드의 해외 현장 사용 환불·취소가 "
                    "확인되어 임시활동 대상으로 묶음. 결제창은 행사기간이 아니며 "
                    "사용자 확인 전 배부·전기하지 않음"
                )
            else:
                rationale = (
                    "원거래 연결은 없지만 현재 카드 가맹점이 OTA·항공·여행상품으로 "
                    "확인되어 임시예약 환불 대상으로 제안함. 결제일을 행사일로 쓰지 "
                    "않으며 사용자 확인 전 배부·전기하지 않음"
                )
        elif target_path == "manual_travel_tab_ambiguous":
            confidence = 0.50
            confidence_label = "수기여행탭-중복확인대기"
            rationale = (
                "현재 카드의 발급사·이용일·절댓값 금액에 대응하는 수기 여행 탭이 "
                "여러 개이거나 현재 카드행이 여러 개라 여행명을 선택하지 않음"
            )
        elif target_path == "manual_geography_conflict":
            confidence = 0.50
            confidence_label = "수기탭-대만맥락충돌-확인대기"
            rationale = (
                "수기 여행 탭과 현재 카드 대만 맥락이 서로 다른 여행을 가리켜 "
                "여행명을 선택하지 않음"
            )
        elif target_path == "reversal_axis_inherit":
            confidence = (
                0.99 if inheritance_path.endswith(":unique_original") else 0.97
            )
            confidence_label = "원거래축상속"
            rationale = (
                "취소·환불은 결제일을 행사일로 다시 판단하지 않고, 검증된 확정 원거래의 "
                "비용축(account·cost_type·allocation_target)을 상속"
            )
        else:
            confidence = 0.58
            confidence_label = "정책자동-원거래연결없음"
            rationale = (
                "원거래 연결이 없지만 현재 카드의 가맹점·국내외 정책으로 "
                "환급의 비용축을 자동 분류하고, 행사일은 결제일로 추정하지 않음"
            )
        rule_path = f"{account_path}|{target_path}|cost:{'overhead' if cost_type == OVERHEAD_COST else 'travel'}"
        schedule_status = "not_applicable"
        target_evidence_source = (
            "manual_travel_tab_target_only"
            if target_path in {
                "manual_travel_tab_exact",
                "manual_travel_tab_mn_target_invariant",
                MANUAL_REVERSAL_EXACT_PATH,
                MANUAL_REVERSAL_MN_PATH,
            }
            else target_path
        )
        target_registry = (
            registry_manifest(placeholder_by_payment[int(row["payment_id"])]
            )
            if target_path in REGISTRY_BACKED_TARGET_PATHS
            and int(row["payment_id"]) in placeholder_by_payment
            else None
        )
        axis_evidence = _axis_evidence(
            row,
            account=account,
            cost_type=cost_type,
            target=target,
            account_path=account_path,
            target_path=target_path,
            target_evidence_source=target_evidence_source,
            manual_match=manual_match,
            geographic_context=geographic_context,
            target_registry=target_registry,
            gmail_evidence=row.get("gmail_payment_evidence"),
            owner_decision=row.get("current_owner_decision"),
            reversal_inheritance=inheritance_path,
            admitted_rule_paths=admitted_paths,
        )
        reversal_expectations[int(row["payment_id"])] = {
            "target": target,
            "target_path": target_path,
            "schedule_status": schedule_status,
            "manual_match": manual_match,
            "provisional_link": provisional_link,
        }
        feature = {
            "source": row["source"], "merchant": _norm(row["merchant"]),
            "biz": _norm(row["biz"]), "currency": _norm(row["currency"]),
            "card4": _norm(row["card4"]), "occurred_on": row["occurred_on"],
            "posted_on": row["posted_on"], "target": target,
            "reversal_relation": inheritance_path,
            "manual_travel_tab_match": manual_match,
            "reversal_inheritance": provisional_link,
            "axis_evidence": axis_evidence,
            "placeholder_registry": (
                registry_manifest(placeholder_by_payment[int(row["payment_id"])])
                if target_path in REGISTRY_BACKED_TARGET_PATHS
                and int(row["payment_id"]) in placeholder_by_payment
                else None
            ),
        }
        prediction_core = {
            "model_contract": MODEL_CONTRACT,
            "model_sha256": model_sha256,
            "direct_event_key": row["direct_event_key"],
            "current_fact_sha256": row["current_fact_sha256"],
            "account": account, "cost_type": cost_type,
            "allocation_target": target, "rule_path": rule_path,
            "schedule_status": schedule_status,
            "manual_travel_tab_match": manual_match,
            "reversal_inheritance": provisional_link,
            "axis_evidence": axis_evidence,
        }
        prediction_sha256 = _sha(prediction_core)
        prediction_id = "high-coverage-prediction:" + _sha({
            "direct_event_key": row["direct_event_key"],
            "current_fact_sha256": row["current_fact_sha256"],
            "prediction_sha256": prediction_sha256,
        })
        predictions.append({
            "prediction_id": prediction_id, "model_id": model_id,
            "direct_event_key": str(row["direct_event_key"]),
            "current_evidence_id": str(row["current_evidence_id"]),
            "payment_id": int(row["payment_id"]),
            "feature_sha256": _sha(feature),
            "account": account, "cost_type": cost_type,
            "allocation_target": target, "rule_path": rule_path,
            "confidence": confidence, "confidence_label": confidence_label,
            "schedule_status": schedule_status,
            "conflict_count": 0, "prediction_sha256": prediction_sha256,
            "axis_evidence": axis_evidence,
            "rationale": rationale,
            "manual_travel_tab_match": manual_match,
            "trip_cluster_registry_id": (
                str(placeholder_by_payment[int(row["payment_id"])]["registry_id"])
                if target_path in REGISTRY_BACKED_TARGET_PATHS
                and int(row["payment_id"]) in placeholder_by_payment
                else ""
            ),
        })
        if provisional_link is not None:
            link_core = {
                "run_id": run_id,
                "reversal_payment_id": int(row["payment_id"]),
                "reversal_direct_event_key": str(row["direct_event_key"]),
                "reversal_current_evidence_id": str(row["current_evidence_id"]),
                **provisional_link,
            }
            reversal_inheritance_links.append({
                **link_core,
                "link_sha256": _sha(link_core),
                "reversal_prediction_id": prediction_id,
                "inheritance_status": "provisional",
            })
    candidates = [*purchase_candidates, *reversal_candidates]
    candidates.sort(key=lambda row: str(row["direct_event_key"]))
    predictions.sort(key=lambda row: str(row["direct_event_key"]))
    withheld.sort(key=lambda row: str(row["direct_event_key"]))
    current_by_event = {
        str(row["direct_event_key"]): row for row in current
    }
    target_path_merchant_counter: Counter[tuple[str, str]] = Counter()
    for prediction in predictions:
        if prediction["allocation_target"] == TRIP_UNASSIGNED:
            current_row = current_by_event.get(str(prediction["direct_event_key"]))
            if current_row is not None:
                target_path_merchant_counter[
                    _target_path(prediction["rule_path"]),
                    _norm(current_row.get("merchant")),
                ] += 1
    target_path_merchant_counts = [
        {
            "target_path": path,
            "merchant": merchant,
            "count": count,
        }
        for (path, merchant), count in sorted(
            target_path_merchant_counter.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
    ]
    validation_checks = [
        "all promoted rows have three nonempty active axes",
        "prepaid travel rows use 여행_미배정 unless a one-to-one manual target or a validated reservation placeholder supplies a needs_review target",
        "2025 and 2026 dates are matched against the same month/day template",
        "Taiwan target requires a current-card Taiwan marker and exact 2026 context window and remains needs_review",
        "manual travel-tab targets use the travel tab only for allocation_target; amount components may ignore service-date differences, and sign is classification-only",
        "ambiguous manual travel tabs never fall back to geographic context",
        "manual rows and geographic context are classification-only, not transaction evidence",
        "card-specific region clusters require three purchases, two dates, two merchants, and a bounded seven-day span",
        "strict trip-clusters may confirm only when they resolve to one canonical schedule; new registry targets and placeholders stay provisional",
        "provisional travel targets have no allocation plan or cost allocation",
        "domestic ordinary rows use overhead target and cost type",
        "explicit owner decisions are exact-match, single-use, and scope-audited",
        "verified Gmail service periods require one canonical schedule target",
        "OTA mail service periods require exact card amount, provider compatibility, and one canonical schedule target",
        "OTA M:N components require equal cardinality and common target without row pairing",
        "2026 non-OTA foreign physical use may use the card use date only when one canonical schedule target remains",
        "provisional original targets are never inherited by a reversal; only confirmed evidence may supply reversal axes",
        "unlinked reversals use merchant policy without a reversal date as service date",
    ]
    validation_error_count = 0
    validation_error_samples: list[dict[str, object]] = []
    for prediction in predictions:
        if any(not str(prediction[field]).strip() for field in (
            "account", "cost_type", "allocation_target",
        )):
            validation_error_count += 1
            if len(validation_error_samples) < 10:
                validation_error_samples.append({
                    "kind": "empty_axis",
                    "event": prediction["direct_event_key"],
                    "path": prediction["rule_path"],
                })
        current_row = current_by_event.get(str(prediction["direct_event_key"]))
        if (
            current_row is not None
            and current_row["transaction_type"] == "purchase"
            and (
                _domestic_travel_product(current_row)
                or _payment_gateway(current_row)
            )
            and not _explicit_domestic_nontravel(current_row)
            and not (
                isinstance(current_row.get("gmail_payment_evidence"), dict)
                and str(current_row["gmail_payment_evidence"].get("classification") or "")
                == "overhead"
            )
            and not isinstance(current_row.get("current_owner_decision"), dict)
            and _target_path(prediction["rule_path"])
            != "domestic_gateway_nontravel_policy"
            and _target_path(prediction["rule_path"])
            != GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH
            and _target_path(prediction["rule_path"])
            not in CONFIRMED_TRAVEL_TARGET_PATHS
            and _target_path(prediction["rule_path"]) not in admitted_paths
            and not _is_review_prediction(prediction, admitted_paths)
            and (
                prediction["allocation_target"] != TRIP_UNASSIGNED
                or prediction["schedule_status"] != "not_applicable"
            )
        ):
            validation_error_count += 1
            if len(validation_error_samples) < 10:
                validation_error_samples.append({
                    "kind": "gateway_policy",
                    "event": prediction["direct_event_key"],
                    "target": prediction["allocation_target"],
                    "path": prediction["rule_path"],
                    "status": prediction["schedule_status"],
                })
        if current_row is not None and str(
            current_row["transaction_type"]
        ) in REVERSAL_TYPES:
            expected_reversal = reversal_expectations.get(
                int(current_row["payment_id"])
            )
            if expected_reversal is None:
                validation_error_count += 1
                continue
            expected_target = str(expected_reversal["target"])
            expected_path = str(expected_reversal["target_path"])
            expected_status = str(expected_reversal["schedule_status"])
            if (
                prediction["allocation_target"] != expected_target
                or str(prediction["rule_path"]).split("|", 1)[1].split("|", 1)[0]
                != expected_path
                or prediction["schedule_status"] != expected_status
            ):
                validation_error_count += 1
                if len(validation_error_samples) < 10:
                    validation_error_samples.append({
                        "kind": "reversal",
                        "event": prediction["direct_event_key"],
                        "actual": {
                            "target": prediction["allocation_target"],
                            "path": prediction["rule_path"],
                            "status": prediction["schedule_status"],
                        },
                        "expected": expected_reversal,
                    })
            continue
        if current_row is not None:
            manual_match = preliminary_manual_matches.get(
                int(current_row["payment_id"])
            )
            context_matches = _geographic_context_matches(
                current_row, geographic_context,
            )
            inferred_target = inferred_target_by_payment.get(
                int(current_row["payment_id"]),
            )
            if isinstance(current_row.get("current_owner_decision"), dict):
                owner_decision = current_row["current_owner_decision"]
                expected_target = str(owner_decision["allocation_target"])
                expected_path = OWNER_DECISION_CURRENT_SCOPE_PATH
                expected_status = "not_applicable"
            elif (
                isinstance(current_row.get("gmail_payment_evidence"), dict)
                and str(current_row["gmail_payment_evidence"].get("classification") or "")
                == "overhead"
            ):
                expected_target = OVERHEAD_TARGET
                expected_path = GMAIL_PAYMENT_OVERHEAD_EVIDENCE_PATH
                expected_status = "not_applicable"
            elif isinstance(inferred_target, dict):
                expected_target = str(inferred_target.get("target_code") or "")
                expected_path = INFERRED_EXTERNAL_TARGET_PATH
                expected_status = "unique_match"
            elif (
                isinstance(current_row.get("gmail_payment_evidence"), dict)
                and str(current_row["gmail_payment_evidence"].get("classification") or "")
                == "travel"
                and (
                    str(current_row["gmail_payment_evidence"].get("service_start") or "")
                    or str(current_row["gmail_payment_evidence"].get("match_method") or "").endswith(
                        "approval_family_source_card_merchant_unverified"
                    )
                )
            ):
                gmail = current_row["gmail_payment_evidence"]
                gmail_target = (
                    _gmail_schedule_target(gmail, schedule)
                    if str(current_row.get("transaction_type") or "") == "purchase"
                    else None
                )
                family_pending = str(gmail.get("match_method") or "").endswith(
                    "approval_family_source_card_merchant_unverified"
                )
                expected_target = TRIP_UNASSIGNED
                expected_path = (
                    GMAIL_PAYMENT_APPROVAL_FAMILY_PENDING_PATH
                    if family_pending
                    else GMAIL_PAYMENT_SERVICE_PERIOD_PENDING_PATH
                    if str(gmail.get("service_start") or "")
                    else GMAIL_PAYMENT_TRAVEL_EVIDENCE_PATH
                )
                expected_status = (
                    "ambiguous_match" if family_pending
                    else "no_match" if str(gmail.get("service_start") or "")
                    else "not_applicable"
                )
                if gmail_target is not None and not family_pending:
                    expected_target = gmail_target
                    expected_path = (
                        GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH
                        if _verified_gmail_schedule_target(gmail, schedule) is not None
                        else GMAIL_PAYMENT_SERVICE_PERIOD_PATH
                    )
                    expected_status = "unique_match"
            elif manual_match is not None:
                manual_status = str(manual_match.get("status") or "")
                if manual_status not in {
                    "exact", "target_invariant",
                    "amount_component_exact",
                    "amount_component_target_invariant",
                }:
                    manual_target_codes = {
                        str(item.get("manual_tab") or "")
                        for item in manual_match.get("matches", [])
                        if isinstance(item, dict)
                        and str(item.get("manual_tab") or "")
                    }
                    ota_target = ota_service_period_by_payment.get(
                        int(current_row["payment_id"])
                    )
                    ota_usable = (
                        isinstance(ota_target, dict)
                        and str(ota_target.get("target_code") or "")
                        and (
                            not manual_target_codes
                            or str(ota_target.get("target_code") or "")
                            in manual_target_codes
                        )
                    )
                    if ota_usable:
                        expected_target = str(ota_target["target_code"])
                        expected_path = _ota_service_period_target_path(
                            ota_target.get("match_kind")
                        )
                        expected_status = "unique_match"
                    else:
                        direct_target_exact = _direct_foreign_use_date_target(
                            current_row, schedule, allow_generic_foreign=True,
                        )
                        if (
                            direct_target_exact is not None
                            and (
                                not manual_target_codes
                                or direct_target_exact in manual_target_codes
                            )
                        ):
                            expected_target = direct_target_exact
                            expected_path = FOREIGN_USE_DATE_SCHEDULE_EXACT_PATH
                            expected_status = "unique_match"
                        else:
                            direct_target = _direct_foreign_use_date_target(
                                current_row, schedule,
                            )
                            if direct_target is not None:
                                expected_target = direct_target
                                expected_path = FOREIGN_USE_DATE_SCHEDULE_PATH
                                expected_status = "unique_match"
                            else:
                                expected_target = TRIP_UNASSIGNED
                                expected_path = "manual_travel_tab_ambiguous"
                                expected_status = "ambiguous_match"
                elif (
                    len(context_matches) == 1
                    and str(context_matches[0]["tab"])
                    != str(manual_match["target"])
                ):
                    expected_target = TRIP_UNASSIGNED
                    expected_path = "manual_geography_conflict"
                    expected_status = "ambiguous_match"
                else:
                    expected_target = str(manual_match["target"])
                    expected_path = {
                        "exact": "manual_travel_tab_exact",
                        "target_invariant": "manual_travel_tab_mn_target_invariant",
                        "amount_component_exact": MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
                        "amount_component_target_invariant": MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH,
                    }[manual_status]
                    expected_status = "unique_match"
            elif (
                current_row["transaction_type"] == "purchase"
                and _direct_foreign_use_date_target(
                    current_row, schedule, allow_generic_foreign=True,
                ) is not None
            ):
                expected_target = str(_direct_foreign_use_date_target(
                    current_row, schedule, allow_generic_foreign=True,
                ))
                expected_path = FOREIGN_USE_DATE_SCHEDULE_EXACT_PATH
                expected_status = "unique_match"
            elif (
                current_row["transaction_type"] == "purchase"
                and int(current_row["payment_id"]) in ota_service_period_by_payment
            ):
                ota_target = ota_service_period_by_payment[int(
                    current_row["payment_id"]
                )]
                expected_target = str(ota_target["target_code"])
                expected_path = _ota_service_period_target_path(
                    ota_target.get("match_kind")
                )
                expected_status = "unique_match"
            elif (
                current_row["transaction_type"] == "purchase"
                and int(current_row["payment_id"]) in trip_cluster_by_payment
            ):
                cluster = trip_cluster_by_payment[int(current_row["payment_id"])]
                expected_target = str(cluster["target_code"])
                expected_path = REGISTRY_PATH
                expected_status = "unique_match"
            elif (
                current_row["transaction_type"] == "purchase"
                and int(current_row["payment_id"]) in placeholder_by_payment
            ):
                placeholder = placeholder_by_payment[int(
                    current_row["payment_id"]
                )]
                expected_target = str(placeholder["target_code"])
                expected_path = str(placeholder["classification_path"])
                expected_status = str(
                    placeholder.get("schedule_status") or "not_applicable"
                )
            elif (
                isinstance(current_row.get("gmail_payment_evidence"), dict)
                and str(current_row["gmail_payment_evidence"].get("classification") or "")
                == "overhead"
            ):
                expected_target = OVERHEAD_TARGET
                expected_path = GMAIL_PAYMENT_OVERHEAD_EVIDENCE_PATH
                expected_status = "not_applicable"
            elif (
                isinstance(current_row.get("gmail_payment_evidence"), dict)
                and str(current_row["gmail_payment_evidence"].get("classification") or "")
                == "travel"
            ):
                gmail = current_row["gmail_payment_evidence"]
                gmail_target = (
                    _gmail_schedule_target(gmail, schedule)
                    if str(current_row.get("transaction_type") or "") == "purchase"
                    else None
                )
                family_pending = str(gmail.get("match_method") or "").endswith(
                    "approval_family_source_card_merchant_unverified"
                )
                expected_target = TRIP_UNASSIGNED
                expected_path = (
                    GMAIL_PAYMENT_APPROVAL_FAMILY_PENDING_PATH
                    if family_pending
                    else GMAIL_PAYMENT_SERVICE_PERIOD_PENDING_PATH
                    if str(gmail.get("service_start") or "")
                    else GMAIL_PAYMENT_TRAVEL_EVIDENCE_PATH
                )
                expected_status = (
                    "ambiguous_match" if family_pending
                    else "no_match" if str(gmail.get("service_start") or "")
                    else "not_applicable"
                )
                if gmail_target is not None and not family_pending:
                    expected_target = gmail_target
                    expected_path = (
                        GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH
                        if _verified_gmail_schedule_target(gmail, schedule) is not None
                        else GMAIL_PAYMENT_SERVICE_PERIOD_PATH
                    )
                    expected_status = "unique_match"
            elif is_taiwan_marker(
                f"{current_row.get('merchant') or ''} {current_row.get('biz') or ''}"
            ):
                expected_target = (
                    str(context_matches[0]["tab"])
                    if len(context_matches) == 1 else TRIP_UNASSIGNED
                )
                expected_path = (
                    "current_card_geography_context_exact_2026"
                    if len(context_matches) == 1
                    else "geographic_context_period_missing"
                )
                expected_status = (
                    "unique_match" if len(context_matches) == 1
                    else "not_applicable"
                )
            elif (
                current_row["transaction_type"] == "purchase"
                and str(current_row.get("sub") or "") == "해외"
                and _direct_foreign_use_date_target(
                    current_row,
                    schedule,
                    allow_known_foreign_gateway=True,
                ) is not None
            ):
                expected_target = str(_direct_foreign_use_date_target(
                    current_row,
                    schedule,
                    allow_known_foreign_gateway=True,
                ))
                expected_path = FOREIGN_USE_DATE_SCHEDULE_PATH
                expected_status = "unique_match"
            elif (
                current_row["transaction_type"] == "purchase"
                and str(current_row.get("sub") or "") == "해외"
            ):
                expected_target = TRIP_UNASSIGNED
                expected_path = FOREIGN_SERVICE_PERIOD_PENDING_PATH
                expected_status = "no_match"
            else:
                continue
            if (
                prediction["allocation_target"] != expected_target
                or str(prediction["rule_path"]).split("|", 1)[1].split("|", 1)[0]
                != expected_path
                or prediction["schedule_status"]
                != expected_status
            ):
                validation_error_count += 1
                if len(validation_error_samples) < 10:
                    validation_error_samples.append({
                        "kind": "target_path",
                        "event": prediction["direct_event_key"],
                        "actual": {
                            "target": prediction["allocation_target"],
                            "path": prediction["rule_path"],
                            "status": prediction["schedule_status"],
                        },
                        "expected": {
                            "target": expected_target,
                            "path": expected_path,
                            "status": expected_status,
                        },
                    })
    if reversal_inheritance_links:
        validation_error_count += 1
        if len(validation_error_samples) < 10:
            validation_error_samples.append({
                "kind": "provisional_reversal_inheritance_forbidden",
                "count": len(reversal_inheritance_links),
            })
    if validation_error_count:
        raise ValueError(
            "high_classifier_internal_validation_failed:"
            + json.dumps(validation_error_samples, ensure_ascii=False, sort_keys=True)
        )
    manual_match_links = sorted(
        [
            {
                "prediction_id": prediction["prediction_id"],
                "direct_event_key": prediction["direct_event_key"],
                "prediction_sha256": prediction["prediction_sha256"],
                "manual_travel_tab_match": prediction["manual_travel_tab_match"],
            }
            for prediction in predictions
            if prediction.get("manual_travel_tab_match") is not None
        ],
        key=lambda item: str(item["prediction_id"]),
    )
    manual_match_links_sha256 = _sha(manual_match_links)
    reversal_inheritance_links.sort(
        key=lambda item: str(item["reversal_direct_event_key"])
    )
    reversal_inheritance_links_sha256 = _sha(reversal_inheritance_links)
    candidate_set_sha256 = _sha([
        {
            "direct_event_key": row["direct_event_key"],
            "current_fact_sha256": row["current_fact_sha256"],
        }
        for row in candidates
    ])
    prediction_set_sha256 = _sha([
        {
            key: row[key] for key in (
                "prediction_id", "direct_event_key", "feature_sha256",
                "account", "cost_type", "allocation_target",
                "rule_path", "prediction_sha256",
            )
        }
        for row in predictions
    ])
    run_state_core = {
        "training_source_sha256": TRAINING_SOURCE_SHA256,
        "candidate_set_sha256": candidate_set_sha256,
        "prediction_set_sha256": prediction_set_sha256,
        "withheld_set_sha256": _sha(withheld),
        "manual_source_manifest_sha256": manual_source_manifest_sha256,
        "manual_match_links_sha256": manual_match_links_sha256,
        "geographic_context_source_sha256": [
            str(item["source_sha256"]) for item in geographic_context
        ],
        "manual_match_links": manual_match_links,
        "manual_match_links_sha256": manual_match_links_sha256,
        "reversal_inheritance_links": reversal_inheritance_links,
        "reversal_inheritance_links_sha256": reversal_inheritance_links_sha256,
        "trip_registry_set_sha256": _sha([
            registry_manifest(row)
            for row in all_trip_registries
        ]),
    }
    run_state_sha256 = _sha(run_state_core)
    payload = {
        **algorithm, "model_sha256": model_sha256,
        "candidate_set_sha256": candidate_set_sha256,
        "prediction_set_sha256": prediction_set_sha256,
        "run_state_sha256": run_state_sha256,
        "manual_source_manifest_sha256": manual_source_manifest_sha256,
        "manual_match_links": manual_match_links,
        "manual_match_links_sha256": manual_match_links_sha256,
        "reversal_inheritance_links": reversal_inheritance_links,
        "reversal_inheritance_links_sha256": reversal_inheritance_links_sha256,
        "geographic_context_source_sha256": [
            str(item["source_sha256"]) for item in geographic_context
        ],
        "training_row_count": len(training), "candidate_count": len(candidates),
        "promoted_count": len(predictions), "withheld_count": len(withheld),
        "validation_checks": validation_checks,
        "validation_count": len(validation_checks),
        "validation_error_count": validation_error_count,
        "predicted_target_counts": _counts(predictions, "allocation_target"),
        "predicted_cost_type_counts": _counts(predictions, "cost_type"),
        "predicted_account_counts": _counts(predictions, "account"),
        "training_manual_or_historical_transaction_evidence_used": False,
        "manual_travel_tab_classification_evidence_used": bool(manual_match_links),
        "target_path_merchant_counts": target_path_merchant_counts,
    }
    model = {
        "model_id": model_id, "model_contract": MODEL_CONTRACT,
        "model_sha256": model_sha256, "run_state_sha256": run_state_sha256,
        "training_source_sha256": TRAINING_SOURCE_SHA256,
        "candidate_set_sha256": candidate_set_sha256,
        "prediction_set_sha256": prediction_set_sha256,
        "training_row_count": len(training), "candidate_count": len(candidates),
        "promoted_count": len(predictions),
        "validation_count": len(validation_checks),
        "validation_error_count": validation_error_count,
        "training_role": TRAINING_ROLE,
        "payload_json": _canonical(payload).decode("utf-8"),
    }
    return {
        "model": model, "predictions": predictions, "withheld": withheld,
        "candidate_count": len(candidates), "promoted_count": len(predictions),
        "validation_count": len(validation_checks),
        "validation_error_count": validation_error_count,
        "target_counts": _counts(predictions, "allocation_target"),
        "target_path_counts": dict(sorted(
            Counter(_target_path(row["rule_path"]) for row in predictions).items()
        )),
        "manual_match_links": manual_match_links,
        "manual_source_manifest": manual_manifest,
        "manual_match_links_sha256": manual_match_links_sha256,
        "reversal_inheritance_links": reversal_inheritance_links,
        "reversal_inheritance_links_sha256": reversal_inheritance_links_sha256,
        "target_path_merchant_counts": target_path_merchant_counts,
        "trip_registries": all_trip_registries,
        "inferred_target_by_payment": inferred_target_by_payment,
    }


def _counts(rows: Iterable[dict[str, object]], field: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row[field])] += 1
    return dict(sorted(counts.items()))


def project_high_coverage_classifier(
    db: sqlite3.Connection,
    run_id: str,
    admitted_rule_paths: Iterable[str] = (),
) -> dict[str, object]:
    admitted_paths = normalize_admitted_rule_paths(admitted_rule_paths)
    if db.execute(
        "SELECT COUNT(*) FROM direct_high_coverage_classifier_models WHERE run_id=?",
        (run_id,),
    ).fetchone()[0]:
        raise ValueError("high_classifier_already_projected")
    expected = _build_expected(db, run_id, admitted_paths)
    model = expected["model"]
    assert isinstance(model, dict)
    if not expected["predictions"]:
        raise ValueError("high_classifier_no_promotions")
    db.execute("SAVEPOINT high_coverage_classifier")
    try:
        db.execute(
            """INSERT INTO direct_high_coverage_classifier_models(
                 run_id,model_id,model_contract,model_sha256,run_state_sha256,
                 training_source_sha256,candidate_set_sha256,prediction_set_sha256,
                 training_row_count,candidate_count,promoted_count,
                 validation_count,validation_error_count,training_role,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, model["model_id"], model["model_contract"],
                model["model_sha256"], model["run_state_sha256"],
                model["training_source_sha256"], model["candidate_set_sha256"],
                model["prediction_set_sha256"], model["training_row_count"],
                model["candidate_count"], model["promoted_count"],
                model["validation_count"], model["validation_error_count"],
                model["training_role"], model["payload_json"],
            ),
        )
        for registry in expected["trip_registries"]:
            event_keys = sorted(
                str(row["direct_event_key"]) for row in registry["members"]
            )
            fact_shas = sorted(
                str(row["current_fact_sha256"]) for row in registry["members"]
            )
            db.execute(
                """INSERT INTO direct_high_coverage_trip_registries(
                     run_id,registry_id,registry_version,rule_id,registry_sha256,
                     target_code,target_kind,source_system,card_identity_sha256,
                     country,region,starts_on,ends_on,event_set_sha256,
                     fact_set_sha256,registry_status,payload_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'provisional',?)""",
                (
                    run_id, registry["registry_id"], registry["registry_version"],
                    registry["rule_id"], registry["registry_sha256"],
                    registry["target_code"], registry["target_kind"],
                    registry["source_system"], registry["card_identity_sha256"],
                    registry["country"], registry["region"],
                    registry["starts_on"], registry["ends_on"],
                    _sha(event_keys), _sha(fact_shas), registry["payload_json"],
                ),
            )
            for member in registry["members"]:
                db.execute(
                    """INSERT INTO direct_high_coverage_trip_registry_members(
                         run_id,registry_id,payment_id,direct_event_key,
                         current_evidence_id,current_fact_sha256)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        run_id, registry["registry_id"], member["payment_id"],
                        member["direct_event_key"], member["current_evidence_id"],
                        member["current_fact_sha256"],
                    ),
                )
        for withheld in expected["withheld"]:
            db.execute(
                """INSERT INTO direct_high_coverage_classifier_withheld(
                     run_id,direct_event_key,current_evidence_id,reason_code,
                     detail_sha256) VALUES (?,?,?,?,?)""",
                (
                    run_id, withheld["direct_event_key"],
                    withheld["current_evidence_id"], withheld["reason_code"],
                    withheld["detail_sha256"],
                ),
            )
        for prediction in expected["predictions"]:
            db.execute(
                """INSERT INTO direct_high_coverage_classifier_predictions(
                     run_id,prediction_id,model_id,direct_event_key,
                     current_evidence_id,payment_id,feature_sha256,account,
                     cost_type,allocation_target,rule_path,confidence,
                     confidence_label,schedule_status,conflict_count,
                     prediction_sha256,axis_evidence_json,rationale)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, prediction["prediction_id"], prediction["model_id"],
                    prediction["direct_event_key"], prediction["current_evidence_id"],
                    prediction["payment_id"], prediction["feature_sha256"],
                    prediction["account"], prediction["cost_type"],
                    prediction["allocation_target"], prediction["rule_path"],
                    prediction["confidence"], prediction["confidence_label"],
                    prediction["schedule_status"], prediction["conflict_count"],
                    prediction["prediction_sha256"],
                    _canonical(prediction["axis_evidence"]).decode("utf-8"),
                    prediction["rationale"],
                ),
            )
            for dimension in ACTIVE_DIMENSIONS:
                value = str(prediction[{
                    "account": "account", "cost_type": "cost_type",
                    "allocation_target": "allocation_target",
                }[dimension]])
                derivation_id = "high-coverage-derivation:" + _sha({
                    "prediction_id": prediction["prediction_id"],
                    "dimension": dimension, "value": value,
                })
                decision_id = int(db.execute(
                    """INSERT INTO classification_decisions(
                         target_type,target_id,dimension,value,confidence,
                         confidence_label,decision_status,rule_id,rationale)
                       VALUES ('payment',?,?,?,?,?,?,?,?)""",
                    (
                        prediction["payment_id"], dimension, value,
                        prediction["confidence"], prediction["confidence_label"],
                        _decision_status_for_prediction(prediction, admitted_paths),
                        RULE_ID, prediction["rationale"],
                    ),
                ).lastrowid)
                db.execute(
                    """INSERT INTO direct_high_coverage_classifier_axis_derivations(
                         derivation_id,run_id,model_id,prediction_id,payment_id,
                         direct_event_key,dimension,value,rule_id,current_evidence_id,
                         derivation_status,conflict_count)
                       VALUES (?,?,?,?,?,?,?,?,?,?, 'pass',0)""",
                    (
                        derivation_id, run_id, prediction["model_id"],
                        prediction["prediction_id"], prediction["payment_id"],
                        prediction["direct_event_key"], dimension, value,
                        RULE_ID, prediction["current_evidence_id"],
                    ),
                )
                db.execute(
                    """INSERT INTO direct_high_coverage_classifier_decision_bindings(
                         run_id,decision_id,derivation_id) VALUES (?,?,?)""",
                    (run_id, decision_id, derivation_id),
                )
        for link in expected["reversal_inheritance_links"]:
            db.execute(
                """INSERT INTO direct_high_coverage_reversal_inheritance(
                     run_id,reversal_payment_id,reversal_direct_event_key,
                     original_payment_id,original_prediction_id,relation_id,
                     relation_match_method,relation_reference_value,
                     original_target,original_prediction_sha256,link_sha256,
                     inheritance_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, link["reversal_payment_id"],
                    link["reversal_direct_event_key"],
                    link["original_payment_id"], link["original_prediction_id"],
                    link["relation_id"], link["relation_match_method"],
                    link["relation_reference_value"], link["original_target"],
                    link["original_prediction_sha256"], link["link_sha256"],
                    link["inheritance_status"] if "inheritance_status" in link
                    else "provisional",
                ),
            )
    except Exception:
        db.execute("ROLLBACK TO high_coverage_classifier")
        db.execute("RELEASE high_coverage_classifier")
        raise
    else:
        db.execute("RELEASE high_coverage_classifier")
    return {
        "model_id": model["model_id"],
        "candidate_count": model["candidate_count"],
        "promoted_payment_count": model["promoted_count"],
        "decision_count": int(model["promoted_count"]) * len(ACTIVE_DIMENSIONS),
        "withheld_payment_count": len(expected["withheld"]),
        "validation_count": model["validation_count"],
        "validation_error_count": model["validation_error_count"],
        "target_counts": expected["target_counts"],
        "target_path_counts": expected["target_path_counts"],
        "target_path_merchant_counts": expected["target_path_merchant_counts"],
        "trip_registry_count": len(expected["trip_registries"]),
        "manual_travel_tab_classification_evidence_used": bool(
            expected.get("manual_match_links")
        ),
        "manual_match_links_sha256": expected.get("manual_match_links_sha256"),
        "manual_or_historical_transaction_evidence_used": False,
        "structural_rule_admission": admission_manifest(admitted_paths),
    }


def project_high_coverage_provisional_reviews(
    db: sqlite3.Connection,
    run_id: str,
    admitted_rule_paths: Iterable[str] = (),
) -> dict[str, int]:
    """Record owner-review cases without creating a posting or allocation.

    This is deliberately separate from the confirmed promotion view.  A
    provisional target remains review-only unless its path is explicitly
    admitted by the run-scoped structural-rule package.  An admitted path
    gets a terminal classification record only; it still cannot feed a plan,
    a cost allocation, posting, or reversal-axis inheritance.
    """
    admitted_paths = normalize_admitted_rule_paths(admitted_rule_paths)
    rows = db.execute(
        """SELECT p.prediction_id,p.payment_id,p.rule_path,p.allocation_target,
                  p.rationale,pt.transaction_type,p.axis_evidence_json
           FROM direct_high_coverage_classifier_predictions p
           JOIN payment_transactions pt ON pt.id=p.payment_id
           WHERE p.run_id=? ORDER BY p.prediction_id""",
        (run_id,),
    ).fetchall()
    decisions_by_prediction: dict[str, list[tuple[object, ...]]] = defaultdict(list)
    for decision_row in db.execute(
        """SELECT x.prediction_id,d.id,d.dimension,d.value,
                  d.decision_status,d.rule_id
           FROM direct_high_coverage_classifier_axis_derivations x
           JOIN direct_high_coverage_classifier_decision_bindings b
             ON b.run_id=x.run_id AND b.derivation_id=x.derivation_id
           JOIN classification_decisions d ON d.id=b.decision_id
           WHERE x.run_id=? ORDER BY x.prediction_id,d.dimension""",
        (run_id,),
    ).fetchall():
        decisions_by_prediction[str(decision_row[0])].append(tuple(decision_row[1:]))
    plan_payment_ids = {
        int(row[0]) for row in db.execute(
            """SELECT DISTINCT ap.payment_id
               FROM allocation_plans ap
               JOIN direct_payment_projection_links l
                 ON l.run_id=? AND l.payment_id=ap.payment_id""",
            (run_id,),
        ).fetchall()
    }
    allocation_payment_ids = {
        int(row[0]) for row in db.execute(
            """SELECT DISTINCT a.payment_id
               FROM current_cost_allocations a
               JOIN direct_payment_projection_links l
                 ON l.run_id=? AND l.payment_id=a.payment_id""",
            (run_id,),
        ).fetchall()
    }
    existing_reviews = {
        int(row[0]): tuple(row[1:]) for row in db.execute(
            """SELECT r.payment_id,r.outcome,r.reason_code,r.rationale,
                      r.review_status,r.rule_id
               FROM allocation_review_cases r
               JOIN direct_payment_projection_links l
                 ON l.run_id=? AND l.payment_id=r.payment_id""",
            (run_id,),
        ).fetchall()
    }
    registry_target_codes = {
        str(row[0]) for row in db.execute(
            """SELECT DISTINCT target_code
               FROM direct_high_coverage_trip_registries
               WHERE run_id=? AND registry_status='provisional'""",
            (run_id,),
        ).fetchall()
    }
    counts = Counter()
    for (
        prediction_id, payment_id, rule_path, allocation_target,
        rationale, transaction_type, axis_evidence_json,
    ) in rows:
        path = _target_path(rule_path)
        try:
            axis_evidence = json.loads(str(axis_evidence_json))
        except (TypeError, json.JSONDecodeError):
            axis_evidence = {}
        prediction_has_finality_veto = _has_row_finality_veto({
            "axis_evidence": axis_evidence,
        })
        admitted_terminal = path in admitted_paths and not prediction_has_finality_veto
        if (
            not admitted_terminal
            and path not in REVIEW_TARGET_PATHS
            and not prediction_has_finality_veto
        ):
            continue
        if str(transaction_type) not in {"purchase", *REVERSAL_TYPES}:
            raise ValueError("high_provisional_transaction_type_invalid")
        owner_confirmation_veto = False
        if admitted_terminal:
            outcome = "structural_rule_admitted"
            reason_code = "structural_rule_admitted_no_allocation"
            if str(allocation_target) in {TRIP_UNASSIGNED, OVERHEAD_TARGET}:
                raise ValueError("high_admitted_structural_target_invalid")
            if (
                path in REGISTRY_BACKED_TARGET_PATHS
                and str(allocation_target) not in registry_target_codes
            ):
                raise ValueError("high_admitted_registry_target_missing")
        else:
            owner_confirmation_veto = (
                path == FOREIGN_SERVICE_PERIOD_PENDING_PATH
                or (
                    prediction_has_finality_veto
                    and path not in REVIEW_TARGET_PATHS
                    and str(allocation_target) == TRIP_UNASSIGNED
                )
            )
        if not admitted_terminal and prediction_has_finality_veto and path not in REVIEW_TARGET_PATHS:
            if str(allocation_target) == OVERHEAD_TARGET:
                # The user-facing 2025-payment lane also covers rows that the
                # ordinary policy would otherwise classify as overhead.  Keep
                # that row display-only and block the later confirmed
                # overhead review/side effect until the required mail period
                # is present.
                outcome = "overhead"
                reason_code = "2025_payment_mail_service_period_required"
                owner_confirmation_veto = True
            else:
                outcome = "travel_unassigned" if owner_confirmation_veto else "trip"
                reason_code = "row_finality_veto_owner_confirmation"
        elif not admitted_terminal and path in {
            "manual_travel_tab_exact",
            "manual_travel_tab_mn_target_invariant",
            MANUAL_REVERSAL_EXACT_PATH,
            MANUAL_REVERSAL_MN_PATH,
            "current_card_geography_context_exact_2026",
            REGISTRY_PATH,
            ACTIVITY_PLACEHOLDER_PATH,
            RESERVATION_PLACEHOLDER_PATH,
            REVERSAL_PROVISIONAL_INHERIT_PATH,
            GMAIL_PAYMENT_SERVICE_PERIOD_PATH,
            INFERRED_EXTERNAL_TARGET_PATH,
            FOREIGN_USE_DATE_SCHEDULE_PATH,
        }:
            outcome = "trip"
            reason_code = "provisional_travel_target_owner_confirmation"
            if str(allocation_target) in {TRIP_UNASSIGNED, OVERHEAD_TARGET}:
                raise ValueError("high_provisional_trip_target_invalid")
            if (
                path in REGISTRY_BACKED_TARGET_PATHS
                and str(allocation_target) not in registry_target_codes
            ):
                raise ValueError("high_provisional_registry_target_missing")
        elif not admitted_terminal and path == "manual_travel_tab_ambiguous":
            outcome = "travel_unassigned"
            reason_code = "manual_travel_tab_ambiguous_owner_confirmation"
            if str(allocation_target) != TRIP_UNASSIGNED:
                raise ValueError("high_ambiguous_manual_target_invalid")
        elif not admitted_terminal and path == GMAIL_PAYMENT_SERVICE_PERIOD_PENDING_PATH:
            outcome = "travel_unassigned"
            reason_code = "gmail_service_period_unverified_owner_confirmation"
            if str(allocation_target) != TRIP_UNASSIGNED:
                raise ValueError("high_gmail_service_period_pending_target_invalid")
        elif not admitted_terminal and path == GMAIL_PAYMENT_APPROVAL_FAMILY_PENDING_PATH:
            outcome = "travel_unassigned"
            reason_code = "gmail_approval_family_not_singleton_owner_confirmation"
            if str(allocation_target) != TRIP_UNASSIGNED:
                raise ValueError("high_gmail_approval_family_pending_target_invalid")
        elif not admitted_terminal and path == DOMESTIC_GATEWAY_UNVERIFIED_PATH:
            outcome = "travel_unassigned"
            reason_code = "domestic_gateway_purpose_owner_confirmation"
            if str(allocation_target) != TRIP_UNASSIGNED:
                raise ValueError("high_domestic_gateway_pending_target_invalid")
        elif not admitted_terminal and path == FOREIGN_SERVICE_PERIOD_PENDING_PATH:
            outcome = "travel_unassigned"
            reason_code = "foreign_service_period_pending_owner_confirmation"
            if str(allocation_target) != TRIP_UNASSIGNED:
                raise ValueError("high_foreign_service_period_pending_target_invalid")
        elif not admitted_terminal:
            outcome = "travel_unassigned"
            reason_code = "manual_geography_conflict_owner_confirmation"
            if str(allocation_target) != TRIP_UNASSIGNED:
                raise ValueError("high_conflicting_manual_target_invalid")

        review_status = (
            "confirmed"
            if admitted_terminal
            else AUTO_PROVISIONAL_REVIEW_STATUS
            if (
                prediction_has_finality_veto and not owner_confirmation_veto
            ) or path in {
                "manual_travel_tab_exact",
                "manual_travel_tab_mn_target_invariant",
                MANUAL_REVERSAL_EXACT_PATH,
                MANUAL_REVERSAL_MN_PATH,
                "current_card_geography_context_exact_2026",
                REGISTRY_PATH,
                ACTIVITY_PLACEHOLDER_PATH,
                RESERVATION_PLACEHOLDER_PATH,
                REVERSAL_PROVISIONAL_INHERIT_PATH,
                GMAIL_PAYMENT_SERVICE_PERIOD_PATH,
                INFERRED_EXTERNAL_TARGET_PATH,
                FOREIGN_USE_DATE_SCHEDULE_PATH,
            }
            else OWNER_CONFIRMATION_REVIEW_STATUS
        )
        if review_status == AUTO_PROVISIONAL_REVIEW_STATUS:
            reason_code = "provisional_travel_target_metadata_enrichment"

        decision_rows = decisions_by_prediction.get(str(prediction_id), [])
        dimensions = {str(row[1]) for row in decision_rows}
        rules = {str(row[4]) for row in decision_rows}
        statuses = {str(row[3]) for row in decision_rows}
        if (
            len(decision_rows) != len(ACTIVE_DIMENSIONS)
            or dimensions != set(ACTIVE_DIMENSIONS)
            or rules != {RULE_ID}
            or statuses != (
                {"confirmed"} if admitted_terminal else {"needs_review"}
            )
        ):
            raise ValueError("high_provisional_axis_contract_invalid")

        if payment_id in plan_payment_ids or payment_id in allocation_payment_ids:
            raise ValueError("high_provisional_allocation_leak")

        existing = existing_reviews.get(int(payment_id))
        if existing is not None:
            if (
                str(existing[0]) != outcome
                or str(existing[1]) != reason_code
                or str(existing[4]) != RULE_ID
                or str(existing[3]) != review_status
            ):
                raise ValueError("high_provisional_review_conflict")

        db.execute(
            """INSERT INTO allocation_review_cases(
                     payment_id,outcome,reason_code,rationale,review_status,rule_id)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(payment_id) DO UPDATE SET
                 outcome=excluded.outcome,
                 reason_code=excluded.reason_code,
                 rationale=excluded.rationale,
                 review_status=excluded.review_status,
                 rule_id=excluded.rule_id,
                 reviewed_at=CURRENT_TIMESTAMP""",
            (
                payment_id, outcome, reason_code,
                str(rationale), review_status, RULE_ID,
            ),
        )
        counts[outcome] += 1
    return {
        "provisional_trip_count": int(counts["trip"]),
        "ambiguous_review_count": int(counts["travel_unassigned"]),
        "structural_rule_admitted_count": int(
            counts["structural_rule_admitted"]
        ),
    }


def validate_high_coverage_classifier(
    db: sqlite3.Connection,
    run_id: str,
    *,
    require_allocations: bool = False,
    admitted_rule_paths: Iterable[str] = (),
) -> dict[str, object]:
    admitted_paths = normalize_admitted_rule_paths(admitted_rule_paths)
    issues: list[str] = []
    try:
        cost_payment_id_set = {
            int(row[0]) for row in db.execute(
                "SELECT payment_id FROM direct_2025_cost_accounting WHERE run_id=?",
                (run_id,),
            ).fetchall()
        }
    except sqlite3.OperationalError:
        cost_payment_id_set = set()
    geographic_context_evidence_count = int(db.execute(
        """SELECT COUNT(*) FROM direct_promotion_evidence
           WHERE run_id=? AND source_kind='geographic_trip_context'""",
        (run_id,),
    ).fetchone()[0])
    if geographic_context_evidence_count:
        issues.append("geographic_context_used_as_transaction_evidence")
    try:
        expected = _build_expected(db, run_id, admitted_paths)
    except (TypeError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        return {"passed": False, "issues": [f"expected_rebuild_failed:{exc}"]}
    model = expected["model"]
    assert isinstance(model, dict)
    actual_model = db.execute(
        """SELECT model_id,model_contract,model_sha256,run_state_sha256,
                  training_source_sha256,candidate_set_sha256,prediction_set_sha256,
                  training_row_count,candidate_count,promoted_count,
                  validation_count,validation_error_count,training_role,payload_json
           FROM direct_high_coverage_classifier_models WHERE run_id=?""",
        (run_id,),
    ).fetchone()
    expected_model = tuple(model[name] for name in (
        "model_id", "model_contract", "model_sha256", "run_state_sha256",
        "training_source_sha256", "candidate_set_sha256", "prediction_set_sha256",
        "training_row_count", "candidate_count", "promoted_count",
        "validation_count", "validation_error_count", "training_role",
        "payload_json",
    ))
    if actual_model is None or tuple(actual_model) != expected_model:
        issues.append("high_classifier_model_mismatch")
    expected_registries = sorted(
        (
            str(row["registry_id"]), str(row["registry_version"]),
            str(row["rule_id"]), str(row["registry_sha256"]),
            str(row["target_code"]), str(row["target_kind"]),
            str(row["source_system"]), str(row["card_identity_sha256"]),
            str(row["country"]), str(row["region"]),
            str(row["starts_on"]), str(row["ends_on"]),
            _sha(sorted(str(item["direct_event_key"]) for item in row["members"])),
            _sha(sorted(str(item["current_fact_sha256"]) for item in row["members"])),
            "provisional", str(row["payload_json"]),
        )
        for row in expected["trip_registries"]
    )
    actual_registries = [tuple(row) for row in db.execute(
        """SELECT registry_id,registry_version,rule_id,registry_sha256,
                  target_code,target_kind,source_system,card_identity_sha256,
                  country,region,starts_on,ends_on,event_set_sha256,
                  fact_set_sha256,registry_status,payload_json
           FROM direct_high_coverage_trip_registries
           WHERE run_id=? ORDER BY registry_id""",
        (run_id,),
    ).fetchall()]
    if actual_registries != expected_registries:
        issues.append("high_classifier_trip_registry_mismatch")
    expected_members = sorted(
        (
            str(registry["registry_id"]), int(member["payment_id"]),
            str(member["direct_event_key"]), str(member["current_evidence_id"]),
            str(member["current_fact_sha256"]),
        )
        for registry in expected["trip_registries"]
        for member in registry["members"]
    )
    actual_members = [tuple(row) for row in db.execute(
        """SELECT registry_id,payment_id,direct_event_key,current_evidence_id,
                  current_fact_sha256
           FROM direct_high_coverage_trip_registry_members
           WHERE run_id=? ORDER BY registry_id,payment_id""",
        (run_id,),
    ).fetchall()]
    if actual_members != expected_members:
        issues.append("high_classifier_trip_registry_member_mismatch")
    registry_allocation_leak_count = int(db.execute(
        """SELECT COUNT(*) FROM direct_high_coverage_trip_registries r
           JOIN allocation_plans p ON p.payment_id IN (
             SELECT m.payment_id
             FROM direct_high_coverage_trip_registry_members m
             WHERE m.run_id=r.run_id AND m.registry_id=r.registry_id
           )
           WHERE r.run_id=?
             AND NOT EXISTS (
               SELECT 1 FROM direct_2025_cost_accounting c
               WHERE c.run_id=r.run_id
                 AND c.payment_id IN (
                   SELECT m2.payment_id
                   FROM direct_high_coverage_trip_registry_members m2
                   WHERE m2.run_id=r.run_id AND m2.registry_id=r.registry_id
                 )
             )""",
        (run_id,),
    ).fetchone()[0])
    if registry_allocation_leak_count:
        leak_sample = [
            {
                "registry_id": str(row[0]),
                "payment_id": int(row[1]),
                "target_code": str(row[2]),
                "allocation_count": int(row[3]),
                "rule_path": str(row[4]),
            }
            for row in db.execute(
                """SELECT r.registry_id,m.payment_id,at.code,
                          COUNT(DISTINCT ap.id),hc.rule_path
                   FROM direct_high_coverage_trip_registries r
                   JOIN direct_high_coverage_trip_registry_members m
                     ON m.run_id=r.run_id AND m.registry_id=r.registry_id
                   JOIN allocation_plans ap ON ap.payment_id=m.payment_id
                   JOIN cost_allocations ca ON ca.plan_id=ap.id
                   JOIN allocation_targets at ON at.id=ca.target_id
                   LEFT JOIN direct_high_coverage_classifier_predictions hc
                     ON hc.run_id=r.run_id AND hc.payment_id=m.payment_id
                   WHERE r.run_id=?
                   GROUP BY r.registry_id,m.payment_id,at.code,hc.rule_path
                   ORDER BY r.registry_id,m.payment_id
                   LIMIT 10""",
                (run_id,),
            ).fetchall()
        ]
        issues.append(
            "high_classifier_trip_registry_allocation_leak:"
            + json.dumps(leak_sample, ensure_ascii=False, sort_keys=True)
        )
    actual_predictions = [tuple(row) for row in db.execute(
        """SELECT prediction_id,model_id,direct_event_key,current_evidence_id,
                  payment_id,feature_sha256,account,cost_type,allocation_target,
                  rule_path,confidence,confidence_label,schedule_status,
                  conflict_count,prediction_sha256,axis_evidence_json,rationale
           FROM direct_high_coverage_classifier_predictions
           WHERE run_id=? ORDER BY prediction_id""",
        (run_id,),
    ).fetchall()]
    fields = (
        "prediction_id", "model_id", "direct_event_key", "current_evidence_id",
        "payment_id", "feature_sha256", "account", "cost_type",
        "allocation_target", "rule_path", "confidence", "confidence_label",
        "schedule_status", "conflict_count", "prediction_sha256",
        "axis_evidence_json", "rationale",
    )
    expected_predictions = sorted(
        tuple(
            row[field]
            if field != "axis_evidence_json"
            else _canonical(row["axis_evidence"]).decode("utf-8")
            for field in fields
        )
        for row in expected["predictions"]
    )
    if actual_predictions != expected_predictions:
        issues.append("high_classifier_prediction_set_mismatch")
    current_by_payment = {
        int(row["payment_id"]): row
        for row in _load_current(db, run_id)
    }
    for row in actual_predictions:
        if int(row[4]) in cost_payment_id_set:
            continue
        prediction = {
            "prediction_id": str(row[0]),
            "payment_id": int(row[4]),
            "account": str(row[6]),
            "cost_type": str(row[7]),
            "allocation_target": str(row[8]),
            "rule_path": str(row[9]),
        }
        try:
            axis_payload = json.loads(str(row[15]))
        except (TypeError, json.JSONDecodeError):
            issues.append(
                f"axis_evidence_json_invalid:{prediction['prediction_id']}"
            )
            continue
        for issue in _axis_evidence_contract_issues(
            prediction,
            axis_payload,
            current_by_payment.get(prediction["payment_id"]),
            admitted_paths,
        ):
            issues.append(f"{issue}:{prediction['prediction_id']}")
    link_fields = (
        "reversal_payment_id", "reversal_direct_event_key",
        "original_payment_id", "original_prediction_id", "relation_id",
        "relation_match_method", "relation_reference_value", "original_target",
        "original_prediction_sha256", "link_sha256", "inheritance_status",
    )
    expected_links = sorted(
        tuple(link[field] for field in link_fields)
        for link in expected["reversal_inheritance_links"]
    )
    actual_links = [tuple(row) for row in db.execute(
        """SELECT reversal_payment_id,reversal_direct_event_key,
                  original_payment_id,original_prediction_id,relation_id,
                  relation_match_method,relation_reference_value,original_target,
                  original_prediction_sha256,link_sha256,inheritance_status
           FROM direct_high_coverage_reversal_inheritance
           WHERE run_id=? ORDER BY reversal_payment_id""",
        (run_id,),
    ).fetchall()]
    if actual_links != expected_links:
        issues.append("high_classifier_reversal_inheritance_mismatch")
    for link in actual_links:
        (
            reversal_payment_id, reversal_event_key, original_payment_id,
            original_prediction_id, relation_id, relation_match_method,
            relation_reference_value, original_target,
            original_prediction_sha256, link_sha256, inheritance_status,
        ) = link
        reversal_prediction = db.execute(
            """SELECT prediction_id,current_evidence_id,rule_path,
                      allocation_target,prediction_sha256
               FROM direct_high_coverage_classifier_predictions
               WHERE run_id=? AND payment_id=?""",
            (run_id, int(reversal_payment_id)),
        ).fetchone()
        if reversal_prediction is None:
            issues.append("high_classifier_reversal_link_prediction_missing")
            continue
        if _target_path(reversal_prediction[2]) != REVERSAL_PROVISIONAL_INHERIT_PATH:
            issues.append("high_classifier_reversal_link_path_mismatch")
        if str(inheritance_status) != "provisional":
            issues.append("high_classifier_reversal_link_status_invalid")
        relation_count = int(db.execute(
            """SELECT COUNT(*) FROM transaction_relations
               WHERE id=? AND transaction_id=? AND related_transaction_id=?
                 AND relation_status NOT IN ('rejected','superseded')""",
            (int(relation_id), int(reversal_payment_id), int(original_payment_id)),
        ).fetchone()[0])
        if relation_count != 1:
            issues.append("high_classifier_reversal_link_relation_invalid")
        original_prediction = db.execute(
            """SELECT prediction_id,allocation_target,rule_path,prediction_sha256
               FROM direct_high_coverage_classifier_predictions
               WHERE run_id=? AND prediction_id=? AND payment_id=?""",
            (run_id, str(original_prediction_id), int(original_payment_id)),
        ).fetchone()
        if original_prediction is None:
            issues.append("high_classifier_reversal_link_original_prediction_missing")
        elif (
            str(original_prediction[0]) != str(original_prediction_id)
            or str(original_prediction[1]) != str(original_target)
            or str(original_prediction[3]) != str(original_prediction_sha256)
        ):
            issues.append("high_classifier_reversal_link_original_prediction_mismatch")
        if (
            original_prediction is not None
            and _target_path(original_prediction[2]) not in PROVISIONAL_TARGET_PATHS
        ):
            issues.append("high_classifier_reversal_link_original_target_not_provisional")
        link_core = {
            "run_id": run_id,
            "reversal_payment_id": int(reversal_payment_id),
            "reversal_direct_event_key": str(reversal_event_key),
            "reversal_current_evidence_id": str(reversal_prediction[1]),
            "relation_id": int(relation_id),
            "relation_match_method": str(relation_match_method),
            "relation_reference_value": str(relation_reference_value or ""),
            "original_payment_id": int(original_payment_id),
            "original_prediction_id": str(original_prediction_id),
            "original_target": str(original_target),
            "original_prediction_sha256": str(original_prediction_sha256),
        }
        if _sha(link_core) != str(link_sha256):
            issues.append("high_classifier_reversal_link_hash_mismatch")
    if db.execute(
        """SELECT COUNT(*)
           FROM direct_high_coverage_reversal_inheritance h
           JOIN direct_high_coverage_classifier_predictions p
             ON p.run_id=h.run_id AND p.payment_id=h.reversal_payment_id
           WHERE h.run_id=?
             AND instr(p.rule_path,'|current_card_reversal_provisional_inherit|')=0""",
        (run_id,),
    ).fetchone()[0]:
        issues.append("high_classifier_reversal_link_orphaned")
    actual_withheld = [tuple(row) for row in db.execute(
        """SELECT direct_event_key,current_evidence_id,reason_code,detail_sha256
           FROM direct_high_coverage_classifier_withheld
           WHERE run_id=? ORDER BY direct_event_key,reason_code""",
        (run_id,),
    ).fetchall()]
    expected_withheld = sorted(
        (
            row["direct_event_key"], row["current_evidence_id"],
            row["reason_code"], row["detail_sha256"],
        ) for row in expected["withheld"]
    )
    if actual_withheld != expected_withheld:
        issues.append("high_classifier_withheld_set_mismatch")
    expected_decisions = []
    for prediction in expected["predictions"]:
        if int(prediction["payment_id"]) in cost_payment_id_set:
            continue
        for dimension in ACTIVE_DIMENSIONS:
            value = str(prediction[dimension])
            derivation_id = "high-coverage-derivation:" + _sha({
                "prediction_id": prediction["prediction_id"],
                "dimension": dimension, "value": value,
            })
            expected_decisions.append((
                prediction["prediction_id"], prediction["direct_event_key"],
                dimension, value, RULE_ID, prediction["current_evidence_id"],
                derivation_id, prediction["confidence"],
                prediction["confidence_label"],
                _decision_status_for_prediction(prediction, admitted_paths), RULE_ID,
                prediction["rationale"],
            ))
    actual_decision_rows = db.execute(
        """SELECT x.prediction_id,x.direct_event_key,x.dimension,x.value,
                  x.rule_id,x.current_evidence_id,x.derivation_id,d.confidence,
                  d.confidence_label,d.decision_status,d.rule_id,d.rationale,
                  x.payment_id
           FROM direct_high_coverage_classifier_axis_derivations x
           JOIN direct_high_coverage_classifier_decision_bindings b
             ON b.run_id=x.run_id AND b.derivation_id=x.derivation_id
           JOIN classification_decisions d ON d.id=b.decision_id
           WHERE x.run_id=? ORDER BY x.prediction_id,x.dimension""",
        (run_id,),
    ).fetchall()
    actual_decisions = [
        tuple(row[:-1]) for row in actual_decision_rows
        if int(row[-1]) not in cost_payment_id_set
    ]
    if actual_decisions != sorted(expected_decisions):
        issues.append("high_classifier_decision_set_mismatch")
    if require_allocations:
        expected_allocations = sorted(
            (
                row["direct_event_key"], row["allocation_target"],
                int(db.execute(
                    "SELECT amount_krw FROM payment_transactions WHERE id=?",
                    (row["payment_id"],),
                ).fetchone()[0]),
            )
            for row in expected["predictions"]
            if (
                int(row["payment_id"]) not in cost_payment_id_set
                and
                row["allocation_target"] not in {OVERHEAD_TARGET, TRIP_UNASSIGNED}
                and _target_path(row["rule_path"]) not in admitted_paths
                and not _is_review_prediction(row, admitted_paths)
            )
        )
        actual_allocation_rows = db.execute(
            """SELECT p.payment_id,p.direct_event_key,t.code,a.amount_krw
               FROM direct_high_coverage_classifier_predictions p
               JOIN current_cost_allocations a ON a.payment_id=p.payment_id
               JOIN allocation_targets t ON t.id=a.target_id
               WHERE p.run_id=? ORDER BY p.direct_event_key""",
            (run_id,),
        ).fetchall()
        actual_allocations = [
            tuple(row[1:]) for row in actual_allocation_rows
            if int(row[0]) not in cost_payment_id_set
        ]
        if actual_allocations != expected_allocations:
            issues.append("high_classifier_allocation_set_mismatch")
    return {
        "passed": not issues,
        "issues": issues,
        "candidate_count": model["candidate_count"],
        "promoted_payment_count": model["promoted_count"],
        "decision_count": int(model["promoted_count"]) * len(ACTIVE_DIMENSIONS),
        "withheld_payment_count": len(expected["withheld"]),
        "validation_count": model["validation_count"],
        "validation_error_count": model["validation_error_count"],
        "target_counts": expected["target_counts"],
        "target_path_counts": expected["target_path_counts"],
        "target_path_merchant_counts": expected["target_path_merchant_counts"],
        "geographic_context_evidence_count": geographic_context_evidence_count,
        "manual_travel_tab_classification_evidence_used": bool(
            expected.get("manual_match_links")
        ),
        "manual_match_links_sha256": expected.get("manual_match_links_sha256"),
    }
