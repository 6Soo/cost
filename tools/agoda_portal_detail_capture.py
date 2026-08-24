#!/usr/bin/env python3
"""Capture payment-detail evidence for the pinned Agoda 2026 booking set.

This tool deliberately stops at evidence collection.  It does not create
payment-booking links, classification decisions, allocations, journals, or
postings.  The mutable crash-resume work database and the immutable sealed
result are private files below ``/tmp``; the pinned list staging database is
opened only with SQLite ``mode=ro&immutable=1``.

Raw accessibility trees, screenshots, names, e-mail addresses, property
addresses, full PANs and CVVs are never persisted or printed.  Booking IDs
and card last-four values are retained only inside the mode-0600 private DB so
that a later, separately reviewed reconciliation step can bind evidence.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import hmac
import json
import os
import re
import signal
import sqlite3
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from tools.agoda_portal_page_capture import (
        _card_blocks,
        _click,
        _element_name,
        _run_orca,
        _tree,
    )
except ModuleNotFoundError:  # direct ``python tools/...`` invocation
    from agoda_portal_page_capture import (
        _card_blocks,
        _click,
        _element_name,
        _run_orca,
        _tree,
    )


EXPECTED_TARGET_YEAR = 2026
TARGET_SOURCE_SCOPES = ("target_2026_overlap", "year_unknown")
COMPETITOR_SERVICE_END_FLOOR = date(2025, 8, 1)
DETAIL_STATUSES = (
    "success",
    "failed_load",
    "failed_parse",
    "failed_verify",
    "failed_drift",
)
TAB_RANK = {"Upcoming": 0, "Completed": 1, "Cancelled": 2}
WINDOW_REBIND_REASON = "crash_recovery_window_rebind"
NO_PRICE_OBSERVATION_KIND = "price_evidence_not_displayed"
STATUS_CONFLICT_OBSERVATION_KIND = (
    "cancelled_list_detail_status_conflict_no_price"
)
TERMINAL_OBSERVATION_KINDS = {
    NO_PRICE_OBSERVATION_KIND,
    STATUS_CONFLICT_OBSERVATION_KIND,
}
TERMINAL_SOURCE_RESERVATION_STATUSES = frozenset({"Cancelled", "unknown"})


TEXT_NODE_RE = re.compile(r"^\s*\d+\s+(?:텍스트|제목)\s*(.*?)\s*$")
MANAGE_BUTTON_RE = re.compile(
    r"^\s*(\d+)\s+(?:단추|button)\s+(?:Manage booking|예약 관리)"
    r"(?:\s+(\d{6,20}))?\s*$",
    re.IGNORECASE,
)
MANAGE_BUTTON_RE = re.compile(
    r"^\s*(\d+)\s+(?:\uB2E8\uCD94|button)\s+"
    r"(?:Manage booking|\uC608\uC57D \uAD00\uB9AC|"
    r"\uC608\uC57D \uD655\uC778/\uBCC0\uACBD\uD558\uAE30)"
    r"(?:\s+(\d{6,20}))?\s*$",
    re.IGNORECASE,
)
BACK_BUTTON_RE = re.compile(
    r"^\s*(\d+)\s+(?:단추|링크|button|link)\s+"
    r"(?:Back to bookings|Back to booking|예약으로 돌아가기)\s*$",
    re.IGNORECASE,
)
DETAIL_DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(\d{1,2}),\s+(\d{4})\b",
    re.IGNORECASE,
)
KOREAN_DATE_RE = re.compile(
    r"(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"
    r"(?:\s*[월화수목금토일]\s*요일)?"
)
ROOM_NIGHT_RE = re.compile(
    r"\b(\d+)\s+room(?:\(s\)|s)?\s*[x×]\s*(\d+)\s+night(?:\(s\)|s)?\b",
    re.IGNORECASE,
)
KOREAN_ROOM_NIGHT_RE = re.compile(
    r"(?:(?<!\d)(\d+)\s*(?:개\s*)?(?:객실|룸)|"
    r"(?:객실|룸)\s*(\d+)\s*개)\s*[x×]\s*(\d+)\s*(?:박|밤)(?!\w)"
)
ROOM_COUNT_INLINE_RE = re.compile(
    r"(?<!\d)(\d+)\s*[x×]\s*[^\n]*?\broom(?:\(s\)|s)?\b",
    re.IGNORECASE,
)
CARD4_RE = re.compile(
    r"(?:(?:[•*xX]\s*){4,}.*?(?P<masked>\d{4})\s*$|"
    r"\b(?:ending(?:\s+in)?|last\s*4|끝자리|마지막\s*4자리)\D*"
    r"(?P<ending>\d{4})\b)",
    re.IGNORECASE,
)
CARD_ISSUER_RE = re.compile(
    r"\b(Visa|Master\s*Card|Mastercard|American Express|Amex|JCB|UnionPay|"
    r"비자|마스터\s*카드|아메리칸\s*익스프레스)\b",
    re.IGNORECASE,
)
REFERENCE_CODE_RE = re.compile(r"(?<!\d)(\d{6,20})(?!\d)")
BOOKING_ID_LABELS = frozenset(
    {"booking id", "예약 번호", "예약번호", "예약 id"}
)
REFERENCE_CODE_LABELS = frozenset(
    {"reference code", "참조 코드", "참조코드"}
)
PAYMENT_INFORMATION_LABELS = frozenset(
    {"payment information", "결제 정보", "결제정보"}
)
CARD_TYPE_LABELS = frozenset({"card type", "카드 종류", "카드종류"})
CARD_NUMBER_LABELS = frozenset({"card number", "카드 번호", "카드번호"})

CURRENCY_SCALE = {
    "JPY": 0,
    "KRW": 0,
    "VND": 0,
    "IDR": 0,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "TWD": 2,
    "THB": 2,
    "HKD": 2,
    "CNY": 2,
    "AUD": 2,
    "CAD": 2,
    "SGD": 2,
    "PHP": 2,
    "MYR": 2,
    "NZD": 2,
}
CURRENCY_ALIASES = {
    "₩": "KRW",
    "KRW": "KRW",
    "¥": "JPY",
    "￥": "JPY",
    "JPY": "JPY",
    "US$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "NT$": "TWD",
    "TWD": "TWD",
    "฿": "THB",
    "THB": "THB",
    "HK$": "HKD",
    "HKD": "HKD",
    "CNY": "CNY",
    "RMB": "CNY",
    "AUD": "AUD",
    "CAD": "CAD",
    "SGD": "SGD",
    "VND": "VND",
    "IDR": "IDR",
    "PHP": "PHP",
    "MYR": "MYR",
    "NZD": "NZD",
}
_CURRENCY_TOKEN = "|".join(
    re.escape(token) for token in sorted(CURRENCY_ALIASES, key=len, reverse=True)
)
AMOUNT_PREFIX_RE = re.compile(
    rf"^\s*(?P<paren>\()?\s*(?P<currency>{_CURRENCY_TOKEN})\s*"
    rf"(?P<sign>[+-]?)\s*(?P<number>\d[\d\s\u00a0\u202f,\.]*)\s*\)?\s*$",
    re.IGNORECASE,
)
AMOUNT_SUFFIX_RE = re.compile(
    rf"^\s*(?P<paren>\()?\s*(?P<sign>[+-]?)\s*"
    rf"(?P<number>\d[\d\s\u00a0\u202f,\.]*)\s*"
    rf"(?P<currency>{_CURRENCY_TOKEN})\s*\)?\s*$",
    re.IGNORECASE,
)

PRICE_KIND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "chargeback",
        re.compile(r"\b(chargeback|payment reversal)\b|차지백", re.I),
    ),
    (
        "future_due",
        re.compile(
            r"\b(pay later|future payment|scheduled payment|pay nothing until|"
            r"automatically charged on|payment will be settled on)\b|"
            r"결제 예정|나중에 결제|자동(?:으로)? 청구|결제일에 청구",
            re.I,
        ),
    ),
    (
        "gross_total",
        re.compile(
            r"\b(total charge|grand total|booking total)\b|총 금액|총액|예약 총액",
            re.I,
        ),
    ),
    (
        "paid_today",
        re.compile(
            r"\b(paid today|paid now|amount paid)\b|오늘 결제됨|오늘 결제|"
            r"지금 결제됨|결제 완료",
            re.I,
        ),
    ),
    (
        "charge",
        re.compile(r"\b(charged on|card charged|payment on)\b|청구일|결제일", re.I),
    ),
    ("remaining_due", re.compile(r"\b(remaining|balance due|amount due)\b", re.I)),
    (
        "property_due",
        re.compile(
            r"\b(pay at (?:the )?(?:property|hotel)|property due|pay on arrival)\b|"
            r"숙소에서(?: 직접)? 결제|현장에서 결제|도착 시 결제",
            re.I,
        ),
    ),
    (
        "taxes_and_fees",
        re.compile(
            r"\b(taxes?\s*(?:and|&)\s*fees?|taxes and charges)\b|"
            r"세금\s*(?:및|과|와)\s*(?:봉사료|제반요금|제반 요금|수수료)",
            re.I,
        ),
    ),
    (
        "tax",
        re.compile(
            r"\b(tax|vat|city tax|accommodation tax)\b|세금|도시세|현지 세금|숙박세",
            re.I,
        ),
    ),
    ("fee", re.compile(r"\b(fee|service charge|booking fee)\b|수수료|봉사료", re.I)),
    ("discount", re.compile(r"\b(discount|promotion|promo)\b|할인|프로모션", re.I)),
    ("coupon", re.compile(r"\b(coupon|voucher)\b|쿠폰", re.I)),
    ("agoda_cash", re.compile(r"\b(agodacash|agoda cash)\b|아고다\s*캐시", re.I)),
    ("points", re.compile(r"\b(points?|miles?)\b|포인트|마일리지", re.I)),
    (
        "refund",
        re.compile(
            r"\b(refund|refunded)\b|환불(?:됨|완료|처리|금액)?|"
            r"부분\s*환불|일부\s*환불|전액\s*환불",
            re.I,
        ),
    ),
    (
        "base",
        re.compile(
            r"\b(room(?:\(s\)|s)?\s*[x×].*night|room rate|base price|subtotal)\b|"
            r"객실\s*요금|객실료|객실\s*\d+\s*개?\s*[x×].*박|"
            r"기본 요금|소계",
            re.I,
        ),
    ),
)


class CaptureError(RuntimeError):
    """Base class for a bounded, reportable capture failure."""


class DetailLoadError(CaptureError):
    pass


class DetailParseError(CaptureError):
    pass


class DetailVerifyError(CaptureError):
    pass


class ListDriftError(CaptureError):
    pass


@dataclass(frozen=True)
class Money:
    currency: str
    decimal_text: str
    minor_units: int
    scale: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "decimal_text": self.decimal_text,
            "minor_units": self.minor_units,
            "scale": self.scale,
        }


@dataclass(frozen=True)
class SourceBooking:
    page_no: int
    booking_id: str
    booking_id_sha256: str
    service_start_on: str | None
    service_end_on: str | None
    reservation_status: str
    list_card_sha256: str
    tab_name: str = "Completed"
    card_position: int = 1
    booking_pseudonym_hmac: str = ""
    source_scope_status: str = "target_2026_overlap"

    def membership_tuple(self) -> tuple[Any, ...]:
        return (
            self.tab_name,
            self.booking_id_sha256,
            self.booking_pseudonym_hmac,
            self.service_start_on,
            self.service_end_on,
            self.source_scope_status,
            self.reservation_status,
            self.list_card_sha256,
        )


@dataclass(frozen=True)
class SourceSnapshot:
    path: Path
    file_sha256: str
    source_run_id: str
    source_capture_set_sha256: str
    membership_ordered_sha256: str
    membership_set_sha256: str
    bookings: tuple[SourceBooking, ...]
    page_manifest: dict[tuple[str, int], dict[str, Any]]
    population_count: int = 0
    pseudonym_key_id: str = ""
    all_booking_semantics: tuple[tuple[str, str], ...] = ()
    tab_totals: tuple[tuple[str, int], ...] = ()
    target_2026_count: int = 0
    competitor_count: int = 0


@dataclass(frozen=True)
class UnresolvedPageBatch:
    tab_name: str
    page_no: int
    page_target_count: int
    targets: tuple[SourceBooking, ...]



def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _terminal_kind_matches_detail_status(kind: object, status: object) -> bool:
    kind_text = str(kind)
    status_text = str(status)
    return (
        kind_text == NO_PRICE_OBSERVATION_KIND
        and status_text in {"cancelled", "unknown"}
    ) or (
        kind_text == STATUS_CONFLICT_OBSERVATION_KIND
        and status_text in {"confirmed", "completed"}
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_tmp(path: Path, *, must_exist: bool = False) -> Path:
    resolved = path.expanduser().resolve()
    allowed_roots = [
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
    ]
    matched_root: Path | None = None
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            matched_root = root
            break
        except ValueError:
            continue
    if matched_root is None:
        raise CaptureError(
            "private Agoda staging paths must be below the private temp root"
        )
    if resolved == matched_root:
        raise CaptureError("private Agoda staging path must name a file")
    if must_exist and not resolved.is_file():
        raise CaptureError("required staging database is missing")
    return resolved


def _secure_private_parent(path: Path) -> None:
    """Create a private result parent without ever chmod'ing shared /tmp."""
    parent = path.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    exempt = {Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()}
    if parent.resolve() not in exempt and os.name != "nt":
        os.chmod(parent, 0o700)


def _immutable_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _visible_text_values(tree: str) -> list[str]:
    values: list[str] = []
    for line in tree.splitlines():
        match = TEXT_NODE_RE.match(line)
        if match:
            value = re.sub(r"\s+", " ", match.group(1).strip())
            values.append(value)
    return values


def _normalize_number(number: str, currency: str) -> tuple[str, int, int]:
    compact = re.sub(r"[\s\u00a0\u202f]", "", number)
    if not compact or not re.fullmatch(r"\d[\d,.]*", compact):
        raise DetailParseError("invalid_money_number")

    if "," in compact and "." in compact:
        if compact.rfind(",") > compact.rfind("."):
            compact = compact.replace(".", "").replace(",", ".")
        else:
            compact = compact.replace(",", "")
    elif "," in compact:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", compact):
            compact = compact.replace(",", "")
        else:
            compact = compact.replace(",", ".")
    elif "." in compact:
        if currency in {"JPY", "KRW", "VND", "IDR"} and re.fullmatch(
            r"\d{1,3}(?:\.\d{3})+", compact
        ):
            compact = compact.replace(".", "")

    try:
        amount = Decimal(compact)
    except InvalidOperation as exc:
        raise DetailParseError("invalid_money_decimal") from exc
    scale = CURRENCY_SCALE.get(currency)
    if scale is None:
        scale = max(0, -amount.as_tuple().exponent)
    scaled = amount * (Decimal(10) ** scale)
    if scaled != scaled.to_integral_value():
        raise DetailParseError("money_precision_exceeds_currency_scale")
    decimal_text = format(amount, "f")
    if "." in decimal_text:
        decimal_text = decimal_text.rstrip("0").rstrip(".")
    return decimal_text or "0", int(scaled), scale


def _parse_money(value: str) -> Money | None:
    normalized = value.strip().replace("−", "-")
    match = AMOUNT_PREFIX_RE.match(normalized) or AMOUNT_SUFFIX_RE.match(normalized)
    if not match:
        return None
    token = match.group("currency")
    canonical_token = next(
        (key for key in CURRENCY_ALIASES if key.casefold() == token.casefold()),
        token,
    )
    currency = CURRENCY_ALIASES[canonical_token]
    decimal_text, minor_units, scale = _normalize_number(match.group("number"), currency)
    negative = bool(match.group("paren")) or match.group("sign") == "-"
    if negative:
        amount = Decimal(decimal_text) * -1
        decimal_text = format(amount, "f")
        minor_units *= -1
    return Money(currency, decimal_text, minor_units, scale)


def _component_kind(label: str) -> str | None:
    for kind, pattern in PRICE_KIND_PATTERNS:
        if pattern.search(label):
            return kind
    return None


