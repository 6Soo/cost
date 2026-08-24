"""Build a reversible accounting draft for proposed Agoda/card links.

The input database is opened read-only and never changed.  The command copies
it, verifies every proposed one-to-one link and its portal evidence, then adds
only proposed classification and allocation rows.  It never creates journal
entries or authoritative posting rows.

Trip attribution is deliberately fail-closed: a booking is assigned to a trip
only when its complete lodging service period fits exactly one imported,
explicitly dated schedule authority.  The legacy ``mm/dd/window`` source is
retained for audit/candidate reporting but cannot assign a target.  Missing or
ambiguous authority remains ``여행_미배정``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.direct_sources import import_trip_schedule
from ledger.domain.direct_verified_ota_lodging import (
    load_authoritative_trip_schedule,
)


RULE_ID = "agoda-linked-lodging-accounting-draft-v1"
ACTIVE_DIMENSIONS = ("account", "cost_type", "allocation_target")
PORTAL_ROLES = {
    "identity",
    "lifecycle",
    "portal_card_observation",
    "portal_payment_claim",
    "service_period",
}
UNASSIGNED_TARGET = "여행_미배정"
POSTING_TABLES = (
    "journal_entries",
    "direct_accounting_posting_batches",
    "direct_accounting_posting_lines",
)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def table_names(db: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def table_count(db: sqlite3.Connection, name: str) -> int:
    if name not in table_names(db):
        return 0
    return int(db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])


def copy_database(source_path: Path, destination_path: Path) -> None:
    source = sqlite3.connect(
        f"file:{source_path.resolve().as_posix()}?mode=ro", uri=True
    )
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()


def validate_trip_schedule_document(path: Path) -> list[dict[str, object]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("trip_schedule_root_invalid")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    legacy_shape = {"tab", "mm", "dd", "region", "window"}
    explicit_shape = {
        "tab", "event_year", "starts_on", "ends_on", "region",
        "authority_kind", "authority_status", "end_semantics",
    }
    explicit_service_shape = {
        "tab", "event_year", "service_start_on", "service_end_on", "region",
        "authority_kind", "authority_status", "end_semantics",
    }
    for index, value in enumerate(raw):
        if not isinstance(value, dict) or set(value) not in (
            legacy_shape, explicit_shape, explicit_service_shape,
        ):
            raise ValueError(f"trip_schedule_row_shape_invalid:{index}")
        row = dict(value)
        if set(row) in (explicit_shape, explicit_service_shape):
            if (
                not isinstance(row["tab"], str)
                or row["tab"] != row["tab"].strip()
                or not row["tab"]
                or row["tab"] in seen
                or not isinstance(row["region"], str)
                or not row["region"].strip()
                or type(row["event_year"]) is not int
                or row["authority_status"] not in {"authoritative", "candidate_only"}
                or not isinstance(row["authority_kind"], str)
                or not isinstance(row["end_semantics"], str)
            ):
                raise ValueError(f"trip_schedule_row_invalid:{index}")
            if set(row) == explicit_shape:
                if row["end_semantics"] != "inclusive_last_service_date":
                    raise ValueError(f"trip_schedule_row_invalid:{index}")
                start_value, end_value = row["starts_on"], row["ends_on"]
            else:
                if row["end_semantics"] != "exclusive_service_end":
                    raise ValueError(f"trip_schedule_row_invalid:{index}")
                start_value, end_value = row["service_start_on"], row["service_end_on"]
            try:
                start = date.fromisoformat(str(start_value))
                end = date.fromisoformat(str(end_value))
            except ValueError as exc:
                raise ValueError(f"trip_schedule_row_invalid:{index}") from exc
            invalid_order = (
                end < start
                or set(row) == explicit_service_shape and end <= start
            )
            if invalid_order or not start.year <= row["event_year"] <= end.year:
                raise ValueError(f"trip_schedule_row_invalid:{index}")
            seen.add(str(row["tab"]))
            result.append(row)
            continue
        if (
            not isinstance(row["tab"], str)
            or row["tab"] != row["tab"].strip()
            or not row["tab"]
            or row["tab"] in seen
            or not isinstance(row["region"], str)
            or row["region"] != row["region"].strip()
            or not row["region"]
            or type(row["mm"]) is not int
            or type(row["dd"]) is not int
            or type(row["window"]) is not int
            or not 1 <= int(row["window"]) <= 60
        ):
            raise ValueError(f"trip_schedule_row_invalid:{index}")
        date(2026, int(row["mm"]), int(row["dd"]))
        seen.add(str(row["tab"]))
        result.append(row)
    return result


def matching_trip_codes(
    service_start_on: str,
    service_end_on: str,
    schedule: dict[str, dict[str, object]],
) -> list[str]:
    start = date.fromisoformat(service_start_on)
    end = date.fromisoformat(service_end_on)
    if end <= start:
        raise ValueError("booking_service_period_invalid")
    last_night = end - timedelta(days=1)
    return sorted(
        str(code)
        for code, trip in schedule.items()
        if date.fromisoformat(str(trip["starts_on"])) <= start
        <= date.fromisoformat(str(trip["ends_on"]))
        and last_night <= date.fromisoformat(str(trip["ends_on"]))
    )


def validate_portal_evidence(
    db: sqlite3.Connection,
    booking_id: int,
    booking_number: str,
    service_start_on: str,
    service_end_on: str,
) -> str:
    rows = db.execute(
        """SELECT e.direct_source_record_id,e.source_kind,e.source_key,
                  e.source_sha256,e.evidence_kind,e.evidence_role,
                  e.evidence_status,e.conflict_count,s.payload_json
           FROM booking_source_evidence e
           JOIN direct_source_records s
             ON s.id=e.direct_source_record_id
            AND s.source_kind=e.source_kind
            AND s.source_key=e.source_key
            AND s.source_sha256=e.source_sha256
           WHERE e.booking_id=? ORDER BY e.evidence_role""",
        (booking_id,),
    ).fetchall()
    if len(rows) != len(PORTAL_ROLES):
        raise ValueError(f"portal_evidence_role_count_invalid:{booking_id}")
    if {str(row[5]) for row in rows} != PORTAL_ROLES:
        raise ValueError(f"portal_evidence_role_set_invalid:{booking_id}")
    if len({int(row[0]) for row in rows}) != 1:
        raise ValueError(f"portal_evidence_source_not_unique:{booking_id}")
    evidence_snapshot: list[list[object]] = []
    payloads: list[dict[str, object]] = []
    for row in rows:
        if (
            str(row[1]) != "agoda_portal_detail"
            or str(row[4]) != "agoda_portal_detail"
            or str(row[6]) != "observed"
            or int(row[7]) != 0
            or not is_sha256(str(row[3]))
        ):
            raise ValueError(f"portal_evidence_not_active:{booking_id}")
        try:
            payload = json.loads(str(row[8]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"portal_payload_invalid:{booking_id}") from exc
        if not isinstance(payload, dict) or content_sha256(payload) != str(row[3]):
            raise ValueError(f"portal_payload_digest_mismatch:{booking_id}")
        payloads.append(payload)
        evidence_snapshot.append(
            [int(row[0]), str(row[2]), str(row[3]), str(row[5]), str(row[6])]
        )
    if len({canonical_json(payload) for payload in payloads}) != 1:
        raise ValueError(f"portal_payload_not_unique:{booking_id}")
    payload = payloads[0]
    if (
        str(payload.get("provider")) != "agoda"
        or str(payload.get("booking_number")) != booking_number
        or str(payload.get("product_type")) != "lodging"
        or str(payload.get("status")) != "completed"
        or str(payload.get("reservation_status")) != "completed"
        or str(payload.get("payment_status")) != "paid"
        or str(payload.get("refund_status")) != "none_displayed"
        or str(payload.get("service_start_on")) != service_start_on
        or str(payload.get("service_end_on")) != service_end_on
    ):
        raise ValueError(f"portal_payload_contract_invalid:{booking_id}")
    components = payload.get("price_components")
    if not isinstance(components, list) or not components:
        raise ValueError(f"portal_price_components_missing:{booking_id}")
    if not any(
        isinstance(component, dict)
        and component.get("kind") in {"paid_today", "scheduled_payment"}
        and type(component.get("minor_units")) is int
        and int(component["minor_units"]) > 0
        for component in components
    ):
        raise ValueError(f"portal_positive_charge_missing:{booking_id}")
    return content_sha256(evidence_snapshot)


def load_link_scope(
    db: sqlite3.Connection,
    *,
    input_database_sha256: str,
    input_audit_sha256: str,
) -> list[dict[str, object]]:
    if "direct_agoda_card_proposed_link_authorities" not in table_names(db):
        raise ValueError("proposed_link_authority_table_missing")
    rows = db.execute(
        """SELECT a.authority_id,a.reconciliation_run_id,
                  a.candidate_report_sha256,a.payment_id,a.booking_id,
                  a.authority_sha256,a.payload_json,
                  l.relation_type,l.confidence,l.link_status,
                  b.provider,b.booking_number,b.product_type,b.service_start_on,
                  b.service_end_on,b.status,
                  p.external_key,p.source_system,p.transaction_type,
                  p.amount_krw,p.merchant
           FROM direct_agoda_card_proposed_link_authorities a
           JOIN payment_booking_links l
             ON l.payment_id=a.payment_id AND l.booking_id=a.booking_id
           JOIN bookings b ON b.id=a.booking_id
           JOIN payment_transactions p ON p.id=a.payment_id
           ORDER BY a.payment_id"""
    ).fetchall()
    authority_count = table_count(db, "direct_agoda_card_proposed_link_authorities")
    link_count = int(
        db.execute(
            "SELECT COUNT(*) FROM payment_booking_links WHERE link_status='proposed'"
        ).fetchone()[0]
    )
    if not rows or len(rows) != authority_count or len(rows) != link_count:
        raise ValueError("proposed_link_scope_count_mismatch")
    run_ids = {str(row[1]) for row in rows}
    if len(run_ids) != 1:
        raise ValueError("reconciliation_run_not_unique")
    run_id = next(iter(run_ids))
    run = db.execute(
        "SELECT status FROM direct_projection_runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if run is None or str(run[0]) != "passed":
        raise ValueError("reconciliation_run_not_passed")
    result: list[dict[str, object]] = []
    for row in rows:
        try:
            authority_payload = json.loads(str(row[6]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"link_authority_payload_invalid:{row[0]}") from exc
        if (
            not isinstance(authority_payload, dict)
            or content_sha256(authority_payload) != str(row[0])
            or str(row[0]) != str(row[5])
            or int(authority_payload.get("payment_id", -1)) != int(row[3])
            or int(authority_payload.get("booking_id", -1)) != int(row[4])
            or authority_payload.get("link_status") != "proposed"
            or authority_payload.get("relation_type") != "pays_for"
        ):
            raise ValueError(f"link_authority_binding_invalid:{row[0]}")
        if (
            str(row[7]) != "pays_for"
            or float(row[8]) != 1.0
            or str(row[9]) != "proposed"
            or str(row[10]) != "agoda"
            or str(row[12]) != "lodging"
            or str(row[15]) != "completed"
            or str(row[18]) != "purchase"
            or int(row[19]) <= 0
        ):
            raise ValueError(f"linked_lodging_contract_invalid:{row[0]}")
        service_start = str(row[13])
        service_end = str(row[14])
        date.fromisoformat(service_start)
        date.fromisoformat(service_end)
        evidence_set_sha256 = validate_portal_evidence(
            db,
            int(row[4]),
            str(row[11]),
            service_start,
            service_end,
        )
        result.append(
            {
                "link_authority_id": str(row[0]),
                "reconciliation_run_id": str(row[1]),
                "candidate_report_sha256": str(row[2]),
                "payment_id": int(row[3]),
                "booking_id": int(row[4]),
                "booking_number": str(row[11]),
                "service_start_on": service_start,
                "service_end_on": service_end,
                "external_key": str(row[16]),
                "source_system": str(row[17]),
                "transaction_type": str(row[18]),
                "amount_krw": int(row[19]),
                "merchant": str(row[20] or ""),
                "booking_evidence_set_sha256": evidence_set_sha256,
                "input_database_sha256": input_database_sha256,
                "input_audit_sha256": input_audit_sha256,
            }
        )
    if len({int(row["payment_id"]) for row in result}) != len(result):
        raise ValueError("draft_payment_scope_not_unique")
    if len({int(row["booking_id"]) for row in result}) != len(result):
        raise ValueError("draft_booking_scope_not_unique")
    return result


def build_draft_rows(
    scope: Iterable[dict[str, object]],
    schedule: dict[str, dict[str, object]],
    trip_schedule_sha256: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in scope:
        candidates = matching_trip_codes(
            str(source["service_start_on"]),
            str(source["service_end_on"]),
            schedule,
        )
        if len(candidates) == 1:
            match_status = "unique_service_period"
            target = candidates[0]
            allocation_confidence = 1.0
        elif candidates:
            match_status = "service_target_ambiguous"
            target = UNASSIGNED_TARGET
            allocation_confidence = 0.0
        else:
            match_status = "service_target_missing"
            target = UNASSIGNED_TARGET
            allocation_confidence = 0.0
        payload = {
            **source,
            "trip_schedule_sha256": trip_schedule_sha256,
            "candidate_targets": candidates,
            "candidate_target_set_sha256": content_sha256(candidates),
            "target_match_status": match_status,
            "account": "숙박비",
            "cost_type": "여행원가",
            "allocation_target": target,
            "allocation_confidence": allocation_confidence,
            "decision_status": "proposed",
            "plan_status": "proposed",
            "posting_eligible": False,
        }
        draft_id = content_sha256(payload)
        rows.append(
            {
                **payload,
                "draft_id": draft_id,
                "draft_sha256": draft_id,
                "payload_json": canonical_json(payload),
            }
        )
    return rows


def create_draft_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE direct_agoda_accounting_draft_authorities(
          draft_id TEXT PRIMARY KEY CHECK(length(draft_id)=64),
          reconciliation_run_id TEXT NOT NULL
            REFERENCES direct_projection_runs(run_id),
          link_authority_id TEXT NOT NULL UNIQUE
            REFERENCES direct_agoda_card_proposed_link_authorities(authority_id),
          input_database_sha256 TEXT NOT NULL CHECK(length(input_database_sha256)=64),
          input_audit_sha256 TEXT NOT NULL CHECK(length(input_audit_sha256)=64),
          booking_evidence_set_sha256 TEXT NOT NULL
            CHECK(length(booking_evidence_set_sha256)=64),
          trip_schedule_sha256 TEXT NOT NULL CHECK(length(trip_schedule_sha256)=64),
          candidate_target_set_sha256 TEXT NOT NULL
            CHECK(length(candidate_target_set_sha256)=64),
          payment_id INTEGER NOT NULL UNIQUE REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id),
          account TEXT NOT NULL CHECK(account='숙박비'),
          cost_type TEXT NOT NULL CHECK(cost_type='여행원가'),
          allocation_target TEXT NOT NULL,
          target_match_status TEXT NOT NULL CHECK(target_match_status IN (
            'unique_service_period','service_target_ambiguous','service_target_missing'
          )),
          decision_status TEXT NOT NULL CHECK(decision_status='proposed'),
          plan_status TEXT NOT NULL CHECK(plan_status='proposed'),
          posting_eligible INTEGER NOT NULL CHECK(posting_eligible=0),
          draft_sha256 TEXT NOT NULL CHECK(length(draft_sha256)=64),
          payload_json TEXT NOT NULL
        );

        CREATE TABLE direct_agoda_accounting_draft_decision_bindings(
          draft_id TEXT NOT NULL
            REFERENCES direct_agoda_accounting_draft_authorities(draft_id),
          dimension TEXT NOT NULL CHECK(dimension IN (
            'account','cost_type','allocation_target'
          )),
          decision_id INTEGER NOT NULL UNIQUE REFERENCES classification_decisions(id),
          PRIMARY KEY(draft_id,dimension)
        );

        CREATE TABLE direct_agoda_accounting_draft_plan_bindings(
          draft_id TEXT PRIMARY KEY
            REFERENCES direct_agoda_accounting_draft_authorities(draft_id),
          plan_id INTEGER NOT NULL UNIQUE REFERENCES allocation_plans(id)
        );
        """
    )


