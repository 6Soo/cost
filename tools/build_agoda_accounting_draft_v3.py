"""Build the year-safe, authority-gated Agoda accounting draft v3.

The active accounting path uses only the explicit trip-schedule authority
document.  Historical ``trips.json``/``mm/dd/window`` data is not read here:
it remains available only for replay of old artifacts.  A row can be
target-bound only when the supplied schedule document contains a unique
authoritative record with explicit dates.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger.domain.direct_trip_schedule_authority import (
    ScheduleRecord,
    canonical_json,
    file_sha256,
    load_document,
    match_service_period,
    manifest,
    sha256_value,
)
from ledger.domain.manual_ledger_booking_link import ManualBookingRow
from ledger.domain.manual_tab_overlap_resolution import (
    OverlapDecision,
    load_verified_manual_rows,
    resolve_overlap_target,
)
from tools.build_agoda_accounting_draft import (
    copy_database,
    load_link_scope,
    table_count,
    table_names,
)


RULE_ID = "agoda-linked-lodging-accounting-draft-v3"
UNASSIGNED_TARGET = "여행_미배정"
MATCH_STATUSES = {
    "bound_unique",
    "authority_ambiguous",
    "payment_year_terminal",
    "authority_missing",
}


def _payment_occurred_on(db: sqlite3.Connection, payment_id: int) -> str:
    row = db.execute(
        "SELECT occurred_on FROM payment_transactions WHERE id=?", (payment_id,)
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError(f"payment_occurred_on_missing:{payment_id}")
    value = str(row[0])
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"payment_occurred_on_invalid:{payment_id}") from exc
    return value


def _payment_merchant(db: sqlite3.Connection, payment_id: int) -> str:
    try:
        row = db.execute(
            "SELECT merchant FROM payment_transactions WHERE id=?", (payment_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    return "" if row is None or row[0] is None else str(row[0])


def _year(value: str, field: str, payment_id: int) -> int:
    try:
        return date.fromisoformat(value).year
    except ValueError as exc:
        raise ValueError(f"{field}_invalid:{payment_id}") from exc


def _payment_lane(payment_year: int) -> str:
    return f"{payment_year}년 결제"


def build_rows(
    db: sqlite3.Connection,
    scope: Iterable[Mapping[str, object]],
    authoritative: Iterable[ScheduleRecord],
    *,
    input_database_sha256: str,
    input_audit_sha256: str,
    authority_document_sha256: str,
    overlap_manual_rows: Iterable[ManualBookingRow] = (),
    overlap_resolution_sha256: str | None = None,
    overlap_resolution_document_sha256: str = "",
) -> list[dict[str, object]]:
    authoritative = tuple(authoritative)
    overlap_manual_rows = tuple(overlap_manual_rows)
    authority_manifest_sha256 = sha256_value(manifest(authoritative))
    rows: list[dict[str, object]] = []
    for source in sorted(scope, key=lambda item: int(item["payment_id"])):
        payment_id = int(source["payment_id"])
        service_start = str(source["service_start_on"])
        service_end = str(source["service_end_on"])
        occurred_on = _payment_occurred_on(db, payment_id)
        payment_year = _year(occurred_on, "payment_date", payment_id)
        service_year = _year(service_start, "service_start_on", payment_id)
        explicit_candidates = match_service_period(
            service_start, service_end, authoritative, authoritative_only=True
        )
        explicit = explicit_candidates
        overlap_decision: OverlapDecision | None = None
        if len(explicit_candidates) > 1 and overlap_resolution_sha256 is not None:
            overlap_decision = resolve_overlap_target(
                candidate_targets=[record.trip_code for record in explicit_candidates],
                occurred_on=occurred_on,
                amount_krw=int(source["amount_krw"]),
                merchant=_payment_merchant(db, payment_id),
                service_start_on=service_start,
                service_end_on=service_end,
                manual_rows=overlap_manual_rows,
                resolution_sha256=overlap_resolution_sha256 or "",
            )
            if overlap_decision is not None:
                explicit = tuple(
                    record
                    for record in explicit_candidates
                    if record.trip_code == overlap_decision.selected_target
                )
        if len(explicit) == 1:
            target_match_status = "bound_unique"
            allocation_target = explicit[0].trip_code
            target_authority = "authoritative_explicit_period"
            candidate_targets = [record.trip_code for record in explicit]
            target_type = "trip"
            posting_eligible = False
        elif explicit:
            target_match_status = "authority_ambiguous"
            allocation_target = UNASSIGNED_TARGET
            target_authority = "authoritative_conflict"
            candidate_targets = [record.trip_code for record in explicit]
            target_type = "unassigned"
            posting_eligible = False
        elif payment_year == 2025:
            # A 2025 payment without independently verified 2026 service
            # evidence is a user-facing terminal lane, not a missing 2026
            # trip. Keep the payment fact and its year; do not manufacture a
            # trip code or silently drop it from the accounting scope.
            target_match_status = "payment_year_terminal"
            allocation_target = "2025년 결제"
            target_authority = "payment_year_terminal"
            candidate_targets = []
            target_type = "other"
            posting_eligible = False
        else:
            target_match_status = "authority_missing"
            allocation_target = UNASSIGNED_TARGET
            target_authority = "none"
            candidate_targets = []
            target_type = "unassigned"
            posting_eligible = False

        if explicit_candidates:
            candidate_targets = [record.trip_code for record in explicit_candidates]

        payload = {
            "rule_id": RULE_ID,
            "link_authority_id": str(source["link_authority_id"]),
            "payment_id": payment_id,
            "booking_id": int(source["booking_id"]),
            "booking_number": str(source["booking_number"]),
            "external_key": str(source["external_key"]),
            "amount_krw": int(source["amount_krw"]),
            "service_start_on": service_start,
            "service_end_on": service_end,
            "occurred_on": occurred_on,
            "payment_year": payment_year,
            "service_year": service_year,
            "payment_lane": _payment_lane(payment_year),
            "event_year": service_year,
            "authority_document_sha256": authority_document_sha256,
            "authority_manifest_sha256": authority_manifest_sha256,
            "overlap_resolution_document_sha256": overlap_resolution_document_sha256,
            "authority_candidate_targets": candidate_targets,
            "overlap_resolution": (
                overlap_decision.as_dict(
                    resolution_document_sha256=overlap_resolution_sha256 or ""
                )
                if overlap_decision is not None
                else None
            ),
            "target_match_status": target_match_status,
            "target_authority": target_authority,
            "target_type": target_type,
            "allocation_target": allocation_target,
            "account": "숙박비",
            "cost_type": "여행원가",
            "decision_status": "proposed",
            "posting_eligible": posting_eligible,
            "input_database_sha256": input_database_sha256,
            "input_audit_sha256": input_audit_sha256,
            "booking_evidence_set_sha256": str(source["booking_evidence_set_sha256"]),
        }
        draft_id = sha256_value(payload)
        rows.append(
            {
                **payload,
                "draft_id": draft_id,
                "draft_sha256": draft_id,
                "payload_json": canonical_json(payload),
            }
        )
    return rows


def create_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE direct_agoda_accounting_draft_v3_authorities(
          draft_id TEXT PRIMARY KEY CHECK(length(draft_id)=64),
          link_authority_id TEXT NOT NULL UNIQUE
            REFERENCES direct_agoda_card_proposed_link_authorities(authority_id),
          input_database_sha256 TEXT NOT NULL CHECK(length(input_database_sha256)=64),
          input_audit_sha256 TEXT NOT NULL CHECK(length(input_audit_sha256)=64),
          booking_evidence_set_sha256 TEXT NOT NULL CHECK(length(booking_evidence_set_sha256)=64),
          payment_id INTEGER NOT NULL REFERENCES payment_transactions(id),
          booking_id INTEGER NOT NULL REFERENCES bookings(id),
          booking_number TEXT NOT NULL,
          service_start_on TEXT NOT NULL,
          service_end_on TEXT NOT NULL,
          occurred_on TEXT NOT NULL,
          payment_year INTEGER NOT NULL,
          service_year INTEGER NOT NULL,
          event_year INTEGER NOT NULL,
          payment_lane TEXT NOT NULL,
          authority_document_sha256 TEXT NOT NULL CHECK(length(authority_document_sha256)=64),
          authority_manifest_sha256 TEXT NOT NULL CHECK(length(authority_manifest_sha256)=64),
          authority_candidate_targets_json TEXT NOT NULL,
          target_match_status TEXT NOT NULL CHECK(target_match_status IN (
            'bound_unique','authority_ambiguous','payment_year_terminal','authority_missing'
          )),
          target_authority TEXT NOT NULL CHECK(target_authority IN (
            'authoritative_explicit_period','authoritative_conflict',
            'payment_year_terminal','candidate_only','none'
          )),
          target_type TEXT NOT NULL CHECK(target_type IN ('trip','other','unassigned')),
          allocation_target TEXT NOT NULL,
          account TEXT NOT NULL,
          cost_type TEXT NOT NULL,
          amount_krw INTEGER NOT NULL CHECK(amount_krw>0),
          decision_status TEXT NOT NULL CHECK(decision_status='proposed'),
          posting_eligible INTEGER NOT NULL CHECK(posting_eligible=0),
          draft_sha256 TEXT NOT NULL UNIQUE CHECK(length(draft_sha256)=64),
          payload_json TEXT NOT NULL
        );

        CREATE TABLE direct_agoda_accounting_draft_v3_manifest(
          manifest_id TEXT PRIMARY KEY CHECK(length(manifest_id)=64),
          input_database_sha256 TEXT NOT NULL CHECK(length(input_database_sha256)=64),
          input_audit_sha256 TEXT NOT NULL CHECK(length(input_audit_sha256)=64),
          authority_document_sha256 TEXT NOT NULL CHECK(length(authority_document_sha256)=64),
          row_count INTEGER NOT NULL CHECK(row_count>=0),
          bound_unique_count INTEGER NOT NULL CHECK(bound_unique_count>=0),
          authority_ambiguous_count INTEGER NOT NULL CHECK(authority_ambiguous_count>=0),
          payment_2025_terminal_count INTEGER NOT NULL CHECK(payment_2025_terminal_count>=0),
          authority_missing_count INTEGER NOT NULL CHECK(authority_missing_count>=0),
          payment_2025_count INTEGER NOT NULL CHECK(payment_2025_count>=0),
          payment_2026_count INTEGER NOT NULL CHECK(payment_2026_count>=0),
          total_amount_krw INTEGER NOT NULL CHECK(total_amount_krw>=0),
          posting_eligible INTEGER NOT NULL CHECK(posting_eligible=0),
          payload_json TEXT NOT NULL
        );
        """
    )


