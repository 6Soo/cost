"""Promote strong Agoda/card candidates to reversible proposed links.

This command never edits the candidate input database.  It creates a copied
database, records only ``payment_booking_links(link_status='proposed')`` plus
content-addressed provenance, and verifies that accounting authority tables
remain unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.agoda_card_reconciliation import build_agoda_card_candidate_report


ACCOUNTING_TABLES = (
    "classification_decisions",
    "allocation_plans",
    "allocation_review_cases",
    "allocation_targets",
    "cost_allocations",
    "journal_entries",
    "direct_accounting_posting_batches",
    "direct_accounting_posting_lines",
)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def parse_numeric_key(value: object, prefix: str) -> int:
    text = str(value)
    if not text.startswith(prefix):
        raise ValueError(f"candidate_key_invalid:{text}")
    return int(text[len(prefix) :].split(":", 1)[0])


def table_names(db: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def selected_counts(db: sqlite3.Connection, names: Iterable[str]) -> dict[str, int]:
    available = table_names(db)
    return {
        name: int(db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
        for name in names
        if name in available
    }


def portal_attestation(db: sqlite3.Connection) -> dict[str, object]:
    hashes = sorted(
        str(row[0])
        for row in db.execute(
            "SELECT source_sha256 FROM direct_source_records "
            "WHERE source_kind='agoda_portal_detail'"
        )
    )
    return {
        "source_kind": "agoda_portal_detail",
        "record_count": len(hashes),
        "source_hashes": hashes,
        "source_hashes_sha256": content_sha256(hashes),
    }


def copy_database(source_path: Path, destination_path: Path) -> None:
    source_uri = f"file:{source_path.resolve().as_posix()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()


def create_authority_table(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE direct_agoda_card_proposed_link_authorities(
          authority_id TEXT PRIMARY KEY CHECK(length(authority_id)=64),
          reconciliation_run_id TEXT NOT NULL,
          candidate_report_sha256 TEXT NOT NULL CHECK(length(candidate_report_sha256)=64),
          reservation_key TEXT NOT NULL UNIQUE,
          payment_key TEXT NOT NULL UNIQUE,
          payment_id INTEGER NOT NULL UNIQUE REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL UNIQUE REFERENCES bookings(id),
          event_kind TEXT NOT NULL CHECK(event_kind='charge'),
          currency TEXT NOT NULL,
          comparison_units INTEGER NOT NULL CHECK(comparison_units>0),
          evidence_tier TEXT NOT NULL,
          generic_link_status TEXT NOT NULL CHECK(generic_link_status='proposed'),
          accounting_side_effects INTEGER NOT NULL CHECK(accounting_side_effects=0),
          authority_sha256 TEXT NOT NULL CHECK(length(authority_sha256)=64),
          payload_json TEXT NOT NULL
        )
        """
    )


