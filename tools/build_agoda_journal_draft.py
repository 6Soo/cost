"""Build balanced, non-authoritative Agoda journal drafts.

The command consumes the immutable Agoda accounting-draft database.  It copies
that database, records additional candidate-only target evidence for every
unresolved booking, and creates balanced debit/credit draft batches only for
bookings whose service period already maps to one trip.

It deliberately does not write ``journal_entries`` or any
``direct_accounting_posting_*`` table.  Historical/manual classifications are
preserved as candidates and are never applied to current decisions or plans.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_agoda_accounting_draft import (
    canonical_json,
    content_sha256,
    copy_database,
    file_sha256,
    relative,
    table_count,
    table_names,
    write_json,
)


RULE_ID = "agoda-linked-lodging-journal-draft-v1"
DEBIT_ACCOUNT = "숙박비"
CREDIT_ACCOUNT = "법인카드미지급금"
COST_TYPE = "여행원가"
VAT_TAG = "불공제_해외"
LEDGER_CURRENCY = "KRW"
EVIDENCE_LABEL = "Agoda 포털 완료 숙박+카드 1:1; 해외숙박 불공제"

RESOLUTION_STATUSES = {
    "historical_exact_booking_candidate",
    "historical_exact_booking_conflict",
    "property_region_candidate",
    "property_evidence_only",
    "no_additional_evidence",
}


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def exact_booking_reference(text: str, booking_number: str) -> bool:
    return re.search(
        rf"(?<!\d){re.escape(str(booking_number))}(?!\d)", str(text)
    ) is not None


def parse_int(value: object) -> int | None:
    text = str(value or "").strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(?:\.0+)?", text):
        return None
    return int(float(text))


def is_false_text(value: object) -> bool:
    return str(value or "").strip().casefold() in {"", "0", "false", "no", "n"}


def validate_input_audit(
    audit_path: Path, database_path: Path,
) -> tuple[dict[str, object], str, str]:
    raw = load_json(audit_path)
    if not isinstance(raw, dict):
        raise ValueError("accounting_draft_audit_root_invalid")
    checks = raw.get("checks")
    outputs = raw.get("outputs")
    authority = raw.get("authority")
    if not isinstance(checks, dict) or not isinstance(outputs, dict):
        raise ValueError("accounting_draft_audit_shape_invalid")
    if not isinstance(authority, dict):
        raise ValueError("accounting_draft_authority_shape_invalid")
    database_sha = file_sha256(database_path)
    audit_sha = file_sha256(audit_path)
    if outputs.get("database_sha256") != database_sha:
        raise ValueError("accounting_draft_database_sha256_mismatch")
    if not checks.get("validation_passed") or not checks.get(
        "independent_rebuild_matches"
    ):
        raise ValueError("accounting_draft_audit_not_passed")
    if checks.get("confirmed_side_effects") != 0 or checks.get("posting_rows") != 0:
        raise ValueError("accounting_draft_authority_leak")
    if authority.get("authoritative_posting_written") is not False:
        raise ValueError("accounting_draft_posting_state_invalid")
    return raw, database_sha, audit_sha


def load_scope(db: sqlite3.Connection) -> list[dict[str, object]]:
    required = {
        "direct_agoda_accounting_draft_authorities",
        "direct_agoda_accounting_draft_plan_bindings",
        "allocation_plans",
        "cost_allocations",
        "allocation_targets",
        "payment_transactions",
        "bookings",
    }
    missing = required - table_names(db)
    if missing:
        raise ValueError(f"journal_draft_input_tables_missing:{sorted(missing)}")
    rows = db.execute(
        """SELECT a.draft_id,a.payment_id,a.booking_id,a.allocation_target,
                  a.target_match_status,a.decision_status,a.plan_status,
                  a.posting_eligible,a.payload_json,
                  b.booking_number,b.service_start_on,b.service_end_on,b.status,
                  p.external_key,p.source_system,p.transaction_type,p.amount_krw,
                  p.occurred_on,p.merchant,
                  pb.plan_id,ap.plan_status,ap.confidence,
                  ca.id,ca.target_id,ca.amount_krw,t.code,t.target_type
           FROM direct_agoda_accounting_draft_authorities a
           JOIN bookings b ON b.id=a.booking_id
           JOIN payment_transactions p ON p.id=a.payment_id
           JOIN direct_agoda_accounting_draft_plan_bindings pb
             ON pb.draft_id=a.draft_id
           JOIN allocation_plans ap ON ap.id=pb.plan_id
           JOIN cost_allocations ca ON ca.plan_id=ap.id
           JOIN allocation_targets t ON t.id=ca.target_id
           ORDER BY a.payment_id"""
    ).fetchall()
    if not rows:
        raise ValueError("journal_draft_scope_empty")
    result: list[dict[str, object]] = []
    for raw in rows:
        try:
            payload = json.loads(str(raw[8]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"journal_source_payload_invalid:{raw[0]}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"journal_source_payload_invalid:{raw[0]}")
        if (
            str(raw[5]) != "proposed"
            or str(raw[6]) != "proposed"
            or int(raw[7]) != 0
            or str(raw[12]) != "completed"
            or str(raw[15]) != "purchase"
            or int(raw[16]) <= 0
            or str(raw[20]) != "proposed"
            or int(raw[16]) != int(raw[24])
            or str(raw[3]) != str(raw[25])
            or str(payload.get("booking_number")) != str(raw[9])
            or str(payload.get("service_start_on")) != str(raw[10])
            or str(payload.get("service_end_on")) != str(raw[11])
        ):
            raise ValueError(f"journal_source_contract_invalid:{raw[0]}")
        candidates = payload.get("candidate_targets")
        if not isinstance(candidates, list) or not all(
            isinstance(value, str) for value in candidates
        ):
            raise ValueError(f"journal_source_candidates_invalid:{raw[0]}")
        result.append(
            {
                "source_draft_id": str(raw[0]),
                "payment_id": int(raw[1]),
                "booking_id": int(raw[2]),
                "booking_number": str(raw[9]),
                "allocation_target": str(raw[3]),
                "target_match_status": str(raw[4]),
                "candidate_targets": sorted(candidates),
                "service_start_on": str(raw[10]),
                "service_end_on": str(raw[11]),
                "external_key": str(raw[13]),
                "source_system": str(raw[14]),
                "amount_krw": int(raw[16]),
                "occurred_on": str(raw[17]),
                "merchant": str(raw[18] or ""),
                "plan_id": int(raw[19]),
                "plan_confidence": float(raw[21]),
                "allocation_id": int(raw[22]),
                "target_id": int(raw[23]),
                "target_type": str(raw[26]),
            }
        )
    if len({row["payment_id"] for row in result}) != len(result):
        raise ValueError("journal_source_payment_not_unique")
    if len({row["booking_id"] for row in result}) != len(result):
        raise ValueError("journal_source_booking_not_unique")
    return result


def index_historical_rows(
    path: Path, booking_numbers: Iterable[str],
) -> dict[str, list[dict[str, object]]]:
    wanted = sorted({str(value) for value in booking_numbers}, key=len, reverse=True)
    result: dict[str, list[dict[str, object]]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            normalized = {str(key): str(value or "") for key, value in row.items()}
            searchable = "\n".join(normalized.values())
            matches = [value for value in wanted if exact_booking_reference(searchable, value)]
            for booking_number in matches:
                payload = {
                    "booking_number": booking_number,
                    "uid": normalized.get("uid", ""),
                    "src": normalized.get("src", ""),
                    "use_date": normalized.get("use_date", ""),
                    "merchant": normalized.get("merchant", ""),
                    "krw": normalized.get("krw", ""),
                    "bucket": normalized.get("bucket", ""),
                    "account": normalized.get("account", ""),
                    "cost_type": normalized.get("cost_type", ""),
                    "vat_tag": normalized.get("vat_tag", ""),
                    "confidence": normalized.get("confidence", ""),
                    "cancel": normalized.get("cancel", ""),
                    "note": normalized.get("note", ""),
                }
                result[booking_number].append(
                    {
                        **payload,
                        "source_locator": normalized.get("uid", ""),
                        "evidence_sha256": content_sha256(payload),
                    }
                )
    for booking_number in result:
        unique = {row["evidence_sha256"]: row for row in result[booking_number]}
        result[booking_number] = [unique[key] for key in sorted(unique)]
    return dict(result)


def index_property_rows(
    path: Path, booking_numbers: Iterable[str],
) -> dict[str, list[dict[str, object]]]:
    wanted = {str(value) for value in booking_numbers}
    raw = load_json(path)
    if not isinstance(raw, dict) or not isinstance(raw.get("records"), list):
        raise ValueError("agoda_property_evidence_root_invalid")
    result: dict[str, list[dict[str, object]]] = defaultdict(list)
    for index, value in enumerate(raw["records"]):
        if not isinstance(value, dict):
            continue
        booking_number = str(value.get("source_id") or "")
        hotel = str(value.get("hotel") or "").strip()
        if (
            booking_number not in wanted
            or str(value.get("detail_id") or "") != booking_number
            or value.get("id_exact_match") is not True
            or not hotel
        ):
            continue
        payload = {
            "booking_number": booking_number,
            "hotel": hotel,
            "status": str(value.get("status") or ""),
            "dates": value.get("dates") if isinstance(value.get("dates"), list) else [],
            "page": value.get("page"),
            "card_index": value.get("card_index"),
        }
        result[booking_number].append(
            {
                **payload,
                "source_locator": f"records[{index}]",
                "evidence_sha256": content_sha256(payload),
            }
        )
    for booking_number in result:
        unique = {row["evidence_sha256"]: row for row in result[booking_number]}
        result[booking_number] = [unique[key] for key in sorted(unique)]
    return dict(result)


def historical_row_is_candidate(
    evidence: Mapping[str, object], amount_krw: int,
) -> bool:
    return (
        str(evidence.get("account")) == DEBIT_ACCOUNT
        and str(evidence.get("cost_type")) == COST_TYPE
        and bool(str(evidence.get("bucket") or "").strip())
        and is_false_text(evidence.get("cancel"))
        and parse_int(evidence.get("krw")) == int(amount_krw)
    )


def property_target_matches(
    property_rows: Iterable[Mapping[str, object]], candidate_targets: Iterable[str],
) -> list[str]:
    hotels = " ".join(str(row.get("hotel") or "") for row in property_rows).casefold()
    matches: list[str] = []
    for target in sorted({str(value) for value in candidate_targets}):
        region = target.split("_", 1)[-1].strip().casefold()
        if region and region in hotels:
            matches.append(target)
    return matches


def build_resolution_rows(
    unresolved: Iterable[dict[str, object]],
    historical: Mapping[str, list[dict[str, object]]],
    properties: Mapping[str, list[dict[str, object]]],
    *,
    historical_path: str,
    historical_sha256: str,
    property_path: str,
    property_sha256: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    resolutions: list[dict[str, object]] = []
    evidence_rows: list[dict[str, object]] = []
    for source in sorted(unresolved, key=lambda row: str(row["booking_number"])):
        booking_number = str(source["booking_number"])
        historical_rows = list(historical.get(booking_number, []))
        property_rows = list(properties.get(booking_number, []))
        eligible = [
            row
            for row in historical_rows
            if historical_row_is_candidate(row, int(source["amount_krw"]))
        ]
        historical_targets = sorted({str(row["bucket"]) for row in eligible})
        property_targets = property_target_matches(
            property_rows, source.get("candidate_targets", [])
        )
        if len(historical_targets) == 1:
            status = "historical_exact_booking_candidate"
            suggested_target: str | None = historical_targets[0]
        elif len(historical_targets) > 1:
            status = "historical_exact_booking_conflict"
            suggested_target = None
        elif len(property_targets) == 1:
            status = "property_region_candidate"
            suggested_target = property_targets[0]
        elif property_rows:
            status = "property_evidence_only"
            suggested_target = None
        else:
            status = "no_additional_evidence"
            suggested_target = None
        if status not in RESOLUTION_STATUSES:
            raise AssertionError(status)
        preliminary = {
            "source_draft_id": source["source_draft_id"],
            "payment_id": source["payment_id"],
            "booking_id": source["booking_id"],
            "booking_number": booking_number,
            "amount_krw": source["amount_krw"],
            "service_start_on": source["service_start_on"],
            "service_end_on": source["service_end_on"],
            "current_match_status": source["target_match_status"],
            "current_candidate_targets": source.get("candidate_targets", []),
            "historical_candidate_targets": historical_targets,
            "property_candidate_targets": property_targets,
            "suggested_target": suggested_target,
            "resolution_status": status,
            "authority_status": "candidate_only",
            "posting_status": "blocked",
            "posting_eligible": False,
        }
        resolution_id = content_sha256(preliminary)
        evidence_ids: list[str] = []
        for source_kind, source_path, source_sha, rows in (
            (
                "historical_manual_classification",
                historical_path,
                historical_sha256,
                historical_rows,
            ),
            ("agoda_paseo_property_capture", property_path, property_sha256, property_rows),
        ):
            for row in rows:
                evidence_payload = {
                    "resolution_id": resolution_id,
                    "source_kind": source_kind,
                    "source_path": source_path,
                    "source_file_sha256": source_sha,
                    "source_locator": row["source_locator"],
                    "source_evidence_sha256": row["evidence_sha256"],
                    "evidence": {
                        key: value
                        for key, value in row.items()
                        if key not in {"source_locator", "evidence_sha256"}
                    },
                }
                evidence_id = content_sha256(evidence_payload)
                evidence_ids.append(evidence_id)
                evidence_rows.append(
                    {
                        **evidence_payload,
                        "evidence_id": evidence_id,
                        "payload_json": canonical_json(evidence_payload),
                    }
                )
        payload = {**preliminary, "evidence_ids": sorted(evidence_ids)}
        resolutions.append(
            {
                **payload,
                "resolution_id": resolution_id,
                "resolution_sha256": content_sha256(payload),
                "payload_json": canonical_json(payload),
            }
        )
    evidence_rows.sort(key=lambda row: str(row["evidence_id"]))
    return resolutions, evidence_rows


def build_journal_rows(
    scope: Iterable[dict[str, object]], source_database_sha256: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    batches: list[dict[str, object]] = []
    lines: list[dict[str, object]] = []
    for source in sorted(scope, key=lambda row: int(row["payment_id"])):
        if source["target_match_status"] != "unique_service_period":
            continue
        if source["target_type"] != "trip" or float(source["plan_confidence"]) != 1.0:
            raise ValueError(f"journal_unique_target_contract_invalid:{source['payment_id']}")
        posting_date = str(source["occurred_on"])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", posting_date):
            raise ValueError(f"journal_posting_date_invalid:{source['payment_id']}")
        payload = {
            "rule_id": RULE_ID,
            "source_database_sha256": source_database_sha256,
            "source_draft_id": source["source_draft_id"],
            "payment_id": source["payment_id"],
            "booking_id": source["booking_id"],
            "booking_number": source["booking_number"],
            "allocation_id": source["allocation_id"],
            "target_id": source["target_id"],
            "trip_code": source["allocation_target"],
            "posting_date": posting_date,
            "accounting_period": posting_date[:7],
            "ledger_currency": LEDGER_CURRENCY,
            "amount_krw": source["amount_krw"],
            "debit_account": DEBIT_ACCOUNT,
            "credit_account": CREDIT_ACCOUNT,
            "cost_type": COST_TYPE,
            "vat_tag": VAT_TAG,
            "evidence_label": EVIDENCE_LABEL,
            "batch_status": "draft_balanced",
            "posting_status": "draft",
            "posting_eligible": False,
            "external_posting": False,
        }
        batch_id = content_sha256(payload)
        batches.append(
            {
                **payload,
                "batch_id": batch_id,
                "batch_sha256": batch_id,
                "payload_json": canonical_json(payload),
            }
        )
        for line_no, (side, account) in enumerate(
            (("debit", DEBIT_ACCOUNT), ("credit", CREDIT_ACCOUNT)), start=1
        ):
            line_payload = {
                "batch_id": batch_id,
                "line_no": line_no,
                "side": side,
                "account_code": account,
                "amount_krw": source["amount_krw"],
                "payment_id": source["payment_id"],
                "booking_id": source["booking_id"],
                "allocation_id": source["allocation_id"],
                "trip_code": source["allocation_target"],
                "posting_date": posting_date,
                "accounting_period": posting_date[:7],
                "ledger_currency": LEDGER_CURRENCY,
                "vat_tag": VAT_TAG,
            }
            lines.append(
                {
                    **line_payload,
                    "line_sha256": content_sha256(line_payload),
                    "payload_json": canonical_json(line_payload),
                }
            )
    return batches, lines


def create_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE direct_agoda_target_resolution_candidates(
          resolution_id TEXT PRIMARY KEY CHECK(length(resolution_id)=64),
          source_draft_id TEXT NOT NULL UNIQUE
            REFERENCES direct_agoda_accounting_draft_authorities(draft_id),
          payment_id INTEGER NOT NULL UNIQUE REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id),
          booking_number TEXT NOT NULL,
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          current_match_status TEXT NOT NULL CHECK(current_match_status IN (
            'service_target_ambiguous','service_target_missing'
          )),
          suggested_target TEXT,
          resolution_status TEXT NOT NULL CHECK(resolution_status IN (
            'historical_exact_booking_candidate',
            'historical_exact_booking_conflict',
            'property_region_candidate',
            'property_evidence_only',
            'no_additional_evidence'
          )),
          authority_status TEXT NOT NULL CHECK(authority_status='candidate_only'),
          posting_status TEXT NOT NULL CHECK(posting_status='blocked'),
          posting_eligible INTEGER NOT NULL CHECK(posting_eligible=0),
          resolution_sha256 TEXT NOT NULL CHECK(length(resolution_sha256)=64),
          payload_json TEXT NOT NULL
        );

        CREATE TABLE direct_agoda_target_resolution_evidence(
          evidence_id TEXT PRIMARY KEY CHECK(length(evidence_id)=64),
          resolution_id TEXT NOT NULL
            REFERENCES direct_agoda_target_resolution_candidates(resolution_id),
          source_kind TEXT NOT NULL CHECK(source_kind IN (
            'historical_manual_classification','agoda_paseo_property_capture'
          )),
          source_path TEXT NOT NULL,
          source_file_sha256 TEXT NOT NULL CHECK(length(source_file_sha256)=64),
          source_locator TEXT NOT NULL,
          source_evidence_sha256 TEXT NOT NULL CHECK(length(source_evidence_sha256)=64),
          payload_json TEXT NOT NULL
        );

        CREATE TABLE direct_agoda_journal_draft_batches(
          batch_id TEXT PRIMARY KEY CHECK(length(batch_id)=64),
          source_draft_id TEXT NOT NULL UNIQUE
            REFERENCES direct_agoda_accounting_draft_authorities(draft_id),
          payment_id INTEGER NOT NULL UNIQUE REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id),
          allocation_id INTEGER NOT NULL UNIQUE REFERENCES cost_allocations(id),
          target_id INTEGER NOT NULL REFERENCES allocation_targets(id),
          trip_code TEXT NOT NULL,
          accounting_period TEXT NOT NULL,
          posting_date TEXT NOT NULL,
          ledger_currency TEXT NOT NULL CHECK(ledger_currency='KRW'),
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          debit_account TEXT NOT NULL CHECK(debit_account='숙박비'),
          credit_account TEXT NOT NULL CHECK(credit_account='법인카드미지급금'),
          cost_type TEXT NOT NULL CHECK(cost_type='여행원가'),
          vat_tag TEXT NOT NULL CHECK(vat_tag='불공제_해외'),
          evidence_label TEXT NOT NULL,
          batch_status TEXT NOT NULL CHECK(batch_status='draft_balanced'),
          posting_status TEXT NOT NULL CHECK(posting_status='draft'),
          posting_eligible INTEGER NOT NULL CHECK(posting_eligible=0),
          external_posting INTEGER NOT NULL CHECK(external_posting=0),
          batch_sha256 TEXT NOT NULL CHECK(length(batch_sha256)=64),
          payload_json TEXT NOT NULL
        );

        CREATE TABLE direct_agoda_journal_draft_lines(
          batch_id TEXT NOT NULL REFERENCES direct_agoda_journal_draft_batches(batch_id),
          line_no INTEGER NOT NULL CHECK(line_no IN (1,2)),
          side TEXT NOT NULL CHECK(side IN ('debit','credit')),
          account_code TEXT NOT NULL,
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL REFERENCES bookings(id),
          allocation_id INTEGER NOT NULL REFERENCES cost_allocations(id),
          trip_code TEXT NOT NULL,
          accounting_period TEXT NOT NULL,
          posting_date TEXT NOT NULL,
          ledger_currency TEXT NOT NULL CHECK(ledger_currency='KRW'),
          vat_tag TEXT NOT NULL CHECK(vat_tag='불공제_해외'),
          line_sha256 TEXT NOT NULL UNIQUE CHECK(length(line_sha256)=64),
          payload_json TEXT NOT NULL,
          PRIMARY KEY(batch_id,line_no)
        );

        CREATE TABLE direct_agoda_journal_draft_manifests(
          manifest_id TEXT PRIMARY KEY CHECK(length(manifest_id)=64),
          source_database_sha256 TEXT NOT NULL CHECK(length(source_database_sha256)=64),
          batch_count INTEGER NOT NULL CHECK(batch_count>=0),
          line_count INTEGER NOT NULL CHECK(line_count>=0),
          unresolved_count INTEGER NOT NULL CHECK(unresolved_count>=0),
          debit_total_krw INTEGER NOT NULL CHECK(debit_total_krw>=0),
          credit_total_krw INTEGER NOT NULL CHECK(credit_total_krw>=0),
          batch_set_sha256 TEXT NOT NULL CHECK(length(batch_set_sha256)=64),
          resolution_set_sha256 TEXT NOT NULL CHECK(length(resolution_set_sha256)=64),
          posting_status TEXT NOT NULL CHECK(posting_status='draft_balanced'),
          authoritative_posting INTEGER NOT NULL CHECK(authoritative_posting=0),
          payload_json TEXT NOT NULL,
          CHECK(debit_total_krw=credit_total_krw)
        );
        """
    )