def ensure_source_document(
    db: sqlite3.Connection, source_kind: str, path: Path, sha256: str,
) -> None:
    db.execute(
        "INSERT OR IGNORE INTO source_documents(source_kind,path,sha256) VALUES (?,?,?)",
        (source_kind, relative(path), sha256),
    )
    row = db.execute(
        "SELECT source_kind FROM source_documents WHERE path=? AND sha256=?",
        (relative(path), sha256),
    ).fetchone()
    if row is None or str(row[0]) != source_kind:
        raise ValueError(f"source_document_binding_invalid:{source_kind}")


def ensure_target(
    db: sqlite3.Connection,
    row: dict[str, object],
    schedule: dict[str, dict[str, object]],
) -> int:
    code = str(row["allocation_target"])
    if code == UNASSIGNED_TARGET:
        db.execute(
            """INSERT OR IGNORE INTO allocation_targets(target_type,code,name,trip_id)
               VALUES ('unassigned',?,?,NULL)""",
            (code, code),
        )
        expected = ("unassigned", code, None)
    else:
        trip = schedule.get(code)
        if trip is None:
            raise ValueError(f"draft_trip_target_missing:{code}")
        db.execute(
            """INSERT OR IGNORE INTO trips(code,name,region,starts_on,ends_on,status)
               VALUES (?,?,?,?,?,'planned')""",
            (
                code,
                code,
                str(trip["region"]),
                str(trip["starts_on"]),
                str(trip["ends_on"]),
            ),
        )
        trip_row = db.execute(
            "SELECT id,name,region,starts_on,ends_on,status FROM trips WHERE code=?",
            (code,),
        ).fetchone()
        if trip_row is None or tuple(trip_row[1:]) != (
            code,
            str(trip["region"]),
            str(trip["starts_on"]),
            str(trip["ends_on"]),
            "planned",
        ):
            raise ValueError(f"draft_trip_row_conflict:{code}")
        db.execute(
            """INSERT OR IGNORE INTO allocation_targets(target_type,code,name,trip_id)
               VALUES ('trip',?,?,?)""",
            (code, code, int(trip_row[0])),
        )
        expected = ("trip", code, int(trip_row[0]))
    target = db.execute(
        "SELECT id,target_type,name,trip_id FROM allocation_targets WHERE code=?",
        (code,),
    ).fetchone()
    if target is None or tuple(target[1:]) != expected:
        raise ValueError(f"draft_allocation_target_conflict:{code}")
    return int(target[0])


