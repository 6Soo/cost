"""Build a complete, balanced Agoda accounting shadow for all linked bookings.

The command consumes the immutable v1 Agoda journal-draft database.  It copies
that database and adds a separate v2 shadow layer covering the complete
77-payment scope:

* uniquely schedule-bound rows debit ``숙박비``;
* unresolved rows debit ``미확정여행원가``;
* every row credits ``법인카드미지급금``.

This is a local proof of balanced accounting coverage, not a posting command.
Every batch is permanently marked ``shadow_only`` with posting eligibility,
authoritative posting, and external posting all set to false.  The command
never writes ``journal_entries`` or ``direct_accounting_posting_*`` tables.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
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
from tools.build_agoda_journal_draft import load_json, load_scope


RULE_ID = "agoda-linked-lodging-journal-shadow-v2"
BOUND_DEBIT_ACCOUNT = "숙박비"
UNRESOLVED_DEBIT_ACCOUNT = "미확정여행원가"
CREDIT_ACCOUNT = "법인카드미지급금"
COST_TYPE = "여행원가"
VAT_TAG = "불공제_해외"
LEDGER_CURRENCY = "KRW"
UNASSIGNED_TARGET = "여행_미배정"


def validate_input_audit(
    audit_path: Path,
    database_path: Path,
) -> tuple[dict[str, object], str, str]:
    raw = load_json(audit_path)
    if not isinstance(raw, dict):
        raise ValueError("journal_shadow_input_audit_root_invalid")
    if raw.get("artifact_kind") != "agoda_card_journal_draft_audit":
        raise ValueError("journal_shadow_input_audit_kind_invalid")
    checks = raw.get("checks")
    counts = raw.get("counts")
    outputs = raw.get("outputs")
    authority = raw.get("authority")
    if not all(isinstance(value, dict) for value in (checks, counts, outputs, authority)):
        raise ValueError("journal_shadow_input_audit_shape_invalid")

    database_sha = file_sha256(database_path)
    audit_sha = file_sha256(audit_path)
    if outputs.get("database_sha256") != database_sha:
        raise ValueError("journal_shadow_input_database_sha256_mismatch")
    required_true = (
        "validation_passed",
        "semantic_idempotent",
        "independent_rebuild_matches",
        "input_database_unchanged",
    )
    if not all(checks.get(key) is True for key in required_true):
        raise ValueError("journal_shadow_input_audit_not_passed")
    if any(
        int(checks.get(key, -1)) != 0
        for key in (
            "unauthorized_rows",
            "unresolved_in_journal",
            "line_pair_issues",
            "posting_table_rows",
        )
    ):
        raise ValueError("journal_shadow_input_authority_leak")
    source_scope = int(counts.get("source_scope", -1))
    journal_batches = int(counts.get("journal_draft_batches", -1))
    journal_lines = int(counts.get("journal_draft_lines", -1))
    resolutions = int(counts.get("resolution_candidates", -1))
    if source_scope <= 0 or source_scope != journal_batches + resolutions:
        raise ValueError("journal_shadow_input_scope_partition_invalid")
    if journal_lines != journal_batches * 2:
        raise ValueError("journal_shadow_input_line_count_invalid")
    if authority.get("authoritative_posting_written") is not False:
        raise ValueError("journal_shadow_input_posting_state_invalid")
    if int(authority.get("legacy_journal_entries_written", -1)) != 0:
        raise ValueError("journal_shadow_input_legacy_journal_state_invalid")
    if authority.get("unresolved_posting_status") != "blocked":
        raise ValueError("journal_shadow_input_unresolved_state_invalid")
    return raw, database_sha, audit_sha


def load_resolution_map(db: sqlite3.Connection) -> dict[str, dict[str, object]]:
    required = {
        "direct_agoda_target_resolution_candidates",
        "direct_agoda_target_resolution_evidence",
    }
    missing = required - table_names(db)
    if missing:
        raise ValueError(f"journal_shadow_resolution_tables_missing:{sorted(missing)}")
    rows = db.execute(
        """SELECT resolution_id,source_draft_id,payment_id,booking_id,
                  current_match_status,suggested_target,resolution_status,
                  authority_status,posting_status,posting_eligible,
                  resolution_sha256
             FROM direct_agoda_target_resolution_candidates
            ORDER BY payment_id"""
    ).fetchall()
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        source_draft_id = str(row[1])
        if source_draft_id in result:
            raise ValueError(f"journal_shadow_resolution_duplicate:{source_draft_id}")
        if (
            str(row[7]) != "candidate_only"
            or str(row[8]) != "blocked"
            or int(row[9]) != 0
            or len(str(row[0])) != 64
            or len(str(row[10])) != 64
        ):
            raise ValueError(f"journal_shadow_resolution_contract_invalid:{source_draft_id}")
        result[source_draft_id] = {
            "resolution_id": str(row[0]),
            "source_draft_id": source_draft_id,
            "payment_id": int(row[2]),
            "booking_id": int(row[3]),
            "current_match_status": str(row[4]),
            "suggested_target": None if row[5] is None else str(row[5]),
            "resolution_status": str(row[6]),
            "resolution_sha256": str(row[10]),
        }
    return result


def build_shadow_rows(
    scope: Iterable[dict[str, object]],
    resolutions: Mapping[str, Mapping[str, object]],
    source_database_sha256: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    batches: list[dict[str, object]] = []
    lines: list[dict[str, object]] = []
    used_resolutions: set[str] = set()

    for source in sorted(scope, key=lambda row: int(row["payment_id"])):
        posting_date = str(source["occurred_on"])
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", posting_date):
            raise ValueError(f"journal_shadow_posting_date_invalid:{source['payment_id']}")
        source_draft_id = str(source["source_draft_id"])
        target_match_status = str(source["target_match_status"])
        resolution = resolutions.get(source_draft_id)

        if target_match_status == "unique_service_period":
            if (
                source["target_type"] != "trip"
                or float(source["plan_confidence"]) != 1.0
                or resolution is not None
            ):
                raise ValueError(
                    f"journal_shadow_bound_contract_invalid:{source['payment_id']}"
                )
            shadow_cohort = "target_bound"
            debit_account = BOUND_DEBIT_ACCOUNT
            assigned_target = str(source["allocation_target"])
            suggested_target = None
            resolution_id = None
            resolution_status = None
            target_authority = "bound_unique"
            release_gate = "proposed_link_and_classification_confirmation"
        else:
            if (
                target_match_status
                not in {"service_target_ambiguous", "service_target_missing"}
                or source["target_type"] != "unassigned"
                or float(source["plan_confidence"]) != 0.0
                or str(source["allocation_target"]) != UNASSIGNED_TARGET
                or resolution is None
                or str(resolution["current_match_status"]) != target_match_status
                or int(resolution["payment_id"]) != int(source["payment_id"])
                or int(resolution["booking_id"]) != int(source["booking_id"])
            ):
                raise ValueError(
                    f"journal_shadow_unresolved_contract_invalid:{source['payment_id']}"
                )
            shadow_cohort = "target_unresolved"
            debit_account = UNRESOLVED_DEBIT_ACCOUNT
            assigned_target = UNASSIGNED_TARGET
            suggested_target = resolution["suggested_target"]
            resolution_id = str(resolution["resolution_id"])
            resolution_status = str(resolution["resolution_status"])
            target_authority = "candidate_only" if suggested_target else "none"
            release_gate = "target_resolution_and_authority_confirmation"
            used_resolutions.add(source_draft_id)

        payload = {
            "rule_id": RULE_ID,
            "source_database_sha256": source_database_sha256,
            "source_draft_id": source_draft_id,
            "payment_id": int(source["payment_id"]),
            "booking_id": int(source["booking_id"]),
            "booking_number": str(source["booking_number"]),
            "allocation_id": int(source["allocation_id"]),
            "target_id": int(source["target_id"]),
            "target_match_status": target_match_status,
            "assigned_target": assigned_target,
            "suggested_target": suggested_target,
            "resolution_id": resolution_id,
            "resolution_status": resolution_status,
            "target_authority": target_authority,
            "shadow_cohort": shadow_cohort,
            "posting_date": posting_date,
            "accounting_period": posting_date[:7],
            "ledger_currency": LEDGER_CURRENCY,
            "amount_krw": int(source["amount_krw"]),
            "debit_account": debit_account,
            "credit_account": CREDIT_ACCOUNT,
            "cost_type": COST_TYPE,
            "vat_tag": VAT_TAG,
            "release_gate": release_gate,
            "batch_status": "shadow_balanced",
            "posting_status": "shadow_only",
            "posting_eligible": False,
            "authoritative_posting": False,
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
        for line_no, (side, account_code) in enumerate(
            (("debit", debit_account), ("credit", CREDIT_ACCOUNT)), start=1
        ):
            line_payload = {
                "batch_id": batch_id,
                "line_no": line_no,
                "side": side,
                "account_code": account_code,
                "amount_krw": int(source["amount_krw"]),
                "payment_id": int(source["payment_id"]),
                "booking_id": int(source["booking_id"]),
                "allocation_id": int(source["allocation_id"]),
                "assigned_target": assigned_target,
                "shadow_cohort": shadow_cohort,
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

    if used_resolutions != set(resolutions):
        unused = sorted(set(resolutions) - used_resolutions)
        raise ValueError(f"journal_shadow_resolution_scope_mismatch:{unused[:3]}")
    if len({row["payment_id"] for row in batches}) != len(batches):
        raise ValueError("journal_shadow_payment_not_unique")
    return batches, lines


def create_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE direct_agoda_journal_shadow_v2_batches(
          batch_id TEXT PRIMARY KEY CHECK(length(batch_id)=64),
          source_draft_id TEXT NOT NULL UNIQUE
            REFERENCES direct_agoda_accounting_draft_authorities(draft_id),
          payment_id INTEGER NOT NULL UNIQUE REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id),
          booking_number TEXT NOT NULL,
          allocation_id INTEGER NOT NULL UNIQUE REFERENCES cost_allocations(id),
          target_id INTEGER NOT NULL REFERENCES allocation_targets(id),
          target_match_status TEXT NOT NULL CHECK(target_match_status IN (
            'unique_service_period','service_target_ambiguous','service_target_missing'
          )),
          assigned_target TEXT NOT NULL,
          suggested_target TEXT,
          resolution_id TEXT REFERENCES direct_agoda_target_resolution_candidates(resolution_id),
          resolution_status TEXT,
          target_authority TEXT NOT NULL CHECK(target_authority IN (
            'bound_unique','candidate_only','none'
          )),
          shadow_cohort TEXT NOT NULL CHECK(shadow_cohort IN (
            'target_bound','target_unresolved'
          )),
          accounting_period TEXT NOT NULL,
          posting_date TEXT NOT NULL,
          ledger_currency TEXT NOT NULL CHECK(ledger_currency='KRW'),
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          debit_account TEXT NOT NULL CHECK(debit_account IN (
            '숙박비','미확정여행원가'
          )),
          credit_account TEXT NOT NULL CHECK(credit_account='법인카드미지급금'),
          cost_type TEXT NOT NULL CHECK(cost_type='여행원가'),
          vat_tag TEXT NOT NULL CHECK(vat_tag='불공제_해외'),
          release_gate TEXT NOT NULL,
          batch_status TEXT NOT NULL CHECK(batch_status='shadow_balanced'),
          posting_status TEXT NOT NULL CHECK(posting_status='shadow_only'),
          posting_eligible INTEGER NOT NULL CHECK(posting_eligible=0),
          authoritative_posting INTEGER NOT NULL CHECK(authoritative_posting=0),
          external_posting INTEGER NOT NULL CHECK(external_posting=0),
          batch_sha256 TEXT NOT NULL CHECK(length(batch_sha256)=64),
          payload_json TEXT NOT NULL,
          CHECK(
            (shadow_cohort='target_bound' AND target_match_status='unique_service_period'
             AND debit_account='숙박비' AND target_authority='bound_unique'
             AND resolution_id IS NULL AND resolution_status IS NULL)
            OR
            (shadow_cohort='target_unresolved'
             AND target_match_status IN ('service_target_ambiguous','service_target_missing')
             AND debit_account='미확정여행원가' AND resolution_id IS NOT NULL)
          )
        );

        CREATE TABLE direct_agoda_journal_shadow_v2_lines(
          batch_id TEXT NOT NULL REFERENCES direct_agoda_journal_shadow_v2_batches(batch_id),
          line_no INTEGER NOT NULL CHECK(line_no IN (1,2)),
          side TEXT NOT NULL CHECK(side IN ('debit','credit')),
          account_code TEXT NOT NULL,
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL REFERENCES bookings(id),
          allocation_id INTEGER NOT NULL REFERENCES cost_allocations(id),
          assigned_target TEXT NOT NULL,
          shadow_cohort TEXT NOT NULL CHECK(shadow_cohort IN (
            'target_bound','target_unresolved'
          )),
          accounting_period TEXT NOT NULL,
          posting_date TEXT NOT NULL,
          ledger_currency TEXT NOT NULL CHECK(ledger_currency='KRW'),
          vat_tag TEXT NOT NULL CHECK(vat_tag='불공제_해외'),
          line_sha256 TEXT NOT NULL UNIQUE CHECK(length(line_sha256)=64),
          payload_json TEXT NOT NULL,
          PRIMARY KEY(batch_id,line_no)
        );

        CREATE TABLE direct_agoda_journal_shadow_v2_manifests(
          manifest_id TEXT PRIMARY KEY CHECK(length(manifest_id)=64),
          source_database_sha256 TEXT NOT NULL CHECK(length(source_database_sha256)=64),
          batch_count INTEGER NOT NULL CHECK(batch_count>=0),
          line_count INTEGER NOT NULL CHECK(line_count>=0),
          target_bound_count INTEGER NOT NULL CHECK(target_bound_count>=0),
          target_unresolved_count INTEGER NOT NULL CHECK(target_unresolved_count>=0),
          target_bound_total_krw INTEGER NOT NULL CHECK(target_bound_total_krw>=0),
          target_unresolved_total_krw INTEGER NOT NULL CHECK(target_unresolved_total_krw>=0),
          debit_total_krw INTEGER NOT NULL CHECK(debit_total_krw>=0),
          credit_total_krw INTEGER NOT NULL CHECK(credit_total_krw>=0),
          batch_set_sha256 TEXT NOT NULL CHECK(length(batch_set_sha256)=64),
          line_set_sha256 TEXT NOT NULL CHECK(length(line_set_sha256)=64),
          posting_status TEXT NOT NULL CHECK(posting_status='shadow_only'),
          authoritative_posting INTEGER NOT NULL CHECK(authoritative_posting=0),
          external_posting INTEGER NOT NULL CHECK(external_posting=0),
          payload_json TEXT NOT NULL,
          CHECK(batch_count=target_bound_count+target_unresolved_count),
          CHECK(debit_total_krw=credit_total_krw),
          CHECK(debit_total_krw=target_bound_total_krw+target_unresolved_total_krw)
        );
        """
    )


