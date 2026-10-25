"""Read-only Agoda portal-to-card reconciliation candidates.

This module deliberately stops at a private candidate report.  It does not
insert bookings, payment transactions, or payment-booking links, and it never
turns a portal claim into an issuer event.  The pure graph resolver is reused
only for its closed-universe/card4/amount rules; its historical
``confirmed_*`` result names are translated to ``proposed`` or ``review``
below so there is no second confirmation authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from tools.agoda_amount_candidate_graph import (
    PaymentAmount,
    ReservationAmount,
    resolve_candidate_graph,
)


# A common fixed comparison scale keeps JPY integer amounts, KRW amounts, and
# decimal foreign amounts comparable without assuming that the issuer and OTA
# use the same currency-specific minor-unit convention.  Canonical portal
# values are already bounded to scale <= 9.
COMPARISON_SCALE = 9
COMPARISON_FACTOR = 10**COMPARISON_SCALE

_CHARGE_COMPONENTS = {"paid_today", "charged", "actual_paid", "charge"}
_REFUND_COMPONENTS = {"refund", "refunded", "refunded_today"}
_CHARGE_COLLECTION_MODELS = {
    "agoda_collect",
    "agoda_collect_pay_now",
    "merchant_collect",
    "pay_now",
    "prepaid",
}
_NON_CARD_COLLECTION_MODELS = {
    "property_collect",
    "property_collect_pay_later",
    "pay_at_property",
    "pay_later",
    "future_payment",
}
_ACTIVE_PORTAL_STATUSES = {"completed", "confirmed", "active", "booked", "reserved"}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _valid_sha256(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _text(value: object) -> str:
    return str(value or "").strip()


def _card4(value: object) -> str | None:
    value = _text(value)
    return value if len(value) == 4 and value.isascii() and value.isdigit() else None


def _comparison_units(value: object) -> int:
    """Convert a decimal amount to the fixed comparison scale exactly."""
    try:
        decimal = Decimal(_text(value).replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("agoda_amount_decimal_invalid") from exc
    if not decimal.is_finite():
        raise ValueError("agoda_amount_decimal_invalid")
    scaled = decimal * COMPARISON_FACTOR
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise ValueError("agoda_amount_precision_exceeds_comparison_scale")
    result = int(integral)
    if result == 0:
        raise ValueError("agoda_amount_zero")
    return result


def _canonical_money(component: Mapping[str, object]) -> int:
    """Read canonical ``minor_units`` + ``scale`` without losing precision."""
    try:
        minor = int(component["minor_units"])
        scale = int(component["scale"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("agoda_canonical_money_invalid") from exc
    if scale < 0 or scale > COMPARISON_SCALE:
        raise ValueError("agoda_canonical_scale_invalid")
    return _comparison_units(Decimal(minor) / (10**scale))


def _currency(value: object) -> str:
    currency = _text(value).upper()
    return currency if len(currency) == 3 and currency.isascii() and currency.isalpha() else ""


def _is_agoda_merchant(value: object) -> bool:
    if not isinstance(value, str):
        return False
    merchant = " ".join(value.strip().upper().split())
    return (
        merchant == "AGODA"
        or merchant.startswith(("AGODA.", "AGODA_", "AGODA "))
        or merchant == "아고다_나이스"
        or merchant == "아고다페이먼츠코리아"
    )


def _raw_card_normalization(payload: Mapping[str, object]) -> tuple[int, str] | None:
    """Recompute the direct-card sign/type contract from the immutable RAW row.

    The candidate query must not trust all three derived payment tables when
    the RAW envelope says something else.  HAN has a separate component
    contract in the normalizer, so its multi-component envelope is left to
    that canonical contract rather than guessed here.
    """
    source = _text(payload.get("src")).upper()
    if not source or source == "HAN" or "krw" not in payload:
        return None
    try:
        raw_amount = int(payload["krw"])
    except (TypeError, ValueError) as exc:
        raise ValueError("card_raw_amount_invalid") from exc
    cancelled = payload.get("cancel")
    if type(cancelled) is not bool:
        raise ValueError("card_raw_cancel_invalid")
    if cancelled and source in {"KBO", "CORP"}:
        return -abs(raw_amount), "cancellation"
    if raw_amount < 0:
        return raw_amount, "refund"
    if cancelled:
        return raw_amount, "cancellation"
    if raw_amount == 0:
        return 0, "adjustment"
    return raw_amount, "purchase"


def _collection_competes(payload: Mapping[str, object]) -> tuple[bool, str | None]:
    model = _text(payload.get("collection_model")).lower()
    if model in _CHARGE_COLLECTION_MODELS:
        return True, None
    if model in _NON_CARD_COLLECTION_MODELS:
        return False, "collection_model_not_issuer_charge"
    # Missing/unrecognized collection model is still a candidate input, but
    # its promotion flag remains false because the model is not verified.
    return True, "collection_model_unverified"


def _portal_lifecycle_hold(payload: Mapping[str, object]) -> str | None:
    """Reject portal claims whose payload still signals lifecycle uncertainty."""
    for field in ("status", "reservation_status"):
        value = _text(payload.get(field)).lower()
        if value and value not in _ACTIVE_PORTAL_STATUSES:
            return "portal_lifecycle_requires_review"

    payment_status = _text(payload.get("payment_status")).lower()
    if payment_status and payment_status not in {
        "paid", "captured", "completed", "confirmed", "settled",
    }:
        return "portal_lifecycle_requires_review"

    refund_status = _text(payload.get("refund_status")).lower()
    if refund_status and refund_status not in {
        "none", "none_displayed", "not_refunded", "no_refund",
    }:
        return "portal_lifecycle_requires_review"

    payment_state = _text(payload.get("portal_payment_state")).lower()
    if payment_state and payment_state not in {
        "none", "paid", "paid_today", "captured", "completed", "confirmed", "settled",
    }:
        return "portal_lifecycle_requires_review"
    return None


def _claim_to_node(
    *,
    booking_id: int,
    booking_number: str,
    source_key: str,
    payload: Mapping[str, object],
    event_kind: str,
    currency: str,
    amount: int,
    card4_override: str | None = None,
) -> ReservationAmount:
    card4 = card4_override if card4_override is not None else _card4(payload.get("card_last4"))
    competes, hold_reason = _collection_competes(payload)
    key = f"booking:{booking_id}:claim:{event_kind}:{currency}:{amount}"
    return ReservationAmount(
        key=key,
        currency=currency,
        amount_minor_units=amount,
        event_kind=event_kind,
        card4=card4,
        competes_for_payment=competes,
        promotion_eligible=(competes and hold_reason is None and event_kind == "charge"),
        hold_reason=hold_reason,
    )


def _portal_nodes(db: sqlite3.Connection) -> tuple[list[ReservationAmount], list[dict[str, object]] , list[str]]:
    census_rows = db.execute(
        """
        SELECT source_sha256
        FROM direct_source_records
        WHERE source_kind='agoda_portal_detail'
        ORDER BY id
        """
    ).fetchall()
    unlinked_rows = db.execute(
        """
        SELECT s.id, s.source_key
        FROM direct_source_records AS s
        WHERE s.source_kind='agoda_portal_detail'
          AND NOT EXISTS (
              SELECT 1
              FROM booking_source_evidence AS e
              JOIN bookings AS b ON b.id=e.booking_id
              WHERE e.direct_source_record_id=s.id
                AND b.provider='agoda'
          )
        ORDER BY s.id
        """
    ).fetchall()
    rows = db.execute(
        """
        SELECT b.id, b.booking_number, b.status,
               e.evidence_status, e.conflict_count, e.evidence_role,
               s.source_key, s.source_sha256, s.payload_json
        FROM bookings AS b
        JOIN booking_source_evidence AS e ON e.booking_id=b.id
        JOIN direct_source_records AS s ON s.id=e.direct_source_record_id
        WHERE b.provider='agoda'
          AND e.evidence_kind='agoda_portal_detail'
          AND e.evidence_role='portal_payment_claim'
          AND s.source_kind='agoda_portal_detail'
        ORDER BY b.id, s.source_key
        """
    ).fetchall()
    grouped: dict[tuple[int, str, str, int], dict[str, object]] = {}
    source_hashes = [str(row[0]) for row in census_rows]
    holds: list[dict[str, object]] = [
        {
            "source_id": int(row[0]),
            "source_key": str(row[1]),
            "reason": "portal_census_unlinked_record",
        }
        for row in unlinked_rows
    ]
    for row in rows:
        (
            booking_id,
            booking_number,
            booking_status,
            evidence_status,
            conflict_count,
            evidence_role,
            source_key,
            source_sha256,
            raw_payload,
        ) = row
        if str(evidence_role or "") != "portal_payment_claim":
            holds.append({
                "booking_id": int(booking_id),
                "source_key": str(source_key),
                "reason": "portal_evidence_role_not_payment_claim",
                "evidence_role": str(evidence_role or "unknown"),
            })
            continue
        normalized_booking_status = _text(booking_status).lower()
        if normalized_booking_status in {"cancelled", "canceled"}:
            holds.append({
                "booking_id": int(booking_id),
                "source_key": str(source_key),
                "reason": "booking_cancelled_requires_lifecycle_review",
            })
            continue
        if normalized_booking_status == "upcoming":
            holds.append({
                "booking_id": int(booking_id),
                "source_key": str(source_key),
                "reason": "booking_upcoming_payment_lifecycle_review",
            })
            continue
        if normalized_booking_status not in {"confirmed", "completed"}:
            holds.append({
                "booking_id": int(booking_id),
                "source_key": str(source_key),
                "reason": "booking_status_unverified",
                "booking_status": normalized_booking_status or "unknown",
            })
            continue
        normalized_evidence_status = _text(evidence_status).lower()
        if normalized_evidence_status in {"rejected", "superseded"}:
            holds.append({
                "booking_id": int(booking_id),
                "source_key": str(source_key),
                "reason": "portal_evidence_not_active",
                "evidence_status": normalized_evidence_status,
            })
            continue
        try:
            evidence_conflict_count = int(conflict_count or 0)
        except (TypeError, ValueError):
            evidence_conflict_count = 1
        if evidence_conflict_count:
            holds.append({
                "booking_id": int(booking_id),
                "source_key": str(source_key),
                "reason": "portal_evidence_conflict",
                "conflict_count": evidence_conflict_count,
            })
            continue
        payload = json.loads(str(raw_payload))
        if not isinstance(payload, Mapping):
            holds.append({"booking_id": int(booking_id), "reason": "portal_payload_not_object"})
            continue
        if not _valid_sha256(source_sha256) or _sha256(payload) != str(source_sha256).lower():
            holds.append({
                "booking_id": int(booking_id),
                "source_key": str(source_key),
                "reason": "portal_source_payload_digest_invalid",
            })
            continue
        lifecycle_reason = _portal_lifecycle_hold(payload)
        if lifecycle_reason is not None:
            holds.append({
                "booking_id": int(booking_id),
                "source_key": str(source_key),
                "reason": lifecycle_reason,
            })
            continue
        claims: list[tuple[str, str, int]] = []
        raw_claims = payload.get("portal_event_claims")
        if isinstance(raw_claims, list) and raw_claims:
            for claim in raw_claims:
                if not isinstance(claim, Mapping):
                    continue
                event_kind = _text(claim.get("event_kind"))
                currency = _currency(claim.get("currency"))
                if event_kind not in {"charge", "refund", "chargeback"} or not currency:
                    continue
                try:
                    amount = _canonical_money(claim)
                except ValueError as exc:
                    holds.append({"booking_id": int(booking_id), "source_key": str(source_key), "reason": str(exc)})
                    continue
                if amount <= 0:
                    holds.append({
                        "booking_id": int(booking_id),
                        "source_key": str(source_key),
                        "reason": "portal_claim_amount_nonpositive",
                    })
                    continue
                claims.append((event_kind, currency, amount))
        else:
            components = payload.get("price_components")
            if isinstance(components, list):
                for component in components:
                    if not isinstance(component, Mapping):
                        continue
                    kind = _text(component.get("kind")).lower()
                    if kind in _CHARGE_COMPONENTS:
                        event_kind = "charge"
                    elif kind in _REFUND_COMPONENTS:
                        event_kind = "refund"
                    else:
                        continue
                    currency = _currency(component.get("currency"))
                    if not currency:
                        continue
                    try:
                        amount = _canonical_money(component)
                    except ValueError as exc:
                        holds.append({"booking_id": int(booking_id), "source_key": str(source_key), "reason": str(exc)})
                        continue
                    if amount <= 0:
                        holds.append({
                            "booking_id": int(booking_id),
                            "source_key": str(source_key),
                            "reason": "portal_claim_amount_nonpositive",
                        })
                        continue
                    claims.append((event_kind, currency, amount))
        if not claims:
            holds.append({
                "booking_id": int(booking_id),
                "booking_number": str(booking_number),
                "source_key": str(source_key),
                "reason": "no_actual_charge_claim",
                "portal_payment_state": payload.get("portal_payment_state"),
            })
            continue
        for event_kind, currency, amount in claims:
            key = (int(booking_id), event_kind, currency, amount)
            entry = grouped.setdefault(
                key,
                {
                    "booking_id": int(booking_id),
                    "booking_number": str(booking_number),
                    "source_keys": [],
                    "payload": payload,
                    "card4s": set(),
                    "collection_models": set(),
                },
            )
            entry["source_keys"].append(str(source_key))
            observed_card4 = _card4(payload.get("card_last4"))
            if observed_card4 is not None:
                entry["card4s"].add(observed_card4)
            observed_model = _text(payload.get("collection_model")).lower()
            if observed_model:
                entry["collection_models"].add(observed_model)

    # Multiple different claim signatures for one booking are preserved as a
    # review item, never allowed to compete as two charges for one booking.
    by_booking: dict[int, list[tuple[tuple[int, str, str, int], dict[str, object]]]] = {}
    for key, entry in grouped.items():
        by_booking.setdefault(key[0], []).append((key, entry))
    nodes: list[ReservationAmount] = []
    for booking_id, entries in sorted(by_booking.items()):
        signatures = {(key[1], key[2], key[3]) for key, _ in entries}
        if len(signatures) > 1:
            holds.append({
                "booking_id": booking_id,
                "reason": "booking_claim_conflict",
                "claim_signatures": sorted(signatures),
            })
            continue
        key, entry = entries[0]
        if len(entry["card4s"]) > 1:
            holds.append({
                "booking_id": booking_id,
                "reason": "booking_card4_conflict",
                "card4_values": sorted(entry["card4s"]),
            })
            continue
        if len(entry["collection_models"]) > 1:
            holds.append({
                "booking_id": booking_id,
                "reason": "booking_collection_model_conflict",
                "collection_models": sorted(entry["collection_models"]),
            })
            continue
        event_kind, currency, amount = key[1], key[2], key[3]
        nodes.append(_claim_to_node(
            booking_id=booking_id,
            booking_number=str(entry["booking_number"]),
            source_key=str(entry["source_keys"][0]),
            payload=entry["payload"],
            event_kind=event_kind,
            currency=currency,
            amount=amount,
            card4_override=(next(iter(entry["card4s"])) if entry["card4s"] else None),
        ))
    return nodes, holds, sorted(source_hashes)


def _payment_nodes(
    db: sqlite3.Connection, run_id: str,
) -> tuple[list[PaymentAmount], list[dict[str, object]], list[str]]:
    rows = db.execute(
        """
        SELECT p.id, p.external_key, p.source_system, p.transaction_type,
               p.currency, p.foreign_amount, p.amount_krw,
               n.amount_krw, n.transaction_type,
               s.source_sha256, s.payload_json,
               e.identity_status, e.amount_krw, e.source_system
        FROM direct_payment_projection_links AS l
        JOIN payment_transactions AS p ON p.id=l.payment_id
        JOIN direct_normalized_payments AS n ON n.id=l.direct_payment_id
        JOIN direct_source_records AS s ON s.id=n.source_record_id
        LEFT JOIN direct_card_events AS e ON e.source_record_id=n.source_record_id
        WHERE l.run_id=? AND s.source_kind='card_raw'
        ORDER BY p.id
        """,
        (run_id,),
    ).fetchall()
    nodes: list[PaymentAmount] = []
    holds: list[dict[str, object]] = []
    source_hashes: list[str] = []
    for row in rows:
        (
            payment_id,
            external_key,
            source_system,
            transaction_type,
            db_currency,
            db_foreign,
            amount_krw,
            normalized_amount_krw,
            normalized_transaction_type,
            source_sha256,
            raw_payload,
            identity_status,
            event_amount_krw,
            event_source_system,
        ) = row
        source_hashes.append(str(source_sha256))
        payload = json.loads(str(raw_payload))
        if not isinstance(payload, Mapping):
            holds.append({"payment_id": int(payment_id), "reason": "card_payload_not_object"})
            continue
        if not _valid_sha256(source_sha256) or _sha256(payload) != str(source_sha256).lower():
            holds.append({
                "payment_id": int(payment_id),
                "reason": "card_source_payload_digest_invalid",
            })
            continue
        raw_merchant = payload.get("merchant")
        if not _is_agoda_merchant(raw_merchant):
            holds.append({
                "payment_id": int(payment_id),
                "reason": "card_merchant_not_agoda",
            })
            continue
        raw_source_system = _text(payload.get("src")).upper()
        canonical_source_system = _text(source_system).upper()
        if raw_source_system and canonical_source_system and raw_source_system != canonical_source_system:
            holds.append({
                "payment_id": int(payment_id),
                "reason": "card_source_system_raw_conflict",
                "raw_source_system": raw_source_system,
                "canonical_source_system": canonical_source_system,
            })
            continue
        try:
            raw_contract = _raw_card_normalization(payload)
        except ValueError as exc:
            holds.append({"payment_id": int(payment_id), "reason": str(exc)})
            continue
        canonical_amounts: list[int] = []
        canonical_amount_invalid = False
        for value in (amount_krw, normalized_amount_krw, event_amount_krw):
            if value is None:
                continue
            try:
                canonical_amounts.append(int(value))
            except (TypeError, ValueError):
                holds.append({
                    "payment_id": int(payment_id),
                    "reason": "card_amount_canonical_invalid",
                })
                canonical_amount_invalid = True
                break
        if canonical_amount_invalid:
            continue
        if canonical_amounts and len(set(canonical_amounts)) != 1:
            holds.append({
                "payment_id": int(payment_id),
                "reason": "card_amount_canonical_conflict",
                "amounts_krw": canonical_amounts,
            })
            continue
        if raw_contract is not None:
            raw_amount, raw_transaction_type = raw_contract
            if raw_transaction_type != str(transaction_type):
                holds.append({
                    "payment_id": int(payment_id),
                    "reason": "card_raw_transaction_type_conflict",
                    "raw_transaction_type": raw_transaction_type,
                    "canonical_transaction_type": str(transaction_type),
                })
                continue
            if canonical_amounts and raw_amount != canonical_amounts[0]:
                holds.append({
                    "payment_id": int(payment_id),
                    "reason": "card_raw_amount_conflict",
                    "raw_amount_krw": raw_amount,
                    "canonical_amounts_krw": canonical_amounts,
                })
                continue
        if normalized_transaction_type is not None and str(normalized_transaction_type) != str(transaction_type):
            holds.append({
                "payment_id": int(payment_id),
                "reason": "card_transaction_type_canonical_conflict",
            })
            continue
        if event_source_system and str(event_source_system) != str(source_system):
            holds.append({
                "payment_id": int(payment_id),
                "reason": "card_source_system_canonical_conflict",
            })
            continue
        raw_currency_text = _text(payload.get("currency") or payload.get("cur"))
        payload_currency = _currency(raw_currency_text)
        canonical_currency = _currency(db_currency)
        if raw_currency_text and not payload_currency:
            holds.append({
                "payment_id": int(payment_id),
                "reason": "card_currency_raw_invalid",
                "raw_currency": raw_currency_text,
            })
            continue
        if _text(db_currency) and not canonical_currency:
            holds.append({
                "payment_id": int(payment_id),
                "reason": "card_currency_canonical_invalid",
            })
            continue
        if payload_currency and canonical_currency and payload_currency != canonical_currency:
            holds.append({
                "payment_id": int(payment_id),
                "reason": "card_currency_canonical_conflict",
                "raw_currency": payload_currency,
                "canonical_currency": canonical_currency,
            })
            continue
        currency = payload_currency or canonical_currency
        event_kind = {"purchase": "charge", "refund": "refund", "cancellation": "refund"}.get(str(transaction_type))
        if event_kind is None:
            holds.append({"payment_id": int(payment_id), "reason": "card_transaction_type_not_reconcilable", "transaction_type": transaction_type})
            continue
        try:
            if currency == "KRW" or not currency:
                currency = "KRW"
                amount = _comparison_units(amount_krw)
            else:
                foreign = payload.get("foreign") or payload.get("fx") or db_foreign
                amount = _comparison_units(foreign)
        except ValueError as exc:
            holds.append({"payment_id": int(payment_id), "reason": str(exc)})
            continue
        raw_foreign = payload.get("foreign") or payload.get("fx")
        if raw_foreign not in (None, "") and db_foreign not in (None, "") and currency != "KRW":
            try:
                if _comparison_units(raw_foreign) != _comparison_units(db_foreign):
                    holds.append({
                        "payment_id": int(payment_id),
                        "reason": "card_foreign_amount_canonical_conflict",
                    })
                    continue
            except ValueError as exc:
                holds.append({"payment_id": int(payment_id), "reason": str(exc)})
                continue
        card4 = _card4(payload.get("card4") or payload.get("c4"))
        promotion_eligible = event_kind == "charge" and str(identity_status or "") == "unique"
        reason = None
        if event_kind != "charge":
            reason = "issuer_lifecycle_event_requires_review"
        elif identity_status is None:
            reason = "card_identity_missing"
        elif str(identity_status) != "unique":
            reason = "card_identity_collision"
        elif event_kind == "charge" and amount <= 0:
            reason = "issuer_charge_amount_nonpositive"
            promotion_eligible = False
        if reason:
            holds.append({"payment_id": int(payment_id), "reason": reason})
        if reason == "issuer_charge_amount_nonpositive":
            continue
        nodes.append(PaymentAmount(
            key=f"payment:{int(payment_id)}",
            currency=currency,
            amount_minor_units=amount,
            event_kind=event_kind,
            card4=card4,
            promotion_eligible=promotion_eligible,
            hold_reason=reason,
        ))
    return nodes, holds, sorted(source_hashes)


def _verify_universe_attestation(
    attestation: Mapping[str, object] | None,
    portal_hashes: list[str],
) -> bool:
    """Bind the closed-universe assertion to the exact portal source census."""
    if not isinstance(attestation, Mapping):
        return False
    if _text(attestation.get("source_kind")) != "agoda_portal_detail":
        return False
    attested_hashes = attestation.get("source_hashes")
    if not isinstance(attested_hashes, list):
        return False
    expected_hashes = sorted(str(value) for value in portal_hashes)
    observed_hashes = sorted(_text(value) for value in attested_hashes)
    if observed_hashes != expected_hashes:
        return False
    try:
        record_count = int(attestation.get("record_count"))
    except (TypeError, ValueError):
        return False
    if record_count != len(expected_hashes):
        return False
    return _text(attestation.get("source_hashes_sha256")) == _sha256(expected_hashes)


def build_agoda_card_candidate_report(
    db: sqlite3.Connection,
    *,
    run_id: str,
    universe_sealed: bool,
    universe_attestation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a deterministic, read-only candidate report from one card run."""
    run = db.execute(
        "SELECT status, input_manifest_sha256 FROM direct_projection_runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if run is None:
        raise ValueError("agoda_card_projection_run_missing")
    reservations, portal_holds, portal_hashes = _portal_nodes(db)
    payments, card_holds, card_hashes = _payment_nodes(db, run_id)
    portal_census_linkage_verified = not any(
        item.get("reason") == "portal_census_unlinked_record"
        for item in portal_holds
    )
    universe_attestation_verified = _verify_universe_attestation(
        universe_attestation,
        portal_hashes,
    )
    universe_attestation_sha256 = (
        _sha256(universe_attestation) if isinstance(universe_attestation, Mapping) else None
    )
    effective_universe_sealed = bool(
        universe_sealed
        and universe_attestation_verified
        and portal_census_linkage_verified
    )
    resolution = resolve_candidate_graph(
        reservations,
        payments,
        universe_sealed=effective_universe_sealed,
    )
    reservation_by_key = {node.key: node for node in reservations}
    payment_by_key = {node.key: node for node in payments}
    proposed: list[dict[str, object]] = []
    review_individuals: list[dict[str, object]] = []
    run_status = _text(run[0]).lower()
    run_is_passed = run_status == "passed"
    run_holds: list[dict[str, object]] = []
    if not run_is_passed:
        run_holds.append({
            "reason": "card_projection_run_not_passed",
            "run_id": run_id,
            "run_status": run_status or "unknown",
        })
    if universe_sealed and not universe_attestation_verified:
        run_holds.append({
            "reason": "universe_attestation_missing_or_invalid",
            "source_kind": "agoda_portal_detail",
        })
    for item in resolution["confirmed_individuals"]:
        reservation = reservation_by_key[str(item["reservation_key"])]
        payment = payment_by_key[str(item["payment_key"])]
        strong = (
            run_is_passed
            and
            reservation.event_kind == "charge"
            and reservation.card4 is not None
            and payment.card4 is not None
            and reservation.card4 == payment.card4
            and reservation.promotion_eligible
            and payment.promotion_eligible
        )
        row = {
            **item,
            "status": "proposed" if strong else "review",
            "card4_required_for_proposed": True,
        }
        (proposed if strong else review_individuals).append(row)
    report = {
        "report_kind": "agoda_card_reconciliation_candidate",
        "report_version": "agoda-card-candidate-v1",
        "authority": {
            "writes_canonical_db": False,
            "creates_payment_transactions": False,
            "creates_payment_booking_links": False,
            "creates_confirmed_authority": False,
            "portal_claims_are_issuer_events": False,
        },
        "card_projection": {
            "run_id": run_id,
            "status": str(run[0]),
            "input_manifest_sha256": str(run[1]),
            "payment_count": len(payments),
        },
        "universe_sealed": effective_universe_sealed,
        "universe_sealed_asserted": bool(universe_sealed),
        "universe_attestation_verified": universe_attestation_verified,
        "portal_census_linkage_verified": portal_census_linkage_verified,
        "universe_attestation_sha256": universe_attestation_sha256,
        "source_hashes": {
            "portal": portal_hashes,
            "card": card_hashes,
        },
        "input_fingerprint": _sha256({
            "run_id": run_id,
            "universe_sealed": effective_universe_sealed,
            "universe_attestation_verified": universe_attestation_verified,
            "universe_attestation_sha256": universe_attestation_sha256,
            "portal": portal_hashes,
            "card": card_hashes,
        }),
        "amount_candidates": list(resolution["amount_candidates"]),
        "proposed_individuals": proposed,
        "review_individuals": review_individuals,
        "review_groups": [
            {**item, "status": "review"}
            for item in resolution["confirmed_groups"]
        ],
        "held": [*run_holds, *portal_holds, *card_holds, *list(resolution["held"])],
    }
    return report


__all__ = ["COMPARISON_SCALE", "build_agoda_card_candidate_report"]