def ensure_decision(
    db: sqlite3.Connection,
    row: dict[str, object],
    dimension: str,
) -> int:
    values = {
        "account": str(row["account"]),
        "cost_type": str(row["cost_type"]),
        "allocation_target": str(row["allocation_target"]),
    }
    confidence = (
        float(row["allocation_confidence"])
        if dimension == "allocation_target"
        else 1.0
    )
    rule_id = f"{RULE_ID}:{dimension}"
    rationale = (
        "완료된 Agoda 숙박 예약과 구매 카드의 검증된 1:1 proposed 링크에 기반한 "
        "가역 분류·배부 초안; 회계전기 권한은 부여하지 않음"
    )
    db.execute(
        """INSERT OR IGNORE INTO classification_decisions(
             target_type,target_id,dimension,value,confidence,confidence_label,
             decision_status,rule_id,rationale)
           VALUES ('payment',?,?,?,?,?,'proposed',?,?)""",
        (
            int(row["payment_id"]),
            dimension,
            values[dimension],
            confidence,
            "포털완료숙박+1:1카드링크",
            rule_id,
            rationale,
        ),
    )
    decision = db.execute(
        """SELECT id,value,confidence,confidence_label,decision_status,rule_id,rationale
           FROM classification_decisions
           WHERE target_type='payment' AND target_id=? AND dimension=?
             AND superseded_by_id IS NULL AND decision_status<>'superseded'""",
        (int(row["payment_id"]), dimension),
    ).fetchone()
    expected = (
        values[dimension],
        confidence,
        "포털완료숙박+1:1카드링크",
        "proposed",
        rule_id,
        rationale,
    )
    if decision is None or tuple(decision[1:]) != expected:
        raise ValueError(
            f"draft_classification_conflict:{row['payment_id']}:{dimension}"
        )
    return int(decision[0])


