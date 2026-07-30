"""원천별 안정 식별자, 개인정보 제거, 금액·기간 정규화.

이 모듈은 원천 사실만 다룬다. 여행 귀속·계정·증빙 판정은 여기서 만들지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Mapping


CARD_EVENT_ID_VERSION = "card-event-v2"
OTA_REDACTION_VERSION = "ota-allowlist-v1"

OTA_ALLOWED_FIELDS = {
    "provider",
    "message_id",
    "message_hash",
    "booking_number",
    "order_id",
    "pnr",
    "product_type",
    "service_start_on",
    "service_end_on",
    "date_precision",
    "period_original",
    "merchant",
    "currency",
    "booking_display_amount",
    "discount_amount",
    "points_amount",
    "onsite_amount",
    "payment_date",
    "card_last4",
    "status",
}


@dataclass(frozen=True)
class CardEventIdentity:
    card_event_id: str
    generator_version: str
    identity_status: str
    structural_payload: dict[str, object]


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _decimal_text(value: object) -> str:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return ""
    try:
        return format(Decimal(text).normalize(), "f")
    except InvalidOperation:
        return text


def _strict_occurrence_date(row: Mapping[str, object]) -> str | None:
    value = _text(row.get("use_date") or row.get("occurred_on"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        normalized = date.fromisoformat(value).isoformat()
    except ValueError:
        return None
    return normalized if normalized == value else None


def _hash_payload(namespace: str, payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(f"{namespace}:{canonical}".encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def stable_card_event_identity(row: Mapping[str, object]) -> CardEventIdentity:
    """카드사 구조 키로 이벤트 ID를 만든다.

    승인번호가 있으면 카드·승인번호·거래종류가 핵심이다. 승인번호가 없는 국민해외
    등은 카드4·통화·원통화금액·이용일·매입일·원천행 식별자를 사용한다. 마지막
    식별자까지 없는 legacy 행은 자동 병합할 수 없는 fallback으로 표시한다.
    """
    source = _text(row.get("src") or row.get("source_system")).upper() or "UNKNOWN"
    approval = _digits(row.get("appr") or row.get("approval_number"))
    original_approval = _digits(row.get("orig_appr"))
    amount_krw = int(round(float(str(row.get("krw") or row.get("amount_krw") or 0).replace(",", ""))))
    cancelled = str(row.get("cancel") or "").lower() in {"1", "true", "yes", "y"}
    event_kind = "refund" if amount_krw < 0 or cancelled else "purchase"
    stable_source_locator = _text(
        row.get("raw_record_id")
        or row.get("source_row_id")
        or row.get("source_event_id")
    )
    legacy_locator = _text(row.get("uid"))
    source_locator = stable_source_locator or legacy_locator

    if approval:
        occurred_on = _strict_occurrence_date(row)
        payload: dict[str, object] = {
            "source": source,
            "card4": _digits(row.get("card4"))[-4:],
            "approval": approval,
            "original_approval": original_approval,
            "event_kind": event_kind,
            "occurred_on": occurred_on or "",
        }
        status = "unique" if occurred_on else "legacy_fallback"
    else:
        payload = {
            "source": source,
            "card4": _digits(row.get("card4"))[-4:],
            "occurred_on": _text(row.get("use_date") or row.get("occurred_on")),
            "posted_on": _text(row.get("post_date") or row.get("posted_on")),
            "currency": _text(row.get("currency")).upper(),
            "foreign_amount": _decimal_text(
                row.get("foreign") or row.get("foreign_amount")
            ),
            "event_kind": event_kind,
            "source_locator": source_locator,
        }
        status = "unique" if stable_source_locator else "legacy_fallback"

    return CardEventIdentity(
        card_event_id=_hash_payload("card", payload),
        generator_version=CARD_EVENT_ID_VERSION,
        identity_status=status,
        structural_payload=payload,
    )


def mark_identity_collisions(
    identities: list[CardEventIdentity],
) -> list[CardEventIdentity]:
    """같은 구조 ID가 여러 행에 나오면 삭제하지 않고 모두 collision으로 표시한다."""
    counts: dict[str, int] = {}
    for identity in identities:
        counts[identity.card_event_id] = counts.get(identity.card_event_id, 0) + 1
    return [
        CardEventIdentity(
            identity.card_event_id,
            identity.generator_version,
            "collision" if counts[identity.card_event_id] > 1 else identity.identity_status,
            identity.structural_payload,
        )
        for identity in identities
    ]


def sanitize_ota_record(record: Mapping[str, object]) -> dict[str, object]:
    """OTA 원문 대신 대사에 필요한 허용 필드만 반환한다."""
    clean = {
        key: record[key]
        for key in OTA_ALLOWED_FIELDS
        if key in record and record[key] not in (None, "")
    }
    clean["redaction_version"] = OTA_REDACTION_VERSION
    return clean


def forbidden_ota_fields(record: Mapping[str, object]) -> set[str]:
    normalized = {
        re.sub(r"[^0-9a-z가-힣]", "", str(key).lower())
        for key in record
    }
    forbidden_tokens = {
        "pin", "password", "birth", "birthdate", "dob", "phone", "email",
        "passport", "생년월일", "전화번호", "연락처", "이메일", "여권",
    }
    return {
        key for key in normalized
        if any(token in key for token in forbidden_tokens)
    }


def reconcile_amount(
    card_charge_krw: int,
    booking_amount_krw: int | None,
    *,
    discount_krw: int = 0,
    overseas_krw: bool = False,
) -> tuple[str, float | None]:
    """표시액과 청구액의 대사 유형을 반환한다."""
    if booking_amount_krw in (None, 0):
        return "unknown", None
    reference = abs(int(booking_amount_krw))
    charge = abs(int(card_charge_krw))
    difference_ratio = abs(charge - reference) / reference
    if charge == reference:
        return "exact", 0.0
    if discount_krw and charge == abs(reference - abs(int(discount_krw))):
        return "discount_adjusted", difference_ratio
    if overseas_krw and difference_ratio <= 0.02:
        return "within_2_percent", difference_ratio
    return "mismatch", difference_ratio


def normalize_service_period(
    start: object,
    end: object = None,
    *,
    original_text: str = "",
) -> tuple[str | None, str | None, str, str]:
    """ISO 날짜 또는 MMDD 기간을 정밀도와 함께 보존한다."""
    start_text = _text(start)
    end_text = _text(end)
    try:
        start_iso = date.fromisoformat(start_text).isoformat()
        end_iso = date.fromisoformat(end_text).isoformat() if end_text else start_iso
        return start_iso, end_iso, "day", original_text or start_text
    except ValueError:
        pass
    if re.fullmatch(r"\d{4}", start_text) and (
        not end_text or re.fullmatch(r"\d{4}", end_text)
    ):
        return start_text, end_text or start_text, "month_day", original_text or start_text
    return None, None, "unknown", original_text or " ".join(filter(None, (start_text, end_text)))