def _extract_price_components(values: Sequence[str]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        money = _parse_money(value)
        if money is None:
            continue
        label = ""
        for candidate in reversed(values[max(0, index - 3) : index]):
            if candidate and _parse_money(candidate) is None:
                label = candidate
                break
        kind = _component_kind(label)
        if kind is None:
            continue
        components.append(
            {
                "ordinal": len(components) + 1,
                "kind": kind,
                "label_normalized": re.sub(r"\s+", " ", label).strip().casefold(),
                **money.as_dict(),
            }
        )
    return components


def _single_component(
    components: Sequence[dict[str, Any]], kind: str
) -> dict[str, Any] | None:
    matches = [component for component in components if component["kind"] == kind]
    if len(matches) > 1:
        raise DetailParseError(f"ambiguous_{kind}_component")
    return matches[0] if matches else None


def _parse_dates(values: Sequence[str]) -> set[str]:
    parsed: set[str] = set()
    for value in values:
        for month, day, year in DETAIL_DATE_RE.findall(value):
            try:
                parsed.add(
                    datetime.strptime(
                        f"{month.title()} {day} {year}", "%b %d %Y"
                    )
                    .date()
                    .isoformat()
                )
            except ValueError:
                continue
        for year, month, day in KOREAN_DATE_RE.findall(value):
            try:
                parsed.add(
                    date(int(year), int(month), int(day)).isoformat()
                )
            except ValueError:
                continue
    return parsed


def _detail_service_period(values: Sequence[str]) -> tuple[str, str]:
    """Extract the stay period from labelled detail fields, not payment dates."""

    def dates_after(labels: set[str], max_distance: int) -> list[str]:
        for index, value in enumerate(values):
            if value.strip().casefold() not in labels:
                continue
            result: list[str] = []
            for candidate in values[index + 1 : index + 1 + max_distance]:
                result.extend(sorted(_parse_dates([candidate])))
            if result:
                return result
        return []

    check_in = dates_after(
        {"check-in", "check in", "체크인", "체크 인"}, 3
    )
    check_out = dates_after(
        {"check-out", "check out", "체크아웃", "체크 아웃"}, 3
    )
    if check_in and check_out:
        start_on, end_on = check_in[0], check_out[0]
    else:
        date_range = dates_after(
            {
                "date",
                "stay dates",
                "booking dates",
                "숙박 날짜",
                "투숙 기간",
                "여행 날짜",
            },
            4,
        )
        if len(date_range) < 2:
            raise DetailParseError("detail_service_period_missing")
        start_on, end_on = date_range[0], date_range[1]
    if date.fromisoformat(end_on) < date.fromisoformat(start_on):
        raise DetailParseError("detail_service_period_reversed")
    return start_on, end_on


def _detail_scope_status(start_on: str, end_on: str) -> str:
    start = date.fromisoformat(start_on)
    end = date.fromisoformat(end_on)
    return (
        "target_2026_overlap"
        if start <= date(2026, 12, 31) and end >= date(2026, 1, 1)
        else "outside_2026"
    )


def _value_after(
    values: Sequence[str],
    label: str | Sequence[str],
    *,
    max_distance: int = 3,
) -> str | None:
    labels = {label} if isinstance(label, str) else set(label)
    normalized_labels = {item.casefold() for item in labels}
    for index, value in enumerate(values):
        if value.casefold() not in normalized_labels:
            continue
        for candidate in values[index + 1 : index + 1 + max_distance]:
            if candidate:
                return candidate
    return None


def _status_axes(values: Sequence[str], components: Sequence[dict[str, Any]]) -> dict[str, str]:
    text = "\n".join(values).casefold()
    headline = next(
        (
            value
            for value in values
            if "your booking is" in value.casefold()
            or "예약 상태" in value
        ),
        "",
    )
    headline_lower = headline.casefold()
    cancelled_state = any(
        re.fullmatch(
            r"(?:예약\s*)?(?:cancelled|canceled|취소(?:됨|된 예약)?)",
            value.strip(),
            re.IGNORECASE,
        )
        for value in values
    )
    confirmed_state = any(
        re.fullmatch(
            r"(?:confirmed|확정됨|예약 확정|확정된 예약)",
            value.strip(),
            re.IGNORECASE,
        )
        for value in values
    )
    completed_state = any(
        re.fullmatch(
            r"(?:completed|투숙 완료|여행 완료|완료된 예약)",
            value.strip(),
            re.IGNORECASE,
        )
        for value in values
    )
    if "cancel" in headline_lower or cancelled_state:
        reservation_status = "cancelled"
    elif "complete" in headline_lower or completed_state:
        reservation_status = "completed"
    elif "confirm" in headline_lower or confirmed_state:
        reservation_status = "confirmed"
    else:
        reservation_status = "unknown"

    explicit_property_payment = any(
        re.search(
            r"\b(pay at (?:the )?(?:property|hotel)|pay on arrival)\b|"
            r"숙소에서(?: 직접)? 결제|현장에서 결제|도착 시 결제",
            value,
            re.I,
        )
        and not re.search(
            r"\b(city|local|accommodation) tax\b|도시세|현지 세금|숙박세",
            value,
            re.I,
        )
        for value in values
    )
    paid_component = any(component["kind"] == "paid_today" for component in components)
    scheduled_component = any(
        component["kind"] == "future_due" for component in components
    )
    explicit_scheduled_payment = scheduled_component or any(
        re.search(
            r"\b(pay nothing until|automatically charged on|"
            r"payment will be settled on|change credit card to be charged)\b|"
            r"결제 예정|나중에 결제|자동(?:으로)? 청구|결제일에 청구",
            value,
            re.I,
        )
        for value in values
    )
    property_component = any(component["kind"] == "property_due" for component in components)
    explicit_refund = bool(
        re.search(
            r"\b(partially refunded|fully refunded|refund (?:issued|processed|amount|status)|refunded)\b",
            text,
            re.I,
        )
        or re.search(
            r"부분\s*환불|일부\s*환불|전액\s*환불|환불(?:됨|완료|처리)",
            text,
            re.I,
        )
    )
    if explicit_refund:
        payment_status = "refunded"
    elif (
        "payment pending" in text
        or "pending payment" in text
        or re.search(r"결제\s*(?:대기|보류)(?:\s*중)?", text)
    ):
        payment_status = "pending"
    elif paid_component and scheduled_component:
        payment_status = "partially_paid"
    elif (
        "paid and confirmed" in text
        or paid_component
        or re.search(r"결제\s*(?:완료|됨)", text)
    ):
        payment_status = "paid"
    elif explicit_scheduled_payment:
        payment_status = "scheduled"
    elif explicit_property_payment or property_component:
        payment_status = "not_collected"
    else:
        payment_status = "unknown"

    if (explicit_property_payment or property_component) and paid_component:
        collection_model = "hybrid"
    elif explicit_property_payment or property_component:
        collection_model = "property_collect"
    elif paid_component or payment_status == "paid":
        collection_model = "agoda_collect"
    elif explicit_scheduled_payment:
        collection_model = "agoda_collect"
    else:
        collection_model = "unknown"

    if "partially refunded" in text or re.search(r"부분\s*환불|일부\s*환불", text):
        refund_status = "partial"
    elif explicit_refund:
        refund_status = "full_or_unspecified"
    else:
        refund_status = "none_displayed"
    return {
        "reservation_status": reservation_status,
        "payment_status": payment_status,
        "collection_model": collection_model,
        "refund_status": refund_status,
    }


def _canonical_card_type(value: str | None) -> str | None:
    if value is None:
        return None
    compact = re.sub(r"\s+", "", value).casefold()
    aliases = {
        "비자": "Visa",
        "visa": "Visa",
        "마스터카드": "MasterCard",
        "mastercard": "MasterCard",
        "아메리칸익스프레스": "American Express",
        "americanexpress": "American Express",
        "amex": "American Express",
        "jcb": "JCB",
        "unionpay": "UnionPay",
    }
    return aliases.get(compact, re.sub(r"\s+", "", value))


def _parse_card(values: Sequence[str], collection_model: str) -> dict[str, str | None]:
    card_type = _value_after(values, CARD_TYPE_LABELS)
    if card_type is None:
        for value in values:
            issuer = CARD_ISSUER_RE.search(value)
            if issuer:
                card_type = _canonical_card_type(issuer.group(1))
                break
    card_type = _canonical_card_type(card_type)
    card4_candidates: list[str] = []
    card_number_labels = {label.casefold() for label in CARD_NUMBER_LABELS}
    for index, value in enumerate(values):
        if value.strip().casefold() not in card_number_labels:
            continue
        for candidate in values[index + 1 : index + 4]:
            match = CARD4_RE.search(candidate)
            if match:
                card4_candidates.append(match.group("masked") or match.group("ending"))
    # Scan the whole attested detail scope as well.  A second payment method
    # can be rendered outside the first card-number label's local DOM window;
    # silently accepting only the first card would make card matching unsafe.
    for value in values:
        match = CARD4_RE.search(value)
        if match:
            card4_candidates.append(match.group("masked") or match.group("ending"))
    unique_card4 = sorted(set(card4_candidates))
    if len(unique_card4) > 1:
        raise DetailParseError("card4_ambiguous")
    card4 = unique_card4[0] if unique_card4 else None
    if collection_model == "property_collect":
        card_role = "guarantee_card" if card4 else "not_displayed"
    elif collection_model in {"agoda_collect", "hybrid"}:
        card_role = "payment_or_guarantee_unresolved" if card4 else "not_displayed"
    else:
        card_role = "unknown"
    return {
        "card_type": card_type,
        "card4": card4,
        "card4_sha256": _sha256_text(card4) if card4 else None,
        "card_role": card_role,
    }


def _extract_reference_code(
    values: Sequence[str], *, booking_id: str | None = None
) -> str | None:
    candidates: list[str] = []
    reference_labels = {label.casefold() for label in REFERENCE_CODE_LABELS}
    booking_labels = {label.casefold() for label in BOOKING_ID_LABELS}
    for index, value in enumerate(values):
        if value.strip().casefold() in reference_labels:
            for candidate in values[index + 1 : index + 4]:
                if candidate.strip().casefold() in reference_labels | booking_labels:
                    break
                normalized_candidate = re.sub(r"\s+", "", candidate)
                if re.fullmatch(r"\d{6,20}", normalized_candidate):
                    if normalized_candidate != booking_id:
                        candidates.append(normalized_candidate)
                    break
        inline = re.search(
            r"(?:reference\s*code|참조\s*코드|참조코드)\D*(\d{6,20})",
            value,
            re.IGNORECASE,
        )
        if inline:
            if inline.group(1) != booking_id:
                candidates.append(inline.group(1))
    unique = sorted(set(candidates))
    if len(unique) > 1:
        raise DetailParseError("reference_code_ambiguous")
    return unique[0] if unique else None


def _parse_detail_tree(tree: str, source: SourceBooking) -> dict[str, Any]:
    lowered = tree.casefold()
    if any(
        marker in lowered
        for marker in (
            "something went wrong",
            "unable to load",
            "network error",
            "access denied",
            "captcha",
            "sign in to your account",
        )
    ):
        raise DetailLoadError("detail_error_or_authentication_page")
    values = _visible_text_values(tree)
    if not values:
        raise DetailParseError("detail_visible_values_missing")
    booking_id_labels = [
        index
        for index, value in enumerate(values)
        if value.strip().casefold()
        in {label.casefold() for label in BOOKING_ID_LABELS}
    ]
    booking_id_candidates: list[str] = []
    for booking_id_index in booking_id_labels:
        for value in values[booking_id_index + 1 : booking_id_index + 4]:
            booking_id_candidates.extend(
                re.findall(r"(?<!\d)\d{9,}(?!\d)", value)
            )
    for value in values:
        if re.search(
            r"\bbooking\s*id\b|예약\s*(?:번호|id)",
            value,
            re.IGNORECASE,
        ):
            booking_id_candidates.extend(
                re.findall(r"(?<!\d)\d{9,}(?!\d)", value)
            )
    exact_booking_id_pattern = re.compile(
        rf"(?<!\d){re.escape(source.booking_id)}(?!\d)"
    )
    exact_booking_id_count = sum(
        exact_booking_id_pattern.search(value) is not None for value in values
    )
    if exact_booking_id_count == 0:
        raise DetailVerifyError("detail_booking_id_mismatch")
    if any(candidate != source.booking_id for candidate in booking_id_candidates):
        raise DetailVerifyError("detail_booking_id_label_ambiguous")
    payment_information_present = any(
        value.strip().casefold()
        in {label.casefold() for label in PAYMENT_INFORMATION_LABELS}
        for value in values
    )
    reference_code = _extract_reference_code(values, booking_id=source.booking_id)
    detail_service_start_on, detail_service_end_on = _detail_service_period(values)
    if (
        source.service_start_on
        and source.service_start_on != detail_service_start_on
    ) or (
        source.service_end_on
        and source.service_end_on != detail_service_end_on
    ):
        raise DetailVerifyError("detail_service_period_mismatch")

    components = _extract_price_components(values)
    visible_money_value_count = sum(
        _parse_money(value) is not None for value in values
    )
    gross = _single_component(components, "gross_total")
    paid_today = _single_component(components, "paid_today")
    property_due = _single_component(components, "property_due")
    axes = _status_axes(values, components)
    if not payment_information_present or gross is None:
        if visible_money_value_count:
            raise DetailParseError("partial_price_evidence_without_gross")
        cancelled_source = (
            source.tab_name == "Cancelled"
            and source.reservation_status
            in TERMINAL_SOURCE_RESERVATION_STATUSES
        )
        if not cancelled_source:
            raise DetailParseError(
                "payment_information_missing"
                if not payment_information_present
                else "gross_total_missing"
            )
        detail_reservation_status = axes["reservation_status"]
        if detail_reservation_status in {"cancelled", "unknown"}:
            observation_kind = NO_PRICE_OBSERVATION_KIND
        elif detail_reservation_status in {"confirmed", "completed"}:
            # Agoda's Cancelled list can open a detail view whose reservation
            # headline still says Confirmed/Completed while exposing no money
            # at all.  Preserve that contradiction as its own non-final,
            # non-matchable observation instead of retrying forever or
            # pretending that the detail status agrees with the list.
            observation_kind = STATUS_CONFLICT_OBSERVATION_KIND
        else:  # defensive: _status_axes currently emits only these states.
            raise DetailParseError("terminal_detail_status_unsupported")
        if (
            source.service_start_on is None
            or source.service_end_on is None
            or source.service_start_on != detail_service_start_on
            or source.service_end_on != detail_service_end_on
        ):
            raise DetailVerifyError(
                "terminal_observation_requires_exact_source_service_period"
            )
        card = _parse_card(values, axes["collection_model"])
        observation = {
            "capture_kind": observation_kind,
            "booking_id_sha256": source.booking_id_sha256,
            "reference_code": reference_code,
            "booking_pseudonym_hmac": source.booking_pseudonym_hmac,
            "tab_name": source.tab_name,
            "page_no": source.page_no,
            "card_position": source.card_position,
            "list_card_sha256": source.list_card_sha256,
            "service_start_on": source.service_start_on,
            "service_end_on": source.service_end_on,
            "source_scope_status": source.source_scope_status,
            "detail_service_start_on": detail_service_start_on,
            "detail_service_end_on": detail_service_end_on,
            "detail_scope_status": _detail_scope_status(
                detail_service_start_on, detail_service_end_on
            ),
            "reservation_status": "cancelled",
            "detail_reservation_status": detail_reservation_status,
            "payment_status": axes["payment_status"],
            "collection_model": axes["collection_model"],
            "refund_status": axes["refund_status"],
            "payment_information_present": int(payment_information_present),
            "gross_total_present": 0,
            "visible_money_value_count": 0,
            "card_type": card["card_type"],
            "card4_sha256": card["card4_sha256"],
            "card_role": card["card_role"],
            "amount_matching_eligible": 0,
            "unresolved_competitor": 1,
        }
        semantic_observation = {
            key: value
            for key, value in observation.items()
            if key not in {"page_no", "card_position"}
        }
        return {
            **observation,
            "booking_id": source.booking_id,
            "card4": card["card4"],
            "semantic_detail_sha256": _sha256_text(
                _canonical_json(semantic_observation)
            ),
        }

    if axes["payment_status"] == "unknown" or axes["collection_model"] == "unknown":
        raise DetailParseError("payment_state_ambiguous")

    room_count: int | None = None
    rooms_value = _value_after(values, {"Rooms", "객실", "객실 수"})
    if rooms_value and rooms_value.isdigit():
        room_count = int(rooms_value)
    nights: int | None = None
    for value in values:
        match = ROOM_NIGHT_RE.search(value) or KOREAN_ROOM_NIGHT_RE.search(value)
        if match:
            if match.re is KOREAN_ROOM_NIGHT_RE:
                component_rooms = int(match.group(1) or match.group(2))
                nights = int(match.group(3))
            else:
                component_rooms, nights = int(match.group(1)), int(match.group(2))
            if room_count is None:
                room_count = component_rooms
            elif room_count != component_rooms:
                raise DetailParseError("room_count_ambiguous")
            break
        if room_count is None:
            inline_room = ROOM_COUNT_INLINE_RE.search(value)
            if inline_room:
                room_count = int(inline_room.group(1))
    if nights is None:
        derived_nights = (
            date.fromisoformat(detail_service_end_on)
            - date.fromisoformat(detail_service_start_on)
        ).days
        if derived_nights >= 0:
            nights = derived_nights

    has_local_tax = int(
        any(
            re.search(
                r"\b(city|local|accommodation) tax\b|도시세|현지\s*세금|숙박세",
                value,
                re.I,
            )
            and re.search(
                r"\b(property|check-in|arrival)\b|숙소|체크인|도착",
                value,
                re.I,
            )
            for value in values
        )
    )
    local_tax = next(
        (
            component
            for component in components
            if component["kind"] == "tax"
            and re.search(
                r"\b(city|local|accommodation) tax\b|도시세|현지\s*세금|숙박세",
                component["label_normalized"],
                re.I,
            )
        ),
        None,
    )
    card = _parse_card(values, axes["collection_model"])

    payment_events: list[dict[str, Any]] = []
    for component in components:
        if component["kind"] not in {"charge", "refund", "chargeback"}:
            continue
        label_dates = _parse_dates([component["label_normalized"]])
        payment_events.append(
            {
                "event_kind": component["kind"],
                "event_on": next(iter(label_dates), None),
                "currency": component["currency"],
                "decimal_text": component["decimal_text"],
                "minor_units": component["minor_units"],
                "scale": component["scale"],
                "card4_sha256": card["card4_sha256"],
                "evidence_label": component["label_normalized"],
            }
        )
    normalized_payload = {
        "capture_kind": "price_evidence",
        "booking_id_sha256": source.booking_id_sha256,
        "booking_pseudonym_hmac": source.booking_pseudonym_hmac,
        "tab_name": source.tab_name,
        "page_no": source.page_no,
        "card_position": source.card_position,
        "list_card_sha256": source.list_card_sha256,
        "service_start_on": source.service_start_on,
        "service_end_on": source.service_end_on,
        "source_scope_status": source.source_scope_status,
        "reference_code": reference_code,
        "detail_service_start_on": detail_service_start_on,
        "detail_service_end_on": detail_service_end_on,
        "detail_scope_status": _detail_scope_status(
            detail_service_start_on, detail_service_end_on
        ),
        "room_count": room_count,
        "nights": nights,
        **axes,
        "has_local_tax": has_local_tax,
        "gross_total": gross,
        "paid_today": paid_today,
        "property_due": property_due,
        "local_tax": local_tax,
        "price_components": components,
        "payment_events": payment_events,
        "card_type": card["card_type"],
        "card4_sha256": card["card4_sha256"],
        "card_role": card["card_role"],
    }
    semantic_payload = {
        key: value
        for key, value in normalized_payload.items()
        if key not in {"page_no", "card_position"}
    }
    return {
        **normalized_payload,
        "booking_id": source.booking_id,
        "card4": card["card4"],
        "semantic_detail_sha256": _sha256_text(_canonical_json(semantic_payload)),
    }


def _ordered_membership_hash(bookings: Iterable[SourceBooking]) -> str:
    return _sha256_text(_canonical_json([booking.membership_tuple() for booking in bookings]))


def _set_membership_hash(bookings: Iterable[SourceBooking]) -> str:
    return _sha256_text(
        _canonical_json(sorted(booking.membership_tuple() for booking in bookings))
    )


def _load_private_hmac_key(path: Path) -> tuple[bytes, str]:
    key_path = _require_tmp(path, must_exist=True)
    if key_path.is_symlink() or (
        os.name != "nt" and (key_path.stat().st_mode & 0o077) != 0
    ):
        raise CaptureError("pseudonym_key_permissions_invalid")
    key = key_path.read_bytes()
    if len(key) < 32:
        raise CaptureError("pseudonym_key_too_short")
    key_id = hashlib.sha256(key).hexdigest()[:16]
    return key, f"agoda-hmac-v1:{key_id}"


def _load_source_snapshot(path: Path, hmac_key_file: Path) -> SourceSnapshot:
    """Load a sealed converged three-tab census, never the stale r3 set."""
    try:
        from tools.agoda_portal_full_survey import (
            TAB_NAMES,
            _convergence_manifest,
        )
    except ModuleNotFoundError:
        from agoda_portal_full_survey import (
            TAB_NAMES,
            _convergence_manifest,
        )

    source_path = _require_tmp(path, must_exist=True)
    key, key_id = _load_private_hmac_key(hmac_key_file)
    before_hash = _file_sha256(source_path)
    # ``sqlite3.Connection``'s context manager commits/rolls back but does
    # not close the handle.  A read-only immutable handle left alive here
    # keeps the source file locked on Windows and also makes later VSS/file
    # cleanup nondeterministic.  ``closing`` gives the read-only census load
    # an explicit lifetime.
    with closing(_immutable_connection(source_path)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise CaptureError("source_census_integrity_failed")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required_tables = {
            "survey_run_manifest",
            "survey_pages",
            "survey_booking_cards",
            "survey_canonical_bookings",
        }
        if not required_tables.issubset(tables):
            raise CaptureError("source_is_not_fresh_three_tab_census")
        manifests = connection.execute(
            "SELECT * FROM survey_run_manifest"
        ).fetchall()
        if len(manifests) != 1:
            raise CaptureError("source_census_manifest_invalid")
        manifest = manifests[0]
        pass_count = int(manifest["verification_pass_count"])
        if (
            int(manifest["tab_count"]) != 3
            or pass_count < 2
            or str(manifest["pseudonym_key_id"]) != key_id
        ):
            raise CaptureError("source_census_contract_invalid")

        try:
            expected_tab_totals = json.loads(
                str(manifest["expected_tab_totals_json"])
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CaptureError("source_census_expected_totals_invalid") from exc
        if (
            set(expected_tab_totals) != set(TAB_NAMES)
            or any(
                not isinstance(expected_tab_totals[tab], int)
                or expected_tab_totals[tab] < 0
                for tab in TAB_NAMES
            )
        ):
            raise CaptureError("source_census_expected_totals_invalid")

        all_page_rows = connection.execute(
            "SELECT * FROM survey_pages ORDER BY pass_no,tab_name,page_no"
        ).fetchall()
        all_card_rows = connection.execute(
            "SELECT * FROM survey_booking_cards "
            "ORDER BY pass_no,tab_name,page_no,card_position"
        ).fetchall()
        if (
            len(all_page_rows) != int(manifest["captured_page_count"])
            or len(all_card_rows) != int(manifest["captured_card_count"])
        ):
            raise CaptureError("source_census_manifest_count_mismatch")
        pass_numbers = sorted({int(row["pass_no"]) for row in all_page_rows})
        if pass_numbers != list(range(1, pass_count + 1)):
            raise CaptureError("source_census_pass_sequence_invalid")
        if any(int(row["duplicate_occurrence_count"]) != 0 for row in all_page_rows):
            raise CaptureError("source_census_duplicate_within_page")
        for pass_no in pass_numbers:
            rows = [row for row in all_page_rows if int(row["pass_no"]) == pass_no]
            if {str(row["tab_name"]) for row in rows} != set(TAB_NAMES):
                raise CaptureError("source_census_three_tab_population_missing")
            for tab_name in TAB_NAMES:
                tab_rows = [row for row in rows if str(row["tab_name"]) == tab_name]
                pages = [int(row["page_no"]) for row in tab_rows]
                if pages != list(range(1, len(pages) + 1)):
                    raise CaptureError("source_census_page_sequence_invalid")
                if sum(int(row["card_count"]) for row in tab_rows) != int(
                    expected_tab_totals[tab_name]
                ):
                    raise CaptureError("source_census_expected_tab_total_mismatch")

        observed_duplicate_count = sum(
            len(rows)
            - len({str(row["booking_pseudonym_hmac"]) for row in rows})
            for pass_no in pass_numbers
            for rows in [[
                row for row in all_card_rows if int(row["pass_no"]) == pass_no
            ]]
        )
        if observed_duplicate_count != int(manifest["duplicate_occurrence_count"]):
            raise CaptureError("source_census_duplicate_count_mismatch")

        canonical_rows = connection.execute(
            "SELECT * FROM survey_canonical_bookings"
        ).fetchall()
        canonical_rows = sorted(
            canonical_rows,
            key=lambda row: (
                TAB_NAMES.index(str(row["tab_name"])),
                str(row["booking_pseudonym_hmac"]),
            ),
        )
        if (
            not canonical_rows
            or len(canonical_rows) != int(manifest["canonical_booking_count"])
            or len(canonical_rows) != sum(int(expected_tab_totals[tab]) for tab in TAB_NAMES)
        ):
            raise CaptureError("source_census_canonical_count_mismatch")

        raw_ids = [str(row["booking_id"]) for row in canonical_rows]
        pseudonyms = [str(row["booking_pseudonym_hmac"]) for row in canonical_rows]
        if len(set(raw_ids)) != len(raw_ids) or len(set(pseudonyms)) != len(pseudonyms):
            raise CaptureError("source_census_booking_membership_not_unique")
        for row in canonical_rows:
            expected = hmac.new(
                key, str(row["booking_id"]).encode("utf-8"), hashlib.sha256
            ).hexdigest()
            if expected != str(row["booking_pseudonym_hmac"]):
                raise CaptureError("source_census_booking_hmac_mismatch")
            semantic_payload = {
                "tab_name": str(row["tab_name"]),
                "booking_pseudonym_hmac": str(row["booking_pseudonym_hmac"]),
                "service_start_on": row["service_start_on"],
                "service_end_on": row["service_end_on"],
                "scope_status": str(row["scope_status"]),
                "reservation_status": str(row["reservation_status"]),
                "action_kind": "manage_booking",
            }
            if _sha256_text(_canonical_json(semantic_payload)) != str(
                row["booking_semantic_sha256"]
            ):
                raise CaptureError("source_census_booking_semantic_hash_mismatch")
            stable_first_pass = int(row["first_pass_no"])
            if stable_first_pass < 1 or stable_first_pass > pass_count:
                raise CaptureError("source_census_stable_pass_invalid")
            observations = [
                observed for observed in all_card_rows
                if str(observed["booking_pseudonym_hmac"])
                == str(row["booking_pseudonym_hmac"])
                and int(observed["pass_no"]) >= stable_first_pass
            ]
            if (
                len(observations) != int(row["observation_count"])
                or {str(item["booking_id"]) for item in observations}
                != {str(row["booking_id"])}
                or {str(item["booking_semantic_sha256"]) for item in observations}
                != {str(row["booking_semantic_sha256"])}
            ):
                raise CaptureError("source_census_observation_lineage_mismatch")

        scope_counts = {
            scope: sum(str(row["scope_status"]) == scope for row in canonical_rows)
            for scope in (
                "target_2026_overlap", "year_unknown", "outside_2026"
            )
        }
        if scope_counts != {
            "target_2026_overlap": int(manifest["target_2026_count"]),
            "year_unknown": int(manifest["year_unknown_count"]),
            "outside_2026": int(manifest["outside_2026_count"]),
        }:
            raise CaptureError("source_census_scope_count_mismatch")
        canonical_manifest_rows = [dict(row) for row in canonical_rows]
        if _convergence_manifest(
            expected_tab_totals, canonical_manifest_rows
        ) != str(manifest["pass_manifest_sha256"]):
            raise CaptureError("source_census_convergence_hash_mismatch")

        selected_rows = []
        for row in canonical_rows:
            scope = str(row["scope_status"])
            end_on = (
                date.fromisoformat(str(row["service_end_on"]))
                if row["service_end_on"] is not None
                else None
            )
            if scope in TARGET_SOURCE_SCOPES or (
                end_on is not None and end_on >= COMPETITOR_SERVICE_END_FLOOR
            ):
                selected_rows.append(row)
        expected_target_count = int(manifest["target_2026_count"])
        expected_unknown_count = int(manifest["year_unknown_count"])
        if sum(
            str(row["scope_status"]) == "target_2026_overlap"
            for row in selected_rows
        ) != expected_target_count or sum(
            str(row["scope_status"]) == "year_unknown"
            for row in selected_rows
        ) != expected_unknown_count:
            raise CaptureError("source_census_selected_count_mismatch")
        bookings = tuple(
            SourceBooking(
                tab_name=str(row["tab_name"]),
                page_no=int(row["first_page_no"]),
                card_position=int(row["first_card_position"]),
                booking_id=str(row["booking_id"]),
                booking_id_sha256=_sha256_text(str(row["booking_id"])),
                booking_pseudonym_hmac=str(row["booking_pseudonym_hmac"]),
                service_start_on=(
                    str(row["service_start_on"])
                    if row["service_start_on"] is not None else None
                ),
                service_end_on=(
                    str(row["service_end_on"])
                    if row["service_end_on"] is not None else None
                ),
                source_scope_status=str(row["scope_status"]),
                reservation_status=str(row["reservation_status"]),
                list_card_sha256=str(row["booking_semantic_sha256"]),
            )
            for row in selected_rows
        )
        if any(
            booking.source_scope_status == "target_2026_overlap"
            and (not booking.service_start_on or not booking.service_end_on)
            for booking in bookings
        ):
            raise CaptureError("source_target_period_missing")

        stable_first_passes = {
            int(row["first_pass_no"]) for row in canonical_rows
        }
        if len(stable_first_passes) != 1:
            raise CaptureError("source_census_stable_pass_inconsistent")
        stable_first_pass = stable_first_passes.pop()
        first_pass_pages = [
            row for row in all_page_rows
            if int(row["pass_no"]) == stable_first_pass
        ]
        page_manifest = {
            (str(row["tab_name"]), int(row["page_no"])): {
                "tab_name": str(row["tab_name"]),
                "page_no": int(row["page_no"]),
                "card_count": int(row["card_count"]),
                "target_2026_count": int(row["target_2026_count"]),
                "year_unknown_count": int(row["year_unknown_count"]),
                "ordered_page_sha256": str(row["ordered_page_sha256"]),
                "set_page_sha256": str(row["set_page_sha256"]),
            }
            for row in first_pass_pages
        }

    after_hash = _file_sha256(source_path)
    if before_hash != after_hash:
        raise CaptureError("source_changed_during_verification")
    return SourceSnapshot(
        path=source_path,
        file_sha256=before_hash,
        source_run_id=str(manifest["run_id"]),
        source_capture_set_sha256=str(manifest["pass_manifest_sha256"]),
        membership_ordered_sha256=_ordered_membership_hash(bookings),
        membership_set_sha256=_set_membership_hash(bookings),
        bookings=bookings,
        page_manifest=page_manifest,
        population_count=len(canonical_rows),
        pseudonym_key_id=key_id,
        all_booking_semantics=tuple(
            (
                str(row["booking_pseudonym_hmac"]),
                str(row["booking_semantic_sha256"]),
            )
            for row in canonical_rows
        ),
        tab_totals=tuple(
            (tab_name, int(expected_tab_totals[tab_name]))
            for tab_name in TAB_NAMES
        ),
        target_2026_count=expected_target_count,
        competitor_count=len(selected_rows) - expected_target_count,
    )


def _work_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = DELETE;
        PRAGMA synchronous = FULL;
        CREATE TABLE capture_run_manifest (
            run_id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            source_file_sha256 TEXT NOT NULL,
            source_run_id TEXT NOT NULL,
            source_capture_set_sha256 TEXT NOT NULL,
            membership_ordered_sha256 TEXT NOT NULL,
            membership_set_sha256 TEXT NOT NULL,
            source_population_count INTEGER NOT NULL CHECK (source_population_count > 0),
            target_count INTEGER NOT NULL CHECK (target_count > 0),
            target_2026_count INTEGER NOT NULL CHECK (target_2026_count > 0),
            competitor_count INTEGER NOT NULL CHECK (competitor_count >= 0),
            target_year INTEGER NOT NULL CHECK (target_year = 2026),
            pseudonym_key_id TEXT NOT NULL,
            app_name TEXT NOT NULL,
            window_id INTEGER NOT NULL,
            epoch_status TEXT NOT NULL CHECK (
                epoch_status IN ('capturing', 'failed_drift', 'complete')
            ),
            created_at_utc TEXT NOT NULL,
            completed_at_utc TEXT,
            final_revalidation_sha256 TEXT,
            final_revalidated_at_utc TEXT
        );
        CREATE TABLE capture_attempts (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            booking_id_sha256 TEXT NOT NULL,
            tab_name TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            card_position INTEGER NOT NULL,
            attempt_no INTEGER NOT NULL,
            started_at_utc TEXT NOT NULL,
            finished_at_utc TEXT,
            capture_status TEXT NOT NULL CHECK (
                capture_status IN (
                    'started', 'success', 'failed_load', 'failed_parse',
                    'failed_verify', 'failed_drift'
                )
            ),
            failure_code TEXT,
            semantic_detail_sha256 TEXT,
            UNIQUE(run_id, booking_id_sha256, attempt_no)
        );
        CREATE TABLE booking_detail_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            booking_id TEXT NOT NULL,
            reference_code TEXT,
            booking_id_sha256 TEXT NOT NULL,
            booking_pseudonym_hmac TEXT NOT NULL,
            tab_name TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            card_position INTEGER NOT NULL,
            list_card_sha256 TEXT NOT NULL,
            source_service_start_on TEXT,
            source_service_end_on TEXT,
            source_scope_status TEXT NOT NULL,
            source_reservation_status TEXT NOT NULL,
            detail_service_start_on TEXT NOT NULL,
            detail_service_end_on TEXT NOT NULL,
            detail_scope_status TEXT NOT NULL,
            room_count INTEGER,
            nights INTEGER,
            reservation_status TEXT NOT NULL,
            payment_status TEXT NOT NULL,
            collection_model TEXT NOT NULL,
            refund_status TEXT NOT NULL,
            payment_schedule_json TEXT NOT NULL,
            has_local_tax INTEGER NOT NULL CHECK (has_local_tax IN (0, 1)),
            card_type TEXT,
            card4 TEXT,
            card4_sha256 TEXT,
            card_role TEXT NOT NULL,
            semantic_detail_sha256 TEXT NOT NULL,
            snapshot_version INTEGER NOT NULL,
            captured_at_utc TEXT NOT NULL,
            UNIQUE(run_id, booking_id_sha256, snapshot_version),
            UNIQUE(run_id, booking_id_sha256, semantic_detail_sha256)
        );
        CREATE TABLE price_components (
            snapshot_id INTEGER NOT NULL,
            ordinal INTEGER NOT NULL,
            component_kind TEXT NOT NULL,
            label_normalized TEXT NOT NULL,
            currency TEXT NOT NULL,
            amount_decimal_text TEXT NOT NULL,
            amount_minor_units INTEGER NOT NULL,
            currency_scale INTEGER NOT NULL,
            PRIMARY KEY(snapshot_id, ordinal),
            FOREIGN KEY(snapshot_id) REFERENCES booking_detail_snapshots(snapshot_id)
        );
        CREATE TABLE payment_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            event_kind TEXT NOT NULL CHECK (
                event_kind IN ('charge', 'refund', 'chargeback')
            ),
            event_on TEXT,
            currency TEXT NOT NULL,
            amount_decimal_text TEXT NOT NULL,
            amount_minor_units INTEGER NOT NULL,
            currency_scale INTEGER NOT NULL,
            card4_sha256 TEXT,
            evidence_label TEXT NOT NULL,
            FOREIGN KEY(snapshot_id) REFERENCES booking_detail_snapshots(snapshot_id)
        );
        CREATE TABLE booking_detail_observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            booking_id_sha256 TEXT NOT NULL,
            reference_code TEXT,
            booking_pseudonym_hmac TEXT NOT NULL,
            tab_name TEXT NOT NULL CHECK(tab_name = 'Cancelled'),
            page_no INTEGER NOT NULL,
            card_position INTEGER NOT NULL,
            list_card_sha256 TEXT NOT NULL,
            list_attestation_id INTEGER NOT NULL,
            attested_ordered_membership_sha256 TEXT NOT NULL,
            attested_set_membership_sha256 TEXT NOT NULL,
            attested_source_page_set_sha256 TEXT NOT NULL,
            source_service_start_on TEXT,
            source_service_end_on TEXT,
            source_scope_status TEXT NOT NULL,
            source_reservation_status TEXT NOT NULL,
            detail_service_start_on TEXT NOT NULL,
            detail_service_end_on TEXT NOT NULL,
            detail_scope_status TEXT NOT NULL,
            reservation_status TEXT NOT NULL CHECK(reservation_status = 'cancelled'),
            detail_reservation_status TEXT NOT NULL CHECK(
                detail_reservation_status IN (
                    'cancelled', 'unknown', 'confirmed', 'completed'
                )
            ),
            payment_status TEXT NOT NULL,
            collection_model TEXT NOT NULL,
            refund_status TEXT NOT NULL,
            observation_kind TEXT NOT NULL CHECK(
                observation_kind IN (
                    'price_evidence_not_displayed',
                    'cancelled_list_detail_status_conflict_no_price'
                )
            ),
            payment_information_present INTEGER NOT NULL CHECK(
                payment_information_present IN (0, 1)
            ),
            gross_total_present INTEGER NOT NULL CHECK(gross_total_present = 0),
            visible_money_value_count INTEGER NOT NULL CHECK(
                visible_money_value_count = 0
            ),
            card_type TEXT,
            card4 TEXT,
            card4_sha256 TEXT,
            card_role TEXT NOT NULL,
            amount_matching_eligible INTEGER NOT NULL CHECK(
                amount_matching_eligible = 0
            ),
            unresolved_competitor INTEGER NOT NULL CHECK(
                unresolved_competitor = 1
            ),
            semantic_detail_sha256 TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            UNIQUE(run_id, booking_id_sha256),
            UNIQUE(run_id, booking_id_sha256, semantic_detail_sha256)
        );
        CREATE TABLE page_attestations (
            attestation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            tab_name TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            phase TEXT NOT NULL CHECK (phase IN ('before_click', 'after_return')),
            expected_selected_page INTEGER NOT NULL,
            observed_selected_page INTEGER,
            ordered_membership_sha256 TEXT NOT NULL,
            set_membership_sha256 TEXT NOT NULL,
            source_page_set_sha256 TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL
        );
        CREATE TABLE page_attestation_members (
            attestation_id INTEGER NOT NULL,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 1),
            booking_pseudonym_hmac TEXT NOT NULL,
            list_card_sha256 TEXT NOT NULL,
            PRIMARY KEY(attestation_id, ordinal),
            UNIQUE(attestation_id, booking_pseudonym_hmac),
            FOREIGN KEY(attestation_id) REFERENCES page_attestations(attestation_id)
        );
        CREATE TABLE live_census_deltas (
            delta_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            tab_name TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            phase TEXT NOT NULL CHECK (phase IN ('before_click', 'after_return')),
            booking_pseudonym_hmac TEXT NOT NULL,
            list_card_sha256 TEXT NOT NULL,
            delta_kind TEXT NOT NULL CHECK (delta_kind = 'post_census_booking'),
            observed_at_utc TEXT NOT NULL,
            UNIQUE(run_id, booking_pseudonym_hmac, list_card_sha256)
        );
        CREATE TABLE observation_schema_migration_audit (
            migration_id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_kind TEXT NOT NULL UNIQUE,
            invalidated_observation_count INTEGER NOT NULL CHECK(
                invalidated_observation_count >= 0
            ),
            applied_at_utc TEXT NOT NULL
        );
        CREATE TABLE window_rebind_audit (
            rebind_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            old_window_id INTEGER NOT NULL,
            new_window_id INTEGER NOT NULL,
            reason_code TEXT NOT NULL,
            rebound_at_utc TEXT NOT NULL
        );
        CREATE INDEX idx_attempt_booking ON capture_attempts(run_id, booking_id_sha256);
        CREATE INDEX idx_snapshot_booking ON booking_detail_snapshots(run_id, booking_id_sha256);
        CREATE INDEX idx_price_kind ON price_components(component_kind, currency, amount_minor_units);
        CREATE INDEX idx_observation_booking
        ON booking_detail_observations(run_id, booking_id_sha256);
        CREATE INDEX idx_window_rebind_run ON window_rebind_audit(run_id);
        """
    )


def _ensure_snapshot_schema(connection: sqlite3.Connection) -> None:
    """Backfill optional detail identifiers on resumable work databases."""
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(booking_detail_snapshots)"
        )
    }
    if "reference_code" not in columns:
        connection.execute(
            "ALTER TABLE booking_detail_snapshots ADD COLUMN reference_code TEXT"
        )


def _ensure_detail_observation_schema(connection: sqlite3.Connection) -> None:
    """Add the terminal no-price observation lane to resumable work DBs."""
    existing_observation = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='booking_detail_observations'"
    ).fetchone()
    existing_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(booking_detail_observations)"
        )
    }
    v3_contract_columns = {
        "detail_reservation_status",
        "list_attestation_id",
        "visible_money_value_count",
        "attested_ordered_membership_sha256",
        "attested_set_membership_sha256",
        "attested_source_page_set_sha256",
    }
    if (
        existing_observation is not None
        and v3_contract_columns <= existing_columns
        and STATUS_CONFLICT_OBSERVATION_KIND
        not in str(existing_observation[0] or "")
    ):
        # SQLite cannot widen a CHECK constraint in place.  Existing terminal
        # observations are derived evidence and cannot be safely reinterpreted
        # under the new explicit list/detail-status-conflict lane, so invalidate
        # only those rows and return their bookings to the capture queue.
        invalidated_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_observations"
            ).fetchone()[0]
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS observation_schema_migration_audit (
                migration_id INTEGER PRIMARY KEY AUTOINCREMENT,
                migration_kind TEXT NOT NULL UNIQUE,
                invalidated_observation_count INTEGER NOT NULL CHECK(
                    invalidated_observation_count >= 0
                ),
                applied_at_utc TEXT NOT NULL
            )
            """
        )
        connection.execute("DROP TABLE booking_detail_observations")
        connection.execute(
            """
            INSERT OR IGNORE INTO observation_schema_migration_audit(
                migration_kind, invalidated_observation_count, applied_at_utc
            ) VALUES ('terminal_status_conflict_contract_v4', ?, ?)
            """,
            (invalidated_count, _utc_now()),
        )
    had_attestation_members = bool(
        connection.execute(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='page_attestation_members')"
        ).fetchone()[0]
    )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS booking_detail_observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            booking_id_sha256 TEXT NOT NULL,
            reference_code TEXT,
            booking_pseudonym_hmac TEXT NOT NULL,
            tab_name TEXT NOT NULL CHECK(tab_name = 'Cancelled'),
            page_no INTEGER NOT NULL,
            card_position INTEGER NOT NULL,
            list_card_sha256 TEXT NOT NULL,
            list_attestation_id INTEGER NOT NULL,
            attested_ordered_membership_sha256 TEXT NOT NULL,
            attested_set_membership_sha256 TEXT NOT NULL,
            attested_source_page_set_sha256 TEXT NOT NULL,
            source_service_start_on TEXT,
            source_service_end_on TEXT,
            source_scope_status TEXT NOT NULL,
            source_reservation_status TEXT NOT NULL,
            detail_service_start_on TEXT NOT NULL,
            detail_service_end_on TEXT NOT NULL,
            detail_scope_status TEXT NOT NULL,
            reservation_status TEXT NOT NULL CHECK(reservation_status = 'cancelled'),
            detail_reservation_status TEXT NOT NULL CHECK(
                detail_reservation_status IN (
                    'cancelled', 'unknown', 'confirmed', 'completed'
                )
            ),
            payment_status TEXT NOT NULL,
            collection_model TEXT NOT NULL,
            refund_status TEXT NOT NULL,
            observation_kind TEXT NOT NULL CHECK(
                observation_kind IN (
                    'price_evidence_not_displayed',
                    'cancelled_list_detail_status_conflict_no_price'
                )
            ),
            payment_information_present INTEGER NOT NULL CHECK(
                payment_information_present IN (0, 1)
            ),
            gross_total_present INTEGER NOT NULL CHECK(gross_total_present = 0),
            visible_money_value_count INTEGER NOT NULL CHECK(
                visible_money_value_count = 0
            ),
            card_type TEXT,
            card4 TEXT,
            card4_sha256 TEXT,
            card_role TEXT NOT NULL,
            amount_matching_eligible INTEGER NOT NULL CHECK(
                amount_matching_eligible = 0
            ),
            unresolved_competitor INTEGER NOT NULL CHECK(
                unresolved_competitor = 1
            ),
            semantic_detail_sha256 TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            UNIQUE(run_id, booking_id_sha256),
            UNIQUE(run_id, booking_id_sha256, semantic_detail_sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_observation_booking
        ON booking_detail_observations(run_id, booking_id_sha256);
        CREATE TABLE IF NOT EXISTS observation_schema_migration_audit (
            migration_id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_kind TEXT NOT NULL UNIQUE,
            invalidated_observation_count INTEGER NOT NULL CHECK(
                invalidated_observation_count >= 0
            ),
            applied_at_utc TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS page_attestation_members (
            attestation_id INTEGER NOT NULL,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 1),
            booking_pseudonym_hmac TEXT NOT NULL,
            list_card_sha256 TEXT NOT NULL,
            PRIMARY KEY(attestation_id, ordinal),
            UNIQUE(attestation_id, booking_pseudonym_hmac),
            FOREIGN KEY(attestation_id) REFERENCES page_attestations(attestation_id)
        );
        CREATE TABLE IF NOT EXISTS live_census_deltas (
            delta_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            tab_name TEXT NOT NULL,
            page_no INTEGER NOT NULL,
            phase TEXT NOT NULL CHECK (phase IN ('before_click', 'after_return')),
            booking_pseudonym_hmac TEXT NOT NULL,
            list_card_sha256 TEXT NOT NULL,
            delta_kind TEXT NOT NULL CHECK (delta_kind = 'post_census_booking'),
            observed_at_utc TEXT NOT NULL,
            UNIQUE(run_id, booking_pseudonym_hmac, list_card_sha256)
        );
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(booking_detail_observations)"
        )
    }
    migration_columns = {
        "reference_code": "TEXT",
        "detail_reservation_status": (
            "TEXT NOT NULL DEFAULT 'unknown'"
        ),
        "list_attestation_id": "INTEGER",
        "visible_money_value_count": "INTEGER NOT NULL DEFAULT 0",
        "attested_ordered_membership_sha256": "TEXT",
        "attested_set_membership_sha256": "TEXT",
        "attested_source_page_set_sha256": "TEXT",
    }
    missing_columns = [
        column for column in migration_columns if column not in columns
    ]
    if missing_columns or not had_attestation_members:
        invalidated_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM booking_detail_observations"
            ).fetchone()[0]
        )
        if invalidated_count:
            # Legacy observations cannot be cryptographically rebound to the
            # exact pre-click page attestation.  Removing only this derived
            # terminal result makes the canonical booking eligible for a
            # fresh capture; source census and successful price snapshots are
            # left untouched.
            connection.execute("DELETE FROM booking_detail_observations")
        connection.execute(
            """
            INSERT OR IGNORE INTO observation_schema_migration_audit(
                migration_kind, invalidated_observation_count, applied_at_utc
            ) VALUES ('terminal_attestation_contract_v3', ?, ?)
            """,
            (invalidated_count, _utc_now()),
        )
        for column in missing_columns:
            connection.execute(
                "ALTER TABLE booking_detail_observations "
                f"ADD COLUMN {column} {migration_columns[column]}"
            )