def materialize_draft(
    db: sqlite3.Connection,
    rows: list[dict[str, object]],
    schedule: dict[str, dict[str, object]],
) -> int:
    before = db.total_changes
    for row in rows:
        db.execute(
            """INSERT OR IGNORE INTO direct_agoda_accounting_draft_authorities(
                 draft_id,reconciliation_run_id,link_authority_id,
                 input_database_sha256,input_audit_sha256,
                 booking_evidence_set_sha256,trip_schedule_sha256,
                 candidate_target_set_sha256,payment_id,booking_id,account,cost_type,
                 allocation_target,target_match_status,decision_status,plan_status,
                 posting_eligible,draft_sha256,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'proposed','proposed',0,?,?)""",
            (
                row["draft_id"],
                row["reconciliation_run_id"],
                row["link_authority_id"],
                row["input_database_sha256"],
                row["input_audit_sha256"],
                row["booking_evidence_set_sha256"],
                row["trip_schedule_sha256"],
                row["candidate_target_set_sha256"],
                row["payment_id"],
                row["booking_id"],
                row["account"],
                row["cost_type"],
                row["allocation_target"],
                row["target_match_status"],
                row["draft_sha256"],
                row["payload_json"],
            ),
        )
        stored = db.execute(
            "SELECT draft_sha256,payload_json FROM direct_agoda_accounting_draft_authorities WHERE draft_id=?",
            (row["draft_id"],),
        ).fetchone()
        if stored is None or tuple(stored) != (
            str(row["draft_sha256"]), str(row["payload_json"]),
        ):
            raise ValueError(f"draft_authority_conflict:{row['draft_id']}")
        target_id = ensure_target(db, row, schedule)
        decisions: dict[str, int] = {}
        for dimension in ACTIVE_DIMENSIONS:
            decision_id = ensure_decision(db, row, dimension)
            decisions[dimension] = decision_id
            db.execute(
                """INSERT OR IGNORE INTO direct_agoda_accounting_draft_decision_bindings(
                     draft_id,dimension,decision_id) VALUES (?,?,?)""",
                (row["draft_id"], dimension, decision_id),
            )
        allocation_confidence = float(row["allocation_confidence"])
        db.execute(
            """INSERT OR IGNORE INTO booking_target_links(
                 booking_id,target_id,confidence,link_status)
               VALUES (?,?,?,'proposed')""",
            (row["booking_id"], target_id, allocation_confidence),
        )
        booking_target = db.execute(
            """SELECT confidence,link_status FROM booking_target_links
               WHERE booking_id=? AND target_id=?""",
            (row["booking_id"], target_id),
        ).fetchone()
        if booking_target is None or tuple(booking_target) != (
            allocation_confidence, "proposed",
        ):
            raise ValueError(f"draft_booking_target_conflict:{row['booking_id']}")
        db.execute(
            """INSERT OR IGNORE INTO allocation_plans(
                 payment_id,plan_version,plan_status,confidence,source_decision_id)
               VALUES (?,1,'proposed',?,?)""",
            (
                row["payment_id"],
                allocation_confidence,
                decisions["allocation_target"],
            ),
        )
        plan = db.execute(
            """SELECT id,plan_status,confidence,source_decision_id
               FROM allocation_plans WHERE payment_id=? AND plan_version=1""",
            (row["payment_id"],),
        ).fetchone()
        if plan is None or tuple(plan[1:]) != (
            "proposed", allocation_confidence, decisions["allocation_target"],
        ):
            raise ValueError(f"draft_allocation_plan_conflict:{row['payment_id']}")
        allocations = db.execute(
            """SELECT booking_id,target_id,amount_krw FROM cost_allocations
               WHERE plan_id=?""",
            (int(plan[0]),),
        ).fetchall()
        expected_allocation = (
            int(row["booking_id"]), target_id, int(row["amount_krw"]),
        )
        if not allocations:
            db.execute(
                """INSERT INTO cost_allocations(plan_id,booking_id,target_id,amount_krw)
                   VALUES (?,?,?,?)""",
                (int(plan[0]), *expected_allocation),
            )
        elif len(allocations) != 1 or tuple(allocations[0]) != expected_allocation:
            raise ValueError(f"draft_cost_allocation_conflict:{row['payment_id']}")
        db.execute(
            """INSERT OR IGNORE INTO direct_agoda_accounting_draft_plan_bindings(
                 draft_id,plan_id) VALUES (?,?)""",
            (row["draft_id"], int(plan[0])),
        )
        if row["target_match_status"] != "unique_service_period":
            reason = str(row["target_match_status"])
            rationale = (
                "숙박 서비스 기간이 현재 여행 일정에 유일하게 결속되지 않아 "
                "전기하지 않고 여행_미배정 proposed 배부로 보존"
            )
            db.execute(
                """INSERT OR IGNORE INTO allocation_review_cases(
                     payment_id,outcome,reason_code,rationale,review_status,rule_id)
                   VALUES (?,'travel_unassigned',?,?,'needs_review',?)""",
                (row["payment_id"], reason, rationale, RULE_ID),
            )
            review = db.execute(
                """SELECT outcome,reason_code,rationale,review_status,rule_id
                   FROM allocation_review_cases WHERE payment_id=?""",
                (row["payment_id"],),
            ).fetchone()
            if review is None or tuple(review) != (
                "travel_unassigned", reason, rationale, "needs_review", RULE_ID,
            ):
                raise ValueError(f"draft_review_case_conflict:{row['payment_id']}")
    return db.total_changes - before


