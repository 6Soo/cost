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
    sanitize_ota_record,
    stable_card_event_identity,
)


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
        approval_amount = int(normalized["approval_amount"])
        cancel_amount = int(normalized["cancel_amount"])
        if normalized["src"] == "HAN" and cancel_amount:
            approval_row = dict(normalized)
            approval_row.update(
                krw=abs(approval_amount),
                cancel=False,
                raw_record_id=f"{normalized['raw_record_id']}:approval",
            )
            cancellation_row = dict(normalized)
            cancellation_row.update(
                krw=-abs(cancel_amount),
                cancel=True,
                raw_record_id=f"{normalized['raw_record_id']}:cancellation",
            )
            components = [
                (
                    "approval",
                    stable_card_event_identity(approval_row),
                    abs(approval_amount),
                    "purchase",
                ),
                (
                    "cancellation",
                    stable_card_event_identity(cancellation_row),
                    -abs(cancel_amount),
                    "cancellation",
                ),
            ]
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
        clean = sanitize_ota_record(row)
        # 이미 구조화된 인덱스의 camelCase 필드도 허용목록 이름으로 매핑한다.
        for old, new in (
            ("messageId", "message_id"),
            ("messageHash", "message_hash"),
            ("bookingRefs", "booking_number"),
            ("travelDates", "period_original"),
        ):
            if old in row and new not in clean:
                clean[new] = row[old]
        clean["redaction_version"] = OTA_REDACTION_VERSION
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
