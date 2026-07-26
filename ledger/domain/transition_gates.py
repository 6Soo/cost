"""v2 전환 게이트 7개를 기계적으로 검증한다."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ledger.domain.ledger_db import (
    DEFAULT_CSV,
    LEDGER_DIR,
    connect,
    review_report,
    validation_report,
)
from ledger.domain.review_verifier import verify_review_claims
from ledger.domain.v2_workbook_adapter import regression_report


def build_gate_report(db_path: Path, baseline: Path) -> dict[str, object]:
    db = connect(db_path)
    try:
        validation = validation_report(db)
        review = review_report(db)
        regression = regression_report(db, baseline)
        review_claims = verify_review_claims(
            DEFAULT_CSV,
            LEDGER_DIR / "data" / "manual_v4.csv",
            LEDGER_DIR / "data" / "ota_mail_index.json",
        )
        direct_sources = int(
            db.execute(
                "SELECT COUNT(*) FROM direct_source_records WHERE source_kind='card_raw'"
            ).fetchone()[0]
        )
        direct_payments = int(
            db.execute("SELECT COUNT(*) FROM direct_normalized_payments").fetchone()[0]
        )
        expected_direct_payments = int(
            db.execute(
                """
                SELECT COUNT(*) + COALESCE(SUM(
                    CASE
                      WHEN json_extract(payload_json, '$.src')='HAN'
                       AND CAST(json_extract(payload_json, '$.cancel_amount') AS INTEGER)<>0
                      THEN 1 ELSE 0
                    END
                ), 0)
                FROM direct_source_records
                WHERE source_kind='card_raw'
                """
            ).fetchone()[0]
        )
        gates = [
            {
                "gate": 1,
                "name": "direct_card_source_count",
                "passed": (
                    expected_direct_payments == direct_payments
                    and direct_sources > 0
                ),
                "actual": {
                    "source_records": direct_sources,
                    "expected_events": expected_direct_payments,
                    "normalized": direct_payments,
                },
            },
            {
                "gate": 2,
                "name": "payment_allocation_total",
                "passed": (
                    validation["transaction_total_krw"]
                    == validation["allocation_total_krw"]
                ),
                "actual": {
                    "payments": validation["transaction_total_krw"],
                    "allocations": validation["allocation_total_krw"],
                },
            },
            {
                "gate": 3,
                "name": "per_payment_allocation",
                "passed": validation["allocation_mismatches"] == 0,
                "actual": validation["allocation_mismatches"],
            },
            {
                "gate": 4,
                "name": "refund_relations_reviewed",
                "passed": validation["unexplained_transaction_relations"] == 0,
                "actual": {
                    "outside_window": validation["outside_window_transaction_relations"],
                    "insufficient_evidence": validation[
                        "insufficient_evidence_transaction_relations"
                    ],
                    "unexplained": validation["unexplained_transaction_relations"],
                },
            },
            {
                "gate": 5,
                "name": "booking_target_conflicts",
                "passed": review["bookings_linked_to_multiple_targets"] == 0,
                "actual": review["bookings_linked_to_multiple_targets"],
            },
            {
                "gate": 6,
                "name": "high_confidence_uncertain_rationale",
                "passed": review["high_confidence_with_uncertain_rationale"] == 0,
                "actual": review["high_confidence_with_uncertain_rationale"],
            },
            {
                "gate": 7,
                "name": "workbook_regression_explained",
                "passed": regression["unexplained_differences"] == 0,
                "actual": regression,
            },
            {
                "gate": 8,
                "name": "review_claims_evidence_consistent",
                "passed": review_claims["passed"],
                "actual": {
                    "assertion_count": review_claims["assertion_count"],
                    "counts": review_claims["counts"],
                    "collection_blockers": {
                        name: review_claims["counts"].get(name, 0)
                        for name in (
                            "attachment_required",
                            "forwarded_unextracted",
                        )
                    },
                    "ota_field_loss_by_type": {
                        name: review_claims["counts"].get(name, 0)
                        for name in (
                            "ota_booking_ref_loss",
                            "ota_amount_loss",
                            "ota_travel_date_loss",
                        )
                    },
                },
            },
        ]
        return {
            "format_version": 2,
            "passed": all(bool(gate["passed"]) for gate in gates),
            "gates": gates,
            "cutover_policy": (
                "ready_for_user_approval"
                if all(bool(gate["passed"]) for gate in gates)
                else "legacy_path_remains_authoritative"
            ),
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_gate_report(args.db, args.baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
