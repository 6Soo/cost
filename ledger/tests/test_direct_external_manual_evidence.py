from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ledger.domain.direct_external_manual_evidence import (
    _amount,
    _date,
    _manual,
    _merchant_compatible,
    _provider,
    _require_same_event_set,
    build_external_manual_evidence,
    verify_external_manual_evidence,
)


class DirectExternalManualEvidenceTest(unittest.TestCase):
    def test_alias_contract_separates_exclusive_providers(self) -> None:
        self.assertEqual(_provider("MYTRIP 항공권"), "mytrip")
        self.assertEqual(_provider("고투게이트 결제"), "gotogate")
        self.assertFalse(_merchant_compatible("MYTRIP", "고투게이트"))
        self.assertTrue(_merchant_compatible("AGODA.COM HOTEL", "아고다_호텔"))
        self.assertFalse(_merchant_compatible("", "아고다"))

    def test_independent_exact_merchant_set_mismatch_fails_closed(self) -> None:
        _require_same_event_set({"event-a"}, {"event-a"})
        with self.assertRaisesRegex(ValueError, "signed_exact_merchant_set_mismatch"):
            _require_same_event_set({"event-a"}, {"event-b"})

    def test_strict_manual_parser_rejects_fractional_and_duplicate_locator(self) -> None:
        self.assertEqual(_date("26.04.01"), "2026-04-01")
        self.assertEqual(_date("99.12.31"), "2099-12-31")
        for invalid_date in ("2026.04.01", "26-04-01", "26.02.30"):
            with self.assertRaisesRegex(ValueError, "date_invalid"):
                _date(invalid_date)
        self.assertEqual(_amount("-34500.0"), -34500)
        for invalid in ("1.5", "NaN", "Infinity", ""):
            with self.assertRaisesRegex(ValueError, "amount_invalid"):
                _amount(invalid)
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "manual.csv"
            path.write_text(
                "tab,row,date,item,desc,card,amount,book\n"
                "T,1,26.04.01,A,B,국민,100,REF1\n"
                "T,1,26.04.02,C,D,하나,200,REF2\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "locator_invalid"):
                _manual(path)

    def test_committed_manual_round_trip_authority_and_tamper(self) -> None:
        manual = Path("ledger/data/manual_v4.csv").resolve()
        with tempfile.TemporaryDirectory(prefix="r25-package-") as dirname:
            output = Path(dirname) / "package"
            result = build_external_manual_evidence(manual, output=output)
            manifest = result["manifest"]
            self.assertEqual(manifest["authority_status"], "unattested")
            self.assertEqual(manifest["posting_status"], "blocked")
            self.assertEqual(manifest["confirmed_count"], 0)
            self.assertEqual(manifest["gate5_credit"], 0)
            self.assertEqual(verify_external_manual_evidence(output, manual_csv=manual)["status"], "valid")
            proposals = output / "proposals.csv"
            original = proposals.read_bytes()
            proposals.write_bytes(original + b"tamper\n")
            with self.assertRaisesRegex(ValueError, "(file_hash|live_context)"):
                verify_external_manual_evidence(output, manual_csv=manual)
            proposals.write_bytes(original)
            manifest_path = output / "manifest.json"
            original_manifest = manifest_path.read_bytes()
            rows = list(csv.DictReader(original.decode("utf-8").splitlines()))
            rows[0]["disposition"] = "self_consistent_forgery"
            with proposals.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
            forged_manifest = json.loads(original_manifest)
            forged_manifest["files"]["proposals.csv"]["sha256"] = hashlib.sha256(proposals.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(forged_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "live_context"):
                verify_external_manual_evidence(output, manual_csv=manual)
            proposals.write_bytes(original); manifest_path.write_bytes(original_manifest)
            manifest = json.loads(original_manifest)
            manifest["gate5_credit"] = 1
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "authority_boundary"):
                verify_external_manual_evidence(output, manual_csv=manual)
            manifest_path.write_bytes(original_manifest)
            diagnostics = output / "diagnostics.csv"
            copy = Path(dirname) / "diagnostics-copy.csv"
            copy.write_bytes(diagnostics.read_bytes())
            diagnostics.unlink(); diagnostics.symlink_to(copy)
            with self.assertRaisesRegex(ValueError, "package_file_invalid"):
                verify_external_manual_evidence(output, manual_csv=manual)

    def test_latest_full_snapshot_census_when_available(self) -> None:
        manual = Path("/tmp/cost-r25-manual-v4.csv")
        if not manual.is_file():
            self.skipTest("latest full Drive parse is external")
        result = build_external_manual_evidence(manual)
        counts = result["manifest"]["counts"]
        self.assertEqual(result["manifest"]["manual_raw_sha256"], "2c6d7486458a0921186311780cb2fab26950c13b369d8cf876a5ad04cac10489")
        self.assertEqual((counts["isolated_total"], counts["known_agreement"], counts["classification_conflicts"], counts["new_proposals"]), (1043, 847, 8, 188))
        self.assertEqual(counts["source_counts"], {"CORP": 2, "HAN": 65, "KBD": 94, "KBO": 27})
        self.assertEqual(counts["role_counts"], {"approval": 4, "single": 184})
        self.assertEqual((counts["merchant_exact"], counts["merchant_containment"], counts["booking_present"], counts["booking_ref_exact"], counts["booking_ref_unique"]), (19, 87, 67, 32, 28))
        self.assertEqual(counts["merchant_alias_compatible_within_188"], 143)
        self.assertEqual((counts["independent_signed_exact_merchant"], counts["signed_exact_merchant_set_equal"]), (19, True))
        self.assertEqual((counts["merchant_alias_bilateral"], counts["merchant_alias_intersect_primary"], counts["merchant_alias_only_not_primary"]), (143, 143, 0))
        self.assertRegex(result["manifest"]["alias_contract_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(counts["r23_unmatched"], 4101)
        self.assertEqual(counts["evidence_set_counts"], {"amount_conflict_21": 21, "clean_110": 110, "group_members_29": 29, "manual_signed_exact_19": 19, "portal_1": 1, "typed_v14_65": 65})
        self.assertEqual(counts["event_id_intersections"], {"manual_188_intersect_amount_conflict_21": 0, "manual_188_intersect_clean_110": 90, "manual_188_intersect_group_members_29": 0, "manual_188_intersect_manual_signed_exact_19": 19, "manual_188_intersect_portal_1": 0, "manual_188_intersect_typed_v14_65": 2})
        self.assertEqual((counts["individual_proposal_event_union"], counts["remaining_after_individual_proposal_union"]), (272, 3829))
        self.assertEqual(counts["negative_proposals"], 5)
        self.assertEqual(counts["remaining_r23_unmatched"], 3913)

    def test_abs_sign_is_not_used_by_match_rule(self) -> None:
        manual = Path("/tmp/cost-r25-manual-v4.csv")
        if not manual.is_file():
            self.skipTest("latest full Drive parse is external")
        with tempfile.TemporaryDirectory(prefix="r25-sign-") as dirname:
            output = Path(dirname) / "package"
            build_external_manual_evidence(manual, output=output)
            with (output / "proposals.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(sum(int(row["signed_amount_krw"]) < 0 for row in rows), 5)
            self.assertTrue(all(row["match_rule"] == "exact-source-date-signed-amount-bilateral-v1" for row in rows))
            self.assertEqual(len({row["direct_event_key"] for row in rows}), len(rows))
            self.assertEqual(len({row["manual_locator"] for row in rows}), len(rows))
            self.assertTrue(all(json.loads(json.dumps(row)) for row in rows))
            self.assertEqual(sum(row["merchant_alias_compatible"] == "true" for row in rows), 143)
            with (output / "conflicts.csv").open(encoding="utf-8", newline="") as stream:
                conflicts = list(csv.DictReader(stream))
            self.assertEqual(len(conflicts), 8)
            self.assertTrue(all(row["historical_proposal_json"] and row["manual_row_json"] and row["current_source_sha256"] for row in conflicts))
            with (output / "diagnostics.csv").open(encoding="utf-8", newline="") as stream:
                diagnostics = list(csv.DictReader(stream))
            self.assertEqual(len(diagnostics), 2)
            self.assertTrue(all(row["diagnostic_type"] == "malformed_manual_row" for row in diagnostics))


if __name__ == "__main__":
    unittest.main()