def _secure_create_work_db(
    path: Path,
    snapshot: SourceSnapshot,
    run_id: str,
    app: str,
    window_id: int,
) -> sqlite3.Connection:
    work_path = _require_tmp(path)
    _secure_private_parent(work_path)
    try:
        file_descriptor = os.open(work_path, os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise CaptureError("work_database_already_exists_use_resume") from exc
    os.close(file_descriptor)
    connection = sqlite3.connect(work_path)
    connection.row_factory = sqlite3.Row
    try:
        _work_schema(connection)
        connection.execute(
            """
            INSERT INTO capture_run_manifest(
                run_id, source_path, source_file_sha256, source_run_id,
                source_capture_set_sha256, membership_ordered_sha256,
                membership_set_sha256, source_population_count, target_count,
                target_2026_count, competitor_count, target_year,
                pseudonym_key_id, app_name, window_id,
                epoch_status, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2026, ?, ?, ?, 'capturing', ?)
            """,
            (
                run_id,
                str(snapshot.path),
                snapshot.file_sha256,
                snapshot.source_run_id,
                snapshot.source_capture_set_sha256,
                snapshot.membership_ordered_sha256,
                snapshot.membership_set_sha256,
                snapshot.population_count,
                len(snapshot.bookings),
                snapshot.target_2026_count,
                snapshot.competitor_count,
                snapshot.pseudonym_key_id,
                app,
                window_id,
                _utc_now(),
            ),
        )
        connection.commit()
        os.chmod(work_path, 0o600)
        return connection
    except Exception:
        connection.close()
        work_path.unlink(missing_ok=True)
        raise


def _ensure_window_rebind_audit_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS window_rebind_audit (
            rebind_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            old_window_id INTEGER NOT NULL,
            new_window_id INTEGER NOT NULL,
            reason_code TEXT NOT NULL,
            rebound_at_utc TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_window_rebind_run
        ON window_rebind_audit(run_id)
        """
    )


def _resume_work_db(
    path: Path,
    snapshot: SourceSnapshot,
    run_id: str,
    app: str | None = None,
    window_id: int | None = None,
    rebind_window: bool = False,
) -> sqlite3.Connection:
    work_path = _require_tmp(path, must_exist=True)
    if os.name != "nt" and (work_path.stat().st_mode & 0o077) != 0:
        raise CaptureError("work_database_permissions_are_not_0600")
    if rebind_window and (
        window_id is None
        or isinstance(window_id, bool)
        or not isinstance(window_id, int)
        or window_id <= 0
    ):
        raise CaptureError("invalid_rebind_window_id")
    connection = sqlite3.connect(work_path)
    connection.row_factory = sqlite3.Row
    try:
        _ensure_snapshot_schema(connection)
        _ensure_detail_observation_schema(connection)
        connection.commit()
        if rebind_window:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise CaptureError("work_database_rebind_busy") from exc
        row = connection.execute("SELECT * FROM capture_run_manifest").fetchone()
        if row is None:
            raise CaptureError("work_run_manifest_missing")
        expected_immutable = (
            run_id,
            str(snapshot.path),
            snapshot.file_sha256,
            snapshot.source_run_id,
            snapshot.source_capture_set_sha256,
            snapshot.membership_ordered_sha256,
            snapshot.membership_set_sha256,
            snapshot.population_count,
            len(snapshot.bookings),
            snapshot.target_2026_count,
            snapshot.competitor_count,
            EXPECTED_TARGET_YEAR,
            snapshot.pseudonym_key_id,
            app if app is not None else row["app_name"],
        )
        actual_immutable = (
            row["run_id"],
            row["source_path"],
            row["source_file_sha256"],
            row["source_run_id"],
            row["source_capture_set_sha256"],
            row["membership_ordered_sha256"],
            row["membership_set_sha256"],
            int(row["source_population_count"]),
            int(row["target_count"]),
            int(row["target_2026_count"]),
            int(row["competitor_count"]),
            int(row["target_year"]),
            row["pseudonym_key_id"],
            row["app_name"],
        )
        if actual_immutable != expected_immutable:
            raise CaptureError("work_database_manifest_mismatch")
        if row["epoch_status"] == "failed_drift":
            raise CaptureError("work_database_epoch_failed_drift_start_new_epoch")
        if row["epoch_status"] == "complete":
            raise CaptureError("work_database_epoch_already_complete")
        if rebind_window and row["epoch_status"] != "capturing":
            raise CaptureError("work_database_rebind_requires_capturing_epoch")

        current_window_id = int(row["window_id"])
        if window_id is not None:
            if isinstance(window_id, bool) or not isinstance(window_id, int) or window_id <= 0:
                raise CaptureError("work_database_manifest_mismatch")

            if window_id != current_window_id:
                if not rebind_window:
                    raise CaptureError("work_database_manifest_mismatch")
                _ensure_window_rebind_audit_schema(connection)
                connection.execute(
                    """
                    INSERT INTO window_rebind_audit (
                        run_id, old_window_id, new_window_id, reason_code, rebound_at_utc
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        current_window_id,
                        window_id,
                        WINDOW_REBIND_REASON,
                        _utc_now(),
                    ),
                )
                updated = connection.execute(
                    """
                    UPDATE capture_run_manifest
                    SET window_id = ?
                    WHERE run_id = ? AND window_id = ? AND epoch_status = 'capturing'
                    """,
                    (window_id, run_id, current_window_id),
                )
                if updated.rowcount != 1:
                    raise CaptureError("work_database_rebind_lost_race")

        if rebind_window:
            connection.commit()

        return connection
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
        raise


def _page_target_bookings(
    snapshot: SourceSnapshot,
    tab_name: str,
    page_no: int,
    target_bookings: Sequence[SourceBooking] | None = None,
) -> tuple[SourceBooking, ...]:
    candidates = snapshot.bookings if target_bookings is None else target_bookings
    return tuple(
        booking
        for booking in candidates
        if booking.tab_name == tab_name and booking.page_no == page_no
    )


def _attest_live_page(
    connection: sqlite3.Connection,
    *,
    snapshot: SourceSnapshot,
    run_id: str,
    tab_name: str,
    page_no: int,
    phase: str,
    tree: str,
    pseudonym_key: bytes,
) -> list[dict[str, Any]]:
    try:
        from tools.agoda_portal_full_survey import SurveyError, _build_state
    except ModuleNotFoundError:
        from agoda_portal_full_survey import SurveyError, _build_state

    try:
        live_state = _build_state(
            tree, tab_name, page_no, pseudonym_key
        )
    except SurveyError as exc:
        raise ListDriftError(f"live_page_attestation_failed:{exc}") from exc
    cards = list(live_state.cards)
    if not cards:
        raise ListDriftError("live_page_contains_no_cards")
    pseudonyms = [str(card["booking_pseudonym_hmac"]) for card in cards]
    if len(pseudonyms) != len(set(pseudonyms)):
        raise ListDriftError("duplicate_booking_within_live_page")
    source_semantics = dict(snapshot.all_booking_semantics) or {
        booking.booking_pseudonym_hmac: booking.list_card_sha256
        for booking in snapshot.bookings
    }
    if not source_semantics:
        raise ListDriftError("source_canonical_membership_missing")
    unknown_cards: list[dict[str, Any]] = []
    for card in cards:
        pseudonym = str(card["booking_pseudonym_hmac"])
        if pseudonym not in source_semantics:
            unknown_cards.append(card)
            continue
        if str(card["booking_semantic_sha256"]) != source_semantics[pseudonym]:
            raise ListDriftError("live_booking_semantic_drift")
    connection.executemany(
        """
        INSERT OR IGNORE INTO live_census_deltas(
            run_id, tab_name, page_no, phase, booking_pseudonym_hmac,
            list_card_sha256, delta_kind, observed_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, 'post_census_booking', ?)
        """,
        [
            (
                run_id,
                tab_name,
                page_no,
                phase,
                str(card["booking_pseudonym_hmac"]),
                str(card["booking_semantic_sha256"]),
                _utc_now(),
            )
            for card in unknown_cards
        ],
    )
    target_pseudonyms = {
        booking.booking_pseudonym_hmac for booking in snapshot.bookings
    }
    live_target_order = [
        pseudonym for pseudonym in pseudonyms if pseudonym in target_pseudonyms
    ]
    ordered_sha256 = _sha256_text(_canonical_json(live_target_order))
    set_sha256 = _sha256_text(_canonical_json(sorted(live_target_order)))
    cursor = connection.execute(
        """
        INSERT INTO page_attestations(
            run_id, tab_name, page_no, phase, expected_selected_page,
            observed_selected_page, ordered_membership_sha256,
            set_membership_sha256, source_page_set_sha256, observed_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            tab_name,
            page_no,
            phase,
            page_no,
            live_state.page_no,
            ordered_sha256,
            set_sha256,
            snapshot.source_capture_set_sha256,
            _utc_now(),
        ),
    )
    attestation_id = int(cursor.lastrowid)
    target_cards = [
        card
        for card in cards
        if str(card["booking_pseudonym_hmac"]) in target_pseudonyms
    ]
    connection.executemany(
        """
        INSERT INTO page_attestation_members(
            attestation_id, ordinal, booking_pseudonym_hmac, list_card_sha256
        ) VALUES (?, ?, ?, ?)
        """,
        [
            (
                attestation_id,
                ordinal,
                str(card["booking_pseudonym_hmac"]),
                str(card["booking_semantic_sha256"]),
            )
            for ordinal, card in enumerate(target_cards, start=1)
        ],
    )
    connection.commit()
    return cards


def _attestation_membership_is_valid(
    connection: sqlite3.Connection,
    *,
    attestation_id: int,
    ordered_membership_sha256: str,
    set_membership_sha256: str,
    expected_booking_pseudonym_hmac: str,
    expected_list_card_sha256: str,
) -> bool:
    rows = connection.execute(
        """
        SELECT ordinal, booking_pseudonym_hmac, list_card_sha256
        FROM page_attestation_members
        WHERE attestation_id=?
        ORDER BY ordinal
        """,
        (attestation_id,),
    ).fetchall()
    if not rows or [int(row["ordinal"]) for row in rows] != list(
        range(1, len(rows) + 1)
    ):
        return False
    pseudonyms = [str(row["booking_pseudonym_hmac"]) for row in rows]
    if len(pseudonyms) != len(set(pseudonyms)):
        return False
    if _sha256_text(_canonical_json(pseudonyms)) != ordered_membership_sha256:
        return False
    if _sha256_text(_canonical_json(sorted(pseudonyms))) != set_membership_sha256:
        return False
    return any(
        str(row["booking_pseudonym_hmac"])
        == expected_booking_pseudonym_hmac
        and str(row["list_card_sha256"]) == expected_list_card_sha256
        for row in rows
    )


def _find_manage_booking_button(tree: str, booking_id: str) -> int:
    matching_blocks = []
    for block in _card_blocks(tree):
        button_matches = [
            match
            for line in block.splitlines()
            if (match := MANAGE_BUTTON_RE.match(line))
        ]
        if any(match.group(2) == booking_id for match in button_matches):
            matching_blocks.append(block)
    if len(matching_blocks) != 1:
        raise DetailVerifyError("booking_card_subtree_not_unique")
    matches = [
        int(match.group(1))
        for line in matching_blocks[0].splitlines()
        if (match := MANAGE_BUTTON_RE.match(line))
        and match.group(2) == booking_id
    ]
    if len(matches) != 1:
        raise DetailVerifyError("manage_booking_button_not_unique")
    return matches[0]


def _find_back_button(tree: str) -> int:
    matches = [
        int(match.group(1))
        for line in tree.splitlines()
        if (match := BACK_BUTTON_RE.match(line))
    ]
    if len(matches) != 1:
        raise DetailVerifyError("back_to_bookings_button_not_unique")
    return matches[0]


def _wait_stable_detail(
    app: str,
    window_id: int,
    source: SourceBooking,
    *,
    timeout_seconds: float = 75.0,
) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    previous_semantic_hash: str | None = None
    latest_error: CaptureError | None = None
    while time.monotonic() < deadline:
        tree = _tree(app, window_id)
        lowered = tree.casefold()
        if any(marker in lowered for marker in ("loading", "skeleton", "spinner")):
            previous_semantic_hash = None
            time.sleep(0.75)
            continue
        try:
            parsed = _parse_detail_tree(tree, source)
        except CaptureError as exc:
            latest_error = exc
            previous_semantic_hash = None
            time.sleep(0.75)
            continue
        semantic_hash = str(parsed["semantic_detail_sha256"])
        if semantic_hash == previous_semantic_hash:
            return tree, parsed
        previous_semantic_hash = semantic_hash
        time.sleep(0.75)
    if isinstance(latest_error, DetailVerifyError):
        raise latest_error
    if isinstance(latest_error, DetailParseError):
        raise latest_error
    raise DetailLoadError("detail_view_did_not_stabilize") from latest_error


def _wait_detail_with_single_refresh(
    app: str, window_id: int, source: SourceBooking
) -> tuple[str, dict[str, Any]]:
    """Allow exactly one refresh for a blank/transiently unloaded detail view."""
    try:
        return _wait_stable_detail(
            app, window_id, source, timeout_seconds=20.0
        )
    except DetailLoadError:
        _run_orca(
            "computer",
            "hotkey",
            "--app",
            app,
            "--window-id",
            str(window_id),
            "--key",
            "CmdOrCtrl+R",
            "--restore-window",
            "--no-screenshot",
        )
        return _wait_stable_detail(
            app, window_id, source, timeout_seconds=75.0
        )


def _position_list_page(
    app: str,
    window_id: int,
    tab_name: str,
    page_no: int,
    pseudonym_key: bytes,
) -> str:
    """Re-enter the allowlisted list route and prove the requested tab/page."""
    try:
        from tools.agoda_portal_full_survey import (
            _go_to_numeric_page,
            _select_tab_at_first_page,
        )
    except ModuleNotFoundError:
        from agoda_portal_full_survey import (
            _go_to_numeric_page,
            _select_tab_at_first_page,
        )

    state = _select_tab_at_first_page(app, window_id, tab_name, pseudonym_key)
    if page_no > state.last_page:
        raise ListDriftError("requested_page_exceeds_live_last_page")
    for target_page in range(2, page_no + 1):
        state = _go_to_numeric_page(
            app,
            window_id,
            tab_name,
            target_page,
            target_page - 1,
            state,
            pseudonym_key,
        )
    return state.tree


def _locate_source_booking(
    connection: sqlite3.Connection,
    *,
    app: str,
    window_id: int,
    snapshot: SourceSnapshot,
    run_id: str,
    source: SourceBooking,
    pseudonym_key: bytes,
) -> tuple[str, SourceBooking]:
    """Find a canonical booking despite unstable tied-sort page boundaries."""
    try:
        from tools.agoda_portal_full_survey import (
            _go_to_numeric_page,
            _select_tab_at_first_page,
        )
    except ModuleNotFoundError:
        from agoda_portal_full_survey import (
            _go_to_numeric_page,
            _select_tab_at_first_page,
        )

    state = _select_tab_at_first_page(
        app, window_id, source.tab_name, pseudonym_key
    )
    for page_no in range(1, state.last_page + 1):
        if page_no > 1:
            state = _go_to_numeric_page(
                app,
                window_id,
                source.tab_name,
                page_no,
                page_no - 1,
                state,
                pseudonym_key,
            )
        cards = _attest_live_page(
            connection,
            snapshot=snapshot,
            run_id=run_id,
            tab_name=source.tab_name,
            page_no=page_no,
            phase="before_click",
            tree=state.tree,
            pseudonym_key=pseudonym_key,
        )
        matches = [
            card
            for card in cards
            if str(card["booking_pseudonym_hmac"])
            == source.booking_pseudonym_hmac
        ]
        if len(matches) > 1:
            raise ListDriftError("booking_duplicated_within_live_page")
        if matches:
            return state.tree, replace(
                source,
                page_no=page_no,
                card_position=int(matches[0]["card_position"]),
            )
    raise ListDriftError("canonical_booking_not_found_in_live_tab")


def _stable_current_list_page(
    app: str,
    window_id: int,
    tab_name: str,
    page_no: int,
    pseudonym_key: bytes,
    expected_last_page: int,
) -> str:
    try:
        from tools.agoda_portal_full_survey import _wait_tab_state
    except ModuleNotFoundError:
        from agoda_portal_full_survey import _wait_tab_state
    state = _wait_tab_state(
        app,
        window_id,
        tab_name,
        page_no,
        pseudonym_key,
        expected_last_page=expected_last_page,
        partial_stable_seconds=0.0,
    )
    return state.tree


def _wait_for_list_surface_after_history_back(
    app: str,
    window_id: int,
    tab_name: str,
    page_no: int,
    *,
    timeout_seconds: float = 20.0,
) -> str:
    """Wait briefly for the SPA list surface after browser-history Back.

    Edge can acknowledge Alt+Left before the booking cards have been
    materialized in the UIA tree.  Returning the first transient tree makes
    the caller fall back to the much slower tab/page route reset.  Polling is
    bounded and only observes the existing window; attestation remains the
    authoritative guard before the next booking click.
    """
    deadline = time.monotonic() + timeout_seconds
    selected_tab_pattern = re.compile(
        rf"^\s*\d+\s+기본\s+{re.escape(tab_name)}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    # History Back may legitimately restore the list on a different page
    # (often page 1) before the caller repositions to ``page_no``.  Waiting
    # for the target page here makes recovery loop back into tab selection and
    # hides the real page-positioning step.  Require only an attested numeric
    # page marker; _attest_live_page/_position_list_page owns exact-page
    # recovery below.
    selected_page_pattern = re.compile(
        r"^\s*\d+\s+기본\s+\d+\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    current_tree = _tree(app, window_id)
    while (
        "mmb-booking-card--" not in current_tree
        or not selected_tab_pattern.search(current_tree)
        or (
            os.environ.get("AGODA_UI_BACKEND", "").strip().lower()
            == "windows_uia"
            and not selected_page_pattern.search(current_tree)
        )
    ):
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)
        current_tree = _tree(app, window_id)
    return current_tree


def _native_browser_back(app: str, window_id: int) -> str:
    """Click Chromium's browser-chrome Back button through the native backend.

    Windows UIA can lose foreground ownership while a detail SPA is being
    unloaded, which makes its semantic Alt+Left action fail with
    ``window_not_focused``.  The native Orca tree still exposes the browser
    chrome Back button in that state.  Use only that existing control; this
    helper never navigates to a new URL.
    """
    saved_backend = os.environ.pop("AGODA_UI_BACKEND", None)
    try:
        result = _run_orca(
            "computer",
            "get-app-state",
            "--app",
            app,
            "--window-id",
            str(window_id),
            "--restore-window",
            "--no-screenshot",
        )
        native_tree = str(result["result"]["snapshot"]["treeText"])
        detail_back_matches = [
            int(match.group(1))
            for line in native_tree.splitlines()
            if (
                match := re.match(
                    r"^\s*(\d+)\s+(?:단추|링크|button|link)\s+"
                    r"(?:Back to bookings|Back to booking|예약으로 돌아가기)\s*$",
                    line,
                    re.IGNORECASE,
                )
            )
        ]
        browser_back_matches = [
            int(match.group(1))
            for line in native_tree.splitlines()
            if (
                match := re.match(
                    r"^\s*(\d+)\s+(?:단추|button)\s+(?:뒤로|Back)\s*$",
                    line,
                    re.IGNORECASE,
                )
            )
        ]
        matches = detail_back_matches or browser_back_matches
        if len(matches) != 1:
            raise RuntimeError("native_browser_back_not_unique")
        _run_orca(
            "computer",
            "click",
            "--app",
            app,
            "--window-id",
            str(window_id),
            "--element-index",
            str(matches[0]),
            "--restore-window",
            "--no-screenshot",
        )
        return native_tree
    finally:
        if saved_backend is not None:
            os.environ["AGODA_UI_BACKEND"] = saved_backend


def _return_to_attested_page(
    connection: sqlite3.Connection,
    *,
    app: str,
    window_id: int,
    snapshot: SourceSnapshot,
    run_id: str,
    tab_name: str,
    page_no: int,
    pseudonym_key: bytes,
    detail_tree: str | None = None,
    fast_direct: bool = False,
) -> str:
    current_tree = detail_tree or _tree(app, window_id)
    if "mmb-booking-card--" not in current_tree:
        try:
            if (
                fast_direct
                and os.environ.get("AGODA_UI_BACKEND", "").strip().lower()
                == "windows_uia"
            ):
                # The coordinate Back hyperlink can be acknowledged before
                # the SPA repaints.  One browser-history Back avoids clicking
                # a transient detail control a second time.
                _run_orca(
                    "computer",
                    "hotkey",
                    "--app",
                    app,
                    "--window-id",
                    str(window_id),
                    "--key",
                    "Alt+Left",
                    "--no-screenshot",
                )
                current_tree = _wait_for_list_surface_after_history_back(
                    app, window_id, tab_name, page_no
                )
            else:
                back_button = _find_back_button(current_tree)
                _click(
                    app,
                    window_id,
                    back_button,
                    expected_name=_element_name(current_tree, back_button),
                )
        except RuntimeError:
            # UIA can lose foreground ownership while unloading the detail
            # SPA.  Recover through the existing browser-chrome Back button
            # before considering a route reset; this preserves the current
            # tab/session and avoids a new navigation.
            if (
                fast_direct
                and os.environ.get("AGODA_UI_BACKEND", "").strip().lower()
                == "windows_uia"
            ):
                try:
                    _native_browser_back(app, window_id)
                    current_tree = _wait_for_list_surface_after_history_back(
                        app, window_id, tab_name, page_no
                    )
                except RuntimeError:
                    # The native fallback is bounded.  If the browser chrome
                    # is unavailable too, use the existing allowlisted route
                    # reset and let page attestation decide whether it is safe
                    # to continue.
                    current_tree = _position_list_page(
                        app, window_id, tab_name, page_no, pseudonym_key
                    )
            else:
                # The Windows UIA bridge can reject an otherwise valid
                # semantic click transiently.  Re-enter the allowlisted list
                # route instead of aborting the resumable capture run.
                current_tree = _position_list_page(
                    app, window_id, tab_name, page_no, pseudonym_key
                )
        else:
            try:
                if fast_direct:
                    # The semantic Back action has already completed.  One
                    # fresh tree is enough to establish the list surface;
                    # _attest_live_page below remains the binding guard.
                    current_tree = _tree(app, window_id)
                    if (
                        "mmb-booking-card--" not in current_tree
                        and not fast_direct
                    ):
                        current_tree = _position_list_page(
                            app, window_id, tab_name, page_no, pseudonym_key
                        )
                else:
                    current_tree = _stable_current_list_page(
                        app,
                        window_id,
                        tab_name,
                        page_no,
                        pseudonym_key,
                        max(
                            candidate_page
                            for candidate_tab, candidate_page in snapshot.page_manifest
                            if candidate_tab == tab_name
                        ),
                    )
            except CaptureError:
                current_tree = _position_list_page(
                    app, window_id, tab_name, page_no, pseudonym_key
                )
    if (
        fast_direct
        and os.environ.get("AGODA_UI_BACKEND", "").strip().lower()
        != "windows_uia"
        and "mmb-booking-card--" not in current_tree
    ):
        # Chromium can acknowledge the coordinate click before the SPA has
        # repainted the list.  A single in-history Back is the bounded
        # recovery for that transient; it never opens a new URL.
        try:
            _run_orca(
                "computer",
                "hotkey",
                "--app",
                app,
                "--window-id",
                str(window_id),
                "--key",
                "Alt+Left",
                "--no-screenshot",
            )
            current_tree = _tree(app, window_id)
        except BaseException:
            pass
    try:
        _attest_live_page(
            connection,
            snapshot=snapshot,
            run_id=run_id,
            tab_name=tab_name,
            page_no=page_no,
            phase="after_return",
            tree=current_tree,
            pseudonym_key=pseudonym_key,
        )
        return current_tree
    except ListDriftError:
        current_tree = _position_list_page(
            app, window_id, tab_name, page_no, pseudonym_key
        )
        _attest_live_page(
            connection,
            snapshot=snapshot,
            run_id=run_id,
            tab_name=tab_name,
            page_no=page_no,
            phase="after_return",
            tree=current_tree,
            pseudonym_key=pseudonym_key,
        )
        return current_tree


def _recover_after_booking_error(
    connection: sqlite3.Connection,
    *,
    app: str,
    window_id: int,
    snapshot: SourceSnapshot,
    run_id: str,
    tab_name: str,
    page_no: int,
    pseudonym_key: bytes,
    detail_tree: str | None,
    fast_direct: bool = False,
) -> str:
    """Recover one booking without forcing the whole worker to restart.

    The ordinary return path already prefers the semantic Back button.  If
    that complete recovery path fails for a transient, non-drift reason, make
    one fresh allowlisted route attempt to the assigned tab/page and attest it
    before allowing capture to continue.  Membership drift remains terminal.
    """
    try:
        return _return_to_attested_page(
            connection,
            app=app,
            window_id=window_id,
            snapshot=snapshot,
            run_id=run_id,
            tab_name=tab_name,
            page_no=page_no,
            pseudonym_key=pseudonym_key,
            detail_tree=detail_tree,
            fast_direct=fast_direct,
        )
    except BaseException as recovery_exc:
        recovery_status, _recovery_code = _failure_status(recovery_exc)
        if recovery_status == "failed_drift":
            _mark_epoch_drift(connection, run_id)
            raise

    try:
        recovered_tree = _position_list_page(
            app, window_id, tab_name, page_no, pseudonym_key
        )
        _attest_live_page(
            connection,
            snapshot=snapshot,
            run_id=run_id,
            tab_name=tab_name,
            page_no=page_no,
            # Reuse the sealed schema's existing post-detail attestation
            # phase; this fallback is still a return-to-list observation.
            phase="after_return",
            tree=recovered_tree,
            pseudonym_key=pseudonym_key,
        )
        return recovered_tree
    except BaseException as fallback_exc:
        fallback_status, fallback_code = _failure_status(fallback_exc)
        if fallback_status == "failed_drift":
            _mark_epoch_drift(connection, run_id)
            raise
        raise CaptureError(
            f"browser_recovery_failed:{fallback_code}"
        ) from fallback_exc


def _attempt_number(
    connection: sqlite3.Connection, run_id: str, booking_id_sha256: str
) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM capture_attempts "
            "WHERE run_id = ? AND booking_id_sha256 = ?",
            (run_id, booking_id_sha256),
        ).fetchone()[0]
    ) + 1


def _begin_attempt(
    connection: sqlite3.Connection, run_id: str, source: SourceBooking
) -> tuple[int, int]:
    attempt_no = _attempt_number(connection, run_id, source.booking_id_sha256)
    cursor = connection.execute(
        """
        INSERT INTO capture_attempts(
            run_id, booking_id_sha256, tab_name, page_no, card_position,
            attempt_no, started_at_utc, capture_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'started')
        """,
        (
            run_id, source.booking_id_sha256, source.tab_name, source.page_no,
            source.card_position, attempt_no, _utc_now()
        ),
    )
    connection.commit()
    return int(cursor.lastrowid), attempt_no


def _finish_failed_attempt(
    connection: sqlite3.Connection,
    attempt_id: int,
    status: str,
    failure_code: str,
) -> None:
    if status not in DETAIL_STATUSES or status == "success":
        raise ValueError("invalid failed-attempt status")
    connection.execute(
        """
        UPDATE capture_attempts
        SET finished_at_utc = ?, capture_status = ?, failure_code = ?
        WHERE attempt_id = ? AND capture_status <> 'success'
        """,
        (_utc_now(), status, failure_code, attempt_id),
    )
    connection.commit()


def _latest_success_exists(
    connection: sqlite3.Connection, run_id: str, booking_id_sha256: str
) -> bool:
    has_observations = bool(
        connection.execute(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='booking_detail_observations')"
        ).fetchone()[0]
    )
    if not has_observations:
        return bool(
            connection.execute(
                "SELECT EXISTS(SELECT 1 FROM booking_detail_snapshots "
                "WHERE run_id=? AND booking_id_sha256=?)",
                (run_id, booking_id_sha256),
            ).fetchone()[0]
        )
    return bool(
        connection.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM booking_detail_snapshots
                WHERE run_id = ? AND booking_id_sha256 = ?
                UNION ALL
                SELECT 1 FROM booking_detail_observations
                WHERE run_id = ? AND booking_id_sha256 = ?
            )
            """,
            (run_id, booking_id_sha256, run_id, booking_id_sha256),
        ).fetchone()[0]
    )


