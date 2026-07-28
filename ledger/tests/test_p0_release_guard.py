from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ledger.domain.p0_release_guard import (
    P0GuardError,
    canonical_csv_census,
    file_sha256,
    validate_candidate_against_frozen_canonical,
    validate_input_contract,
    verify_release_block,
)


ROOT = Path(__file__).resolve().parents[2]
BASELINE = (
    ROOT / "ledger" / "baselines" / "p0_current_canonical_20260728_v2"
)
MANIFEST = BASELINE / "manifest.json"
RELEASE_BLOCKS = (
    ROOT
    / "ledger"
    / "baselines"
    / "p0_current_canonical_20260728"
    / "release_blocks.json"
)


class P0CanonicalManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.release_blocks = json.loads(
            RELEASE_BLOCKS.read_text(encoding="utf-8")
        )

    def test_frozen_canonical_facts_match_current_file(self) -> None:
        canonical = self.manifest["canonical"]
        path = ROOT / canonical["path"]
        self.assertEqual(file_sha256(path), canonical["sha256"])
        self.assertEqual(path.stat().st_size, canonical["bytes"])
        self.assertEqual(
            canonical_csv_census(path),
            canonical["census"],
        )

    def test_current_input_bundle_matches_every_stage_contract(self) -> None:
        contract = self.manifest["input_contract"]
        for stage in contract["stage_policies"]:
            with self.subTest(stage=stage):
                result = validate_input_contract(ROOT, contract, stage)
                self.assertTrue(result["passed"])

    def test_required_missing_fails_and_optional_missing_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            present = root / "present.txt"
            present.write_text("fixed input\n", encoding="utf-8")
            digest = hashlib.sha256(present.read_bytes()).hexdigest()
            contract = {
                "stage_policies": {"test": "fixture"},
                "inputs": [
                    {
                        "path": "present.txt",
                        "sha256": digest,
                        "bytes": present.stat().st_size,
                        "stages": {"test": "required"},
                    },
                    {
                        "path": "optional.txt",
                        "stages": {"test": "optional"},
                    },
                ],
            }
            result = validate_input_contract(root, contract, "test")
            self.assertEqual(result["missing_optional"], ["optional.txt"])

            contract["inputs"].append(
                {
                    "path": "required-missing.txt",
                    "stages": {"test": "required"},
                }
            )
            with self.assertRaisesRegex(
                P0GuardError, "required input is missing"
            ):
                validate_input_contract(root, contract, "test")

    def test_hash_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            path = root / "input.json"
            path.write_text('{"records": [1]}', encoding="utf-8")
            contract = {
                "stage_policies": {"test": "fixture"},
                "inputs": [
                    {
                        "path": "input.json",
                        "sha256": "0" * 64,
                        "record_count": 1,
                        "stages": {"test": "required"},
                    }
                ],
            }
            with self.assertRaisesRegex(P0GuardError, "sha256"):
                validate_input_contract(root, contract, "test")

    def test_candidate_loss_or_amount_mutation_fails_closed(self) -> None:
        canonical_path = ROOT / self.manifest["canonical"]["path"]
        import csv
        with canonical_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        passed = validate_candidate_against_frozen_canonical(ROOT, rows)
        self.assertEqual(passed["row_count"], 1834)
        with self.assertRaisesRegex(P0GuardError, "missing="):
            validate_candidate_against_frozen_canonical(ROOT, rows[:-1])
        mutated = copy.deepcopy(rows)
        mutated[0]["krw"] = str(int(float(mutated[0]["krw"])) + 1)
        with self.assertRaisesRegex(P0GuardError, "mutated="):
            validate_candidate_against_frozen_canonical(ROOT, mutated)

    def test_candidate_gate_verifies_reference_file_hash(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            canonical = root / "canonical.csv"
            canonical.write_text(
                "uid,src,use_date,card4,currency,foreign,krw,vat,tax_type,"
                "bucket,account,cancel,cost_type,vat_tag,appr,orig_appr\n"
                "A,KBO,2026-01-01,1234,KRW,,100,0,과세,X,숙박비,"
                "False,여행원가,불공제,1,\n",
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "canonical": {
                            "path": "canonical.csv",
                            "sha256": file_sha256(canonical),
                            "bytes": canonical.stat().st_size,
                        }
                    }
                ),
                encoding="utf-8",
            )
            canonical.write_text(
                canonical.read_text(encoding="utf-8").replace(",100,", ",101,"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                P0GuardError, "frozen canonical sha256 drift"
            ):
                validate_candidate_against_frozen_canonical(
                    root,
                    [],
                    Path("manifest.json"),
                )

    def test_recorded_input_amount_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            path = root / "input.csv"
            path.write_text("uid,krw\nA,100\nB,-20\n", encoding="utf-8")
            contract = {
                "stage_policies": {"test": "fixture"},
                "inputs": [
                    {
                        "path": "input.csv",
                        "record_count": 2,
                        "signed_amount_krw": 81,
                        "stages": {"test": "required"},
                    }
                ],
            }
            with self.assertRaisesRegex(P0GuardError, "signed amount 80 != 81"):
                validate_input_contract(root, contract, "test")

    def test_blocked_artifacts_match_recorded_facts_when_present(self) -> None:
        for block in self.release_blocks["artifacts"]:
            with self.subTest(block=block["id"]):
                result = verify_release_block(ROOT, block)
                self.assertEqual(result["status"], "blocked")
                paths = [ROOT / path for path in block["paths"].values()]
                self.assertEqual(
                    result["available"],
                    all(path.exists() for path in paths),
                )

    def test_workbook_block_records_exact_financial_difference(self) -> None:
        workbook = next(
            block
            for block in self.release_blocks["artifacts"]
            if block["id"] == "cost-workbook-v76"
        )
        facts = workbook["observed"]
        self.assertEqual(facts["canonical_amount_krw"], 320055642)
        self.assertEqual(facts["summary_ai_expense_krw"], 324471472)
        self.assertEqual(facts["summary_difference_krw"], 4415830)
        self.assertEqual(facts["preperiod_refund_amount_krw"], -4415830)
        self.assertIn(
            "summary_amount_mismatch",
            workbook["reason_codes"],
        )

    def test_hardcoded_block_fact_drift_fails(self) -> None:
        for original in self.release_blocks["artifacts"]:
            paths = [ROOT / path for path in original["paths"].values()]
            if not all(path.exists() for path in paths):
                continue
            block = copy.deepcopy(original)
            if block["kind"] == "xlsx":
                block["observed"]["summary_difference_krw"] += 1
            else:
                block["observed"]["disposition_rows"] += 1
            with self.subTest(block=block["id"]):
                with self.assertRaisesRegex(
                    P0GuardError, "blocked artifact facts drifted"
                ):
                    verify_release_block(ROOT, block)

    def test_missing_blocked_artifact_remains_blocked(self) -> None:
        block = {
            "id": "missing-fixture",
            "kind": "pending_report",
            "status": "blocked",
            "missing_artifact_policy": "remain_blocked",
            "paths": {
                "summary": "missing/summary.json",
                "dispositions": "missing/dispositions.csv",
            },
            "observed": {},
        }
        result = verify_release_block(ROOT, block)
        self.assertEqual(
            result,
            {
                "available": False,
                "missing": [
                    "missing/dispositions.csv",
                    "missing/summary.json",
                ],
                "status": "blocked",
            },
        )


if __name__ == "__main__":
    unittest.main()
