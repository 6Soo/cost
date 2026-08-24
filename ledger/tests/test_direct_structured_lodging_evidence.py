from __future__ import annotations

import csv
import io
import json
import copy
import tempfile
import unittest
from ledger.tests._platform import requires_staged_evidence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from ledger.domain import direct_structured_lodging_evidence as r38


@requires_staged_evidence()
class StructuredLodgingEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.files = r38._build(Path("ledger"))

    @staticmethod
    def _rows(raw):
        return list(csv.DictReader(io.StringIO(raw.decode())))

    def _write(self, root):
        target = root / "artifact"; target.mkdir(mode=0o700)
        for name, data in self.files.items():
            path = target / name; path.write_bytes(data); path.chmod(0o600)
        return target

    def test_exact_contract_authority_privacy_and_partition(self):
        manifest = self.manifest
        self.assertEqual(manifest["selected_event_set_sha256"], r38.SELECTED_SET_SHA256)
        self.assertEqual(manifest["semantic_set_sha256"], r38.SEMANTIC_SHA256)
        self.assertEqual(manifest["remaining_event_set_sha256"], r38.REMAINING_SET_SHA256)
        self.assertEqual(manifest["counts"], {"r37_deferred": 26, "proposals": 2, "remaining": 24,
                                               "confirmed": 0, "gate5_credit": 0})
        proposals = self._rows(self.files["proposals.csv"])
        exclusions = self._rows(self.files["exclusions.csv"])
        groups = self._rows(self.files["groups.csv"])
        self.assertEqual((len(proposals), len(exclusions), len(groups)), (2, 24, 1))
        self.assertTrue(all((x["account"], x["cost_type"], x["vat_tag"]) ==
                            ("숙박비", "여행원가", "불공제_해외") for x in proposals))
        self.assertTrue(all(x["bijection_asserted"] == "false" for x in proposals + groups))
        forbidden = {"booking_reference", "manual_locator", "amount", "merchant", "date", "email", "card_number"}
        self.assertFalse(any(column in forbidden for columns in (r38.GROUP_COLUMNS, r38.PROPOSAL_COLUMNS, r38.EXCLUSION_COLUMNS)
                             for column in columns))

    def test_round_trip_and_package_tamper_fail_closed(self):
        with tempfile.TemporaryDirectory() as dirname:
            target = self._write(Path(dirname))
            with patch.object(r38, "_build", return_value=(self.manifest, self.files)):
                self.assertEqual(r38.verify_structured_lodging_evidence(target)["status"], "valid")
                rows = self._rows((target / "proposals.csv").read_bytes()); rows[0]["vat_tag"] = "확인"
                (target / "proposals.csv").write_bytes(r38._csv(r38.PROPOSAL_COLUMNS, rows))
                with self.assertRaisesRegex(ValueError, "package_mismatch"):
                    r38.verify_structured_lodging_evidence(target)

    def test_authority_mode_extra_and_noncanonical_booking_fail_closed(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname); target = self._write(root)
            manifest = json.loads((target / "manifest.json").read_bytes()); manifest["applied"] = True
            (target / "manifest.json").write_bytes(r38.r36._json(manifest)); (target / "manifest.json").chmod(0o600)
            with self.assertRaisesRegex(ValueError, "authority_boundary"):
                r38.verify_structured_lodging_evidence(target)
            (target / "manifest.json").write_bytes(self.files["manifest.json"]); (target / "extra").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "package_shape"):
                r38.verify_structured_lodging_evidence(target)
            copied = root / "booking.json"; copied.write_bytes((Path("ledger/data/booking_info.json")).read_bytes())
            with self.assertRaisesRegex(ValueError, "noncanonical_booking_info"):
                r38._build(Path("ledger"), booking_info=copied)

    def test_upstream_rule_selected_reason_and_source_drift_fail_closed(self):
        original_build = r38.r37._build
        manifest, files = original_build(Path("ledger"))
        changed = copy.deepcopy(manifest); changed["rule_contract_sha256"] = "0" * 64
        with patch.object(r38.r37, "_build", return_value=(changed, files)), \
             self.assertRaisesRegex(ValueError, "upstream_contract_invalid"):
            r38._build(Path("ledger"))
        rows = self._rows(files["exclusions.csv"])
        row = next(x for x in rows if x["group_id"] == r38.GROUP_ID); row["reason_code"] = "airfare_raw_support_absent"
        changed_files = copy.deepcopy(files); changed_files["exclusions.csv"] = r38._csv(tuple(rows[0]), rows)
        with patch.object(r38.r37, "_build", return_value=(manifest, changed_files)), \
             self.assertRaisesRegex(ValueError, "selected_exclusion_semantic_invalid"):
            r38._build(Path("ledger"))
        rows = self._rows(files["exclusions.csv"]); row = next(x for x in rows if x["group_id"] == r38.GROUP_ID)
        row["current_source_locator_sha256"] = "0" * 64
        changed_files = copy.deepcopy(files); changed_files["exclusions.csv"] = r38._csv(tuple(rows[0]), rows)
        with patch.object(r38.r37, "_build", return_value=(manifest, changed_files)), \
             self.assertRaisesRegex(ValueError, "selected_exclusion_semantic_invalid"):
            r38._build(Path("ledger"))

    def test_booking_period_and_current_purchase_mutations_fail_closed(self):
        original_strict = r38.r36._strict_json; calls = 0
        def mutate_booking(raw, code):
            nonlocal calls; value = original_strict(raw, code); calls += 1
            if calls == 1:
                value = copy.deepcopy(value)
                for row in value.values(): row["period"] = "숙박_0701_0702"
            return value
        with patch.object(r38.r36, "_strict_json", side_effect=mutate_booking), \
             self.assertRaisesRegex(ValueError, "booking_period_outside_trip"):
            r38._build(Path("ledger"))

        original_context = r38.r36._context
        def mutate_context(*args, **kwargs):
            context = original_context(*args, **kwargs)
            next(x for x in context["events"] if x["direct_event_key"] in r38.EXPECTED_EVENTS)["transaction_type"] = "cancellation"
            return context
        with patch.object(r38.r36, "_context", side_effect=mutate_context), \
             self.assertRaisesRegex(ValueError, "foreign_purchase_invalid"):
            r38._build(Path("ledger"))
        with self.assertRaisesRegex(ValueError, "duplicate_key"):
            r38.r36._strict_json(b'{"x":1,"x":2}', "r38_booking_info")

    def test_trip_window_uses_inclusive_day_count_and_rejects_bad_types(self):
        start, end = r38._trip_bounds({"mm": 4, "dd": 4, "window": 7})
        self.assertEqual((end - start).days, 6)
        for window in (0, -1, True, False, "7", 7.0):
            with self.subTest(window=window), self.assertRaisesRegex(ValueError, "trip_window_invalid"):
                r38._trip_bounds({"mm": 4, "dd": 4, "window": window})

    def test_atomic_no_replace_cleanup_and_concurrent_single_winner(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname); target = root / "out"
            with patch.object(r38, "_build", return_value=(self.manifest, self.files)), \
                 patch.object(r38, "verify_structured_lodging_evidence", return_value={"status": "valid"}), \
                 patch.object(r38, "_install_noreplace", side_effect=OSError("injected")):
                with self.assertRaises(OSError): r38.build_structured_lodging_evidence(output=target)
            self.assertFalse(target.exists()); self.assertFalse(any(root.iterdir()))
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname) / "out"
            with patch.object(r38, "_build", return_value=(self.manifest, self.files)), \
                 patch.object(r38, "verify_structured_lodging_evidence", return_value={"status": "valid"}):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(r38.build_structured_lodging_evidence, output=target) for _ in range(2)]
                    outcomes = []
                    for future in futures:
                        try: future.result(); outcomes.append("ok")
                        except FileExistsError: outcomes.append("exists")
            self.assertEqual(sorted(outcomes), ["exists", "ok"])
            self.assertEqual({x.name for x in target.iterdir()}, set(r38.FILES))

    def test_post_publish_durability_and_reconcile_swap(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname); target = root / "out"; calls = 0
            def fsync(_path):
                nonlocal calls; calls += 1
                if calls == 2: raise OSError("parent")
            with patch.object(r38, "_build", return_value=(self.manifest, self.files)), \
                 patch.object(r38, "verify_structured_lodging_evidence", return_value={"status": "valid"}), \
                 patch.object(r38.r37, "_fsync_dir", side_effect=fsync), \
                 self.assertRaises(r38.PublicationDurabilityError) as caught:
                r38.build_structured_lodging_evidence(output=target)
            self.assertTrue(target.is_dir()); self.assertTrue(caught.exception.published)
            with patch.object(r38, "_build", return_value=(self.manifest, self.files)), \
                 patch.object(r38.r37, "_fsync_dir", return_value=None):
                result = r38.reconcile_publication_durability(caught.exception)
            self.assertTrue(result["parent_fsync"])

            competitor = root / "competitor"; competitor.mkdir(); (competitor / "x").write_text("competitor", encoding="utf-8")
            moved = root / "moved"
            def swap(_path): target.rename(moved); competitor.rename(target)
            with patch.object(r38, "_build", return_value=(self.manifest, self.files)), \
                 patch.object(r38.r37, "_fsync_dir", side_effect=swap), \
                 self.assertRaises((ValueError, OSError)):
                r38.reconcile_publication_durability(caught.exception)
            self.assertEqual((target / "x").read_text(encoding="utf-8"), "competitor")


if __name__ == "__main__": unittest.main()
