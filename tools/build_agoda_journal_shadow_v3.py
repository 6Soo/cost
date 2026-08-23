"""Build a balanced, non-posting journal shadow from accounting draft v3.

The v3 shadow keeps payment year and service/event assignment separate.  It
uses ``숙박비`` only for an explicit authoritative unique schedule match; all
legacy-window-only, ambiguous, or missing rows debit ``미확정여행원가`` and
remain ``여행_미배정``.  No journal or posting table is written.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.direct_trip_schedule_authority import (
    canonical_json,
    file_sha256,
    sha256_value,
)
from tools.build_agoda_accounting_draft import copy_database, table_count, table_names


RULE_ID = "agoda-linked-lodging-journal-shadow-v3"
BOUND_DEBIT_ACCOUNT = "숙박비"
UNRESOLVED_DEBIT_ACCOUNT = "미확정여행원가"
CREDIT_ACCOUNT = "법인카드미지급금"
UNASSIGNED_TARGET = "여행_미배정"


def _load_audit(path: Path, database: Path) -> tuple[dict[str, Any], str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("artifact_kind") != "agoda_accounting_draft_v3":
        raise ValueError("v3_journal_input_audit_invalid")
    database_sha256 = file_sha256(database)
    if raw.get("database_sha256") != database_sha256:
        raise ValueError("v3_journal_input_database_sha256_mismatch")
    if int(raw.get("posting_eligible", 1)) != 0:
        raise ValueError("v3_journal_input_posting_state_invalid")
    return raw, database_sha256


def create_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE direct_agoda_journal_shadow_v3_batches(
          batch_id TEXT PRIMARY KEY CHECK(length(batch_id)=64),
          draft_id TEXT NOT NULL UNIQUE
            REFERENCES direct_agoda_accounting_draft_v3_authorities(draft_id),
          payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL REFERENCES bookings(id),
          booking_number TEXT NOT NULL,
          payment_lane TEXT NOT NULL,
          payment_year INTEGER NOT NULL,
          service_year INTEGER NOT NULL,
          target_match_status TEXT NOT NULL,
          assigned_target TEXT NOT NULL,
          suggested_targets_json TEXT NOT NULL,
          target_authority TEXT NOT NULL,
          shadow_cohort TEXT NOT NULL CHECK(shadow_cohort IN ('target_bound','target_unresolved')),
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          debit_account TEXT NOT NULL CHECK(debit_account IN ('숙박비','미확정여행원가')),
          credit_account TEXT NOT NULL CHECK(credit_account='법인카드미지급금'),
          cost_type TEXT NOT NULL CHECK(cost_type='여행원가'),
          posting_date TEXT NOT NULL,
          posting_status TEXT NOT NULL CHECK(posting_status='shadow_only'),
          posting_eligible INTEGER NOT NULL CHECK(posting_eligible=0),
          authoritative_posting INTEGER NOT NULL CHECK(authoritative_posting=0),
          external_posting INTEGER NOT NULL CHECK(external_posting=0),
          batch_sha256 TEXT NOT NULL UNIQUE CHECK(length(batch_sha256)=64),
          payload_json TEXT NOT NULL
        );

        CREATE TABLE direct_agoda_journal_shadow_v3_lines(
          batch_id TEXT NOT NULL REFERENCES direct_agoda_journal_shadow_v3_batches(batch_id),
          line_no INTEGER NOT NULL CHECK(line_no IN (1,2)),
          side TEXT NOT NULL CHECK(side IN ('debit','credit')),
          account_code TEXT NOT NULL,
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL REFERENCES bookings(id),
          assigned_target TEXT NOT NULL,
          payment_lane TEXT NOT NULL,
          posting_date TEXT NOT NULL,
          line_sha256 TEXT NOT NULL UNIQUE CHECK(length(line_sha256)=64),
          payload_json TEXT NOT NULL,
          PRIMARY KEY(batch_id,line_no)
        );

        CREATE TABLE direct_agoda_journal_shadow_v3_manifest(
          manifest_id TEXT PRIMARY KEY CHECK(length(manifest_id)=64),
          source_database_sha256 TEXT NOT NULL CHECK(length(source_database_sha256)=64),
          input_audit_sha256 TEXT NOT NULL CHECK(length(input_audit_sha256)=64),
          batch_count INTEGER NOT NULL CHECK(batch_count>=0),
          line_count INTEGER NOT NULL CHECK(line_count>=0),
          target_bound_count INTEGER NOT NULL CHECK(target_bound_count>=0),
          target_unresolved_count INTEGER NOT NULL CHECK(target_unresolved_count>=0),
          target_bound_total_krw INTEGER NOT NULL CHECK(target_bound_total_krw>=0),
          target_unresolved_total_krw INTEGER NOT NULL CHECK(target_unresolved_total_krw>=0),
          debit_total_krw INTEGER NOT NULL CHECK(debit_total_krw>=0),
          credit_total_krw INTEGER NOT NULL CHECK(credit_total_krw>=0),
          posting_status TEXT NOT NULL CHECK(posting_status='shadow_only'),
          authoritative_posting INTEGER NOT NULL CHECK(authoritative_posting=0),
          external_posting INTEGER NOT NULL CHECK(external_posting=0),
          payload_json TEXT NOT NULL
        );
        """
    )