def insert_exact(
    db: sqlite3.Connection,
    sql: str,
    values: tuple[object, ...],
) -> None:
    db.execute(sql, values)


def materialize(
    db: sqlite3.Connection,
    resolutions: list[dict[str, object]],
    evidence_rows: list[dict[str, object]],
    batches: list[dict[str, object]],
    lines: list[dict[str, object]],
    source_database_sha256: str,
) -> int:
    before = db.total_changes
    for row in resolutions:
        insert_exact(
            db,
            """INSERT OR IGNORE INTO direct_agoda_target_resolution_candidates(
                 resolution_id,source_draft_id,payment_id,booking_id,booking_number,
                 amount_krw,current_match_status,suggested_target,resolution_status,
                 authority_status,posting_status,posting_eligible,resolution_sha256,
                 payload_json) VALUES (?,?,?,?,?,?,?,?,?,'candidate_only','blocked',0,?,?)""",
            (
                row["resolution_id"], row["source_draft_id"], row["payment_id"],
                row["booking_id"], row["booking_number"], row["amount_krw"],
                row["current_match_status"], row["suggested_target"],
                row["resolution_status"], row["resolution_sha256"], row["payload_json"],
            ),
        )
    for row in evidence_rows:
        insert_exact(
            db,
            """INSERT OR IGNORE INTO direct_agoda_target_resolution_evidence(
                 evidence_id,resolution_id,source_kind,source_path,source_file_sha256,
                 source_locator,source_evidence_sha256,payload_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                row["evidence_id"], row["resolution_id"], row["source_kind"],
                row["source_path"], row["source_file_sha256"], row["source_locator"],
                row["source_evidence_sha256"], row["payload_json"],
            ),
        )
    for row in batches:
        insert_exact(
            db,
            """INSERT OR IGNORE INTO direct_agoda_journal_draft_batches(
                 batch_id,source_draft_id,payment_id,booking_id,allocation_id,target_id,
                 trip_code,accounting_period,posting_date,ledger_currency,amount_krw,
                 debit_account,credit_account,cost_type,vat_tag,evidence_label,
                 batch_status,posting_status,posting_eligible,external_posting,
                 batch_sha256,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,'KRW',?,?,?,?,?,?,'draft_balanced','draft',0,0,?,?)""",
            (
                row["batch_id"], row["source_draft_id"], row["payment_id"],
                row["booking_id"], row["allocation_id"], row["target_id"],
                row["trip_code"], row["accounting_period"], row["posting_date"],
                row["amount_krw"], row["debit_account"], row["credit_account"],
                row["cost_type"], row["vat_tag"], row["evidence_label"],
                row["batch_sha256"], row["payload_json"],
            ),
        )
    for row in lines:
        insert_exact(
            db,
            """INSERT OR IGNORE INTO direct_agoda_journal_draft_lines(
                 batch_id,line_no,side,account_code,amount_krw,payment_id,booking_id,
                 allocation_id,trip_code,accounting_period,posting_date,ledger_currency,
                 vat_tag,line_sha256,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'KRW',?,?,?)""",
            (
                row["batch_id"], row["line_no"], row["side"], row["account_code"],
                row["amount_krw"], row["payment_id"], row["booking_id"],
                row["allocation_id"], row["trip_code"], row["accounting_period"],
                row["posting_date"], row["vat_tag"], row["line_sha256"],
                row["payload_json"],
            ),
        )
    debit_total = sum(int(row["amount_krw"]) for row in lines if row["side"] == "debit")
    credit_total = sum(
        int(row["amount_krw"]) for row in lines if row["side"] == "credit"
    )
    manifest_payload = {
        "rule_id": RULE_ID,
        "source_database_sha256": source_database_sha256,
        "batch_count": len(batches),
        "line_count": len(lines),
        "unresolved_count": len(resolutions),
        "debit_total_krw": debit_total,
        "credit_total_krw": credit_total,
        "batch_set_sha256": content_sha256(sorted(row["batch_id"] for row in batches)),
        "resolution_set_sha256": content_sha256(
            sorted(row["resolution_id"] for row in resolutions)
        ),
        "posting_status": "draft_balanced",
        "authoritative_posting": False,
        "external_posting": False,
    }
    manifest_id = content_sha256(manifest_payload)
    insert_exact(
        db,
        """INSERT OR IGNORE INTO direct_agoda_journal_draft_manifests(
             manifest_id,source_database_sha256,batch_count,line_count,unresolved_count,
             debit_total_krw,credit_total_krw,batch_set_sha256,resolution_set_sha256,
             posting_status,authoritative_posting,payload_json)
           VALUES (?,?,?,?,?,?,?,?,?,'draft_balanced',0,?)""",
        (
            manifest_id, source_database_sha256, len(batches), len(lines),
            len(resolutions), debit_total, credit_total,
            manifest_payload["batch_set_sha256"],
            manifest_payload["resolution_set_sha256"], canonical_json(manifest_payload),
        ),
    )
    return db.total_changes - before


def semantic_snapshot(db: sqlite3.Connection) -> dict[str, object]:
    queries = {
        "resolutions": """SELECT resolution_id,source_draft_id,payment_id,booking_id,
            booking_number,amount_krw,current_match_status,suggested_target,
            resolution_status,authority_status,posting_status,posting_eligible,
            resolution_sha256 FROM direct_agoda_target_resolution_candidates
            ORDER BY booking_number""",
        "evidence": """SELECT evidence_id,resolution_id,source_kind,source_path,
            source_file_sha256,source_locator,source_evidence_sha256
            FROM direct_agoda_target_resolution_evidence ORDER BY evidence_id""",
        "batches": """SELECT batch_id,source_draft_id,payment_id,booking_id,
            allocation_id,target_id,trip_code,accounting_period,posting_date,
            amount_krw,debit_account,credit_account,cost_type,vat_tag,batch_status,
            posting_status,posting_eligible,external_posting,batch_sha256
            FROM direct_agoda_journal_draft_batches ORDER BY payment_id""",
        "lines": """SELECT batch_id,line_no,side,account_code,amount_krw,payment_id,
            booking_id,allocation_id,trip_code,accounting_period,posting_date,
            vat_tag,line_sha256 FROM direct_agoda_journal_draft_lines
            ORDER BY payment_id,line_no""",
        "manifest": """SELECT manifest_id,source_database_sha256,batch_count,line_count,
            unresolved_count,debit_total_krw,credit_total_krw,batch_set_sha256,
            resolution_set_sha256,posting_status,authoritative_posting
            FROM direct_agoda_journal_draft_manifests""",
    }
    return {key: [list(row) for row in db.execute(sql)] for key, sql in queries.items()}


def validate_materialized(
    db: sqlite3.Connection,
    scope: list[dict[str, object]],
    resolutions: list[dict[str, object]],
    evidence_rows: list[dict[str, object]],
    batches: list[dict[str, object]],
    lines: list[dict[str, object]],
) -> dict[str, object]:
    unique = [row for row in scope if row["target_match_status"] == "unique_service_period"]
    unresolved = [row for row in scope if row["target_match_status"] != "unique_service_period"]
    expected_total = sum(int(row["amount_krw"]) for row in unique)
    counts = {
        "source_scope": len(scope),
        "resolution_candidates": table_count(db, "direct_agoda_target_resolution_candidates"),
        "resolution_evidence": table_count(db, "direct_agoda_target_resolution_evidence"),
        "journal_draft_batches": table_count(db, "direct_agoda_journal_draft_batches"),
        "journal_draft_lines": table_count(db, "direct_agoda_journal_draft_lines"),
        "journal_draft_manifests": table_count(db, "direct_agoda_journal_draft_manifests"),
        "legacy_journal_entries": table_count(db, "journal_entries"),
    }
    expected_counts = {
        "source_scope": len(scope),
        "resolution_candidates": len(resolutions),
        "resolution_evidence": len(evidence_rows),
        "journal_draft_batches": len(batches),
        "journal_draft_lines": len(lines),
        "journal_draft_manifests": 1,
        "legacy_journal_entries": 0,
    }
    totals = db.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN side='debit' THEN amount_krw END),0),
             COALESCE(SUM(CASE WHEN side='credit' THEN amount_krw END),0)
           FROM direct_agoda_journal_draft_lines"""
    ).fetchone()
    unauthorized = int(
        db.execute(
            """SELECT
               (SELECT COUNT(*) FROM direct_agoda_journal_draft_batches
                 WHERE posting_status<>'draft' OR posting_eligible<>0 OR external_posting<>0)+
               (SELECT COUNT(*) FROM direct_agoda_target_resolution_candidates
                 WHERE authority_status<>'candidate_only' OR posting_status<>'blocked'
                    OR posting_eligible<>0)+
               (SELECT COUNT(*) FROM classification_decisions
                 WHERE decision_status='confirmed')+
               (SELECT COUNT(*) FROM allocation_plans WHERE plan_status='confirmed')+
               (SELECT COUNT(*) FROM payment_booking_links WHERE link_status='confirmed')"""
        ).fetchone()[0]
    )
    unresolved_in_journal = int(
        db.execute(
            """SELECT COUNT(*) FROM direct_agoda_journal_draft_batches j
               JOIN direct_agoda_accounting_draft_authorities a
                 ON a.draft_id=j.source_draft_id
               WHERE a.target_match_status<>'unique_service_period'"""
        ).fetchone()[0]
    )
    line_pair_issues = int(
        db.execute(
            """SELECT COUNT(*) FROM (
                 SELECT batch_id,COUNT(*) n,
                        SUM(CASE WHEN side='debit' THEN amount_krw ELSE 0 END) d,
                        SUM(CASE WHEN side='credit' THEN amount_krw ELSE 0 END) c
                 FROM direct_agoda_journal_draft_lines GROUP BY batch_id
                 HAVING n<>2 OR d<>c
               )"""
        ).fetchone()[0]
    )
    posting_table_rows = sum(
        table_count(db, name)
        for name in (
            "direct_accounting_posting_batches",
            "direct_accounting_posting_lines",
            "direct_accounting_posting_manifests",
        )
    )
    resolution_status_counts = {
        str(row[0]): int(row[1])
        for row in db.execute(
            """SELECT resolution_status,COUNT(*)
               FROM direct_agoda_target_resolution_candidates
               GROUP BY resolution_status ORDER BY resolution_status"""
        )
    }
    issues: list[str] = []
    if counts != expected_counts:
        issues.append("journal_draft_table_count_mismatch")
    if len(unique) != len(batches) or len(unresolved) != len(resolutions):
        issues.append("journal_draft_scope_partition_mismatch")
    if int(totals[0]) != expected_total or int(totals[1]) != expected_total:
        issues.append("journal_draft_total_mismatch")
    if unauthorized:
        issues.append("journal_draft_authority_leak")
    if unresolved_in_journal:
        issues.append("unresolved_target_journal_leak")
    if line_pair_issues:
        issues.append("journal_draft_unbalanced_batch")
    if posting_table_rows:
        issues.append("authoritative_posting_table_leak")
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        issues.append("integrity_check_failed")
    foreign_keys = [list(row) for row in db.execute("PRAGMA foreign_key_check")]
    if foreign_keys:
        issues.append("foreign_key_check_failed")
    return {
        "passed": not issues,
        "issues": issues,
        "counts": counts,
        "expected_counts": expected_counts,
        "unique_scope_count": len(unique),
        "unresolved_scope_count": len(unresolved),
        "debit_total_krw": int(totals[0]),
        "credit_total_krw": int(totals[1]),
        "expected_total_krw": expected_total,
        "unauthorized_rows": unauthorized,
        "unresolved_in_journal": unresolved_in_journal,
        "line_pair_issues": line_pair_issues,
        "posting_table_rows": posting_table_rows,
        "resolution_status_counts": resolution_status_counts,
        "foreign_key_violations": foreign_keys,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-db", default="outputs/agoda-card-accounting-draft-v1-20260824.sqlite"
    )
    parser.add_argument(
        "--input-audit",
        default="outputs/agoda-card-accounting-draft-audit-v1-20260824.json",
    )
    parser.add_argument("--historical", default="ledger/data/classified_v14.csv")
    parser.add_argument("--property-evidence", default="outputs/agoda-paseo-staging.json")
    parser.add_argument(
        "--output-db", default="outputs/agoda-card-journal-draft-v1-20260824.sqlite"
    )
    parser.add_argument(
        "--output-detail", default="outputs/agoda-card-journal-draft-detail-v1-20260824.json"
    )
    parser.add_argument(
        "--output-audit", default="outputs/agoda-card-journal-draft-audit-v1-20260824.json"
    )
    args = parser.parse_args()

    input_db = (ROOT / args.input_db).resolve()
    input_audit = (ROOT / args.input_audit).resolve()
    historical_path = (ROOT / args.historical).resolve()
    property_path = (ROOT / args.property_evidence).resolve()
    output_db = (ROOT / args.output_db).resolve()
    output_detail = (ROOT / args.output_detail).resolve()
    output_audit = (ROOT / args.output_audit).resolve()
    for path in (input_db, input_audit, historical_path, property_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (output_db, output_detail, output_audit):
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    audit, source_database_sha, source_audit_sha = validate_input_audit(
        input_audit, input_db
    )
    read_db = sqlite3.connect(f"file:{input_db.as_posix()}?mode=ro", uri=True)
    read_db.row_factory = sqlite3.Row
    try:
        scope = load_scope(read_db)
    finally:
        read_db.close()
    target_counts = {
        status: sum(row["target_match_status"] == status for row in scope)
        for status in {
            "unique_service_period",
            "service_target_ambiguous",
            "service_target_missing",
        }
    }
    if audit.get("target_match_counts") != target_counts:
        raise ValueError("accounting_draft_target_counts_mismatch")
    unresolved = [
        row for row in scope if row["target_match_status"] != "unique_service_period"
    ]
    booking_numbers = [str(row["booking_number"]) for row in unresolved]
    historical_sha = file_sha256(historical_path)
    property_sha = file_sha256(property_path)
    historical = index_historical_rows(historical_path, booking_numbers)
    properties = index_property_rows(property_path, booking_numbers)
    resolutions, evidence_rows = build_resolution_rows(
        unresolved,
        historical,
        properties,
        historical_path=relative(historical_path),
        historical_sha256=historical_sha,
        property_path=relative(property_path),
        property_sha256=property_sha,
    )
    batches, lines = build_journal_rows(scope, source_database_sha)

    copy_database(input_db, output_db)
    db = sqlite3.connect(output_db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        create_tables(db)
        db.commit()
        first_changes = materialize(
            db, resolutions, evidence_rows, batches, lines, source_database_sha
        )
        db.commit()
        before_second = db.total_changes
        second_changes = materialize(
            db, resolutions, evidence_rows, batches, lines, source_database_sha
        )
        db.commit()
        second_total_changes = db.total_changes - before_second
        snapshot = semantic_snapshot(db)
        semantic_sha = content_sha256(snapshot)
        validation = validate_materialized(
            db, scope, resolutions, evidence_rows, batches, lines
        )
    finally:
        db.close()

    with tempfile.TemporaryDirectory(prefix="agoda-journal-rebuild-") as temp_dir:
        rebuilt_path = Path(temp_dir) / "rebuilt.sqlite"
        copy_database(input_db, rebuilt_path)
        rebuilt = sqlite3.connect(rebuilt_path)
        rebuilt.row_factory = sqlite3.Row
        rebuilt.execute("PRAGMA foreign_keys=ON")
        try:
            create_tables(rebuilt)
            rebuilt.commit()
            materialize(
                rebuilt, resolutions, evidence_rows, batches, lines, source_database_sha
            )
            rebuilt.commit()
            rebuilt_semantic_sha = content_sha256(semantic_snapshot(rebuilt))
        finally:
            rebuilt.close()

    detail = {
        "artifact_kind": "agoda_card_journal_draft_detail",
        "artifact_version": "v1",
        "journal_batches": batches,
        "journal_lines": lines,
        "target_resolution_candidates": resolutions,
        "target_resolution_evidence": evidence_rows,
    }
    write_json(output_detail, detail)
    result = {
        "artifact_kind": "agoda_card_journal_draft_audit",
        "artifact_version": "v1",
        "rule_id": RULE_ID,
        "builder": {
            "path": relative(Path(__file__)),
            "sha256": file_sha256(Path(__file__)),
        },
        "inputs": {
            "database": relative(input_db),
            "database_sha256": source_database_sha,
            "audit": relative(input_audit),
            "audit_sha256": source_audit_sha,
            "historical_candidate_source": relative(historical_path),
            "historical_candidate_source_sha256": historical_sha,
            "property_evidence_source": relative(property_path),
            "property_evidence_source_sha256": property_sha,
        },
        "outputs": {
            "database": relative(output_db),
            "database_sha256": file_sha256(output_db),
            "detail": relative(output_detail),
            "detail_sha256": file_sha256(output_detail),
            "semantic_sha256": semantic_sha,
        },
        "counts": validation["counts"],
        "resolution_status_counts": validation["resolution_status_counts"],
        "amounts": {
            "debit_total_krw": validation["debit_total_krw"],
            "credit_total_krw": validation["credit_total_krw"],
            "expected_total_krw": validation["expected_total_krw"],
        },
        "checks": {
            "validation_passed": validation["passed"],
            "validation_issues": validation["issues"],
            "first_materialization_changes": first_changes,
            "second_materialization_changes": second_changes,
            "second_total_changes": second_total_changes,
            "semantic_idempotent": second_total_changes == 0,
            "independent_rebuild_semantic_sha256": rebuilt_semantic_sha,
            "independent_rebuild_matches": rebuilt_semantic_sha == semantic_sha,
            "input_database_unchanged": file_sha256(input_db) == source_database_sha,
            "unauthorized_rows": validation["unauthorized_rows"],
            "unresolved_in_journal": validation["unresolved_in_journal"],
            "line_pair_issues": validation["line_pair_issues"],
            "posting_table_rows": validation["posting_table_rows"],
            "foreign_key_violations": validation["foreign_key_violations"],
        },
        "authority": {
            "journal_status": "draft_balanced",
            "authoritative_posting_written": False,
            "legacy_journal_entries_written": 0,
            "historical_evidence_status": "candidate_only",
            "unresolved_posting_status": "blocked",
        },
    }
    if not all(
        (
            result["checks"]["validation_passed"],
            result["checks"]["semantic_idempotent"],
            result["checks"]["independent_rebuild_matches"],
            result["checks"]["input_database_unchanged"],
            result["checks"]["unauthorized_rows"] == 0,
            result["checks"]["unresolved_in_journal"] == 0,
            result["checks"]["line_pair_issues"] == 0,
            result["checks"]["posting_table_rows"] == 0,
            not result["checks"]["foreign_key_violations"],
        )
    ):
        raise RuntimeError("agoda_journal_draft_audit_failed")
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