def materialize(db: sqlite3.Connection, rows: list[dict[str, object]], hashes: Mapping[str, str]) -> dict[str, object]:
    for row in rows:
        db.execute(
            """INSERT INTO direct_agoda_accounting_draft_v3_authorities(
              draft_id,link_authority_id,input_database_sha256,input_audit_sha256,
              booking_evidence_set_sha256,payment_id,booking_id,booking_number,
              service_start_on,service_end_on,occurred_on,payment_year,service_year,
              event_year,payment_lane,authority_document_sha256,authority_manifest_sha256,
              authority_candidate_targets_json,
              target_match_status,target_authority,target_type,allocation_target,
              account,cost_type,amount_krw,decision_status,posting_eligible,
              draft_sha256,payload_json)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["draft_id"], row["link_authority_id"], row["input_database_sha256"],
                row["input_audit_sha256"], row["booking_evidence_set_sha256"],
                row["payment_id"], row["booking_id"], row["booking_number"],
                row["service_start_on"], row["service_end_on"], row["occurred_on"],
                row["payment_year"], row["service_year"], row["event_year"],
                row["payment_lane"], row["authority_document_sha256"],
                row["authority_manifest_sha256"],
                canonical_json(row["authority_candidate_targets"]),
                row["target_match_status"],
                row["target_authority"], row["target_type"], row["allocation_target"],
                row["account"], row["cost_type"], row["amount_krw"],
                row["decision_status"], row["posting_eligible"], row["draft_sha256"],
                row["payload_json"],
            ),
        )

    def count(status: str) -> int:
        return sum(row["target_match_status"] == status for row in rows)

    payload = {
        "rule_id": RULE_ID,
        **hashes,
        "row_count": len(rows),
        "bound_unique_count": count("bound_unique"),
        "authority_ambiguous_count": count("authority_ambiguous"),
        "payment_2025_terminal_count": count("payment_year_terminal"),
        "authority_missing_count": count("authority_missing"),
        "payment_2025_count": sum(row["payment_year"] == 2025 for row in rows),
        "payment_2026_count": sum(row["payment_year"] == 2026 for row in rows),
        "total_amount_krw": sum(int(row["amount_krw"]) for row in rows),
        "posting_eligible": False,
    }
    manifest_id = sha256_value(payload)
    db.execute(
        """INSERT INTO direct_agoda_accounting_draft_v3_manifest(
          manifest_id,input_database_sha256,input_audit_sha256,authority_document_sha256,
          row_count,bound_unique_count,authority_ambiguous_count,
          payment_2025_terminal_count,authority_missing_count,payment_2025_count,
          payment_2026_count,total_amount_krw,posting_eligible,payload_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            manifest_id, hashes["input_database_sha256"], hashes["input_audit_sha256"],
            hashes["authority_document_sha256"], payload["row_count"],
            payload["bound_unique_count"], payload["authority_ambiguous_count"],
            payload["payment_2025_terminal_count"], payload["authority_missing_count"],
            payload["payment_2025_count"],
            payload["payment_2026_count"], payload["total_amount_krw"], 0,
            canonical_json(payload),
        ),
    )
    return {**payload, "manifest_id": manifest_id}


