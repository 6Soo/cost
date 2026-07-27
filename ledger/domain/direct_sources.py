"""P6 카드·수기·OTA 원천의 멱등 직접 적재와 legacy 병렬 대조."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict, deque
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping

from ledger import cardindex
from ledger.domain.source_adapters import (
    OTA_REDACTION_VERSION,
    confirmed_booking_service_start,
    sanitize_ota_record,
    stable_card_event_identity,
)


def _canonical_hash(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _booking_provider(provider: object) -> str:
    """Use the same provider identity for Gmail staging and legacy links."""
    value = str(provider or "").strip().lower()
    return {
        "trip_hotel": "trip.com",
        "trip_flight": "trip.com",
        "trip": "trip.com",
        "booking": "booking.com",
    }.get(value, value or "unknown")


def _ensure_ota_import_schema(db: sqlite3.Connection) -> None:
    """Make the public OTA importer safe on a newly connected database."""
    required = {"direct_source_records", "bookings", "direct_booking_service_periods"}
    existing = {
        str(row[0])
        for row in db.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            """
        ).fetchall()
    }
    booking_columns = (
        {
            str(row[1])
            for row in db.execute("PRAGMA table_info(bookings)").fetchall()
        }
        if "bookings" in existing
        else set()
    )
    if (
        not required.issubset(existing)
        or "service_end_on" not in booking_columns
    ):
        # Delayed import avoids the ledger_db -> direct_sources module cycle.
        from ledger.domain.ledger_db import initialize

        initialize(db)


def signed_card_event_amount(row: dict[str, object]) -> int:
    """카드사가 취소금액을 양수로 제공해도 이벤트 원장에는 음수로 보존한다."""
    amount = int(row.get("krw") or 0)
    cancelled = bool(row.get("cancel"))
    return -abs(amount) if cancelled and row.get("src") != "HAN" else amount


def hana_lifecycle_component_amounts(row: dict[str, object]) -> tuple[int, int]:
    """Return posted purchase/refund amounts for a captured Hana cancellation."""
    approved = abs(int(row.get("approval_amount") or 0))
    billed = abs(int(row.get("purchase_amount") or 0))
    cancelled = abs(int(row.get("cancel_amount") or 0))
    purchase = billed or cancelled or approved
    refund = cancelled or purchase
    return purchase, -refund


