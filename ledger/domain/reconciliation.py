"""Lossless card coverage, OTA match groups, refunds, and close gates.

This module deliberately does not guess a trip when evidence conflicts.  It
stores every card event, records all comparable OTA signals, and makes period
close fail until each event has a final accounting disposition.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from itertools import permutations
from typing import Iterable, Mapping


FINAL_DISPOSITIONS = {
    "trip",
    "overhead",
    "leader",
    "cancellation_refund",
    "clearing",
    "prepaid_future_trip",
}

NONPOSTING_SOURCE_DISPOSITIONS = {
    "superseded_duplicate_projection",
    "manual_claimed_card_no_raw",
    "rejected_legacy_projection",
}


def _integer_amount(value: object) -> int:
    try:
        return int(round(float(str(value or "0").replace(",", ""))))
    except (TypeError, ValueError):
        return 0
MATCH_STATUSES = {
    "confirmed_strong",
    "confirmed_manual",
    "proposed",
    "conflict",
    "unmatched",
}

STRONG_IDENTIFIER_SIGNALS = {
    "booking_number",
    "order_number",
    "pnr",
    "approval_number",
}
STRONG_CONFIRMATION_BLOCKERS = {
    "ota_field_loss",
    "attachment_required",
    "forwarded_unextracted",
    "amount_currency_unresolved",
}
SAFE_SIGNAL_EVIDENCE_KEYS = {
    "source_type",
    "source_channel",
    "message_id",
    "source_record_id",
    "provider",
    "attachment_id",
    "attachment_state",
    "forwarded_state",
    "amount_currency_state",
    "ota_field_loss_state",
    "extraction_source",
    "filename",
    "mime_type",
}
BLOCKING_ATTACHMENT_STATES = {
    "present_unread",
    "required_missing",
    "unsupported",
    "read_error",
}
BLOCKING_FORWARDED_STATES = {"detected_unextracted"}
BLOCKING_AMOUNT_CURRENCY_STATES = {"missing", "unresolved", "ambiguous"}
ALLOWED_ATTACHMENT_STATES = {"none", "present_read", "not_applicable"}
ALLOWED_FORWARDED_STATES = {"not_forwarded", "extracted", "not_applicable"}
ALLOWED_OTA_FIELD_LOSS_STATES = {"clear", "not_applicable"}
BLOCKING_NOTE_SOURCE_TYPES = {
    "note",
    "manual_note",
    "card_note",
    "ledger_note",
    "unverified_note",
    "booking_info",
    "booking_info_only",
    "title",
    "title_only",
    "subject",
    "subject_only",
    "email_title",
    "message_title",
}
ALLOWED_OTA_EXTRACTION_SOURCES = {
    "message_body",
    "gmail_body",
    "attachment_text",
    "forwarded_message",
    "authenticated_portal_dom",
}


def _safe_signal_evidence(evidence: object) -> list[dict[str, object]]:
    if not isinstance(evidence, (list, tuple)):
        return []
    return [
        {
            key: item[key]
            for key in SAFE_SIGNAL_EVIDENCE_KEYS
            if key in item and item[key] not in (None, "")
        }
        for item in evidence
        if isinstance(item, Mapping)
    ]


def verification_dimensions(
    *,
    card_source_event_ids: Iterable[object],
    signal_rows: Iterable[Mapping[str, object]],
) -> dict[str, bool]:
    """Keep card, OTA, travel and service-period proof as separate facts.

    A card source event proves the payment only.  A mail title, note, or
    booking-info value is never OTA proof.  A verified OTA identifier is not
    period proof unless both service boundaries are independently matched.
    """
    source_ids = [str(value or "") for value in card_source_event_ids]
    card_verified = bool(source_ids) and all(value.startswith("card:") for value in source_ids)
    trusted_identifier_names = {"booking_number", "order_number", "pnr", "approval_number"}

    def trusted(signal: Mapping[str, object]) -> bool:
        if signal.get("status") != "match":
            return False
        evidence = _safe_signal_evidence(signal.get("evidence"))
        if not evidence:
            return False
        for item in evidence:
            source_type = str(item.get("source_type") or "").lower()
            extraction_source = str(item.get("extraction_source") or "").lower()
            if (
                not (item.get("message_id") or item.get("source_record_id"))
                or source_type in BLOCKING_NOTE_SOURCE_TYPES
                or (extraction_source and extraction_source not in ALLOWED_OTA_EXTRACTION_SOURCES)
                or str(item.get("attachment_state") or "") not in ALLOWED_ATTACHMENT_STATES
                or str(item.get("forwarded_state") or "") not in ALLOWED_FORWARDED_STATES
                or str(item.get("ota_field_loss_state") or "") not in ALLOWED_OTA_FIELD_LOSS_STATES
            ):
                return False
        return True

    rows = list(signal_rows)
    direct_ota_evidence = any(
        trusted(row)
        and any(
            str(item.get("source_type") or "").lower()
            in {
                "ota_mail",
                "ota_authenticated_portal",
                "direct_receipt",
                "gmail_receipt",
            }
            and bool(item.get("message_id") or item.get("source_record_id"))
            for item in _safe_signal_evidence(row.get("evidence"))
        )
        for row in rows
    )
    matched_axes = {
        str(row.get("name") or "")
        for row in rows
        if trusted(row)
        and str(row.get("name") or "")
        in {"amount", "provider", "occurred_on", "product_type"}
    }
    ota_verified = (
        direct_ota_evidence
        and any(
            str(row.get("name") or "") in trusted_identifier_names and trusted(row)
            for row in rows
        )
        and len(matched_axes) >= 3
    )
    travel_verified = any(
        str(row.get("name") or "") in {"booking_number", "order_number", "pnr"}
        and trusted(row)
        for row in rows
    )
    period_names = {"service_start_on", "service_end_on"}
    period_verified = (
        travel_verified
        and period_names.issubset({str(row.get("name") or "") for row in rows if trusted(row)})
    )
    # Payment-mail amount and a separate ticket/PNR mail are leads, not a
    # lineage.  Strong classification needs one direct evidence lineage that
    # carries every required matched fact; date/provider/route proximity may
    # score a candidate but cannot bridge this gap.
    required_names = trusted_identifier_names | {"amount", "provider", "occurred_on", "product_type"} | period_names
    lineage_sets = []
    for row in rows:
        if not trusted(row) or str(row.get("name") or "") not in required_names:
            continue
        ids = {
            str(item.get("message_id") or item.get("source_record_id") or "")
            for item in _safe_signal_evidence(row.get("evidence"))
            if item.get("message_id") or item.get("source_record_id")
        }
        if ids:
            lineage_sets.append(ids)
    direct_lineage_complete = bool(lineage_sets) and bool(set.intersection(*lineage_sets))
    return {
        "card_verified": card_verified,
        "ota_verified": ota_verified,
        "travel_verified": travel_verified,
        "period_verified": period_verified,
        "strong_travel_classification_ready": (
            card_verified and ota_verified and travel_verified and period_verified
            and direct_lineage_complete
        ),
    }


def _validate_strong_confirmation(
    db: sqlite3.Connection,
    payment_ids: list[int],
    signal_rows: list[Mapping[str, object]],
    booking_ids: list[int] | None = None,
) -> None:
    if any(s.get("status") == "mismatch" for s in signal_rows):
        raise ValueError("충돌 신호가 있는 그룹은 confirmed_strong일 수 없습니다.")
    blocking_signals = [
        str(s.get("name") or "")
        for s in signal_rows
        if s.get("name") in STRONG_CONFIRMATION_BLOCKERS
        and s.get("status") != "match"
    ]
    if blocking_signals:
        raise ValueError(
            "미해결 OTA 수집 차단 신호가 있어 confirmed_strong일 수 없습니다: "
            + ", ".join(sorted(set(blocking_signals)))
        )

    eligible = [
        signal
        for signal in signal_rows
        if signal.get("status") == "match"
        and signal.get("name") in STRONG_IDENTIFIER_SIGNALS
    ]
    if len(payment_ids) > 1 and eligible and all(
        signal.get("name") == "unique_amount_group" for signal in eligible
    ):
        raise ValueError(
            "복수 결제는 동일금액 그룹만으로 confirmed_strong 처리할 수 없습니다. "
            "각 결제의 승인번호와 예약번호/주문번호/PNR 식별이 필요합니다."
        )
    if not eligible:
        raise ValueError(
            "confirmed_strong에는 예약/주문/PNR/승인번호 또는 "
            "유일 금액그룹 일치가 필요합니다."
        )
    if booking_ids and not any(
        signal.get("name") in {"booking_number", "order_number", "pnr"}
        for signal in eligible
    ):
        raise ValueError(
            "카드 승인/관계 확정은 예약·여행 연결을 확정하지 않습니다. "
            "예약번호·주문번호·PNR의 독립 OTA 근거가 필요합니다."
        )

    payment_event_ids = (
        {
            str(row["source_event_id"])
            for row in db.execute(
                f"""
                SELECT source_event_id
                FROM payment_transactions
                WHERE id IN ({','.join('?' for _ in payment_ids)})
                """,
                payment_ids,
            ).fetchall()
        }
        if payment_ids
        else set()
    )
    failures: list[str] = []
    for signal in eligible:
        name = str(signal.get("name") or "")
        source_event_id = str(signal.get("source_event_id") or "")
        evidence = _safe_signal_evidence(signal.get("evidence"))
        if not source_event_id or source_event_id not in payment_event_ids:
            failures.append(f"{name}:source_event_id")
            continue
        if not evidence or not any(
            item.get("message_id") or item.get("source_record_id")
            for item in evidence
        ):
            failures.append(f"{name}:evidence_lineage")
            continue
        attachment_states = {
            str(item.get("attachment_state") or "") for item in evidence
        }
        forwarded_states = {
            str(item.get("forwarded_state") or "") for item in evidence
        }
        currency_states = {
            str(item.get("amount_currency_state") or "") for item in evidence
        }
        field_loss_states = {
            str(item.get("ota_field_loss_state") or "") for item in evidence
        }
        source_types = {
            str(item.get("source_type") or "").strip().lower()
            for item in evidence
            if item.get("source_type")
        }
        extraction_sources = {
            str(item.get("extraction_source") or "").strip().lower()
            for item in evidence
            if item.get("extraction_source")
        }
        if (
            not attachment_states
            or attachment_states & BLOCKING_ATTACHMENT_STATES
            or not attachment_states.issubset(ALLOWED_ATTACHMENT_STATES)
        ):
            failures.append(f"{name}:attachment_state")
        if (
            not forwarded_states
            or forwarded_states & BLOCKING_FORWARDED_STATES
            or not forwarded_states.issubset(ALLOWED_FORWARDED_STATES)
        ):
            failures.append(f"{name}:forwarded_state")
        if currency_states & BLOCKING_AMOUNT_CURRENCY_STATES:
            failures.append(f"{name}:amount_currency_state")
        if (
            not field_loss_states
            or not field_loss_states.issubset(ALLOWED_OTA_FIELD_LOSS_STATES)
        ):
            failures.append(f"{name}:ota_field_loss_state")
        if source_types & BLOCKING_NOTE_SOURCE_TYPES:
            failures.append(f"{name}:source_type")
        if extraction_sources and not extraction_sources.issubset(
            ALLOWED_OTA_EXTRACTION_SOURCES
        ):
            failures.append(f"{name}:extraction_source")
        if name == "unique_amount_group" and "resolved" not in currency_states:
            failures.append(f"{name}:amount_currency_state")
    if failures:
        raise ValueError(
            "강확정 증거 계보가 불완전합니다: "
            + ", ".join(sorted(set(failures)))
        )


def _reject_confirmation_conflicts(
    signal_rows: Iterable[Mapping[str, object]],
    *,
    status: str,
) -> None:
    conflicts = sorted(
        {
            str(signal.get("name") or "")
            for signal in signal_rows
            if signal.get("status") == "mismatch"
        }
    )
    if conflicts:
        raise ValueError(
            f"{status}은 명시적 충돌 신호를 허용하지 않습니다: "
            + ", ".join(conflicts)
        )


def _normalized_signal_value(name: str, value: object) -> str:
    if name == "foreign_amount":
        try:
            return format(
                Decimal(str(value).replace(",", "")).normalize(),
                "f",
            )
        except (InvalidOperation, ValueError):
            pass
    if name in {"amount", "unique_amount_group"}:
        try:
            return str(abs(int(round(float(str(value).replace(",", ""))))))
        except (TypeError, ValueError):
            pass
    return re.sub(r"[^0-9A-Z가-힣]", "", str(value).upper())


def _validate_signal_consistency(
    signal_rows: Iterable[Mapping[str, object]],
) -> None:
    inconsistent: list[str] = []
    for signal in signal_rows:
        name = str(signal.get("name") or "")
        if name in STRONG_CONFIRMATION_BLOCKERS:
            continue
        status = str(signal.get("status") or "")
        left = signal.get("left")
        right = signal.get("right")
        left_present = left not in (None, "")
        right_present = right not in (None, "")
        if name == "merchant" and left_present and right_present:
            left_normalized = _normalized_signal_value(name, left)
            right_normalized = _normalized_signal_value(name, right)
            equal = bool(
                left_normalized
                and right_normalized
                and (
                    left_normalized in right_normalized
                    or right_normalized in left_normalized
                )
            )
        else:
            equal = (
                left_present
                and right_present
                and _normalized_signal_value(name, left)
                == _normalized_signal_value(name, right)
            )
        if status == "match" and (not left_present or not right_present or not equal):
            inconsistent.append(name)
        elif status == "mismatch" and (
            not left_present or not right_present or equal
        ):
            inconsistent.append(name)
        elif status == "unavailable" and left_present and right_present:
            inconsistent.append(name)
    if inconsistent:
        raise ValueError(
            "신호 상태와 좌우 값이 모순됩니다: "
            + ", ".join(sorted(set(inconsistent)))
        )


def _reject_confirmed_member_reuse(
    db: sqlite3.Connection,
    *,
    group_id: int | None,
    payment_ids: Iterable[int],
    booking_ids: Iterable[int],
) -> None:
    reused: list[str] = []
    for payment_id in payment_ids:
        rows = db.execute(
            """
            SELECT DISTINCT g.group_key
            FROM current_match_group_projection g
            JOIN match_group_payments m ON m.group_id=g.group_id
            WHERE m.payment_id=?
              AND g.status IN ('confirmed_strong', 'confirmed_manual')
              AND (? IS NULL OR g.group_id<>?)
            """,
            (payment_id, group_id, group_id),
        ).fetchall()
        reused.extend(
            f"payment:{payment_id}@{row['group_key']}" for row in rows
        )
    for booking_id in booking_ids:
        rows = db.execute(
            """
            SELECT DISTINCT g.group_key
            FROM current_match_group_projection g
            JOIN match_group_bookings m ON m.group_id=g.group_id
            WHERE m.booking_id=?
              AND g.status IN ('confirmed_strong', 'confirmed_manual')
              AND (? IS NULL OR g.group_id<>?)
            """,
            (booking_id, group_id, group_id),
        ).fetchall()
        reused.extend(
            f"booking:{booking_id}@{row['group_key']}" for row in rows
        )
    if reused:
        raise ValueError(
            "이미 다른 확정 그룹이 소비한 카드/예약입니다: "
            + ", ".join(sorted(set(reused)))
        )


def intersection_signals(
    card: Mapping[str, object],
    ota: Mapping[str, object],
) -> list[dict[str, object]]:
    """Compare only fields present on both sides, preserving every conflict."""
    aliases = (
        ("approval_number", "approval_number", "approval_number"),
        ("card_suffix", "card4", "card4"),
        ("booking_number", "booking_number", "booking_number"),
        ("order_number", "order_number", "order_number"),
        ("pnr", "pnr", "pnr"),
        ("amount", "amount_krw", "amount_krw"),
        ("currency", "currency", "currency"),
        ("occurred_on", "occurred_on", "payment_date"),
        ("merchant", "merchant", "merchant"),
        ("service_start_on", "service_start_on", "service_start_on"),
        ("service_end_on", "service_end_on", "service_end_on"),
        ("foreign_amount", "foreign_amount", "foreign_amount"),
    )
    results: list[dict[str, object]] = []
    for name, card_key, ota_key in aliases:
        left = card.get(card_key)
        right = ota.get(ota_key)
        if left in (None, "") or right in (None, ""):
            status = "unavailable"
        elif name == "amount":
            status = "match" if abs(int(left)) == abs(int(right)) else "mismatch"
        elif name == "merchant":
            left_norm = re.sub(r"[^0-9A-Z]", "", str(left).upper())
            right_norm = re.sub(r"[^0-9A-Z]", "", str(right).upper())
            status = (
                "match"
                if left_norm
                and right_norm
                and (left_norm in right_norm or right_norm in left_norm)
                else "mismatch"
            )
        else:
            left_norm = _normalized_signal_value(name, left)
            right_norm = _normalized_signal_value(name, right)
            status = "match" if left_norm == right_norm else "mismatch"
        results.append(
            {
                "name": name,
                "status": status,
                "left": left,
                "right": right,
                "rule_id": "intersection-v1",
            }
        )
    return results


def reconcile_repeated_amount_ota_group(
    card_events: Iterable[Mapping[str, object]],
    ota_events: Iterable[Mapping[str, object]],
    proposed_allocations: Mapping[str, str] | None = None,
    *,
    max_time_delta_seconds: int = 15 * 60,
) -> dict[str, object]:
    """Resolve equal-amount payments before evaluating trip allocation.

    Individual card↔OTA identity requires a unique card approval, a unique OTA
    booking reference, and a unique one-to-one issue/mail-time assignment.
    A confirmed payment identity never proves the downstream trip allocation.
    """

    cards = list(card_events)
    otas = list(ota_events)
    allocations = {
        str(card_id): str(trip_code)
        for card_id, trip_code in (proposed_allocations or {}).items()
    }

    def event_time(
        event: Mapping[str, object],
        names: tuple[str, ...],
    ) -> tuple[datetime | None, str]:
        for name in names:
            raw = str(event.get(name) or "").strip()
            if not raw:
                continue
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc), name
            except ValueError:
                return None, name
        return None, ""

    def blocked(reason: str) -> dict[str, object]:
        return {
            "payment_status": "conflict",
            "payment_reason": reason,
            "payment_matches": [],
            "allocation_status": "blocked_by_payment_identity",
            "allocation_reason": "payment_identity_not_confirmed",
            "allocation_results": [],
        }

    if len(cards) < 2 or len(cards) != len(otas):
        return blocked("repeated_group_cardinality_mismatch")

    card_ids = [str(card.get("card_id") or "") for card in cards]
    approvals = [
        re.sub(r"[^0-9A-Z]", "", str(card.get("approval_number") or "").upper())
        for card in cards
    ]
    raw_booking_refs = [
        str(ota.get("booking_ref") or "").strip() for ota in otas
    ]
    booking_refs = [
        re.sub(r"[^0-9A-Z]", "", value.upper())
        for value in raw_booking_refs
    ]
    if (
        any(not value for value in card_ids)
        or len(set(card_ids)) != len(card_ids)
        or any(not value for value in approvals)
        or len(set(approvals)) != len(approvals)
    ):
        return blocked("approval_identity_missing_or_duplicated")
    if any(not value for value in booking_refs) or len(set(booking_refs)) != len(
        booking_refs
    ):
        return blocked("booking_reference_missing_or_duplicated")
    ota_lineage_verified = [
        bool(
            (
                ota.get("message_id")
                and (
                    ota.get("booking_ref")
                    or ota.get("pnr")
                    or ota.get("order_number")
                )
            )
            or (
                str(ota.get("document_role") or "")
                in {"receipt", "payment_confirmation"}
                and ota.get("source_record_id")
            )
        )
        and str(ota.get("source_type") or "").strip().lower()
        not in BLOCKING_NOTE_SOURCE_TYPES
        for ota in otas
    ]
    if not all(ota_lineage_verified):
        return blocked("ota_direct_evidence_missing")

    card_times = [
        event_time(card, ("approved_at", "occurred_at"))
        for card in cards
    ]
    ota_times = [
        event_time(ota, ("issued_at", "mail_at"))
        for ota in otas
    ]
    if any(value[0] is None for value in card_times + ota_times):
        return blocked("issue_or_mail_time_missing")

    assignments: list[tuple[float, tuple[int, ...]]] = []
    for ota_order in permutations(range(len(otas))):
        total_delta = 0.0
        compatible = True
        for card_index, ota_index in enumerate(ota_order):
            card = cards[card_index]
            ota = otas[ota_index]
            if abs(int(card.get("amount_krw") or 0)) != abs(
                int(ota.get("amount_krw") or 0)
            ):
                compatible = False
                break
            card_currency = str(card.get("currency") or "").upper()
            ota_currency = str(ota.get("currency") or "").upper()
            if card_currency and ota_currency and card_currency != ota_currency:
                compatible = False
                break
            ota_approval = re.sub(
                r"[^0-9A-Z]",
                "",
                str(ota.get("approval_number") or "").upper(),
            )
            if ota_approval and ota_approval != approvals[card_index]:
                compatible = False
                break
            delta = abs(
                (
                    card_times[card_index][0] - ota_times[ota_index][0]
                ).total_seconds()
            )
            if delta > max_time_delta_seconds:
                compatible = False
                break
            total_delta += delta
        if compatible:
            assignments.append((total_delta, ota_order))
    if not assignments:
        return blocked("no_amount_currency_time_intersection")
    assignments.sort(key=lambda item: item[0])
    if len(assignments) > 1 and assignments[0][0] == assignments[1][0]:
        return blocked("temporal_assignment_not_unique")

    chosen = assignments[0][1]
    payment_matches: list[dict[str, object]] = []
    expected_allocations: dict[str, str] = {}
    for card_index, ota_index in enumerate(chosen):
        card = cards[card_index]
        ota = otas[ota_index]
        card_id = card_ids[card_index]
        delta_seconds = int(
            abs(
                (
                    card_times[card_index][0] - ota_times[ota_index][0]
                ).total_seconds()
            )
        )
        trip_code = str(ota.get("trip_code") or "")
        allocation_key = str(ota.get("allocation_key") or trip_code)
        expected_allocations[card_id] = allocation_key
        payment_matches.append(
            {
                "card_id": card_id,
                # The one-to-one approval/booking match owns its original
                # card-side owner.  Equal amounts must not collapse owners
                # from different cards or trips into a shared allocation.
                "owner": str(card.get("owner") or ""),
                "approval_number": approvals[card_index],
                "booking_ref": raw_booking_refs[ota_index],
                "payment_status": "confirmed_strong",
                "amount_krw": abs(int(card.get("amount_krw") or 0)),
                "temporal_delta_seconds": delta_seconds,
                "temporal_source": ota_times[ota_index][1],
                "trip_code": trip_code,
                "allocation_key": allocation_key,
                "intersection_signals": [
                    "approval_number",
                    "booking_ref",
                    "amount_currency",
                    ota_times[ota_index][1],
                ],
            }
        )

    allocation_results: list[dict[str, object]] = []
    for payment in payment_matches:
        card_id = str(payment["card_id"])
        expected = expected_allocations[card_id]
        proposed = allocations.get(card_id, "")
        allocation_results.append(
            {
                "card_id": card_id,
                "booking_ref": payment["booking_ref"],
                "expected_trip_code": expected,
                "proposed_trip_code": proposed,
                "expected_allocation_key": expected,
                "proposed_allocation_key": proposed,
                "allocation_status": (
                    "confirmed"
                    if proposed and proposed == expected
                    else "needs_review"
                    if not proposed
                    else "conflict"
                ),
            }
        )
    mismatches = [
        result
        for result in allocation_results
        if result["allocation_status"] == "conflict"
    ]
    expected_values = sorted(
        value for value in expected_allocations.values() if value
    )
    proposed_values = sorted(
        value for value in allocations.values() if value
    )
    reverse_assignment = bool(
        len(mismatches) >= 2
        and expected_values
        and expected_values == proposed_values
    )
    return {
        "payment_status": "confirmed_strong",
        "payment_reason": "approval_booking_time_intersection",
        "payment_matches": payment_matches,
        "allocation_status": (
            "conflict"
            if mismatches
            else "needs_review"
            if any(
                result["allocation_status"] == "needs_review"
                for result in allocation_results
            )
            else "confirmed"
        ),
        "allocation_reason": (
            "reverse_assignment"
            if reverse_assignment
            else "trip_allocation_mismatch"
            if mismatches
            else "trip_evidence_missing"
            if any(
                result["allocation_status"] == "needs_review"
                for result in allocation_results
            )
            else "booking_trip_match"
        ),
        "allocation_results": allocation_results,
    }


def select_direct_receipt(
    card: Mapping[str, object],
    candidates: Iterable[Mapping[str, object]],
    *,
    max_seconds: int = 180,
) -> dict[str, object]:
    """Select a unique direct receipt before any itinerary/bucket score."""
    card_amount = abs(int(card.get("amount_krw") or 0))
    card_time = str(card.get("occurred_at") or "")
    card_refs = {
        str(card.get(name) or "")
        for name in ("booking_number", "order_number", "payment_id")
        if card.get(name)
    }
    eligible: list[tuple[Mapping[str, object], float]] = []
    for candidate in candidates:
        if str(candidate.get("document_role") or "") not in {
            "receipt",
            "payment_confirmation",
        }:
            continue
        if abs(int(candidate.get("amount_krw") or 0)) != card_amount:
            continue
        candidate_refs = {
            str(candidate.get(name) or "")
            for name in ("booking_number", "order_number", "payment_id")
            if candidate.get(name)
        }
        if card_refs and candidate_refs and not card_refs.intersection(candidate_refs):
            continue
        try:
            seconds = abs(
                (
                    datetime.fromisoformat(card_time)
                    - datetime.fromisoformat(str(candidate.get("occurred_at") or ""))
                ).total_seconds()
            )
        except ValueError:
            continue
        if seconds <= max_seconds:
            eligible.append((candidate, seconds))
    if len(eligible) != 1:
        return {
            "status": "conflict" if eligible else "unmatched",
            "candidate": None,
            "candidate_count": len(eligible),
            "reason": "direct_receipt_not_unique" if eligible else "no_direct_receipt",
        }
    candidate, seconds = eligible[0]
    return {
        "status": "confirmed_strong",
        "candidate": dict(candidate),
        "candidate_count": 1,
        "reason": "unique_direct_receipt_amount_time",
        "time_delta_seconds": seconds,
    }


def assess_insurance_trip_link(
    *,
    payment_identity_confirmed: bool,
    trip_code: str = "",
    policy_travel_dates_confirmed: bool = False,
    policy_roster_confirmed: bool = False,
    exact_manual_trip_row: bool = False,
) -> dict[str, object]:
    """Keep insurance payment identity separate from its trip allocation."""
    trip_evidence = (
        policy_travel_dates_confirmed
        or policy_roster_confirmed
        or exact_manual_trip_row
    )
    return {
        "payment_identity_status": (
            "confirmed" if payment_identity_confirmed else "proposed"
        ),
        "trip_link_status": (
            "confirmed" if trip_code and trip_evidence else "needs_review"
        ),
        "trip_code": trip_code if trip_code and trip_evidence else "",
        "reason": (
            "policy_or_manual_trip_evidence"
            if trip_code and trip_evidence
            else "payment_evidence_does_not_prove_trip"
        ),
    }


def record_authorization_hold(
    db: sqlite3.Connection,
    payment_id: int,
    *,
    evidence: Iterable[Mapping[str, object]] = (),
) -> None:
    """Preserve a hotel card hold without recognizing travel cost."""
    existing = db.execute(
        "SELECT hold_status FROM authorization_holds WHERE hold_payment_id=?",
        (payment_id,),
    ).fetchone()
    if existing and str(existing["hold_status"]) != "pending":
        raise ValueError("resolved authorization hold cannot be recorded again")
    with db:
        db.execute(
            """
            INSERT INTO authorization_holds(
                hold_payment_id, hold_status, evidence_json, reason_code
            ) VALUES (?, 'pending', ?, 'merchant_authorization_hold')
            ON CONFLICT(hold_payment_id) DO UPDATE SET
                evidence_json=excluded.evidence_json,
                reason_code=excluded.reason_code,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                payment_id,
                json.dumps(list(evidence), ensure_ascii=False, sort_keys=True),
            ),
        )
        db.execute(
            """
            INSERT INTO card_event_dispositions(
                payment_id, disposition, finalized, reason_code
            ) VALUES (?, 'pending', 0, 'authorization_hold_unresolved')
            ON CONFLICT(payment_id) DO UPDATE SET
                disposition='pending', finalized=0, target_id=NULL,
                reason_code='authorization_hold_unresolved',
                updated_at=CURRENT_TIMESTAMP
            """,
            (payment_id,),
        )