def _failed_attempt_count(
    connection: sqlite3.Connection, run_id: str, booking_id_sha256: str
) -> int:
    return int(
        connection.execute(
            """
            SELECT COUNT(*) FROM capture_attempts
            WHERE run_id = ? AND booking_id_sha256 = ?
              AND capture_status LIKE 'failed_%'
            """,
            (run_id, booking_id_sha256),
        ).fetchone()[0]
    )


def _ordered_unresolved_targets(
    connection: sqlite3.Connection,
    run_id: str,
    targets: Sequence[SourceBooking],
    *,
    recapture_existing: bool = False,
) -> tuple[SourceBooking, ...]:
    """Order canonical page targets by prior failure burden.

    Success snapshots are excluded and failed-attempt counts are scoped to the
    supplied run in the same parameterized query.  The final sort deliberately
    uses the canonical source card position, not a runtime position observed
    after navigation.
    """
    if not targets:
        return ()

    if recapture_existing:
        failed_counts = {
            target.booking_id_sha256: _failed_attempt_count(
                connection, run_id, target.booking_id_sha256
            )
            for target in targets
        }
    else:
        target_values = ",".join("(?)" for _ in targets)
        hashes = [target.booking_id_sha256 for target in targets]
        has_observations = bool(
            connection.execute(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='booking_detail_observations')"
            ).fetchone()[0]
        )
        observation_union = (
            """
                    UNION ALL
                    SELECT 1
                    FROM booking_detail_observations AS observations
                    WHERE observations.run_id = ?
                      AND observations.booking_id_sha256 = target_hashes.booking_id_sha256
            """
            if has_observations
            else ""
        )
        unresolved_rows = connection.execute(
            f"""
            WITH target_hashes(booking_id_sha256) AS (
                VALUES {target_values}
            ), unresolved_hashes AS (
                SELECT DISTINCT target_hashes.booking_id_sha256
                FROM target_hashes
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM booking_detail_snapshots AS snapshots
                    WHERE snapshots.run_id = ?
                      AND snapshots.booking_id_sha256 = target_hashes.booking_id_sha256
                    {observation_union}
                )
            ), failed_counts AS (
                SELECT attempts.booking_id_sha256, COUNT(*) AS failed_count
                FROM capture_attempts AS attempts
                INNER JOIN unresolved_hashes
                    ON unresolved_hashes.booking_id_sha256 = attempts.booking_id_sha256
                WHERE attempts.run_id = ?
                  AND attempts.capture_status LIKE 'failed_%'
                GROUP BY attempts.booking_id_sha256
            )
            SELECT unresolved_hashes.booking_id_sha256,
                   COALESCE(failed_counts.failed_count, 0) AS failed_count
            FROM unresolved_hashes
            LEFT JOIN failed_counts
                ON failed_counts.booking_id_sha256 = unresolved_hashes.booking_id_sha256
            """,
            [
                *hashes,
                run_id,
                *([run_id] if has_observations else []),
                run_id,
            ],
        ).fetchall()
        failed_counts = {
            str(row[0]): int(row[1])
            for row in unresolved_rows
        }

    unresolved: list[tuple[int, int, str, SourceBooking]] = []
    for booking in targets:
        if booking.booking_id_sha256 not in failed_counts:
            continue
        failed_count = failed_counts[booking.booking_id_sha256]
        unresolved.append(
            (
                failed_count,
                int(booking.card_position),
                str(booking.booking_id_sha256),
                booking,
            )
        )
    unresolved.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple(item[3] for item in unresolved)