def build_artifact(
    input_database: Path,
    input_audit: Path,
    output_database: Path,
    authority_document: Path,
    detail_output: Path,
    audit_output: Path,
    *,
    overlap_resolution_document: Path | None = None,
    manual_workbook: Path | None = None,
) -> dict[str, object]:
    if output_database.exists():
        raise ValueError(f"output_exists:{output_database}")
    input_database_sha256 = file_sha256(input_database)
    input_audit_sha256 = file_sha256(input_audit)
    authoritative, authority_document_sha256 = load_document(authority_document)
    overlap_resolution: Mapping[str, object] | None = None
    overlap_manual_rows: tuple[ManualBookingRow, ...] = ()
    overlap_resolution_sha256 = ""
    if overlap_resolution_document is not None:
        if manual_workbook is None:
            raise ValueError("manual_overlap_workbook_required")
        overlap_resolution = json.loads(
            overlap_resolution_document.read_text(encoding="utf-8")
        )
        if not isinstance(overlap_resolution, dict):
            raise ValueError("manual_overlap_resolution_document_invalid")
        overlap_resolution_sha256 = file_sha256(overlap_resolution_document)
        overlap_manual_rows = load_verified_manual_rows(
            manual_workbook, overlap_resolution
        )
    copy_database(input_database, output_database)
    db = sqlite3.connect(output_database)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        if "direct_agoda_card_proposed_link_authorities" not in table_names(db):
            raise ValueError("proposed_link_authority_table_missing")
        scope = load_link_scope(
            db,
            input_database_sha256=input_database_sha256,
            input_audit_sha256=input_audit_sha256,
        )
        create_tables(db)
        hashes = {
            "input_database_sha256": input_database_sha256,
            "input_audit_sha256": input_audit_sha256,
            "authority_document_sha256": authority_document_sha256,
            "overlap_resolution_document_sha256": overlap_resolution_sha256,
        }
        rows = build_rows(
            db,
            scope,
            authoritative,
            overlap_manual_rows=overlap_manual_rows,
            overlap_resolution_sha256=(
                overlap_resolution_sha256 if overlap_resolution_document is not None else None
            ),
            **hashes,
        )
        summary = materialize(db, rows, hashes)
        db.commit()
        integrity = [str(row[0]) for row in db.execute("PRAGMA integrity_check")]
        foreign_keys = [list(row) for row in db.execute("PRAGMA foreign_key_check")]
        if integrity != ["ok"] or foreign_keys:
            raise ValueError("v3_database_integrity_failed")
        summary.update(
            {
                "artifact_kind": "agoda_accounting_draft_v3",
                "database_sha256": file_sha256(output_database),
                "source_scope": len(scope),
                "integrity_check": integrity,
                "foreign_key_check": foreign_keys,
                "authority_records": len(authoritative),
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
                {"summary": summary, "rows": rows},
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
    parser.add_argument(
        "--authority-document", type=Path,
        default=ROOT / "ledger/data/trip_schedule_authority_v3.json",
    )
    parser.add_argument(
        "--overlap-resolution-document",
        type=Path,
        default=ROOT / "ledger/data/agoda_overlap_resolution_v1.json",
    )
    parser.add_argument(
        "--manual-workbook",
        type=Path,
        default=ROOT / "ledger/data/ledger_current.xlsx",
    )
    parser.add_argument("--detail-output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()
    result = build_artifact(
        args.input_database.resolve(), args.input_audit.resolve(),
        args.output_database.resolve(), args.authority_document.resolve(),
        args.detail_output.resolve(),
        args.audit_output.resolve(),
        overlap_resolution_document=args.overlap_resolution_document.resolve(),
        manual_workbook=args.manual_workbook.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
