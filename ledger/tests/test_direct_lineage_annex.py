from __future__ import annotations

import json
import csv
import hashlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from ledger.domain.direct_lineage_annex import build_annex, verify_annex, _install_noreplace


class DirectLineageAnnexTest(unittest.TestCase):
    def test_real_fixed_census_and_authority_boundary(self) -> None:
        result = build_annex()
        manifest = result["manifest"]
        self.assertEqual(manifest["counts"]["direct"], 5328)
        self.assertEqual(manifest["counts"]["exact_proposals"], 1227)
        self.assertEqual(manifest["counts"]["p0_high_complete"], 932)
        self.assertEqual(manifest["counts"]["other_proposals"], 295)
        self.assertEqual(manifest["counts"]["unmatched"], 4101)
        self.assertEqual(manifest["counts"]["stable_identity"], 464)
        self.assertEqual(manifest["counts"]["compound_posted_merchant_exact"], 923)
        self.assertEqual(manifest["counts"]["compound_high_high_both_exact"], 787)
        self.assertEqual(manifest["counts"]["independent_posted_merchant_exact"], 925)
        self.assertEqual(manifest["counts"]["independent_high_high"], 788)
        self.assertEqual(manifest["counts"]["independent_high_high_complete"], 777)
        self.assertEqual(manifest["source_counts"], {"KBD": 409, "KBO": 343, "HAN": 425, "CORP": 50})
        self.assertEqual((manifest["counts"]["collision_current_groups"], manifest["counts"]["collision_current_rows"], manifest["counts"]["collision_historical_groups"], manifest["counts"]["collision_historical_rows"]), (64, 216, 19, 48))
        for envelope in result["package"]["envelopes"]:
            self.assertIn(envelope["lineage_tier"], {"stable_identity", "compound_exact", "unmatched"})
            self.assertIsInstance(envelope["posted_date_exact"], bool)
            self.assertIsInstance(envelope["merchant_exact"], bool)
            self.assertIn(envelope["collision_reason"], {None, "current_duplicate", "historical_duplicate", "no_exact_candidate"})
            if envelope["lineage_tier"] == "unmatched":
                self.assertIsNotNone(envelope["collision_reason"])
            else:
                self.assertIsNone(envelope["collision_reason"])
        self.assertEqual(manifest["authority_status"], "unattested")
        self.assertEqual(manifest["posting_status"], "blocked")
        self.assertEqual(manifest["confirmed_count"], 0)
        self.assertEqual(manifest["gate5_credit"], 0)
        self.assertNotIn("owner", json.dumps(result["package"], ensure_ascii=False))

    def test_external_csv_round_trip_and_manifest_context_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            output = Path(dirname) / "annex"
            result = build_annex(output=output)
            with (output / "events.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            envelopes = {item["direct_event_key"]: item for item in result["package"]["envelopes"]}
            self.assertEqual(len(rows), 5328)
            for row in rows:
                envelope = envelopes[row["direct_event_key"]]
                self.assertEqual(row["current_event_sha256"], envelope["current_event_sha256"])
                self.assertEqual(row["lineage_tier"], envelope["lineage_tier"])
                self.assertEqual(row["posted_date_exact"], str(envelope["posted_date_exact"]).lower())
                self.assertEqual(row["merchant_exact"], str(envelope["merchant_exact"]).lower())
                self.assertEqual(row["collision_reason"], envelope["collision_reason"] or "")
                self.assertEqual(row["current_source_kind"], envelope["current_source_kind"])
                self.assertEqual(row["current_source_key"], envelope["current_source_key"])
                self.assertEqual(row["current_source_sha256"], envelope["current_source_sha256"])
                self.assertEqual(json.loads(row["proposal_json"]), envelope["proposal"])
            manifest_path = output / "manifest.json"
            original = manifest_path.read_bytes()
            tampered = json.loads(original)
            tampered["current_event_set_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest_context"):
                verify_annex(output)
            manifest_path.write_bytes(original)
            self.assertEqual(verify_annex(output)["status"], "valid")

    def test_verifier_schema_and_live_rebuild_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            output = Path(dirname) / "annex"
            build_annex(output=output)
            manifest_path = output / "manifest.json"
            original = manifest_path.read_bytes()
            tampered = json.loads(original)
            tampered["counts"]["direct"] = 1
            manifest_path.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "events_count"):
                verify_annex(output)
            manifest_path.write_bytes(original)
            events_path = output / "events.csv"
            original_events = events_path.read_bytes()
            events_path.write_bytes(original_events.replace(b"lineage_tier", b"unknown_tier", 1))
            tampered = json.loads(original)
            tampered["events_sha256"] = hashlib.sha256(events_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "(events_schema|envelope_hash)"):
                verify_annex(output)
            events_path.write_bytes(original_events)
            manifest_path.write_bytes(original)
            self.assertEqual(verify_annex(output)["status"], "valid")

    def test_live_verifier_rejects_self_consistent_forged_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            output = Path(dirname) / "annex"
            build_annex(output=output)
            events_path = output / "events.csv"
            with events_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["proposal_json"] = json.dumps({"bucket": "FORGED_TARGET"}, separators=(",", ":"))
            with events_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
                writer.writeheader(); writer.writerows(rows)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["events_sha256"] = hashlib.sha256(events_path.read_bytes()).hexdigest()
            manifest["envelope_set_sha256"] = manifest["events_sha256"]
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_annex(output)

    def test_two_runs_deterministic_and_cli_temp_output(self) -> None:
        first = build_annex(); second = build_annex()
        self.assertEqual((first["manifest_sha256"], first["events_sha256"]), (second["manifest_sha256"], second["events_sha256"]))
        with tempfile.TemporaryDirectory(prefix="r23-test-") as dirname:
            output = Path(dirname) / "annex"
            proc = subprocess.run(["python3", "-m", "ledger.domain.direct_lineage_annex", "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue((output / "manifest.json").is_file()); self.assertTrue((output / "events.csv").is_file())

    def test_noncanonical_output_and_tamper_rejected(self) -> None:
        with self.assertRaises(ValueError): build_annex(ledger_dir=Path("/tmp"))
        with tempfile.TemporaryDirectory() as dirname:
            output = Path(dirname) / "annex"; build_annex(output=output)
            with self.assertRaises(FileExistsError): build_annex(output=output)

    def test_broken_symlink_output_is_existing_and_parent_is_canonicalized(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname); alias = root / "alias"; alias.symlink_to(root / "missing", target_is_directory=True)
            with self.assertRaisesRegex(FileExistsError, "r23_output_exists"):
                build_annex(output=alias)
            destination = root / "destination"; destination.mkdir(); normal = root / "normal"; normal.symlink_to(destination, target_is_directory=True)
            with self.assertRaisesRegex(FileExistsError, "r23_output_exists"):
                build_annex(output=normal)
            link = root / "repo-link"; link.symlink_to(Path.cwd(), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "r23_output_inside_repository"):
                build_annex(output=link / "annex", ledger_dir=Path("ledger"))

    def test_unsupported_noreplace_fails_closed_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname); stage = root / "stage"; stage.mkdir(); target = root / "target"
            with patch("ledger.domain.direct_lineage_annex.ctypes.CDLL", side_effect=AttributeError):
                with self.assertRaisesRegex(OSError, "r23_atomic_noreplace_unsupported"):
                    _install_noreplace(stage, target)
            self.assertFalse(target.exists())
            self.assertTrue(stage.exists())

    def test_renameat2_race_preserves_competing_target(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname); stage = root / "stage"; stage.mkdir(); target = root / "target"
            class FakeLib:
                class Rename:
                    argtypes = None; restype = None
                    def __call__(self, oldfd, oldname, newfd, newname, flags):
                        target.mkdir()
                        import ctypes
                        ctypes.set_errno(errno.EEXIST)
                        return -1
                renameat2 = Rename()
            import errno
            with patch("ledger.domain.direct_lineage_annex.ctypes.CDLL", return_value=FakeLib()):
                with self.assertRaisesRegex(FileExistsError, "r23_output_exists"):
                    _install_noreplace(stage, target)
            self.assertTrue(target.is_dir())
            self.assertTrue(stage.exists())

    def test_public_verify_rejects_event_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            output = Path(dirname) / "annex"; build_annex(output=output)
            self.assertEqual(verify_annex(output)["status"], "valid")
            events = output / "events.csv"; events.write_bytes(events.read_bytes() + b"tamper\n")
            with self.assertRaisesRegex(ValueError, "events_hash_mismatch"): verify_annex(output)


if __name__ == "__main__": unittest.main()
