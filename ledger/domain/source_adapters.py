"""원천별 안정 식별자, 개인정보 제거, 금액·기간 정규화.

이 모듈은 원천 사실만 다룬다. 여행 귀속·계정·증빙 판정은 여기서 만들지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Mapping


CARD_EVENT_ID_VERSION = "card-event-v2"
OTA_REDACTION_VERSION = "ota-allowlist-v3"
OTA_LIFECYCLE_PARSER_VERSION = "ota-lifecycle-v2"
OTA_STATUS_RULE_VERSION = "ota-status-v2"
PG_REDACTION_VERSION = "pg-allowlist-v1"
SERVICE_MAIL_REDACTION_VERSION = "service-mail-allowlist-v1"

# PG mail is evidence at the same trust level as the typed OTA mail source,
# but only after it has been reduced to this allow-list.  Raw MIME, subjects,
# snippets, recipients, names, addresses, URLs, and account identifiers are
# intentionally not part of the persisted contract.
PG_ALLOWED_FIELDS = {
    "provider",
    "message_id",
    "thread_id",
    "sender_domain",
    "sent_at",
    "payment_at",
    "payment_date",
    "merchant",
    "product",
    "amount_krw",
    "cancel_amount_krw",
    "remaining_amount_krw",
    "approval_number",
    "original_approval_number",
    "order_id",
    "status",
    "service_start_on",
    "service_end_on",
    "service_date_precision",
    "service_evidence_key",
    "evidence_level",
    "source_type",
}

SERVICE_MAIL_ALLOWED_FIELDS = {
    "provider",
    "message_id",
    "sender_domain",
    "sent_at",
    "merchant",
    "property_name",
    "room_name",
    "service_start_on",
    "service_end_on",
    "status",
    "source_type",
}

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
    # Derived, non-content metadata retained so a month/day service date is
    # never assigned a year merely because the current schedule happens to be
    # 2026.  The raw subject is not stored.
    "sent_at",
    "message_status",
    "message_template_class",
    "lifecycle_parser_version",
    "message_status_rule_version",
    "service_year_candidates",
}

_OTA_CANDIDATE_FIELDS = {
    "amounts": ("amount_candidates", int),
    "pnrs": ("pnr_candidates", str),
    "bookingRefs": ("booking_ref_candidates", str),
    "travelDates": ("travel_date_candidates", str),
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


def _typed_ota_candidates(record: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    patterns = {
        "pnr_candidates": r"[A-Z0-9]{5,16}",
        "booking_ref_candidates": r"[0-9]+(?:-[0-9]+)*",
        "travel_date_candidates": r"(?:\d{4}|\d{4}-\d{2}-\d{2})",
    }
    for source, (target, kind) in _OTA_CANDIDATE_FIELDS.items():
        if source not in record:
            continue
        value = record[source]
        if not isinstance(value, list):
            raise ValueError(f"ota_candidate_type:{source}")
        values: list[object] = []
        for index, item in enumerate(value):
            if kind is int:
                if isinstance(item, bool) or not isinstance(item, int):
                    raise ValueError(f"ota_candidate_type:{source}:{index}")
            else:
                if not isinstance(item, str):
                    raise ValueError(f"ota_candidate_type:{source}:{index}")
                if not re.fullmatch(patterns[target], item):
                    raise ValueError(f"ota_candidate_pattern:{source}:{index}")
                if source == "bookingRefs" and not 8 <= len(item) <= 32:
                    raise ValueError(f"ota_candidate_length:{source}:{index}")
                if source == "travelDates":
                    try:
                        if re.fullmatch(r"\d{4}", item):
                            date(2000, int(item[:2]), int(item[2:]))
                        else:
                            date.fromisoformat(item)
                    except ValueError as exc:
                        raise ValueError(f"ota_candidate_date:{source}:{index}") from exc
            values.append(item)
        result[target] = values
    return result


def _normalized_ota_sent_at(value: object) -> str | None:
    """Return a canonical timestamp without retaining the raw mail header."""
    if value in (None, ""):
        return None
    text = _text(value)
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        # Accept an already ISO-8601 timestamp as well; this is useful for
        # future mailbox exports that do not use RFC-2822 headers.
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            raise ValueError("ota_sent_at_invalid") from None
    if parsed.tzinfo is None:
        # Some mailbox exports expose an ISO timestamp without an offset.
        # Keep that explicit as a naive local timestamp; date/year matching
        # remains valid and we do not fabricate a timezone.
        return parsed.replace(microsecond=0).isoformat()
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _ota_message_status(subject: object) -> str:
    """Derive a completed lifecycle state without treating policy text as an event.

    OTA confirmations often contain phrases such as ``무료 취소 가능``.  That
    phrase describes an option, not a cancellation that actually happened, so
    it must never close the active booking component.
    """
    text = _text(subject).lower()
    option_text = re.compile(
        r"취소\s*가능|환불\s*가능|무료\s*취소|"
        r"free\s+cancellation|cancel(?:lable|able)|can\s+cancel|"
        r"refundable"
    )
    if not option_text.search(text) and re.search(
        r"예약\s*취소|취소\s*(?:되었습니다|완료|처리|됨|안내)|"
        r"cancel(?:ed|led)|refund(?:ed)?|환불\s*(?:되었습니다|완료|처리|안내)",
        text,
    ):
        return "cancel"
    if re.search(
        r"변경\s*(?:되었습니다|완료|처리|안내)|업데이트\s*(?:됨|완료)|"
        r"updated|itinerary\s+changed|booking\s+changed|"
        r"change\s+confirmation",
        text,
    ) and not re.search(r"변경\s*가능|changeable", text):
        return "change"
    if any(token in text for token in (
        "확정", "예약", "order", "주문", "결제", "payment", "receipt",
        "청구", "confirmation", "confirmed",
    )):
        return "confirmation"
    return "unknown"


def _ota_service_year_candidates(subject: object) -> list[int]:
    """Extract explicit service years from subject metadata only."""
    years = sorted({
        int(value)
        for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", _text(subject))
        if 2020 <= int(value) <= 2100
    })
    return years


def adapt_ota_record(record: Mapping[str, object]) -> dict[str, object]:
    """Return the single canonical, typed OTA projection used by import and inventory."""
    if forbidden_ota_fields(record):
        raise ValueError("forbidden_ota_field")
    clean = sanitize_ota_record(record)
    for old, new in (("messageId", "message_id"), ("messageHash", "message_hash")):
        if old in record and new not in clean:
            value = record[old]
            if not isinstance(value, str) or not value:
                raise ValueError(f"ota_scalar_type:{old}")
            clean[new] = value
    sent_at = _normalized_ota_sent_at(record.get("sentAt", record.get("sent_at")))
    if sent_at is not None:
        clean["sent_at"] = sent_at
    clean["message_status"] = _ota_message_status(record.get("subject", ""))
    clean["message_template_class"] = clean["message_status"]
    clean["lifecycle_parser_version"] = OTA_LIFECYCLE_PARSER_VERSION
    clean["message_status_rule_version"] = OTA_STATUS_RULE_VERSION
    clean["service_year_candidates"] = _ota_service_year_candidates(
        record.get("subject", "")
    )
    for field, value in clean.items():
        if field not in {"redaction_version", "service_year_candidates"} and isinstance(
            value, (list, dict, tuple, set)
        ):
            raise ValueError(f"ota_scalar_type:{field}")
        if field == "service_year_candidates" and (
            not isinstance(value, list)
            or any(type(item) is not int or not 2020 <= item <= 2100 for item in value)
        ):
            raise ValueError("ota_service_year_candidates_invalid")
    candidates = _typed_ota_candidates(record)
    clean.update(candidates)
    clean["redaction_version"] = OTA_REDACTION_VERSION
    if forbidden_ota_fields(clean):
        raise ValueError("forbidden_ota_value")
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
    """표시액과 청구액을 정확값 또는 명시된 할인 근거로만 대사한다."""
    if booking_amount_krw in (None, 0):
        return "unknown", None
    reference = abs(int(booking_amount_krw))
    charge = abs(int(card_charge_krw))
    difference_ratio = abs(charge - reference) / reference
    if charge == reference:
        return "exact", 0.0
    if discount_krw and charge == abs(reference - abs(int(discount_krw))):
        return "discount_adjusted", difference_ratio
    # 해외 결제라는 사실만으로 금액 차이를 설명할 수 없다. 수수료·환율·
    # 할인처럼 원천에 명시된 조정식이 없으면 근사치는 후보 신호일 뿐이다.
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


def _pg_amount(value: object, field: str) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"pg_amount_type:{field}")
    text = str(value).replace(",", "").replace("원", "").strip()
    if not re.fullmatch(r"\d+", text):
        raise ValueError(f"pg_amount_invalid:{field}")
    return int(text)


def _pg_date(value: object, field: str) -> str | None:
    if value in (None, ""):
        return None
    text = _text(value)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"pg_date_invalid:{field}") from exc


def adapt_pg_record(record: Mapping[str, object]) -> dict[str, object]:
    """Normalize one PG receipt/cancellation into the persisted allow-list.

    The adapter deliberately rejects an unrecognised field instead of silently
    carrying raw mail content into SQLite.  A PG receipt is high-trust source
    evidence, not permission to infer a service period from its payment date.
    """
    if forbidden_ota_fields(record):
        raise ValueError("forbidden_pg_field")
    unknown = set(record) - PG_ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"pg_unknown_field:{sorted(str(item) for item in unknown)[0]}")
    message_id = _text(record.get("message_id"))
    if not message_id:
        raise ValueError("pg_message_id_missing")
    provider = _text(record.get("provider"))
    sender_domain = _text(record.get("sender_domain")).lower()
    if not provider or not sender_domain:
        raise ValueError("pg_provider_identity_missing")
    status = _text(record.get("status")).lower() or "purchase"
    if status not in {"purchase", "cancel", "partial_cancel", "refund"}:
        raise ValueError("pg_status_invalid")
    clean: dict[str, object] = {
        "provider": provider,
        "message_id": message_id,
        "sender_domain": sender_domain,
        "status": status,
        "evidence_level": _text(record.get("evidence_level")) or "high",
        "source_type": _text(record.get("source_type")) or "payment_receipt",
    }
    for field in ("thread_id", "merchant", "product", "approval_number",
                  "original_approval_number", "order_id", "service_evidence_key"):
        value = _text(record.get(field))
        if value:
            clean[field] = value
    for field in ("sent_at", "payment_at"):
        value = _text(record.get(field))
        if value:
            clean[field] = value
    for field in ("payment_date", "service_start_on", "service_end_on"):
        value = _pg_date(record.get(field), field)
        if value:
            clean[field] = value
    for field in ("amount_krw", "cancel_amount_krw", "remaining_amount_krw"):
        value = _pg_amount(record.get(field), field)
        if value is not None:
            clean[field] = value
    precision = _text(record.get("service_date_precision"))
    if precision:
        if precision not in {"day", "month_day", "unknown"}:
            raise ValueError("pg_service_date_precision_invalid")
        clean["service_date_precision"] = precision
    if clean.get("status") in {"cancel", "partial_cancel", "refund"} and not any(
        field in clean for field in ("cancel_amount_krw", "amount_krw")
    ):
        raise ValueError("pg_cancel_amount_missing")
    clean["redaction_version"] = PG_REDACTION_VERSION
    return clean


def adapt_service_mail_record(record: Mapping[str, object]) -> dict[str, object]:
    """Normalize an independent provider message containing a service date."""
    if forbidden_ota_fields(record):
        raise ValueError("forbidden_service_mail_field")
    unknown = set(record) - SERVICE_MAIL_ALLOWED_FIELDS
    if unknown:
        raise ValueError(
            f"service_mail_unknown_field:{sorted(str(item) for item in unknown)[0]}"
        )
    message_id = _text(record.get("message_id"))
    provider = _text(record.get("provider"))
    sender_domain = _text(record.get("sender_domain")).lower()
    if not message_id or not provider or not sender_domain:
        raise ValueError("service_mail_identity_missing")
    start = _pg_date(record.get("service_start_on"), "service_start_on")
    end = _pg_date(record.get("service_end_on"), "service_end_on") or start
    if not start or not end or end < start:
        raise ValueError("service_mail_period_invalid")
    status = _text(record.get("status")) or "confirmed"
    if status not in {"confirmed", "payment", "cancel", "refund"}:
        raise ValueError("service_mail_status_invalid")
    clean: dict[str, object] = {
        "provider": provider,
        "message_id": message_id,
        "sender_domain": sender_domain,
        "service_start_on": start,
        "service_end_on": end,
        "status": status,
        "source_type": _text(record.get("source_type")) or "service_confirmation",
        "redaction_version": SERVICE_MAIL_REDACTION_VERSION,
    }
    for field in ("sent_at", "merchant", "property_name", "room_name"):
        value = _text(record.get(field))
        if value:
            clean[field] = value
    return clean
