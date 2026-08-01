"""P6 카드·수기·OTA 원천의 멱등 직접 적재와 legacy 병렬 대조."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable, Mapping

from ledger import cardindex
from ledger.domain.source_adapters import (
    OTA_REDACTION_VERSION,
    adapt_ota_record,
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
    cards = cardindex.build_cards(ledger_dir=ledger_dir)

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
        "records": len(cards),
        "inserted": inserted,
        "identity_collisions": sum(
            len(source_ids) for source_ids in identities.values() if len(source_ids) > 1
        ),
        "normalized_payments": int(
            db.execute("SELECT COUNT(*) FROM direct_normalized_payments").fetchone()[0]
        ),
    }


def import_manual(db: sqlite3.Connection, path: Path) -> dict[str, int]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    inserted = 0
    for row in rows:
        key = f"{row.get('tab')}:{row.get('row')}"
        _, created = _insert_source(db, "manual_ledger", key, dict(row))
        inserted += int(created)
    return {"records": len(rows), "inserted": inserted}


def import_ota(db: sqlite3.Connection, path: Path) -> dict[str, int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows: Iterable[dict[str, object]] = raw.get("records", raw)
    count = 0
    inserted = 0
    for index, row in enumerate(rows):
        clean = adapt_ota_record(row)
        key = str(clean.get("message_id") or f"row:{index}")
        _, created = _insert_source(
            db,
            "ota_mail",
            key,
            clean,
            OTA_REDACTION_VERSION,
        )
        inserted += int(created)
        count += 1
    return {"records": count, "inserted": inserted}


def import_all(
    db: sqlite3.Connection,
    ledger_dir: Path,
    manual_path: Path,
    ota_path: Path,
) -> dict[str, object]:
    with db:
        cards = import_cards(db, ledger_dir)
        manual = import_manual(db, manual_path)
        ota = import_ota(db, ota_path)
    return {
        "cards": cards,
        "manual": manual,
        "ota": ota,
        "direct_records": int(
            db.execute("SELECT COUNT(*) FROM direct_source_records").fetchone()[0]
        ),
    }


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
