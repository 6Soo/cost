#!/usr/bin/env python3
"""도메인 분리형 비용 원장 초기화·legacy v14 이관·불변식 검증.

기존 산출 경로를 대체하지 않는다. 승인된 classified 정본을 원천 스냅샷으로 가져와
결제 사실, 예약 연결, 배분, 분류판정을 분리하고 동일 건수·합계를 검증한다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .source_adapters import stable_card_event_identity
from .direct_sources import compare_with_legacy, import_all as import_direct_sources
from .reconciliation import (
    PeriodCloseBlocked,
    close_period,
    coverage_report,
    create_match_group,
    record_match_decision,
    verification_dimensions,
)
from .review_verifier import verify_review_claims
from .period_recognition import (
    Q2_CLOSE_ON,
    is_prepaid_future_trip,
    structured_service_start_on,
)


HERE = Path(__file__).resolve().parent
LEDGER_DIR = HERE.parent
def default_db_path() -> Path:
    configured = os.environ.get("COST_LEDGER_DB")
    if configured:
        return Path(configured).expanduser()
    local_root = os.environ.get("LOCALAPPDATA")
    if local_root:
        return Path(local_root) / "SoopgilTravel" / "cost" / "ledger_v2.db"
    return Path.home() / ".local" / "share" / "soopgil-cost" / "ledger_v2.db"


DEFAULT_DB = default_db_path()
DEFAULT_CSV = LEDGER_DIR / "data" / "classified_v15.csv"
DEFAULT_TRIPS = LEDGER_DIR / "data" / "trips.json"
DEFAULT_BOOKINGS = LEDGER_DIR / "data" / "booking_info.json"
SCHEMA = HERE / "schema.sql"
REVIEW_RULE_VERSION = "p0-v1"
UNCERTAIN_RATIONALE_RE = re.compile(r"추정|유사|불명|확인\s*(?:필요|要)")
STRONG_EVIDENCE_RULES = (
    ("gmail_verified", re.compile(r"Gmail확정|메일확정")),
    ("user_confirmed", re.compile(r"사용자|대표님?\s*확정|확정:")),
    ("manual_unique", re.compile(r"수기\s*(?:단독|국민|하나)?.{0,12}(?:매칭|일치|정답)")),
    ("local_consistency", re.compile(r"현지정합\s*여행기간내")),
    ("booking_verified", re.compile(r"예약(?:번호|코드)?[A-Z0-9]{5,19}.{0,30}(?:확정|검증기간)")),
)

# These merchant strings identify an OTA or payment-gateway charge, not the
# underlying travel service.  They therefore cannot keep a legacy travel
# classification at high confidence unless the card, direct OTA receipt,
# journey and service-period gates are all present.  Keep this deliberately
# narrow: a direct airline or hotel merchant is not silently swept into the
# OTA rule, and Agoda is outside the current review scope.
DIRECT_OTA_REQUIRED_MERCHANT_TOKENS = (
    "TRIP.COM",
    "트립닷컴",
    "MYTRIP",
    "GOTOGATE",
    "SKYTICKET",
    "스카이티켓",
    "KLOOK",
    "클룩",
    "인터넷상거래",
    "KCP",
    "NICE",
    "이니시스",
    "INICIS",
    "토스",
    "TOSS",
)
DIRECT_OTA_GATED_DIMENSIONS = {
    "allocation_target",
    "expense_type",
    "cost_nature",
    "period_recognition",
}


def _legacy_ota_or_pg_requires_direct_evidence(row: sqlite3.Row) -> bool:
    """Return true only for a legacy OTA/PG travel conclusion.

    A merchant name can corroborate a provider after a direct receipt was
    matched.  It must never create that receipt or promote a PG charge into
    OTA proof on its own.
    """
    return (
        str(row["rule_id"] or "") == "legacy_v14_import"
        and str(row["dimension"] or "") in DIRECT_OTA_GATED_DIMENSIONS
        and any(
            token in str(row["merchant"] or "").upper()
            for token in DIRECT_OTA_REQUIRED_MERCHANT_TOKENS
        )
    )

REVIEW_DETAIL_FIELDS = [
    "entity_type",
    "entity_key",
    "payment_external_key",
    "occurred_on",
    "merchant",
    "amount_krw",
    "review_amount_krw",
    "transaction_type",
    "approval_number",
    "booking_numbers",
    "booking_providers",
    "allocation_targets",
    "decision_values",
    "decision_rule_ids",
    "decision_confidence_labels",
    "decision_min_confidence",
    "decision_rationales",
    "relation_type",
    "relation_reference",
    "relation_match_method",
    "relation_confidence",
]

REVIEW_QUEUE_METRICS = {
    "unassigned": "unassigned_payments",
    "engine_isolated": "engine_isolated_payments",
    "zero_amount": "zero_amount_payments",
    "unresolved_transaction_relations": "unresolved_transaction_relations",
    "unknown_booking_providers": "unknown_booking_providers",
    "bookings_linked_to_multiple_targets": "bookings_linked_to_multiple_targets",
    "high_confidence_uncertain_rationale": "high_confidence_with_uncertain_rationale",
    "low_confidence": "low_confidence_payments",
}

BOOKING_RE = re.compile(r"예약\s*([0-9]{6,19}|[A-Z0-9]{5,7})(?![0-9])")
TRIP_CODE_RE = re.compile(r"^(?:(\d{2})(\d{2})|(\d{1,2})월)_(.+)$")

ISSUER_BY_SOURCE = {
    "KBD": "국민",
    "KBO": "국민",
    "HAN": "하나",
    "CORP": "기업",
}

CONFIDENCE = {
    "상": 1.0,
    "중": 0.7,
    "하": 0.3,
}

NONPOSTING_SOURCE_DISPOSITIONS = {
    "superseded_duplicate_projection",
    "manual_claimed_card_no_raw",
    "rejected_legacy_projection",
}


@dataclass(frozen=True)
class ImportStats:
    source_rows: int
    transactions: int
    bookings: int
    allocations: int
    decisions: int
    amount_krw: int
    repeated_snapshot: bool = False


@dataclass(frozen=True)
class AllocationItem:
    target_id: int
    amount_krw: int
    booking_id: int | None = None


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    return db


def initialize(db: sqlite3.Connection) -> None:
    existing_tables = {
        str(row["name"])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "payment_transactions" in existing_tables:
        payment_columns = {
            str(row["name"])
            for row in db.execute("PRAGMA table_info(payment_transactions)").fetchall()
        }
        required_columns = {"source_event_id", "identity_fingerprint"}
        if not required_columns.issubset(payment_columns):
            raise RuntimeError(
                "기존 v2 DB 스키마는 현재 코드와 호환되지 않습니다. "
                "DB를 직접 수정하지 말고 `python -m ledger.domain.ledger_db "
                "rebuild`로 불변 원천에서 재생성하세요."
            )
    if "direct_normalized_payments" in existing_tables:
        direct_columns = {
            str(row["name"])
            for row in db.execute(
                "PRAGMA table_info(direct_normalized_payments)"
            ).fetchall()
        }
        if "event_role" not in direct_columns:
            raise RuntimeError(
                "기존 직접 적재 DB는 승인·취소 분리 스키마와 호환되지 않습니다. "
                "`python -m ledger.domain.ledger_db rebuild`로 불변 원천에서 재생성하세요."
            )
    if "match_signal_results" in existing_tables:
        signal_columns = {
            str(row["name"])
            for row in db.execute(
                "PRAGMA table_info(match_signal_results)"
            ).fetchall()
        }
        if "source_event_id" not in signal_columns:
            db.execute(
                "ALTER TABLE match_signal_results ADD COLUMN source_event_id TEXT"
            )
        if "evidence_json" not in signal_columns:
            db.execute(
                "ALTER TABLE match_signal_results "
                "ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '[]'"
            )
    if "bookings" in existing_tables:
        booking_columns = {
            str(row["name"])
            for row in db.execute("PRAGMA table_info(bookings)").fetchall()
        }
        if "service_end_on" not in booking_columns:
            db.execute("ALTER TABLE bookings ADD COLUMN service_end_on TEXT")
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    db.commit()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_int(value: object) -> int:
    try:
        return int(round(float(str(value or "0").replace(",", ""))))
    except (TypeError, ValueError):
        return 0


def is_true(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def product_type(account: str) -> str:
    text = account or ""
    if "숙박" in text:
        return "lodging"
    if "항공" in text:
        return "flight"
    if "렌트" in text:
        return "rental"
    return "unknown"


def provider_for(number: str, note: str, booking_info: dict[str, dict]) -> str:
    label = str(booking_info.get(number, {}).get("label", ""))
    text = f"{label} {note}".upper()
    if number.startswith("1400") and len(number) == 16:
        return "trip.com"
    if "AGODA" in text or "아고다" in text:
        return "agoda"
    if "BOOKING" in text or "부킹" in text:
        return "booking.com"
    if "TRIP.COM" in text or "트립닷컴" in text:
        return "trip.com"
    return "unknown"


def period_dates(period: str, year: int = 2026) -> tuple[str | None, str | None]:
    match = re.search(r"_(\d{2})(\d{2})_(\d{2})(\d{2})$", period or "")
    if not match:
        return None, None
    sm, sd, em, ed = map(int, match.groups())
    try:
        start = date(year, sm, sd)
        end_year = year + (1 if (em, ed) < (sm, sd) else 0)
        end = date(end_year, em, ed)
    except ValueError:
        return None, None
    return start.isoformat(), end.isoformat()


def booking_numbers(note: str) -> list[str]:
    return list(dict.fromkeys(BOOKING_RE.findall(note or "")))


def verified_booking_numbers(
    db: sqlite3.Connection,
    booking_info: dict[str, dict],
) -> set[str]:
    """Return references supported by imported OTA mail evidence only.

    Booking-info JSON is an enrichment/proposal source, not settlement proof.
    A number copied only into a legacy note or present only in booking_info is
    a lead: it must not create a booking link or supply a service period.
    Direct OTA rows are privacy-sanitized and are the only source permitted to
    establish that the underlying Gmail evidence exists.
    """
    verified: set[str] = set()
    rows = db.execute(
        """
        SELECT payload_json
        FROM direct_source_records
        WHERE source_kind IN ('ota_mail', 'ota_authenticated_portal')
        """
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for value in (payload.get("booking_number"), payload.get("order_id")):
            number = str(value or "").strip()
            if number:
                verified.add(number)
        values = payload.get("booking_numbers", [])
        if not isinstance(values, list):
            values = [values]
        verified.update(str(value).strip() for value in values if str(value).strip())
    return verified


def target_type(code: str, known_trips: set[str]) -> str:
    if code in known_trips or TRIP_CODE_RE.match(code or ""):
        return "trip"
    if code in {"기타비용", "2분기_기타비용"}:
        return "overhead"
    if (code or "").startswith("대장_"):
        return "leader"
    if code == "여행_미배정":
        return "unassigned"
    if code in {"취소환불", "전기예약_환불"}:
        return "clearing"
    return "other"


def method_values(row: dict[str, str]) -> tuple[str, str | None, str | None, str]:
    source = row.get("src", "")
    issuer = ISSUER_BY_SOURCE.get(source)
    last4 = re.sub(r"\D", "", row.get("card4", ""))[-4:] or None
    holder = (row.get("user") or "").strip() or None
    if issuer:
        key = ":".join([issuer, last4 or "unknown", holder or "unknown"])
        return key, issuer, last4, "company"
    key = f"manual:{last4 or 'unknown'}:{holder or 'unknown'}"
    return key, None, last4, "unknown"


def upsert_payment_method(db: sqlite3.Connection, row: dict[str, str]) -> int:
    key, issuer, last4, ownership = method_values(row)
    db.execute(
        """
        INSERT INTO payment_methods(method_key, issuer, last4, holder_name, ownership_type)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(method_key) DO UPDATE SET
            issuer=excluded.issuer,
            last4=excluded.last4,
            holder_name=excluded.holder_name
        """,
        (key, issuer, last4, (row.get("user") or "").strip() or None, ownership),
    )
    return int(db.execute("SELECT id FROM payment_methods WHERE method_key=?", (key,)).fetchone()[0])


def card_event_fingerprint(row: dict[str, str]) -> str:
    """Stable, non-unique review fingerprint; it never authorizes deduplication."""
    payload = {
        "source": row.get("src") or "UNKNOWN",
        "card4": re.sub(r"\D", "", row.get("card4") or ""),
        "approval": re.sub(r"\D", "", row.get("appr") or ""),
        "occurred_on": row.get("use_date") or "",
        "posted_on": row.get("post_date") or "",
        "merchant": re.sub(r"\s+", " ", row.get("merchant") or "").strip().upper(),
        "currency": (row.get("currency") or "").upper(),
        "foreign_amount": row.get("foreign") or "",
        "amount_krw": parse_int(row.get("krw")),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upsert_payment(
    db: sqlite3.Connection,
    row: dict[str, str],
    method_id: int,
    source_record_id: int,
) -> int:
    amount = parse_int(row.get("krw"))
    if amount < 0:
        transaction_type = "refund"
    elif is_true(row.get("cancel")):
        transaction_type = "cancellation"
    elif amount == 0:
        transaction_type = "adjustment"
    else:
        transaction_type = "purchase"
    values = (
        row["uid"],
        row.get("source_event_id") or row["uid"],
        card_event_fingerprint(row),
        method_id,
        row.get("src") or "UNKNOWN",
        row.get("use_date") or None,
        row.get("post_date") or None,
        row.get("merchant") or "",
        row.get("biz") or None,
        row.get("country") or None,
        row.get("currency") or None,
        row.get("foreign") or None,
        amount,
        row.get("appr") or None,
        transaction_type,
    )
    existing = db.execute(
        """
        SELECT source_event_id, identity_fingerprint, payment_method_id,
               source_system, occurred_on, posted_on, merchant,
               business_category, country, currency, foreign_amount, amount_krw,
               approval_number, transaction_type, record_version
        FROM payment_transactions WHERE external_key=?
        """,
        (row["uid"],),
    ).fetchone()
    source_event_id = row.get("source_event_id") or row["uid"]
    source_owner = db.execute(
        """
        SELECT external_key FROM payment_transactions
        WHERE source_event_id=? AND external_key<>?
        """,
        (source_event_id, row["uid"]),
    ).fetchone()
    if source_owner is not None:
        raise ValueError(
            "source event lineage is already projected by "
            f"{source_owner['external_key']!r}: {source_event_id!r}"
        )
    if (
        existing is not None
        # A legacy snapshot without lineage used its display UID as the
        # source-event key.  Permit that one-way enrichment, but never let a
        # regenerated positional UID (for example TRIP-0042) overwrite a
        # different raw-card or manual-ledger event.
        and existing["source_event_id"] not in {row["uid"], source_event_id}
    ):
        raise ValueError(
            "source event lineage conflict for "
            f"{row['uid']}: existing={existing['source_event_id']!r}, "
            f"incoming={source_event_id!r}"
        )
    if (
        existing is not None
        and amount < 0
        and existing["transaction_type"] in {"cancellation", "refund"}
    ):
        # Preserve the previously resolved semantic type while comparing raw
        # card facts. The relation pass below will append a new version only
        # when the original/refund amounts change that conclusion.
        values = values[:-1] + (existing["transaction_type"],)
    comparable = values[1:]
    changed = True
    if existing is None:
        payment_id = int(db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint,
                payment_method_id, source_system, occurred_on, posted_on,
                merchant, business_category, country, currency, foreign_amount,
                amount_krw, approval_number, transaction_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        ).lastrowid)
        record_version = 1
    elif tuple(existing[:-1]) != comparable:
        payment_id = int(
            db.execute(
                "SELECT id FROM payment_transactions WHERE external_key=?",
                (row["uid"],),
            ).fetchone()[0]
        )
        record_version = int(existing["record_version"]) + 1
        db.execute(
            """
            UPDATE payment_transactions SET
                source_event_id=?, identity_fingerprint=?,
                payment_method_id=?, source_system=?, occurred_on=?, posted_on=?,
                merchant=?, business_category=?, country=?, currency=?, foreign_amount=?,
                amount_krw=?, approval_number=?, transaction_type=?,
                record_version=record_version+1, updated_at=CURRENT_TIMESTAMP
            WHERE external_key=?
            """,
            comparable + (row["uid"],),
        )
    else:
        payment_id = int(
            db.execute(
                "SELECT id FROM payment_transactions WHERE external_key=?",
                (row["uid"],),
            ).fetchone()[0]
        )
        changed = False

    if changed:
        db.execute(
            """
            INSERT INTO payment_transaction_versions(
                transaction_id, record_version, source_record_id,
                source_event_id, identity_fingerprint, payment_method_id,
                source_system, occurred_on, posted_on, merchant, business_category,
                country, currency, foreign_amount, amount_krw, approval_number,
                transaction_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (payment_id, record_version, source_record_id) + comparable,
        )
    identity = stable_card_event_identity(row)
    db.execute(
        """
        INSERT INTO card_event_identities(
            transaction_id, card_event_id, generator_version,
            identity_status, structural_payload_json
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(transaction_id) DO UPDATE SET
            card_event_id=excluded.card_event_id,
            generator_version=excluded.generator_version,
            identity_status=excluded.identity_status,
            structural_payload_json=excluded.structural_payload_json
        """,
        (
            payment_id,
            identity.card_event_id,
            identity.generator_version,
            identity.identity_status,
            json.dumps(
                identity.structural_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )
    collision_count = int(
        db.execute(
            "SELECT COUNT(*) FROM card_event_identities WHERE card_event_id=?",
            (identity.card_event_id,),
        ).fetchone()[0]
    )
    if collision_count > 1:
        db.execute(
            """
            UPDATE card_event_identities
            SET identity_status='collision'
            WHERE card_event_id=?
            """,
            (identity.card_event_id,),
        )
    return payment_id


def ensure_trip(
    db: sqlite3.Connection,
    code: str,
    region: str,
    starts_on: str | None,
    ends_on: str | None,
) -> int:
    db.execute(
        """
        INSERT INTO trips(code, name, region, starts_on, ends_on)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            name=excluded.name,
            region=COALESCE(excluded.region, trips.region),
            starts_on=COALESCE(excluded.starts_on, trips.starts_on),
            ends_on=COALESCE(excluded.ends_on, trips.ends_on)
        """,
        (code, code, region or None, starts_on, ends_on),
    )
    return int(db.execute("SELECT id FROM trips WHERE code=?", (code,)).fetchone()[0])


def load_trips(db: sqlite3.Connection, path: Path) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for item in raw:
        code = item["tab"]
        start = date(2026, int(item["mm"]), int(item["dd"]))
        end = start + timedelta(days=max(1, int(item.get("window", 7))) - 1)
        ensure_trip(db, code, item.get("region", ""), start.isoformat(), end.isoformat())
        codes.add(code)
    return codes


def infer_trip(db: sqlite3.Connection, code: str) -> int:
    match = TRIP_CODE_RE.match(code or "")
    if not match:
        raise ValueError(f"여행 코드 형식을 해석할 수 없습니다: {code}")
    mm = int(match.group(1) or match.group(3))
    dd = int(match.group(2) or 1)
    region = match.group(4)
    start = date(2026, mm, dd)
    return ensure_trip(db, code, region, start.isoformat(), None)


def ensure_target(db: sqlite3.Connection, code: str, kind: str) -> int:
    trip_id = None
    if kind == "trip":
        row = db.execute("SELECT id FROM trips WHERE code=?", (code,)).fetchone()
        trip_id = int(row[0]) if row else infer_trip(db, code)
    db.execute(
        """
        INSERT INTO allocation_targets(target_type, code, name, trip_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            target_type=excluded.target_type,
            name=excluded.name,
            trip_id=COALESCE(excluded.trip_id, allocation_targets.trip_id)
        """,
        (kind, code, code, trip_id),
    )
    return int(db.execute("SELECT id FROM allocation_targets WHERE code=?", (code,)).fetchone()[0])


def ensure_booking(
    db: sqlite3.Connection,
    number: str,
    row: dict[str, str],
    booking_info: dict[str, dict],
) -> int:
    info = booking_info.get(number, {})
    provider = provider_for(number, row.get("note", ""), booking_info)
    # A human-written note or a display period is not enough to defer a card
    # payment.  Only a dedicated ISO date on the booking record is accounting
    # evidence for service-period recognition.
    start = structured_service_start_on(info)
    _, end = period_dates(str(info.get("period", "")))
    db.execute(
        """
        INSERT INTO bookings(
            provider, booking_number, product_type, label, service_start_on, service_end_on
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, booking_number) DO UPDATE SET
            product_type=CASE
                WHEN bookings.product_type='unknown' THEN excluded.product_type
                ELSE bookings.product_type
            END,
            label=COALESCE(excluded.label, bookings.label),
            service_start_on=COALESCE(excluded.service_start_on, bookings.service_start_on),
            service_end_on=COALESCE(excluded.service_end_on, bookings.service_end_on)
        """,
        (
            provider,
            number,
            product_type(row.get("account", "")),
            info.get("label"),
            start,
            end,
        ),
    )
    return int(
        db.execute(
            "SELECT id FROM bookings WHERE provider=? AND booking_number=?",
            (provider, number),
        ).fetchone()[0]
    )


def replace_decision(
    db: sqlite3.Connection,
    target_type_name: str,
    target_id: int,
    dimension: str,
    value: str,
    confidence: float,
    confidence_label: str,
    rationale: str,
    evidence_id: int | None,
    *,
    decision_status: str = "legacy",
    rule_id: str = "legacy_v14_import",
) -> int:
    previous = db.execute(
        """
        SELECT id, value, confidence, confidence_label, rationale,
               decision_status, rule_id
        FROM classification_decisions
        WHERE target_type=? AND target_id=? AND dimension=?
          AND superseded_by_id IS NULL AND decision_status <> 'superseded'
        """,
        (target_type_name, target_id, dimension),
    ).fetchone()
    if previous and (
        previous["value"],
        previous["confidence"],
        previous["confidence_label"],
        previous["rationale"],
        previous["decision_status"],
        previous["rule_id"],
    ) == (
        value,
        confidence,
        confidence_label,
        rationale,
        decision_status,
        rule_id,
    ):
        decision_id = int(previous["id"])
    else:
        if previous:
            db.execute(
                "UPDATE classification_decisions SET decision_status='superseded' WHERE id=?",
                (previous["id"],),
            )
        cursor = db.execute(
            """
            INSERT INTO classification_decisions(
                target_type, target_id, dimension, value, confidence, confidence_label,
                decision_status, rule_id, rationale
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_type_name,
                target_id,
                dimension,
                value or "미정",
                confidence,
                confidence_label or None,
                decision_status,
                rule_id,
                rationale or None,
            ),
        )
        decision_id = int(cursor.lastrowid)
        if previous:
            db.execute(
                "UPDATE classification_decisions SET superseded_by_id=? WHERE id=?",
                (decision_id, previous["id"]),
            )
    if evidence_id is not None:
        db.execute(
            """
            INSERT OR IGNORE INTO decision_evidence(decision_id, evidence_id, evidence_role)
            VALUES (?, ?, 'supporting')
            """,
            (decision_id, evidence_id),
        )
    return decision_id


SENSITIVE_KEYS = {
    "pin", "password", "birth", "birthdate", "dob", "phone", "email",
    "passport", "생년월일", "전화번호", "연락처", "이메일", "여권",
}


def redact_sensitive_payload(value: object) -> object:
    """Remove authentication and high-risk personal data before persistence."""
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^0-9a-z가-힣]", "", str(key).lower())
            if any(token in normalized for token in SENSITIVE_KEYS):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_sensitive_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_payload(item) for item in value]
    if isinstance(value, str):
        text = re.sub(
            r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
            "[REDACTED_EMAIL]",
            value,
        )
        text = re.sub(
            r"(?i)(PIN\s*(?:번호)?\s*[:：]?\s*)\d{3,12}",
            r"\1[REDACTED]",
            text,
        )
        text = re.sub(
            r"(?<!\d)(?:\+?82[-.\s]?)?0?1[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)",
            "[REDACTED_PHONE]",
            text,
        )
        return text
    return value


def canonical_change_event(event: dict[str, object]) -> dict[str, object]:
    required = {"event_type", "target_type", "target_key", "payload"}
    missing = sorted(required - set(event))
    if missing:
        raise ValueError(f"변경 이벤트 필수값 누락: {', '.join(missing)}")
    clean = redact_sensitive_payload({
        "event_type": str(event["event_type"]),
        "target_type": str(event["target_type"]),
        "target_key": str(event["target_key"]),
        "payload": event["payload"],
        "actor": str(event.get("actor") or "User"),
    })
    semantic = json.dumps(
        clean,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    clean["event_id"] = hashlib.sha256(semantic.encode("utf-8")).hexdigest()
    clean["recorded_at"] = str(
        event.get("recorded_at") or datetime.now(timezone.utc).isoformat()
    )
    return clean


def append_change_event(path: Path, event: dict[str, object]) -> dict[str, object]:
    """Append a sanitized semantic event once; the JSONL file is the source of truth."""
    normalized = canonical_change_event(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                existing = json.loads(line)
                if existing.get("event_id") == normalized["event_id"]:
                    return existing
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return normalized


def _apply_classification_change(
    db: sqlite3.Connection,
    target_type_name: str,
    target_key: str,
    payload: dict[str, object],
) -> None:
    if target_type_name != "payment":
        raise ValueError("현재 변경 원장은 payment 분류판정만 지원합니다.")
    row = db.execute(
        "SELECT id FROM payment_transactions WHERE external_key=?",
        (target_key,),
    ).fetchone()
    if row is None:
        raise ValueError(f"결제 이벤트를 찾을 수 없습니다: {target_key}")
    replace_decision(
        db,
        "payment",
        int(row["id"]),
        str(payload["dimension"]),
        str(payload["value"]),
        float(payload.get("confidence", 1.0)),
        str(payload.get("confidence_label") or "상"),
        str(payload.get("rationale") or ""),
        None,
        decision_status=str(payload.get("status") or "confirmed"),
        rule_id=str(payload.get("rule_id") or "manual_change_log"),
    )


def _apply_payment_booking_change(
    db: sqlite3.Connection,
    target_key: str,
    payload: dict[str, object],
) -> None:
    payment = db.execute(
        "SELECT id FROM payment_transactions WHERE external_key=?",
        (target_key,),
    ).fetchone()
    if payment is None:
        raise ValueError(f"결제 이벤트를 찾을 수 없습니다: {target_key}")
    provider = str(payload.get("provider") or "unknown")
    booking_number = str(payload["booking_number"])
    product = str(payload.get("product_type") or "unknown")
    db.execute(
        """
        INSERT INTO bookings(provider, booking_number, product_type, label)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(provider, booking_number) DO UPDATE SET
            product_type=CASE
                WHEN bookings.product_type='unknown' THEN excluded.product_type
                ELSE bookings.product_type
            END,
            label=COALESCE(excluded.label, bookings.label)
        """,
        (provider, booking_number, product, payload.get("label")),
    )
    booking_id = int(
        db.execute(
            "SELECT id FROM bookings WHERE provider=? AND booking_number=?",
            (provider, booking_number),
        ).fetchone()[0]
    )
    relation_type = str(payload.get("relation_type") or "pays_for")
    status = str(payload.get("status") or "confirmed")
    if status not in {"proposed", "confirmed", "rejected", "superseded"}:
        raise ValueError(f"지원하지 않는 예약 연결 상태: {status}")
    db.execute(
        """
        INSERT INTO payment_booking_links(
            payment_id, booking_id, relation_type, confidence, link_status
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(payment_id, booking_id, relation_type) DO UPDATE SET
            confidence=excluded.confidence,
            link_status=excluded.link_status
        """,
        (
            int(payment["id"]),
            booking_id,
            relation_type,
            float(payload.get("confidence", 1.0)),
            status,
        ),
    )


def apply_change_log(db: sqlite3.Connection, path: Path) -> int:
    """Apply unapplied JSONL events transactionally and idempotently."""
    initialize(db)
    if not path.exists():
        return 0
    applied = 0
    with db, path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            event = json.loads(line)
            raw_semantic = {
                "event_type": str(event.get("event_type") or ""),
                "target_type": str(event.get("target_type") or ""),
                "target_key": str(event.get("target_key") or ""),
                "payload": event.get("payload"),
                "actor": str(event.get("actor") or "User"),
            }
            if redact_sensitive_payload(raw_semantic) != raw_semantic:
                raise ValueError(
                    f"변경 이벤트에 저장 금지 민감정보가 있습니다: "
                    f"{path}:{line_number}"
                )
            normalized = canonical_change_event(event)
            event_id = str(event.get("event_id") or "")
            if not event_id or event_id != normalized["event_id"]:
                raise ValueError(
                    f"변경 이벤트 무결성 오류(내용 또는 event_id 변조): "
                    f"{path}:{line_number}"
                )
            event = normalized
            if db.execute(
                "SELECT 1 FROM ledger_change_events WHERE event_id=?",
                (event_id,),
            ).fetchone():
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                raise ValueError(f"변경 이벤트 payload 오류: {path}:{line_number}")
            event_type = str(event["event_type"])
            if event_type == "classification_decision":
                _apply_classification_change(
                    db,
                    str(event["target_type"]),
                    str(event["target_key"]),
                    payload,
                )
            elif event_type == "payment_booking_link":
                _apply_payment_booking_change(
                    db,
                    str(event["target_key"]),
                    payload,
                )
            else:
                raise ValueError(f"지원하지 않는 변경 이벤트: {event_type}")
            db.execute(
                """
                INSERT INTO ledger_change_events(
                    event_id, event_type, target_type, target_key,
                    payload_json, actor, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    str(event["target_type"]),
                    str(event["target_key"]),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    str(event.get("actor") or "User"),
                    str(event["recorded_at"]),
                ),
            )
            applied += 1
    return applied


def replace_allocation_plan(
    db: sqlite3.Connection,
    payment_id: int,
    items: list[AllocationItem],
    status: str,
    confidence: float,
    source_decision_id: int | None = None,
) -> int:
    if not items:
        raise ValueError("배분 plan에는 한 개 이상의 배분 행이 필요합니다.")
    if scalar(
        db,
        """
        SELECT COUNT(*) FROM authorization_holds
        WHERE hold_payment_id=?
           OR (related_payment_id=? AND hold_status='released')
        """,
        (payment_id, payment_id),
    ):
        raise ValueError("authorization hold 또는 해제 이벤트는 비용 배분할 수 없습니다.")
    payment_amount = scalar(
        db,
        "SELECT amount_krw FROM payment_transactions WHERE id=?",
        (payment_id,),
    )
    allocation_total = sum(item.amount_krw for item in items)
    if payment_amount != allocation_total:
        raise ValueError(
            f"결제금액과 배분합계가 다릅니다: payment={payment_amount:,}, allocation={allocation_total:,}"
        )

    previous_plan = db.execute(
        """
        SELECT p.id, p.plan_version, p.plan_status, p.confidence, p.source_decision_id
        FROM allocation_plans p
        WHERE p.payment_id=?
          AND NOT EXISTS (
              SELECT 1 FROM allocation_plans newer
              WHERE newer.supersedes_plan_id=p.id
          )
        """,
        (payment_id,),
    ).fetchone()
    if previous_plan:
        previous_rows = db.execute(
            """
            SELECT target_id, amount_krw, booking_id
            FROM cost_allocations WHERE plan_id=? ORDER BY id
            """,
            (previous_plan["id"],),
        ).fetchall()
        if (
            [tuple(row) for row in previous_rows]
            == [(item.target_id, item.amount_krw, item.booking_id) for item in items]
            and previous_plan["plan_status"] == status
            and previous_plan["confidence"] == confidence
            and previous_plan["source_decision_id"] == source_decision_id
        ):
            return int(previous_plan["id"])
    next_version = scalar(
        db,
        "SELECT COALESCE(MAX(plan_version), 0) + 1 FROM allocation_plans WHERE payment_id=?",
        (payment_id,),
    )
    plan_id = int(
        db.execute(
            """
            INSERT INTO allocation_plans(
                payment_id, plan_version, plan_status, confidence,
                source_decision_id, supersedes_plan_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payment_id,
                next_version,
                status,
                confidence,
                source_decision_id,
                int(previous_plan["id"]) if previous_plan else None,
            ),
        ).lastrowid
    )
    db.executemany(
        """
        INSERT INTO cost_allocations(plan_id, booking_id, target_id, amount_krw)
        VALUES (?, ?, ?, ?)
        """,
        [
            (plan_id, item.booking_id, item.target_id, item.amount_krw)
            for item in items
        ],
    )
    return plan_id


def reject_current_allocation_plan(
    db: sqlite3.Connection,
    payment_id: int,
) -> int | None:
    """Append a rejected leaf without mutating or uncovering an older plan."""
    current = db.execute(
        """
        SELECT p.id, p.plan_status, p.confidence, p.source_decision_id
        FROM allocation_plans p
        WHERE p.payment_id=?
          AND NOT EXISTS (
              SELECT 1
              FROM allocation_plans newer
              WHERE newer.supersedes_plan_id=p.id
          )
        """,
        (payment_id,),
    ).fetchone()
    if current is None:
        return None
    if current["plan_status"] == "rejected":
        return int(current["id"])
    items = [
        AllocationItem(
            target_id=int(row["target_id"]),
            amount_krw=int(row["amount_krw"]),
            booking_id=(
                int(row["booking_id"])
                if row["booking_id"] is not None
                else None
            ),
        )
        for row in db.execute(
            """
            SELECT target_id, amount_krw, booking_id
            FROM cost_allocations
            WHERE plan_id=?
            ORDER BY id
            """,
            (int(current["id"]),),
        ).fetchall()
    ]
    if not items:
        raise ValueError("현재 allocation plan에 거절 이력을 승계할 배분행이 없습니다.")
    return replace_allocation_plan(
        db,
        payment_id,
        items,
        status="rejected",
        confidence=float(current["confidence"]),
        source_decision_id=(
            int(current["source_decision_id"])
            if current["source_decision_id"] is not None
            else None
        ),
    )


def replace_legacy_allocation_plan(
    db: sqlite3.Connection,
    payment_id: int,
    booking_id: int | None,
    target_id: int,
    amount: int,
    confidence: float,
    source_decision_id: int,
) -> int:
    return replace_allocation_plan(
        db,
        payment_id,
        [AllocationItem(target_id=target_id, amount_krw=amount, booking_id=booking_id)],
        status="legacy",
        confidence=confidence,
        source_decision_id=source_decision_id,
    )


def import_legacy(
    db: sqlite3.Connection,
    csv_path: Path,
    trips_path: Path,
    bookings_path: Path,
) -> ImportStats:
    initialize(db)
    digest = file_sha256(csv_path)
    existing_doc = db.execute(
        "SELECT id FROM source_documents WHERE path=? AND sha256=?",
        (str(csv_path.resolve()), digest),
    ).fetchone()
    if existing_doc:
        report = validation_report(db)
        return ImportStats(
            source_rows=report["source_records"],
            transactions=report["transactions"],
            bookings=report["bookings"],
            allocations=report["active_allocations"],
            decisions=report["current_decisions"],
            amount_krw=report["transaction_total_krw"],
            repeated_snapshot=True,
        )

    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    booking_info = json.loads(bookings_path.read_text(encoding="utf-8"))
    verified_numbers = verified_booking_numbers(db, booking_info)

    with db:
        known_trips = load_trips(db, trips_path)
        document_id = int(
            db.execute(
                """
                INSERT INTO source_documents(source_kind, path, sha256)
                VALUES ('classified_v14_snapshot', ?, ?)
                """,
                (str(csv_path.resolve()), digest),
            ).lastrowid
        )
        # The classified canonical is a complete snapshot. End only legacy-derived links
        # before rebuilding the current projection; confirmed/proposed links
        # from later evidence remain untouched.
        db.execute(
            """
            UPDATE payment_booking_links
            SET link_status='superseded', superseded_by_document_id=?
            WHERE link_status='legacy'
            """,
            (document_id,),
        )
        db.execute(
            """
            UPDATE booking_target_links
            SET link_status='superseded', superseded_by_document_id=?
            WHERE link_status='legacy'
            """,
            (document_id,),
        )
        db.execute(
            """
            UPDATE transaction_relations
            SET relation_status='superseded', superseded_by_document_id=?
            WHERE relation_status='legacy'
            """,
            (document_id,),
        )

        imported_payment_ids: list[int] = []
        approval_lookup: dict[tuple[str, str], list[int]] = {}
        pending_relations: list[tuple[int, str, str]] = []

        for row_number, row in enumerate(rows, start=2):
            source_record_id = int(
                db.execute(
                    """
                    INSERT INTO source_records(document_id, row_number, natural_key, raw_payload)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        row_number,
                        row.get("uid"),
                        json.dumps(row, ensure_ascii=False, sort_keys=True),
                    ),
                ).lastrowid
            )
            method_id = upsert_payment_method(db, row)
            payment_id = upsert_payment(db, row, method_id, source_record_id)
            imported_payment_ids.append(payment_id)
            db.execute(
                """
                INSERT OR IGNORE INTO transaction_sources(transaction_id, source_record_id)
                VALUES (?, ?)
                """,
                (payment_id, source_record_id),
            )

            issuer = ISSUER_BY_SOURCE.get(row.get("src", ""), row.get("src", ""))
            approval = re.sub(r"\D", "", row.get("appr", ""))
            if approval and parse_int(row.get("krw")) > 0 and not is_true(row.get("cancel")):
                approval_lookup.setdefault((issuer, approval), []).append(payment_id)
            original = re.sub(r"\D", "", row.get("orig_appr", ""))
            if original:
                pending_relations.append((payment_id, issuer, original))
            elif parse_int(row.get("krw")) < 0:
                pending_relations.append(
                    (payment_id, issuer, f"missing:{row['uid']}")
                )

            confidence_label = row.get("confidence") or "하"
            confidence = CONFIDENCE.get(confidence_label, 0.3)
            note = row.get("note") or ""
            evidence_id = int(
                db.execute(
                    """
                    INSERT INTO evidence(
                        evidence_type, source_record_id, reference_value, observed_value, summary
                    ) VALUES ('legacy_note', ?, ?, ?, ?)
                    """,
                    (source_record_id, row.get("uid"), row.get("note") or None, note or None),
                ).lastrowid
            )

            code = row.get("bucket") or "미정"
            kind = target_type(code, known_trips)
            target_id = ensure_target(db, code, kind)
            allocation_decision_id = replace_decision(
                db,
                "payment",
                payment_id,
                "allocation_target",
                code,
                confidence,
                confidence_label,
                note,
                evidence_id,
            )
            replace_decision(
                db,
                "payment",
                payment_id,
                "expense_type",
                row.get("account") or "미정",
                confidence,
                confidence_label,
                note,
                evidence_id,
            )
            replace_decision(
                db,
                "payment",
                payment_id,
                "cost_nature",
                row.get("cost_type") or "미정",
                confidence,
                confidence_label,
                note,
                evidence_id,
            )
            replace_decision(
                db,
                "payment",
                payment_id,
                "vat_treatment",
                row.get("vat_tag") or "미정",
                CONFIDENCE.get(row.get("tax_conf") or "", confidence),
                row.get("tax_conf") or confidence_label,
                note,
                evidence_id,
            )
            replace_decision(
                db,
                "payment",
                payment_id,
                "legacy_status",
                row.get("status") or "미정",
                confidence,
                confidence_label,
                note,
                evidence_id,
            )

            source_disposition = row.get("source_event_disposition") or ""
            is_nonposting_projection = source_disposition in NONPOSTING_SOURCE_DISPOSITIONS
            if source_disposition:
                replace_decision(
                    db,
                    "payment",
                    payment_id,
                    "source_event_disposition",
                    source_disposition,
                    1.0 if is_nonposting_projection else confidence,
                    "상" if is_nonposting_projection else confidence_label,
                    (
                        f"source alias of {row.get('source_event_alias_of')}"
                        if row.get("source_event_alias_of")
                        else source_disposition
                    ),
                    evidence_id,
                    decision_status="confirmed" if is_nonposting_projection else "legacy",
                    rule_id=f"lineage:{source_disposition}",
                )

            if is_nonposting_projection:
                # Keep the payment fact and its source record for audit, but
                # reject any legacy cost plan.  The reconciliation disposition
                # is finalized separately as a non-posting alias.
                reject_current_allocation_plan(db, payment_id)
                continue

            linked_bookings: list[int] = []
            note_booking_numbers = booking_numbers(note)
            linked_booking_numbers = [
                number for number in note_booking_numbers if number in verified_numbers
            ]
            unverified_numbers = [
                number for number in note_booking_numbers if number not in verified_numbers
            ]
            if unverified_numbers:
                # Preserve the lead for review without treating a note-only
                # reference as a Gmail/booking-file confirmation.  It is
                # deliberately excluded from both booking links and period
                # recognition below.
                replace_decision(
                    db,
                    "payment",
                    payment_id,
                    "booking_reference_status",
                    "unverified_booking_ref",
                    0.0,
                    "하",
                    "note-only booking reference has no Gmail or booking-file evidence",
                    evidence_id,
                    decision_status="needs_review",
                    rule_id="booking-ref:unverified-note-only",
                )
            for number in linked_booking_numbers:
                booking_id = ensure_booking(db, number, row, booking_info)
                linked_bookings.append(booking_id)
                db.execute(
                    """
                    INSERT INTO payment_booking_links(
                        payment_id, booking_id, relation_type, confidence, link_status,
                        first_seen_document_id, last_seen_document_id
                    ) VALUES (?, ?, 'pays_for', ?, 'legacy', ?, ?)
                    ON CONFLICT(payment_id, booking_id, relation_type) DO UPDATE SET
                        confidence=excluded.confidence,
                        link_status='legacy',
                        first_seen_document_id=COALESCE(
                            payment_booking_links.first_seen_document_id,
                            excluded.first_seen_document_id
                        ),
                        last_seen_document_id=excluded.last_seen_document_id,
                        superseded_by_document_id=NULL
                    """,
                    (payment_id, booking_id, confidence, document_id, document_id),
                )
                db.execute(
                    """
                    INSERT INTO booking_target_links(
                        booking_id, target_id, confidence, link_status,
                        first_seen_document_id, last_seen_document_id
                    )
                    VALUES (?, ?, ?, 'legacy', ?, ?)
                    ON CONFLICT(booking_id, target_id) DO UPDATE SET
                        confidence=excluded.confidence,
                        link_status='legacy',
                        first_seen_document_id=COALESCE(
                            booking_target_links.first_seen_document_id,
                            excluded.first_seen_document_id
                        ),
                        last_seen_document_id=excluded.last_seen_document_id,
                        superseded_by_document_id=NULL
                    """,
                    (booking_id, target_id, confidence, document_id, document_id),
                )

            allocation_booking_id = linked_bookings[0] if len(linked_bookings) == 1 else None
            if refundable_deposit_pending_for_payment(
                db,
                linked_booking_numbers,
                booking_info,
            ):
                # A charged, refundable deposit awaits its contractual return
                # or capture.  It is not interchangeable with a normal
                # prepaid service, which has a known future start date.
                replace_decision(
                    db, "payment", payment_id, "period_recognition", "settlement_pending",
                    1.0, "상", "structured booking says refundable deposit pending", evidence_id,
                    decision_status="confirmed", rule_id="period:refundable-deposit",
                )
                replace_decision(
                    db, "payment", payment_id, "allocation_target", "비용외정산",
                    1.0, "상", "refundable deposit awaits settlement", evidence_id,
                    decision_status="confirmed", rule_id="period:refundable-deposit",
                )
                replace_decision(
                    db, "payment", payment_id, "expense_type", "보증금정산대기",
                    1.0, "상", "refundable deposit awaits settlement", evidence_id,
                    decision_status="confirmed", rule_id="period:refundable-deposit",
                )
                replace_decision(
                    db, "payment", payment_id, "cost_nature", "비용외정산",
                    1.0, "상", "refundable deposit awaits settlement", evidence_id,
                    decision_status="confirmed", rule_id="period:refundable-deposit",
                )
                reject_current_allocation_plan(db, payment_id)
                continue
            future_service_start = future_service_start_for_payment(
                db,
                linked_booking_numbers,
                booking_info,
            )
            if future_service_start:
                # The payment happened in Q2, but the linked service begins
                # later.  Retain the card event and the real trip target as
                # auditable facts; do not recognize a Q2 travel cost or emit
                # an automatic posting until the service period is reached.
                replace_decision(
                    db, "payment", payment_id, "service_start_on", future_service_start,
                    1.0, "상", "linked booking service start", evidence_id,
                    decision_status="confirmed", rule_id="period:service-start",
                )
                replace_decision(
                    db, "payment", payment_id, "service_period_target", code,
                    confidence, confidence_label, "preserved future service target", evidence_id,
                    decision_status="confirmed", rule_id="period:prepaid-future-trip",
                )
                replace_decision(
                    db, "payment", payment_id, "service_period_expense_type",
                    row.get("account") or "미정", confidence, confidence_label,
                    "preserved future service expense type", evidence_id,
                    decision_status="confirmed", rule_id="period:prepaid-future-trip",
                )
                replace_decision(
                    db, "payment", payment_id, "service_period_cost_nature",
                    row.get("cost_type") or "미정", confidence, confidence_label,
                    "preserved future service cost nature", evidence_id,
                    decision_status="confirmed", rule_id="period:prepaid-future-trip",
                )
                replace_decision(
                    db, "payment", payment_id, "period_recognition", "prepaid_future_trip",
                    1.0, "상", f"service starts {future_service_start} after Q2 close {Q2_CLOSE_ON}",
                    evidence_id, decision_status="confirmed", rule_id="period:prepaid-future-trip",
                )
                replace_decision(
                    db, "payment", payment_id, "allocation_target", "비용외정산",
                    1.0, "상", "future service is outside the Q2 cost period", evidence_id,
                    decision_status="confirmed", rule_id="period:prepaid-future-trip",
                )
                replace_decision(
                    db, "payment", payment_id, "expense_type", "선급비용",
                    1.0, "상", "future service is outside the Q2 cost period", evidence_id,
                    decision_status="confirmed", rule_id="period:prepaid-future-trip",
                )
                replace_decision(
                    db, "payment", payment_id, "cost_nature", "비용외정산",
                    1.0, "상", "future service is outside the Q2 cost period", evidence_id,
                    decision_status="confirmed", rule_id="period:prepaid-future-trip",
                )
                reject_current_allocation_plan(db, payment_id)
                continue
            replace_legacy_allocation_plan(
                db,
                payment_id,
                allocation_booking_id,
                target_id,
                parse_int(row.get("krw")),
                confidence,
                allocation_decision_id,
            )

        for transaction_id, issuer, original in pending_relations:
            has_original_reference = not original.startswith("missing:")
            original_candidates = (
                approval_lookup.get((issuer, original), [])
                if has_original_reference else []
            )
            refund_row = db.execute(
                """
                SELECT amount_krw, occurred_on, merchant
                FROM payment_transactions WHERE id=?
                """,
                (transaction_id,),
            ).fetchone()
            candidate_rows = [
                db.execute(
                    """
                    SELECT id, amount_krw, occurred_on, merchant
                    FROM payment_transactions WHERE id=?
                    """,
                    (candidate_id,),
                ).fetchone()
                for candidate_id in original_candidates
            ]
            exact_amount = [
                candidate
                for candidate in candidate_rows
                if abs(int(candidate["amount_krw"])) == abs(int(refund_row["amount_krw"]))
            ]
            eligible = exact_amount if len(exact_amount) == 1 else candidate_rows
            related_id = (
                int(eligible[0]["id"])
                if len(eligible) == 1
                else None
            )
            ambiguous_original = len(original_candidates) > 1 and related_id is None
            if related_id == transaction_id:
                related_id = None
            refund_amount = int(
                db.execute(
                    "SELECT amount_krw FROM payment_transactions WHERE id=?",
                    (transaction_id,),
                ).fetchone()[0]
            )
            original_amount = (
                int(
                    db.execute(
                        "SELECT amount_krw FROM payment_transactions WHERE id=?",
                        (related_id,),
                    ).fetchone()[0]
                )
                if related_id is not None else None
            )
            is_full_cancellation = (
                original_amount is not None
                and refund_amount < 0
                and abs(refund_amount) == abs(original_amount)
            )
            relation_type = "cancels" if is_full_cancellation else "refunds"
            transaction_type = "cancellation" if is_full_cancellation else "refund"
            current_type = str(
                db.execute(
                    "SELECT transaction_type FROM payment_transactions WHERE id=?",
                    (transaction_id,),
                ).fetchone()[0]
            )
            if current_type != transaction_type:
                latest_source_record_id = int(
                    db.execute(
                        """
                        SELECT source_record_id
                        FROM payment_transaction_versions
                        WHERE transaction_id=?
                        ORDER BY record_version DESC
                        LIMIT 1
                        """,
                        (transaction_id,),
                    ).fetchone()[0]
                )
                db.execute(
                    """
                    UPDATE payment_transactions
                    SET transaction_type=?, record_version=record_version+1,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (transaction_type, transaction_id),
                )
                db.execute(
                    """
                    INSERT INTO payment_transaction_versions(
                        transaction_id, record_version, source_record_id,
                        source_event_id, identity_fingerprint,
                        payment_method_id, source_system, occurred_on, posted_on,
                        merchant, business_category, country, currency,
                        foreign_amount, amount_krw, approval_number,
                        transaction_type
                    )
                    SELECT
                        id, record_version, ?, source_event_id, identity_fingerprint,
                        payment_method_id, source_system,
                        occurred_on, posted_on, merchant, business_category,
                        country, currency, foreign_amount, amount_krw,
                        approval_number, transaction_type
                    FROM payment_transactions
                    WHERE id=?
                    """,
                    (latest_source_record_id, transaction_id),
                )
            allocation_code = db.execute(
                """
                SELECT t.code
                FROM current_cost_allocations a
                JOIN allocation_targets t ON t.id=a.target_id
                WHERE a.payment_id=?
                ORDER BY a.id LIMIT 1
                """,
                (transaction_id,),
            ).fetchone()
            relation_source_rows = (
                db.execute(
                    """
                    SELECT external_key, source_event_id, source_system
                    FROM payment_transactions
                    WHERE id IN (?, ?)
                    """,
                    (transaction_id, related_id),
                ).fetchall()
                if related_id is not None
                else []
            )
            source_events_verified = bool(
                len(relation_source_rows) == 2
                and all(
                    str(source_row["source_event_id"])
                    != str(source_row["external_key"])
                    or str(source_row["external_key"]).startswith(
                        f"{source_row['source_system']}-"
                    )
                    for source_row in relation_source_rows
                )
            )
            if related_id and source_events_verified:
                relation_status = "confirmed"
                resolution_code = "original_linked"
                rationale = "카드사 구조키로 원거래 연결"
            elif related_id:
                relation_status = "proposed"
                resolution_code = "source_event_unverified"
                rationale = (
                    "원승인 후보는 연결됐지만 raw source_event_id 확인 전"
                )
            elif allocation_code and allocation_code["code"] == "전기예약_환불":
                relation_status = "confirmed"
                resolution_code = "original_outside_window"
                rationale = "원거래가 현재 적재기간 밖인 전기예약 환불"
            else:
                relation_status = "proposed"
                resolution_code = (
                    "ambiguous_original_approval"
                    if ambiguous_original
                    else "insufficient_evidence"
                )
                rationale = (
                    "동일 원승인번호 후보가 복수여서 금액·일자 근거 추가 대기"
                    if ambiguous_original
                    else "환불 이벤트는 보존하며 원승인 또는 예약 근거를 추가 대기"
                )
            db.execute(
                f"""
                INSERT INTO transaction_relations(
                    transaction_id, related_transaction_id, relation_type,
                    reference_value, match_method, confidence, relation_status,
                    resolution_code, rationale,
                    first_seen_document_id, last_seen_document_id
                ) VALUES (?, ?, '{relation_type}', ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(transaction_id, relation_type, reference_value) DO UPDATE SET
                    related_transaction_id=excluded.related_transaction_id,
                    match_method=excluded.match_method,
                    confidence=excluded.confidence,
                    relation_status=excluded.relation_status,
                    resolution_code=excluded.resolution_code,
                    rationale=excluded.rationale,
                    first_seen_document_id=COALESCE(
                        transaction_relations.first_seen_document_id,
                        excluded.first_seen_document_id
                    ),
                    last_seen_document_id=excluded.last_seen_document_id,
                    superseded_by_document_id=NULL
                """,
                (
                    transaction_id,
                    related_id,
                    original,
                    (
                        "issuer+original_approval"
                        if related_id and source_events_verified
                        else "unverified_source_event+original_approval"
                        if related_id
                        else "ambiguous_original_approval"
                        if ambiguous_original
                        else "unresolved_original_approval"
                        if has_original_reference
                        else "missing_original_reference"
                    ),
                    1.0 if related_id else 0.5 if has_original_reference else 0.2,
                    relation_status,
                    resolution_code,
                    rationale,
                    document_id,
                    document_id,
                ),
            )

    report = validation_report(db, payment_ids=imported_payment_ids)
    return ImportStats(
        source_rows=len(rows),
        transactions=len(imported_payment_ids),
        bookings=report["bookings"],
        allocations=report["active_allocations"],
        decisions=report["current_decisions"],
        amount_krw=sum(parse_int(row.get("krw")) for row in rows),
    )


def scalar(db: sqlite3.Connection, query: str, params: Iterable[object] = ()) -> int:
    return int(db.execute(query, tuple(params)).fetchone()[0])


def confirmed_direct_booking_terms(
    db: sqlite3.Connection,
    booking_numbers_for_payment: Iterable[str],
) -> dict[str, dict[str, str]]:
    """Read only non-conflicting confirmed periods from direct OTA evidence."""
    numbers = list(dict.fromkeys(booking_numbers_for_payment))
    if not numbers:
        return {}
    placeholders = ",".join("?" for _ in numbers)
    rows = db.execute(
        f"""
        SELECT b.booking_number, p.service_start_on,
               COALESCE(p.settlement_condition, '') AS settlement_condition
        FROM direct_booking_service_periods p
        JOIN bookings b ON b.id=p.booking_id
        WHERE p.evidence_status='confirmed'
          AND b.booking_number IN ({placeholders})
        """,
        numbers,
    ).fetchall()
    candidates: dict[str, set[tuple[str, str]]] = {}
    for row in rows:
        candidates.setdefault(str(row["booking_number"]), set()).add(
            (str(row["service_start_on"]), str(row["settlement_condition"] or ""))
        )
    return {
        number: {
            "service_start_on": next(iter(values))[0],
            "settlement_condition": next(iter(values))[1],
        }
        for number, values in candidates.items()
        if len(values) == 1
    }


def future_service_start_for_payment(
    db: sqlite3.Connection,
    booking_numbers_for_payment: Iterable[str],
    booking_info: dict[str, dict],
    *,
    closed_through_on: str = Q2_CLOSE_ON,
) -> str | None:
    """Return a future start only from every linked structured booking field."""
    numbers = list(booking_numbers_for_payment)
    if not numbers:
        return None
    direct_terms = confirmed_direct_booking_terms(db, numbers)
    starts: list[str | None] = []
    for number in numbers:
        candidates = {
            value
            for value in (
                structured_service_start_on(booking_info.get(number, {})),
                direct_terms.get(number, {}).get("service_start_on"),
            )
            if value
        }
        if len(candidates) != 1:
            return None
        starts.append(next(iter(candidates)))
    if not all(starts):
        return None
    if not all(
        is_prepaid_future_trip(start, closed_through_on=closed_through_on)
        for start in starts
    ):
        return None
    return min(str(start) for start in starts)


def refundable_deposit_pending_for_payment(
    db: sqlite3.Connection,
    booking_numbers_for_payment: Iterable[str],
    booking_info: dict[str, dict],
) -> bool:
    """Recognize a deposit only from an explicit structured contract state.

    A mention of a deposit or refund in a card note must not turn an ordinary
    advance payment into a settlement item.  Multiple linked bookings must all
    carry the same explicit state before the whole payment is excluded.
    """
    numbers = list(booking_numbers_for_payment)
    if not numbers:
        return False
    direct_terms = confirmed_direct_booking_terms(db, numbers)
    for number in numbers:
        conditions = {
            value
            for value in (
                str(booking_info.get(number, {}).get("settlement_condition") or ""),
                direct_terms.get(number, {}).get("settlement_condition"),
            )
            if value
        }
        if conditions != {"refundable_deposit_pending"}:
            return False
    return True


def recognize_prepaid_service_period(
    db: sqlite3.Connection,
    *,
    recognized_through_on: str,
) -> int:
    """Recognize deferred service without creating another payment event."""
    try:
        date.fromisoformat(recognized_through_on)
    except ValueError as exc:
        raise ValueError("recognized_through_on은 YYYY-MM-DD 형식이어야 합니다.") from exc
    rows = db.execute(
        """
        SELECT p.id AS payment_id, p.amount_krw, start.value AS service_start_on,
               target.value AS target_code, expense.value AS expense_type,
               nature.value AS cost_nature,
               CASE WHEN COUNT(DISTINCT b.id)=1 THEN MIN(b.id) END AS booking_id,
               at.id AS target_id
        FROM payment_transactions p
        JOIN current_classification_decisions period
          ON period.target_type='payment' AND period.target_id=p.id
         AND period.dimension='period_recognition' AND period.value='prepaid_future_trip'
        JOIN current_classification_decisions start
          ON start.target_type='payment' AND start.target_id=p.id AND start.dimension='service_start_on'
        JOIN current_classification_decisions target
          ON target.target_type='payment' AND target.target_id=p.id AND target.dimension='service_period_target'
        JOIN current_classification_decisions expense
          ON expense.target_type='payment' AND expense.target_id=p.id AND expense.dimension='service_period_expense_type'
        JOIN current_classification_decisions nature
          ON nature.target_type='payment' AND nature.target_id=p.id AND nature.dimension='service_period_cost_nature'
        JOIN allocation_targets at ON at.code=target.value
        LEFT JOIN payment_booking_links pbl
          ON pbl.payment_id=p.id AND pbl.link_status NOT IN ('rejected', 'superseded')
        LEFT JOIN bookings b ON b.id=pbl.booking_id
        WHERE start.value <= ?
        GROUP BY p.id
        """,
        (recognized_through_on,),
    ).fetchall()
    changed = 0
    for row in rows:
        payment_id = int(row["payment_id"])
        decision_id = replace_decision(
            db, "payment", payment_id, "period_recognition", "recognized_service_period",
            1.0, "상", f"service starts {row['service_start_on']} within close through {recognized_through_on}",
            None, decision_status="confirmed", rule_id="period:service-recognition",
        )
        for dimension, key in (
            ("allocation_target", "target_code"),
            ("expense_type", "expense_type"),
            ("cost_nature", "cost_nature"),
        ):
            replace_decision(
                db, "payment", payment_id, dimension, str(row[key]), 1.0, "상",
                "restored when service period became recognizable", None,
                decision_status="confirmed", rule_id="period:service-recognition",
            )
        replace_allocation_plan(
            db,
            payment_id,
            [AllocationItem(
                target_id=int(row["target_id"]),
                amount_krw=int(row["amount_krw"]),
                booking_id=int(row["booking_id"]) if row["booking_id"] else None,
            )],
            status="confirmed", confidence=1.0, source_decision_id=decision_id,
        )
        changed += 1
    return changed


def validation_report(
    db: sqlite3.Connection,
    payment_ids: Iterable[int] | None = None,
) -> dict[str, int | bool]:
    ids = list(payment_ids or [])
    # Authorization holds are card-lifecycle evidence, not recognizable cost.
    # Their one-to-one final disposition is checked by ``coverage_report``;
    # including them here would make the allocation-total gate fail precisely
    # when they are correctly excluded from ``current_cost_allocations``.
    scope_sql = (
        " WHERE NOT EXISTS ("
        "SELECT 1 FROM authorization_holds h WHERE h.hold_payment_id=p.id"
        ") AND NOT EXISTS ("
        "SELECT 1 FROM authorization_holds h "
        "WHERE h.related_payment_id=p.id AND h.hold_status='released'"
        ")"
        " AND NOT EXISTS ("
        "SELECT 1 FROM current_classification_decisions sd "
        "WHERE sd.target_type='payment' AND sd.target_id=p.id "
        "AND sd.dimension='source_event_disposition' "
        "AND sd.value IN ('superseded_duplicate_projection', 'manual_claimed_card_no_raw', 'rejected_legacy_projection')"
        ")"
        " AND NOT EXISTS ("
        "SELECT 1 FROM current_classification_decisions pr "
        "WHERE pr.target_type='payment' AND pr.target_id=p.id "
        "AND pr.dimension='period_recognition' "
        "AND pr.value IN ('prepaid_future_trip', 'settlement_pending')"
        ")"
    )


    params: list[object] = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        scope_sql += f" AND p.id IN ({placeholders})"
        params.extend(ids)

    transaction_count = scalar(db, f"SELECT COUNT(*) FROM payment_transactions p{scope_sql}", params)
    transaction_total = scalar(
        db,
        f"SELECT COALESCE(SUM(p.amount_krw), 0) FROM payment_transactions p{scope_sql}",
        params,
    )
    if ids:
        placeholders = ",".join("?" for _ in ids)
        allocation_count = scalar(
            db,
            f"""
            SELECT COUNT(*) FROM current_cost_allocations
            WHERE payment_id IN ({placeholders})
            """,
            ids,
        )
        allocation_total = scalar(
            db,
            f"""
            SELECT COALESCE(SUM(amount_krw), 0) FROM current_cost_allocations
            WHERE payment_id IN ({placeholders})
            """,
            ids,
        )
        mismatches = scalar(
            db,
            f"""
            SELECT COUNT(*) FROM payment_allocation_summary
            WHERE payment_id IN ({placeholders})
              AND NOT EXISTS (
                  SELECT 1 FROM authorization_holds h
                  WHERE h.hold_payment_id=payment_allocation_summary.payment_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM authorization_holds h
                  WHERE h.related_payment_id=payment_allocation_summary.payment_id
                    AND h.hold_status='released'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM current_classification_decisions sd
                  WHERE sd.target_type='payment'
                    AND sd.target_id=payment_allocation_summary.payment_id
                    AND sd.dimension='source_event_disposition'
                    AND sd.value IN ('superseded_duplicate_projection', 'manual_claimed_card_no_raw', 'rejected_legacy_projection')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM current_classification_decisions pr
                  WHERE pr.target_type='payment'
                    AND pr.target_id=payment_allocation_summary.payment_id
                    AND pr.dimension='period_recognition'
                    AND pr.value IN ('prepaid_future_trip', 'settlement_pending')
              )
              AND difference_krw <> 0
            """,
            ids,
        )
    else:
        allocation_count = scalar(db, "SELECT COUNT(*) FROM current_cost_allocations")
        allocation_total = scalar(db, "SELECT COALESCE(SUM(amount_krw), 0) FROM current_cost_allocations")
        mismatches = scalar(
            db,
            """
            SELECT COUNT(*) FROM payment_allocation_summary
            WHERE NOT EXISTS (
                SELECT 1 FROM authorization_holds h
                WHERE h.hold_payment_id=payment_allocation_summary.payment_id
            )
              AND NOT EXISTS (
                  SELECT 1 FROM authorization_holds h
                  WHERE h.related_payment_id=payment_allocation_summary.payment_id
                    AND h.hold_status='released'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM current_classification_decisions sd
                  WHERE sd.target_type='payment'
                    AND sd.target_id=payment_allocation_summary.payment_id
                    AND sd.dimension='source_event_disposition'
                    AND sd.value IN ('superseded_duplicate_projection', 'manual_claimed_card_no_raw', 'rejected_legacy_projection')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM current_classification_decisions pr
                  WHERE pr.target_type='payment'
                    AND pr.target_id=payment_allocation_summary.payment_id
                    AND pr.dimension='period_recognition'
                    AND pr.value IN ('prepaid_future_trip', 'settlement_pending')
              )
              AND difference_krw <> 0
            """,
        )

    report: dict[str, int | bool] = {
        "source_documents": scalar(db, "SELECT COUNT(*) FROM source_documents"),
        "source_records": scalar(db, "SELECT COUNT(*) FROM source_records"),
        "transactions": transaction_count,
        "transaction_versions": scalar(
            db, "SELECT COUNT(*) FROM payment_transaction_versions"
        ),
        "card_event_identities": scalar(
            db, "SELECT COUNT(*) FROM card_event_identities"
        ),
        "missing_card_event_identities": scalar(
            db,
            """
            SELECT COUNT(*)
            FROM payment_transactions p
            LEFT JOIN card_event_identities i ON i.transaction_id=p.id
            WHERE i.transaction_id IS NULL
            """,
        ),
        "card_event_identity_collisions": scalar(
            db,
            """
            SELECT COUNT(*)
            FROM card_event_identities
            WHERE identity_status='collision'
            """,
        ),
        "transaction_total_krw": transaction_total,
        "bookings": scalar(db, "SELECT COUNT(*) FROM bookings"),
        "trips": scalar(db, "SELECT COUNT(*) FROM trips"),
        "allocation_targets": scalar(db, "SELECT COUNT(*) FROM allocation_targets"),
        "active_allocations": allocation_count,
        "allocation_total_krw": allocation_total,
        "allocation_mismatches": mismatches,
        "current_decisions": scalar(db, "SELECT COUNT(*) FROM current_classification_decisions"),
        "transaction_relations": scalar(
            db,
            """
            SELECT COUNT(*) FROM transaction_relations
            WHERE relation_status NOT IN ('rejected', 'superseded')
            """,
        ),
        "resolved_transaction_relations": scalar(
            db,
            """
            SELECT COUNT(*) FROM transaction_relations
            WHERE related_transaction_id IS NOT NULL
              AND relation_status NOT IN ('rejected', 'superseded')
            """,
        ),
        "outside_window_transaction_relations": scalar(
            db,
            """
            SELECT COUNT(*) FROM transaction_relations
            WHERE related_transaction_id IS NULL
              AND resolution_code='original_outside_window'
              AND relation_status NOT IN ('rejected', 'superseded')
            """,
        ),
        "insufficient_evidence_transaction_relations": scalar(
            db,
            """
            SELECT COUNT(*) FROM transaction_relations
            WHERE related_transaction_id IS NULL
              AND resolution_code='insufficient_evidence'
              AND relation_status NOT IN ('rejected', 'superseded')
            """,
        ),
        "unexplained_transaction_relations": scalar(
            db,
            """
            SELECT COUNT(*) FROM transaction_relations
            WHERE related_transaction_id IS NULL
              AND resolution_code IS NULL
              AND relation_status NOT IN ('rejected', 'superseded')
            """,
        ),
        "superseded_payment_booking_links": scalar(
            db,
            "SELECT COUNT(*) FROM payment_booking_links WHERE link_status='superseded'",
        ),
        "superseded_booking_target_links": scalar(
            db,
            "SELECT COUNT(*) FROM booking_target_links WHERE link_status='superseded'",
        ),
        "forbidden_sensitive_source_records": scalar(
            db,
            """
            SELECT COUNT(*) FROM source_records
            WHERE lower(raw_payload) LIKE '%"pin"%'
               OR lower(raw_payload) LIKE '%"password"%'
               OR lower(raw_payload) LIKE '%"birthdate"%'
               OR lower(raw_payload) LIKE '%"passport"%'
               OR raw_payload LIKE '%"생년월일"%'
               OR raw_payload LIKE '%"전화번호"%'
               OR raw_payload LIKE '%"여권"%'
            """,
        ),
    }
    report["valid"] = (
        report["transactions"] == report["active_allocations"]
        and report["transaction_total_krw"] == report["allocation_total_krw"]
        and report["allocation_mismatches"] == 0
        and report["missing_card_event_identities"] == 0
        and report["forbidden_sensitive_source_records"] == 0
    )
    return report


def review_report(db: sqlite3.Connection) -> dict[str, int]:
    """합계 오류가 아닌 분류 품질 문제를 검토 큐로 드러낸다."""
    engine_isolated_filter = """
        p.external_key LIKE 'MISC-%'
        AND NOT EXISTS (
            SELECT 1
            FROM transaction_relations relation
            WHERE relation.transaction_id=p.id
              AND relation.related_transaction_id IS NOT NULL
              AND relation.relation_status='confirmed'
              AND relation.match_method='hana_same_raw_row_approval_cancel'
        )
    """
    return {
        "unassigned_payments": scalar(
            db,
            """
            SELECT COUNT(DISTINCT a.payment_id)
            FROM current_cost_allocations a
            JOIN allocation_targets t ON t.id=a.target_id
            WHERE t.target_type='unassigned'
            """,
        ),
        "unassigned_amount_krw": scalar(
            db,
            """
            SELECT COALESCE(SUM(a.amount_krw), 0)
            FROM current_cost_allocations a
            JOIN allocation_targets t ON t.id=a.target_id
            WHERE t.target_type='unassigned'
            """,
        ),
        "engine_isolated_payments": scalar(
            db,
            f"""
            SELECT COUNT(*)
            FROM payment_transactions p
            WHERE {engine_isolated_filter}
            """,
        ),
        "engine_isolated_amount_krw": scalar(
            db,
            f"""
            SELECT COALESCE(SUM(p.amount_krw), 0)
            FROM payment_transactions p
            WHERE {engine_isolated_filter}
            """,
        ),
        "zero_amount_payments": scalar(
            db,
            "SELECT COUNT(*) FROM payment_transactions WHERE amount_krw=0",
        ),
        "unresolved_transaction_relations": scalar(
            db,
            """
            SELECT COUNT(*) FROM transaction_relations
            WHERE related_transaction_id IS NULL
              AND resolution_code IS NULL
              AND relation_status NOT IN ('rejected', 'superseded')
            """,
        ),
        "unknown_booking_providers": scalar(
            db,
            "SELECT COUNT(*) FROM bookings WHERE provider='unknown'",
        ),
        "bookings_linked_to_multiple_targets": scalar(
            db,
            """
            SELECT COUNT(*) FROM (
                SELECT booking_id
                FROM booking_target_links
                WHERE link_status NOT IN ('rejected', 'superseded')
                GROUP BY booking_id
                HAVING COUNT(DISTINCT target_id) > 1
            )
            """,
        ),
        "high_confidence_with_uncertain_rationale": scalar(
            db,
            """
            SELECT COUNT(DISTINCT target_id)
            FROM current_classification_decisions
            WHERE target_type='payment'
              AND confidence_label='상'
              AND (
                  rationale LIKE '%추정%'
                  OR rationale LIKE '%유사%'
                  OR rationale LIKE '%불명%'
                  OR rationale LIKE '%확인 필요%'
                  OR rationale LIKE '%검토요망%'
              )
            """,
        ),
        "low_confidence_payments": scalar(
            db,
            """
            SELECT COUNT(DISTINCT target_id)
            FROM current_classification_decisions
            WHERE target_type='payment' AND confidence <= 0.3
            """,
        ),
    }


PAYMENT_REVIEW_CONTEXT = """
WITH decision_context AS (
    SELECT
        target_id AS payment_id,
        GROUP_CONCAT(DISTINCT dimension || '=' || value) AS decision_values,
        GROUP_CONCAT(DISTINCT COALESCE(rule_id, '')) AS decision_rule_ids,
        GROUP_CONCAT(DISTINCT COALESCE(confidence_label, '')) AS decision_confidence_labels,
        MIN(confidence) AS decision_min_confidence,
        GROUP_CONCAT(DISTINCT COALESCE(rationale, '')) AS decision_rationales
    FROM current_classification_decisions
    WHERE target_type='payment'
    GROUP BY target_id
),
booking_context AS (
    SELECT
        pbl.payment_id,
        GROUP_CONCAT(DISTINCT b.booking_number) AS booking_numbers,
        GROUP_CONCAT(DISTINCT b.provider) AS booking_providers
    FROM payment_booking_links pbl
    JOIN bookings b ON b.id=pbl.booking_id
    WHERE pbl.link_status NOT IN ('rejected', 'superseded')
    GROUP BY pbl.payment_id
),
allocation_context AS (
    SELECT
        a.payment_id,
        GROUP_CONCAT(DISTINCT t.code) AS allocation_targets
    FROM current_cost_allocations a
    JOIN allocation_targets t ON t.id=a.target_id
    GROUP BY a.payment_id
)
"""


def _detail_row(row: sqlite3.Row, **overrides: object) -> dict[str, object]:
    values = {field: "" for field in REVIEW_DETAIL_FIELDS}
    for field in REVIEW_DETAIL_FIELDS:
        if field in row.keys() and row[field] is not None:
            values[field] = row[field]
    values.update(overrides)
    return values


def _payment_review_rows(
    db: sqlite3.Connection,
    predicate: str,
    review_amount_sql: str = "p.amount_krw",
) -> list[dict[str, object]]:
    rows = db.execute(
        PAYMENT_REVIEW_CONTEXT
        + f"""
        SELECT
            'payment' AS entity_type,
            p.external_key AS entity_key,
            p.external_key AS payment_external_key,
            p.occurred_on,
            p.merchant,
            p.amount_krw,
            {review_amount_sql} AS review_amount_krw,
            p.transaction_type,
            p.approval_number,
            bc.booking_numbers,
            bc.booking_providers,
            ac.allocation_targets,
            dc.decision_values,
            dc.decision_rule_ids,
            dc.decision_confidence_labels,
            dc.decision_min_confidence,
            dc.decision_rationales
        FROM payment_transactions p
        LEFT JOIN decision_context dc ON dc.payment_id=p.id
        LEFT JOIN booking_context bc ON bc.payment_id=p.id
        LEFT JOIN allocation_context ac ON ac.payment_id=p.id
        WHERE {predicate}
        ORDER BY p.external_key
        """
    ).fetchall()
    return [_detail_row(row) for row in rows]


def review_details(db: sqlite3.Connection) -> dict[str, list[dict[str, object]]]:
    """집계 리포트의 각 품질 지표를 행 단위 검토 큐로 반환한다."""
    engine_isolated_filter = """
        p.external_key LIKE 'MISC-%'
        AND NOT EXISTS (
            SELECT 1
            FROM transaction_relations relation
            WHERE relation.transaction_id=p.id
              AND relation.related_transaction_id IS NOT NULL
              AND relation.relation_status='confirmed'
              AND relation.match_method='hana_same_raw_row_approval_cancel'
        )
    """
    queues: dict[str, list[dict[str, object]]] = {
        "unassigned": _payment_review_rows(
            db,
            """
            EXISTS (
                SELECT 1
                FROM current_cost_allocations a
                JOIN allocation_targets t ON t.id=a.target_id
                WHERE a.payment_id=p.id AND t.target_type='unassigned'
            )
            """,
            """
            (
                SELECT COALESCE(SUM(a.amount_krw), 0)
                FROM current_cost_allocations a
                JOIN allocation_targets t ON t.id=a.target_id
                WHERE a.payment_id=p.id AND t.target_type='unassigned'
            )
            """,
        ),
        "engine_isolated": _payment_review_rows(db, engine_isolated_filter),
        "zero_amount": _payment_review_rows(db, "p.amount_krw=0"),
        "high_confidence_uncertain_rationale": _payment_review_rows(
            db,
            """
            EXISTS (
                SELECT 1
                FROM current_classification_decisions d
                WHERE d.target_type='payment'
                  AND d.target_id=p.id
                  AND d.confidence_label='상'
                  AND (
                      d.rationale LIKE '%추정%'
                      OR d.rationale LIKE '%유사%'
                      OR d.rationale LIKE '%불명%'
                      OR d.rationale LIKE '%확인 필요%'
                      OR d.rationale LIKE '%검토요망%'
                  )
            )
            """,
        ),
        "low_confidence": _payment_review_rows(
            db,
            """
            EXISTS (
                SELECT 1
                FROM current_classification_decisions d
                WHERE d.target_type='payment'
                  AND d.target_id=p.id
                  AND d.confidence <= 0.3
            )
            """,
        ),
    }

    relation_rows = db.execute(
        PAYMENT_REVIEW_CONTEXT
        + """
        SELECT
            'transaction_relation' AS entity_type,
            p.external_key || ':' || r.relation_type || ':' ||
                COALESCE(r.reference_value, '') AS entity_key,
            p.external_key AS payment_external_key,
            p.occurred_on,
            p.merchant,
            p.amount_krw,
            p.amount_krw AS review_amount_krw,
            p.transaction_type,
            p.approval_number,
            bc.booking_numbers,
            bc.booking_providers,
            ac.allocation_targets,
            dc.decision_values,
            dc.decision_rule_ids,
            dc.decision_confidence_labels,
            dc.decision_min_confidence,
            dc.decision_rationales,
            r.relation_type,
            r.reference_value AS relation_reference,
            r.match_method AS relation_match_method,
            r.confidence AS relation_confidence
        FROM transaction_relations r
        JOIN payment_transactions p ON p.id=r.transaction_id
        LEFT JOIN decision_context dc ON dc.payment_id=p.id
        LEFT JOIN booking_context bc ON bc.payment_id=p.id
        LEFT JOIN allocation_context ac ON ac.payment_id=p.id
        WHERE r.related_transaction_id IS NULL
          AND r.resolution_code IS NULL
          AND r.relation_status NOT IN ('rejected', 'superseded')
        ORDER BY r.id
        """
    ).fetchall()
    queues["unresolved_transaction_relations"] = [
        _detail_row(row) for row in relation_rows
    ]

    booking_rows = db.execute(
        """
        WITH payment_rows AS (
            SELECT DISTINCT
                pbl.booking_id,
                p.id AS payment_id,
                p.external_key,
                p.merchant,
                p.amount_krw
            FROM payment_booking_links pbl
            JOIN payment_transactions p ON p.id=pbl.payment_id
            WHERE pbl.link_status NOT IN ('rejected', 'superseded')
        ),
        payment_context AS (
            SELECT
                booking_id,
                GROUP_CONCAT(DISTINCT external_key) AS payment_external_keys,
                GROUP_CONCAT(DISTINCT merchant) AS merchants,
                COALESCE(SUM(amount_krw), 0) AS amount_krw
            FROM payment_rows
            GROUP BY booking_id
        ),
        decision_context AS (
            SELECT
                pbl.booking_id,
                GROUP_CONCAT(DISTINCT d.dimension || '=' || d.value) AS decision_values,
                GROUP_CONCAT(DISTINCT COALESCE(d.rule_id, '')) AS decision_rule_ids,
                GROUP_CONCAT(DISTINCT COALESCE(d.confidence_label, ''))
                    AS decision_confidence_labels,
                MIN(d.confidence) AS decision_min_confidence,
                GROUP_CONCAT(DISTINCT COALESCE(d.rationale, '')) AS decision_rationales
            FROM payment_booking_links pbl
            JOIN current_classification_decisions d
              ON d.target_type='payment' AND d.target_id=pbl.payment_id
            WHERE pbl.link_status NOT IN ('rejected', 'superseded')
            GROUP BY pbl.booking_id
        ),
        target_context AS (
            SELECT
                btl.booking_id,
                GROUP_CONCAT(DISTINCT t.code) AS allocation_targets
            FROM booking_target_links btl
            JOIN allocation_targets t ON t.id=btl.target_id
            WHERE btl.link_status NOT IN ('rejected', 'superseded')
            GROUP BY btl.booking_id
        )
        SELECT
            'booking' AS entity_type,
            b.provider || ':' || b.booking_number AS entity_key,
            pc.payment_external_keys AS payment_external_key,
            pc.merchants AS merchant,
            pc.amount_krw,
            pc.amount_krw AS review_amount_krw,
            b.booking_number AS booking_numbers,
            b.provider AS booking_providers,
            tc.allocation_targets,
            dc.decision_values,
            dc.decision_rule_ids,
            dc.decision_confidence_labels,
            dc.decision_min_confidence,
            dc.decision_rationales
        FROM bookings b
        LEFT JOIN payment_context pc ON pc.booking_id=b.id
        LEFT JOIN decision_context dc ON dc.booking_id=b.id
        LEFT JOIN target_context tc ON tc.booking_id=b.id
        WHERE b.provider='unknown'
        ORDER BY b.booking_number
        """
    ).fetchall()
    queues["unknown_booking_providers"] = [_detail_row(row) for row in booking_rows]

    multi_target_rows = db.execute(
        """
        WITH conflicted AS (
            SELECT booking_id
            FROM booking_target_links
            WHERE link_status NOT IN ('rejected', 'superseded')
            GROUP BY booking_id
            HAVING COUNT(DISTINCT target_id) > 1
        ),
        payment_rows AS (
            SELECT DISTINCT
                pbl.booking_id,
                p.id AS payment_id,
                p.external_key,
                p.merchant,
                p.amount_krw
            FROM payment_booking_links pbl
            JOIN payment_transactions p ON p.id=pbl.payment_id
            WHERE pbl.link_status NOT IN ('rejected', 'superseded')
        ),
        payment_context AS (
            SELECT
                booking_id,
                GROUP_CONCAT(DISTINCT external_key) AS payment_external_keys,
                GROUP_CONCAT(DISTINCT merchant) AS merchants,
                COALESCE(SUM(amount_krw), 0) AS amount_krw
            FROM payment_rows
            GROUP BY booking_id
        ),
        decision_context AS (
            SELECT
                pbl.booking_id,
                GROUP_CONCAT(DISTINCT d.dimension || '=' || d.value) AS decision_values,
                GROUP_CONCAT(DISTINCT COALESCE(d.rule_id, '')) AS decision_rule_ids,
                GROUP_CONCAT(DISTINCT COALESCE(d.confidence_label, ''))
                    AS decision_confidence_labels,
                MIN(d.confidence) AS decision_min_confidence,
                GROUP_CONCAT(DISTINCT COALESCE(d.rationale, '')) AS decision_rationales
            FROM payment_booking_links pbl
            JOIN current_classification_decisions d
              ON d.target_type='payment' AND d.target_id=pbl.payment_id
            WHERE pbl.link_status NOT IN ('rejected', 'superseded')
            GROUP BY pbl.booking_id
        ),
        target_context AS (
            SELECT
                btl.booking_id,
                GROUP_CONCAT(DISTINCT t.code) AS allocation_targets
            FROM booking_target_links btl
            JOIN allocation_targets t ON t.id=btl.target_id
            WHERE btl.link_status NOT IN ('rejected', 'superseded')
            GROUP BY btl.booking_id
        )
        SELECT
            'booking' AS entity_type,
            b.provider || ':' || b.booking_number AS entity_key,
            pc.payment_external_keys AS payment_external_key,
            pc.merchants AS merchant,
            pc.amount_krw,
            pc.amount_krw AS review_amount_krw,
            b.booking_number AS booking_numbers,
            b.provider AS booking_providers,
            tc.allocation_targets,
            dc.decision_values,
            dc.decision_rule_ids,
            dc.decision_confidence_labels,
            dc.decision_min_confidence,
            dc.decision_rationales
        FROM conflicted c
        JOIN bookings b ON b.id=c.booking_id
        LEFT JOIN payment_context pc ON pc.booking_id=b.id
        LEFT JOIN decision_context dc ON dc.booking_id=b.id
        LEFT JOIN target_context tc ON tc.booking_id=b.id
        ORDER BY b.provider, b.booking_number
        """
    ).fetchall()
    queues["bookings_linked_to_multiple_targets"] = [
        _detail_row(row) for row in multi_target_rows
    ]

    return {name: queues[name] for name in REVIEW_QUEUE_METRICS}


def regression_totals(db: sqlite3.Connection) -> dict[str, list[dict[str, object]]]:
    """legacy v14 이관값의 배분대상·여행·계정별 회귀 기준을 만든다."""
    targets = [
        dict(row)
        for row in db.execute(
            """
            SELECT
                t.code AS key,
                t.target_type AS type,
                COUNT(DISTINCT a.payment_id) AS payments,
                SUM(a.amount_krw) AS amount_krw
            FROM current_cost_allocations a
            JOIN allocation_targets t ON t.id=a.target_id
            GROUP BY t.id
            ORDER BY t.target_type, t.code
            """
        ).fetchall()
    ]
    trips = [
        dict(row)
        for row in db.execute(
            """
            SELECT
                t.code AS key,
                COUNT(DISTINCT a.payment_id) AS payments,
                SUM(a.amount_krw) AS amount_krw
            FROM current_cost_allocations a
            JOIN allocation_targets t ON t.id=a.target_id
            WHERE t.target_type='trip'
            GROUP BY t.id
            ORDER BY t.code
            """
        ).fetchall()
    ]
    accounts = [
        dict(row)
        for row in db.execute(
            """
            SELECT
                d.value AS key,
                COUNT(DISTINCT p.id) AS payments,
                SUM(p.amount_krw) AS amount_krw
            FROM current_classification_decisions d
            JOIN payment_transactions p ON p.id=d.target_id
            WHERE d.target_type='payment' AND d.dimension='expense_type'
            GROUP BY d.value
            ORDER BY d.value
            """
        ).fetchall()
    ]
    return {
        "allocation_targets": targets,
        "trips": trips,
        "accounts": accounts,
    }


def _snapshot_inputs(db: sqlite3.Connection) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in db.execute(
            """
            SELECT source_kind, path, sha256, imported_at
            FROM source_documents
            ORDER BY id
            """
        ).fetchall()
    ]


def build_review_snapshot(db: sqlite3.Connection) -> dict[str, object]:
    summary = review_report(db)
    queues = review_details(db)
    totals = regression_totals(db)
    inputs = _snapshot_inputs(db)
    queue_keys = {
        name: [str(row["entity_key"]) for row in rows]
        for name, rows in queues.items()
    }
    semantic_payload = {
        "rule_version": REVIEW_RULE_VERSION,
        "inputs": [
            {
                "source_kind": item["source_kind"],
                "sha256": item["sha256"],
            }
            for item in inputs
        ],
        "summary": summary,
        "regression_totals": totals,
        "queues": queues,
    }
    semantic_json = json.dumps(
        semantic_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "format_version": 1,
        "rule_version": REVIEW_RULE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantic_sha256": hashlib.sha256(semantic_json.encode("utf-8")).hexdigest(),
        "inputs": inputs,
        "summary": summary,
        "regression_totals": totals,
        "queue_keys": queue_keys,
        "queues": queues,
    }


def compare_review_snapshots(
    current: dict[str, object],
    previous_manifest: dict[str, object],
) -> dict[str, object]:
    current_keys = current["queue_keys"]
    previous_keys = previous_manifest.get("queue_keys", {})
    queue_names = sorted(set(current_keys) | set(previous_keys))
    queues: dict[str, dict[str, object]] = {}
    for name in queue_names:
        now = set(current_keys.get(name, []))
        before = set(previous_keys.get(name, []))
        added = sorted(now - before)
        resolved = sorted(before - now)
        remaining = sorted(now & before)
        queues[name] = {
            "added_count": len(added),
            "added": added,
            "resolved_count": len(resolved),
            "resolved": resolved,
            "remaining_count": len(remaining),
            "remaining": remaining,
        }
    return {
        "previous_semantic_sha256": previous_manifest.get("semantic_sha256"),
        "current_semantic_sha256": current["semantic_sha256"],
        "unchanged": (
            previous_manifest.get("semantic_sha256") == current["semantic_sha256"]
        ),
        "queues": queues,
    }


def _load_snapshot_manifest(path: Path) -> dict[str, object]:
    manifest_path = path / "manifest.json" if path.is_dir() else path
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def write_review_snapshot(
    db: sqlite3.Connection,
    output_dir: Path,
    compare_to: Path | None = None,
) -> dict[str, object]:
    snapshot = build_review_snapshot(db)
    output_dir.mkdir(parents=True, exist_ok=True)
    queues_dir = output_dir / "queues"
    queues_dir.mkdir(parents=True, exist_ok=True)

    for name, rows in snapshot["queues"].items():
        with (queues_dir / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=REVIEW_DETAIL_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    manifest = {key: value for key, value in snapshot.items() if key != "queues"}
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(snapshot["summary"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "regression_totals.json").write_text(
        json.dumps(snapshot["regression_totals"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    diff = None
    if compare_to is not None:
        diff = compare_review_snapshots(snapshot, _load_snapshot_manifest(compare_to))
        (output_dir / "diff.json").write_text(
            json.dumps(diff, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    diff_summary = None
    if diff is not None:
        diff_summary = {
            "unchanged": diff["unchanged"],
            "queues": {
                name: {
                    "added_count": values["added_count"],
                    "resolved_count": values["resolved_count"],
                    "remaining_count": values["remaining_count"],
                }
                for name, values in diff["queues"].items()
            },
        }
    return {
        "output_dir": str(output_dir),
        "semantic_sha256": snapshot["semantic_sha256"],
        "summary": snapshot["summary"],
        "diff": diff_summary,
    }


def apply_p1_confidence_rules(db: sqlite3.Connection) -> dict[str, int]:
    """상 신뢰도와 불확실 문구가 충돌하는 legacy 판정을 버전으로 정리한다."""
    rows = db.execute(
        """
        SELECT d.*, p.external_key, p.merchant
        FROM current_classification_decisions d
        JOIN payment_transactions p
          ON d.target_type='payment' AND d.target_id=p.id
        WHERE d.confidence >= 0.9
          AND (
              d.rationale LIKE '%추정%'
              OR d.rationale LIKE '%유사%'
              OR d.rationale LIKE '%불명%'
              OR d.rationale LIKE '%확인 필요%'
              OR d.rationale LIKE '%확인要%'
              OR (
                  d.rule_id='legacy_v14_import'
                  AND d.dimension IN (
                      'allocation_target', 'expense_type', 'cost_nature',
                      'period_recognition'
                  )
              )
          )
        ORDER BY d.target_id, d.dimension
        """
    ).fetchall()
    confirmed_payments: set[int] = set()
    downgraded_payments: set[int] = set()
    unverified_booking_payments = {
        int(row[0])
        for row in db.execute(
            """
            SELECT target_id
            FROM current_classification_decisions
            WHERE target_type='payment'
              AND dimension='booking_reference_status'
              AND value='unverified_booking_ref'
            """
        ).fetchall()
    }
    # Legacy rationale text (including "Gmail confirmed", titles and booking
    # numbers) is not evidence by itself.  Only a persisted, direct-evidence
    # match group with all four verification dimensions may retain a strong
    # travel classification through this cleanup pass.
    structurally_verified_payments: set[int] = set()
    strong_groups = db.execute(
        "SELECT id FROM match_groups WHERE status='confirmed_strong'"
    ).fetchall()
    for group in strong_groups:
        group_id = int(group["id"])
        payment_rows = db.execute(
            """
            SELECT p.id, p.source_event_id
            FROM match_group_payments gp
            JOIN payment_transactions p ON p.id=gp.payment_id
            WHERE gp.group_id=?
            """,
            (group_id,),
        ).fetchall()
        signal_rows = []
        for signal in db.execute(
            """
            SELECT signal_name, signal_status, left_value, right_value,
                   source_event_id, evidence_json
            FROM match_signal_results WHERE group_id=?
            """,
            (group_id,),
        ).fetchall():
            try:
                evidence = json.loads(str(signal["evidence_json"] or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                evidence = []
            signal_rows.append(
                {
                    "name": signal["signal_name"],
                    "status": signal["signal_status"],
                    "left": signal["left_value"],
                    "right": signal["right_value"],
                    "source_event_id": signal["source_event_id"],
                    "evidence": evidence,
                }
            )
        dimensions = verification_dimensions(
            card_source_event_ids=[row["source_event_id"] for row in payment_rows],
            signal_rows=signal_rows,
        )
        if dimensions["strong_travel_classification_ready"]:
            structurally_verified_payments.update(int(row["id"]) for row in payment_rows)
    changed = 0
    with db:
        for row in rows:
            rationale = str(row["rationale"] or "")
            # Regex matches are retained in the rationale for review but are
            # never sufficient to promote a classification.  In particular,
            # a title keyword or booking_info value cannot create OTA/travel
            # or period verification.
            requires_direct_ota = _legacy_ota_or_pg_requires_direct_evidence(row)
            if not requires_direct_ota and not UNCERTAIN_RATIONALE_RE.search(rationale):
                # The query includes every high-confidence legacy
                # classification dimension so OTA/PG conclusions can be
                # gated.  Other legacy conclusions remain untouched here
                # unless they already meet the uncertainty-cleanup rule.
                continue
            matched_rules = (
                ["direct_card+ota+travel+period"]
                if (
                    requires_direct_ota
                    and int(row["target_id"]) in structurally_verified_payments
                )
                else []
            )
            if int(row["target_id"]) in unverified_booking_payments:
                # A booking number that appears only in a note cannot turn a
                # tentative rationale into a strong confirmation.  The
                # dedicated status is written during import before P1 runs.
                matched_rules = []
            if matched_rules:
                confidence = 1.0
                confidence_label = "상"
                status = "confirmed"
                rule_id = "p1:" + "+".join(matched_rules)
                new_rationale = (
                    "구조화 확정근거: "
                    + ", ".join(matched_rules)
                    + f" | legacy 결제키 {row['external_key']}"
                )
                confirmed_payments.add(int(row["target_id"]))
            else:
                confidence = 0.7
                confidence_label = "중"
                status = "needs_review"
                rule_id = "p1:uncertain_rationale_downgrade"
                new_rationale = (
                    "자동확정 허용조건 미충족; legacy 근거 재검토 필요 | "
                    + rationale
                )
                downgraded_payments.add(int(row["target_id"]))
            replace_decision(
                db,
                "payment",
                int(row["target_id"]),
                str(row["dimension"]),
                str(row["value"]),
                confidence,
                confidence_label,
                new_rationale,
                None,
                decision_status=status,
                rule_id=rule_id,
            )
            changed += 1
    return {
        "candidate_decisions": len(rows),
        "changed_decisions": changed,
        "confirmed_payments": len(confirmed_payments),
        "downgraded_payments": len(downgraded_payments),
        "remaining_high_confidence_uncertain": review_report(db)[
            "high_confidence_with_uncertain_rationale"
        ],
    }


def resolve_hana_split_cancellations(db: sqlite3.Connection) -> dict[str, int]:
    """하나 RAW 한 행이 legacy에서 `0원 원행 + 음수 MISC`로 갈라진 경우를 복원한다.

    원행은 승인금액의 purchase, MISC 행은 같은 승인번호의 cancellation으로 보존하고
    두 행을 명시적으로 연결한다. 기존 버전과 미연결 관계는 삭제하지 않고 supersede한다.
    """
    pairs = db.execute(
        """
        SELECT
            original.id AS original_id,
            original.external_key AS original_key,
            refund.id AS refund_id,
            refund.external_key AS refund_key,
            refund.amount_krw AS refund_amount,
            original.approval_number,
            allocation.target_id,
            CASE
              WHEN allocation.booking_id IS NOT NULL
               AND EXISTS (
                    SELECT 1
                    FROM current_payment_booking_links booking_link
                    WHERE booking_link.payment_id=original.id
                      AND booking_link.booking_id=allocation.booking_id
                      AND booking_link.link_status='confirmed'
               )
              THEN allocation.booking_id
              ELSE NULL
            END AS booking_id,
            decision.id AS allocation_decision_id,
            decision.value AS allocation_code
        FROM payment_transactions original
        JOIN payment_transactions refund
          ON refund.source_system='HAN'
         AND original.source_system='HAN'
         AND refund.approval_number=original.approval_number
         AND refund.id<>original.id
         AND refund.amount_krw < 0
        JOIN current_cost_allocations allocation
          ON allocation.payment_id=original.id
        JOIN current_classification_decisions decision
          ON decision.target_type='payment'
         AND decision.target_id=original.id
         AND decision.dimension='allocation_target'
         AND decision.decision_status='confirmed'
        WHERE original.amount_krw=0
          AND original.approval_number IS NOT NULL
          AND original.approval_number<>''
          AND refund.external_key LIKE 'MISC-%'
        ORDER BY original.id
        """
    ).fetchall()
    resolved = 0
    with db:
        for pair in pairs:
            original_id = int(pair["original_id"])
            refund_id = int(pair["refund_id"])
            approval_amount = abs(int(pair["refund_amount"]))
            latest_source = int(
                db.execute(
                    """
                    SELECT source_record_id
                    FROM payment_transaction_versions
                    WHERE transaction_id=?
                    ORDER BY record_version DESC LIMIT 1
                    """,
                    (original_id,),
                ).fetchone()[0]
            )
            db.execute(
                """
                UPDATE payment_transactions
                SET amount_krw=?, transaction_type='purchase',
                    record_version=record_version+1,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (approval_amount, original_id),
            )
            db.execute(
                """
                INSERT INTO payment_transaction_versions(
                    transaction_id, record_version, source_record_id,
                    source_event_id, identity_fingerprint,
                    payment_method_id, source_system, occurred_on, posted_on,
                    merchant, business_category, country, currency,
                    foreign_amount, amount_krw, approval_number,
                    transaction_type
                )
                SELECT
                    id, record_version, ?, source_event_id, identity_fingerprint,
                    payment_method_id, source_system, occurred_on, posted_on,
                    merchant, business_category, country, currency,
                    foreign_amount, amount_krw, approval_number,
                    transaction_type
                FROM payment_transactions WHERE id=?
                """,
                (latest_source, original_id),
            )

            replace_allocation_plan(
                db,
                original_id,
                [
                    AllocationItem(
                        target_id=int(pair["target_id"]),
                        amount_krw=approval_amount,
                        booking_id=(
                            int(pair["booking_id"])
                            if pair["booking_id"] is not None
                            else None
                        ),
                    )
                ],
                status="confirmed",
                confidence=1.0,
                source_decision_id=int(pair["allocation_decision_id"]),
            )
            refund_decision = replace_decision(
                db,
                "payment",
                refund_id,
                "allocation_target",
                str(pair["allocation_code"]),
                1.0,
                "상",
                "하나카드 RAW 동일 행·동일 승인번호의 승인취소금액",
                None,
                decision_status="confirmed",
                rule_id="p2:hana_same_row_approval_cancellation",
            )
            original_dimensions = db.execute(
                """
                SELECT dimension, value
                FROM current_classification_decisions
                WHERE target_type='payment'
                  AND target_id=?
                  AND decision_status='confirmed'
                  AND dimension IN (
                      'expense_type', 'cost_nature', 'vat_treatment'
                  )
                """,
                (original_id,),
            ).fetchall()
            for dimension in original_dimensions:
                replace_decision(
                    db,
                    "payment",
                    refund_id,
                    str(dimension["dimension"]),
                    str(dimension["value"]),
                    1.0,
                    "상",
                    "하나카드 동일 RAW 행의 승인 거래 분류를 취소 이벤트에 승계",
                    None,
                    decision_status="confirmed",
                    rule_id="p2:hana_same_row_approval_cancellation",
                )
            replace_allocation_plan(
                db,
                refund_id,
                [
                    AllocationItem(
                        target_id=int(pair["target_id"]),
                        amount_krw=int(pair["refund_amount"]),
                        booking_id=(
                            int(pair["booking_id"])
                            if pair["booking_id"] is not None
                            else None
                        ),
                    )
                ],
                status="confirmed",
                confidence=1.0,
                source_decision_id=refund_decision,
            )
            db.execute(
                """
                UPDATE transaction_relations
                SET relation_status='superseded',
                    resolution_code='superseded_by_hana_raw_pair',
                    rationale='하나카드 RAW 동일 행 구조로 재연결'
                WHERE transaction_id=?
                  AND related_transaction_id IS NULL
                  AND relation_status NOT IN ('rejected', 'superseded')
                """,
                (refund_id,),
            )
            reference = f"hana:{pair['approval_number']}:same-row"
            db.execute(
                """
                INSERT INTO transaction_relations(
                    transaction_id, related_transaction_id, relation_type,
                    reference_value, match_method, confidence, relation_status,
                    resolution_code, rationale
                ) VALUES (?, ?, 'cancels', ?,
                          'hana_same_raw_row_approval_cancel', 1.0, 'confirmed',
                          'original_linked',
                          '하나카드 동일 RAW 행의 승인금액과 승인취소금액')
                ON CONFLICT(transaction_id, relation_type, reference_value)
                DO UPDATE SET
                    related_transaction_id=excluded.related_transaction_id,
                    match_method=excluded.match_method,
                    confidence=excluded.confidence,
                    relation_status='confirmed',
                    resolution_code='original_linked',
                    rationale=excluded.rationale,
                    superseded_by_document_id=NULL
                """,
                (refund_id, original_id, reference),
            )
            resolved += 1
    return {
        "resolved_pairs": resolved,
        "remaining_hana_split_candidates": scalar(
            db,
            """
            SELECT COUNT(*)
            FROM payment_transactions original
            JOIN payment_transactions refund
              ON refund.source_system='HAN'
             AND original.source_system='HAN'
             AND refund.approval_number=original.approval_number
             AND refund.amount_krw<0
             AND refund.external_key LIKE 'MISC-%'
            WHERE original.amount_krw=0
            """,
        ),
    }


def apply_p3_unassigned_review(db: sqlite3.Connection) -> dict[str, int]:
    """미배정 결제를 삭제 없이 네 가지 검토 결과로 설명하고 확정 건만 재배분한다."""
    # These are not amount-only guesses.  Each rule is backed by the card
    # event's approval identity plus the corresponding manual-ledger row (or,
    # for GYOMU, the same KBO raw event already allocated to Myoko).  Keeping
    # the authority here makes a fresh rebuild reach the same result without
    # relying on a previously generated workbook/CSV projection.
    automatic_assignments = {
        "KBD-0403": {
            "outcome": "overhead",
            "target": "기타비용",
            "target_type": "overhead",
            "expense_type": "주차비",
            "cost_nature": "판관비",
            "vat_treatment": "미정",
            "rule": "p3:3820_parking_outside_trip",
            "rationale": "3820 국내 주차 2,400원은 여행기간 밖이며 수기 2,400원은 다른 가맹점 거래로 정매칭되어 있다.",
        },
        "MISC-0001": {
            "outcome": "trip",
            "target": "0620_묘코",
            "target_type": "trip",
            "expense_type": "기타비용",
            "cost_nature": "여행원가",
            "vat_treatment": "불공제_해외",
            "rule": "p3:gyomu_same_kbo_event",
            "rationale": "GYOMU SUPA 쓰루오카 결제는 동일 국민 원천 KBO-0367과 일치하는 묘코 현지 식재료·소모품 거래다.",
        },
        "MISC-0006": {
            "outcome": "trip",
            "target": "5월_유럽",
            "target_type": "trip",
            "expense_type": "렌터카",
            "cost_nature": "여행원가",
            "vat_treatment": "불공제_해외",
            "rule": "p3:avis_manual_approval_match",
            "rationale": "AVIS 366,794원은 동일 승인번호·가맹점의 5월 유럽 수기 렌터카 행과 일치하는 현지 추가정산이다.",
        },
        "MISC-0010": {
            "outcome": "trip",
            "target": "5월_유럽",
            "target_type": "trip",
            "expense_type": "렌터카",
            "cost_nature": "여행원가",
            "vat_treatment": "불공제_해외",
            "rule": "p3:sicily_manual_approval_match",
            "rationale": "SICILY BY CAR 584,193원은 동일 승인번호·가맹점의 5월 유럽 수기 렌터카 행과 일치한다.",
        },
        "MISC-0011": {
            "outcome": "trip",
            "target": "5월_유럽",
            "target_type": "trip",
            "expense_type": "렌터카",
            "cost_nature": "여행원가",
            "vat_treatment": "불공제_해외",
            "rule": "p3:hertz_manual_approval_match",
            "rationale": "HERTZ 543,947원은 동일 승인번호·가맹점의 5월 유럽 수기 렌터카 행과 일치한다.",
        },
    }
    cancellation_clearings = {
        "CORP-2005": "기업카드 승인취소로 실청구가 0원인 조정 이벤트다.",
        "MISC-0003": "LOONG AGE 원거래는 2026-05-11 전액 리버설된 카드 이벤트다.",
        "MISC-0005": "카카오T 가승인과 동일 승인번호의 승인취소가 완전상쇄된다.",
        "MISC-0007": "TOTAL Marseille 승인과 동일 승인번호의 승인취소가 완전상쇄된다.",
        "MISC-0008": "RESIDHOTEL 승인과 동일 승인번호의 승인취소가 완전상쇄된다.",
        "MISC-0009": "AVIS Marseille 승인과 동일 승인번호의 승인취소가 완전상쇄된다.",
    }
    rows = db.execute(
        """
        SELECT
            p.id, p.external_key, p.amount_krw, p.transaction_type,
            p.occurred_on, p.merchant,
            COALESCE(i.identity_status, '') AS identity_status
        FROM current_cost_allocations a
        JOIN allocation_targets t ON t.id=a.target_id
        JOIN payment_transactions p ON p.id=a.payment_id
        LEFT JOIN card_event_identities i ON i.transaction_id=p.id
        WHERE t.target_type='unassigned'
        ORDER BY p.external_key
        """
    ).fetchall()
    counts: dict[str, int] = {
        "trip": 0,
        "overhead": 0,
        "cancellation_settlement": 0,
        "insufficient_evidence": 0,
    }
    with db:
        for row in rows:
            payment_id = int(row["id"])
            external_key = str(row["external_key"])
            assignment = automatic_assignments.get(external_key)
            if assignment:
                outcome = str(assignment["outcome"])
                reason_code = str(assignment["rule"]).split(":", 1)[1]
                rationale = str(assignment["rationale"])
                review_status = "confirmed"
                target_id = ensure_target(
                    db, str(assignment["target"]), str(assignment["target_type"])
                )
                decision_id = replace_decision(
                    db,
                    "payment",
                    payment_id,
                    "allocation_target",
                    str(assignment["target"]),
                    1.0,
                    "상",
                    rationale,
                    None,
                    decision_status="confirmed",
                    rule_id=str(assignment["rule"]),
                )
                for dimension in ("expense_type", "cost_nature", "vat_treatment"):
                    replace_decision(
                        db,
                        "payment",
                        payment_id,
                        dimension,
                        str(assignment[dimension]),
                        1.0,
                        "상",
                        rationale,
                        None,
                        decision_status="confirmed",
                        rule_id=str(assignment["rule"]),
                    )
                replace_allocation_plan(
                    db,
                    payment_id,
                    [AllocationItem(target_id=target_id, amount_krw=int(row["amount_krw"]))],
                    status="confirmed",
                    confidence=1.0,
                    source_decision_id=decision_id,
                )
            elif external_key in cancellation_clearings:
                outcome = "cancellation_settlement"
                reason_code = "confirmed_card_cancellation_clearing"
                rationale = cancellation_clearings[external_key]
                review_status = "confirmed"
                target_id = ensure_target(db, "취소환불_정산", "clearing")
                decision_id = replace_decision(
                    db, "payment", payment_id, "allocation_target", "취소환불_정산",
                    1.0, "상", rationale, None, decision_status="confirmed",
                    rule_id="p3:confirmed_card_cancellation_clearing",
                )
                replace_allocation_plan(
                    db,
                    payment_id,
                    [AllocationItem(target_id=target_id, amount_krw=int(row["amount_krw"]))],
                    status="confirmed",
                    confidence=1.0,
                    source_decision_id=decision_id,
                )
                counterpart = db.execute(
                    """
                    SELECT id FROM payment_transactions
                    WHERE approval_number IS NOT NULL
                      AND approval_number<>''
                      AND approval_number=(
                          SELECT approval_number FROM payment_transactions WHERE id=?
                      )
                      AND id<>?
                      AND external_key NOT LIKE 'MISC-%'
                    ORDER BY ABS(amount_krw) DESC, id
                    LIMIT 1
                    """,
                    (payment_id, payment_id),
                ).fetchone()
                db.execute(
                    """
                    INSERT INTO transaction_relations(
                        transaction_id, related_transaction_id, relation_type,
                        reference_value, match_method, confidence, relation_status,
                        resolution_code, rationale
                    ) VALUES (?, ?, 'cancels', ?,
                              'p3_confirmed_cancellation_clearing', 1.0, 'confirmed',
                              'clearing_only_no_expense', ?)
                    ON CONFLICT(transaction_id, relation_type, reference_value)
                    DO UPDATE SET
                        related_transaction_id=excluded.related_transaction_id,
                        match_method=excluded.match_method,
                        confidence=excluded.confidence,
                        relation_status='confirmed',
                        resolution_code=excluded.resolution_code,
                        rationale=excluded.rationale
                    """,
                    (
                        payment_id,
                        int(counterpart["id"]) if counterpart else None,
                        f"p3-clearing:{external_key}",
                        rationale,
                    ),
                )
            elif (
                int(row["amount_krw"]) <= 0
                or str(row["identity_status"]) == "collision"
            ):
                outcome = "cancellation_settlement"
                reason_code = (
                    "legacy_duplicate_card_representation"
                    if str(row["identity_status"]) == "collision"
                    else "refund_or_zero_adjustment"
                )
                rationale = (
                    "동일 카드 이벤트의 legacy 이중표현으로 P6 원천 통합 대기"
                    if str(row["identity_status"]) == "collision"
                    else "음수 환불 또는 0원 승인조정으로 여행 자동귀속 금지"
                )
                review_status = "needs_review"
            else:
                outcome = "insufficient_evidence"
                reason_code = "booking_or_business_purpose_missing"
                rationale = (
                    "예약번호·서비스기간 또는 판관비 용도를 확정할 근거가 부족하여 "
                    "미배정 유지"
                )
                review_status = "needs_review"
            db.execute(
                """
                INSERT INTO allocation_review_cases(
                    payment_id, outcome, reason_code, rationale,
                    review_status, rule_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(payment_id) DO UPDATE SET
                    outcome=excluded.outcome,
                    reason_code=excluded.reason_code,
                    rationale=excluded.rationale,
                    review_status=excluded.review_status,
                    rule_id=excluded.rule_id,
                    reviewed_at=CURRENT_TIMESTAMP
                """,
                (
                    payment_id,
                    outcome,
                    reason_code,
                    rationale,
                    review_status,
                    f"p3:{reason_code}",
                ),
            )
            counts[outcome] += 1
    unexplained = scalar(
        db,
        """
        SELECT COUNT(*)
        FROM current_cost_allocations a
        JOIN allocation_targets t ON t.id=a.target_id
        LEFT JOIN allocation_review_cases r ON r.payment_id=a.payment_id
        WHERE t.target_type='unassigned' AND r.payment_id IS NULL
        """,
    )
    return {
        "reviewed": len(rows),
        **counts,
        "remaining_unassigned": review_report(db)["unassigned_payments"],
        "unexplained_unassigned": unexplained,
    }


def apply_p4_provider_rules(db: sqlite3.Connection) -> dict[str, int]:
    """예약번호 형식은 보조근거로만 쓰고 가맹점 실증이 있는 공급자만 확정한다."""
    rows = db.execute(
        """
        SELECT
            b.id, b.booking_number,
            COALESCE(GROUP_CONCAT(DISTINCT p.merchant), '') AS merchants
        FROM bookings b
        LEFT JOIN current_payment_booking_links l ON l.booking_id=b.id
        LEFT JOIN payment_transactions p ON p.id=l.payment_id
        WHERE b.provider='unknown'
        GROUP BY b.id
        ORDER BY b.id
        """
    ).fetchall()
    confirmed = 0
    proposed = 0
    with db:
        for row in rows:
            booking_id = int(row["id"])
            number = str(row["booking_number"])
            merchants = str(row["merchants"] or "")
            upper = merchants.upper()
            provider = "unknown"
            status = "needs_review"
            reason = "insufficient_provider_evidence"
            rationale = "번호 형식만으로 Agoda와 Booking.com 등을 단정하지 않음"
            if "AGODA" in upper or "아고다" in merchants:
                provider, status = "agoda", "confirmed"
                reason = "merchant_provider_evidence"
                rationale = "연결 결제 가맹점에 Agoda/아고다 명시"
            elif "BOOKING.COM" in upper or "부킹" in merchants:
                provider, status = "booking.com", "confirmed"
                reason = "merchant_provider_evidence"
                rationale = "연결 결제 가맹점에 Booking.com/부킹 명시"
            elif "TRIP.COM" in upper or "트립닷컴" in merchants:
                provider, status = "trip.com", "confirmed"
                reason = "merchant_provider_evidence"
                rationale = "연결 결제 가맹점에 Trip.com/트립닷컴 명시"
            elif "TRAVELOKA" in upper:
                provider, status = "traveloka", "confirmed"
                reason = "merchant_provider_evidence"
                rationale = "연결 결제 가맹점에 Traveloka 명시"
            elif "아시아나" in merchants:
                provider, status = "asiana", "confirmed"
                reason = "merchant_provider_evidence"
                rationale = "연결 결제 가맹점에 아시아나 명시"
            elif "이스타항공" in merchants:
                provider, status = "eastar", "confirmed"
                reason = "merchant_provider_evidence"
                rationale = "연결 결제 가맹점에 이스타항공 명시"
            elif re.fullmatch(r"20\d{16}", number):
                provider = "domestic_reference"
                reason = "domestic_long_reference_format"
                rationale = "국내 결제/예약 참조번호 형식이며 OTA 예약번호로 확정하지 않음"

            identifier_status = "confirmed" if status == "confirmed" else "proposed"
            db.execute(
                """
                INSERT INTO booking_identifiers(
                    booking_id, provider, identifier, identifier_type,
                    identifier_status, rule_id
                ) VALUES (?, ?, ?, 'booking_number', ?, ?)
                ON CONFLICT(booking_id, provider, identifier, identifier_type)
                DO UPDATE SET
                    identifier_status=excluded.identifier_status,
                    rule_id=excluded.rule_id
                """,
                (
                    booking_id,
                    provider,
                    number,
                    identifier_status,
                    f"p4:{reason}",
                ),
            )
            if status == "confirmed":
                conflict = db.execute(
                    """
                    SELECT id FROM bookings
                    WHERE provider=? AND booking_number=? AND id<>?
                    """,
                    (provider, number, booking_id),
                ).fetchone()
                if conflict is None:
                    db.execute(
                        "UPDATE bookings SET provider=? WHERE id=?",
                        (provider, booking_id),
                    )
                    confirmed += 1
                else:
                    status = "needs_review"
                    reason = "provider_identifier_conflict"
                    rationale = "같은 공급자·예약번호 객체가 이미 있어 자동 병합을 중단"
                    proposed += 1
            else:
                proposed += 1
            db.execute(
                """
                INSERT INTO booking_provider_reviews(
                    booking_id, proposed_provider, review_status,
                    reason_code, rationale, rule_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(booking_id) DO UPDATE SET
                    proposed_provider=excluded.proposed_provider,
                    review_status=excluded.review_status,
                    reason_code=excluded.reason_code,
                    rationale=excluded.rationale,
                    rule_id=excluded.rule_id,
                    reviewed_at=CURRENT_TIMESTAMP
                """,
                (
                    booking_id,
                    provider,
                    status,
                    reason,
                    rationale,
                    f"p4:{reason}",
                ),
            )
    unknown_without_reason = scalar(
        db,
        """
        SELECT COUNT(*)
        FROM bookings b
        LEFT JOIN booking_provider_reviews r ON r.booking_id=b.id
        WHERE b.provider='unknown' AND r.booking_id IS NULL
        """,
    )
    return {
        "reviewed": len(rows),
        "confirmed": confirmed,
        "proposed_or_needs_review": proposed,
        "remaining_unknown": scalar(
            db, "SELECT COUNT(*) FROM bookings WHERE provider='unknown'"
        ),
        "unknown_without_reason": unknown_without_reason,
    }


def apply_p5_quality_audit(db: sqlite3.Connection) -> dict[str, int]:
    """저신뢰와 0원 거래의 비용인식·자동전기 가능 여부를 명시한다."""
    low_rows = db.execute(
        """
        SELECT DISTINCT p.id, p.external_key
        FROM current_classification_decisions d
        JOIN payment_transactions p
          ON d.target_type='payment' AND d.target_id=p.id
        WHERE d.confidence <= 0.3
        ORDER BY p.id
        """
    ).fetchall()
    categories: dict[str, int] = {}
    with db:
        for row in low_rows:
            payment_id = int(row["id"])
            unassigned = scalar(
                db,
                """
                SELECT COUNT(*)
                FROM current_cost_allocations a
                JOIN allocation_targets t ON t.id=a.target_id
                WHERE a.payment_id=? AND t.target_type='unassigned'
                """,
                (payment_id,),
            )
            unknown_booking = scalar(
                db,
                """
                SELECT COUNT(*)
                FROM current_payment_booking_links l
                JOIN bookings b ON b.id=l.booking_id
                WHERE l.payment_id=? AND b.provider='unknown'
                """,
                (payment_id,),
            )
            uncertain_account = scalar(
                db,
                """
                SELECT COUNT(*)
                FROM current_classification_decisions
                WHERE target_type='payment' AND target_id=?
                  AND dimension='expense_type'
                  AND value IN ('미정', '기타비용')
                """,
                (payment_id,),
            )
            if unassigned:
                category = "travel_unconfirmed"
            elif unknown_booking:
                category = "booking_unconfirmed"
            elif uncertain_account:
                category = "account_unconfirmed"
            else:
                category = "evidence_unconfirmed"
            categories[category] = categories.get(category, 0) + 1
            db.execute(
                """
                INSERT INTO payment_quality_audits(
                    payment_id, audit_type, category, rationale,
                    recognition_amount_krw, posting_eligibility,
                    audit_status, rule_id
                ) VALUES (?, 'low_confidence', ?, ?,
                          NULL, 'blocked', 'needs_review', ?)
                ON CONFLICT(payment_id, audit_type) DO UPDATE SET
                    category=excluded.category,
                    rationale=excluded.rationale,
                    recognition_amount_krw=excluded.recognition_amount_krw,
                    posting_eligibility=excluded.posting_eligibility,
                    audit_status=excluded.audit_status,
                    rule_id=excluded.rule_id,
                    audited_at=CURRENT_TIMESTAMP
                """,
                (
                    payment_id,
                    category,
                    "확정 근거가 추가될 때까지 자동전기 차단",
                    f"p5:{category}",
                ),
            )

        zero_rows = db.execute(
            """
            SELECT p.id, p.external_key, p.transaction_type,
                   COALESCE(i.identity_status, '') AS identity_status
            FROM payment_transactions p
            LEFT JOIN card_event_identities i ON i.transaction_id=p.id
            WHERE p.amount_krw=0
            ORDER BY p.id
            """
        ).fetchall()
        for row in zero_rows:
            if str(row["identity_status"]) == "collision":
                category = "split_cancellation_amount"
                rationale = (
                    "같은 카드 이벤트의 음수 결제행에 취소금액이 있으며 이 0원 표현의 "
                    "비용인식액은 0원"
                )
            else:
                category = "cancelled_authorization"
                rationale = "승인취소/매출취소 상태의 0원 이벤트로 비용인식액 0원"
            db.execute(
                """
                INSERT INTO payment_quality_audits(
                    payment_id, audit_type, category, rationale,
                    recognition_amount_krw, posting_eligibility,
                    audit_status, rule_id
                ) VALUES (?, 'zero_amount', ?, ?, 0,
                          'not_applicable', 'confirmed', ?)
                ON CONFLICT(payment_id, audit_type) DO UPDATE SET
                    category=excluded.category,
                    rationale=excluded.rationale,
                    recognition_amount_krw=excluded.recognition_amount_krw,
                    posting_eligibility=excluded.posting_eligibility,
                    audit_status=excluded.audit_status,
                    rule_id=excluded.rule_id,
                    audited_at=CURRENT_TIMESTAMP
                """,
                (int(row["id"]), category, rationale, f"p5:{category}"),
            )

    confirmed_low = scalar(
        db,
        """
        SELECT COUNT(DISTINCT d.target_id)
        FROM current_classification_decisions d
        WHERE d.target_type='payment'
          AND d.decision_status='confirmed'
          AND d.confidence <= 0.3
        """,
    )
    return {
        "low_confidence_reviewed": len(low_rows),
        "zero_amount_reviewed": len(zero_rows),
        "blocked_low_confidence": scalar(
            db,
            """
            SELECT COUNT(*) FROM payment_quality_audits
            WHERE audit_type='low_confidence' AND posting_eligibility='blocked'
            """,
        ),
        "confirmed_low_confidence": confirmed_low,
        **{f"low_{key}": value for key, value in sorted(categories.items())},
    }


def rebuild_database(
    destination: Path,
    csv_path: Path = DEFAULT_CSV,
    trips_path: Path = DEFAULT_TRIPS,
    bookings_path: Path = DEFAULT_BOOKINGS,
    change_log: Path | None = None,
) -> dict[str, object]:
    """Atomically rebuild the projection DB from immutable inputs and changes."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256(
        f"{destination}:{datetime.now(timezone.utc).isoformat()}".encode("utf-8")
    ).hexdigest()[:12]
    temporary = destination.with_name(f".{destination.name}.{token}.rebuild")
    db = connect(temporary)
    try:
        stats = import_legacy(db, csv_path, trips_path, bookings_path)
        p2_hana_result = resolve_hana_split_cancellations(db)
        p1_result = apply_p1_confidence_rules(db)
        p3_result = apply_p3_unassigned_review(db)
        p4_result = apply_p4_provider_rules(db)
        p5_result = apply_p5_quality_audit(db)
        applied_changes = apply_change_log(db, change_log) if change_log else 0
        report = validation_report(db)
        if not report["valid"]:
            raise ValueError("재생성 DB 정합성 검증에 실패했습니다.")
        corrected_amount_krw = scalar(
            db,
            "SELECT COALESCE(SUM(amount_krw), 0) FROM payment_transactions",
        )
        semantic_sha256 = build_review_snapshot(db)["semantic_sha256"]
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        db.close()
        temporary.unlink(missing_ok=True)
        temporary.with_name(temporary.name + "-wal").unlink(missing_ok=True)
        temporary.with_name(temporary.name + "-shm").unlink(missing_ok=True)
        raise
    else:
        db.close()
    destination.with_name(destination.name + "-wal").unlink(missing_ok=True)
    destination.with_name(destination.name + "-shm").unlink(missing_ok=True)
    os.replace(temporary, destination)
    temporary.with_name(temporary.name + "-wal").unlink(missing_ok=True)
    temporary.with_name(temporary.name + "-shm").unlink(missing_ok=True)
    return {
        "db": str(destination),
        "transactions": stats.transactions,
        "amount_krw": corrected_amount_krw,
        "applied_changes": applied_changes,
        "p2_hana_split_cancellations": p2_hana_result,
        "p1_confidence_rules": p1_result,
        "p3_unassigned_review": p3_result,
        "p4_provider_rules": p4_result,
        "p5_quality_audit": p5_result,
        "semantic_sha256": semantic_sha256,
    }


def backup_database(source: Path, destination: Path) -> dict[str, object]:
    """SQLite 온라인 백업과 검증용 semantic hash manifest를 만든다."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_db = connect(source)
    backup_db = connect(destination)
    try:
        source_db.backup(backup_db)
        report = validation_report(backup_db)
        if not report["valid"]:
            raise ValueError("백업 DB 정합성 검증에 실패했습니다.")
        semantic_sha256 = build_review_snapshot(backup_db)["semantic_sha256"]
    finally:
        backup_db.close()
        source_db.close()
    manifest = {
        "format_version": 1,
        "source": str(source),
        "backup": str(destination),
        "backup_sha256": file_sha256(destination),
        "semantic_sha256": semantic_sha256,
        "transactions": report["transactions"],
        "amount_krw": report["transaction_total_krw"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def restore_database(backup: Path, destination: Path) -> dict[str, object]:
    """검증된 백업을 임시 파일에 복원한 뒤 원자적으로 교체한다."""
    manifest_path = backup.with_suffix(backup.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if file_sha256(backup) != manifest["backup_sha256"]:
        raise ValueError("백업 파일 해시가 manifest와 다릅니다.")
    token = hashlib.sha256(str(destination).encode("utf-8")).hexdigest()[:12]
    temporary = destination.with_name(f".{destination.name}.{token}.restore")
    backup_db = connect(backup)
    restored_db = connect(temporary)
    try:
        backup_db.backup(restored_db)
        report = validation_report(restored_db)
        semantic_sha256 = build_review_snapshot(restored_db)["semantic_sha256"]
        if not report["valid"] or semantic_sha256 != manifest["semantic_sha256"]:
            raise ValueError("복원 DB가 백업 manifest와 일치하지 않습니다.")
        restored_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        restored_db.close()
        backup_db.close()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.with_name(destination.name + "-wal").unlink(missing_ok=True)
    destination.with_name(destination.name + "-shm").unlink(missing_ok=True)
    os.replace(temporary, destination)
    return {
        "db": str(destination),
        "semantic_sha256": semantic_sha256,
        "transactions": report["transactions"],
        "amount_krw": report["transaction_total_krw"],
    }


def print_stats(stats: ImportStats) -> None:
    state = "기존 스냅샷 재사용" if stats.repeated_snapshot else "이관 완료"
    print(
        f"{state}: 원천 {stats.source_rows:,}행 / 결제 {stats.transactions:,}건 / "
        f"예약 {stats.bookings:,}건 / 배분 {stats.allocations:,}건 / "
        f"판정 {stats.decisions:,}건 / 결제합 {stats.amount_krw:,}원"
    )


def cli(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="빈 DB에 스키마를 적용한다.")

    importer = sub.add_parser("import-legacy", help="classified 정본 스냅샷을 도메인별로 이관한다.")
    importer.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    importer.add_argument("--trips", type=Path, default=DEFAULT_TRIPS)
    importer.add_argument("--bookings", type=Path, default=DEFAULT_BOOKINGS)

    sub.add_parser("validate", help="결제=배분 합계와 참조 무결성을 검사한다.")
    sub.add_parser("review-report", help="미배정·근거충돌 등 분류 품질 검토 큐를 출력한다.")
    snapshot = sub.add_parser(
        "review-snapshot",
        help="상세 검토 큐 CSV와 회귀 기준 스냅샷을 생성한다.",
    )
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument(
        "--compare-to",
        type=Path,
        help="이전 스냅샷 디렉터리 또는 manifest.json과 추가·해소·잔존 건을 비교한다.",
    )
    change_apply = sub.add_parser(
        "apply-changes",
        help="append-only JSONL 변경 원장을 현재 DB에 멱등 적용한다.",
    )
    change_apply.add_argument("--log", type=Path, required=True)
    change_record = sub.add_parser(
        "record-change",
        help="JSON 변경 이벤트를 민감정보 제거 후 변경 원장에 추가한다.",
    )
    change_record.add_argument("--log", type=Path, required=True)
    change_record.add_argument("--event", type=Path, required=True)
    rebuild = sub.add_parser(
        "rebuild",
        help="불변 원천과 변경 원장으로 DB를 원자적으로 재생성한다.",
    )
    rebuild.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    rebuild.add_argument("--trips", type=Path, default=DEFAULT_TRIPS)
    rebuild.add_argument("--bookings", type=Path, default=DEFAULT_BOOKINGS)
    rebuild.add_argument("--change-log", type=Path)
    backup = sub.add_parser("backup", help="운영 DB를 검증 가능한 SQLite 백업으로 저장합니다.")
    backup.add_argument("--output", type=Path, required=True)
    restore = sub.add_parser("restore", help="검증된 SQLite 백업을 원자적으로 복원합니다.")
    restore.add_argument("--backup", type=Path, required=True)
    sub.add_parser(
        "apply-p1-confidence-rules",
        help="고신뢰·불확실 근거 충돌을 버전 있는 판정으로 정리합니다.",
    )
    sub.add_parser(
        "apply-p3-unassigned-review",
        help="미배정 결제를 네 가지 결과로 설명하고 확정 건만 재배분합니다.",
    )
    sub.add_parser(
        "apply-p4-provider-rules",
        help="예약 공급자를 실증근거와 형식 보조근거로 정규화합니다.",
    )
    sub.add_parser(
        "apply-p5-quality-audit",
        help="저신뢰·0원 결제의 비용인식과 자동전기 게이트를 감사합니다.",
    )
    sub.add_parser(
        "coverage-report",
        help="카드 이벤트 전수원장과 최종 배분의 무손실 상태를 검사합니다.",
    )
    recognize_prepaid = sub.add_parser(
        "recognize-prepaid-services",
        help="서비스 시작일이 도래한 선급 여행비를 해당 서비스 기간의 배분으로 복원합니다.",
    )
    recognize_prepaid.add_argument(
        "--through-on",
        required=True,
        help="이 날짜까지 시작한 서비스만 인식합니다 (YYYY-MM-DD).",
    )
    close = sub.add_parser(
        "close-period",
        help="미배정·미연결 환불·순액 근거 부족이 없는지 마감 게이트를 실행합니다.",
    )
    close.add_argument("--run-id", required=True)
    match_group = sub.add_parser(
        "upsert-match-group",
        help="OTA/카드 관계그룹과 신호를 기록합니다. 확정은 record-decision을 사용합니다.",
    )
    match_group.add_argument("--group-key", required=True)
    match_group.add_argument("--provider", default="")
    match_group.add_argument("--status", default="proposed")
    match_group.add_argument("--confidence", type=float, default=0.0)
    match_group.add_argument("--rationale", default="")
    match_group.add_argument("--payment-ids-json", default="[]")
    match_group.add_argument("--booking-ids-json", default="[]")
    match_group.add_argument("--signals-json", default="[]")
    decision = sub.add_parser("record-decision", help="OTA/카드 매칭 대표 판정을 append-only로 기록합니다.")
    decision.add_argument("--decision-id", required=True)
    decision.add_argument("--group-id", type=int, required=True)
    decision.add_argument("--status", required=True)
    decision.add_argument("--actor", required=True)
    decision.add_argument("--reason-code", required=True)
    decision.add_argument("--rationale", required=True)
    decision.add_argument("--evidence-json", default="[]")
    decision.add_argument("--supersedes")
    direct = sub.add_parser(
        "import-direct-sources",
        help="카드 RAW·수기장부·OTA 구조화 인덱스를 source 계층에 직접 적재합니다.",
    )
    direct.add_argument("--ledger-dir", type=Path, default=LEDGER_DIR)
    direct.add_argument("--manual", type=Path, default=LEDGER_DIR / "data" / "manual_v4.csv")
    direct.add_argument("--ota", type=Path, default=LEDGER_DIR / "data" / "ota_mail_index.json")
    verify_claims = sub.add_parser(
        "verify-review-claims",
        help="검토 큐의 수기·메일 부재 및 별도 미배정 주장을 원천자료로 재검증합니다.",
    )
    verify_claims.add_argument("--classified", type=Path, default=DEFAULT_CSV)
    verify_claims.add_argument("--manual", type=Path, default=LEDGER_DIR / "data" / "manual_v4.csv")
    verify_claims.add_argument("--ota", type=Path, default=LEDGER_DIR / "data" / "ota_mail_index.json")

    args = parser.parse_args(argv)
    if args.command == "verify-review-claims":
        result = verify_review_claims(args.classified, args.manual, args.ota)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "record-change":
        event = json.loads(args.event.read_text(encoding="utf-8"))
        result = append_change_event(args.log, event)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "rebuild":
        result = rebuild_database(
            args.db,
            args.csv,
            args.trips,
            args.bookings,
            args.change_log,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "backup":
        print(json.dumps(backup_database(args.db, args.output), ensure_ascii=False, indent=2))
        return 0
    if args.command == "restore":
        print(json.dumps(restore_database(args.backup, args.db), ensure_ascii=False, indent=2))
        return 0
    db = connect(args.db)
    try:
        if args.command == "init":
            initialize(db)
            print(f"스키마 초기화 완료: {args.db}")
            return 0
        if args.command == "import-legacy":
            stats = import_legacy(db, args.csv, args.trips, args.bookings)
            print_stats(stats)
            report = validation_report(db)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["valid"] else 1
        if args.command == "validate":
            initialize(db)
            report = validation_report(db)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["valid"] else 1
        if args.command == "review-report":
            initialize(db)
            print(json.dumps(review_report(db), ensure_ascii=False, indent=2))
            return 0
        if args.command == "review-snapshot":
            initialize(db)
            result = write_review_snapshot(db, args.output, args.compare_to)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "apply-p1-confidence-rules":
            initialize(db)
            print(
                json.dumps(
                    apply_p1_confidence_rules(db),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "apply-p3-unassigned-review":
            initialize(db)
            print(
                json.dumps(
                    apply_p3_unassigned_review(db),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "apply-p4-provider-rules":
            initialize(db)
            print(
                json.dumps(
                    apply_p4_provider_rules(db),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "apply-p5-quality-audit":
            initialize(db)
            print(
                json.dumps(
                    apply_p5_quality_audit(db),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "coverage-report":
            initialize(db)
            report = coverage_report(db)
            print(json.dumps(report.__dict__ | {"lossless": report.lossless}, ensure_ascii=False, indent=2))
            return 0 if report.lossless else 1
        if args.command == "recognize-prepaid-services":
            initialize(db)
            changed = recognize_prepaid_service_period(
                db,
                recognized_through_on=args.through_on,
            )
            db.commit()
            print(json.dumps({"recognized_payments": changed}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "close-period":
            initialize(db)
            source_claims = verify_review_claims(
                DEFAULT_CSV,
                LEDGER_DIR / "data" / "manual_v4.csv",
                LEDGER_DIR / "data" / "ota_mail_index.json",
            )
            if not source_claims["passed"]:
                print(
                    json.dumps(
                        {
                            "passed": False,
                            "gates": {
                                "review_claims_evidence_consistent": source_claims
                            },
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1
            try:
                result = close_period(
                    db,
                    args.run_id,
                    require_tax_evidence=True,
                )
            except PeriodCloseBlocked as exc:
                print(json.dumps({"passed": False, "gates": exc.gates}, ensure_ascii=False, indent=2, default=str))
                return 1
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0
        if args.command == "upsert-match-group":
            initialize(db)
            if args.status in {"confirmed_strong", "confirmed_manual"}:
                raise ValueError(
                    "운영 CLI의 확정 상태는 append-only 판정 이력을 남기도록 "
                    "`record-decision`으로 기록해야 합니다."
                )
            existing_group = db.execute(
                """
                SELECT status
                FROM current_match_group_projection
                WHERE group_key=?
                """,
                (args.group_key,),
            ).fetchone()
            if (
                existing_group is not None
                and existing_group["status"]
                in {"confirmed_strong", "confirmed_manual"}
            ):
                raise ValueError(
                    "이미 확정된 그룹의 신호를 upsert로 덮어쓸 수 없습니다. "
                    "새 그룹 또는 명시적 후속 판정을 사용해야 합니다."
                )
            group_id = create_match_group(
                db,
                args.group_key,
                provider=args.provider,
                status=args.status,
                confidence=args.confidence,
                rationale=args.rationale,
                payment_ids=json.loads(args.payment_ids_json),
                booking_ids=json.loads(args.booking_ids_json),
                signals=json.loads(args.signals_json),
            )
            db.commit()
            print(
                json.dumps(
                    {"group_id": group_id, "group_key": args.group_key},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "record-decision":
            initialize(db)
            created = record_match_decision(
                db, args.decision_id, args.group_id, status=args.status,
                actor=args.actor, reason_code=args.reason_code,
                rationale=args.rationale, evidence=json.loads(args.evidence_json),
                supersedes=args.supersedes,
            )
            db.commit()
            print(json.dumps({"decision_id": args.decision_id, "created": created}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "import-direct-sources":
            initialize(db)
            result = import_direct_sources(db, args.ledger_dir, args.manual, args.ota)
            result["legacy_comparison"] = compare_with_legacy(db)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "apply-changes":
            applied = apply_change_log(db, args.log)
            print(json.dumps({"applied_changes": applied}, ensure_ascii=False, indent=2))
            return 0
    finally:
        db.close()
    return 2


if __name__ == "__main__":
    sys.exit(cli())