def _ordered_unresolved_page_batches(
    connection: sqlite3.Connection,
    run_id: str,
    snapshot: SourceSnapshot,
    page_keys: Sequence[tuple[str, int]] | None = None,
    target_bookings: Sequence[SourceBooking] | None = None,
    *,
    recapture_existing: bool = False,
) -> tuple[UnresolvedPageBatch, ...]:
    """Order unresolved page batches by the first unresolved target's failure burden.

    Success-only pages are excluded. Within each page, unresolved targets are
    ordered by existing single-page fairness. Pages are then ordered by the
    first unresolved target's failed_% count ascending, breaking ties by
    canonical tab rank and page number. Original page_target_count is preserved.
    """
    if page_keys is None:
        page_keys = sorted(
            {
                (booking.tab_name, booking.page_no)
                for booking in snapshot.bookings
            },
            key=lambda item: (TAB_RANK.get(item[0], 99), item[1]),
        )
    batches: list[tuple[int, int, int, UnresolvedPageBatch]] = []
    for tab_name, page_no in page_keys:
        page_targets = _page_target_bookings(
            snapshot, tab_name, page_no, target_bookings
        )
        if not page_targets:
            continue
        page_target_count = len(page_targets)
        targets = _ordered_unresolved_targets(
            connection,
            run_id,
            page_targets,
            recapture_existing=recapture_existing,
        )
        if not targets:
            continue
        first_failed_count = _failed_attempt_count(
            connection, run_id, targets[0].booking_id_sha256
        )
        batch = UnresolvedPageBatch(
            tab_name=tab_name,
            page_no=page_no,
            page_target_count=page_target_count,
            targets=targets,
        )
        batches.append(
            (
                first_failed_count,
                TAB_RANK.get(tab_name, 99),
                page_no,
                batch,
            )
        )
    batches.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple(item[3] for item in batches)


