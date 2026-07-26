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
OTA_REDACTION_VERSION = "ota-allowlist-v5"

OTA_ALLOWED_FIELDS = {
    "provider",
    "source_channel",
    "message_id",
    "message_hash",
    "observed_at",
    "booking_number",
    "reference_code",
    "order_id",
    "pnr",
    "passenger_count",
    "room_count",
    "product_type",
    "service_start_on",
    "service_end_on",
    "date_precision",
    "period_original",
    "merchant",
    "currency",
    "foreign_amount",
    "booking_display_amount",
    "booking_display_amounts",
    "amount_candidates",
    "booking_numbers",
    "pnrs",
    "travel_dates",
    "discount_amount",
    "points_amount",
    "onsite_amount",
    "payment_date",
    "card_last4",
    "status",
    "record_type",
    "booking_confirmation_status",
    "settlement_condition",
    "cancellation_condition",
    "attachment_state",
    "attachment_count",
    "attachment_mime_types",
    "attachment_receipt_detected",
    "forwarded_content_detected",
    "forwarded_content_extracted",
    "extraction_sources",
}

OTA_FIELD_ALIASES = {
    "messageId": "message_id",
    "messageHash": "message_hash",
    "bookingRefs": "booking_numbers",
    "travelDates": "travel_dates",
    "amounts": "booking_display_amounts",
    "cardLast4": "card_last4",
    "amountCandidates": "amount_candidates",
    "attachmentState": "attachment_state",
    "attachmentCount": "attachment_count",
    "attachmentMimeTypes": "attachment_mime_types",
    "attachmentReceiptDetected": "attachment_receipt_detected",
    "forwardedContentDetected": "forwarded_content_detected",
    "forwardedContentExtracted": "forwarded_content_extracted",
    "extractionSources": "extraction_sources",
    # Apps Script Gmail staging fields.  The aliases let its privacy-safe rows
    # feed the direct OTA importer without copying a mail body or memo.
    "source": "provider",
    "type": "record_type",
    "bookingNo": "booking_number",
    "serviceStartOn": "service_start_on",
    "serviceEndOn": "service_end_on",
    "bookingStatus": "booking_confirmation_status",
    "settlementCondition": "settlement_condition",
    "passengerCount": "passenger_count",
    "roomCount": "room_count",
    "cancellationCondition": "cancellation_condition",
}

OTA_ATTACHMENT_STATES = {
    "none",
    "present_unread",
    "text_extracted",
    "unsupported",
    "read_error",
}

OTA_AMOUNT_ROLES = {
    "displayed_total",
    "settled_charge",
    "attempted_amount",
    "scheduled_amount",
    "pay_at_property_total",
    "hold_amount",
    "deposit",
    "expected_refund",
    "settled_refund",
}

OTA_EXTRACTION_SOURCES = {
    "message_body",
    "attachment_text",
    "forwarded_message",
    "authenticated_portal_dom",
}

OTA_SOURCE_CHANNELS = {
    "mail",
    "authenticated_booking_portal",
}

OTA_BOOKING_CONFIRMATION_STATUSES = {"confirmed"}
OTA_RECORD_TYPES = {
    "charge", "refund", "refund_pending", "payment_confirmation", "update",
    "invoice", "evidence_only", "payment_failed", "payment_scheduled",
    "pay_at_property", "authorization_hold_possible", "cancel_no_charge",
}
OTA_SETTLEMENT_CONDITIONS = {
    "refundable_deposit_pending",
    "authorization_hold_possible",
}
OTA_CANCELLATION_CONDITIONS = {
    "refundable",
    "nonrefundable",
    "no_show_charge",
    "change_fee",
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
        payload: dict[str, object] = {
            "source": source,
            "card4": _digits(row.get("card4"))[-4:],
            "approval": approval,
            "original_approval": original_approval,
            "event_kind": event_kind,
            # Approval numbers are not globally unique in the supplied Hana
            # lifecycle rows.  Preserve separate exact events sharing an
            # approval number (Hertz/Avis/Sicily) instead of collapsing them.
            "amount_krw": amount_krw,
            "occurred_on": _text(row.get("use_date") or row.get("occurred_on")),
            "source_locator": stable_source_locator,
        }
        status = "unique"
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


def _ota_text_list(value: object) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    for item in values:
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return result


def _ota_pnr_list(value: object) -> list[str]:
    """Keep reservation locators, never free-form passenger text."""
    result: list[str] = []
    for item in _ota_text_list(value):
        normalized = re.sub(r"[^0-9A-Z]", "", item.upper())
        if re.fullmatch(r"[0-9A-Z]{5,8}", normalized) and normalized not in result:
            result.append(normalized)
    return result


def _ota_amount_candidates(value: object) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, object]] = []
    for candidate in value:
        if not isinstance(candidate, Mapping):
            continue
        amount = _decimal_text(candidate.get("amount"))
        currency = _text(candidate.get("currency")).upper()
        role = _text(candidate.get("role"))
        source = _text(candidate.get("source"))
        if not amount or not currency or role not in OTA_AMOUNT_ROLES:
            continue
        clean: dict[str, object] = {
            "amount": amount,
            "currency": currency,
            "role": role,
        }
        if source in OTA_EXTRACTION_SOURCES:
            clean["source"] = source
        result.append(clean)
    return result


def _ota_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "y"}


