#!/usr/bin/env python3
"""도메인 분리형 비용 원장 초기화·legacy v14 이관·불변식 검증.

기존 산출 경로를 대체하지 않는다. classified_v14를 원천 스냅샷으로 가져와
결제 사실, 예약 연결, 배분, 분류판정을 분리하고 동일 건수·합계를 검증한다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable


HERE = Path(__file__).resolve().parent
LEDGER_DIR = HERE.parent
DEFAULT_DB = LEDGER_DIR / "data" / "ledger_v2.db"
DEFAULT_CSV = LEDGER_DIR / "data" / "classified_v14.csv"
DEFAULT_TRIPS = LEDGER_DIR / "data" / "trips.json"
DEFAULT_BOOKINGS = LEDGER_DIR / "data" / "booking_info.json"
SCHEMA = HERE / "schema.sql"

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


def upsert_payment(
    db: sqlite3.Connection,
    row: dict[str, str],
    method_id: int,
) -> int:
    amount = parse_int(row.get("krw"))
    transaction_type = "cancellation" if is_true(row.get("cancel")) or amount < 0 else "purchase"
    values = (
        row["uid"],
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
        SELECT payment_method_id, source_system, occurred_on, posted_on, merchant,
               business_category, country, currency, foreign_amount, amount_krw,
               approval_number, transaction_type
        FROM payment_transactions WHERE external_key=?
        """,
        (row["uid"],),
    ).fetchone()
    comparable = values[1:]
    if existing is None:
        db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, payment_method_id, source_system, occurred_on, posted_on,
                merchant, business_category, country, currency, foreign_amount,
                amount_krw, approval_number, transaction_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
    elif tuple(existing) != comparable:
        db.execute(
            """
            UPDATE payment_transactions SET
                payment_method_id=?, source_system=?, occurred_on=?, posted_on=?,
                merchant=?, business_category=?, country=?, currency=?, foreign_amount=?,
                amount_krw=?, approval_number=?, transaction_type=?,
                record_version=record_version+1, updated_at=CURRENT_TIMESTAMP
            WHERE external_key=?
            """,
            comparable + (row["uid"],),
        )
    return int(
        db.execute("SELECT id FROM payment_transactions WHERE external_key=?", (row["uid"],)).fetchone()[0]
    )


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
    start, end = period_dates(str(info.get("period", "")))
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
) -> int:
    previous = db.execute(
        """
        SELECT id, value, confidence, confidence_label, rationale
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
    ) == (value, confidence, confidence_label, rationale):
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
            ) VALUES (?, ?, ?, ?, ?, ?, 'legacy', 'legacy_v14_import', ?)
            """,
            (
                target_type_name,
                target_id,
                dimension,
                value or "미정",
                confidence,
                confidence_label or None,
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
        WHERE p.payment_id=? AND p.plan_status <> 'rejected'
          AND NOT EXISTS (
              SELECT 1 FROM allocation_plans newer
              WHERE newer.supersedes_plan_id=p.id AND newer.plan_status <> 'rejected'
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

        imported_payment_ids: list[int] = []
        approval_lookup: dict[tuple[str, str], int] = {}
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
            payment_id = upsert_payment(db, row, method_id)
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
            if approval and not is_true(row.get("cancel")):
                approval_lookup[(issuer, approval)] = payment_id
            original = re.sub(r"\D", "", row.get("orig_appr", ""))
            if original:
                pending_relations.append((payment_id, issuer, original))

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

            linked_bookings: list[int] = []
            for number in booking_numbers(note):
                booking_id = ensure_booking(db, number, row, booking_info)
                linked_bookings.append(booking_id)
                db.execute(
                    """
                    INSERT INTO payment_booking_links(
                        payment_id, booking_id, relation_type, confidence, link_status
                    ) VALUES (?, ?, 'pays_for', ?, 'legacy')
                    ON CONFLICT(payment_id, booking_id, relation_type) DO UPDATE SET
                        confidence=excluded.confidence
                    """,
                    (payment_id, booking_id, confidence),
                )
                db.execute(
                    """
                    INSERT INTO booking_target_links(booking_id, target_id, confidence, link_status)
                    VALUES (?, ?, ?, 'legacy')
                    ON CONFLICT(booking_id, target_id) DO UPDATE SET confidence=excluded.confidence
                    """,
                    (booking_id, target_id, confidence),
                )

            allocation_booking_id = linked_bookings[0] if len(linked_bookings) == 1 else None
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
            related_id = approval_lookup.get((issuer, original))
            if related_id == transaction_id:
                related_id = None
            db.execute(
                """
                INSERT INTO transaction_relations(
                    transaction_id, related_transaction_id, relation_type,
                    reference_value, match_method, confidence
                ) VALUES (?, ?, 'cancels', ?, ?, ?)
                ON CONFLICT(transaction_id, relation_type, reference_value) DO UPDATE SET
                    related_transaction_id=excluded.related_transaction_id,
                    match_method=excluded.match_method,
                    confidence=excluded.confidence
                """,
                (
                    transaction_id,
                    related_id,
                    original,
                    "issuer+original_approval" if related_id else "unresolved_original_approval",
                    1.0 if related_id else 0.5,
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


def validation_report(
    db: sqlite3.Connection,
    payment_ids: Iterable[int] | None = None,
) -> dict[str, int | bool]:
    ids = list(payment_ids or [])
    scope_sql = ""
    params: list[object] = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        scope_sql = f" WHERE id IN ({placeholders})"
        params.extend(ids)

    transaction_count = scalar(db, f"SELECT COUNT(*) FROM payment_transactions{scope_sql}", params)
    transaction_total = scalar(
        db,
        f"SELECT COALESCE(SUM(amount_krw), 0) FROM payment_transactions{scope_sql}",
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
            WHERE payment_id IN ({placeholders}) AND difference_krw <> 0
            """,
            ids,
        )
    else:
        allocation_count = scalar(db, "SELECT COUNT(*) FROM current_cost_allocations")
        allocation_total = scalar(db, "SELECT COALESCE(SUM(amount_krw), 0) FROM current_cost_allocations")
        mismatches = scalar(
            db,
            "SELECT COUNT(*) FROM payment_allocation_summary WHERE difference_krw <> 0",
        )

    report: dict[str, int | bool] = {
        "source_documents": scalar(db, "SELECT COUNT(*) FROM source_documents"),
        "source_records": scalar(db, "SELECT COUNT(*) FROM source_records"),
        "transactions": transaction_count,
        "transaction_total_krw": transaction_total,
        "bookings": scalar(db, "SELECT COUNT(*) FROM bookings"),
        "trips": scalar(db, "SELECT COUNT(*) FROM trips"),
        "allocation_targets": scalar(db, "SELECT COUNT(*) FROM allocation_targets"),
        "active_allocations": allocation_count,
        "allocation_total_krw": allocation_total,
        "allocation_mismatches": mismatches,
        "current_decisions": scalar(db, "SELECT COUNT(*) FROM current_classification_decisions"),
        "transaction_relations": scalar(db, "SELECT COUNT(*) FROM transaction_relations"),
        "resolved_transaction_relations": scalar(
            db,
            "SELECT COUNT(*) FROM transaction_relations WHERE related_transaction_id IS NOT NULL",
        ),
    }
    report["valid"] = (
        report["transactions"] == report["active_allocations"]
        and report["transaction_total_krw"] == report["allocation_total_krw"]
        and report["allocation_mismatches"] == 0
    )
    return report


def review_report(db: sqlite3.Connection) -> dict[str, int]:
    """합계 오류가 아닌 분류 품질 문제를 검토 큐로 드러낸다."""
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
            "SELECT COUNT(*) FROM payment_transactions WHERE external_key LIKE 'MISC-%'",
        ),
        "engine_isolated_amount_krw": scalar(
            db,
            """
            SELECT COALESCE(SUM(amount_krw), 0)
            FROM payment_transactions
            WHERE external_key LIKE 'MISC-%'
            """,
        ),
        "zero_amount_payments": scalar(
            db,
            "SELECT COUNT(*) FROM payment_transactions WHERE amount_krw=0",
        ),
        "unresolved_transaction_relations": scalar(
            db,
            "SELECT COUNT(*) FROM transaction_relations WHERE related_transaction_id IS NULL",
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
                WHERE link_status <> 'rejected'
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


def print_stats(stats: ImportStats) -> None:
    state = "기존 스냅샷 재사용" if stats.repeated_snapshot else "이관 완료"
    print(
        f"{state}: 원천 {stats.source_rows:,}행 / 결제 {stats.transactions:,}건 / "
        f"예약 {stats.bookings:,}건 / 배분 {stats.allocations:,}건 / "
        f"판정 {stats.decisions:,}건 / 결제합 {stats.amount_krw:,}원"
    )


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="빈 DB에 스키마를 적용한다.")

    importer = sub.add_parser("import-legacy", help="classified_v14 스냅샷을 도메인별로 이관한다.")
    importer.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    importer.add_argument("--trips", type=Path, default=DEFAULT_TRIPS)
    importer.add_argument("--bookings", type=Path, default=DEFAULT_BOOKINGS)

    sub.add_parser("validate", help="결제=배분 합계와 참조 무결성을 검사한다.")
    sub.add_parser("review-report", help="미배정·근거충돌 등 분류 품질 검토 큐를 출력한다.")

    args = parser.parse_args(argv)
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
    finally:
        db.close()
    return 2


if __name__ == "__main__":
    sys.exit(cli())
