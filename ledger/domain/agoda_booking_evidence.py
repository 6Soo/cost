"""Agoda mail/portal evidence를 하나의 canonical booking에 연결한다.

이 모듈은 예약 객체와 원천 증거의 관계만 만든다. 카드 승인·매입 행을
추정하거나 ``payment_booking_links``를 자동 확정하지 않는다. 포털의
``paid_today``도 issuer charge가 아닌 포털의 결제 상태로 보존한다.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping

from ledger.domain.direct_sources import _insert_source


REDACTION_VERSION = "agoda-booking-evidence-v1"
EVIDENCE_KINDS = {"ota_mail", "ota_mail_live", "agoda_portal_detail"}
BOOKING_NUMBER_RE = re.compile(r"^[0-9]{8,32}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{4}$|^\d{2}\d{2}$")
MINOR_UNITS_MIN = -(1 << 63)
MINOR_UNITS_MAX = (1 << 63) - 1
COMPONENT_KINDS = {
    "base",
    "charge",
    "chargeback",
    "coupon",
    "fee",
    "gross_total",
    "paid_today",
    "future_due",
    "remaining_due",
    "property_due",
    "discount",
    "points",
    "agoda_cash",
    "refund",
    "tax",
    "taxes_and_fees",
}
CARD_OBSERVATION_STATUSES = {
    "observed_card4",
    "confirmed_non_card",
    "confirmed_absent",
    "unresolved",
}
EVIDENCE_ROLES = {
    "identity",
    "service_period",
    "portal_payment_claim",
    "portal_card_observation",
    "lifecycle",
}


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _hash_text(value: object) -> str:
    return hashlib.sha256(_text(value).encode("utf-8")).hexdigest()


def _canonical_hash(value: object) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


HASH_RE = re.compile(r"^[0-9a-f]{64}$")
DECIMAL_RE = re.compile(
    r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$"
)
SAFE_LABEL_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,160}$")
REFERENCE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SENSITIVE_LABEL_RE = re.compile(r"(?:\d[ -]?){12,19}|\d{6,}")


def _safe_scalar_text(value: object, field: str, *, max_len: int = 160) -> str | None:
    """Accept only bounded scalar text in the redacted evidence envelope."""
    if value in (None, ""):
        return None
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"{field}_must_be_scalar")
    if isinstance(value, str) and any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in value
    ):
        raise ValueError(f"{field}_control_character")
    text = _text(value)
    if not text or len(text) > max_len or not SAFE_LABEL_RE.fullmatch(text):
        raise ValueError(f"{field}_value_invalid")
    return text


def _validated_hash(value: object, field: str) -> str | None:
    text = _safe_scalar_text(value, field, max_len=64)
    if text is None:
        return None
    if not HASH_RE.fullmatch(text):
        raise ValueError(f"{field}_format_invalid")
    return text


def _safe_evidence_label(value: object) -> str | None:
    text = _safe_scalar_text(value, "evidence_label")
    if text is not None and (
        SENSITIVE_LABEL_RE.search(text)
        or "@" in text
        or "http://" in text.casefold()
        or "https://" in text.casefold()
    ):
        raise ValueError("evidence_label_value_invalid")
    return text


def _validated_money_representation(
    item: Mapping[str, object],
    *,
    prefix: str,
    decimal_text: str,
) -> dict[str, int]:
    minor_units = item.get("minor_units")
    scale = item.get("scale")
    if (minor_units is None) != (scale is None):
        raise ValueError(f"{prefix}_minor_units_scale_incomplete")
    if minor_units is None:
        return {}
    if type(minor_units) is not int:
        raise ValueError(f"{prefix}_minor_units_invalid")
    if not MINOR_UNITS_MIN <= minor_units <= MINOR_UNITS_MAX:
        raise ValueError(f"{prefix}_minor_units_out_of_range")
    if type(scale) is not int or not 0 <= scale <= 9:
        raise ValueError(f"{prefix}_scale_invalid")
    try:
        scaled = Decimal(decimal_text.replace(",", "")) * (Decimal(10) ** scale)
    except InvalidOperation as exc:
        raise ValueError(f"{prefix}_representation_invalid") from exc
    if scaled != Decimal(minor_units):
        raise ValueError(f"{prefix}_representation_mismatch")
    return {"minor_units": minor_units, "scale": scale}


def _validated_booking_hash(value: object, booking_number: str) -> str:
    expected = _hash_text(booking_number)
    supplied = _validated_hash(value, "booking_id_sha256")
    if supplied is not None and supplied != expected:
        raise ValueError("booking_id_sha256_mismatch")
    return expected


def ensure_schema(db: sqlite3.Connection) -> None:
    """Add the evidence link table to databases created before this contract."""
    # Keep schema installation inside the caller's transaction.  sqlite3's
    # executescript() commits any pending transaction before running, which
    # would make an import failure leave a partial canonical import behind.
    statements = (
        """
        CREATE TABLE IF NOT EXISTS booking_source_evidence (
            id INTEGER PRIMARY KEY,
            booking_id INTEGER NOT NULL REFERENCES bookings(id),
            direct_source_record_id INTEGER NOT NULL REFERENCES direct_source_records(id),
            source_kind TEXT NOT NULL,
            source_key TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            evidence_kind TEXT NOT NULL CHECK(
                evidence_kind IN ('ota_mail', 'ota_mail_live', 'agoda_portal_detail')
            ),
            evidence_role TEXT NOT NULL CHECK(
                evidence_role IN (
                    'identity', 'service_period', 'portal_payment_claim',
                    'portal_card_observation', 'lifecycle'
                )
            ),
            observed_at TEXT,
            evidence_status TEXT NOT NULL DEFAULT 'observed' CHECK(
                evidence_status IN ('observed', 'proposed', 'confirmed', 'rejected', 'superseded')
            ),
            conflict_count INTEGER NOT NULL DEFAULT 0 CHECK(conflict_count >= 0),
            conflict_json TEXT NOT NULL DEFAULT '[]',
            UNIQUE(booking_id, direct_source_record_id, evidence_role),
            FOREIGN KEY(
                direct_source_record_id, source_kind, source_key, source_sha256
            ) REFERENCES direct_source_records(
                id, source_kind, source_key, source_sha256
            )
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS booking_source_evidence_by_booking
        ON booking_source_evidence(booking_id, evidence_kind)
        """,
        """
        CREATE TABLE IF NOT EXISTS direct_source_lineage (
            direct_source_record_id INTEGER NOT NULL REFERENCES direct_source_records(id),
            source_record_id INTEGER NOT NULL REFERENCES source_records(id),
            PRIMARY KEY(direct_source_record_id, source_record_id)
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS direct_source_records_id_tuple
        ON direct_source_records(id, source_kind, source_key, source_sha256)
        """,
    )
    for statement in statements:
        db.execute(statement)
    columns = {
        str(row[1])
        for row in db.execute("PRAGMA table_info(booking_source_evidence)").fetchall()
    }
    required = {
        "booking_id",
        "direct_source_record_id",
        "source_kind",
        "source_key",
        "source_sha256",
        "evidence_kind",
        "evidence_role",
        "evidence_status",
    }
    if not required.issubset(columns):
        raise RuntimeError("booking_source_evidence_schema_incompatible")
    table_sql_row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='booking_source_evidence'"
    ).fetchone()
    normalized_sql = re.sub(r"\s+", "", str(table_sql_row[0]).lower()) if table_sql_row else ""
    expected_fk = (
        "foreignkey(direct_source_record_id,source_kind,source_key,source_sha256)"
        "referencesdirect_source_records(id,source_kind,source_key,source_sha256)"
    )
    if expected_fk not in normalized_sql:
        raise RuntimeError("booking_source_evidence_provenance_fk_incompatible")


def _valid_booking_number(value: object) -> str | None:
    text = _text(value)
    return text if BOOKING_NUMBER_RE.fullmatch(text) else None


def _canonical_date(value: object) -> str | None:
    text = _text(value)
    return text if DATE_RE.fullmatch(text) else None


def _product_type(value: object) -> str:
    text = _text(value).lower()
    aliases = {
        "hotel": "lodging",
        "accommodation": "lodging",
        "숙소": "lodging",
        "항공": "flight",
    }
    normalized = aliases.get(text, text)
    return normalized if normalized in {"lodging", "flight", "rental", "package"} else "unknown"


def _status(value: object) -> str:
    text = _text(value).lower()
    if not text:
        return "unknown"
    if any(token in text for token in ("cancel", "취소")):
        return "cancelled"
    if any(token in text for token in ("complete", "completed", "투숙 완료", "완료")):
        return "completed"
    if any(token in text for token in ("confirm", "confirmation", "confirmed", "확정")):
        return "confirmed"
    if any(token in text for token in ("upcoming", "예정", "pending", "대기")):
        return "upcoming"
    return text[:80]


def _unknown(value: object) -> bool:
    return not _text(value) or _text(value).lower() in {"unknown", "none", "null"}


def _booking_number_from_mail(payload: Mapping[str, object]) -> str | None:
    direct = _valid_booking_number(payload.get("booking_number"))
    if direct:
        return direct
    candidates = payload.get("booking_ref_candidates")
    if isinstance(candidates, list):
        values = {_valid_booking_number(item) for item in candidates}
        values.discard(None)
        if len(values) == 1:
            return next(iter(values))
    return None


def _insert_identifier(
    db: sqlite3.Connection,
    booking_id: int,
    provider: str,
    identifier: object,
    identifier_type: str,
) -> None:
    value = _text(identifier)
    if not value:
        return
    db.execute(
        """
        INSERT OR IGNORE INTO booking_identifiers(
            booking_id, provider, identifier, identifier_type,
            identifier_status, rule_id
        ) VALUES (?, ?, ?, ?, 'proposed', ?)
        """,
        (booking_id, provider, value, identifier_type, REDACTION_VERSION),
    )


def _ensure_booking(
    db: sqlite3.Connection, payload: Mapping[str, object]
) -> tuple[int, list[dict[str, str]]]:
    provider = _text(payload.get("provider")).lower() or "agoda"
    booking_number = _valid_booking_number(payload.get("booking_number"))
    if booking_number is None:
        raise ValueError("agoda_booking_number_missing_or_ambiguous")
    incoming = {
        "product_type": _product_type(payload.get("product_type")),
        "service_start_on": _canonical_date(payload.get("service_start_on")),
        "service_end_on": _canonical_date(payload.get("service_end_on")),
        "status": _status(payload.get("status")),
        "label": _text(payload.get("label")) or None,
    }
    row = db.execute(
        "SELECT id, product_type, service_start_on, service_end_on, status, label "
        "FROM bookings WHERE provider=? AND booking_number=?",
        (provider, booking_number),
    ).fetchone()
    conflicts: list[dict[str, str]] = []
    if row is None:
        cursor = db.execute(
            """
            INSERT INTO bookings(
                provider, booking_number, product_type, label,
                service_start_on, service_end_on, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                booking_number,
                incoming["product_type"],
                incoming["label"],
                incoming["service_start_on"],
                incoming["service_end_on"],
                incoming["status"],
            ),
        )
        booking_id = int(cursor.lastrowid)
    else:
        booking_id = int(row[0])
        updates: dict[str, object] = {}
        for index, field in enumerate(
            ("product_type", "service_start_on", "service_end_on", "status", "label"),
            start=1,
        ):
            old = row[index]
            new = incoming[field]
            if new is None or _unknown(new):
                continue
            if _unknown(old):
                updates[field] = new
            elif str(old) != str(new):
                conflicts.append({
                    "field": field,
                    "existing": str(old),
                    "incoming": str(new),
                })
        if updates:
            assignments = ", ".join(f"{field}=?" for field in updates)
            db.execute(
                f"UPDATE bookings SET {assignments} WHERE id=?",
                (*updates.values(), booking_id),
            )
    for key, identifier_type in (
        (payload.get("order_id"), "order_id"),
        (payload.get("pnr"), "pnr"),
        (payload.get("reference_code"), "reference_code"),
    ):
        _insert_identifier(db, booking_id, provider, key, identifier_type)
    return booking_id, conflicts


def _source_fields(
    db: sqlite3.Connection, source_id: int
) -> tuple[str, str, str]:
    row = db.execute(
        "SELECT source_kind, source_key, source_sha256 "
        "FROM direct_source_records WHERE id=?",
        (source_id,),
    ).fetchone()
    if row is None:
        raise ValueError("direct_source_record_missing")
    return str(row[0]), str(row[1]), str(row[2])


def _promote_source_record(
    db: sqlite3.Connection,
    source_id: int,
) -> int:
    """Expose one redacted direct observation through the canonical source layer.

    This is a logical normalized evidence document, not a claim that the
    original mailbox/portal bytes are present in ``source_records``.  The
    payload bytes and their SHA are nevertheless identical and reproducible.
    """
    row = db.execute(
        "SELECT source_kind, source_key, source_sha256, payload_json "
        "FROM direct_source_records WHERE id=?",
        (source_id,),
    ).fetchone()
    if row is None:
        raise ValueError("direct_source_record_missing")
    source_kind, source_key, source_sha256, payload_json = map(str, row)
    path = f"direct-evidence://{source_kind}/{source_key}"
    payload_bytes = payload_json.encode("utf-8")
    if hashlib.sha256(payload_bytes).hexdigest() != source_sha256:
        raise ValueError("canonical_source_payload_hash_mismatch")
    db.execute(
        """
        INSERT OR IGNORE INTO source_documents(source_kind, path, sha256)
        VALUES (?, ?, ?)
        """,
        (source_kind, path, source_sha256),
    )
    document = db.execute(
        """
        SELECT id FROM source_documents
        WHERE source_kind=? AND path=? AND sha256=?
        """,
        (source_kind, path, source_sha256),
    ).fetchone()
    if document is None:
        raise ValueError("canonical_source_document_missing")
    document_id = int(document[0])
    db.execute(
        """
        INSERT OR IGNORE INTO source_records(
            document_id, row_number, natural_key, raw_payload
        ) VALUES (?, 1, ?, ?)
        """,
        (document_id, source_key, payload_json),
    )
    source_record = db.execute(
        """
        SELECT id, raw_payload FROM source_records
        WHERE document_id=? AND row_number=1
        """,
        (document_id,),
    ).fetchone()
    if source_record is None or str(source_record[1]) != payload_json:
        raise ValueError("canonical_source_record_conflict")
    source_record_id = int(source_record[0])
    db.execute(
        """
        INSERT OR IGNORE INTO direct_source_lineage(
            direct_source_record_id, source_record_id
        ) VALUES (?, ?)
        """,
        (source_id, source_record_id),
    )
    return source_record_id


def _link_evidence(
    db: sqlite3.Connection,
    booking_id: int,
    source_id: int,
    evidence_kind: str,
    evidence_role: str,
    observed_at: object,
    conflicts: list[dict[str, str]],
) -> bool:
    if evidence_kind not in EVIDENCE_KINDS or evidence_role not in EVIDENCE_ROLES:
        raise ValueError("agoda_evidence_kind_invalid")
    source_kind, source_key, source_sha256 = _source_fields(db, source_id)
    conflict_json = _json(conflicts)
    existing = db.execute(
        """
        SELECT observed_at, conflict_count, conflict_json
        FROM booking_source_evidence
        WHERE booking_id=? AND direct_source_record_id=? AND evidence_role=?
        """,
        (booking_id, source_id, evidence_role),
    ).fetchone()
    normalized_observed_at = _text(observed_at) or None
    if existing is not None:
        if tuple(existing) != (
            normalized_observed_at,
            len(conflicts),
            conflict_json,
        ):
            db.execute(
                """
                UPDATE booking_source_evidence
                SET observed_at=?, conflict_count=?, conflict_json=?
                WHERE booking_id=? AND direct_source_record_id=? AND evidence_role=?
                """,
                (
                    normalized_observed_at,
                    len(conflicts),
                    conflict_json,
                    booking_id,
                    source_id,
                    evidence_role,
                ),
            )
        return False
    before = db.total_changes
    db.execute(
        """
        INSERT INTO booking_source_evidence(
            booking_id, direct_source_record_id, source_kind, source_key,
            source_sha256, evidence_kind, evidence_role, observed_at,
            evidence_status, conflict_count, conflict_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'observed', ?, ?)
        ON CONFLICT(booking_id, direct_source_record_id, evidence_role) DO UPDATE SET
            observed_at=excluded.observed_at,
            conflict_count=excluded.conflict_count,
            conflict_json=excluded.conflict_json
        """,
        (
            booking_id,
            source_id,
            source_kind,
            source_key,
            source_sha256,
            evidence_kind,
            evidence_role,
            normalized_observed_at,
            len(conflicts),
            conflict_json,
        ),
    )
    return db.total_changes > before


def _link_roles(
    db: sqlite3.Connection,
    booking_id: int,
    source_id: int,
    evidence_kind: str,
    roles: Iterable[str],
    observed_at: object,
    conflicts: list[dict[str, str]],
) -> int:
    return sum(
        int(_link_evidence(
            db,
            booking_id,
            source_id,
            evidence_kind,
            role,
            observed_at,
            conflicts,
        ))
        for role in roles
    )


def materialize_agoda_mail_bookings(db: sqlite3.Connection) -> dict[str, int]:
    """Materialize unique Agoda mail references without making card links."""
    ensure_schema(db)
    stats = {
        "source_records": 0,
        "materialized": 0,
        "bookings_created": 0,
        "unresolved": 0,
        "evidence_inserted": 0,
        "conflicts": 0,
    }
    rows = db.execute(
        """
        SELECT id, source_kind, payload_json
        FROM direct_source_records
        WHERE source_kind IN ('ota_mail', 'ota_mail_live')
        ORDER BY id
        """
    ).fetchall()
    before_bookings = int(
        db.execute("SELECT COUNT(*) FROM bookings WHERE provider='agoda'").fetchone()[0]
    )
    for row in rows:
        stats["source_records"] += 1
        payload = json.loads(str(row[2]))
        if not isinstance(payload, dict) or _text(payload.get("provider")).lower() != "agoda":
            continue
        booking_number = _booking_number_from_mail(payload)
        if booking_number is None:
            stats["unresolved"] += 1
            continue
        canonical = dict(payload)
        canonical.update(
            provider="agoda",
            booking_number=booking_number,
            product_type=_text(payload.get("product_type")) or "unknown",
            status=payload.get("status") or payload.get("message_status") or "unknown",
        )
        booking_id, conflicts = _ensure_booking(db, canonical)
        _promote_source_record(db, int(row[0]))
        roles = {"identity"}
        if payload.get("service_start_on") or payload.get("service_end_on"):
            roles.add("service_period")
        if payload.get("message_status") or payload.get("status"):
            roles.add("lifecycle")
        inserted = _link_roles(
            db, booking_id, int(row[0]), str(row[1]), roles,
            payload.get("sent_at"), conflicts,
        )
        stats["materialized"] += 1
        stats["evidence_inserted"] += int(inserted)
        stats["conflicts"] += len(conflicts)
    stats["bookings_created"] = int(
        db.execute("SELECT COUNT(*) FROM bookings WHERE provider='agoda'").fetchone()[0]
    ) - before_bookings
    return stats


def _components(record: Mapping[str, object]) -> list[dict[str, object]]:
    raw = record.get("price_components")
    if not isinstance(raw, list):
        raw = []
    result: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        kind = _safe_scalar_text(item.get("kind"), "component_kind")
        if kind not in COMPONENT_KINDS:
            continue
        currency = (_safe_scalar_text(item.get("currency"), "component_currency") or "").upper()
        decimal_text = _safe_scalar_text(
            item.get("decimal_text") or item.get("amount"),
            "component_decimal_text",
            max_len=64,
        )
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("component_currency_invalid")
        if decimal_text is None or not DECIMAL_RE.fullmatch(decimal_text):
            raise ValueError("component_decimal_text_invalid")
        component: dict[str, object] = {
            "kind": kind,
            "currency": currency,
            "decimal_text": decimal_text,
        }
        component.update(_validated_money_representation(
            item, prefix="component", decimal_text=decimal_text
        ))
        result.append(component)
    return result


def _payment_claims(record: Mapping[str, object]) -> list[dict[str, object]]:
    raw = record.get("payment_events")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        event_kind = _safe_scalar_text(item.get("event_kind"), "payment_event_kind")
        currency = (_safe_scalar_text(item.get("currency"), "payment_event_currency") or "").upper()
        decimal_text = _safe_scalar_text(
            item.get("decimal_text"), "payment_event_decimal_text", max_len=64
        )
        if event_kind not in {"charge", "refund", "chargeback"}:
            continue
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("payment_event_currency_invalid")
        if decimal_text is None or not DECIMAL_RE.fullmatch(decimal_text):
            raise ValueError("payment_event_decimal_text_invalid")
        claim: dict[str, object] = {
            "event_kind": event_kind,
            "currency": currency,
            "decimal_text": decimal_text,
        }
        money = _validated_money_representation(
            item, prefix="payment_event", decimal_text=decimal_text
        )
        claim.update(money)
        for key in ("event_on", "card4_sha256", "evidence_label"):
            if item.get(key) not in (None, ""):
                if key == "card4_sha256":
                    claim[key] = _validated_hash(item[key], key)
                elif key == "evidence_label":
                    claim[key] = _safe_evidence_label(item[key])
                else:
                    claim[key] = _safe_scalar_text(item[key], key)
        result.append(claim)
    return result


def _portal_payload(
    record: Mapping[str, object],
    run_id: str,
    staging_sha256: str | None,
    observed_at_utc: str | None,
) -> dict[str, object]:
    booking_id = _safe_scalar_text(record.get("booking_id"), "booking_id")
    booking_number = _valid_booking_number(booking_id)
    if booking_number is None:
        raise ValueError("agoda_portal_booking_id_invalid")
    service_start = _canonical_date(_safe_scalar_text(
        record.get("detail_service_start_on") or record.get("service_start_on"),
        "service_start_on",
    ))
    service_end = _canonical_date(_safe_scalar_text(
        record.get("detail_service_end_on") or record.get("service_end_on"),
        "service_end_on",
    ))
    components = _components(record)
    payment_claims = _payment_claims(record)
    state = "none"
    for candidate in ("paid_today", "future_due", "remaining_due", "property_due"):
        if any(item["kind"] == candidate for item in components):
            state = candidate
            break
    observed_semantic_hash = _validated_hash(
        record.get("semantic_detail_sha256"), "semantic_detail_sha256"
    )
    card_last4 = _safe_scalar_text(record.get("card4"), "card4", max_len=4)
    if card_last4 is not None and not re.fullmatch(r"\d{4}", card_last4):
        raise ValueError("card4_format_invalid")
    card_hash = _validated_hash(record.get("card4_sha256"), "card4_sha256")
    if card_last4 is not None and card_hash is not None and card_hash != _hash_text(card_last4):
        raise ValueError("card4_sha256_mismatch")
    status = _safe_scalar_text(
        record.get("status") or record.get("reservation_status") or "unknown",
        "status",
    ) or "unknown"
    reservation_status = _safe_scalar_text(record.get("reservation_status"), "reservation_status")
    payment_status = _safe_scalar_text(record.get("payment_status"), "payment_status")
    collection_model = _safe_scalar_text(record.get("collection_model"), "collection_model")
    refund_status = _safe_scalar_text(record.get("refund_status"), "refund_status")
    card_type = _safe_scalar_text(record.get("card_type"), "card_type")
    card_role = _safe_scalar_text(record.get("card_role"), "card_role")
    card_observation_status = _safe_scalar_text(
        record.get("card_observation_status"), "card_observation_status"
    )
    if (
        card_observation_status is not None
        and card_observation_status not in CARD_OBSERVATION_STATUSES
    ):
        raise ValueError("card_observation_status_invalid")
    reference_code = _safe_scalar_text(record.get("reference_code"), "reference_code")
    if reference_code is not None and not REFERENCE_CODE_RE.fullmatch(reference_code):
        raise ValueError("reference_code_value_invalid")
    snapshot_id = record.get("snapshot_id")
    if snapshot_id is not None and type(snapshot_id) is not int:
        snapshot_id = _safe_scalar_text(snapshot_id, "snapshot_id")
    supplied_run_id = _safe_scalar_text(run_id, "capture_run_id")
    if supplied_run_id is None:
        raise ValueError("capture_run_id_missing")
    supplied_staging_hash = _validated_hash(staging_sha256, "staging_sha256")
    booking_hash = _validated_booking_hash(
        record.get("booking_id_sha256"), booking_number
    )
    semantic_payload = {
        "booking_number": booking_number,
        "service_start_on": service_start,
        "service_end_on": service_end,
        "status": status,
        "reservation_status": reservation_status,
        "payment_status": payment_status,
        "collection_model": collection_model,
        "refund_status": refund_status,
        "card_type": card_type,
        "card4_sha256": card_hash,
        "card4_present": card_last4 is not None,
        "card_role": card_role,
        "card_observation_status": card_observation_status,
        "portal_payment_state": state,
        "price_components": components,
        "portal_event_claims": payment_claims,
        "reference_code": reference_code,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    payload: dict[str, object] = {
        "provider": "agoda",
        "booking_number": booking_number,
        "product_type": "lodging",
        "service_start_on": service_start,
        "service_end_on": service_end,
        "status": status,
        "reservation_status": reservation_status,
        "payment_status": payment_status,
        "collection_model": collection_model,
        "refund_status": refund_status,
        "card_type": card_type,
        "card_last4": card_last4,
        "card_last4_sha256": card_hash,
        "card_role": card_role,
        "card_observation_status": card_observation_status,
        "portal_payment_state": state,
        "price_components": components,
        "portal_event_claims": payment_claims,
        "reference_code": reference_code,
        "snapshot_id": snapshot_id,
        "booking_id_sha256": booking_hash,
        "semantic_detail_sha256": semantic_hash,
        "observed_semantic_detail_sha256": observed_semantic_hash,
        "capture_run_id": supplied_run_id,
        "observed_at": _safe_scalar_text(
            record.get("observed_at_utc")
            or record.get("observed_at")
            or record.get("captured_at_utc")
            or observed_at_utc,
            "observed_at",
        ),
        "staging_sha256": supplied_staging_hash,
        "redaction_version": REDACTION_VERSION,
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


def import_agoda_portal_details(
    db: sqlite3.Connection,
    records: Iterable[Mapping[str, object]],
    *,
    run_id: str,
    staging_sha256: str | None = None,
    observed_at_utc: str | None = None,
) -> dict[str, int]:
    """Persist normalized portal detail evidence and attach it to bookings."""
    ensure_schema(db)
    stats = {
        "records": 0,
        "source_inserted": 0,
        "materialized": 0,
        "evidence_inserted": 0,
        "conflicts": 0,
    }
    for record in records:
        stats["records"] += 1
        payload = _portal_payload(record, run_id, staging_sha256, observed_at_utc)
        source_key = ":".join(
            (
                str(payload["capture_run_id"]),
                str(payload["booking_id_sha256"]),
                str(payload["semantic_detail_sha256"]),
            )
        )
        source_id, created = _insert_source(
            db, "agoda_portal_detail", source_key, payload, REDACTION_VERSION
        )
        stats["source_inserted"] += int(created)
        booking_id, conflicts = _ensure_booking(db, payload)
        _promote_source_record(db, source_id)
        roles = {"identity"}
        if payload.get("service_start_on") or payload.get("service_end_on"):
            roles.add("service_period")
        if payload.get("price_components") or payload.get("portal_event_claims"):
            roles.add("portal_payment_claim")
        if (
            payload.get("card_last4")
            or payload.get("card_role")
            or payload.get("card_observation_status")
        ):
            roles.add("portal_card_observation")
        if payload.get("status") or payload.get("refund_status"):
            roles.add("lifecycle")
        inserted = _link_roles(
            db, booking_id, source_id, "agoda_portal_detail", roles,
            payload.get("observed_at"), conflicts,
        )
        stats["materialized"] += 1
        stats["evidence_inserted"] += int(inserted)
        stats["conflicts"] += len(conflicts)
    return stats


def _open_staging_snapshot(path: Path) -> sqlite3.Connection:
    """Freeze one consistent SQLite/WAL view before reading any staging rows."""
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    source = sqlite3.connect(uri, uri=True)
    snapshot = sqlite3.connect(":memory:")
    try:
        source.backup(snapshot)
    except Exception:
        snapshot.close()
        raise
    finally:
        source.close()
    return snapshot


def _staging_records(
    connection: sqlite3.Connection, requested_run_id: str | None
) -> tuple[str, list[dict[str, object]]]:
    run_rows = connection.execute(
        "SELECT DISTINCT run_id FROM booking_detail_snapshots ORDER BY run_id"
    ).fetchall()
    run_ids = [str(row[0]) for row in run_rows]
    if requested_run_id:
        if requested_run_id not in run_ids:
            raise ValueError("agoda_staging_run_id_missing")
        run_id = requested_run_id
    elif len(run_ids) == 1:
        run_id = run_ids[0]
    elif not run_ids:
        return "", []
    else:
        raise ValueError("agoda_staging_run_id_required")

    snapshots = connection.execute(
        """
        SELECT snapshot_id, run_id, booking_id, reference_code,
               booking_id_sha256, detail_service_start_on,
               detail_service_end_on, reservation_status, payment_status,
               collection_model, refund_status, card_type, card4,
               card4_sha256, card_role, semantic_detail_sha256,
               captured_at_utc
        FROM booking_detail_snapshots
        WHERE run_id=? ORDER BY snapshot_id
        """,
        (run_id,),
    ).fetchall()
    records: list[dict[str, object]] = []
    for snapshot in snapshots:
        snapshot_id = int(snapshot[0])
        components = [
            {
                "kind": str(row[0]),
                "currency": str(row[1]),
                "decimal_text": str(row[2]),
                "minor_units": int(row[3]),
                "scale": int(row[4]),
            }
            for row in connection.execute(
                """
                SELECT component_kind, currency, amount_decimal_text,
                       amount_minor_units, currency_scale
                FROM price_components WHERE snapshot_id=? ORDER BY ordinal
                """,
                (snapshot_id,),
            ).fetchall()
        ]
        claims = [
            {
                "event_kind": str(row[0]),
                "event_on": row[1],
                "currency": str(row[2]),
                "decimal_text": str(row[3]),
                "minor_units": int(row[4]),
                "scale": int(row[5]),
                "card4_sha256": row[6],
                "evidence_label": str(row[7]),
            }
            for row in connection.execute(
                """
                SELECT event_kind, event_on, currency, amount_decimal_text,
                       amount_minor_units, currency_scale, card4_sha256,
                       evidence_label
                FROM payment_events WHERE snapshot_id=? ORDER BY event_id
                """,
                (snapshot_id,),
            ).fetchall()
        ]
        records.append(
            {
                "booking_id": snapshot[2],
                "reference_code": snapshot[3],
                "booking_id_sha256": snapshot[4],
                "detail_service_start_on": snapshot[5],
                "detail_service_end_on": snapshot[6],
                "reservation_status": snapshot[7],
                "status": snapshot[7],
                "payment_status": snapshot[8],
                "collection_model": snapshot[9],
                "refund_status": snapshot[10],
                "card_type": snapshot[11],
                "card4": snapshot[12],
                "card4_sha256": snapshot[13],
                "card_role": snapshot[14],
                "semantic_detail_sha256": snapshot[15],
                "captured_at_utc": snapshot[16],
                "snapshot_id": snapshot_id,
                "price_components": components,
                "payment_events": claims,
            }
        )
    return run_id, records


def import_agoda_portal_staging(
    db: sqlite3.Connection,
    staging_path: Path,
    *,
    run_id: str | None = None,
    staging_sha256: str | None = None,
) -> dict[str, int]:
    """Read a capture staging DB and promote only its structured detail rows."""
    path = Path(staging_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    snapshot = _open_staging_snapshot(path)
    try:
        actual_digest = hashlib.sha256(snapshot.serialize()).hexdigest()
        if staging_sha256 is not None:
            supplied_digest = _validated_hash(staging_sha256, "staging_sha256")
            if supplied_digest != actual_digest:
                raise ValueError("agoda_staging_sha256_mismatch")
            digest = supplied_digest
        else:
            digest = actual_digest
        effective_run_id, records = _staging_records(snapshot, run_id)
    finally:
        snapshot.close()
    if not effective_run_id:
        return {"records": 0, "source_inserted": 0, "materialized": 0,
                "evidence_inserted": 0, "conflicts": 0}
    return import_agoda_portal_details(
        db,
        records,
        run_id=effective_run_id,
        staging_sha256=digest,
    )


__all__ = [
    "REDACTION_VERSION",
    "ensure_schema",
    "materialize_agoda_mail_bookings",
    "import_agoda_portal_details",
    "import_agoda_portal_staging",
]