def sanitize_ota_record(record: Mapping[str, object]) -> dict[str, object]:
    """Return the privacy-safe, loss-aware OTA mail-index contract.

    Collector aliases are normalized before the allowlist is applied.  This
    retains attachment/forwarded extraction provenance without storing
    filenames, addresses, or attachment contents.
    """
    normalized = dict(record)
    for old, new in OTA_FIELD_ALIASES.items():
        if old in normalized and new not in normalized:
            normalized[new] = normalized[old]
    has_attachments = normalized.get(
        "hasAttachments",
        normalized.get("hasAttachment", normalized.get("has_attachment")),
    )
    attachment_rows = normalized.get("attachments")
    if isinstance(attachment_rows, (list, tuple)):
        normalized.setdefault("attachment_count", len(attachment_rows))
        mime_types = [
            row.get("mime_type") or row.get("mimeType")
            for row in attachment_rows
            if isinstance(row, Mapping)
        ]
        normalized.setdefault("attachment_mime_types", mime_types)
        has_attachments = bool(attachment_rows)
    if "attachment_state" not in normalized and has_attachments is not None:
        normalized["attachment_state"] = (
            "present_unread" if _ota_bool(has_attachments) else "none"
        )
    clean = {
        key: normalized[key]
        for key in OTA_ALLOWED_FIELDS
        if key in normalized and normalized[key] not in (None, "")
    }
    for key in (
        "booking_numbers",
        "travel_dates",
        "attachment_mime_types",
        "extraction_sources",
    ):
        if key in clean:
            clean[key] = _ota_text_list(clean[key])
    if "pnrs" in clean:
        clean["pnrs"] = _ota_pnr_list(clean["pnrs"])
    if "pnr" in clean:
        pnrs = _ota_pnr_list(clean["pnr"])
        if pnrs:
            clean["pnr"] = pnrs[0]
        else:
            clean.pop("pnr", None)
    if "attachment_mime_types" in clean:
        clean["attachment_mime_types"] = [
            value
            for value in clean["attachment_mime_types"]
            if re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", value.lower())
        ]
        if "message/rfc822" in {
            value.lower() for value in clean["attachment_mime_types"]
        }:
            clean.setdefault("forwarded_content_detected", True)
    if "extraction_sources" in clean:
        clean["extraction_sources"] = [
            value for value in clean["extraction_sources"]
            if value in OTA_EXTRACTION_SOURCES
        ]
    if "amount_candidates" in clean:
        clean["amount_candidates"] = _ota_amount_candidates(clean["amount_candidates"])
    for key, allowed in (
        ("source_channel", OTA_SOURCE_CHANNELS),
        ("booking_confirmation_status", OTA_BOOKING_CONFIRMATION_STATUSES),
        ("record_type", OTA_RECORD_TYPES),
        ("settlement_condition", OTA_SETTLEMENT_CONDITIONS),
        ("cancellation_condition", OTA_CANCELLATION_CONDITIONS),
    ):
        if key in clean:
            clean[key] = _text(clean[key]).lower()
            if clean[key] not in allowed:
                clean.pop(key, None)
    for key in ("service_start_on", "service_end_on"):
        if key not in clean:
            continue
        try:
            clean[key] = date.fromisoformat(_text(clean[key])).isoformat()
        except ValueError:
            clean.pop(key, None)
    for key in ("passenger_count", "room_count"):
        if key not in clean:
            continue
        try:
            count = int(clean[key])
        except (TypeError, ValueError):
            clean.pop(key, None)
            continue
        if count > 0:
            clean[key] = count
        else:
            clean.pop(key, None)
    if "card_last4" in clean:
        last4 = _digits(clean["card_last4"])[-4:]
        if len(last4) == 4:
            clean["card_last4"] = last4
        else:
            clean.pop("card_last4", None)
    if "attachment_count" in clean:
        try:
            clean["attachment_count"] = max(0, int(clean["attachment_count"]))
        except (TypeError, ValueError):
            clean.pop("attachment_count", None)
    if _text(clean.get("attachment_state")) not in OTA_ATTACHMENT_STATES:
        clean.pop("attachment_state", None)
    for key in (
        "attachment_receipt_detected",
        "forwarded_content_detected",
        "forwarded_content_extracted",
    ):
        if key in clean:
            clean[key] = _ota_bool(clean[key])
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


def confirmed_booking_service_start(
    record: Mapping[str, object],
) -> dict[str, str] | None:
    """Return a direct-booking period only when the mail is decisive.

    This deliberately refuses evidence-only correspondence, multiple booking
    references, month/day-only dates, and unconfirmed mail.  The returned
    fields are allowlisted identifiers and dates only; no message body, name,
    address, PIN, or attachment content crosses this boundary.
    """
    if _text(record.get("record_type")).lower() == "evidence_only":
        return None
    if _text(record.get("booking_confirmation_status")).lower() != "confirmed":
        return None
    numbers = _ota_text_list(record.get("booking_numbers"))
    singular = _text(record.get("booking_number"))
    if singular and singular not in numbers:
        numbers.append(singular)
    if len(numbers) != 1:
        return None
    try:
        start_on = date.fromisoformat(_text(record.get("service_start_on"))).isoformat()
    except ValueError:
        return None
    result = {
        "provider": _text(record.get("provider")).lower() or "unknown",
        "booking_number": numbers[0],
        "service_start_on": start_on,
    }
    try:
        end_on = date.fromisoformat(_text(record.get("service_end_on"))).isoformat()
    except ValueError:
        end_on = ""
    if end_on:
        result["service_end_on"] = end_on
    condition = _text(record.get("settlement_condition")).lower()
    if condition in OTA_SETTLEMENT_CONDITIONS:
        result["settlement_condition"] = condition
    return result


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
