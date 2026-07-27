from __future__ import annotations

import csv
import subprocess
import unittest
from io import StringIO
from pathlib import Path

from ledger.domain.source_loss_gate import source_inventory_gate, source_loss_gate


ROOT = Path(__file__).resolve().parents[2]
CURRENT_PROJECTION = ROOT / "ledger" / "data" / "classified_v14.csv"


class SourceLossGateTest(unittest.TestCase):
    def test_inventory_requires_dynamic_reconciliation_and_per_source_floors(self) -> None:
        current = {
            "cards": {"records": 5_237},
            "manual": {"records": 1_526},
            "ota": {"records": 1_720},
            "receipts": {"records": 20},
        }
        report = source_inventory_gate(current, direct_records=8_503)
        self.assertTrue(report["passed"])
        self.assertTrue(report["direct_records_reconciled"])
        self.assertEqual(report["actual"]["manual"], 1_526)

        # Manual append-only growth cannot conceal a lost card source.
        failed = source_inventory_gate(
            current | {"cards": {"records": 5_236}},
            direct_records=8_482,
        )
        self.assertFalse(failed["passed"])
        self.assertIn("cards", failed["below_historical_floor"])

    def test_uid_rekey_candidate_never_becomes_an_automatic_source_match(self) -> None:
        baseline = [
            {
                "uid": "TRIP-0010", "src": "KBD", "appr": "30000001",
                "krw": "1000", "use_date": "2026-04-01", "merchant": "Hotel",
            },
            {
                "uid": "TRIP-0011", "src": "HAN", "appr": "00100001",
                "krw": "2000", "use_date": "2026-04-02", "merchant": "Train",
            },
        ]
        current = [
            {
                "uid": "TRIP-0088", "src": "KBD", "appr": "30000001",
                "krw": "1000", "use_date": "2026-04-01", "merchant": "Hotel",
            }
        ]
        report = source_loss_gate(baseline, current)
        self.assertEqual(report["missing_source_event_ids"], 2)
        self.assertEqual(len(report["rekey_candidates"]), 1)
        self.assertEqual(len(report["closure_blocking_queue"]), 1)
        candidate = report["rekey_candidates"][0]
        self.assertEqual(candidate["source_event_id"], "legacy_uid:TRIP-0010")
        self.assertEqual(candidate["candidate_source_event_id"], "legacy_uid:TRIP-0088")
        self.assertEqual(candidate["status"], "requires_explicit_source_event_id")
        self.assertTrue(report["closure_blocked"])

    def test_explicit_source_event_id_survives_a_display_uid_change(self) -> None:
        baseline = [
            {
                "uid": "TRIP-0010", "source_event_id": "card:KBD:F:18",
                "src": "KBD", "appr": "30000001", "krw": "1000",
                "use_date": "2026-04-01", "merchant": "Hotel",
            }
        ]
        current = [
            {
                "uid": "TRIP-0088", "source_event_id": "card:KBD:F:18",
                "src": "KBD", "appr": "30000001", "krw": "1000",
                "use_date": "2026-04-01", "merchant": "Hotel",
            }
        ]
        report = source_loss_gate(baseline, current)
        self.assertEqual(report["missing_source_event_ids"], 0)
        self.assertFalse(report["closure_blocked"])

    def test_date_shifted_same_approval_and_amount_is_not_a_rekey(self) -> None:
        # A legacy projection can carry an approval/amount that also occurs in
        # a different raw-card lifecycle row.  The date disagreement makes it
        # a rejected-projection review case, never an automatic source link.
        baseline = [{
            "uid": "TRIP-0364", "src": "KBO", "appr": "30000001",
            "krw": "1730635", "use_date": "2026-02-03", "merchant": "ANA",
        }]
        current = [{
            "uid": "KBO-RAW-1", "src": "KBO", "appr": "30000001",
            "krw": "1730635", "use_date": "2026-02-05", "merchant": "ANA",
        }]
        report = source_loss_gate(baseline, current)
        self.assertFalse(report["rekey_candidates"])
        self.assertEqual(
            report["closure_blocking_queue"][0]["source_event_id"],
            "legacy_uid:TRIP-0364",
        )

    def test_approval_less_uid_move_is_diagnostic_only_until_identity_is_explicit(self) -> None:
        baseline = [{
            "uid": "TRIP-0332", "src": "KBO", "appr": "",
            "krw": "1079353", "use_date": "2026-02-03", "merchant": "ANA",
        }]
        current = [{
            "uid": "TRIP-0345", "src": "KBO", "appr": "",
            "krw": "1079353", "use_date": "2026-02-03", "merchant": "ANA",
        }]
        report = source_loss_gate(baseline, current)
        self.assertEqual(len(report["unproven_structural_candidates"]), 1)
        self.assertEqual(
            report["unproven_structural_candidates"][0]["status"],
            "not_a_source_event_match",
        )
        self.assertEqual(len(report["closure_blocking_queue"]), 1)

    def test_same_approval_in_another_card_source_is_not_a_source_merge(self) -> None:
        # Source and approval can collide across card issuers.  The source is
        # part of the candidate key, so KBO -> KBD drift remains blocked.
        baseline = [{
            "uid": "TRIP-0228", "src": "KBO", "appr": "30099001",
            "krw": "306000", "use_date": "2026-01-29", "merchant": "Trip.com",
        }]
        current = [{
            "uid": "KBD-0990", "src": "KBD", "appr": "30099001",
            "krw": "306000", "use_date": "2026-01-29", "merchant": "Trip.com",
        }]
        report = source_loss_gate(baseline, current)
        self.assertFalse(report["rekey_candidates"])
        self.assertFalse(report["unproven_structural_candidates"])
        self.assertEqual(len(report["closure_blocking_queue"]), 1)

    def test_raw_refund_disappearance_is_a_close_blocker(self) -> None:
        refund = {
            "uid": "TRIP-0146",
            "source_event_id": "card:KBD:raw-refund-291800",
            "src": "KBD",
            "appr": "",
            "orig_appr": "30057229",
            "krw": "-291800",
            "use_date": "2026-03-10",
            "merchant": "TRIP.COM NICE",
            "cancel": "True",
        }
        report = source_loss_gate([refund], [])
        self.assertTrue(report["closure_blocked"])
        self.assertEqual(report["missing_source_event_ids"], 1)
        self.assertEqual(
            report["closure_blocking_queue"],
            [{
                "source_event_id": "card:KBD:raw-refund-291800",
                "uid": "TRIP-0146",
                "src": "KBD",
                "approval_number": "",
                "amount_krw": "-291800",
                "occurred_on": "2026-03-10",
                "identity_quality": "explicit",
                "status": "source_event_absent",
                "approval_candidate_count": 0,
                "unproven_structural_candidate_count": 0,
            }],
        )

    def test_reviewed_display_uid_alias_explains_but_never_clears_refund_loss(self) -> None:
        baseline = [{
            "uid": "TRIP-0135", "src": "KBD", "appr": "",
            "orig_appr": "30057229", "krw": "-291800",
            "use_date": "2026-03-10", "merchant": "TRIP.COM NICE",
        }]
        current = [{
            "uid": "TRIP-0146", "src": "KBD", "appr": "",
            "orig_appr": "30057229", "krw": "-291800",
            "use_date": "2026-03-10", "merchant": "TRIP.COM NICE",
        }]
        report = source_loss_gate(
            baseline,
            current,
            reviewed_display_uid_aliases={"TRIP-0135": "TRIP-0146"},
        )
        self.assertEqual(
            report["reviewed_display_uid_aliases"],
            [{
                "source_event_id": "legacy_uid:TRIP-0135",
                "uid": "TRIP-0135", "src": "KBD", "approval_number": "",
                "amount_krw": "-291800", "occurred_on": "2026-03-10",
                "identity_quality": "legacy_uid_fallback", "candidate_uid": "TRIP-0146",
                "status": "display_uid_alias_not_source_identity",
            }],
        )
        self.assertTrue(report["closure_blocked"])

    def test_current_projection_matches_committed_source_snapshot(self) -> None:
        baseline_text = subprocess.run(
            ["git", "show", "HEAD:ledger/data/classified_v14.csv"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
        baseline = list(csv.DictReader(StringIO(baseline_text)))
        with CURRENT_PROJECTION.open(encoding="utf-8", newline="") as stream:
            current_rows = list(csv.DictReader(stream))
        self.assertEqual(len(baseline), len(current_rows))

        report = source_loss_gate(baseline, current_rows)
        self.assertEqual(report["missing_source_event_ids"], 0)
        self.assertEqual(report["added_source_event_ids"], 0)
        self.assertEqual(report["net_row_delta"], 0)
        self.assertEqual(report["rekey_candidates"], [])
        self.assertEqual(report["closure_blocking_queue"], [])
        self.assertEqual(report["unproven_structural_candidates"], [])
        self.assertFalse(report["closure_blocked"])
        self.assertTrue(
            all(
                row["status"] == "source_event_absent"
                for row in report["closure_blocking_queue"]
            )
        )


if __name__ == "__main__":
    unittest.main()
