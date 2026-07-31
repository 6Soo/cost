from __future__ import annotations

import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from ledger.domain.reference_namespace_report import build_report, main


class ReferenceNamespaceReportTest(unittest.TestCase):
    def test_current_absent_census_and_canonical_stdout(self) -> None:
        report = build_report(Path("ledger/data"))
        self.assertEqual(
            [report["references"][name]["absent_from_current_count"] for name in (
                "fixes.json", "matched_uids.json", "matched_fresh.json", "ota_event_links_verified.json"
            )],
            [2, 28, 2, 0],
        )

    def test_output_rejects_repository_and_existing_paths(self) -> None:
        with self.assertRaises(SystemExit) as error:
            main(["--output", "ledger/reference.json"])
        self.assertEqual(error.exception.code, 2)

    def test_report_bytes_are_deterministic_and_malformed_input_fails(self) -> None:
        first = json.dumps(build_report(Path("ledger/data")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        second = json.dumps(build_report(Path("ledger/data")), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname); (root / "classified_v14.csv").write_text("uid\nA\nA\n", encoding="utf-8")
            for name in ("fixes.json", "matched_uids.json", "matched_fresh.json", "ota_event_links_verified.json"):
                (root / name).write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "v14_uid_invalid_or_duplicate"):
                build_report(root)

    def test_duplicate_uid_in_json_object_fails_before_object_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname); (root / "classified_v14.csv").write_text("uid\nA\n", encoding="utf-8")
            (root / "fixes.json").write_text('{"A": 1, "A": 2}', encoding="utf-8")
            for name in ("matched_uids.json", "matched_fresh.json", "ota_event_links_verified.json"):
                (root / name).write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reference_duplicate_uid:fixes.json"):
                build_report(root)

    def test_duplicate_uid_in_list_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname); (root / "classified_v14.csv").write_text("uid\nA\n", encoding="utf-8")
            (root / "fixes.json").write_text('[{"uid":"X"},{"uid":"X"}]', encoding="utf-8")
            for name in ("matched_uids.json", "matched_fresh.json", "ota_event_links_verified.json"):
                (root / name).write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reference_duplicate_uid:fixes.json"):
                build_report(root)


if __name__ == "__main__":
    unittest.main()
