"""P6 카드·수기·OTA 원천의 멱등 직접 적재와 legacy 병렬 대조."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from pathlib import Path
from typing import Iterable, Mapping

from ledger import cardindex
from ledger.domain.source_adapters import (
    OTA_REDACTION_VERSION,
    PG_REDACTION_VERSION,
    SERVICE_MAIL_REDACTION_VERSION,
    adapt_ota_record,
    adapt_pg_record,
    adapt_service_mail_record,
    stable_card_event_identity,
)
from ledger.domain.han_normalizer import (HAN_NORMALIZER_CONTRACT_SHA256,
    HAN_NORMALIZER_VERSION, HanRawAmounts, normalize_han_components)


DIRECT_CARD_NORMALIZATION_VERSION = "direct-card-v3"


def _normalize_single_payment(
    normalized: Mapping[str, object],
) -> tuple[int, str]:
    raw_amount = int(normalized["krw"])
    source = str(normalized["src"])
    cancelled = bool(normalized["cancel"])
    if cancelled and source in {"KBO", "CORP"}:
        return -abs(raw_amount), "cancellation"
    if raw_amount < 0:
        return raw_amount, "refund"
    if cancelled:
        return raw_amount, "cancellation"
    if raw_amount == 0:
        return 0, "adjustment"
    return raw_amount, "purchase"


def _canonical_hash(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(payload: object) -> str:
    """Return the exact UTF-8 JSON representation represented by _canonical_hash."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _insert_source(
    db: sqlite3.Connection,
    kind: str,
    key: str,
    payload: dict[str, object],
    redaction_version: str | None = None,
) -> tuple[int, bool]:
    digest = _canonical_hash(payload)
    rows = db.execute(
        """SELECT source_sha256, payload_json FROM direct_source_records
           WHERE source_kind=? AND source_key=? ORDER BY id""", (kind, key)
    ).fetchall()
    if len(rows) > 1 or (rows and rows[0][0] != digest):
        raise ValueError(f"source_key_content_conflict:{kind}:{key}")
    if rows:
        try:
            stored_digest = _canonical_hash(json.loads(rows[0][1]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"source_payload_digest_inconsistent:{kind}:{key}") from exc
        if stored_digest != rows[0][0]:
            raise ValueError(f"source_payload_digest_inconsistent:{kind}:{key}")
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
            # The stored payload bytes must be exactly the bytes covered by
            # source_sha256; otherwise the source layer advertises a digest
            # for data it did not actually store.
            _canonical_json(payload),
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


def import_cards(
    db: sqlite3.Connection,
    ledger_dir: Path,
    *,
    cards: list[Mapping[str, object]] | None = None,
) -> dict[str, int]:
    """카드 RAW xlsx를 legacy classified CSV 없이 직접 읽는다."""
    card_rows = (
        list(cards)
        if cards is not None
        else list(cardindex.build_cards(ledger_dir=ledger_dir))
    )

    inserted = 0
    identities: dict[str, list[int]] = {}
    for card in card_rows:
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
            "sub": card.get("sub", ""),
            "krw": card.get("krw", 0),
            "approval_amount": card.get("approval_amount", 0),
            "cancel_amount": card.get("cancel_amount", 0),
            "purchase_amount": card.get("purchase_amount", 0),
            "cancel": card.get("cancel", False),
            "status": card.get("status", ""),
        }
        if normalized["src"] == "HAN":
            raw_amounts = (card.get("approval_amount"), card.get("purchase_amount"), card.get("cancel_amount"))
            if any(type(value) is not int for value in raw_amounts) or type(card.get("cancel")) is not bool:
                raise ValueError("han_envelope_type_invalid")
            expected_components = normalize_han_components(HanRawAmounts(
                raw_amounts[0], raw_amounts[1], raw_amounts[2]))
            expected_wire = tuple((x.role, x.signed_amount_krw, x.transaction_type,
                                   x.selection_reason) for x in expected_components)
            supplied_wire = card.get("han_components")
            wire_types_valid = isinstance(supplied_wire, (tuple, list)) and all(
                isinstance(x, (tuple, list)) and len(x) == 4 and type(x[0]) is str and
                type(x[1]) is int and type(x[2]) is str and type(x[3]) is str
                for x in supplied_wire)
            if (card.get("han_normalizer_version") != HAN_NORMALIZER_VERSION or
                card.get("han_contract_sha256") != HAN_NORMALIZER_CONTRACT_SHA256 or
                card.get("amount_selection_reason") != expected_components[0].selection_reason or
                type(card.get("krw")) is not int or card.get("krw") != expected_components[0].signed_amount_krw or
                card.get("cancel") is not bool(raw_amounts[2]) or not wire_types_valid or
                tuple(tuple(x) if isinstance(x, (tuple, list)) else () for x in supplied_wire) != expected_wire):
                raise ValueError("han_component_contract_mismatch")
            normalized.update(
                amount_selection_reason=expected_components[0].selection_reason,
                han_normalizer_version=HAN_NORMALIZER_VERSION,
                han_contract_sha256=HAN_NORMALIZER_CONTRACT_SHA256,
                han_components=[{"role": x.role, "signed_amount_krw": x.signed_amount_krw,
                    "transaction_type": x.transaction_type, "selection_reason": x.selection_reason}
                    for x in expected_components],
            )
        identity = stable_card_event_identity(normalized)
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
                int(normalized["krw"]),
                normalized["appr"] or None,
                normalized["use_date"] or None,
                normalized["merchant"],
            ),
        )
        if normalized["src"] == "HAN":
            components = []
            for component in expected_components:
                identity_row = dict(normalized)
                identity_row.update(krw=component.signed_amount_krw,
                    cancel=component.role == "cancellation",
                    raw_record_id=(normalized["raw_record_id"] if component.role == "single"
                        else f"{normalized['raw_record_id']}:{component.role}"))
                components.append((component.role, stable_card_event_identity(identity_row),
                    component.signed_amount_krw, component.transaction_type))
        else:
            amount, transaction_type = _normalize_single_payment(normalized)
            components = [("single", identity, amount, transaction_type)]

        for role, component_identity, amount, transaction_type in components:
            db.execute(
                """
                INSERT INTO direct_normalized_payments(
                    source_record_id, event_role, card_event_id, amount_krw,
                    transaction_type, normalization_version
                ) VALUES (?, ?, ?, ?, ?, ?)
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
                    DIRECT_CARD_NORMALIZATION_VERSION,
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
        "records": len(card_rows),
        "inserted": inserted,
        "identity_collisions": sum(
            len(source_ids) for source_ids in identities.values() if len(source_ids) > 1
        ),
        "normalized_payments": int(
            db.execute("SELECT COUNT(*) FROM direct_normalized_payments").fetchone()[0]
        ),
    }


def import_manual(
    db: sqlite3.Connection, path: Path, *, raw_bytes: bytes | None = None,
) -> dict[str, int]:
    text = (raw_bytes if raw_bytes is not None else path.read_bytes()).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    inserted = 0
    for row in rows:
        key = f"{row.get('tab')}:{row.get('row')}"
        _, created = _insert_source(db, "manual_ledger", key, dict(row))
        inserted += int(created)
    return {"records": len(rows), "inserted": inserted}


def _strict_json_bytes(raw_bytes: bytes, label: str) -> object:
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label}_duplicate_key:{key}")
            result[key] = value
        return result

    try:
        return json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"{label}_nonfinite:{value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}_json_invalid") from exc


def import_ota(
    db: sqlite3.Connection,
    path: Path,
    *,
    raw_bytes: bytes | None = None,
    source_kind: str = "ota_mail",
) -> dict[str, int]:
    raw = _strict_json_bytes(
        raw_bytes if raw_bytes is not None else path.read_bytes(), "ota_mail"
    )
    if not isinstance(raw, dict):
        raise ValueError("ota_mail_root_invalid")
    rows: Iterable[dict[str, object]] = raw.get("records", raw)
    count = 0
    inserted = 0
    for index, row in enumerate(rows):
        clean = adapt_ota_record(row)
        key = str(clean.get("message_id") or f"row:{index}")
        _, created = _insert_source(
            db,
            source_kind,
            key,
            clean,
            OTA_REDACTION_VERSION,
        )
        inserted += int(created)
        count += 1
    return {"records": count, "inserted": inserted}


def import_pg_mail(
    db: sqlite3.Connection,
    path: Path,
    *,
    raw_bytes: bytes | None = None,
    source_kind: str = "pg_mail",
) -> dict[str, int]:
    """Import redacted PG receipts and lifecycle messages idempotently."""
    raw = _strict_json_bytes(
        raw_bytes if raw_bytes is not None else path.read_bytes(), "pg_mail"
    )
    if not isinstance(raw, dict):
        raise ValueError("pg_mail_root_invalid")
    rows = raw.get("records")
    if not isinstance(rows, list):
        raise ValueError("pg_mail_records_invalid")
    count = 0
    inserted = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"pg_mail_row_invalid:{index}")
        clean = adapt_pg_record(row)
        key = str(clean["message_id"])
        _, created = _insert_source(
            db, source_kind, key, clean, PG_REDACTION_VERSION,
        )
        inserted += int(created)
        count += 1
    return {"records": count, "inserted": inserted}


def import_service_mail(
    db: sqlite3.Connection,
    path: Path,
    *,
    raw_bytes: bytes | None = None,
) -> dict[str, int]:
    """Import a redacted provider service-period index."""
    raw = _strict_json_bytes(
        raw_bytes if raw_bytes is not None else path.read_bytes(), "service_mail"
    )
    if not isinstance(raw, dict) or not isinstance(raw.get("records"), list):
        raise ValueError("service_mail_root_invalid")
    inserted = 0
    for index, row in enumerate(raw["records"]):
        if not isinstance(row, dict):
            raise ValueError(f"service_mail_row_invalid:{index}")
        clean = adapt_service_mail_record(row)
        _, created = _insert_source(
            db, "service_mail", str(clean["message_id"]), clean,
            SERVICE_MAIL_REDACTION_VERSION,
        )
        inserted += int(created)
    return {"records": len(raw["records"]), "inserted": inserted}


def import_trip_schedule(
    db: sqlite3.Connection, path: Path, *, raw_bytes: bytes | None = None,
) -> dict[str, int]:
    raw = _strict_json_bytes(
        raw_bytes if raw_bytes is not None else path.read_bytes(), "trip_schedule"
    )
    if not isinstance(raw, list) or not raw:
        raise ValueError("trip_schedule_root_invalid")
    inserted = 0
    for index, row in enumerate(raw):
        if not isinstance(row, dict) or not isinstance(row.get("tab"), str):
            raise ValueError(f"trip_schedule_row_invalid:{index}")
        _, created = _insert_source(db, "trip_schedule", str(row["tab"]), dict(row))
        inserted += int(created)
    return {"records": len(raw), "inserted": inserted}


def import_geographic_trip_context(
    db: sqlite3.Connection, path: Path, *, raw_bytes: bytes | None = None,
) -> dict[str, int]:
    """Import historical trip context without making it transaction evidence."""
    raw = _strict_json_bytes(
        raw_bytes if raw_bytes is not None else path.read_bytes(),
        "geographic_trip_context",
    )
    from ledger.domain.direct_geographic_trip_context import (
        validate_geographic_trip_context_document,
    )
    records = validate_geographic_trip_context_document(raw)
    inserted = 0
    for row in records:
        _, created = _insert_source(
            db,
            "geographic_trip_context",
            str(row["tab"]),
            dict(row),
            "historical-context-only-v1",
        )
        inserted += int(created)
    return {"records": len(records), "inserted": inserted}


def import_lodging_facts(
    db: sqlite3.Connection, path: Path, *, raw_bytes: bytes | None = None,
) -> dict[str, int]:
    raw = _strict_json_bytes(
        raw_bytes if raw_bytes is not None else path.read_bytes(), "ota_lodging_fact"
    )
    from ledger.domain.direct_verified_ota_lodging import (
        validate_lodging_fact_document,
    )
    document = validate_lodging_fact_document(raw)
    inserted = 0
    for row in document["records"]:
        _, created = _insert_source(
            db, "ota_lodging_fact", str(row["message_id"]), dict(row),
            str(document["privacy_contract"]),
        )
        inserted += int(created)
    return {"records": len(document["records"]), "inserted": inserted}


def import_ota_reservation_facts(
    db: sqlite3.Connection, path: Path, *, raw_bytes: bytes | None = None,
) -> dict[str, int]:
    """Import typed OTA reservation facts without deriving any card match."""
    raw = _strict_json_bytes(
        raw_bytes if raw_bytes is not None else path.read_bytes(),
        "ota_reservation_fact",
    )
    if not isinstance(raw, dict) or not raw:
        raise ValueError("ota_reservation_fact_root_invalid")
    inserted = 0
    for key, row in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("ota_reservation_fact_key_invalid")
        if not isinstance(row, dict):
            raise ValueError(f"ota_reservation_fact_row_invalid:{key}")
        _, created = _insert_source(
            db,
            "ota_reservation_fact",
            key,
            dict(row),
            "ota-reservation-fact-v1",
        )
        inserted += int(created)
    return {"records": len(raw), "inserted": inserted}


def import_current_owner_decisions(
    db: sqlite3.Connection, path: Path, *, raw_bytes: bytes | None = None,
) -> dict[str, int]:
    """Import explicit current-run decisions as auditable source records."""
    from ledger.domain.direct_current_owner_decision import (
        CONTRACT, SOURCE_KIND, parse_owner_decision_document,
    )
    raw = raw_bytes if raw_bytes is not None else path.read_bytes()
    decisions = parse_owner_decision_document(raw)
    inserted = 0
    for row in decisions:
        _, created = _insert_source(
            db,
            SOURCE_KIND,
            str(row["decision_id"]),
            dict(row),
            CONTRACT,
        )
        inserted += int(created)
    return {"records": len(decisions), "inserted": inserted}


def import_all(
    db: sqlite3.Connection,
    ledger_dir: Path,
    manual_path: Path,
    ota_path: Path,
    *,
    cards: list[Mapping[str, object]] | None = None,
    source_bytes: Mapping[str, bytes] | None = None,
    trip_path: Path | None = None,
    geographic_context_path: Path | None = None,
    lodging_fact_path: Path | None = None,
    reservation_path: Path | None = None,
    owner_decision_path: Path | None = None,
    live_ota_path: Path | None = None,
    pg_mail_path: Path | None = None,
    pg_mail_supplement_path: Path | None = None,
    service_mail_path: Path | None = None,
    materialize_agoda_bookings: bool = True,
) -> dict[str, object]:
    snapshots = dict(source_bytes or {})
    with db:
        card_result = import_cards(db, ledger_dir, cards=cards)
        manual = import_manual(
            db, manual_path, raw_bytes=snapshots.get("manual_ledger")
        )
        ota = import_ota(db, ota_path, raw_bytes=snapshots.get("ota_mail"))
        pg_mail = (
            import_pg_mail(
                db, pg_mail_path, raw_bytes=snapshots.get("pg_mail")
            )
            if pg_mail_path is not None else None
        )
        pg_mail_supplement = (
            import_pg_mail(
                db, pg_mail_supplement_path,
                raw_bytes=(
                    snapshots.get("pg_mail_supplement")
                ),
                source_kind="pg_mail_supplement",
            )
            if pg_mail_supplement_path is not None else None
        )
        service_mail = (
            import_service_mail(
                db, service_mail_path, raw_bytes=snapshots.get("service_mail")
            )
            if service_mail_path is not None else None
        )
        live_ota = (
            import_ota(
                db,
                live_ota_path,
                raw_bytes=snapshots.get("ota_mail_live"),
                source_kind="ota_mail_live",
            )
            if live_ota_path is not None and live_ota_path.is_file()
            else None
        )
        agoda_bookings = None
        if materialize_agoda_bookings:
            from ledger.domain.agoda_booking_evidence import (
                materialize_agoda_mail_bookings,
            )
            agoda_bookings = materialize_agoda_mail_bookings(db)
        trip = (
            import_trip_schedule(
                db, trip_path, raw_bytes=snapshots.get("trip_schedule")
            )
            if trip_path is not None else None
        )
        geographic_context = (
            import_geographic_trip_context(
                db,
                geographic_context_path,
                raw_bytes=snapshots.get("geographic_trip_context"),
            )
            if geographic_context_path is not None else None
        )
        lodging = (
            import_lodging_facts(
                db, lodging_fact_path,
                raw_bytes=snapshots.get("ota_lodging_fact"),
            )
            if lodging_fact_path is not None else None
        )
        reservation = (
            import_ota_reservation_facts(
                db, reservation_path,
                raw_bytes=snapshots.get("ota_reservation_fact"),
            )
            if reservation_path is not None else None
        )
        owner_decisions = (
            import_current_owner_decisions(
                db, owner_decision_path,
                raw_bytes=snapshots.get("current_owner_decision"),
            )
            if owner_decision_path is not None else None
        )
    result = {
        "cards": card_result,
        "manual": manual,
        "ota": ota,
        "pg_mail": pg_mail,
        "pg_mail_supplement": pg_mail_supplement,
        "service_mail": service_mail,
        "ota_live": live_ota,
        "agoda_bookings": agoda_bookings,
        "direct_records": int(
            db.execute("SELECT COUNT(*) FROM direct_source_records").fetchone()[0]
        ),
    }
    if trip is not None:
        result["trip_schedule"] = trip
    if geographic_context is not None:
        result["geographic_trip_context"] = geographic_context
    if lodging is not None:
        result["ota_lodging_fact"] = lodging
    if reservation is not None:
        result["ota_reservation_fact"] = reservation
    if owner_decisions is not None:
        result["current_owner_decision"] = owner_decisions
    return result


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