def semantic_snapshot(db: sqlite3.Connection) -> dict[str, object]:
    return {
        "authorities": [
            list(row)
            for row in db.execute(
                """SELECT draft_id,link_authority_id,payment_id,booking_id,account,
                          cost_type,allocation_target,target_match_status,
                          candidate_target_set_sha256,draft_sha256
                   FROM direct_agoda_accounting_draft_authorities
                   ORDER BY payment_id"""
            )
        ],
        "decisions": [
            list(row)
            for row in db.execute(
                """SELECT d.target_id,d.dimension,d.value,d.confidence,
                          d.decision_status,d.rule_id
                   FROM direct_agoda_accounting_draft_decision_bindings b
                   JOIN classification_decisions d ON d.id=b.decision_id
                   ORDER BY d.target_id,d.dimension"""
            )
        ],
        "allocations": [
            list(row)
            for row in db.execute(
                """SELECT ap.payment_id,ap.plan_version,ap.plan_status,ap.confidence,
                          a.booking_id,t.code,a.amount_krw
                   FROM direct_agoda_accounting_draft_plan_bindings b
                   JOIN allocation_plans ap ON ap.id=b.plan_id
                   JOIN cost_allocations a ON a.plan_id=ap.id
                   JOIN allocation_targets t ON t.id=a.target_id
                   ORDER BY ap.payment_id"""
            )
        ],
        "reviews": [
            list(row)
            for row in db.execute(
                """SELECT r.payment_id,r.outcome,r.reason_code,r.review_status,r.rule_id
                   FROM allocation_review_cases r
                   JOIN direct_agoda_accounting_draft_authorities a
                     ON a.payment_id=r.payment_id
                   ORDER BY r.payment_id"""
            )
        ],
    }


