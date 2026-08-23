"""Build and audit a read-only Agoda-to-card candidate database.

The source Agoda database and card workbooks are treated as immutable inputs.
This command materializes card projections in a copied database, but it never
writes booking-payment links, classifications, allocations, or postings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.agoda_card_reconciliation import build_agoda_card_candidate_report
from ledger.domain.direct_projection import SCHEMA_VERSION, _apply_schema, project_card_payments
from ledger.domain.direct_sources import import_cards


SOURCE_DB = ROOT / "outputs" / "agoda-paseo-staging-20260822.sqlite"
CARD_PATHS = (
    ROOT / "ledger" / "newcard" / "conv" / "A_20260720.xlsx",
    ROOT / "ledger" / "newcard" / "conv" / "E.xlsx",
    ROOT / "ledger" / "newcard" / "conv" / "F.xlsx",
    ROOT / "ledger" / "newcard" / "conv" / "G.xlsx",
    ROOT / "ledger" / "newcard" / "conv" / "H.xlsx",
)
CODE_PATHS = (
    ROOT / "ledger" / "cardindex.py",
    ROOT / "ledger" / "domain" / "agoda_booking_evidence.py",
    ROOT / "ledger" / "domain" / "agoda_card_reconciliation.py",
    ROOT / "ledger" / "domain" / "direct_projection.py",
    ROOT / "ledger" / "domain" / "direct_projection_schema.sql",
    ROOT / "ledger" / "domain" / "direct_sources.py",
    ROOT / "ledger" / "domain" / "schema.sql",
    ROOT / "tools" / "agoda_amount_candidate_graph.py",
    Path(__file__).resolve(),
)
VOLATILE_COLUMNS = {"created_at", "imported_at", "normalized_at", "updated_at"}
AUTHORITY_TABLE_MARKERS = ("classification", "allocation", "posting", "journal")


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
    return path.relative_to(ROOT).as_posix()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def open_source() -> sqlite3.Connection:
    uri = f"file:{SOURCE_DB.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def copy_source(destination: sqlite3.Connection) -> None:
    with open_source() as source:
        source.backup(destination)


def table_names(db: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def table_count(db: sqlite3.Connection, table: str) -> int:
    return int(db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def authority_counts(db: sqlite3.Connection) -> dict[str, int]:
    names = table_names(db)
    selected = {
        name
        for name in names
        if name == "payment_booking_links"
        or any(marker in name.lower() for marker in AUTHORITY_TABLE_MARKERS)
    }
    return {name: table_count(db, name) for name in sorted(selected)}


def semantic_table_sha256(db: sqlite3.Connection, table: str) -> str:
    columns = [
        str(row[1])
        for row in db.execute(f'PRAGMA table_info("{table}")')
        if str(row[1]) not in VOLATILE_COLUMNS
    ]
    select_list = ",".join(f'"{column}"' for column in columns)
    rows = [list(row) for row in db.execute(f'SELECT {select_list} FROM "{table}" ORDER BY {select_list}')]
    return content_sha256({"columns": columns, "rows": rows})


def import_semantics(db: sqlite3.Connection) -> dict[str, str]:
    return {
        table: semantic_table_sha256(db, table)
        for table in (
            "direct_source_records",
            "direct_card_events",
            "direct_normalized_payments",
        )
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


def source_payload_digest_mismatches(db: sqlite3.Connection) -> list[dict[str, object]]:
    mismatches: list[dict[str, object]] = []
    rows = db.execute(
        "SELECT id, source_kind, source_key, source_sha256, payload_json "
        "FROM direct_source_records "
        "WHERE source_kind IN ('agoda_portal_detail','card_raw') ORDER BY id"
    )
    for row_id, kind, key, source_hash, payload_json in rows:
        try:
            observed = content_sha256(json.loads(str(payload_json)))
        except (TypeError, json.JSONDecodeError):
            observed = "invalid_json"
        valid_hash = (
            isinstance(source_hash, str)
            and len(source_hash) == 64
            and all(character in "0123456789abcdefABCDEF" for character in source_hash)
        )
        if not valid_hash or str(source_hash).lower() != observed:
            mismatches.append(
                {
                    "id": int(row_id),
                    "source_kind": str(kind),
                    "source_key": str(key),
                    "stored": source_hash,
                    "observed": observed,
                }
            )
    return mismatches


def insert_run(
    db: sqlite3.Connection,
    *,
    run_id: str,
    input_manifest_sha256: str,
    code_commit: str,
    code_bundle_sha256: str,
) -> None:
    db.execute(
        """
        INSERT INTO direct_projection_runs(
            run_id,status,schema_version,input_manifest_sha256,
            code_commit,code_bundle_sha256
        ) VALUES (?,?,?,?,?,?)
        """,
        (
            run_id,
            "passed",
            SCHEMA_VERSION,
            input_manifest_sha256,
            code_commit,
            code_bundle_sha256,
        ),
    )


def materialize(
    db: sqlite3.Connection,
    *,
    run_id: str,
    input_manifest_sha256: str,
    code_commit: str,
    code_bundle_sha256: str,
    check_import_idempotency: bool,
) -> tuple[dict[str, int], dict[str, int] | None, bool, int]:
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    copy_source(db)
    _apply_schema(db)
    insert_run(
        db,
        run_id=run_id,
        input_manifest_sha256=input_manifest_sha256,
        code_commit=code_commit,
        code_bundle_sha256=code_bundle_sha256,
    )
    first_import = import_cards(db, ROOT / "ledger")
    first_semantics = import_semantics(db)
    second_import: dict[str, int] | None = None
    import_idempotent = True
    if check_import_idempotency:
        second_import = import_cards(db, ROOT / "ledger")
        import_idempotent = (
            int(second_import["inserted"]) == 0
            and first_semantics == import_semantics(db)
        )
    projected = project_card_payments(db, run_id)
    db.commit()
    return first_import, second_import, import_idempotent, projected


def parse_numeric_key(value: object, prefix: str) -> int:
    text = str(value)
    if not text.startswith(prefix):
        raise ValueError(f"candidate_key_invalid:{text}")
    return int(text[len(prefix) :].split(":", 1)[0])


def detail_rows(db: sqlite3.Connection, report: dict[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for proposal in report["proposed_individuals"]:
        booking_id = parse_numeric_key(proposal["reservation_key"], "booking:")
        payment_id = parse_numeric_key(proposal["payment_key"], "payment:")
        booking = db.execute(
            "SELECT id, booking_number, service_start_on, service_end_on, status "
            "FROM bookings WHERE id=?",
            (booking_id,),
        ).fetchone()
        payment = db.execute(
            """
            SELECT p.id,p.source_system,p.occurred_on,p.merchant,p.currency,
                   p.foreign_amount,p.amount_krw,p.transaction_type,
                   s.source_key,s.source_sha256,s.payload_json
            FROM payment_transactions p
            JOIN direct_payment_projection_links l
              ON l.payment_id=p.id AND l.run_id=?
            JOIN direct_normalized_payments n ON n.id=l.direct_payment_id
            JOIN direct_source_records s ON s.id=n.source_record_id
            WHERE p.id=?
            """,
            (report["card_projection"]["run_id"], payment_id),
        ).fetchone()
        payload = json.loads(str(payment["payload_json"]))
        rows.append(
            {
                "booking": {
                    "booking_id": int(booking["id"]),
                    "booking_number": str(booking["booking_number"]),
                    "service_start_on": booking["service_start_on"],
                    "service_end_on": booking["service_end_on"],
                    "status": str(booking["status"]),
                },
                "payment": {
                    "payment_id": int(payment["id"]),
                    "source_system": str(payment["source_system"]),
                    "source_key": str(payment["source_key"]),
                    "source_sha256": str(payment["source_sha256"]),
                    "occurred_on": payment["occurred_on"],
                    "merchant": str(payment["merchant"]),
                    "currency": payment["currency"],
                    "foreign_amount": payment["foreign_amount"],
                    "amount_krw": int(payment["amount_krw"]),
                    "transaction_type": str(payment["transaction_type"]),
                    "card_last4": str(payload.get("card4") or "") or None,
                },
                "signature": proposal["signature"],
                "status": proposal["status"],
                "tier": proposal["tier"],
            }
        )
    return rows


def independently_valid_agoda_merchant(value: object) -> bool:
    if not isinstance(value, str):
        return False
    merchant = " ".join(value.strip().upper().split())
    return (
        merchant == "AGODA"
        or merchant.startswith(("AGODA.", "AGODA_", "AGODA "))
        or merchant == "아고다_나이스"
        or merchant == "아고다페이먼츠코리아"
    )


def count_tables(db: sqlite3.Connection, names: Iterable[str]) -> dict[str, int]:
    available = table_names(db)
    return {name: table_count(db, name) for name in names if name in available}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v4")
    parser.add_argument("--date", default="20260823")
    args = parser.parse_args()
    started = time.perf_counter()

    version = str(args.version)
    date = str(args.date)
    output_prefix = ROOT / "outputs" / f"agoda-card-link-candidate-{version}-{date}"
    database_path = output_prefix.with_suffix(".sqlite")
    report_path = output_prefix.with_suffix(".json")
    detail_path = ROOT / "outputs" / f"agoda-card-link-candidate-detail-{version}-{date}.json"
    audit_path = ROOT / "outputs" / f"agoda-card-link-candidate-audit-{version}-{date}.json"
    for path in (database_path, report_path, detail_path, audit_path):
        if path.exists():
            raise FileExistsError(f"refusing_to_overwrite:{path}")

    input_hashes_before = {relative(SOURCE_DB): file_sha256(SOURCE_DB)}
    input_hashes_before.update({relative(path): file_sha256(path) for path in CARD_PATHS})
    inputs = {
        "agoda_staging": {
            "relative_path": relative(SOURCE_DB),
            "raw_sha256": input_hashes_before[relative(SOURCE_DB)],
        },
        "card_sources": [
            {"relative_path": relative(path), "raw_sha256": input_hashes_before[relative(path)]}
            for path in CARD_PATHS
        ],
    }
    input_manifest_sha256 = content_sha256(inputs)
    code_files = {relative(path): file_sha256(path) for path in CODE_PATHS}
    code_bundle_sha256 = content_sha256(code_files)
    try:
        code_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        code_commit = "unknown"
    run_id = (
        f"agoda-card-link-{version}-{date}-"
        f"{input_manifest_sha256[:12]}-{code_bundle_sha256[:12]}"
    )

    with open_source() as source_for_counts:
        source_authority_counts = authority_counts(source_for_counts)

    db = sqlite3.connect(database_path)
    try:
        first_import, second_import, import_idempotent, projected = materialize(
            db,
            run_id=run_id,
            input_manifest_sha256=input_manifest_sha256,
            code_commit=code_commit,
            code_bundle_sha256=code_bundle_sha256,
            check_import_idempotency=True,
        )
        attestation = portal_attestation(db)
        before_report_sha = hashlib.sha256(db.serialize()).hexdigest()
        before_report_changes = db.total_changes
        report = build_agoda_card_candidate_report(
            db,
            run_id=run_id,
            universe_sealed=True,
            universe_attestation=attestation,
        )
        after_report_sha = hashlib.sha256(db.serialize()).hexdigest()
        after_report_changes = db.total_changes
        repeated_report = build_agoda_card_candidate_report(
            db,
            run_id=run_id,
            universe_sealed=True,
            universe_attestation=attestation,
        )
        report_content_sha256 = content_sha256(report)
        candidate_repeat_deterministic = report_content_sha256 == content_sha256(repeated_report)
        details = detail_rows(db, report)
        digest_mismatches = source_payload_digest_mismatches(db)
        final_authority_counts = authority_counts(db)
        integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = [list(row) for row in db.execute("PRAGMA foreign_key_check")]
        counts = count_tables(
            db,
            (
                "bookings",
                "booking_source_evidence",
                "direct_source_records",
                "direct_card_events",
                "direct_normalized_payments",
                "payment_transactions",
                "direct_payment_projection_links",
                "payment_booking_links",
                "classification_decisions",
                "journal_entries",
            ),
        )
        db.commit()
    finally:
        db.close()

    independent = sqlite3.connect(":memory:")
    try:
        materialize(
            independent,
            run_id=run_id,
            input_manifest_sha256=input_manifest_sha256,
            code_commit=code_commit,
            code_bundle_sha256=code_bundle_sha256,
            check_import_idempotency=False,
        )
        independent_report = build_agoda_card_candidate_report(
            independent,
            run_id=run_id,
            universe_sealed=True,
            universe_attestation=portal_attestation(independent),
        )
        independent_report_sha256 = content_sha256(independent_report)
    finally:
        independent.close()

    input_hashes_after = {relative(SOURCE_DB): file_sha256(SOURCE_DB)}
    input_hashes_after.update({relative(path): file_sha256(path) for path in CARD_PATHS})
    write_json(report_path, report)
    detail_document = {
        "artifact_kind": "agoda_card_link_candidate_detail",
        "artifact_version": version,
        "authority": "candidate_only",
        "run_id": run_id,
        "proposed_individuals": details,
        "review_groups": report["review_groups"],
    }
    write_json(detail_path, detail_document)

    proposed_booking_keys = [row["reservation_key"] for row in report["proposed_individuals"]]
    proposed_payment_keys = [row["payment_key"] for row in report["proposed_individuals"]]
    non_agoda_proposed = [
        row
        for row in details
        if not independently_valid_agoda_merchant(row["payment"]["merchant"])
    ]
    merchant_counts = Counter(row["payment"]["merchant"] for row in details)
    hold_counts = Counter(str(row.get("reason")) for row in report["held"])
    report_counts = {
        key: len(report[key])
        for key in (
            "amount_candidates",
            "proposed_individuals",
            "review_individuals",
            "review_groups",
            "held",
        )
    }
    audit = {
        "artifact_kind": "agoda_card_link_candidate_audit",
        "artifact_version": version,
        "created_on": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
        "run_id": run_id,
        "authority": {
            "candidate_only": True,
            "canonical_payment_booking_links_written": False,
            "classification_written": False,
            "confirmed_authority_written": False,
            "posting_written": False,
        },
        "inputs": inputs,
        "input_manifest_sha256": input_manifest_sha256,
        "code_files": code_files,
        "code_bundle_sha256": code_bundle_sha256,
        "counts": counts,
        "report_counts": report_counts,
        "hold_reason_counts": dict(sorted(hold_counts.items())),
        "universe": {
            "sealed": report["universe_sealed"],
            "attestation_verified": report["universe_attestation_verified"],
            "portal_census_linkage_verified": report["portal_census_linkage_verified"],
        },
        "checks": {
            "first_import": first_import,
            "second_import": second_import,
            "import_semantic_idempotent": import_idempotent,
            "projected": projected,
            "candidate_read_only": (
                before_report_sha == after_report_sha
                and before_report_changes == after_report_changes
            ),
            "candidate_repeat_deterministic": candidate_repeat_deterministic,
            "independent_rebuild_matches": report_content_sha256 == independent_report_sha256,
            "independent_rebuild_report_sha256": independent_report_sha256,
            "source_input_unchanged": (
                input_hashes_before[relative(SOURCE_DB)]
                == input_hashes_after[relative(SOURCE_DB)]
            ),
            "card_inputs_unchanged": all(
                input_hashes_before[relative(path)] == input_hashes_after[relative(path)]
                for path in CARD_PATHS
            ),
            "source_payload_digest_mismatches": digest_mismatches,
            "proposed_booking_unique": len(set(proposed_booking_keys)) == len(proposed_booking_keys),
            "proposed_payment_unique": len(set(proposed_payment_keys)) == len(proposed_payment_keys),
            "non_agoda_proposed": non_agoda_proposed,
            "proposal_merchant_counts": dict(sorted(merchant_counts.items())),
            "authority_table_counts_before": source_authority_counts,
            "authority_table_counts_after": final_authority_counts,
            "authority_tables_unchanged": source_authority_counts == final_authority_counts,
            "integrity_check": integrity,
            "foreign_key_violations": foreign_keys,
        },
        "outputs": {
            "database": relative(database_path),
            "database_sha256": file_sha256(database_path),
            "report": relative(report_path),
            "report_content_sha256": report_content_sha256,
            "report_file_sha256": file_sha256(report_path),
            "detail": relative(detail_path),
            "detail_file_sha256": file_sha256(detail_path),
        },
        "supersedes": [
            "outputs/agoda-card-link-candidate-v3-20260823.sqlite",
            "outputs/agoda-card-link-candidate-v3-20260823.json",
            "outputs/agoda-card-link-candidate-detail-v3-20260823.json",
            "outputs/agoda-card-link-candidate-audit-v3-20260823.json",
        ],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(audit_path, audit)
    print(
        json.dumps(
            {
                "database": str(database_path),
                "database_sha256": audit["outputs"]["database_sha256"],
                "report": str(report_path),
                "report_sha256": audit["outputs"]["report_file_sha256"],
                "detail": str(detail_path),
                "detail_sha256": audit["outputs"]["detail_file_sha256"],
                "audit": str(audit_path),
                "audit_sha256": file_sha256(audit_path),
                "run_id": run_id,
                "counts": counts,
                "report_counts": report_counts,
                "checks": audit["checks"],
                "elapsed_seconds": audit["elapsed_seconds"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