DETAIL_WRITE_SAVEPOINT = "agoda_detail_write"


def _rollback_detail_savepoint(
    connection: sqlite3.Connection, savepoint: str = DETAIL_WRITE_SAVEPOINT
) -> None:
    """Undo one detail result without committing a partial replacement."""
    try:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
    finally:
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")


def _delete_snapshot_evidence(
    connection: sqlite3.Connection, snapshot_ids: Iterable[int]
) -> None:
    for snapshot_id in snapshot_ids:
        connection.execute(
            "DELETE FROM payment_events WHERE snapshot_id=?", (snapshot_id,)
        )
        connection.execute(
            "DELETE FROM price_components WHERE snapshot_id=?", (snapshot_id,)
        )
        connection.execute(
            "DELETE FROM booking_detail_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        )


def _insert_success_snapshot(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    source: SourceBooking,
    parsed: dict[str, Any],
    attempt_id: int,
    replace_existing: bool = False,
) -> int:
    savepoint = DETAIL_WRITE_SAVEPOINT
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        old_snapshot_ids: list[int] = []
        old_observation_ids: list[int] = []
        if replace_existing:
            old_snapshot_ids = [
                int(row[0])
                for row in connection.execute(
                    "SELECT snapshot_id FROM booking_detail_snapshots "
                    "WHERE run_id=? AND booking_id_sha256=?",
                    (run_id, source.booking_id_sha256),
                ).fetchall()
            ]
            old_observation_ids = [
                int(row[0])
                for row in connection.execute(
                    "SELECT observation_id FROM booking_detail_observations "
                    "WHERE run_id=? AND booking_id_sha256=?",
                    (run_id, source.booking_id_sha256),
                ).fetchall()
            ]
        elif connection.execute(
            "SELECT EXISTS(SELECT 1 FROM booking_detail_observations "
            "WHERE run_id=? AND booking_id_sha256=?)",
            (run_id, source.booking_id_sha256),
        ).fetchone()[0]:
            raise DetailVerifyError("price_snapshot_conflicts_with_terminal_observation")

        existing = connection.execute(
            """
            SELECT snapshot_id FROM booking_detail_snapshots
            WHERE run_id = ? AND booking_id_sha256 = ?
              AND semantic_detail_sha256 = ?
            """,
            (run_id, source.booking_id_sha256, parsed["semantic_detail_sha256"]),
        ).fetchone()
        if existing:
            snapshot_id = int(existing[0])
        else:
            version = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(snapshot_version), 0) + 1
                    FROM booking_detail_snapshots
                    WHERE run_id = ? AND booking_id_sha256 = ?
                    """,
                    (run_id, source.booking_id_sha256),
                ).fetchone()[0]
            )
            schedule = [
                component
                for component in parsed["price_components"]
                if component["kind"] in {
                    "paid_today",
                    "future_due",
                    "remaining_due",
                    "property_due",
                }
            ]
            cursor = connection.execute(
                """
                INSERT INTO booking_detail_snapshots(
                    run_id, booking_id, reference_code, booking_id_sha256,
                    booking_pseudonym_hmac, tab_name, page_no, card_position,
                    list_card_sha256, source_service_start_on,
                    source_service_end_on, source_scope_status,
                    source_reservation_status, detail_service_start_on,
                    detail_service_end_on, detail_scope_status,
                    room_count, nights, reservation_status, payment_status,
                    collection_model, refund_status, payment_schedule_json,
                    has_local_tax, card_type, card4, card4_sha256, card_role,
                    semantic_detail_sha256, snapshot_version, captured_at_utc
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    run_id,
                    source.booking_id,
                    parsed["reference_code"],
                    source.booking_id_sha256,
                    source.booking_pseudonym_hmac,
                    source.tab_name,
                    source.page_no,
                    source.card_position,
                    source.list_card_sha256,
                    source.service_start_on,
                    source.service_end_on,
                    source.source_scope_status,
                    source.reservation_status,
                    parsed["detail_service_start_on"],
                    parsed["detail_service_end_on"],
                    parsed["detail_scope_status"],
                    parsed["room_count"],
                    parsed["nights"],
                    parsed["reservation_status"],
                    parsed["payment_status"],
                    parsed["collection_model"],
                    parsed["refund_status"],
                    _canonical_json(schedule),
                    parsed["has_local_tax"],
                    parsed["card_type"],
                    parsed["card4"],
                    parsed["card4_sha256"],
                    parsed["card_role"],
                    parsed["semantic_detail_sha256"],
                    version,
                    _utc_now(),
                ),
            )
            snapshot_id = int(cursor.lastrowid)

        if existing is not None and replace_existing:
            connection.execute(
                "DELETE FROM payment_events WHERE snapshot_id=?", (snapshot_id,)
            )
            connection.execute(
                "DELETE FROM price_components WHERE snapshot_id=?", (snapshot_id,)
            )
        if existing is None or replace_existing:
            connection.executemany(
                """
                INSERT INTO price_components(
                    snapshot_id, ordinal, component_kind, label_normalized,
                    currency, amount_decimal_text, amount_minor_units,
                    currency_scale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        component["ordinal"],
                        component["kind"],
                        component["label_normalized"],
                        component["currency"],
                        component["decimal_text"],
                        component["minor_units"],
                        component["scale"],
                    )
                    for component in parsed["price_components"]
                ],
            )
            connection.executemany(
                """
                INSERT INTO payment_events(
                    snapshot_id, event_kind, event_on, currency,
                    amount_decimal_text, amount_minor_units, currency_scale,
                    card4_sha256, evidence_label
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        event["event_kind"],
                        event["event_on"],
                        event["currency"],
                        event["decimal_text"],
                        event["minor_units"],
                        event["scale"],
                        event["card4_sha256"],
                        event["evidence_label"],
                    )
                    for event in parsed["payment_events"]
                ],
            )
        if replace_existing:
            _delete_snapshot_evidence(
                connection,
                [old_id for old_id in old_snapshot_ids if old_id != snapshot_id],
            )
            for observation_id in old_observation_ids:
                connection.execute(
                    "DELETE FROM booking_detail_observations WHERE observation_id=?",
                    (observation_id,),
                )
        connection.execute(
            """
            UPDATE capture_attempts
            SET finished_at_utc = ?, capture_status = 'success',
                semantic_detail_sha256 = ?, failure_code = NULL
            WHERE attempt_id = ?
            """,
            (_utc_now(), parsed["semantic_detail_sha256"], attempt_id),
        )
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        connection.commit()
        return snapshot_id
    except BaseException:
        try:
            _rollback_detail_savepoint(connection, savepoint)
        except sqlite3.Error:
            connection.rollback()
        raise