def proposal_rows(
    db: sqlite3.Connection,
    report: dict[str, Any],
    report_file_sha256: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for proposal in report["proposed_individuals"]:
        if proposal.get("status") != "proposed":
            raise ValueError("candidate_status_not_proposed")
        booking_id = parse_numeric_key(proposal["reservation_key"], "booking:")
        payment_id = parse_numeric_key(proposal["payment_key"], "payment:")
        booking = db.execute(
            "SELECT status FROM bookings WHERE id=?", (booking_id,)
        ).fetchone()
        payment = db.execute(
            "SELECT transaction_type FROM payment_transactions WHERE id=?", (payment_id,)
        ).fetchone()
        if booking is None or str(booking[0]) != "completed":
            raise ValueError(f"candidate_booking_not_completed:{booking_id}")
        if payment is None or str(payment[0]) != "purchase":
            raise ValueError(f"candidate_payment_not_purchase:{payment_id}")
        signature = list(proposal["signature"])
        if len(signature) != 3 or signature[0] != "charge":
            raise ValueError("candidate_signature_not_charge")
        payload = {
            "candidate_report_sha256": report_file_sha256,
            "reconciliation_run_id": report["card_projection"]["run_id"],
            "reservation_key": proposal["reservation_key"],
            "payment_key": proposal["payment_key"],
            "booking_id": booking_id,
            "payment_id": payment_id,
            "signature": signature,
            "tier": proposal["tier"],
            "relation_type": "pays_for",
            "link_status": "proposed",
            "confidence": 1.0,
        }
        authority_sha256 = content_sha256(payload)
        rows.append(
            {
                **payload,
                "authority_id": authority_sha256,
                "authority_sha256": authority_sha256,
                "payload_json": canonical_json(payload),
            }
        )
    booking_ids = [int(row["booking_id"]) for row in rows]
    payment_ids = [int(row["payment_id"]) for row in rows]
    if len(set(booking_ids)) != len(booking_ids):
        raise ValueError("candidate_booking_not_unique")
    if len(set(payment_ids)) != len(payment_ids):
        raise ValueError("candidate_payment_not_unique")
    return rows


def insert_rows(
    db: sqlite3.Connection,
    rows: list[dict[str, object]],
    source_document_id: int,
    *,
    ignore_existing: bool,
) -> int:
    before = db.total_changes
    insert = "INSERT OR IGNORE" if ignore_existing else "INSERT"
    for row in rows:
        db.execute(
            f"""
            {insert} INTO payment_booking_links(
              payment_id,booking_id,relation_type,confidence,link_status,
              first_seen_document_id,last_seen_document_id
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                row["payment_id"],
                row["booking_id"],
                row["relation_type"],
                row["confidence"],
                row["link_status"],
                source_document_id,
                source_document_id,
            ),
        )
        db.execute(
            f"""
            {insert} INTO direct_agoda_card_proposed_link_authorities(
              authority_id,reconciliation_run_id,candidate_report_sha256,
              reservation_key,payment_key,payment_id,booking_id,event_kind,
              currency,comparison_units,evidence_tier,generic_link_status,
              accounting_side_effects,authority_sha256,payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'proposed',0,?,?)
            """,
            (
                row["authority_id"],
                row["reconciliation_run_id"],
                row["candidate_report_sha256"],
                row["reservation_key"],
                row["payment_key"],
                row["payment_id"],
                row["booking_id"],
                row["signature"][0],
                row["signature"][1],
                row["signature"][2],
                row["tier"],
                row["authority_sha256"],
                row["payload_json"],
            ),
        )
    return db.total_changes - before


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate-db",
        default="outputs/agoda-card-link-candidate-v4-20260823.sqlite",
    )
    parser.add_argument(
        "--candidate-report",
        default="outputs/agoda-card-link-candidate-v4-20260823.json",
    )
    parser.add_argument(
        "--candidate-audit",
        default="outputs/agoda-card-link-candidate-audit-v4-20260823.json",
    )
    parser.add_argument(
        "--output-db",
        default="outputs/agoda-card-proposed-links-v1-20260824.sqlite",
    )
    parser.add_argument(
        "--output-audit",
        default="outputs/agoda-card-proposed-links-audit-v1-20260824.json",
    )
    args = parser.parse_args()

    candidate_db = (ROOT / args.candidate_db).resolve()
    candidate_report = (ROOT / args.candidate_report).resolve()
    candidate_audit = (ROOT / args.candidate_audit).resolve()
    output_db = (ROOT / args.output_db).resolve()
    output_audit = (ROOT / args.output_audit).resolve()
    for path in (output_db, output_audit):
        if path.exists():
            raise FileExistsError(f"refusing_to_overwrite:{path}")

    audit = json.loads(candidate_audit.read_text(encoding="utf-8"))
    report = json.loads(candidate_report.read_text(encoding="utf-8"))
    candidate_db_sha256 = file_sha256(candidate_db)
    candidate_report_sha256 = file_sha256(candidate_report)
    if candidate_db_sha256 != audit["outputs"]["database_sha256"]:
        raise ValueError("candidate_database_hash_mismatch")
    if candidate_report_sha256 != audit["outputs"]["report_file_sha256"]:
        raise ValueError("candidate_report_hash_mismatch")
    if not all(
        (
            report.get("universe_sealed"),
            report.get("universe_attestation_verified"),
            report.get("portal_census_linkage_verified"),
        )
    ):
        raise ValueError("candidate_universe_not_verified")

    source_uri = f"file:{candidate_db.as_posix()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    source.row_factory = sqlite3.Row
    try:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("candidate_database_integrity_failed")
        if source.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("candidate_database_foreign_key_failed")
        if selected_counts(source, ("payment_booking_links",))["payment_booking_links"] != 0:
            raise ValueError("candidate_database_already_has_links")
        accounting_before = selected_counts(source, ACCOUNTING_TABLES)
        current_report = build_agoda_card_candidate_report(
            source,
            run_id=str(report["card_projection"]["run_id"]),
            universe_sealed=True,
            universe_attestation=portal_attestation(source),
        )
        if content_sha256(current_report) != audit["outputs"]["report_content_sha256"]:
            raise ValueError("candidate_report_recomputation_mismatch")
        rows = proposal_rows(source, report, candidate_report_sha256)
    finally:
        source.close()

    copy_database(candidate_db, output_db)
    db = sqlite3.connect(output_db)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        create_authority_table(db)
        db.execute(
            "INSERT INTO source_documents(source_kind,path,sha256) VALUES (?,?,?)",
            (
                "agoda_card_candidate_report",
                relative(candidate_report),
                candidate_report_sha256,
            ),
        )
        source_document_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        first_insert_changes = insert_rows(
            db, rows, source_document_id, ignore_existing=False
        )
        db.commit()
        second_insert_changes = insert_rows(
            db, rows, source_document_id, ignore_existing=True
        )
        db.commit()
        link_counts = {
            str(row[0]): int(row[1])
            for row in db.execute(
                "SELECT link_status,COUNT(*) FROM payment_booking_links GROUP BY link_status"
            )
        }
        authority_count = int(
            db.execute(
                "SELECT COUNT(*) FROM direct_agoda_card_proposed_link_authorities"
            ).fetchone()[0]
        )
        accounting_after = selected_counts(db, ACCOUNTING_TABLES)
        integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = [list(row) for row in db.execute("PRAGMA foreign_key_check")]
    finally:
        db.close()

    result = {
        "artifact_kind": "agoda_card_proposed_links_audit",
        "artifact_version": "v1",
        "candidate": {
            "database": relative(candidate_db),
            "database_sha256": candidate_db_sha256,
            "report": relative(candidate_report),
            "report_sha256": candidate_report_sha256,
            "audit": relative(candidate_audit),
            "audit_sha256": file_sha256(candidate_audit),
        },
        "output": {
            "database": relative(output_db),
            "database_sha256": file_sha256(output_db),
        },
        "counts": {
            "candidate_proposed_individuals": len(rows),
            "candidate_review_groups_excluded": len(report["review_groups"]),
            "payment_booking_links_by_status": link_counts,
            "proposed_link_authorities": authority_count,
        },
        "checks": {
            "first_insert_changes": first_insert_changes,
            "second_insert_changes": second_insert_changes,
            "semantic_idempotent": second_insert_changes == 0,
            "all_links_proposed": link_counts == {"proposed": len(rows)},
            "authority_count_matches": authority_count == len(rows),
            "accounting_table_counts_before": accounting_before,
            "accounting_table_counts_after": accounting_after,
            "accounting_tables_unchanged": accounting_before == accounting_after,
            "candidate_database_unchanged": file_sha256(candidate_db) == candidate_db_sha256,
            "integrity_check": integrity,
            "foreign_key_violations": foreign_keys,
        },
        "authority": {
            "link_status": "proposed",
            "confirmed_links_written": 0,
            "classification_written": False,
            "allocation_written": False,
            "journal_or_posting_written": False,
        },
    }
    if not all(
        (
            result["checks"]["semantic_idempotent"],
            result["checks"]["all_links_proposed"],
            result["checks"]["authority_count_matches"],
            result["checks"]["accounting_tables_unchanged"],
            result["checks"]["candidate_database_unchanged"],
            result["checks"]["integrity_check"] == "ok",
            not result["checks"]["foreign_key_violations"],
        )
    ):
        raise RuntimeError("proposed_link_audit_failed")
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
