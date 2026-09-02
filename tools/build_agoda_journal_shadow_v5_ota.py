"""Build a balanced, non-posting journal shadow from v5 OTA-extended accounting draft.

The v5 OTA-extended draft has a flat ``draft_rows`` table (rule_id, payment_id,
booking_id, allocation_target, target_match_status, amount_krw, service_start_on,
service_end_on, occurred_on, merchant). This builder reads that table and emits
the v3-format shadow tables (batches, lines, manifest) so the rest of the
pipeline can treat both kinds of input uniformly.

The shadow is ``posting_eligible=0``: no journal or posting table is written.
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
from tools.build_agoda_journal_shadow_v3 import (
    BOUND_DEBIT_ACCOUNT,
    UNRESOLVED_DEBIT_ACCOUNT,
    CREDIT_ACCOUNT,
    UNASSIGNED_TARGET,
    PAYMENT_YEAR_TERMINAL_STATUS,
)


RULE_ID = "agoda-linked-lodging-journal-shadow-v5-ota-extended"
SHADOW_TABLES = (
    "direct_agoda_journal_shadow_v3_batches",
    "direct_agoda_journal_shadow_v3_lines",
    "direct_agoda_journal_shadow_v3_manifest",
)


def _load_audit(path: Path, database: Path) -> tuple[dict[str, Any], str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("v5_audit_invalid")
    database_sha256 = file_sha256(database)
    # v5 audit may not include database_sha256; only enforce when present
    if raw.get("database_sha256") and raw.get("database_sha256") != database_sha256:
        raise ValueError("v5_audit_database_sha256_mismatch")
    return raw, database_sha256


def create_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS direct_agoda_journal_shadow_v3_batches(
          batch_id TEXT PRIMARY KEY CHECK(length(batch_id)=64),
          draft_id TEXT NOT NULL,
          payment_id INTEGER NOT NULL,
          booking_id INTEGER NOT NULL,
          booking_number TEXT NOT NULL,
          payment_lane TEXT NOT NULL,
          payment_year INTEGER NOT NULL,
          service_year INTEGER NOT NULL,
          target_match_status TEXT NOT NULL,
          assigned_target TEXT NOT NULL,
          suggested_targets_json TEXT NOT NULL,
          target_authority TEXT NOT NULL,
          shadow_cohort TEXT NOT NULL CHECK(shadow_cohort IN (
            'target_bound','target_unresolved','payment_year_terminal'
          )),
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

        CREATE TABLE IF NOT EXISTS direct_agoda_journal_shadow_v3_lines(
          batch_id TEXT NOT NULL,
          line_no INTEGER NOT NULL CHECK(line_no IN (1,2)),
          side TEXT NOT NULL CHECK(side IN ('debit','credit')),
          account_code TEXT NOT NULL,
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          payment_id INTEGER NOT NULL,
          booking_id INTEGER NOT NULL,
          assigned_target TEXT NOT NULL,
          payment_lane TEXT NOT NULL,
          posting_date TEXT NOT NULL,
          line_sha256 TEXT NOT NULL UNIQUE CHECK(length(line_sha256)=64),
          payload_json TEXT NOT NULL,
          PRIMARY KEY(batch_id,line_no)
        );

        CREATE TABLE IF NOT EXISTS direct_agoda_journal_shadow_v3_manifest(
          manifest_id TEXT PRIMARY KEY CHECK(length(manifest_id)=64),
          rule_id TEXT NOT NULL,
          draft_database_sha256 TEXT NOT NULL,
          source_database_sha256 TEXT NOT NULL,
          input_audit_sha256 TEXT NOT NULL,
          shadow_database_sha256 TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL,
          cohort_counts_json TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        """
    )


def _cohort(status: str) -> str:
    if status == "bound_unique":
        return "target_bound"
    if status == PAYMENT_YEAR_TERMINAL_STATUS:
        return "payment_year_terminal"
    return "target_unresolved"


def _debit_account(status: str) -> str:
    if status == "bound_unique":
        return BOUND_DEBIT_ACCOUNT
    return UNRESOLVED_DEBIT_ACCOUNT