def resolve_authorization_hold(
    db: sqlite3.Connection,
    hold_payment_id: int,
    related_payment_id: int,
    *,
    resolution: str,
) -> None:
    if resolution not in {"released", "captured"}:
        raise ValueError("authorization hold resolution must be released or captured")
    if hold_payment_id == related_payment_id:
        raise ValueError("authorization hold cannot resolve to itself")
    hold = db.execute(
        """
        SELECT h.hold_status, p.amount_krw
        FROM authorization_holds h
        JOIN payment_transactions p ON p.id=h.hold_payment_id
        WHERE h.hold_payment_id=?
        """,
        (hold_payment_id,),
    ).fetchone()
    related = db.execute(
        "SELECT amount_krw FROM payment_transactions WHERE id=?",
        (related_payment_id,),
    ).fetchone()
    if not hold or not related:
        raise ValueError("authorization hold or related payment not found")
    if hold["hold_status"] != "pending":
        raise ValueError("authorization hold is already resolved")
    if db.execute(
        """
        SELECT 1 FROM authorization_holds
        WHERE related_payment_id=? AND hold_payment_id<>?
        """,
        (related_payment_id, hold_payment_id),
    ).fetchone():
        raise ValueError("related payment is already linked to another authorization hold")
    if db.execute(
        "SELECT 1 FROM authorization_holds WHERE hold_payment_id=?",
        (related_payment_id,),
    ).fetchone():
        raise ValueError("related payment cannot itself be an authorization hold")
    hold_amount = int(hold["amount_krw"])
    related_amount = int(related["amount_krw"])
    if resolution == "released" and not (
        related_amount < 0 and abs(related_amount) == abs(hold_amount)
    ):
        raise ValueError("release event must be an equal negative card event")
    if resolution == "captured" and related_amount <= 0:
        raise ValueError("captured event must be a positive card event")
    disposition = "cancellation_refund" if resolution == "released" else "clearing"
    related_disposition = "cancellation_refund" if resolution == "released" else "pending"
    related_finalized = int(resolution == "released")
    with db:
        db.execute(
            """
            UPDATE authorization_holds
            SET hold_status=?, related_payment_id=?, updated_at=CURRENT_TIMESTAMP
            WHERE hold_payment_id=? AND hold_status='pending'
            """,
            (resolution, related_payment_id, hold_payment_id),
        )
        db.execute(
            """
            UPDATE card_event_dispositions
            SET disposition=?, finalized=1, reason_code=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE payment_id=?
            """,
            (
                disposition,
                f"authorization_hold_{resolution}",
                hold_payment_id,
            ),
        )
        db.execute(
            """
            INSERT INTO card_event_dispositions(
                payment_id, disposition, finalized, reason_code
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(payment_id) DO UPDATE SET
                disposition=excluded.disposition,
                finalized=excluded.finalized,
                target_id=NULL,
                reason_code=excluded.reason_code,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                related_payment_id,
                related_disposition,
                related_finalized,
                (
                    "authorization_hold_release_pair"
                    if resolution == "released"
                    else "authorization_capture_requires_allocation"
                ),
            ),
        )


class PeriodCloseBlocked(ValueError):
    """Raised when one or more close gates are not satisfied."""

    def __init__(self, gates: Mapping[str, Mapping[str, object]]) -> None:
        self.gates = dict(gates)
        failed = ", ".join(name for name, value in gates.items() if not value["passed"])
        super().__init__(f"기간 마감 차단: {failed}")


@dataclass(frozen=True)
class CoverageReport:
    source_events: int
    disposition_rows: int
    finalized_events: int
    pending_events: int
    missing_dispositions: int
    duplicate_event_ids: int
    direct_events: int = 0
    unprojected_direct_events: int = 0

    @property
    def lossless(self) -> bool:
        return (
            self.missing_dispositions == 0
            and self.pending_events == 0
            and self.duplicate_event_ids == 0
            and self.source_events == self.disposition_rows == self.finalized_events
            and self.unprojected_direct_events == 0
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dispositions(db: sqlite3.Connection) -> int:
    """Project current allocations into the lossless disposition register.

    Existing ``unassigned`` allocations intentionally become ``pending``;
    they are never silently converted into a final accounting target.
    """
    rows = db.execute(
        """
        SELECT p.id AS payment_id,
               COUNT(a.id) AS allocations,
               MIN(t.target_type) AS target_type,
               MIN(t.id) AS target_id,
               SUM(a.amount_krw) AS allocated,
               p.amount_krw,
               h.hold_status,
               MAX(hr.hold_status) AS related_hold_status,
               MAX(sd.value) AS source_event_disposition,
               MAX(pr.value) AS period_recognition
        FROM payment_transactions p
        LEFT JOIN current_cost_allocations a ON a.payment_id=p.id
        LEFT JOIN allocation_targets t ON t.id=a.target_id
        LEFT JOIN authorization_holds h ON h.hold_payment_id=p.id
        LEFT JOIN authorization_holds hr ON hr.related_payment_id=p.id
        LEFT JOIN current_classification_decisions sd
          ON sd.target_type='payment'
         AND sd.target_id=p.id
         AND sd.dimension='source_event_disposition'
        LEFT JOIN current_classification_decisions pr
          ON pr.target_type='payment'
         AND pr.target_id=p.id
         AND pr.dimension='period_recognition'
        GROUP BY p.id
        """
    ).fetchall()
    changed = 0
    for row in rows:
        hold_status = str(row["hold_status"] or "")
        related_hold_status = str(row["related_hold_status"] or "")
        source_disposition = str(row["source_event_disposition"] or "")
        period_recognition = str(row["period_recognition"] or "")
        if source_disposition in NONPOSTING_SOURCE_DISPOSITIONS:
            finalized = True
            disposition = source_disposition
            reason = "source_projection_nonposting_alias"
            target_id = None
        elif period_recognition == "prepaid_future_trip":
            finalized = True
            disposition = "prepaid_future_trip"
            reason = "service_start_after_closed_period"
            target_id = None
        elif period_recognition == "settlement_pending":
            # Refundable deposits cannot become Q2 cost merely because a card
            # charge exists.  Unlike a normal prepaid service they stay open
            # until a separately evidenced refund or capture resolves them.
            finalized = False
            disposition = "pending"
            reason = "refundable_deposit_settlement_pending"
            target_id = None
        elif related_hold_status == "released":
            finalized = True
            disposition = "cancellation_refund"
            reason = "authorization_hold_release_pair"
            target_id = None
        elif hold_status:
            finalized = hold_status in {"released", "captured"}
            disposition = (
                "cancellation_refund"
                if hold_status == "released"
                else "clearing"
                if hold_status == "captured"
                else "pending"
            )
            reason = f"authorization_hold_{hold_status}"
            target_id = None
        else:
            target = str(row["target_type"] or "")
            finalized = bool(
                target in FINAL_DISPOSITIONS
                and row["allocations"]
                and int(row["allocated"] or 0) == int(row["amount_krw"] or 0)
            )
            disposition = target if finalized else "pending"
            reason = "allocation_complete" if finalized else "allocation_pending"
            target_id = row["target_id"]
        before = db.total_changes
        db.execute(
            """
            INSERT INTO card_event_dispositions(
                payment_id, disposition, finalized, target_id, reason_code, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(payment_id) DO UPDATE SET
                disposition=excluded.disposition,
                finalized=excluded.finalized,
                target_id=excluded.target_id,
                reason_code=excluded.reason_code,
                updated_at=excluded.updated_at
            """,
            (row["payment_id"], disposition, int(finalized), target_id, reason, _now()),
        )
        changed += int(db.total_changes > before)
    return changed


def coverage_report(db: sqlite3.Connection) -> CoverageReport:
    ensure_dispositions(db)
    source_events = int(db.execute("SELECT COUNT(*) FROM payment_transactions").fetchone()[0])
    disposition_rows = int(db.execute("SELECT COUNT(*) FROM card_event_dispositions").fetchone()[0])
    finalized = int(
        db.execute("SELECT COUNT(*) FROM card_event_dispositions WHERE finalized=1").fetchone()[0]
    )
    pending = int(
        db.execute("SELECT COUNT(*) FROM card_event_dispositions WHERE finalized=0").fetchone()[0]
    )
    missing = max(source_events - disposition_rows, 0)
    duplicates = int(
        db.execute(
            """SELECT COUNT(*) FROM (
                 SELECT source_event_id FROM payment_transactions
                 GROUP BY source_event_id HAVING COUNT(*) > 1
               )"""
        ).fetchone()[0]
    )
    direct_events = 0
    unprojected = 0
    try:
        direct_events = int(db.execute("SELECT COUNT(*) FROM direct_normalized_payments").fetchone()[0])
        unprojected = int(db.execute("SELECT COUNT(*) FROM direct_normalized_payments d LEFT JOIN direct_payment_links l ON l.direct_payment_id=d.id WHERE l.link_status IS NULL OR l.link_status <> 'confirmed'").fetchone()[0])
    except sqlite3.OperationalError:
        pass
    return CoverageReport(source_events, disposition_rows, finalized, pending, missing, duplicates, direct_events, unprojected)


def project_direct_payments(db: sqlite3.Connection) -> dict[str, int]:
    """Link direct events by stable ID, then by a unique exact structural tuple.

    Legacy canonical rows do not contain raw_record_id, so their stable hashes
    cannot equal direct RAW hashes.  The fallback therefore requires exact
    source, signed amount, date, merchant and (when present) approval.  Approval
    alone is never a match key.
    """
    def merchant_key(value: object) -> str:
        return re.sub(r"[^0-9A-Z가-힣]", "", str(value or "").upper())

    def merchant_compatible(left: object, right: object) -> bool:
        a, b = merchant_key(left), merchant_key(right)
        return bool(
            a and b
            and (a in b or b in a or (len(a) >= 8 and len(b) >= 8 and a[:8] == b[:8]))
        )

    def structural_conflict(
        candidate: Mapping[str, object],
        direct: Mapping[str, object],
    ) -> bool:
        def field(record: Mapping[str, object], name: str) -> object:
            try:
                return record[name]
            except (KeyError, IndexError):
                return None

        candidate_date = str(field(candidate, "occurred_on") or "")
        direct_date = str(field(direct, "occurred_on") or "")
        candidate_merchant = str(field(candidate, "merchant") or "")
        direct_merchant = str(field(direct, "merchant") or "")
        candidate_approval = str(field(candidate, "approval_number") or "")
        direct_approval = str(field(direct, "approval_number") or "")
        return bool(
            (
                field(candidate, "source_system")
                and field(direct, "source_system")
                and field(candidate, "source_system")
                != field(direct, "source_system")
            )
            or int(field(candidate, "amount_krw") or 0)
            != int(field(direct, "amount_krw") or 0)
            or (
                candidate_approval
                and direct_approval
                and candidate_approval != direct_approval
            )
            or (
                candidate_date
                and direct_date
                and candidate_date != direct_date
            )
            or (
                candidate_merchant
                and direct_merchant
                and not merchant_compatible(candidate_merchant, direct_merchant)
            )
        )

    try:
        rows = db.execute(
            """
            SELECT d.id, d.card_event_id, d.amount_krw,
                   e.source_system, e.approval_number, e.occurred_on, e.merchant
            FROM direct_normalized_payments d
            JOIN direct_card_events e ON e.source_record_id=d.source_record_id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return {"direct_events": 0, "confirmed": 0, "unmatched": 0, "conflict": 0}
    counts = {"direct_events": len(rows), "confirmed": 0, "unmatched": 0, "conflict": 0}
    proposed: dict[int, tuple[int | None, str, str]] = {}
    for row in rows:
        candidates = db.execute("SELECT DISTINCT transaction_id FROM card_event_identities WHERE card_event_id=?", (row["card_event_id"],)).fetchall()
        if len(candidates) == 1:
            stable_candidate = db.execute(
                """
                SELECT id, source_system, amount_krw, approval_number,
                       occurred_on, merchant
                FROM payment_transactions
                WHERE id=?
                """,
                (int(candidates[0][0]),),
            ).fetchone()
            if stable_candidate is not None and not structural_conflict(
                stable_candidate,
                row,
            ):
                status, payment_id, reason = (
                    "confirmed",
                    int(candidates[0][0]),
                    "stable_card_event_id",
                )
            else:
                status, payment_id, reason = (
                    "conflict",
                    None,
                    "stable_identity_structural_conflict",
                )
        else:
            sql = """
                SELECT p.id, p.merchant
                FROM payment_transactions p
                WHERE p.source_system=?
                  AND p.amount_krw=?
                  AND COALESCE(p.occurred_on, '')=COALESCE(?, '')
            """
            params: list[object] = [
                row["source_system"],
                int(row["amount_krw"]),
                row["occurred_on"],
            ]
            if row["approval_number"]:
                sql += " AND COALESCE(p.approval_number, '')=?"
                params.append(row["approval_number"])
            structural = [
                candidate
                for candidate in db.execute(sql, params).fetchall()
                if merchant_compatible(candidate["merchant"], row["merchant"])
            ]
            if len(structural) == 1:
                status, payment_id, reason = (
                    "confirmed",
                    int(structural[0]["id"]),
                    "unique_exact_structure",
                )
            elif len(candidates) > 1 or len(structural) > 1:
                status, payment_id, reason = "conflict", None, "structural_candidate_not_unique"
            else:
                approval_peers = (
                    db.execute(
                        """
                        SELECT id, source_system, amount_krw, approval_number,
                               occurred_on, merchant
                        FROM payment_transactions
                        WHERE source_system=?
                          AND amount_krw=?
                          AND approval_number=?
                        """,
                        (
                            row["source_system"],
                            int(row["amount_krw"]),
                            row["approval_number"],
                        ),
                    ).fetchall()
                    if row["approval_number"]
                    else []
                )
                if any(
                    structural_conflict(candidate, row)
                    for candidate in approval_peers
                ):
                    status, payment_id, reason = (
                        "conflict",
                        None,
                        "approval_amount_structural_conflict",
                    )
                else:
                    status, payment_id, reason = (
                        "unmatched",
                        None,
                        "canonical_payment_missing",
                    )
        proposed[int(row["id"])] = (payment_id, status, reason)

    reverse: dict[int, list[int]] = {}
    for direct_id, (payment_id, status, _) in proposed.items():
        if status == "confirmed" and payment_id is not None:
            reverse.setdefault(payment_id, []).append(direct_id)
    for payment_id, direct_ids in reverse.items():
        if len(direct_ids) > 1:
            for direct_id in direct_ids:
                proposed[direct_id] = (None, "conflict", "canonical_payment_consumed_multiple_times")

    for direct_id, (payment_id, status, reason) in proposed.items():
        counts[status] += 1
        db.execute("INSERT INTO direct_payment_links(direct_payment_id,payment_id,link_status,reason_code,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(direct_payment_id) DO UPDATE SET payment_id=excluded.payment_id,link_status=excluded.link_status,reason_code=excluded.reason_code,updated_at=excluded.updated_at", (direct_id, payment_id, status, reason, _now()))
    db.commit()
    return counts


def create_match_group(
    db: sqlite3.Connection,
    group_key: str,
    *,
    provider: str = "",
    status: str = "proposed",
    confidence: float = 0.0,
    rationale: str = "",
    payment_ids: Iterable[int] = (),
    booking_ids: Iterable[int] = (),
    signals: Iterable[Mapping[str, object]] = (),
) -> int:
    """Create or update an N:M OTA/card relation group.

    A mismatch signal is never silently downgraded to unavailable. Strong
    confirmation also requires a card source event and sanitized source
    evidence lineage with all OTA collection blockers resolved.
    """
    if status not in MATCH_STATUSES:
        raise ValueError(f"지원하지 않는 매칭 상태: {status}")
    signal_rows = list(signals)
    if not all(isinstance(signal, Mapping) for signal in signal_rows):
        raise ValueError("매칭 신호는 JSON 객체 목록이어야 합니다.")
    invalid_signals = [
        str(signal.get("name") or "")
        for signal in signal_rows
        if not signal.get("name")
        or signal.get("status") not in {"match", "mismatch", "unavailable"}
    ]
    if invalid_signals:
        raise ValueError("매칭 신호의 name/status가 올바르지 않습니다.")
    _validate_signal_consistency(signal_rows)
    payment_id_rows = [int(payment_id) for payment_id in payment_ids]
    booking_id_rows = [int(booking_id) for booking_id in booking_ids]
    if status in {"confirmed_strong", "confirmed_manual"}:
        _reject_confirmation_conflicts(signal_rows, status=status)
        existing_group = db.execute(
            "SELECT id FROM match_groups WHERE group_key=?",
            (group_key,),
        ).fetchone()
        _reject_confirmed_member_reuse(
            db,
            group_id=int(existing_group["id"]) if existing_group else None,
            payment_ids=payment_id_rows,
            booking_ids=booking_id_rows,
        )
    if status == "confirmed_strong":
        _validate_strong_confirmation(
            db,
            payment_id_rows,
            signal_rows,
            booking_id_rows,
        )
    db.execute(
        """
        INSERT INTO match_groups(group_key, provider, status, confidence, rationale, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(group_key) DO UPDATE SET
            provider=excluded.provider, status=excluded.status,
            confidence=excluded.confidence, rationale=excluded.rationale,
            updated_at=excluded.updated_at
        """,
        (group_key, provider, status, confidence, rationale, _now()),
    )
    group_id = int(db.execute("SELECT id FROM match_groups WHERE group_key=?", (group_key,)).fetchone()[0])
    for payment_id in payment_id_rows:
        payment = db.execute(
            "SELECT amount_krw, transaction_type FROM payment_transactions WHERE id=?",
            (payment_id,),
        ).fetchone()
        amount = int(payment["amount_krw"])
        transaction_type = str(payment["transaction_type"] or "")
        role = (
            "refund"
            if amount < 0 or transaction_type in {"refund", "cancellation"}
            else "adjustment"
            if transaction_type == "adjustment"
            else "charge"
        )
        db.execute(
            "INSERT OR REPLACE INTO match_group_payments(group_id, payment_id, role, amount_krw) VALUES (?, ?, ?, ?)",
            (group_id, payment_id, role, amount),
        )
    for booking_id in booking_id_rows:
        db.execute(
            "INSERT OR REPLACE INTO match_group_bookings(group_id, booking_id, role) VALUES (?, ?, 'primary')",
            (group_id, booking_id),
        )
    for signal in signal_rows:
        db.execute(
            """
            INSERT INTO match_signal_results(
                group_id, signal_name, signal_status, left_value, right_value,
                rule_id, source_event_id, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_id, signal_name) DO UPDATE SET
                signal_status=excluded.signal_status, left_value=excluded.left_value,
                right_value=excluded.right_value, rule_id=excluded.rule_id,
                source_event_id=excluded.source_event_id,
                evidence_json=excluded.evidence_json
            """,
            (
                group_id,
                str(signal["name"]),
                str(signal["status"]),
                signal.get("left"),
                signal.get("right"),
                str(signal.get("rule_id") or "reconciliation-v1"),
                str(signal.get("source_event_id") or "") or None,
                json.dumps(
                    _safe_signal_evidence(signal.get("evidence")),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
    return group_id


def record_match_decision(
    db: sqlite3.Connection,
    decision_id: str,
    group_id: int,
    *,
    status: str,
    actor: str,
    reason_code: str,
    rationale: str,
    evidence: Iterable[Mapping[str, object]] = (),
    supersedes: str | None = None,
) -> bool:
    """Append a durable decision once; repeated decision IDs are idempotent."""
    if status not in MATCH_STATUSES:
        raise ValueError(f"지원하지 않는 매칭 상태: {status}")
    decision_evidence = list(evidence)
    if not all(isinstance(item, Mapping) for item in decision_evidence):
        raise ValueError("판정 근거는 JSON 객체 목록이어야 합니다.")
    payload = json.dumps(decision_evidence, ensure_ascii=False, sort_keys=True)
    existing_decision = db.execute(
        """
        SELECT group_id, status, actor, reason_code, rationale, evidence_json,
               supersedes_decision_id
        FROM match_decisions
        WHERE decision_id=?
        """,
        (decision_id,),
    ).fetchone()
    if existing_decision is not None:
        replay = (
            int(existing_decision["group_id"]) == int(group_id)
            and existing_decision["status"] == status
            and existing_decision["actor"] == actor
            and existing_decision["reason_code"] == reason_code
            and existing_decision["rationale"] == rationale
            and existing_decision["evidence_json"] == payload
            and existing_decision["supersedes_decision_id"] == supersedes
        )
        if replay:
            return False
        raise ValueError(
            f"판정 ID {decision_id}가 서로 다른 내용으로 재사용되었습니다."
        )
    group = db.execute(
        "SELECT id FROM match_groups WHERE id=?",
        (group_id,),
    ).fetchone()
    if group is None:
        raise ValueError(f"존재하지 않는 매칭 그룹: {group_id}")
    current_decision = db.execute(
        """
        SELECT decision_id
        FROM match_decisions
        WHERE group_id=?
        ORDER BY decided_at DESC, rowid DESC
        LIMIT 1
        """,
        (group_id,),
    ).fetchone()
    if current_decision is None and supersedes is not None:
        raise ValueError("최초 판정은 supersedes를 지정할 수 없습니다.")
    if current_decision is not None and (
        supersedes != current_decision["decision_id"]
    ):
        raise ValueError(
            "후속 판정은 같은 그룹의 직전 판정 ID를 supersedes로 지정해야 합니다."
        )
    persisted_signals = [
        {
            "name": row["signal_name"],
            "status": row["signal_status"],
            "left": row["left_value"],
            "right": row["right_value"],
            "rule_id": row["rule_id"],
            "source_event_id": row["source_event_id"],
            "evidence": json.loads(row["evidence_json"] or "[]"),
        }
        for row in db.execute(
            """
            SELECT signal_name, signal_status, left_value, right_value,
                   rule_id, source_event_id, evidence_json
            FROM match_signal_results
            WHERE group_id=?
            """,
            (group_id,),
        ).fetchall()
    ]
    if status in {"confirmed_strong", "confirmed_manual"}:
        _validate_signal_consistency(persisted_signals)
        _reject_confirmation_conflicts(persisted_signals, status=status)
        _reject_confirmation_conflicts(
            [
                {
                    "name": item.get("name")
                    or item.get("signal_name")
                    or "decision_evidence",
                    "status": item.get("status") or item.get("signal_status"),
                }
                for item in decision_evidence
            ],
            status=status,
        )
    if status == "confirmed_strong":
        payment_ids = [
            int(row["payment_id"])
            for row in db.execute(
                "SELECT payment_id FROM match_group_payments WHERE group_id=?",
                (group_id,),
            ).fetchall()
        ]
        booking_ids = [
            int(row["booking_id"])
            for row in db.execute(
                "SELECT booking_id FROM match_group_bookings WHERE group_id=?",
                (group_id,),
            ).fetchall()
        ]
        _validate_strong_confirmation(
            db,
            payment_ids,
            persisted_signals,
            booking_ids,
        )
    if status in {"confirmed_strong", "confirmed_manual"}:
        booking_ids = [
            int(row["booking_id"])
            for row in db.execute(
                "SELECT booking_id FROM match_group_bookings WHERE group_id=?",
                (group_id,),
            ).fetchall()
        ]
        if status != "confirmed_strong":
            payment_ids = [
                int(row["payment_id"])
                for row in db.execute(
                    "SELECT payment_id FROM match_group_payments WHERE group_id=?",
                    (group_id,),
                ).fetchall()
            ]
        _reject_confirmed_member_reuse(
            db,
            group_id=group_id,
            payment_ids=payment_ids,
            booking_ids=booking_ids,
        )
    before = db.total_changes
    db.execute(
        """
        INSERT OR IGNORE INTO match_decisions(
            decision_id, group_id, status, actor, reason_code, rationale,
            evidence_json, supersedes_decision_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (decision_id, group_id, status, actor, reason_code, rationale, payload, supersedes),
    )
    created = db.total_changes > before
    if created:
        db.execute(
            "UPDATE match_groups SET status=?, updated_at=? WHERE id=?",
            (status, _now(), group_id),
        )
        db.execute(
            """
            UPDATE card_event_dispositions
            SET disposition='pending',
                finalized=0,
                reason_code='match_decision_superseded',
                decision_id=?,
                updated_at=?
            WHERE decision_id IN (
                SELECT decision_id
                FROM match_decisions
                WHERE group_id=? AND decision_id<>?
            )
            """,
            (decision_id, _now(), group_id, decision_id),
        )
    return created


def manual_decision_projection(
    db: sqlite3.Connection,
    group_id: int,
) -> dict[str, object] | None:
    """Build the structured Apps Script provenance from the current decision.

    A legacy verified-link row or a copied ``confirmed_manual`` label is not
    enough.  Only the current append-only representative decision can project.
    """
    row = db.execute(
        """
        SELECT d.decision_id, d.group_id, d.status, d.actor, d.reason_code,
               d.rationale, d.evidence_json, d.supersedes_decision_id,
               projection.status AS projected_status,
               projection.decision_id AS projected_decision_id
        FROM current_match_decisions d
        JOIN current_match_group_projection projection
          ON projection.group_id=d.group_id
        WHERE d.group_id=?
        """,
        (group_id,),
    ).fetchone()
    if (
        row is None
        or row["status"] != "confirmed_manual"
        or row["projected_status"] != "confirmed_manual"
        or row["projected_decision_id"] != row["decision_id"]
        or row["actor"] == "legacy_import"
    ):
        return None
    try:
        evidence = json.loads(row["evidence_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        return None

    canonical = {
        "decision_id": row["decision_id"],
        "group_id": int(row["group_id"]),
        "status": row["status"],
        "actor": row["actor"],
        "reason_code": row["reason_code"],
        "rationale": row["rationale"],
        "evidence": evidence,
        "supersedes": row["supersedes_decision_id"],
    }
    evidence_hash = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    try:
        replay_verified = not record_match_decision(
            db,
            str(row["decision_id"]),
            int(row["group_id"]),
            status=str(row["status"]),
            actor=str(row["actor"]),
            reason_code=str(row["reason_code"]),
            rationale=str(row["rationale"]),
            evidence=evidence,
            supersedes=(
                str(row["supersedes_decision_id"])
                if row["supersedes_decision_id"] is not None
                else None
            ),
        )
    except ValueError:
        return None

    chain_verified = True
    seen: set[str] = set()
    current = row
    while current["supersedes_decision_id"] is not None:
        current_id = str(current["decision_id"])
        if current_id in seen:
            chain_verified = False
            break
        seen.add(current_id)
        previous = db.execute(
            """
            SELECT decision_id, group_id, supersedes_decision_id
            FROM match_decisions WHERE decision_id=?
            """,
            (current["supersedes_decision_id"],),
        ).fetchone()
        if previous is None or int(previous["group_id"]) != int(group_id):
            chain_verified = False
            break
        child_count = int(
            db.execute(
                "SELECT COUNT(*) FROM match_decisions WHERE supersedes_decision_id=?",
                (previous["decision_id"],),
            ).fetchone()[0]
        )
        if child_count != 1:
            chain_verified = False
            break
        current = previous

    current_verified = (
        int(
            db.execute(
                """
                SELECT COUNT(*) FROM current_match_decisions
                WHERE group_id=? AND decision_id=? AND status='confirmed_manual'
                """,
                (group_id, row["decision_id"]),
            ).fetchone()[0]
        )
        == 1
    )
    persisted_signals = [
        {
            "name": signal["signal_name"],
            "status": signal["signal_status"],
            "left": signal["left_value"],
            "right": signal["right_value"],
            "rule_id": signal["rule_id"],
            "source_event_id": signal["source_event_id"],
            "evidence": json.loads(signal["evidence_json"] or "[]"),
        }
        for signal in db.execute(
            """
            SELECT signal_name, signal_status, left_value, right_value,
                   rule_id, source_event_id, evidence_json
            FROM match_signal_results WHERE group_id=?
            """,
            (group_id,),
        ).fetchall()
    ]
    try:
        _validate_signal_consistency(persisted_signals)
        _reject_confirmation_conflicts(
            persisted_signals,
            status="confirmed_manual",
        )
        matched_fresh = current_verified
    except (TypeError, ValueError, json.JSONDecodeError):
        matched_fresh = False
    return {
        "pythonProjectionStatus": "confirmed_manual",
        "pythonManualDecision": {
            "decisionId": str(row["decision_id"]),
            "actor": str(row["actor"]),
            "reasonCode": str(row["reason_code"]),
            "rationale": str(row["rationale"]),
            "evidenceHash": evidence_hash,
            "replayVerified": replay_verified,
            "matchedFresh": matched_fresh,
            "currentDecisionVerified": current_verified,
            "supersedesChainVerified": chain_verified,
        },
    }


def refund_balance(db: sqlite3.Connection, original_payment_id: int) -> dict[str, int | bool]:
    """Separate the audit refund trail from the one net travel-cost posting.

    ``audit_refund_krw`` is a disclosure amount: it must not be added to
    ``travel_cost_posting_krw``.  The latter is the only amount available for
    travel-cost posting, so a partial refund cannot be counted both as an
    audit line and as a second cost reduction.
    """
    original = int(
        db.execute("SELECT amount_krw FROM payment_transactions WHERE id=?", (original_payment_id,)).fetchone()[0]
    )
    refunded = int(
        db.execute(
            """SELECT COALESCE(SUM(ABS(COALESCE(rp.amount_krw, 0))), 0)
               FROM transaction_relations r
               JOIN payment_transactions rp ON rp.id=r.transaction_id
               WHERE r.related_transaction_id=? AND r.relation_type IN ('refunds','cancels')
                 AND r.relation_status NOT IN ('rejected','superseded')""",
            (original_payment_id,),
        ).fetchone()[0]
    )
    remaining = original - refunded
    return {
        "gross_krw": original,
        "refunded_krw": refunded,
        "remaining_krw": remaining,
        "audit_refund_krw": refunded,
        "travel_cost_posting_krw": remaining,
        "over_refunded": remaining < 0,
    }


def refund_balance_gate_counts(db: sqlite3.Connection) -> dict[str, int]:
    """Return close-gate blockers for linked refund arithmetic.

    A confirmed relation must run from a negative refund/cancellation event to
    one positive original event.  Refund legs may be shown in an audit trail,
    but their aggregate cannot exceed the original and only the residual is a
    travel cost.
    """
    base = """
        FROM transaction_relations r
        JOIN payment_transactions refund ON refund.id=r.transaction_id
        JOIN payment_transactions original ON original.id=r.related_transaction_id
        WHERE r.relation_type IN ('refunds', 'cancels')
          AND r.relation_status NOT IN ('rejected', 'superseded')
    """
    invalid_sign = int(
        db.execute(
            "SELECT COUNT(*) " + base
            + " AND (refund.amount_krw >= 0 OR original.amount_krw <= 0)"
        ).fetchone()[0]
    )
    over_refunded = int(
        db.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT r.related_transaction_id
                """
            + base
            + """
                GROUP BY r.related_transaction_id, original.amount_krw
                HAVING SUM(ABS(refund.amount_krw)) > original.amount_krw
            )
            """
        ).fetchone()[0]
    )
    unlinked = int(
        db.execute(
            """
            SELECT COUNT(*) FROM transaction_relations r
            JOIN payment_transactions p ON p.id=r.transaction_id
            WHERE r.relation_type IN ('refunds','cancels')
              AND r.related_transaction_id IS NULL
              AND r.relation_status NOT IN ('rejected','superseded')
            """
        ).fetchone()[0]
    )
    provisional = int(
        db.execute(
            """
            SELECT COUNT(*) FROM transaction_relations r
            WHERE r.relation_type IN ('refunds','cancels')
              AND r.relation_status IN ('legacy','proposed')
            """
        ).fetchone()[0]
    )
    return {
        "unlinked_refunds": unlinked,
        "provisional_refund_relations": provisional,
        "invalid_sign_relations": invalid_sign,
        "over_refunded_originals": over_refunded,
    }


def refund_case_disposition(
    *,
    gross_krw: int,
    refund_krw: int,
    original_relation_evidenced: bool,
    original_outside_window: bool = False,
    original_occurred_on: str = "",
    period_start_on: str = "",
    period_end_on: str = "",
) -> dict[str, int | str | None]:
    """State the one posting amount for a reviewed refund case.

    The original/refund relation is a prerequisite for a travel-cost posting.
    Without it, the refund is retained as audit evidence but the apparent
    residual is deliberately not recognised as travel cost.
    """
    gross = int(gross_krw)
    refund = abs(int(refund_krw))
    if gross <= 0:
        raise ValueError("refund original must be a positive charge")
    if refund <= 0:
        raise ValueError("refund amount must be non-zero")
    residual = gross - refund
    if residual < 0:
        raise ValueError("refund exceeds original charge")
    # Narrative notes often describe a historic period imperfectly.  When
    # dates are available, raw source dates are the sole period authority and
    # override a caller's legacy/narrative flag.
    raw_period_result: bool | None = None
    if original_occurred_on and period_start_on and period_end_on:
        try:
            original_day = datetime.strptime(original_occurred_on[:10], "%Y-%m-%d").date()
            period_start = datetime.strptime(period_start_on[:10], "%Y-%m-%d").date()
            period_end = datetime.strptime(period_end_on[:10], "%Y-%m-%d").date()
            raw_period_result = not (period_start <= original_day <= period_end)
        except ValueError:
            raw_period_result = None
    if raw_period_result is not None:
        original_outside_window = raw_period_result
    if not original_relation_evidenced:
        status = "original_relation_unconfirmed"
        posting: int | None = None
        period_treatment = "original_relation_unconfirmed"
    elif original_outside_window:
        status = "original_outside_window"
        posting = None
        period_treatment = "prior_period_refund_adjustment"
    elif residual == 0:
        status = "confirmed_full_cancellation"
        posting = 0
        period_treatment = "same_period_netting"
    else:
        status = "confirmed_partial_refund"
        posting = residual
        period_treatment = "same_period_netting"
    return {
        "gross_krw": gross,
        "audit_refund_krw": refund,
        "residual_krw": residual,
        "travel_cost_posting_krw": posting,
        "status": status,
        "period_treatment": period_treatment,
    }


def refund_lifecycle_bundles(
    legs: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Build approval-anchored refund bundles without collapsing same amounts.

    ``card_evidence_status`` says only that the charge/refund legs exist in
    card RAW.  ``travel_evidence_status`` is deliberately independent: card
    existence does not prove which booking or trip consumed the charge.
    """
    normalized = [dict(leg) for leg in legs]
    purchases: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    refunds: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for leg in normalized:
        source = str(leg.get("src") or "")
        amount = _integer_amount(leg.get("amount_krw", leg.get("krw")))
        approval = re.sub(r"\D", "", str(leg.get("appr") or ""))
        original = re.sub(r"\D", "", str(leg.get("orig_appr") or ""))
        if amount > 0 and approval:
            purchases[(source, approval)].append(leg)
        elif amount < 0:
            # An approval-less overseas cancellation remains a visible raw
            # event-set.  It cannot be joined to any purchase or trip merely
            # because merchant/date/amount look plausible.
            if original:
                refund_key = (source, original)
            else:
                refund_key = (
                    source,
                    "unresolved:"
                    + ":".join(
                        (
                            str(leg.get("use_date") or "")[:10],
                            str(abs(amount)),
                            re.sub(r"[^0-9A-Z]", "", str(leg.get("merchant") or "").upper()),
                        )
                    ),
                )
            refunds[refund_key].append(leg)

    result: list[dict[str, object]] = []
    for source_original, refund_legs in sorted(refunds.items()):
        source, original_key = source_original
        has_original_approval = not original_key.startswith("unresolved:")
        original = original_key if has_original_approval else None
        purchase_legs = purchases.get(source_original, [])
        gross = sum(abs(_integer_amount(leg.get("amount_krw", leg.get("krw")))) for leg in purchase_legs)
        refunded = sum(abs(_integer_amount(leg.get("amount_krw", leg.get("krw")))) for leg in refund_legs)
        all_legs = purchase_legs + refund_legs
        card_verified = bool(all_legs) and all(bool(leg.get("card_verified")) for leg in all_legs)
        travel_verified = bool(all_legs) and all(bool(leg.get("travel_verified")) for leg in all_legs)
        result.append(
            {
                "pair_id": (
                    f"refund-lifecycle:{source}:{original}"
                    if has_original_approval
                    else f"refund-unresolved:{source}:{original_key.removeprefix('unresolved:')}"
                ),
                "source": source,
                "original_approval": original,
                "positive_leg_uids": sorted(str(leg.get("uid") or "") for leg in purchase_legs),
                "negative_leg_uids": sorted(str(leg.get("uid") or "") for leg in refund_legs),
                "gross_krw": gross,
                "refunded_krw": refunded,
                "residual_krw": gross - refunded if purchase_legs else None,
                "original_relation_status": (
                    "original_approval_present"
                    if has_original_approval
                    else "original_approval_missing"
                ),
                "card_evidence_status": "card_verified" if card_verified else "card_unverified",
                "travel_evidence_status": "travel_verified" if travel_verified else "travel_unverified",
            }
        )
    return result


def close_period(db: sqlite3.Connection, run_id: str, *, require_tax_evidence: bool = True) -> dict[str, object]:
    """Evaluate hard close gates and persist their results."""
    # Audit stale posting state before ``coverage_report`` normalizes current
    # dispositions. Otherwise a superseded confirmed decision can be silently
    # repaired and escape the close-gate evidence trail.
    stale_finalized_dispositions = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM card_event_dispositions disposition
            WHERE disposition.finalized=1
              AND disposition.decision_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM current_match_decisions current
                  WHERE current.decision_id=disposition.decision_id
                    AND current.status IN (
                        'confirmed_strong', 'confirmed_manual'
                    )
              )
            """
        ).fetchone()[0]
    )
    projection_status_drift = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM match_groups groups
            JOIN current_match_decisions current
              ON current.group_id=groups.id
            WHERE groups.status<>current.status
            """
        ).fetchone()[0]
    )
    branched_match_groups = int(
        db.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT decision.group_id
                FROM match_decisions decision
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM match_decisions newer
                    WHERE newer.supersedes_decision_id=decision.decision_id
                )
                GROUP BY decision.group_id
                HAVING COUNT(*)>1
            )
            """
        ).fetchone()[0]
    )
    invalid_current_strong_confirmations = 0
    legacy_migration_review_required = int(
        db.execute(
            """
            SELECT COUNT(*) FROM current_match_decisions
            WHERE status='proposed' AND actor='legacy_import'
              AND reason_code='legacy_verified_link'
            """
        ).fetchone()[0]
    )
    for projection in db.execute(
        """
        SELECT group_id
        FROM current_match_group_projection
        WHERE status='confirmed_strong'
        """
    ).fetchall():
        projection_group_id = int(projection["group_id"])
        projection_signals: list[dict[str, object]] = []
        malformed_signal_evidence = False
        for row in db.execute(
            """
            SELECT signal_name, signal_status, left_value, right_value,
                   rule_id, source_event_id, evidence_json
            FROM match_signal_results
            WHERE group_id=?
            """,
            (projection_group_id,),
        ).fetchall():
            try:
                parsed_evidence = json.loads(row["evidence_json"] or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                malformed_signal_evidence = True
                parsed_evidence = []
            projection_signals.append(
                {
                    "name": row["signal_name"],
                    "status": row["signal_status"],
                    "left": row["left_value"],
                    "right": row["right_value"],
                    "rule_id": row["rule_id"],
                    "source_event_id": row["source_event_id"],
                    "evidence": parsed_evidence,
                }
            )
        projection_payment_ids = [
            int(row["payment_id"])
            for row in db.execute(
                """
                SELECT payment_id
                FROM match_group_payments
                WHERE group_id=?
                """,
                (projection_group_id,),
            ).fetchall()
        ]
        projection_booking_ids = [
            int(row["booking_id"])
            for row in db.execute(
                """
                SELECT booking_id
                FROM match_group_bookings
                WHERE group_id=?
                """,
                (projection_group_id,),
            ).fetchall()
        ]
        try:
            if malformed_signal_evidence:
                raise ValueError("신호 evidence_json 파싱 실패")
            _validate_signal_consistency(projection_signals)
            _reject_confirmation_conflicts(
                projection_signals,
                status="confirmed_strong",
            )
            _validate_strong_confirmation(
                db,
                projection_payment_ids,
                projection_signals,
                projection_booking_ids,
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            invalid_current_strong_confirmations += 1
    report = coverage_report(db)
    refund_gate = refund_balance_gate_counts(db)
    gates: dict[str, dict[str, object]] = {
        "card_lossless": {
            "passed": report.lossless,
            "actual": report.__dict__,
            "rationale": "카드 이벤트 전수원장과 최종 배분이 1:1인지 검사",
        },
        "refund_balance": {
            "passed": not any(refund_gate.values()),
            "actual": refund_gate,
            "rationale": "원거래 없는 환불은 마감을 차단",
        },
        "match_projection_current": {
            "passed": (
                stale_finalized_dispositions == 0
                and projection_status_drift == 0
                and branched_match_groups == 0
                and invalid_current_strong_confirmations == 0
                and legacy_migration_review_required == 0
            ),
            "actual": {
                "stale_finalized_dispositions": stale_finalized_dispositions,
                "projection_status_drift": projection_status_drift,
                "branched_match_groups": branched_match_groups,
                "invalid_current_strong_confirmations": (
                    invalid_current_strong_confirmations
                ),
                "legacy_migration_review_required": legacy_migration_review_required,
            },
            "rationale": (
                "현재 match 판정만 자동전기·재매칭에 사용되고 "
                "대체된 확정 판정이 비활성인지 검사"
            ),
        },
    }
    if require_tax_evidence:
        pending_tax = int(
            db.execute("SELECT COUNT(*) FROM tax_basis_assessments WHERE evidence_status='tax_review_required'").fetchone()[0]
        )
        gates["tax_basis_evidence"] = {
            "passed": pending_tax == 0,
            "actual": pending_tax,
            "rationale": "순액매출 근거가 확인되지 않은 여행 존재 여부",
        }
    db.execute("DELETE FROM period_close_gates WHERE run_id=?", (run_id,))
    for name, gate in gates.items():
        db.execute(
            "INSERT INTO period_close_gates(run_id, gate_name, passed, actual_value, rationale) VALUES (?, ?, ?, ?, ?)",
            (run_id, name, int(bool(gate["passed"])), json.dumps(gate["actual"], ensure_ascii=False, default=str), gate["rationale"]),
        )
    db.commit()
    if not all(bool(gate["passed"]) for gate in gates.values()):
        raise PeriodCloseBlocked(gates)
    return {"run_id": run_id, "passed": True, "gates": gates}


def tax_assessment(
    db: sqlite3.Connection,
    trip_id: int,
    *,
    customer_receipts_krw: int,
    entrusted_costs_krw: int,
    refunds_krw: int = 0,
    evidence: Iterable[Mapping[str, object]] = (),
    evidence_confirmed: bool = False,
    version: str = "tax-v1",
) -> dict[str, int | str]:
    net_cost = int(entrusted_costs_krw) - int(refunds_krw)
    commission = int(customer_receipts_krw) - net_cost
    status = "confirmed" if evidence_confirmed else "tax_review_required"
    db.execute(
        """
        INSERT INTO tax_basis_assessments(
            trip_id, customer_receipts_krw, entrusted_costs_krw, refunds_krw,
            net_travel_cost_krw, commission_krw, evidence_status, evidence_json,
            assessment_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trip_id, assessment_version) DO UPDATE SET
            customer_receipts_krw=excluded.customer_receipts_krw,
            entrusted_costs_krw=excluded.entrusted_costs_krw,
            refunds_krw=excluded.refunds_krw,
            net_travel_cost_krw=excluded.net_travel_cost_krw,
            commission_krw=excluded.commission_krw,
            evidence_status=excluded.evidence_status,
            evidence_json=excluded.evidence_json
        """,
        (trip_id, customer_receipts_krw, entrusted_costs_krw, refunds_krw,
         net_cost, commission, status,
         json.dumps(list(evidence), ensure_ascii=False, sort_keys=True), version),
    )
    db.commit()
    return {"trip_id": trip_id, "net_travel_cost_krw": net_cost, "commission_krw": commission, "evidence_status": status}
