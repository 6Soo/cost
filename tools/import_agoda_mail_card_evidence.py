"""Import redacted Agoda confirmation-PDF card evidence.

This adapter is intentionally separate from portal-detail evidence: a card suffix
observed in an emailed confirmation PDF must retain its mail provenance and must
never be relabelled as a portal observation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from ledger.domain.agoda_booking_evidence import ensure_schema, materialize_agoda_mail_bookings
from ledger.domain.direct_sources import _insert_source


ARTIFACT_TYPE = "agoda-mail-card-evidence-v1"
REDACTION_VERSION = "agoda-confirmation-card-allowlist-v1"
BOOKING_RE = re.compile(r"^[0-9]{8,32}$")
CARD4_RE = re.compile(r"^[0-9]{4}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MESSAGE_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
DECIMAL_RE = re.compile(r"^\d+(?:\.\d+)?$")


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_record(raw: Mapping[str, object]) -> dict[str, Any]:
    booking_id = _text(raw.get("booking_id"))
    message_id = _text(raw.get("gmail_message_id")).lower()
    card_type = _text(raw.get("card_type"))
    card4 = _text(raw.get("card_last4"))
    start = _text(raw.get("service_start_on"))
    end = _text(raw.get("service_end_on"))
    sent_at = _text(raw.get("sent_at"))
    evidence_hash = _text(raw.get("evidence_text_sha256")).lower()
    attachment_name = _text(raw.get("attachment_filename"))
    if not BOOKING_RE.fullmatch(booking_id):
        raise ValueError("mail_card_booking_id_invalid")
    if not MESSAGE_ID_RE.fullmatch(message_id):
        raise ValueError("mail_card_message_id_invalid")
    if not card_type or len(card_type) > 32 or any(ord(c) < 0x20 for c in card_type):
        raise ValueError("mail_card_type_invalid")
    if not CARD4_RE.fullmatch(card4):
        raise ValueError("mail_card_last4_invalid")
    if not DATE_RE.fullmatch(start) or not DATE_RE.fullmatch(end) or start >= end:
        raise ValueError("mail_card_service_period_invalid")
    if not sent_at or len(sent_at) > 64:
        raise ValueError("mail_card_sent_at_invalid")
    if not HASH_RE.fullmatch(evidence_hash):
        raise ValueError("mail_card_evidence_hash_invalid")
    if not attachment_name or len(attachment_name) > 180:
        raise ValueError("mail_card_attachment_name_invalid")
    payment = raw.get("scheduled_payment")
    normalized_payment: dict[str, str] | None = None
    if payment is not None:
        if not isinstance(payment, Mapping):
            raise ValueError("mail_card_scheduled_payment_invalid")
        currency = _text(payment.get("currency")).upper()
        decimal_text = _text(payment.get("decimal_text")).replace(",", "")
        due_on = _text(payment.get("due_on"))
        if (
            not CURRENCY_RE.fullmatch(currency)
            or not DECIMAL_RE.fullmatch(decimal_text)
            or not DATE_RE.fullmatch(due_on)
        ):
            raise ValueError("mail_card_scheduled_payment_invalid")
        normalized_payment = {
            "currency": currency,
            "decimal_text": decimal_text,
            "due_on": due_on,
        }
    return {
        "booking_id": booking_id,
        "gmail_message_id": message_id,
        "card_type": card_type,
        "card_last4": card4,
        "service_start_on": start,
        "service_end_on": end,
        "sent_at": sent_at,
        "evidence_text_sha256": evidence_hash,
        "attachment_filename_sha256": _sha256_text(attachment_name),
        "scheduled_payment": normalized_payment,
    }


def load_artifact(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping) or document.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("mail_card_artifact_type_invalid")
    records = document.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("mail_card_records_invalid")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ValueError("mail_card_record_invalid")
        item = _validate_record(raw)
        if item["booking_id"] in seen:
            raise ValueError("mail_card_booking_duplicate")
        seen.add(item["booking_id"])
        normalized.append(item)
    return normalized


def import_artifact(db_path: Path, artifact_path: Path, run_id: str) -> dict[str, Any]:
    records = load_artifact(artifact_path)
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA foreign_keys=ON")
    inserted = 0
    source_ids: list[int] = []
    try:
        db.execute("BEGIN IMMEDIATE")
        ensure_schema(db)
        for item in records:
            booking = db.execute(
                """SELECT id, product_type, label, service_start_on, service_end_on, status
                   FROM bookings WHERE provider='agoda' AND booking_number=?""",
                (item["booking_id"],),
            ).fetchone()
            if booking is None:
                raise ValueError(f"mail_card_booking_missing:{item['booking_id']}")
            if str(booking[3] or "") != item["service_start_on"] or str(booking[4] or "") != item["service_end_on"]:
                raise ValueError(f"mail_card_service_period_conflict:{item['booking_id']}")
            payload: dict[str, object] = {
                "provider": "agoda",
                "booking_number": item["booking_id"],
                "product_type": str(booking[1] or "lodging"),
                "label": str(booking[2] or "agoda booking"),
                "service_start_on": item["service_start_on"],
                "service_end_on": item["service_end_on"],
                "status": str(booking[5] or "unknown"),
                "sent_at": item["sent_at"],
                "gmail_message_id": item["gmail_message_id"],
                "attachment_filename_sha256": item["attachment_filename_sha256"],
                "evidence_text_sha256": item["evidence_text_sha256"],
                "evidence_origin": "gmail_attachment_confirmation_pdf",
                "card_type": item["card_type"],
                "card_last4": item["card_last4"],
                "card_observation_status": "observed_card4",
                "scheduled_payment": item["scheduled_payment"],
                "import_contract": ARTIFACT_TYPE,
            }
            source_key = ":".join((
                item["gmail_message_id"],
                item["booking_id"],
                item["evidence_text_sha256"],
            ))
            source_id, created = _insert_source(
                db, "ota_mail_live", source_key, payload, REDACTION_VERSION
            )
            source_ids.append(source_id)
            inserted += int(created)
        materialized = materialize_agoda_mail_bookings(db)
        if materialized["conflicts"]:
            raise ValueError("mail_card_materialization_conflict")
        for source_id in source_ids:
            linked = db.execute(
                """SELECT COUNT(*) FROM booking_source_evidence
                   WHERE direct_source_record_id=? AND evidence_kind='ota_mail_live'
                     AND evidence_role='identity' AND evidence_status='observed'""",
                (source_id,),
            ).fetchone()[0]
            if int(linked) != 1:
                raise RuntimeError("mail_card_identity_link_missing")
        integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = list(db.execute("PRAGMA foreign_key_check"))
        if integrity != "ok" or foreign_keys:
            raise RuntimeError("mail_card_import_integrity_failure")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {
        "records": len(records),
        "source_inserted": inserted,
        "source_ids": source_ids,
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(_canonical_json(import_artifact(args.db, args.input, args.run_id)))


if __name__ == "__main__":
    main()