def _insert_source(
    db: sqlite3.Connection,
    kind: str,
    key: str,
    payload: dict[str, object],
    redaction_version: str | None = None,
) -> tuple[int, bool]:
    digest = _canonical_hash(payload)
    before = db.total_changes
    db.execute(
        """
        INSERT OR IGNORE INTO direct_source_records(
            source_kind, source_key, source_sha256, payload_json, redaction_version
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            kind,
            key,
            digest,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            redaction_version,
        ),
    )
    row_id = int(
        db.execute(
            """
            SELECT id FROM direct_source_records
            WHERE source_kind=? AND source_key=? AND source_sha256=?
            """,
            (kind, key, digest),
        ).fetchone()[0]
    )
    return row_id, db.total_changes > before


def import_cards(db: sqlite3.Connection, ledger_dir: Path) -> dict[str, int]:
    """카드 RAW xlsx를 legacy classified CSV 없이 직접 읽는다."""
    previous = Path.cwd()
    try:
        # 기존 검증된 카드 파서는 ledger/ 상대경로를 사용한다.
        import os
        os.chdir(ledger_dir)
        cards = cardindex.build_cards()
    finally:
        os.chdir(previous)

    inserted = 0
    identities: dict[str, list[int]] = {}
    for card in cards:
        normalized = {
            "src": card["src"],
            "raw_record_id": card["raw_record_id"],
            "card4": card.get("c4", ""),
            "appr": card.get("appr", ""),
            "orig_appr": card.get("orig", ""),
            "use_date": card.get("use", ""),
            "post_date": card.get("bill", ""),
            "merchant": card.get("mer", ""),
            "biz": card.get("uptype", ""),
            "currency": card.get("cur", ""),
            "foreign": card.get("fx", ""),
            "krw": card.get("krw", 0),
            "approval_amount": card.get("approval_amount", 0),
            "cancel_amount": card.get("cancel_amount", 0),
            "purchase_amount": card.get("purchase_amount", 0),
            "cancel": card.get("cancel", False),
            "status": card.get("status", ""),
        }
        identity = stable_card_event_identity(normalized)
        event_amount = signed_card_event_amount(normalized)
        source_id, created = _insert_source(
            db,
            "card_raw",
            f"{normalized['src']}:{normalized['raw_record_id']}",
            normalized,
        )
        inserted += int(created)
        db.execute(
            """
            INSERT INTO direct_card_events(
                source_record_id, card_event_id, generator_version,
                identity_status, source_system, amount_krw,
                approval_number, occurred_on, merchant
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_record_id) DO UPDATE SET
                card_event_id=excluded.card_event_id,
                generator_version=excluded.generator_version,
                identity_status=excluded.identity_status,
                source_system=excluded.source_system,
                amount_krw=excluded.amount_krw,
                approval_number=excluded.approval_number,
                occurred_on=excluded.occurred_on,
                merchant=excluded.merchant
            """,
            (
                source_id,
                identity.card_event_id,
                identity.generator_version,
                identity.identity_status,
                normalized["src"],
                event_amount,
                normalized["appr"] or None,
                normalized["use_date"] or None,
                normalized["merchant"],
            ),
        )
        approval_amount = int(normalized["approval_amount"])
        cancel_amount = int(normalized["cancel_amount"])
        if normalized["src"] == "HAN" and cancel_amount:
            purchase_component, cancellation_component = (
                hana_lifecycle_component_amounts(normalized)
            )
            approval_row = dict(normalized)
            approval_row.update(
                krw=purchase_component,
                cancel=False,
                raw_record_id=f"{normalized['raw_record_id']}:approval",
            )
            cancellation_row = dict(normalized)
            cancellation_row.update(
                krw=cancellation_component,
                cancel=True,
                raw_record_id=f"{normalized['raw_record_id']}:cancellation",
            )
            components = [
                (
                    "approval",
                    stable_card_event_identity(approval_row),
                    purchase_component,
                    "purchase",
                ),
                (
                    "cancellation",
                    stable_card_event_identity(cancellation_row),
                    cancellation_component,
                    "cancellation",
                ),
            ]
        else:
            amount = event_amount
            transaction_type = (
                "refund"
                if amount < 0
                else "cancellation"
                if normalized["cancel"]
                else "adjustment"
                if amount == 0
                else "purchase"
            )
            components = [("single", identity, amount, transaction_type)]

        for role, component_identity, amount, transaction_type in components:
            db.execute(
                """
                INSERT INTO direct_normalized_payments(
                    source_record_id, event_role, card_event_id, amount_krw,
                    transaction_type, normalization_version
                ) VALUES (?, ?, ?, ?, ?, 'direct-card-v2')
                ON CONFLICT(source_record_id, event_role) DO UPDATE SET
                    card_event_id=excluded.card_event_id,
                    amount_krw=excluded.amount_krw,
                    transaction_type=excluded.transaction_type,
                    normalization_version=excluded.normalization_version
                """,
                (
                    source_id,
                    role,
                    component_identity.card_event_id,
                    amount,
                    transaction_type,
                ),
            )
        identities.setdefault(identity.card_event_id, []).append(source_id)

    for event_id, source_ids in identities.items():
        if len(source_ids) > 1:
            db.execute(
                """
                UPDATE direct_card_events SET identity_status='collision'
                WHERE card_event_id=?
                """,
                (event_id,),
            )
    return {
        "records": len(cards),
        "inserted": inserted,
        "identity_collisions": sum(
            len(source_ids) for source_ids in identities.values() if len(source_ids) > 1
        ),
        "normalized_payments": int(
            db.execute("SELECT COUNT(*) FROM direct_normalized_payments").fetchone()[0]
        ),
    }


def import_manual(
    db: sqlite3.Connection,
    path: Path,
    special_path: Path | None = None,
) -> dict[str, int]:
    """Import ordinary and explicitly maintained manual-source records.

    ``manual_special_rows.json`` is a separate, reviewable manual source.  It
    must not disappear merely because it has no position in the spreadsheet
    extract (for example the Oze lodge transfer).  These rows remain manual
    evidence; this import does not reclassify them as card events.
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    inserted = 0
    for row in rows:
        key = f"{row.get('tab')}:{row.get('row')}"
        _, created = _insert_source(db, "manual_ledger", key, dict(row))
        inserted += int(created)
    special_rows: list[dict[str, object]] = []
    if special_path is not None and special_path.exists():
        loaded = json.loads(special_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise ValueError("manual special rows must be a JSON list")
        special_rows = [dict(row) for row in loaded if isinstance(row, dict)]
        for row in special_rows:
            key = str(row.get("uid") or "").strip()
            if not key:
                raise ValueError("manual special row missing uid")
            _, created = _insert_source(db, "manual_special", key, row)
            inserted += int(created)
    return {"records": len(rows) + len(special_rows), "inserted": inserted}


def import_ota(
    db: sqlite3.Connection,
    path: Path,
    *,
    source_kind: str = "ota_mail",
) -> dict[str, int]:
    """Import sanitized OTA facts, initializing its required schema if absent.

    Only ``confirmed_booking_service_start`` may create a service-period fact;
    note text and unverified travel-date aliases remain non-authoritative.
    """
    if source_kind not in {"ota_mail", "ota_authenticated_portal"}:
        raise ValueError(f"unsupported OTA source kind: {source_kind}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows: Iterable[dict[str, object]] = raw.get("records", raw)
    return import_ota_records(db, rows, source_kind=source_kind)


def import_ota_records(
    db: sqlite3.Connection,
    rows: Iterable[Mapping[str, object]],
    *,
    source_kind: str = "ota_mail",
) -> dict[str, int]:
    """Import already-sanitized OTA observations without a JSON round trip.

    Authenticated portal checkpoints are SQLite-backed and expose only their
    completed, allowlisted payloads.  Keeping this path shared with JSON
    imports means the same redaction and confirmed-period rules apply to both
    sources.  A defensive scope check also ensures a hand-crafted/stale
    checkpoint cannot reintroduce pre-2025 OTA reservations.
    """
    if source_kind not in {"ota_mail", "ota_authenticated_portal"}:
        raise ValueError(f"unsupported OTA source kind: {source_kind}")
    _ensure_ota_import_schema(db)
    count = 0
    inserted = 0
    confirmed_booking_periods = 0
    for index, row in enumerate(rows):
        raw_start = str(row.get("service_start_on") or "").strip()
        if raw_start:
            try:
                if date.fromisoformat(raw_start).year < 2025:
                    continue
            except ValueError:
                # ``sanitize_ota_record`` below will retain the observation
                # but cannot make it an authoritative service period.
                pass
        clean = sanitize_ota_record(row)
        # Alias normalization happens inside sanitize_ota_record before the
        # allowlist. Never append raw aliases after redaction.
        clean["redaction_version"] = OTA_REDACTION_VERSION
        key = str(clean.get("message_id") or f"row:{index}")
        source_record_id, created = _insert_source(
            db,
            source_kind,
            key,
            clean,
            OTA_REDACTION_VERSION,
        )
        inserted += int(created)
        confirmed = confirmed_booking_service_start(clean)
        if confirmed is not None:
            booking_provider = _booking_provider(confirmed["provider"])
            db.execute(
                """
                INSERT INTO bookings(
                    provider, booking_number, product_type, service_start_on,
                    service_end_on, status
                ) VALUES (?, ?, 'lodging', ?, ?, 'confirmed')
                ON CONFLICT(provider, booking_number) DO UPDATE SET
                    service_start_on=COALESCE(
                        bookings.service_start_on, excluded.service_start_on
                    ),
                    service_end_on=COALESCE(
                        bookings.service_end_on, excluded.service_end_on
                    ),
                    status=CASE
                        WHEN bookings.status='unknown' THEN 'confirmed'
                        ELSE bookings.status
                    END
                """,
                (
                    booking_provider,
                    confirmed["booking_number"],
                    confirmed["service_start_on"],
                    confirmed.get("service_end_on"),
                ),
            )
            booking_id = int(
                db.execute(
                    """
                    SELECT id FROM bookings
                    WHERE provider=? AND booking_number=?
                    """,
                    (booking_provider, confirmed["booking_number"]),
                ).fetchone()[0]
            )
            db.execute(
                """
                INSERT OR IGNORE INTO direct_booking_service_periods(
                    booking_id, source_record_id, service_start_on,
                    settlement_condition, evidence_status, redaction_version
                ) VALUES (?, ?, ?, ?, 'confirmed', ?)
                """,
                (
                    booking_id,
                    source_record_id,
                    confirmed["service_start_on"],
                    confirmed.get("settlement_condition"),
                    OTA_REDACTION_VERSION,
                ),
            )
            confirmed_booking_periods += 1
        count += 1
    return {
        "records": count,
        "inserted": inserted,
        "confirmed_booking_periods": confirmed_booking_periods,
    }


def import_ota_checkpoint(
    db: sqlite3.Connection,
    path: Path,
    provider: str,
) -> dict[str, int]:
    """Bridge completed authenticated-portal checkpoints into direct sources.

    The checkpoint store is append-only; ``completed_records`` returns only
    its current complete observations.  Importing those records is likewise
    append-only through ``direct_source_records`` content hashes.
    """
    if not path.exists():
        return {"records": 0, "inserted": 0, "confirmed_booking_periods": 0}
    from .ota_checkpoint import OtaCheckpointStore

    with OtaCheckpointStore(path) as store:
        records = store.completed_records(provider)
    return import_ota_records(
        db,
        records,
        source_kind="ota_authenticated_portal",
    )


def _decimal_key(value: object) -> str:
    try:
        return format(
            Decimal(str(value or "").replace(",", "")).normalize(),
            "f",
        )
    except (InvalidOperation, ValueError):
        return ""


def reconcile_direct_ota_payment_evidence(
    db: sqlite3.Connection,
) -> dict[str, int]:
    """Confirm only unique card↔OTA intersections from direct evidence.

    Booking mail requires exact payment date, currency, foreign amount and
    (when present) card suffix.  Agoda authenticated evidence uses the same
    exact dimensions, but a portal record without a payment date is eligible
    only when currency, foreign amount and card suffix form a bidirectionally
    unique intersection.  Repeated components remain durable N:M conflicts.
    """
    from .reconciliation import create_match_group, record_match_decision

    direct_by_message: dict[str, dict[str, object]] = {}
    ineligible_by_message: dict[str, dict[str, object]] = {}

    def evidence_identity(
        row: Mapping[str, object],
    ) -> tuple[str, ...]:
        return (
            str(row.get("_normalized_provider") or "").lower(),
            str(row.get("booking_number") or "").strip(),
            str(row.get("source_channel") or "").lower(),
            str(row.get("payment_date") or "").strip(),
            str(row.get("service_start_on") or "").strip(),
            str(row.get("service_end_on") or "").strip(),
            str(row.get("currency") or "").upper(),
            _decimal_key(row.get("foreign_amount")),
            str(
                row.get("card4") or row.get("card_last4") or ""
            ).strip(),
            str(row.get("record_type") or "").lower(),
            str(row.get("booking_confirmation_status") or "").lower(),
            str(row.get("status") or "").lower(),
        )

    def store_unique(
        target: dict[str, dict[str, object]],
        payload: dict[str, object],
    ) -> None:
        message_id = str(payload["message_id"])
        prior = target.get(message_id)
        if prior is not None:
            if evidence_identity(prior) != evidence_identity(payload):
                raise RuntimeError(
                    f"conflicting direct OTA evidence for message_id={message_id}"
                )
            return
        target[message_id] = payload

    for source in db.execute(
        """
        SELECT id, source_key, payload_json
        FROM direct_source_records
        WHERE source_kind IN ('ota_mail', 'ota_authenticated_portal')
        ORDER BY id
        """
    ).fetchall():
        payload = json.loads(source["payload_json"])
        provider = _booking_provider(payload.get("provider"))
        source_channel = str(payload.get("source_channel") or "").lower()
        allowed_statuses = {"paid"} if provider == "booking.com" else {
            "paid", "completed"
        }
        if (
            provider not in {"booking.com", "agoda"}
            or source_channel not in {"mail", "authenticated_booking_portal"}
            or str(payload.get("record_type") or "").lower() != "charge"
            or str(payload.get("booking_confirmation_status") or "").lower()
            != "confirmed"
            or str(payload.get("status") or "").lower() not in allowed_statuses
            or not payload.get("message_id")
            or not payload.get("booking_number")
        ):
            continue
        payload["_normalized_provider"] = provider
        payload["_source_record_id"] = int(source["id"])
        card_suffix = str(
            payload.get("card4") or payload.get("card_last4") or ""
        ).strip()
        ineligible_reason = ""
        if provider == "booking.com" and not payload.get("payment_date"):
            ineligible_reason = "missing_payment_date"
        elif not payload.get("currency"):
            ineligible_reason = "missing_currency"
        elif not _decimal_key(payload.get("foreign_amount")):
            ineligible_reason = "missing_foreign_amount"
        elif (
            provider == "agoda"
            and not payload.get("payment_date")
            and not card_suffix
        ):
            ineligible_reason = "missing_date_and_card_suffix"
        if ineligible_reason:
            payload["_ineligible_reason"] = ineligible_reason
            store_unique(ineligible_by_message, payload)
            continue
        store_unique(direct_by_message, payload)
    direct_rows = list(direct_by_message.values())

    payments = [
        dict(row)
        for row in db.execute(
            """
            SELECT p.id, p.external_key,
                   COALESCE(
                       direct.card_event_id,
                       identity.card_event_id,
                       p.source_event_id
                   )
                     AS source_event_id,
                   p.occurred_on, p.merchant, p.currency, p.foreign_amount,
                   p.amount_krw, p.transaction_type, method.last4
            FROM payment_transactions p
            LEFT JOIN direct_payment_links link
              ON link.payment_id=p.id AND link.link_status='confirmed'
            LEFT JOIN direct_normalized_payments direct
              ON direct.id=link.direct_payment_id
            LEFT JOIN payment_methods method ON method.id=p.payment_method_id
            LEFT JOIN card_event_identities identity
              ON identity.transaction_id=p.id
            WHERE p.amount_krw>0
              AND p.transaction_type='purchase'
              AND (
                  p.source_event_id LIKE 'card:%'
                  OR direct.card_event_id IS NOT NULL
                  OR identity.card_event_id IS NOT NULL
              )
            ORDER BY p.id
            """
        ).fetchall()
    ]
    payment_by_id = {int(row["id"]): row for row in payments}
    evidence_by_message = {
        str(row["message_id"]): row for row in direct_rows
    }
    candidates: dict[str, set[int]] = {}
    reverse: dict[int, set[str]] = defaultdict(set)
    for evidence in direct_rows:
        message_id = str(evidence["message_id"])
        card4 = str(
            evidence.get("card4") or evidence.get("card_last4") or ""
        ).strip()
        matched: set[int] = set()
        for payment in payments:
            merchant = re.sub(
                r"[^0-9A-Z]", "", str(payment.get("merchant") or "").upper()
            )
            provider = str(evidence["_normalized_provider"])
            merchant_token = (
                "BOOKINGCOM" if provider == "booking.com" else "AGODA"
            )
            if merchant_token not in merchant:
                continue
            payment_date = str(evidence.get("payment_date") or "")
            if payment_date and str(payment.get("occurred_on") or "") != payment_date:
                continue
            if str(payment.get("currency") or "").upper() != str(
                evidence["currency"]
            ).upper():
                continue
            if _decimal_key(payment.get("foreign_amount")) != _decimal_key(
                evidence["foreign_amount"]
            ):
                continue
            if card4 and str(payment.get("last4") or "") != card4:
                continue
            payment_id = int(payment["id"])
            matched.add(payment_id)
            reverse[payment_id].add(message_id)
        candidates[message_id] = matched

    result = {
        "records": len(direct_rows),
        "confirmed_strong": 0,
        "conflict_records": 0,
        "unmatched_records": 0,
        "booking_links": 0,
        "ineligible_records": len(ineligible_by_message),
        "ineligible_reasons": dict(
            sorted(
                Counter(
                    str(row["_ineligible_reason"])
                    for row in ineligible_by_message.values()
                ).items()
            )
        ),
        "by_provider": {},
    }
    for provider in sorted(
        {
            str(row["_normalized_provider"])
            for row in [
                *direct_rows,
                *ineligible_by_message.values(),
            ]
        }
    ):
        result["by_provider"][provider] = {
            "records": sum(
                str(row["_normalized_provider"]) == provider
                for row in direct_rows
            ),
            "confirmed_strong": 0,
            "conflict_records": 0,
            "unmatched_records": 0,
            "booking_links": 0,
            "ineligible_records": sum(
                str(row["_normalized_provider"]) == provider
                for row in ineligible_by_message.values()
            ),
            "ineligible_reasons": dict(
                sorted(
                    Counter(
                        str(row["_ineligible_reason"])
                        for row in ineligible_by_message.values()
                        if str(row["_normalized_provider"]) == provider
                    ).items()
                )
            ),
        }

    def bump(provider: str, key: str, amount: int = 1) -> None:
        result[key] += amount
        result["by_provider"][provider][key] += amount

    def evidence_lineage(row: Mapping[str, object]) -> dict[str, object]:
        extraction_sources = row.get("extraction_sources")
        extraction_source = (
            str(extraction_sources[0])
            if isinstance(extraction_sources, list) and extraction_sources
            else "message_body"
        )
        source_channel = str(row.get("source_channel") or "")
        return {
            "source_type": (
                "ota_authenticated_portal"
                if source_channel == "authenticated_booking_portal"
                else "ota_mail"
            ),
            "source_channel": source_channel,
            "message_id": str(row["message_id"]),
            "source_record_id": f"direct_source:{row['_source_record_id']}",
            "provider": str(row["_normalized_provider"]),
            "attachment_state": "not_applicable",
            "forwarded_state": "not_forwarded",
            "amount_currency_state": "resolved",
            "ota_field_loss_state": "clear",
            "extraction_source": extraction_source,
        }

    confirmed_messages: set[str] = set()
    for message_id, payment_ids in sorted(candidates.items()):
        if len(payment_ids) != 1:
            continue
        payment_id = next(iter(payment_ids))
        if len(reverse[payment_id]) != 1:
            continue
        evidence = evidence_by_message[message_id]
        payment = payment_by_id[payment_id]
        provider = str(evidence["_normalized_provider"])
        booking = db.execute(
            """
            SELECT id FROM bookings
            WHERE provider=? AND booking_number=?
            """,
            (provider, str(evidence["booking_number"])),
        ).fetchone()
        if booking is None:
            continue
        booking_id = int(booking["id"])
        lineage = [evidence_lineage(evidence)]
        source_event_id = str(payment["source_event_id"])

        def matched_signal(
            name: str, left: object, right: object
        ) -> dict[str, object]:
            return {
                "name": name,
                "status": "match",
                "left": left,
                "right": right,
                "rule_id": f"{provider}-direct-payment-v1",
                "source_event_id": source_event_id,
                "evidence": lineage,
            }

        signals = [
            matched_signal(
                "booking_number",
                evidence["booking_number"],
                evidence["booking_number"],
            ),
            matched_signal("provider", provider, provider),
            matched_signal("product_type", "lodging", "lodging"),
            matched_signal(
                "currency", payment["currency"], evidence["currency"]
            ),
            matched_signal(
                "foreign_amount",
                payment["foreign_amount"],
                evidence["foreign_amount"],
            ),
            matched_signal(
                "service_start_on",
                evidence["service_start_on"],
                evidence["service_start_on"],
            ),
            matched_signal(
                "service_end_on",
                evidence["service_end_on"],
                evidence["service_end_on"],
            ),
        ]
        if evidence.get("payment_date"):
            signals.append(
                matched_signal(
                    "occurred_on",
                    payment["occurred_on"],
                    evidence["payment_date"],
                )
            )
        card4 = str(
            evidence.get("card4") or evidence.get("card_last4") or ""
        ).strip()
        if card4:
            signals.append(matched_signal("card_suffix", payment["last4"], card4))
        provider_key = "booking" if provider == "booking.com" else provider
        group_key = f"{provider_key}-direct:{message_id}"
        group_id = create_match_group(
            db,
            group_key,
            provider=provider,
            status="confirmed_strong",
            confidence=1.0,
            rationale=(
                f"{provider} 직접 결제증빙과 카드 원천의 통화·외화금액·"
                "카드끝4 및 가용 결제일 고유 교차"
            ),
            payment_ids=[payment_id],
            booking_ids=[booking_id],
            signals=signals,
        )
        decision_id = f"{provider_key}-direct-v1:{message_id}"
        record_match_decision(
            db,
            decision_id,
            group_id,
            status="confirmed_strong",
            actor="direct_evidence_reconciler",
            reason_code="unique_direct_payment_intersection",
            rationale=(
                "직접 결제증빙의 예약번호와 카드 원천이 고유하게 교차한다."
            ),
            evidence=lineage,
        )
        before = db.total_changes
        db.execute(
            """
            INSERT INTO payment_booking_links(
                payment_id, booking_id, relation_type, confidence, link_status
            ) VALUES (?, ?, 'pays_for', 1.0, 'confirmed')
            ON CONFLICT(payment_id, booking_id, relation_type) DO UPDATE SET
                confidence=excluded.confidence,
                link_status=excluded.link_status
            """,
            (payment_id, booking_id),
        )
        bump(provider, "booking_links", int(db.total_changes > before))
        bump(provider, "confirmed_strong")
        confirmed_messages.add(message_id)

    visited_messages: set[str] = set()
    for start_message, start_payments in sorted(candidates.items()):
        if start_message in confirmed_messages or start_message in visited_messages:
            continue
        if not start_payments:
            evidence = evidence_by_message[start_message]
            provider = str(evidence["_normalized_provider"])
            provider_key = "booking" if provider == "booking.com" else provider
            booking = db.execute(
                """
                SELECT id FROM bookings
                WHERE provider=? AND booking_number=?
                """,
                (provider, str(evidence["booking_number"])),
            ).fetchone()
            group_id = create_match_group(
                db,
                f"{provider_key}-direct-unmatched:{start_message}",
                provider=provider,
                status="unmatched",
                rationale="직접 결제메일과 정확히 교차하는 카드 외화 원천이 없음",
                booking_ids=[int(booking["id"])] if booking else [],
                signals=[
                    {
                        "name": "booking_number",
                        "status": "match",
                        "left": evidence["booking_number"],
                        "right": evidence["booking_number"],
                        "rule_id": f"{provider}-direct-payment-v1",
                        "evidence": [evidence_lineage(evidence)],
                    }
                ],
            )
            record_match_decision(
                db,
                f"{provider_key}-direct-unmatched-v1:{start_message}",
                group_id,
                status="unmatched",
                actor="direct_evidence_reconciler",
                reason_code="no_exact_card_intersection",
                rationale="카드 외화금액 또는 카드끝4 원천이 없어 자동 연결하지 않는다.",
                evidence=[evidence_lineage(evidence)],
            )
            visited_messages.add(start_message)
            bump(provider, "unmatched_records")
            continue

        component_messages: set[str] = set()
        component_payments: set[int] = set()
        queue: deque[tuple[str, object]] = deque([("message", start_message)])
        while queue:
            kind, value = queue.popleft()
            if kind == "message":
                message_id = str(value)
                if message_id in component_messages:
                    continue
                component_messages.add(message_id)
                visited_messages.add(message_id)
                for payment_id in candidates[message_id]:
                    queue.append(("payment", payment_id))
            else:
                payment_id = int(value)
                if payment_id in component_payments:
                    continue
                component_payments.add(payment_id)
                for message_id in reverse[payment_id]:
                    queue.append(("message", message_id))
        component_providers = {
            str(evidence_by_message[message_id]["_normalized_provider"])
            for message_id in component_messages
        }
        if len(component_providers) != 1:
            raise RuntimeError(
                "direct OTA conflict component crossed providers: "
                + ", ".join(sorted(component_providers))
            )
        provider = next(iter(component_providers))
        provider_key = "booking" if provider == "booking.com" else provider
        booking_ids = [
            int(row["id"])
            for message_id in sorted(component_messages)
            for row in db.execute(
                """
                SELECT id FROM bookings
                WHERE provider=? AND booking_number=?
                """,
                (
                    provider,
                    str(evidence_by_message[message_id]["booking_number"]),
                ),
            ).fetchall()
        ]
        evidence_rows = [
            evidence_by_message[message_id]
            for message_id in sorted(component_messages)
        ]
        component_key = hashlib.sha256(
            "|".join(sorted(component_messages)).encode("utf-8")
        ).hexdigest()[:16]
        group_id = create_match_group(
            db,
            f"{provider_key}-direct-conflict:{component_key}",
            provider=provider,
            status="conflict",
            confidence=0.0,
            rationale="동일 결제일·통화·외화금액 카드와 예약이 N:M으로 반복됨",
            payment_ids=sorted(component_payments),
            booking_ids=booking_ids,
            signals=[],
        )
        lineage = [evidence_lineage(row) for row in evidence_rows]
        record_match_decision(
            db,
            f"{provider_key}-direct-conflict-v1:{component_key}",
            group_id,
            status="conflict",
            actor="direct_evidence_reconciler",
            reason_code="non_unique_repeated_amount",
            rationale="승인시각 등 추가 식별자 없이는 반복금액을 1:1로 배정할 수 없다.",
            evidence=lineage,
        )
        bump(provider, "conflict_records", len(component_messages))
    return result


def import_all(
    db: sqlite3.Connection,
    ledger_dir: Path,
    manual_path: Path,
    ota_path: Path,
) -> dict[str, object]:
    with db:
        cards = import_cards(db, ledger_dir)
        from .reconciliation import project_direct_payments
        direct_projection = project_direct_payments(db)
        manual = import_manual(
            db,
            manual_path,
            ledger_dir / "data" / "manual_special_rows.json",
        )
        ota = import_ota(db, ota_path)
        supplemental_ota = {
            "records": 0,
            "inserted": 0,
            "confirmed_booking_periods": 0,
        }
        for supplemental_ota_path in (
            ledger_dir / "data" / "booking_direct_email_evidence.json",
            ledger_dir / "data" / "agoda_direct_email_evidence.json",
        ):
            if not supplemental_ota_path.exists():
                continue
            imported = import_ota(db, supplemental_ota_path)
            for key in supplemental_ota:
                supplemental_ota[key] += imported[key]
        portal_results: dict[str, dict[str, int]] = {}
        for provider in ("agoda", "booking", "trip"):
            portal_path = (
                ledger_dir / "data" / f"{provider}_direct_browser_evidence.json"
            )
            json_result = (
                import_ota(
                    db,
                    portal_path,
                    source_kind="ota_authenticated_portal",
                )
                if portal_path.exists()
                else {
                    "records": 0,
                    "inserted": 0,
                    "confirmed_booking_periods": 0,
                }
            )
            checkpoint_result = import_ota_checkpoint(
                db,
                ledger_dir / "data" / f"ota_checkpoints_{provider}.db",
                provider,
            )
            portal_results[provider] = {
                key: json_result[key] + checkpoint_result[key]
                for key in ("records", "inserted", "confirmed_booking_periods")
            }
        ota_portal = {
            key: sum(result[key] for result in portal_results.values())
            for key in ("records", "inserted", "confirmed_booking_periods")
        }
        receipt_path = (
            ledger_dir / "receipt_pipeline" / "receipt_batch_20260726.json"
        )
        if receipt_path.exists():
            # Lazy import avoids a module cycle: receipt_projection reuses the
            # privacy-safe direct-source insert primitive from this module.
            from .receipt_projection import import_receipt_batch

            receipts = import_receipt_batch(db, receipt_path)
        else:
            receipts = {
                "records": 0,
                "physical_events_appended": 0,
                "manual_events_projected": 0,
                "physical_event_total": 0,
                "manual_event_total": 0,
            }
        legacy_links = import_legacy_verified_links(
            db, ledger_dir / "data" / "ota_event_links_verified.json"
        )
        direct_ota_matches = reconcile_direct_ota_payment_evidence(db)
    return {
        "cards": cards,
        "manual": manual,
        # The inventory gate reconciles all durable OTA source records.  Keep
        # the mail-only view separately for callers that need its provenance.
        "ota": {
            key: ota[key] + supplemental_ota[key] + ota_portal[key]
            for key in ("records", "inserted", "confirmed_booking_periods")
        },
        "ota_mail": ota,
        "ota_supplemental_direct_email": supplemental_ota,
        "ota_authenticated_portal": ota_portal,
        "ota_authenticated_portal_by_provider": portal_results,
        "receipts": receipts,
        "legacy_verified_links": legacy_links,
        "direct_ota_matches": direct_ota_matches,
        "direct_projection": direct_projection,
        "direct_records": int(
            db.execute("SELECT COUNT(*) FROM direct_source_records").fetchone()[0]
        ),
    }


def import_legacy_verified_links(db: sqlite3.Connection, path: Path) -> dict[str, int]:
    """Append read-only legacy OTA links as durable manual/proposed decisions.

    The legacy file is evidence provenance, never a replacement projection:
    absent direct message lineage remains proposed.  Stable content hashes make
    replay idempotent and a changed legacy record raises rather than superseding
    a current decision.
    """
    if not path.exists():
        return {"records": 0, "created": 0, "proposed": 0, "missing_payment": 0}
    from .reconciliation import create_match_group, record_match_decision
    payload = json.loads(path.read_text(encoding="utf-8"))
    mail_index_path = path.with_name("ota_mail_index.json")
    mail_by_id: dict[str, dict[str, object]] = {}
    if mail_index_path.exists():
        mail_payload = json.loads(mail_index_path.read_text(encoding="utf-8"))
        mail_by_id = {
            str(item.get("messageId")): item
            for item in mail_payload.get("records", [])
            if isinstance(item, dict) and item.get("messageId")
        }
    created = proposed = missing = 0

    def signal(
        name: str,
        left: object,
        right: object,
        *,
        source_event_id: str = "",
    ) -> dict[str, object]:
        left_text = str(left or "").strip()
        right_text = str(right or "").strip()
        if not left_text or not right_text:
            status = "unavailable"
        else:
            status = "match" if left_text == right_text else "mismatch"
        return {
            "name": name,
            "status": status,
            "left": left_text or None,
            "right": right_text or None,
            "rule_id": "legacy-link-signal-v1",
            "source_event_id": source_event_id or None,
            "evidence": [
                {
                    "source_type": "legacy_verified_link",
                    "message_id": source_event_id or None,
                }
            ],
        }

    for external_key, record in sorted(payload.items()):
        if not isinstance(record, dict):
            continue
        payment = db.execute(
            """
            SELECT payment.id, payment.merchant, payment.amount_krw,
                   payment.occurred_on, payment.source_system, method.last4
            FROM payment_transactions payment
            LEFT JOIN payment_methods method ON method.id=payment.payment_method_id
            WHERE external_key=?
            """,
            (external_key,),
        ).fetchone()
        if payment is None:
            missing += 1; continue
        canonical = _canonical_hash(record)
        # A legacy evidence inventory is not the representative's append-only
        # decision log.  Even message+booking lineage remains a proposal until
        # record_match_decision() records an explicit manual review with its
        # own actor/reason/rationale and verified supersedes chain.
        source_message_id = str(
            record.get("message_id") or record.get("source_message_id") or ""
        )
        mail = mail_by_id.get(source_message_id)
        merchant = str(payment["merchant"] or "").upper()
        payment_provider = (
            "mytrip" if "MYTRIP" in merchant or "마이트립" in merchant
            else "trip" if "TRIP.COM" in merchant or "트립닷컴" in merchant
            else "manual_non_ota" if str(payment["source_system"]) == "MAN"
            else ""
        )
        mail_provider = str(
            (mail or {}).get("provider") or record.get("provider") or ""
        ).lower()
        provider_signal = signal(
            "provider",
            payment_provider,
            mail_provider,
            source_event_id=source_message_id,
        )

        paid_amount = record.get("paid_amount")
        mail_amounts = {
            abs(int(value))
            for value in (mail or {}).get("amounts", [])
            if str(value).lstrip("-").isdigit()
        }
        payment_amount = abs(int(payment["amount_krw"]))
        if paid_amount not in (None, ""):
            evidence_amount: object = abs(int(float(str(paid_amount))))
        elif payment_amount in mail_amounts:
            evidence_amount = payment_amount
        elif mail_amounts:
            evidence_amount = "|".join(str(value) for value in sorted(mail_amounts))
        else:
            evidence_amount = ""
        amount_signal = signal(
            "amount",
            payment_amount,
            evidence_amount,
            source_event_id=source_message_id,
        )

        expense_row = db.execute(
            """
            SELECT value FROM current_classification_decisions
            WHERE target_type='payment' AND target_id=?
              AND dimension='expense_type'
            """,
            (int(payment["id"]),),
        ).fetchone()
        expense_type = str(expense_row["value"] if expense_row else "")
        payment_product = (
            "항공" if "항공" in expense_type or payment_provider == "mytrip"
            else "숙박" if "숙박" in expense_type or "HOTEL" in merchant or "호텔" in merchant
            else "교통" if "교통" in expense_type or (
                str(payment["source_system"]) == "MAN" and "KOTSU" in merchant
            )
            else ""
        )
        evidence_product = str(record.get("category") or "")
        if not evidence_product and mail is not None:
            subject = str(mail.get("subject") or "")
            evidence_product = (
                "숙박" if "호텔" in subject or "HOTEL" in subject.upper()
                else "항공" if "항공" in subject or "FLIGHT" in subject.upper()
                else ""
            )
        product_signal = signal(
            "product",
            payment_product,
            evidence_product,
            source_event_id=source_message_id,
        )

        record_periods = {
            token
            for token in re.findall(
                r"(?<!\d)\d{4}(?!\d)",
                str(record.get("period") or ""),
            )
        }
        if (
            not record_periods
            and str(payment["source_system"]) == "MAN"
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(payment["occurred_on"] or ""))
        ):
            occurred = str(payment["occurred_on"])
            record_periods.add(occurred[5:7] + occurred[8:10])
        mail_periods = {
            str(token)
            for token in (mail or {}).get("travelDates", [])
            if re.fullmatch(r"\d{4}", str(token))
        }
        if record_periods and mail_periods and record_periods & mail_periods:
            common_periods = "|".join(sorted(record_periods & mail_periods))
            date_left: object = common_periods
            date_right: object = common_periods
        else:
            date_left = "|".join(sorted(record_periods))
            date_right = "|".join(sorted(mail_periods))
        date_signal = signal(
            "service_date",
            date_left,
            date_right,
            source_event_id=source_message_id,
        )
        card_signal = signal(
            "card_last4",
            payment["last4"],
            record.get("card4"),
            source_event_id=source_message_id,
        )
        signals = [
            provider_signal,
            amount_signal,
            product_signal,
            date_signal,
            card_signal,
        ]
        conflicts = [
            str(item["name"]) + "_conflict"
            for item in signals
            if item["status"] == "mismatch"
        ]
        status = "conflict" if conflicts else "proposed"
        group_key = "legacy-link:" + external_key + ":" + canonical[:16]
        rationale = (
            "legacy OTA link conflict: " + ",".join(conflicts)
            if conflicts
            else "read-only legacy OTA link"
        )
        group_id = create_match_group(db, group_key, provider=str(record.get("provider") or "legacy"), status=status, confidence=0.0, rationale=rationale, payment_ids=[int(payment[0])], signals=signals)
        decision_id = "legacy-ota-link:" + external_key + ":" + canonical
        if record_match_decision(db, decision_id, group_id, status=status, actor="legacy_import", reason_code="legacy_verified_link", rationale=rationale, evidence=[{"source_type":"legacy_verified_link","source_record_id":external_key,"content_hash":canonical,"record":record,"conflicts":conflicts}]):
            created += 1
        proposed += int(status == "proposed")
    return {"records": len(payload), "created": created, "proposed": proposed, "missing_payment": missing}


def compare_with_legacy(db: sqlite3.Connection) -> dict[str, int]:
    """직접 카드 원천과 legacy 카드 결제를 구조키로 대조한다."""
    direct = {
        str(row[0])
        for row in db.execute("SELECT DISTINCT card_event_id FROM direct_card_events")
    }
    legacy = {
        str(row[0])
        for row in db.execute(
            """
            SELECT DISTINCT i.card_event_id
            FROM card_event_identities i
            JOIN payment_transactions p ON p.id=i.transaction_id
            WHERE p.source_system IN ('KBD', 'KBO', 'HAN', 'CORP')
            """
        )
    }
    return {
        "direct_card_event_ids": len(direct),
        "legacy_card_event_ids": len(legacy),
        "direct_only": len(direct - legacy),
        "legacy_only": len(legacy - direct),
        "shared": len(direct & legacy),
    }