def validate_materialized(
    db: sqlite3.Connection,
    expected_rows: list[dict[str, object]],
) -> dict[str, object]:
    expected_count = len(expected_rows)
    unique_count = sum(
        row["target_match_status"] == "unique_service_period"
        for row in expected_rows
    )
    ambiguous_count = sum(
        row["target_match_status"] == "service_target_ambiguous"
        for row in expected_rows
    )
    missing_count = sum(
        row["target_match_status"] == "service_target_missing"
        for row in expected_rows
    )
    expected_amount = sum(int(row["amount_krw"]) for row in expected_rows)
    counts = {
        "draft_authorities": table_count(
            db, "direct_agoda_accounting_draft_authorities"
        ),
        "draft_decision_bindings": table_count(
            db, "direct_agoda_accounting_draft_decision_bindings"
        ),
        "draft_plan_bindings": table_count(
            db, "direct_agoda_accounting_draft_plan_bindings"
        ),
        "classification_decisions": table_count(db, "classification_decisions"),
        "allocation_plans": table_count(db, "allocation_plans"),
        "cost_allocations": table_count(db, "cost_allocations"),
        "booking_target_links": table_count(db, "booking_target_links"),
        "allocation_review_cases": table_count(db, "allocation_review_cases"),
        "journal_entries": table_count(db, "journal_entries"),
    }
    amount = int(
        db.execute(
            """SELECT COALESCE(SUM(a.amount_krw),0)
               FROM direct_agoda_accounting_draft_plan_bindings b
               JOIN cost_allocations a ON a.plan_id=b.plan_id"""
        ).fetchone()[0]
    )
    target_counts = {
        str(row[0]): int(row[1])
        for row in db.execute(
            """SELECT target_match_status,COUNT(*)
               FROM direct_agoda_accounting_draft_authorities
               GROUP BY target_match_status ORDER BY target_match_status"""
        )
    }
    proposed_decisions = int(
        db.execute(
            "SELECT COUNT(*) FROM classification_decisions WHERE decision_status='proposed'"
        ).fetchone()[0]
    )
    proposed_plans = int(
        db.execute(
            "SELECT COUNT(*) FROM allocation_plans WHERE plan_status='proposed'"
        ).fetchone()[0]
    )
    confirmed_side_effects = int(
        db.execute(
            """SELECT
                 (SELECT COUNT(*) FROM classification_decisions
                   WHERE decision_status='confirmed')+
                 (SELECT COUNT(*) FROM allocation_plans
                   WHERE plan_status='confirmed')+
                 (SELECT COUNT(*) FROM payment_booking_links
                   WHERE link_status='confirmed')"""
        ).fetchone()[0]
    )
    posting_rows = sum(table_count(db, name) for name in POSTING_TABLES)
    payload_mismatches = int(
        db.execute(
            """SELECT COUNT(*) FROM direct_agoda_accounting_draft_authorities
               WHERE draft_id<>draft_sha256 OR posting_eligible<>0
                 OR decision_status<>'proposed' OR plan_status<>'proposed'"""
        ).fetchone()[0]
    )
    expected_counts = {
        "draft_authorities": expected_count,
        "draft_decision_bindings": expected_count * len(ACTIVE_DIMENSIONS),
        "draft_plan_bindings": expected_count,
        "classification_decisions": expected_count * len(ACTIVE_DIMENSIONS),
        "allocation_plans": expected_count,
        "cost_allocations": expected_count,
        "booking_target_links": expected_count,
        "allocation_review_cases": ambiguous_count + missing_count,
        "journal_entries": 0,
    }
    issues: list[str] = []
    if counts != expected_counts:
        issues.append("draft_table_count_mismatch")
    if amount != expected_amount:
        issues.append("draft_amount_sum_mismatch")
    if proposed_decisions != expected_count * len(ACTIVE_DIMENSIONS):
        issues.append("draft_decision_status_mismatch")
    if proposed_plans != expected_count:
        issues.append("draft_plan_status_mismatch")
    if confirmed_side_effects:
        issues.append("confirmed_authority_leak")
    if posting_rows:
        issues.append("posting_side_effect_leak")
    if payload_mismatches:
        issues.append("draft_authority_payload_mismatch")
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        issues.append("integrity_check_failed")
    foreign_keys = [list(row) for row in db.execute("PRAGMA foreign_key_check")]
    if foreign_keys:
        issues.append("foreign_key_check_failed")
    return {
        "passed": not issues,
        "issues": issues,
        "counts": counts,
        "target_match_counts": target_counts,
        "expected_target_match_counts": {
            "unique_service_period": unique_count,
            "service_target_ambiguous": ambiguous_count,
            "service_target_missing": missing_count,
        },
        "allocation_amount_krw": amount,
        "expected_amount_krw": expected_amount,
        "confirmed_side_effects": confirmed_side_effects,
        "posting_rows": posting_rows,
        "payload_mismatches": payload_mismatches,
        "foreign_key_violations": foreign_keys,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-db",
        default="outputs/agoda-card-proposed-links-v1-20260824.sqlite",
    )
    parser.add_argument(
        "--input-audit",
        default="outputs/agoda-card-proposed-links-audit-v1-20260824.json",
    )
    parser.add_argument("--trip-schedule", default="ledger/data/trips.json")
    parser.add_argument(
        "--output-db",
        default="outputs/agoda-card-accounting-draft-v1-20260824.sqlite",
    )
    parser.add_argument(
        "--output-detail",
        default="outputs/agoda-card-accounting-draft-detail-v1-20260824.json",
    )
    parser.add_argument(
        "--output-audit",
        default="outputs/agoda-card-accounting-draft-audit-v1-20260824.json",
    )
    args = parser.parse_args()

    input_db = (ROOT / args.input_db).resolve()
    input_audit = (ROOT / args.input_audit).resolve()
    trip_schedule_path = (ROOT / args.trip_schedule).resolve()
    output_db = (ROOT / args.output_db).resolve()
    output_detail = (ROOT / args.output_detail).resolve()
    output_audit = (ROOT / args.output_audit).resolve()
    for path in (output_db, output_detail, output_audit):
        if path.exists():
            raise FileExistsError(f"refusing_to_overwrite:{path}")

    schedule_document = validate_trip_schedule_document(trip_schedule_path)
    input_db_sha256 = file_sha256(input_db)
    input_audit_sha256 = file_sha256(input_audit)
    trip_schedule_sha256 = file_sha256(trip_schedule_path)
    promotion_audit = json.loads(input_audit.read_text(encoding="utf-8"))
    if input_db_sha256 != promotion_audit["output"]["database_sha256"]:
        raise ValueError("input_database_hash_mismatch")
    expected_link_count = int(
        promotion_audit["counts"]["proposed_link_authorities"]
    )

    source = sqlite3.connect(
        f"file:{input_db.as_posix()}?mode=ro", uri=True
    )
    source.row_factory = sqlite3.Row
    try:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("input_database_integrity_failed")
        if source.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("input_database_foreign_key_failed")
        if any(
            table_count(source, table)
            for table in (
                "classification_decisions", "allocation_plans",
                "cost_allocations", "journal_entries",
            )
        ):
            raise ValueError("input_database_already_has_accounting_rows")
        scope = load_link_scope(
            source,
            input_database_sha256=input_db_sha256,
            input_audit_sha256=input_audit_sha256,
        )
        if len(scope) != expected_link_count:
            raise ValueError("input_link_count_drift")
    finally:
        source.close()

    copy_database(input_db, output_db)
    db = sqlite3.connect(output_db)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        create_draft_tables(db)
        ensure_source_document(
            db, "agoda_card_proposed_links_audit", input_audit, input_audit_sha256
        )
        ensure_source_document(
            db, "trip_schedule", trip_schedule_path, trip_schedule_sha256
        )
        imported = import_trip_schedule(db, trip_schedule_path)
        if imported["records"] != len(schedule_document):
            raise ValueError("trip_schedule_import_count_mismatch")
        schedule = load_authoritative_trip_schedule(db)
        rows = build_draft_rows(scope, schedule, trip_schedule_sha256)
        first_changes = materialize_draft(db, rows, schedule)
        db.commit()
        before_second = db.total_changes
        imported_second = import_trip_schedule(db, trip_schedule_path)
        second_changes = materialize_draft(db, rows, schedule)
        db.commit()
        second_total_changes = db.total_changes - before_second
        validation = validate_materialized(db, rows)
        snapshot = semantic_snapshot(db)
        semantic_sha256 = content_sha256(snapshot)
    finally:
        db.close()

    # Rebuild independently in memory from the immutable input to prove that
    # row identity, target selection, and all business values are deterministic.
    source = sqlite3.connect(
        f"file:{input_db.as_posix()}?mode=ro", uri=True
    )
    rebuilt = sqlite3.connect(":memory:")
    rebuilt.row_factory = sqlite3.Row
    try:
        source.backup(rebuilt)
        rebuilt.execute("PRAGMA foreign_keys=ON")
        create_draft_tables(rebuilt)
        ensure_source_document(
            rebuilt, "agoda_card_proposed_links_audit", input_audit,
            input_audit_sha256,
        )
        ensure_source_document(
            rebuilt, "trip_schedule", trip_schedule_path, trip_schedule_sha256
        )
        import_trip_schedule(rebuilt, trip_schedule_path)
        rebuilt_schedule = load_authoritative_trip_schedule(rebuilt)
        rebuilt_scope = load_link_scope(
            rebuilt,
            input_database_sha256=input_db_sha256,
            input_audit_sha256=input_audit_sha256,
        )
        rebuilt_rows = build_draft_rows(
            rebuilt_scope, rebuilt_schedule, trip_schedule_sha256
        )
        materialize_draft(rebuilt, rebuilt_rows, rebuilt_schedule)
        rebuilt.commit()
        rebuilt_semantic_sha256 = content_sha256(semantic_snapshot(rebuilt))
    finally:
        rebuilt.close()
        source.close()

    detail = {
        "artifact_kind": "agoda_card_accounting_draft_detail",
        "artifact_version": "v1",
        "rule_id": RULE_ID,
        "rows": [
            {
                key: row[key]
                for key in (
                    "draft_id", "link_authority_id", "payment_id", "booking_id",
                    "booking_number", "external_key", "source_system",
                    "amount_krw", "service_start_on", "service_end_on", "account",
                    "cost_type", "allocation_target", "target_match_status",
                    "candidate_targets", "allocation_confidence",
                )
            }
            for row in rows
        ],
    }
    write_json(output_detail, detail)

    result = {
        "artifact_kind": "agoda_card_accounting_draft_audit",
        "artifact_version": "v1",
        "rule_id": RULE_ID,
        "builder": {
            "path": relative(Path(__file__)),
            "sha256": file_sha256(Path(__file__)),
        },
        "inputs": {
            "database": relative(input_db),
            "database_sha256": input_db_sha256,
            "audit": relative(input_audit),
            "audit_sha256": input_audit_sha256,
            "trip_schedule": relative(trip_schedule_path),
            "trip_schedule_sha256": trip_schedule_sha256,
            "trip_schedule_record_count": len(schedule_document),
        },
        "outputs": {
            "database": relative(output_db),
            "database_sha256": file_sha256(output_db),
            "detail": relative(output_detail),
            "detail_sha256": file_sha256(output_detail),
            "semantic_sha256": semantic_sha256,
        },
        "counts": validation["counts"],
        "target_match_counts": validation["target_match_counts"],
        "amounts": {
            "allocation_amount_krw": validation["allocation_amount_krw"],
            "expected_amount_krw": validation["expected_amount_krw"],
        },
        "checks": {
            "validation_passed": validation["passed"],
            "validation_issues": validation["issues"],
            "first_materialization_changes": first_changes,
            "second_materialization_changes": second_changes,
            "second_total_changes": second_total_changes,
            "trip_schedule_second_import_inserted": imported_second["inserted"],
            "semantic_idempotent": second_total_changes == 0,
            "independent_rebuild_semantic_sha256": rebuilt_semantic_sha256,
            "independent_rebuild_matches": rebuilt_semantic_sha256 == semantic_sha256,
            "input_database_unchanged": file_sha256(input_db) == input_db_sha256,
            "confirmed_side_effects": validation["confirmed_side_effects"],
            "posting_rows": validation["posting_rows"],
            "foreign_key_violations": validation["foreign_key_violations"],
        },
        "authority": {
            "classification_status": "proposed",
            "allocation_plan_status": "proposed",
            "journal_entries_written": 0,
            "authoritative_posting_written": False,
            "unresolved_targets_are_unassigned": True,
        },
    }
    if not all(
        (
            result["checks"]["validation_passed"],
            result["checks"]["semantic_idempotent"],
            result["checks"]["independent_rebuild_matches"],
            result["checks"]["input_database_unchanged"],
            result["checks"]["confirmed_side_effects"] == 0,
            result["checks"]["posting_rows"] == 0,
            not result["checks"]["foreign_key_violations"],
        )
    ):
        raise RuntimeError("agoda_accounting_draft_audit_failed")
    write_json(output_audit, result)
    print(
        json.dumps(
            {
                **result,
                "output_audit": relative(output_audit),
                "output_audit_sha256": file_sha256(output_audit),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