def materialize(
    db: sqlite3.Connection,
    batches: list[dict[str, object]],
    lines: list[dict[str, object]],
    source_database_sha256: str,
) -> int:
    before = db.total_changes
    for row in batches:
        db.execute(
            """INSERT OR IGNORE INTO direct_agoda_journal_shadow_v2_batches(
                 batch_id,source_draft_id,payment_id,booking_id,booking_number,
                 allocation_id,target_id,target_match_status,assigned_target,
                 suggested_target,resolution_id,resolution_status,target_authority,
                 shadow_cohort,accounting_period,posting_date,ledger_currency,
                 amount_krw,debit_account,credit_account,cost_type,vat_tag,
                 release_gate,batch_status,posting_status,posting_eligible,
                 authoritative_posting,external_posting,batch_sha256,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                       'shadow_balanced','shadow_only',0,0,0,?,?)""",
            (
                row["batch_id"], row["source_draft_id"], row["payment_id"],
                row["booking_id"], row["booking_number"], row["allocation_id"],
                row["target_id"], row["target_match_status"], row["assigned_target"],
                row["suggested_target"], row["resolution_id"],
                row["resolution_status"], row["target_authority"],
                row["shadow_cohort"], row["accounting_period"], row["posting_date"],
                row["ledger_currency"], row["amount_krw"], row["debit_account"],
                row["credit_account"], row["cost_type"], row["vat_tag"],
                row["release_gate"], row["batch_sha256"], row["payload_json"],
            ),
        )
    for row in lines:
        db.execute(
            """INSERT OR IGNORE INTO direct_agoda_journal_shadow_v2_lines(
                 batch_id,line_no,side,account_code,amount_krw,payment_id,booking_id,
                 allocation_id,assigned_target,shadow_cohort,accounting_period,
                 posting_date,ledger_currency,vat_tag,line_sha256,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["batch_id"], row["line_no"], row["side"], row["account_code"],
                row["amount_krw"], row["payment_id"], row["booking_id"],
                row["allocation_id"], row["assigned_target"], row["shadow_cohort"],
                row["accounting_period"], row["posting_date"],
                row["ledger_currency"], row["vat_tag"], row["line_sha256"],
                row["payload_json"],
            ),
        )

    target_bound = [row for row in batches if row["shadow_cohort"] == "target_bound"]
    target_unresolved = [
        row for row in batches if row["shadow_cohort"] == "target_unresolved"
    ]
    bound_total = sum(int(row["amount_krw"]) for row in target_bound)
    unresolved_total = sum(int(row["amount_krw"]) for row in target_unresolved)
    debit_total = sum(int(row["amount_krw"]) for row in lines if row["side"] == "debit")
    credit_total = sum(
        int(row["amount_krw"]) for row in lines if row["side"] == "credit"
    )
    manifest_payload = {
        "rule_id": RULE_ID,
        "source_database_sha256": source_database_sha256,
        "batch_count": len(batches),
        "line_count": len(lines),
        "target_bound_count": len(target_bound),
        "target_unresolved_count": len(target_unresolved),
        "target_bound_total_krw": bound_total,
        "target_unresolved_total_krw": unresolved_total,
        "debit_total_krw": debit_total,
        "credit_total_krw": credit_total,
        "batch_set_sha256": content_sha256(sorted(row["batch_id"] for row in batches)),
        "line_set_sha256": content_sha256(sorted(row["line_sha256"] for row in lines)),
        "posting_status": "shadow_only",
        "authoritative_posting": False,
        "external_posting": False,
    }
    manifest_id = content_sha256(manifest_payload)
    db.execute(
        """INSERT OR IGNORE INTO direct_agoda_journal_shadow_v2_manifests(
             manifest_id,source_database_sha256,batch_count,line_count,
             target_bound_count,target_unresolved_count,target_bound_total_krw,
             target_unresolved_total_krw,debit_total_krw,credit_total_krw,
             batch_set_sha256,line_set_sha256,posting_status,
             authoritative_posting,external_posting,payload_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'shadow_only',0,0,?)""",
        (
            manifest_id, source_database_sha256, len(batches), len(lines),
            len(target_bound), len(target_unresolved), bound_total, unresolved_total,
            debit_total, credit_total, manifest_payload["batch_set_sha256"],
            manifest_payload["line_set_sha256"], canonical_json(manifest_payload),
        ),
    )
    return db.total_changes - before


def semantic_snapshot(db: sqlite3.Connection) -> dict[str, object]:
    queries = {
        "batches": """SELECT batch_id,source_draft_id,payment_id,booking_id,
            booking_number,allocation_id,target_id,target_match_status,assigned_target,
            suggested_target,resolution_id,resolution_status,target_authority,
            shadow_cohort,accounting_period,posting_date,amount_krw,debit_account,
            credit_account,cost_type,vat_tag,release_gate,batch_status,posting_status,
            posting_eligible,authoritative_posting,external_posting,batch_sha256
            FROM direct_agoda_journal_shadow_v2_batches ORDER BY payment_id""",
        "lines": """SELECT batch_id,line_no,side,account_code,amount_krw,payment_id,
            booking_id,allocation_id,assigned_target,shadow_cohort,accounting_period,
            posting_date,vat_tag,line_sha256
            FROM direct_agoda_journal_shadow_v2_lines ORDER BY payment_id,line_no""",
        "manifest": """SELECT manifest_id,source_database_sha256,batch_count,line_count,
            target_bound_count,target_unresolved_count,target_bound_total_krw,
            target_unresolved_total_krw,debit_total_krw,credit_total_krw,
            batch_set_sha256,line_set_sha256,posting_status,authoritative_posting,
            external_posting FROM direct_agoda_journal_shadow_v2_manifests""",
    }
    return {key: [list(row) for row in db.execute(sql)] for key, sql in queries.items()}


def validate_materialized(
    db: sqlite3.Connection,
    scope: list[dict[str, object]],
    resolutions: Mapping[str, Mapping[str, object]],
    batches: list[dict[str, object]],
    lines: list[dict[str, object]],
) -> dict[str, object]:
    expected_total = sum(int(row["amount_krw"]) for row in scope)
    bound = [row for row in batches if row["shadow_cohort"] == "target_bound"]
    unresolved = [row for row in batches if row["shadow_cohort"] == "target_unresolved"]
    expected_bound_total = sum(int(row["amount_krw"]) for row in bound)
    expected_unresolved_total = sum(int(row["amount_krw"]) for row in unresolved)
    counts = {
        "source_scope": len(scope),
        "source_resolution_candidates": table_count(
            db, "direct_agoda_target_resolution_candidates"
        ),
        "shadow_batches": table_count(db, "direct_agoda_journal_shadow_v2_batches"),
        "shadow_lines": table_count(db, "direct_agoda_journal_shadow_v2_lines"),
        "shadow_manifests": table_count(db, "direct_agoda_journal_shadow_v2_manifests"),
        "legacy_journal_entries": table_count(db, "journal_entries"),
    }
    expected_counts = {
        "source_scope": len(scope),
        "source_resolution_candidates": len(resolutions),
        "shadow_batches": len(batches),
        "shadow_lines": len(lines),
        "shadow_manifests": 1,
        "legacy_journal_entries": 0,
    }
    totals = db.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN side='debit' THEN amount_krw END),0),
             COALESCE(SUM(CASE WHEN side='credit' THEN amount_krw END),0)
           FROM direct_agoda_journal_shadow_v2_lines"""
    ).fetchone()
    cohort_rows = {
        str(row[0]): {"count": int(row[1]), "amount_krw": int(row[2])}
        for row in db.execute(
            """SELECT shadow_cohort,COUNT(*),SUM(amount_krw)
                 FROM direct_agoda_journal_shadow_v2_batches
                GROUP BY shadow_cohort ORDER BY shadow_cohort"""
        )
    }
    unauthorized = int(
        db.execute(
            """SELECT
               (SELECT COUNT(*) FROM direct_agoda_journal_shadow_v2_batches
                 WHERE batch_status<>'shadow_balanced' OR posting_status<>'shadow_only'
                    OR posting_eligible<>0 OR authoritative_posting<>0
                    OR external_posting<>0)+
               (SELECT COUNT(*) FROM classification_decisions
                 WHERE decision_status='confirmed')+
               (SELECT COUNT(*) FROM allocation_plans WHERE plan_status='confirmed')+
               (SELECT COUNT(*) FROM payment_booking_links WHERE link_status='confirmed')"""
        ).fetchone()[0]
    )
    account_mapping_issues = int(
        db.execute(
            """SELECT COUNT(*) FROM direct_agoda_journal_shadow_v2_batches
                WHERE (shadow_cohort='target_bound' AND debit_account<>'숙박비')
                   OR (shadow_cohort='target_unresolved'
                       AND debit_account<>'미확정여행원가')
                   OR credit_account<>'법인카드미지급금'"""
        ).fetchone()[0]
    )
    line_pair_issues = int(
        db.execute(
            """SELECT COUNT(*) FROM (
                 SELECT b.batch_id,COUNT(l.line_no) n,
                        SUM(CASE WHEN l.side='debit' THEN l.amount_krw ELSE 0 END) d,
                        SUM(CASE WHEN l.side='credit' THEN l.amount_krw ELSE 0 END) c,
                        SUM(CASE WHEN l.side='debit'
                                  AND l.account_code=b.debit_account THEN 1 ELSE 0 END) dm,
                        SUM(CASE WHEN l.side='credit'
                                  AND l.account_code=b.credit_account THEN 1 ELSE 0 END) cm,
                        MAX(b.amount_krw) amount
                   FROM direct_agoda_journal_shadow_v2_batches b
                   LEFT JOIN direct_agoda_journal_shadow_v2_lines l
                     ON l.batch_id=b.batch_id
                  GROUP BY b.batch_id
                 HAVING n<>2 OR d<>c OR d<>amount OR dm<>1 OR cm<>1
               )"""
        ).fetchone()[0]
    )
    uncovered = int(
        db.execute(
            """SELECT COUNT(*) FROM direct_agoda_accounting_draft_authorities a
               LEFT JOIN direct_agoda_journal_shadow_v2_batches s
                 ON s.source_draft_id=a.draft_id
              WHERE s.batch_id IS NULL"""
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
    issues: list[str] = []
    if counts != expected_counts:
        issues.append("journal_shadow_table_count_mismatch")
    if len(batches) != len(scope) or len(lines) != len(scope) * 2:
        issues.append("journal_shadow_scope_coverage_mismatch")
    if int(totals[0]) != expected_total or int(totals[1]) != expected_total:
        issues.append("journal_shadow_total_mismatch")
    expected_cohorts = {
        "target_bound": {"count": len(bound), "amount_krw": expected_bound_total},
        "target_unresolved": {
            "count": len(unresolved),
            "amount_krw": expected_unresolved_total,
        },
    }
    if cohort_rows != expected_cohorts:
        issues.append("journal_shadow_cohort_mismatch")
    if unauthorized:
        issues.append("journal_shadow_authority_leak")
    if account_mapping_issues:
        issues.append("journal_shadow_account_mapping_invalid")
    if line_pair_issues:
        issues.append("journal_shadow_unbalanced_batch")
    if uncovered:
        issues.append("journal_shadow_uncovered_source")
    if posting_table_rows:
        issues.append("journal_shadow_posting_table_leak")
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
        "cohorts": cohort_rows,
        "debit_total_krw": int(totals[0]),
        "credit_total_krw": int(totals[1]),
        "expected_total_krw": expected_total,
        "unauthorized_rows": unauthorized,
        "account_mapping_issues": account_mapping_issues,
        "line_pair_issues": line_pair_issues,
        "uncovered_source_rows": uncovered,
        "posting_table_rows": posting_table_rows,
        "foreign_key_violations": foreign_keys,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-db", default="outputs/agoda-card-journal-draft-v1-20260824.sqlite"
    )
    parser.add_argument(
        "--input-audit",
        default="outputs/agoda-card-journal-draft-audit-v1-20260824.json",
    )
    parser.add_argument(
        "--output-db", default="outputs/agoda-card-journal-shadow-v2-20260824.sqlite"
    )
    parser.add_argument(
        "--output-detail",
        default="outputs/agoda-card-journal-shadow-detail-v2-20260824.json",
    )
    parser.add_argument(
        "--output-audit",
        default="outputs/agoda-card-journal-shadow-audit-v2-20260824.json",
    )
    args = parser.parse_args()

    input_db = (ROOT / args.input_db).resolve()
    input_audit = (ROOT / args.input_audit).resolve()
    output_db = (ROOT / args.output_db).resolve()
    output_detail = (ROOT / args.output_detail).resolve()
    output_audit = (ROOT / args.output_audit).resolve()
    for path in (input_db, input_audit):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (output_db, output_detail, output_audit):
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    input_audit_raw, source_database_sha, source_audit_sha = validate_input_audit(
        input_audit, input_db
    )
    read_db = sqlite3.connect(f"file:{input_db.as_posix()}?mode=ro", uri=True)
    read_db.row_factory = sqlite3.Row
    try:
        scope = load_scope(read_db)
        resolutions = load_resolution_map(read_db)
    finally:
        read_db.close()
    expected_source_scope = int(input_audit_raw["counts"]["source_scope"])
    if len(scope) != expected_source_scope:
        raise ValueError("journal_shadow_source_scope_count_mismatch")
    if len(resolutions) != int(input_audit_raw["counts"]["resolution_candidates"]):
        raise ValueError("journal_shadow_resolution_count_mismatch")
    batches, lines = build_shadow_rows(scope, resolutions, source_database_sha)

    copy_database(input_db, output_db)
    db = sqlite3.connect(output_db)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        create_tables(db)
        db.commit()
        first_changes = materialize(db, batches, lines, source_database_sha)
        db.commit()
        before_second = db.total_changes
        second_changes = materialize(db, batches, lines, source_database_sha)
        db.commit()
        second_total_changes = db.total_changes - before_second
        snapshot = semantic_snapshot(db)
        semantic_sha = content_sha256(snapshot)
        validation = validate_materialized(db, scope, resolutions, batches, lines)
    finally:
        db.close()

    with tempfile.TemporaryDirectory(prefix="agoda-shadow-v2-rebuild-") as temp_dir:
        rebuilt_path = Path(temp_dir) / "rebuilt.sqlite"
        copy_database(input_db, rebuilt_path)
        rebuilt = sqlite3.connect(rebuilt_path)
        rebuilt.row_factory = sqlite3.Row
        rebuilt.execute("PRAGMA foreign_keys=ON")
        try:
            create_tables(rebuilt)
            rebuilt.commit()
            materialize(rebuilt, batches, lines, source_database_sha)
            rebuilt.commit()
            rebuilt_semantic_sha = content_sha256(semantic_snapshot(rebuilt))
        finally:
            rebuilt.close()

    detail = {
        "artifact_kind": "agoda_card_journal_shadow_detail",
        "artifact_version": "v2",
        "shadow_batches": batches,
        "shadow_lines": lines,
    }
    write_json(output_detail, detail)
    result = {
        "artifact_kind": "agoda_card_journal_shadow_audit",
        "artifact_version": "v2",
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
        },
        "outputs": {
            "database": relative(output_db),
            "database_sha256": file_sha256(output_db),
            "detail": relative(output_detail),
            "detail_sha256": file_sha256(output_detail),
            "semantic_sha256": semantic_sha,
        },
        "counts": validation["counts"],
        "cohorts": validation["cohorts"],
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
            "account_mapping_issues": validation["account_mapping_issues"],
            "line_pair_issues": validation["line_pair_issues"],
            "uncovered_source_rows": validation["uncovered_source_rows"],
            "posting_table_rows": validation["posting_table_rows"],
            "foreign_key_violations": validation["foreign_key_violations"],
        },
        "authority": {
            "shadow_status": "complete_balanced_scope",
            "target_bound_status": "candidate_requires_confirmation",
            "target_unresolved_status": "blocked_in_unresolved_clearing",
            "authoritative_posting_written": False,
            "legacy_journal_entries_written": 0,
            "external_posting_written": False,
        },
    }
    if not all(
        (
            result["checks"]["validation_passed"],
            result["checks"]["semantic_idempotent"],
            result["checks"]["independent_rebuild_matches"],
            result["checks"]["input_database_unchanged"],
            result["checks"]["unauthorized_rows"] == 0,
            result["checks"]["account_mapping_issues"] == 0,
            result["checks"]["line_pair_issues"] == 0,
            result["checks"]["uncovered_source_rows"] == 0,
            result["checks"]["posting_table_rows"] == 0,
            not result["checks"]["foreign_key_violations"],
        )
    ):
        raise RuntimeError("agoda_journal_shadow_v2_audit_failed")
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