def build_rows(db: sqlite3.Connection, source_database_sha256: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cursor = db.execute(
        """SELECT draft_id,payment_id,booking_id,booking_number,amount_krw,
                  payment_lane,payment_year,service_year,occurred_on,
                  target_match_status,target_authority,allocation_target,
                  legacy_window_candidate_targets_json,authority_candidate_targets_json
           FROM direct_agoda_accounting_draft_v3_authorities ORDER BY payment_id"""
    )
    column_names = [str(item[0]) for item in cursor.description]
    rows = [dict(zip(column_names, row)) for row in cursor.fetchall()]
    if not rows:
        raise ValueError("v3_journal_scope_empty")
    batches: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        bound = (
            item["target_match_status"] == "bound_unique"
            and item["target_authority"] == "authoritative_explicit_period"
            and item["allocation_target"] != UNASSIGNED_TARGET
        )
        shadow_cohort = "target_bound" if bound else "target_unresolved"
        assigned_target = str(item["allocation_target"]) if bound else UNASSIGNED_TARGET
        debit_account = BOUND_DEBIT_ACCOUNT if bound else UNRESOLVED_DEBIT_ACCOUNT
        suggested = json.loads(
            item["authority_candidate_targets_json"]
            if item["authority_candidate_targets_json"] != "[]"
            else item["legacy_window_candidate_targets_json"]
        )
        payload = {
            "rule_id": RULE_ID,
            "source_database_sha256": source_database_sha256,
            "draft_id": str(item["draft_id"]),
            "payment_id": int(item["payment_id"]),
            "booking_id": int(item["booking_id"]),
            "booking_number": str(item["booking_number"]),
            "payment_lane": str(item["payment_lane"]),
            "payment_year": int(item["payment_year"]),
            "service_year": int(item["service_year"]),
            "target_match_status": str(item["target_match_status"]),
            "assigned_target": assigned_target,
            "suggested_targets": suggested,
            "target_authority": str(item["target_authority"]),
            "shadow_cohort": shadow_cohort,
            "occurred_on": str(item["occurred_on"]),
            "amount_krw": int(item["amount_krw"]),
            "debit_account": debit_account,
            "credit_account": CREDIT_ACCOUNT,
            "cost_type": "여행원가",
            "posting_status": "shadow_only",
            "posting_eligible": False,
            "authoritative_posting": False,
            "external_posting": False,
        }
        batch_id = sha256_value(payload)
        batch = {
            **item,
            **payload,
            "batch_id": batch_id,
            "batch_sha256": batch_id,
            "payload_json": canonical_json(payload),
            "assigned_target": assigned_target,
            "debit_account": debit_account,
            "shadow_cohort": shadow_cohort,
        }
        batches.append(batch)
        for line_no, side, account in (
            (1, "debit", debit_account), (2, "credit", CREDIT_ACCOUNT)
        ):
            line_payload = {
                "rule_id": RULE_ID,
                "batch_id": batch_id,
                "line_no": line_no,
                "side": side,
                "account_code": account,
                "amount_krw": int(item["amount_krw"]),
                "payment_id": int(item["payment_id"]),
                "booking_id": int(item["booking_id"]),
                "assigned_target": assigned_target,
                "payment_lane": str(item["payment_lane"]),
                "posting_date": str(item["occurred_on"]),
                "posting_status": "shadow_only",
            }
            line_sha256 = sha256_value(line_payload)
            lines.append(
                {
                    **line_payload,
                    "line_sha256": line_sha256,
                    "payload_json": canonical_json(line_payload),
                }
            )
    return batches, lines


def materialize(
    db: sqlite3.Connection,
    batches: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    source_database_sha256: str,
    input_audit_sha256: str,
) -> dict[str, Any]:
    for row in batches:
        db.execute(
            """INSERT INTO direct_agoda_journal_shadow_v3_batches(
              batch_id,draft_id,payment_id,booking_id,booking_number,payment_lane,
              payment_year,service_year,target_match_status,assigned_target,
              suggested_targets_json,target_authority,shadow_cohort,amount_krw,
              debit_account,credit_account,cost_type,posting_date,posting_status,
              posting_eligible,authoritative_posting,external_posting,batch_sha256,
              payload_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["batch_id"], row["draft_id"], row["payment_id"], row["booking_id"],
                row["booking_number"], row["payment_lane"], row["payment_year"],
                row["service_year"], row["target_match_status"], row["assigned_target"],
                canonical_json(row["suggested_targets"]), row["target_authority"],
                row["shadow_cohort"], row["amount_krw"], row["debit_account"],
                CREDIT_ACCOUNT, "여행원가", row["occurred_on"], "shadow_only", 0, 0, 0,
                row["batch_sha256"], row["payload_json"],
            ),
        )
    for row in lines:
        db.execute(
            """INSERT INTO direct_agoda_journal_shadow_v3_lines(
              batch_id,line_no,side,account_code,amount_krw,payment_id,booking_id,
              assigned_target,payment_lane,posting_date,line_sha256,payload_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["batch_id"], row["line_no"], row["side"], row["account_code"],
                row["amount_krw"], row["payment_id"], row["booking_id"],
                row["assigned_target"], row["payment_lane"], row["posting_date"],
                row["line_sha256"], row["payload_json"],
            ),
        )
    target_bound = [row for row in batches if row["shadow_cohort"] == "target_bound"]
    unresolved = [row for row in batches if row["shadow_cohort"] == "target_unresolved"]
    debit_total = sum(int(row["amount_krw"]) for row in batches)
    payload = {
        "rule_id": RULE_ID,
        "source_database_sha256": source_database_sha256,
        "input_audit_sha256": input_audit_sha256,
        "batch_count": len(batches),
        "line_count": len(lines),
        "target_bound_count": len(target_bound),
        "target_unresolved_count": len(unresolved),
        "target_bound_total_krw": sum(int(row["amount_krw"]) for row in target_bound),
        "target_unresolved_total_krw": sum(int(row["amount_krw"]) for row in unresolved),
        "debit_total_krw": debit_total,
        "credit_total_krw": debit_total,
        "posting_status": "shadow_only",
        "authoritative_posting": False,
        "external_posting": False,
    }
    manifest_id = sha256_value(payload)
    db.execute(
        """INSERT INTO direct_agoda_journal_shadow_v3_manifest(
          manifest_id,source_database_sha256,input_audit_sha256,batch_count,line_count,
          target_bound_count,target_unresolved_count,target_bound_total_krw,
          target_unresolved_total_krw,debit_total_krw,credit_total_krw,posting_status,
          authoritative_posting,external_posting,payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            manifest_id, source_database_sha256, input_audit_sha256, len(batches),
            len(lines), len(target_bound), len(unresolved),
            payload["target_bound_total_krw"], payload["target_unresolved_total_krw"],
            debit_total, debit_total, "shadow_only", 0, 0, canonical_json(payload),
        ),
    )
    return {**payload, "manifest_id": manifest_id}


def build_artifact(
    input_database: Path,
    input_audit: Path,
    output_database: Path,
    detail_output: Path,
    audit_output: Path,
) -> dict[str, Any]:
    if output_database.exists():
        raise ValueError(f"output_exists:{output_database}")
    input_audit_payload, source_database_sha256 = _load_audit(input_audit, input_database)
    input_audit_sha256 = file_sha256(input_audit)
    copy_database(input_database, output_database)
    db = sqlite3.connect(output_database)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        if "direct_agoda_accounting_draft_v3_authorities" not in table_names(db):
            raise ValueError("v3_accounting_table_missing")
        create_tables(db)
        batches, lines = build_rows(db, source_database_sha256)
        summary = materialize(
            db, batches, lines, source_database_sha256, input_audit_sha256
        )
        db.commit()
        integrity = [str(row[0]) for row in db.execute("PRAGMA integrity_check")]
        foreign_keys = [list(row) for row in db.execute("PRAGMA foreign_key_check")]
        if integrity != ["ok"] or foreign_keys:
            raise ValueError("v3_journal_database_integrity_failed")
        summary.update(
            {
                "artifact_kind": "agoda_journal_shadow_v3",
                "database_sha256": file_sha256(output_database),
                "input_audit_artifact_sha256": input_audit_sha256,
                "input_audit_manifest_id": input_audit_payload.get("manifest_id"),
                "integrity_check": integrity,
                "foreign_key_check": foreign_keys,
                "posting_tables_present": {
                    name: table_count(db, name)
                    for name in (
                        "journal_entries",
                        "direct_accounting_posting_batches",
                        "direct_accounting_posting_lines",
                    )
                },
            }
        )
        detail_output.write_text(
            json.dumps(
                {"summary": summary, "batches": batches, "lines": lines},
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        audit_output.write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return summary
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-database", type=Path, required=True)
    parser.add_argument("--input-audit", type=Path, required=True)
    parser.add_argument("--output-database", type=Path, required=True)
    parser.add_argument("--detail-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()
    result = build_artifact(
        args.input_database.resolve(), args.input_audit.resolve(),
        args.output_database.resolve(), args.detail_output.resolve(),
        args.audit_output.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