def _assigned_target(status: str, target: str) -> str:
    if status == "bound_unique":
        return target
    return UNASSIGNED_TARGET


def build_batches_and_lines(
    draft_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    batches: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for row in draft_rows:
        amount = abs(int(row["amount_krw"]))
        if amount <= 0:
            continue
        status = row["target_match_status"]
        cohort = _cohort(status)
        debit_account = _debit_account(status)
        assigned_target = _assigned_target(status, row["allocation_target"])
        payment_lane = "ota_extended_v5"
        payment_year = int(row["occurred_on"][:4]) if row.get("occurred_on") else 0
        service_year = int(row["service_start_on"][:4]) if row.get("service_start_on") else 0
        target_authority = (
            "explicit_trip_registry" if cohort == "target_bound"
            else "payment_year_terminal" if cohort == "payment_year_terminal"
            else "unresolved"
        )
        payload = {
            "rule_id": RULE_ID,
            "draft_id": RULE_ID,
            "payment_id": int(row["payment_id"]),
            "booking_id": int(row["booking_id"]),
            "booking_number": str(row["booking_id"]),
            "payment_lane": payment_lane,
            "payment_year": payment_year,
            "service_year": service_year,
            "target_match_status": status,
            "assigned_target": assigned_target,
            "suggested_targets": [row["allocation_target"]],
            "target_authority": target_authority,
            "shadow_cohort": cohort,
            "amount_krw": amount,
            "debit_account": debit_account,
            "credit_account": CREDIT_ACCOUNT,
            "cost_type": "여행원가",
            "posting_date": row["occurred_on"],
            "posting_status": "shadow_only",
            "posting_eligible": 0,
            "authoritative_posting": 0,
            "external_posting": 0,
            "merchant": row.get("merchant", ""),
            "service_start_on": row.get("service_start_on", ""),
            "service_end_on": row.get("service_end_on", ""),
        }
        batch_id = sha256_value(payload)
        batch = {
            **payload,
            "batch_id": batch_id,
            "batch_sha256": batch_id,
            "payload_json": canonical_json(payload),
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
                "amount_krw": amount,
                "payment_id": int(row["payment_id"]),
                "booking_id": int(row["booking_id"]),
                "assigned_target": assigned_target,
                "payment_lane": payment_lane,
                "posting_date": row["occurred_on"],
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
) -> None:
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
                CREDIT_ACCOUNT, "여행원가", row["posting_date"], "shadow_only", 0, 0, 0,
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


def build_manifest(
    db: sqlite3.Connection,
    source_database_sha256: str,
    input_audit_sha256: str,
    draft_database_sha256: str,
) -> dict[str, Any]:
    cur = db.cursor()
    cohort_counts = {}
    for cohort in ("target_bound", "target_unresolved", "payment_year_terminal"):
        cur.execute(
            "SELECT COUNT(*) FROM direct_agoda_journal_shadow_v3_batches WHERE shadow_cohort=?",
            (cohort,),
        )
        cohort_counts[cohort] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM direct_agoda_journal_shadow_v3_batches")
    batch_count = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(amount_krw),0) FROM direct_agoda_journal_shadow_v3_batches")
    total_krw = cur.fetchone()[0]
    shadow_db_path = Path(db.execute("PRAGMA database_list").fetchone()[2])
    shadow_database_sha256 = file_sha256(shadow_db_path)
    payload = {
        "rule_id": RULE_ID,
        "draft_database_sha256": draft_database_sha256,
        "source_database_sha256": source_database_sha256,
        "input_audit_sha256": input_audit_sha256,
        "shadow_database_sha256": shadow_database_sha256,
        "cohort_counts": cohort_counts,
        "batch_count": batch_count,
        "total_krw": total_krw,
    }
    manifest_id = sha256_value(payload)
    db.execute(
        """INSERT INTO direct_agoda_journal_shadow_v3_manifest(
          manifest_id,rule_id,draft_database_sha256,source_database_sha256,
          input_audit_sha256,shadow_database_sha256,created_at,
          cohort_counts_json,payload_json)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            manifest_id, RULE_ID, draft_database_sha256, source_database_sha256,
            input_audit_sha256, shadow_database_sha256,
            "2026-09-02T00:00:00Z", canonical_json(cohort_counts),
            canonical_json(payload),
        ),
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--draft-db",
        default=r"C:\AX\cost\outputs\agoda-card-accounting-draft-v5-ota-extended.sqlite",
        help="Path to v5 OTA-extended draft sqlite",
    )
    parser.add_argument(
        "--draft-audit",
        default=r"C:\AX\cost\outputs\agoda-card-accounting-draft-v5-ota-extended.audit.json",
        help="Path to v5 OTA-extended draft audit json",
    )
    parser.add_argument(
        "--source-db",
        default=r"C:\AX\cost\outputs\agoda-card-link-candidate-v5-20260826.sqlite",
        help="Path to v5 candidate source sqlite",
    )
    parser.add_argument(
        "--out-db",
        default=r"C:\AX\cost\outputs\agoda-card-journal-shadow-v5-ota-extended.sqlite",
        help="Path to output shadow sqlite",
    )
    parser.add_argument(
        "--out-audit",
        default=r"C:\AX\cost\outputs\agoda-card-journal-shadow-v5-ota-extended.audit.json",
        help="Path to output audit json",
    )
    args = parser.parse_args(argv)

    draft_db = Path(args.draft_db)
    draft_audit = Path(args.draft_audit)
    source_db = Path(args.source_db)
    out_db = Path(args.out_db)
    out_audit = Path(args.out_audit)

    if not draft_db.exists():
        raise SystemExit(f"draft db not found: {draft_db}")
    if not draft_audit.exists():
        raise SystemExit(f"draft audit not found: {draft_audit}")

    audit, draft_database_sha256 = _load_audit(draft_audit, draft_db)
    source_database_sha256 = file_sha256(source_db) if source_db.exists() else ""
    input_audit_sha256 = file_sha256(draft_audit)

    # Load draft rows
    conn = sqlite3.connect(str(draft_db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM draft_rows")
    draft_rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    print(f"loaded draft_rows: {len(draft_rows)}건")

    # Build shadow
    batches, lines = build_batches_and_lines(draft_rows)
    print(f"built shadow: {len(batches)} batches, {len(lines)} lines")

    if out_db.exists():
        out_db.unlink()
    out = sqlite3.connect(str(out_db))
    create_tables(out)
    materialize(out, batches, lines)
    manifest = build_manifest(
        out,
        source_database_sha256=source_database_sha256,
        input_audit_sha256=input_audit_sha256,
        draft_database_sha256=draft_database_sha256,
    )
    out.commit()
    out.close()

    # Verify
    chk = sqlite3.connect(str(out_db))
    c = chk.cursor()
    c.execute("SELECT COUNT(*) FROM direct_agoda_journal_shadow_v3_batches")
    bc = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM direct_agoda_journal_shadow_v3_lines")
    lc = c.fetchone()[0]
    c.execute("SELECT shadow_cohort, COUNT(*) FROM direct_agoda_journal_shadow_v3_batches GROUP BY shadow_cohort")
    cohorts = c.fetchall()
    c.execute("SELECT COUNT(*) FROM direct_agoda_journal_shadow_v3_manifest")
    mc = c.fetchone()[0]
    c.execute("PRAGMA foreign_key_check")
    fk = c.fetchall()
    c.execute("PRAGMA integrity_check")
    ic = c.fetchall()
    chk.close()
    print(f"verified: {bc} batches, {lc} lines, {mc} manifests, fk={len(fk)}, integrity={ic}")

    audit_payload = {
        "rule_id": RULE_ID,
        "draft_database_sha256": draft_database_sha256,
        "source_database_sha256": source_database_sha256,
        "input_audit_sha256": input_audit_sha256,
        "manifest": manifest,
        "cohorts": dict(cohorts),
        "batches": bc,
        "lines": lc,
        "integrity_check": ic,
        "foreign_key_check": fk,
        "audit_db_sha256": file_sha256(out_db),
    }
    out_audit.write_text(
        json.dumps(audit_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"created: {out_db} ({out_db.stat().st_size/1024:.0f} KB)")
    print(f"audit:   {out_audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