def _insert_terminal_observation(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    source: SourceBooking,
    parsed: dict[str, Any],
    attempt_id: int,
    replace_existing: bool = False,
) -> int:
    if parsed.get("capture_kind") not in TERMINAL_OBSERVATION_KINDS:
        raise ValueError("invalid_terminal_observation_kind")
    if not _terminal_kind_matches_detail_status(
        parsed.get("capture_kind"), parsed.get("detail_reservation_status")
    ):
        raise DetailVerifyError("terminal_observation_status_kind_mismatch")
    if (
        source.tab_name != "Cancelled"
        or source.reservation_status
        not in TERMINAL_SOURCE_RESERVATION_STATUSES
        or parsed.get("reservation_status") != "cancelled"
    ):
        raise DetailVerifyError("terminal_observation_requires_cancelled_booking")
    if parsed.get("gross_total_present") != 0:
        raise DetailVerifyError("terminal_observation_cannot_contain_gross_total")
    if not replace_existing and connection.execute(
        "SELECT EXISTS(SELECT 1 FROM booking_detail_snapshots "
        "WHERE run_id=? AND booking_id_sha256=?)",
        (run_id, source.booking_id_sha256),
    ).fetchone()[0]:
        raise DetailVerifyError("terminal_observation_conflicts_with_price_snapshot")
    attestation = connection.execute(
        """
        SELECT attestation_id, ordered_membership_sha256,
               set_membership_sha256, source_page_set_sha256
        FROM page_attestations
        WHERE run_id=? AND tab_name=? AND page_no=?
          AND phase='before_click'
          AND expected_selected_page=? AND observed_selected_page=?
        ORDER BY attestation_id DESC LIMIT 1
        """,
        (
            run_id,
            source.tab_name,
            source.page_no,
            source.page_no,
            source.page_no,
        ),
    ).fetchone()
    if attestation is None:
        raise DetailVerifyError("terminal_observation_requires_live_list_attestation")
    list_attestation_id = int(attestation["attestation_id"])
    attested_ordered_membership_sha256 = str(
        attestation["ordered_membership_sha256"]
    )
    attested_set_membership_sha256 = str(attestation["set_membership_sha256"])
    attested_source_page_set_sha256 = str(
        attestation["source_page_set_sha256"]
    )
    if not all(
        (
            attested_ordered_membership_sha256,
            attested_set_membership_sha256,
            attested_source_page_set_sha256,
        )
    ):
        raise DetailVerifyError("terminal_observation_attestation_hash_missing")
    source_manifest = connection.execute(
        "SELECT source_capture_set_sha256 FROM capture_run_manifest "
        "WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if (
        source_manifest is None
        or str(source_manifest["source_capture_set_sha256"])
        != attested_source_page_set_sha256
    ):
        raise DetailVerifyError("terminal_observation_source_manifest_mismatch")
    if not _attestation_membership_is_valid(
        connection,
        attestation_id=list_attestation_id,
        ordered_membership_sha256=attested_ordered_membership_sha256,
        set_membership_sha256=attested_set_membership_sha256,
        expected_booking_pseudonym_hmac=source.booking_pseudonym_hmac,
        expected_list_card_sha256=source.list_card_sha256,
    ):
        raise DetailVerifyError("terminal_observation_list_membership_invalid")

    savepoint = DETAIL_WRITE_SAVEPOINT
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        old_snapshot_ids = [
            int(row[0])
            for row in connection.execute(
                "SELECT snapshot_id FROM booking_detail_snapshots "
                "WHERE run_id=? AND booking_id_sha256=?",
                (run_id, source.booking_id_sha256),
            ).fetchall()
        ] if replace_existing else []
        old_observation_ids = [
            int(row[0])
            for row in connection.execute(
                "SELECT observation_id FROM booking_detail_observations "
                "WHERE run_id=? AND booking_id_sha256=?",
                (run_id, source.booking_id_sha256),
            ).fetchall()
        ] if replace_existing else []
        existing = connection.execute(
            "SELECT observation_id,semantic_detail_sha256 "
            "FROM booking_detail_observations "
            "WHERE run_id=? AND booking_id_sha256=?",
            (run_id, source.booking_id_sha256),
        ).fetchone()
        if existing is not None and not replace_existing:
            if str(existing["semantic_detail_sha256"]) != parsed["semantic_detail_sha256"]:
                raise DetailVerifyError("terminal_observation_semantic_conflict")
            observation_id = int(existing["observation_id"])
        else:
            if replace_existing:
                # booking_detail_observations has a per-booking UNIQUE
                # constraint. Remove the old same-lane row inside the
                # savepoint before inserting its replacement; any failure
                # below restores it atomically.
                for old_observation_id in old_observation_ids:
                    connection.execute(
                        "DELETE FROM booking_detail_observations WHERE observation_id=?",
                        (old_observation_id,),
                    )
            cursor = connection.execute(
                """
                INSERT INTO booking_detail_observations(
                    run_id, booking_id_sha256, reference_code,
                    booking_pseudonym_hmac,
                    tab_name, page_no, card_position, list_card_sha256,
                    list_attestation_id,
                    attested_ordered_membership_sha256,
                    attested_set_membership_sha256,
                    attested_source_page_set_sha256,
                    source_service_start_on, source_service_end_on,
                    source_scope_status, source_reservation_status,
                    detail_service_start_on, detail_service_end_on,
                    detail_scope_status, reservation_status,
                    detail_reservation_status, payment_status,
                    collection_model, refund_status, observation_kind,
                    payment_information_present, gross_total_present,
                    visible_money_value_count,
                    card_type, card4, card4_sha256, card_role,
                    amount_matching_eligible, unresolved_competitor,
                    semantic_detail_sha256, observed_at_utc
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    run_id,
                    source.booking_id_sha256,
                    parsed["reference_code"],
                    source.booking_pseudonym_hmac,
                    source.tab_name,
                    source.page_no,
                    source.card_position,
                    source.list_card_sha256,
                    list_attestation_id,
                    attested_ordered_membership_sha256,
                    attested_set_membership_sha256,
                    attested_source_page_set_sha256,
                    source.service_start_on,
                    source.service_end_on,
                    source.source_scope_status,
                    source.reservation_status,
                    parsed["detail_service_start_on"],
                    parsed["detail_service_end_on"],
                    parsed["detail_scope_status"],
                    parsed["reservation_status"],
                    parsed["detail_reservation_status"],
                    parsed["payment_status"],
                    parsed["collection_model"],
                    parsed["refund_status"],
                    parsed["capture_kind"],
                    parsed["payment_information_present"],
                    parsed["gross_total_present"],
                    parsed["visible_money_value_count"],
                    parsed["card_type"],
                    parsed["card4"],
                    parsed["card4_sha256"],
                    parsed["card_role"],
                    parsed["amount_matching_eligible"],
                    parsed["unresolved_competitor"],
                    parsed["semantic_detail_sha256"],
                    _utc_now(),
                ),
            )
            observation_id = int(cursor.lastrowid)
            if replace_existing:
                _delete_snapshot_evidence(connection, old_snapshot_ids)
        connection.execute(
            """
            UPDATE capture_attempts
            SET finished_at_utc = ?, capture_status = 'success',
                semantic_detail_sha256 = ?, failure_code = NULL
            WHERE attempt_id = ?
            """,
            (_utc_now(), parsed["semantic_detail_sha256"], attempt_id),
        )
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        connection.commit()
        return observation_id
    except BaseException:
        try:
            _rollback_detail_savepoint(connection, savepoint)
        except sqlite3.Error:
            connection.rollback()
        raise


def _failure_status(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, ListDriftError):
        return "failed_drift", str(exc)
    if isinstance(exc, DetailVerifyError):
        return "failed_verify", str(exc)
    if isinstance(exc, DetailParseError):
        return "failed_parse", str(exc)
    if isinstance(exc, DetailLoadError):
        return "failed_load", str(exc)
    return "failed_load", "unexpected_capture_error"


def _mark_epoch_drift(connection: sqlite3.Connection, run_id: str) -> None:
    connection.execute(
        "UPDATE capture_run_manifest SET epoch_status = 'failed_drift' WHERE run_id = ?",
        (run_id,),
    )
    connection.commit()


def _browser_lock_path(work_path: Path, run_id: str) -> Path:
    return work_path.parent / f".{run_id}.agoda-browser.lock"


def _acquire_browser_lock(work_path: Path, run_id: str) -> tuple[Path, int]:
    lock_path = _browser_lock_path(work_path, run_id)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise CaptureError("agoda_browser_actor_is_already_locked") from exc
    return lock_path, descriptor


def _close_interrupted_attempts(
    connection: sqlite3.Connection, run_id: str
) -> int:
    cursor = connection.execute(
        "UPDATE capture_attempts SET capture_status='failed_load', "
        "failure_code='interrupted_previous_process', finished_at_utc=? "
        "WHERE run_id=? AND capture_status='started'",
        (_utc_now(), run_id),
    )
    connection.commit()
    return int(cursor.rowcount)


def _source_still_pinned(snapshot: SourceSnapshot) -> None:
    if _file_sha256(snapshot.path) != snapshot.file_sha256:
        raise CaptureError("source_staging_changed_during_capture")


def _revalidate_full_census(
    app: str,
    window_id: int,
    snapshot: SourceSnapshot,
    pseudonym_key: bytes,
) -> str:
    try:
        from tools.agoda_portal_full_survey import (
            TAB_NAMES,
            SurveyError,
            _canonical_bookings,
            _convergence_manifest,
            _scan_tab,
        )
    except ModuleNotFoundError:
        from agoda_portal_full_survey import (
            TAB_NAMES,
            SurveyError,
            _canonical_bookings,
            _convergence_manifest,
            _scan_tab,
        )
    expected_totals = dict(snapshot.tab_totals)
    expected_semantics = dict(snapshot.all_booking_semantics)
    if set(expected_totals) != set(TAB_NAMES) or not expected_semantics:
        raise ListDriftError("source_convergence_contract_missing")
    accumulated_cards: list[dict[str, Any]] = []
    try:
        for pass_no in range(1, 5):
            pages: list[dict[str, Any]] = []
            cards: list[dict[str, Any]] = []
            for tab_name in TAB_NAMES:
                tab_pages, tab_cards = _scan_tab(
                    app, window_id, tab_name, pass_no, pseudonym_key
                )
                pages.extend(tab_pages)
                cards.extend(tab_cards)
            current_totals = {
                tab_name: sum(
                    int(page["card_count"])
                    for page in pages
                    if str(page["tab_name"]) == tab_name
                )
                for tab_name in TAB_NAMES
            }
            if current_totals != expected_totals:
                raise ListDriftError("final_three_tab_total_drift")
            accumulated_cards.extend(cards)
            canonical = _canonical_bookings(accumulated_cards)
            observed_semantics = {
                str(card["booking_pseudonym_hmac"]): str(
                    card["booking_semantic_sha256"]
                )
                for card in canonical
            }
            if set(observed_semantics) - set(expected_semantics):
                raise ListDriftError("final_three_tab_unknown_booking")
            if any(
                expected_semantics[pseudonym] != semantic
                for pseudonym, semantic in observed_semantics.items()
            ):
                raise ListDriftError("final_three_tab_booking_semantic_drift")
            if len(observed_semantics) > snapshot.population_count:
                raise ListDriftError("final_three_tab_population_exceeded")
            if pass_no >= 2 and observed_semantics == expected_semantics:
                manifest = _convergence_manifest(expected_totals, canonical)
                if manifest != snapshot.source_capture_set_sha256:
                    raise ListDriftError("final_three_tab_manifest_drift")
                return manifest
    except SurveyError as exc:
        raise ListDriftError(f"final_three_tab_scan_failed:{exc}") from exc
    raise ListDriftError("final_three_tab_population_not_recovered")


def capture_details(
    *,
    app: str = "msedge",
    window_id: int,
    source_db: Path,
    hmac_key_file: Path,
    work_db: Path,
    run_id: str,
    pages: Sequence[int] | None = None,
    tabs: Sequence[str] | None = None,
    resume: bool = False,
    rebind_window: bool = False,
    attempts_per_booking: int = 2,
    max_new_successes: int | None = None,
    target_only: bool = False,
    fast_direct: bool = False,
    recapture_existing: bool = False,
) -> dict[str, Any]:
    if pages is not None and (not pages or any(page < 1 for page in pages)):
        raise CaptureError("pages_must_be_positive_when_provided")
    if pages is not None and len(set(pages)) != len(pages):
        raise CaptureError("pages_must_not_repeat")
    allowed_tabs = {"Upcoming", "Completed", "Cancelled"}
    if tabs is not None and (not tabs or set(tabs) - allowed_tabs):
        raise CaptureError("tabs_must_be_known_and_nonempty_when_provided")
    if tabs is not None and len(set(tabs)) != len(tabs):
        raise CaptureError("tabs_must_not_repeat")
    if attempts_per_booking < 1 or attempts_per_booking > 3:
        raise CaptureError("attempts_per_booking_must_be_between_1_and_3")
    if max_new_successes is not None and max_new_successes < 1:
        raise CaptureError("max_new_successes_must_be_positive")
    previous_umask = os.umask(0o077)
    snapshot = _load_source_snapshot(source_db, hmac_key_file)
    pseudonym_key, key_id = _load_private_hmac_key(hmac_key_file)
    if key_id != snapshot.pseudonym_key_id:
        raise CaptureError("pseudonym_key_id_mismatch")
    selected_pages = set(pages) if pages is not None else None
    selected_tabs = set(tabs) if tabs is not None else allowed_tabs
    capture_bookings = tuple(
        booking
        for booking in snapshot.bookings
        if not target_only
        or booking.source_scope_status == "target_2026_overlap"
    )
    if not capture_bookings:
        raise CaptureError("requested_capture_scope_contains_no_candidates")
    tab_rank = TAB_RANK
    page_keys = sorted(
        {
            (booking.tab_name, booking.page_no)
            for booking in capture_bookings
            if booking.tab_name in selected_tabs
            and (selected_pages is None or booking.page_no in selected_pages)
        },
        key=lambda item: (tab_rank[item[0]], item[1]),
    )
    if not page_keys:
        raise CaptureError("requested_capture_scope_contains_no_candidates")
    work_path = _require_tmp(work_db)
    connection = (
        _resume_work_db(
            work_path,
            snapshot,
            run_id,
            app,
            window_id,
            rebind_window=rebind_window,
        )
        if (resume or rebind_window)
        else _secure_create_work_db(work_path, snapshot, run_id, app, window_id)
    )
    lock_path: Path | None = None
    lock_descriptor: int | None = None
    progress: list[dict[str, Any]] = []
    new_successes = 0
    stop_after_limit = False
    try:
        lock_path, lock_descriptor = _acquire_browser_lock(work_path, run_id)
        os.close(lock_descriptor)
        lock_descriptor = None
        _close_interrupted_attempts(connection, run_id)
        page_batches = _ordered_unresolved_page_batches(
            connection,
            run_id,
            snapshot,
            page_keys,
            target_bookings=capture_bookings,
            recapture_existing=recapture_existing,
        )
        for batch in page_batches:
            tab_name = batch.tab_name
            page_no = batch.page_no
            page_target_count = batch.page_target_count
            targets = batch.targets
            tree = _position_list_page(
                app, window_id, tab_name, page_no, pseudonym_key
            )
            live_cards = _attest_live_page(
                connection,
                snapshot=snapshot,
                run_id=run_id,
                tab_name=tab_name,
                page_no=page_no,
                phase="before_click",
                tree=tree,
                pseudonym_key=pseudonym_key,
            )
            current_page = page_no
            for source in targets:
                if (
                    not recapture_existing
                    and _latest_success_exists(connection, run_id, source.booking_id_sha256)
                ):
                    continue
                success = False
                for _attempt in range(attempts_per_booking):
                    attempt_id: int | None = None
                    snapshot_committed = False
                    attempt_no = _attempt_number(
                        connection, run_id, source.booking_id_sha256
                    )
                    detail_tree: str | None = None
                    runtime_source = source
                    try:
                        if fast_direct:
                            # `tree` is the fresh tree returned by the page
                            # attestation before this batch or after the
                            # previous detail Back.  Re-parsing it locally
                            # avoids a second browser snapshot per booking;
                            # the attestation itself is still performed at
                            # every page entry/return.
                            try:
                                from tools.agoda_portal_full_survey import (
                                    _build_state,
                                )
                            except ModuleNotFoundError:
                                from agoda_portal_full_survey import _build_state
                            try:
                                live_cards = list(
                                    _build_state(
                                        tree,
                                        tab_name,
                                        current_page,
                                        pseudonym_key,
                                    ).cards
                                )
                            except Exception as exc:
                                raise ListDriftError(
                                    "fast_current_list_tree_parse_failed"
                                ) from exc
                            fresh_tree = tree
                        else:
                            fresh_tree = _stable_current_list_page(
                                app,
                                window_id,
                                tab_name,
                                current_page,
                                pseudonym_key,
                                max(
                                    candidate_page
                                    for candidate_tab, candidate_page in snapshot.page_manifest
                                    if candidate_tab == tab_name
                                ),
                            )
                            live_cards = _attest_live_page(
                                connection,
                                snapshot=snapshot,
                                run_id=run_id,
                                tab_name=tab_name,
                                page_no=current_page,
                                phase="before_click",
                                tree=fresh_tree,
                                pseudonym_key=pseudonym_key,
                            )
                        matches = [
                            card
                            for card in live_cards
                            if str(card["booking_pseudonym_hmac"])
                            == source.booking_pseudonym_hmac
                        ]
                        if len(matches) > 1:
                            raise ListDriftError(
                                "booking_duplicated_within_live_page"
                            )
                        if matches:
                            runtime_source = replace(
                                source,
                                page_no=current_page,
                                card_position=int(matches[0]["card_position"]),
                            )
                        else:
                            fresh_tree, runtime_source = _locate_source_booking(
                                connection,
                                app=app,
                                window_id=window_id,
                                snapshot=snapshot,
                                run_id=run_id,
                                source=source,
                                pseudonym_key=pseudonym_key,
                            )
                            current_page = runtime_source.page_no
                        attempt_id, attempt_no = _begin_attempt(
                            connection, run_id, runtime_source
                        )
                        button = _find_manage_booking_button(
                            fresh_tree, runtime_source.booking_id
                        )
                        _click(
                            app,
                            window_id,
                            button,
                            expected_name=_element_name(fresh_tree, button),
                        )
                        detail_tree, parsed = _wait_detail_with_single_refresh(
                            app,
                            window_id,
                            runtime_source,
                        )
                        if parsed.get("capture_kind") in TERMINAL_OBSERVATION_KINDS:
                            _insert_terminal_observation(
                                connection,
                                run_id=run_id,
                                source=runtime_source,
                                parsed=parsed,
                                attempt_id=attempt_id,
                                replace_existing=recapture_existing,
                            )
                        else:
                            _insert_success_snapshot(
                                connection,
                                run_id=run_id,
                                source=runtime_source,
                                parsed=parsed,
                                attempt_id=attempt_id,
                                replace_existing=recapture_existing,
                            )
                        snapshot_committed = True
                        tree = _return_to_attested_page(
                            connection,
                            app=app,
                            window_id=window_id,
                            snapshot=snapshot,
                            run_id=run_id,
                            tab_name=tab_name,
                            page_no=current_page,
                            pseudonym_key=pseudonym_key,
                            detail_tree=detail_tree,
                            fast_direct=fast_direct,
                        )
                        success = True
                    except BaseException as exc:
                        status, failure_code = _failure_status(exc)
                        if attempt_id is not None and not snapshot_committed:
                            _finish_failed_attempt(
                                connection,
                                attempt_id,
                                status,
                                failure_code,
                            )
                        if status == "failed_drift":
                            _mark_epoch_drift(connection, run_id)
                            raise
                        tree = _recover_after_booking_error(
                            connection,
                            app=app,
                            window_id=window_id,
                            snapshot=snapshot,
                            run_id=run_id,
                            tab_name=tab_name,
                            page_no=current_page,
                            pseudonym_key=pseudonym_key,
                            detail_tree=detail_tree,
                            fast_direct=fast_direct,
                        )
                        if snapshot_committed:
                            success = True
                    progress_item = {
                        "tab_name": tab_name,
                        "page_no": runtime_source.page_no,
                        "page_position": runtime_source.card_position,
                        "page_target_count": page_target_count,
                        "attempt_no": attempt_no,
                        "success": success,
                    }
                    progress.append(progress_item)
                    print(_canonical_json({"progress": progress_item}), flush=True)
                    if success:
                        new_successes += 1
                        if (
                            max_new_successes is not None
                            and new_successes >= max_new_successes
                        ):
                            stop_after_limit = True
                        break
                if not success:
                    progress_item = {
                        "tab_name": tab_name,
                        "page_no": current_page,
                        "page_position": source.card_position,
                        "page_target_count": page_target_count,
                        "attempt_no": attempt_no,
                        "success": False,
                        "bounded_attempts_exhausted": True,
                    }
                    progress.append(progress_item)
                    print(_canonical_json({"progress": progress_item}), flush=True)
                if stop_after_limit:
                    break
            _source_still_pinned(snapshot)
            if stop_after_limit:
                break

        price_snapshot_count = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) "
                "FROM booking_detail_snapshots WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
        )
        terminal_observation_count = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) "
                "FROM booking_detail_observations WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
        )
        success_count = price_snapshot_count + terminal_observation_count
        failed_attempt_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM capture_attempts "
                "WHERE run_id = ? AND capture_status LIKE 'failed_%'",
                (run_id,),
            ).fetchone()[0]
        )
        failure_reasons = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT failure_code,COUNT(*) FROM capture_attempts "
                "WHERE run_id=? AND capture_status LIKE 'failed_%' "
                "GROUP BY failure_code ORDER BY failure_code",
                (run_id,),
            )
        }
        card4_present_count = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) FROM ("
                "SELECT booking_id_sha256 FROM booking_detail_snapshots "
                "WHERE run_id=? AND card4 IS NOT NULL "
                "UNION ALL "
                "SELECT booking_id_sha256 FROM booking_detail_observations "
                "WHERE run_id=? AND card4 IS NOT NULL)",
                (run_id, run_id),
            ).fetchone()[0]
        )
        final_manifest_revalidated = False
        allow_target_only_revalidation = bool(
            os.environ.get("AGODA_TARGET_ONLY_FINAL_REVALIDATION", "").strip()
        )
        if (
            success_count == len(capture_bookings)
            and (not target_only or allow_target_only_revalidation)
        ):
            try:
                _revalidate_full_census(
                    app, window_id, snapshot, pseudonym_key
                )
                connection.execute(
                    "UPDATE capture_run_manifest SET "
                    "final_revalidation_sha256=?, final_revalidated_at_utc=? "
                    "WHERE run_id=?",
                    (
                        snapshot.source_capture_set_sha256,
                        _utc_now(),
                        run_id,
                    ),
                )
                connection.commit()
                final_manifest_revalidated = True
            except ListDriftError:
                _mark_epoch_drift(connection, run_id)
                raise
        return {
            "run_id": run_id,
            "work_db": str(work_path),
            "source_file_sha256": snapshot.file_sha256,
            "membership_set_sha256": snapshot.membership_set_sha256,
            "target_count": len(snapshot.bookings),
            "capture_scope": (
                "target_2026_overlap" if target_only else "source_selected"
            ),
            "capture_target_count": len(capture_bookings),
            "target_2026_count": snapshot.target_2026_count,
            "competitor_count": snapshot.competitor_count,
            "success_count": success_count,
            "price_snapshot_count": price_snapshot_count,
            "terminal_no_price_count": terminal_observation_count,
            "amount_universe_sealed": terminal_observation_count == 0,
            "remaining_count": len(capture_bookings) - success_count,
            "failed_attempt_count": failed_attempt_count,
            "failure_reasons": failure_reasons,
            "card4_present_count": card4_present_count,
            "new_success_count": new_successes,
            "processed_pages": [
                {"tab_name": tab_name, "page_no": page_no}
                for tab_name, page_no in page_keys
            ],
            "final_manifest_revalidated": final_manifest_revalidated,
        }
    finally:
        connection.close()
        if lock_descriptor is not None:
            os.close(lock_descriptor)
        if lock_path is not None:
            lock_path.unlink(missing_ok=True)
        os.umask(previous_umask)


def _policy_sha256() -> str:
    policy = {
        "version": "agoda-detail-evidence-v6",
        "target_population": (
            "converged_three_tab_census_2026_overlap_plus_year_unknown_"
            "and_2025-08-or-later_competition_only"
        ),
        "page_identity": "canonical_booking_membership_not_unstable_page_position",
        "total_charge_semantics": "gross_not_card_charge",
        "amount_storage": "iso_currency_integer_minor_units_and_decimal_text",
        "card_storage": "private_card_issuer_and_masked_last4_only",
        "full_pan_storage": False,
        "matching_side_effects": False,
        "raw_tree_persisted": False,
        "individual_pair_asserted": False,
        "cancelled_no_price_terminal": (
            "survey_complete_but_unresolved_amount_competitor"
        ),
        "cancelled_list_detail_status_conflict_terminal": (
            "preserve_confirmed_or_completed_detail_status_without_"
            "amount_and_never_make_it_matchable"
        ),
        "amount_confirmation_requires_zero_terminal_no_price": True,
        "terminal_requires": [
            "labelled_booking_id_exact_match",
            "source_and_detail_service_period_exact_match",
            "bound_live_list_attestation",
            "exact_canonical_cancelled_source_status",
            "attested_page_membership_hashes_exact_match",
            "attested_member_rows_recompute_hashes_and_bind_source_semantic",
            "zero_visible_money_values",
        ],
    }
    return _sha256_text(_canonical_json(policy))


def _seal_verification(
    connection: sqlite3.Connection,
    *,
    snapshot: SourceSnapshot,
    run_id: str,
    target_only: bool = False,
) -> tuple[int, str, int, int]:
    live_delta_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM live_census_deltas WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
    )
    if live_delta_count:
        raise CaptureError("cannot_seal_with_post_census_booking_delta")
    snapshot_rows = connection.execute(
        """
        SELECT booking_id_sha256, booking_pseudonym_hmac,
               page_no, source_service_start_on,
               source_service_end_on, source_reservation_status,
               list_card_sha256, COUNT(*) AS snapshot_count
        FROM booking_detail_snapshots
        WHERE run_id = ?
        GROUP BY booking_id_sha256
        """,
        (run_id,),
    ).fetchall()
    observation_rows = connection.execute(
        """
        SELECT booking_id_sha256, booking_pseudonym_hmac,
               page_no, source_service_start_on,
               source_service_end_on, source_reservation_status,
               detail_service_start_on, detail_service_end_on,
               reservation_status, detail_reservation_status,
               observation_kind,
               list_card_sha256, list_attestation_id,
               attested_ordered_membership_sha256,
               attested_set_membership_sha256,
               attested_source_page_set_sha256,
               gross_total_present, visible_money_value_count,
               amount_matching_eligible, unresolved_competitor,
               COUNT(*) AS observation_count
        FROM booking_detail_observations
        WHERE run_id = ?
        GROUP BY booking_id_sha256
        """,
        (run_id,),
    ).fetchall()
    expected_bookings = tuple(
        booking
        for booking in snapshot.bookings
        if not target_only
        or booking.source_scope_status == "target_2026_overlap"
    )
    expected_count = len(expected_bookings)
    if len(snapshot_rows) + len(observation_rows) != expected_count:
        raise CaptureError("cannot_seal_before_complete_fresh_census_membership")
    snapshot_hashes = {str(row["booking_id_sha256"]) for row in snapshot_rows}
    observation_hashes = {
        str(row["booking_id_sha256"]) for row in observation_rows
    }
    if snapshot_hashes & observation_hashes:
        raise CaptureError("sealed_booking_has_price_and_no_price_results")
    observed_hashes = snapshot_hashes | observation_hashes
    expected_hashes = {booking.booking_id_sha256 for booking in expected_bookings}
    if observed_hashes != expected_hashes:
        raise CaptureError("sealed_membership_does_not_match_source")
    if any(int(row["snapshot_count"]) != 1 for row in snapshot_rows):
        raise CaptureError("cannot_seal_booking_with_multiple_detail_versions")
    if any(int(row["observation_count"]) != 1 for row in observation_rows):
        raise CaptureError("cannot_seal_booking_with_multiple_terminal_observations")
    source_bookings = {
        booking.booking_id_sha256: booking for booking in expected_bookings
    }
    for row in observation_rows:
        source_booking = source_bookings.get(str(row["booking_id_sha256"]))
        if (
            source_booking is None
            or row["booking_pseudonym_hmac"]
            != source_booking.booking_pseudonym_hmac
            or row["list_card_sha256"] != source_booking.list_card_sha256
            or not row["source_service_start_on"]
            or not row["source_service_end_on"]
            or row["source_service_start_on"] != row["detail_service_start_on"]
            or row["source_service_end_on"] != row["detail_service_end_on"]
            or row["source_reservation_status"]
            not in TERMINAL_SOURCE_RESERVATION_STATUSES
            or row["reservation_status"] != "cancelled"
            or not _terminal_kind_matches_detail_status(
                row["observation_kind"], row["detail_reservation_status"]
            )
            or row["list_attestation_id"] is None
            or not row["attested_ordered_membership_sha256"]
            or not row["attested_set_membership_sha256"]
            or not row["attested_source_page_set_sha256"]
            or row["attested_source_page_set_sha256"]
            != snapshot.source_capture_set_sha256
            or int(row["gross_total_present"]) != 0
            or int(row["visible_money_value_count"]) != 0
            or int(row["amount_matching_eligible"]) != 0
            or int(row["unresolved_competitor"]) != 1
        ):
            raise CaptureError("terminal_observation_contract_invalid_at_seal")
        if not _attestation_membership_is_valid(
            connection,
            attestation_id=int(row["list_attestation_id"]),
            ordered_membership_sha256=str(
                row["attested_ordered_membership_sha256"]
            ),
            set_membership_sha256=str(row["attested_set_membership_sha256"]),
            expected_booking_pseudonym_hmac=str(
                row["booking_pseudonym_hmac"]
            ),
            expected_list_card_sha256=str(row["list_card_sha256"]),
        ):
            raise CaptureError(
                "terminal_observation_list_membership_invalid_at_seal"
            )
        if not connection.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM page_attestations
                WHERE attestation_id=? AND run_id=? AND tab_name='Cancelled'
                  AND page_no=? AND phase='before_click'
                  AND expected_selected_page=? AND observed_selected_page=?
                  AND ordered_membership_sha256=?
                  AND set_membership_sha256=?
                  AND source_page_set_sha256=?
            )
            """,
            (
                int(row["list_attestation_id"]),
                run_id,
                int(row["page_no"]),
                int(row["page_no"]),
                int(row["page_no"]),
                str(row["attested_ordered_membership_sha256"]),
                str(row["attested_set_membership_sha256"]),
                str(row["attested_source_page_set_sha256"]),
            ),
        ).fetchone()[0]:
            raise CaptureError("terminal_observation_attestation_invalid_at_seal")
    run_manifest = connection.execute(
        "SELECT epoch_status, final_revalidation_sha256 "
        "FROM capture_run_manifest WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run_manifest is None:
        raise CaptureError("capture_run_manifest_missing")
    if run_manifest["epoch_status"] == "failed_drift":
        raise CaptureError("cannot_seal_failed_drift_epoch")
    if run_manifest["final_revalidation_sha256"] != snapshot.source_capture_set_sha256:
        raise CaptureError("cannot_seal_without_final_three_tab_revalidation")
    components = int(connection.execute("SELECT COUNT(*) FROM price_components").fetchone()[0])
    covered_snapshots = int(
        connection.execute(
            "SELECT COUNT(DISTINCT snapshot_id) FROM price_components"
        ).fetchone()[0]
    )
    if components < len(snapshot_rows) or covered_snapshots != len(snapshot_rows):
        raise CaptureError("cannot_seal_booking_without_price_evidence")
    semantic_set_sha256 = _sha256_text(
        _canonical_json(
            sorted(
                str(row[0])
                for row in connection.execute(
                    "SELECT semantic_detail_sha256 FROM booking_detail_snapshots "
                    "WHERE run_id = ? UNION ALL "
                    "SELECT semantic_detail_sha256 FROM booking_detail_observations "
                    "WHERE run_id = ?",
                    (run_id, run_id),
                )
            )
        )
    )
    return (
        components,
        semantic_set_sha256,
        len(snapshot_rows),
        len(observation_rows),
    )


def seal_work_database(
    *,
    source_db: Path,
    hmac_key_file: Path,
    work_db: Path,
    sealed_db: Path,
    run_id: str,
    target_only: bool = False,
) -> dict[str, Any]:
    previous_umask = os.umask(0o077)
    snapshot = _load_source_snapshot(source_db, hmac_key_file)
    work_path = _require_tmp(work_db, must_exist=True)
    sealed_path = _require_tmp(sealed_db)
    if sealed_path.exists() or sealed_path.is_symlink():
        raise CaptureError("refusing_to_overwrite_sealed_database")
    _secure_private_parent(sealed_path)
    lock_path = sealed_path.with_name(f".{sealed_path.name}.lock")
    lock_descriptor: int | None = None
    temporary_path: Path | None = None
    published_inode: tuple[int, int] | None = None
    source = _resume_work_db(work_path, snapshot, run_id)
    try:
        (
            components,
            semantic_set_sha256,
            price_snapshot_count,
            terminal_no_price_count,
        ) = _seal_verification(
            source,
            snapshot=snapshot,
            run_id=run_id,
            target_only=target_only,
        )
        _source_still_pinned(snapshot)
        source.execute(
            """
            UPDATE capture_run_manifest
            SET epoch_status = 'complete', completed_at_utc = ?
            WHERE run_id = ?
            """,
            (_utc_now(), run_id),
        )
        source.commit()
        try:
            lock_descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise CaptureError("sealed_database_destination_is_locked") from exc
        os.close(lock_descriptor)
        lock_descriptor = None
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{sealed_path.name}.",
            suffix=".tmp",
            dir=str(sealed_path.parent),
        )
        os.close(temp_fd)
        temporary_path = Path(temp_name)
        destination = sqlite3.connect(temporary_path)
        try:
            source.backup(destination)
            destination.execute(
                """
                CREATE TABLE sealed_manifest (
                    run_id TEXT PRIMARY KEY,
                    capture_scope TEXT NOT NULL,
                    source_file_sha256 TEXT NOT NULL,
                    membership_set_sha256 TEXT NOT NULL,
                    membership_ordered_sha256 TEXT NOT NULL,
                    policy_sha256 TEXT NOT NULL,
                    booking_count INTEGER NOT NULL,
                    price_snapshot_count INTEGER NOT NULL,
                    terminal_no_price_count INTEGER NOT NULL,
                    amount_universe_sealed INTEGER NOT NULL CHECK(
                        amount_universe_sealed IN (0, 1)
                    ),
                    target_2026_count INTEGER NOT NULL,
                    competitor_count INTEGER NOT NULL,
                    price_component_count INTEGER NOT NULL,
                    semantic_set_sha256 TEXT NOT NULL,
                    sealed_at_utc TEXT NOT NULL
                )
                """
            )
            destination.execute(
                "INSERT INTO sealed_manifest VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    "target_2026_overlap" if target_only else "source_selected",
                    snapshot.file_sha256,
                    snapshot.membership_set_sha256,
                    snapshot.membership_ordered_sha256,
                    _policy_sha256(),
                    price_snapshot_count + terminal_no_price_count,
                    price_snapshot_count,
                    terminal_no_price_count,
                    int(terminal_no_price_count == 0),
                    snapshot.target_2026_count,
                    snapshot.competitor_count,
                    components,
                    semantic_set_sha256,
                    _utc_now(),
                ),
            )
            destination.commit()
        finally:
            destination.close()
        os.chmod(temporary_path, 0o600)
        with temporary_path.open("r+b") as sync_file:
            os.fsync(sync_file.fileno())
        os.link(temporary_path, sealed_path)
        published_stat = sealed_path.stat()
        published_inode = (published_stat.st_dev, published_stat.st_ino)
        temporary_path.unlink()
        temporary_path = None
        os.chmod(sealed_path, 0o600)
        with closing(_immutable_connection(sealed_path)) as verified:
            integrity = verified.execute("PRAGMA integrity_check").fetchone()[0]
            row = verified.execute("SELECT * FROM sealed_manifest").fetchone()
            price_booking_count = int(
                verified.execute(
                    "SELECT COUNT(DISTINCT booking_id_sha256) "
                    "FROM booking_detail_snapshots WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            observation_booking_count = int(
                verified.execute(
                    "SELECT COUNT(DISTINCT booking_id_sha256) "
                    "FROM booking_detail_observations WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            booking_count = price_booking_count + observation_booking_count
        expected_booking_count = (
            snapshot.target_2026_count if target_only else len(snapshot.bookings)
        )
        if integrity != "ok" or booking_count != expected_booking_count:
            raise CaptureError("sealed_database_immutable_verification_failed")
        if (
            row is None
            or row["source_file_sha256"] != snapshot.file_sha256
            or row["membership_set_sha256"] != snapshot.membership_set_sha256
            or row["policy_sha256"] != _policy_sha256()
            or int(row["price_snapshot_count"]) != price_booking_count
            or int(row["terminal_no_price_count"]) != observation_booking_count
            or int(row["amount_universe_sealed"])
            != int(observation_booking_count == 0)
        ):
            raise CaptureError("sealed_manifest_immutable_verification_failed")
        _source_still_pinned(snapshot)
        return {
            "run_id": run_id,
            "sealed_db": str(sealed_path),
            "sealed_db_sha256": _file_sha256(sealed_path),
            "booking_count": booking_count,
            "capture_scope": (
                "target_2026_overlap" if target_only else "source_selected"
            ),
            "price_snapshot_count": price_booking_count,
            "terminal_no_price_count": observation_booking_count,
            "amount_universe_sealed": observation_booking_count == 0,
            "target_2026_count": snapshot.target_2026_count,
            "competitor_count": snapshot.competitor_count,
            "price_component_count": components,
            "source_file_sha256": snapshot.file_sha256,
            "membership_set_sha256": snapshot.membership_set_sha256,
            "policy_sha256": _policy_sha256(),
            "payment_booking_links_created": 0,
            "classification_side_effects": 0,
        }
    except Exception:
        if published_inode is not None and sealed_path.exists():
            current = sealed_path.stat()
            if (current.st_dev, current.st_ino) == published_inode:
                sealed_path.unlink()
        raise
    finally:
        source.close()
        if lock_descriptor is not None:
            os.close(lock_descriptor)
        lock_path.unlink(missing_ok=True)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        os.umask(previous_umask)


def _summary_from_work(work_db: Path, run_id: str) -> dict[str, Any]:
    path = _require_tmp(work_db, must_exist=True)
    with closing(_immutable_connection(path)) as connection:
        has_observations = bool(
            connection.execute(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='booking_detail_observations')"
            ).fetchone()[0]
        )
        price_snapshot_count = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) "
                "FROM booking_detail_snapshots WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
        )
        terminal_observation_count = (
            int(
                connection.execute(
                    "SELECT COUNT(DISTINCT booking_id_sha256) "
                    "FROM booking_detail_observations WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            if has_observations
            else 0
        )
        success_count = price_snapshot_count + terminal_observation_count
        attempts = int(
            connection.execute(
                "SELECT COUNT(*) FROM capture_attempts WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
        )
        failures = int(
            connection.execute(
                "SELECT COUNT(*) FROM capture_attempts "
                "WHERE run_id = ? AND capture_status LIKE 'failed_%'",
                (run_id,),
            ).fetchone()[0]
        )
        card4_present = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) "
                "FROM booking_detail_snapshots WHERE run_id=? AND card4 IS NOT NULL",
                (run_id,),
            ).fetchone()[0]
        )
        card_type_present = int(
            connection.execute(
                "SELECT COUNT(DISTINCT booking_id_sha256) "
                "FROM booking_detail_snapshots WHERE run_id=? AND card_type IS NOT NULL",
                (run_id,),
            ).fetchone()[0]
        )
        if has_observations:
            card4_present += int(
                connection.execute(
                    "SELECT COUNT(DISTINCT booking_id_sha256) "
                    "FROM booking_detail_observations "
                    "WHERE run_id=? AND card4 IS NOT NULL",
                    (run_id,),
                ).fetchone()[0]
            )
            card_type_present += int(
                connection.execute(
                    "SELECT COUNT(DISTINCT booking_id_sha256) "
                    "FROM booking_detail_observations "
                    "WHERE run_id=? AND card_type IS NOT NULL",
                    (run_id,),
                ).fetchone()[0]
            )
        component_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT p.component_kind,COUNT(*) "
                "FROM price_components p "
                "JOIN booking_detail_snapshots s ON s.snapshot_id=p.snapshot_id "
                "WHERE s.run_id=? GROUP BY p.component_kind ORDER BY p.component_kind",
                (run_id,),
            )
        }
        payment_event_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM payment_events p "
                "JOIN booking_detail_snapshots s ON s.snapshot_id=p.snapshot_id "
                "WHERE s.run_id=?",
                (run_id,),
            ).fetchone()[0]
        )
        failure_reasons = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT failure_code,COUNT(*) FROM capture_attempts "
                "WHERE run_id=? AND capture_status LIKE 'failed_%' "
                "GROUP BY failure_code ORDER BY failure_code",
                (run_id,),
            )
        }
        manifest = connection.execute(
            "SELECT epoch_status, source_file_sha256, membership_set_sha256, "
            "target_count, target_2026_count, competitor_count, "
            "final_revalidation_sha256 "
            "FROM capture_run_manifest WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if manifest is None:
        raise CaptureError("work_run_manifest_missing")
    return {
        "run_id": run_id,
        "work_db": str(path),
        "epoch_status": manifest["epoch_status"],
        "source_file_sha256": manifest["source_file_sha256"],
        "membership_set_sha256": manifest["membership_set_sha256"],
        "target_count": int(manifest["target_count"]),
        "target_2026_count": int(manifest["target_2026_count"]),
        "competitor_count": int(manifest["competitor_count"]),
        "success_count": success_count,
        "price_snapshot_count": price_snapshot_count,
        "terminal_no_price_count": terminal_observation_count,
        "amount_universe_sealed": terminal_observation_count == 0,
        "remaining_count": int(manifest["target_count"]) - success_count,
        "attempt_count": attempts,
        "failed_attempt_count": failures,
        "failure_reasons": failure_reasons,
        "card4_present_count": card4_present,
        "card_type_present_count": card_type_present,
        "price_component_counts": component_counts,
        "payment_event_count": payment_event_count,
        "final_manifest_revalidated": bool(manifest["final_revalidation_sha256"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--app", default="msedge")
    capture_parser.add_argument("--window-id", type=int, required=True)
    capture_parser.add_argument("--source-db", type=Path, required=True)
    capture_parser.add_argument("--hmac-key-file", type=Path, required=True)
    capture_parser.add_argument("--work-db", type=Path, required=True)
    capture_parser.add_argument("--run-id", required=True)
    capture_parser.add_argument("--pages", type=int, nargs="+")
    capture_parser.add_argument(
        "--tabs", nargs="+", choices=("Upcoming", "Completed", "Cancelled")
    )
    capture_parser.add_argument("--resume", action="store_true")
    capture_parser.add_argument("--rebind-window", action="store_true")
    capture_parser.add_argument("--attempts-per-booking", type=int, default=2)
    capture_parser.add_argument("--max-new-successes", type=int)
    capture_parser.add_argument(
        "--target-only",
        action="store_true",
        help="capture only source rows in the target_2026_overlap scope",
    )
    capture_parser.add_argument(
        "--fast-direct",
        action="store_true",
        help="reuse attested direct-Orca list trees between detail actions",
    )
    capture_parser.add_argument(
        "--recapture-existing",
        action="store_true",
        help="re-read existing detail rows to populate the current capture fields",
    )

    seal_parser = subparsers.add_parser("seal")
    seal_parser.add_argument("--source-db", type=Path, required=True)
    seal_parser.add_argument("--hmac-key-file", type=Path, required=True)
    seal_parser.add_argument("--work-db", type=Path, required=True)
    seal_parser.add_argument("--db", type=Path, required=True)
    seal_parser.add_argument("--run-id", required=True)
    seal_parser.add_argument("--target-only", action="store_true")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--work-db", type=Path, required=True)
    status_parser.add_argument("--run-id", required=True)

    args = parser.parse_args()
    if args.command == "capture":
        try:
            from tools.agoda_browser_policy import legacy_browser_block
        except ImportError:  # pragma: no cover - direct script execution
            from agoda_browser_policy import legacy_browser_block
        return legacy_browser_block("agoda_portal_detail_capture.capture")

        result = capture_details(
            app=args.app,
            window_id=args.window_id,
            source_db=args.source_db,
            hmac_key_file=args.hmac_key_file,
            work_db=args.work_db,
            run_id=args.run_id,
            pages=args.pages,
            tabs=args.tabs,
            resume=args.resume,
            rebind_window=args.rebind_window,
            attempts_per_booking=args.attempts_per_booking,
            max_new_successes=args.max_new_successes,
            target_only=args.target_only,
            fast_direct=args.fast_direct,
            recapture_existing=args.recapture_existing,
        )
    elif args.command == "seal":
        result = seal_work_database(
            source_db=args.source_db,
            hmac_key_file=args.hmac_key_file,
            work_db=args.work_db,
            sealed_db=args.db,
            run_id=args.run_id,
            target_only=args.target_only,
        )
    else:
        result = _summary_from_work(args.work_db, args.run_id)
    print(_canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
