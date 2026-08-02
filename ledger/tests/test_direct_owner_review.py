from __future__ import annotations

import json
import tempfile
import unittest
import subprocess
import hashlib
import os
from unittest.mock import patch
from pathlib import Path

from ledger.domain.direct_owner_review import (
    build_owner_review,
    dry_run_owner_review,
    serialize_owner_review,
    validate_owner_review,
    write_owner_review,
    load_owner_review,
)


class DirectOwnerReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        from ledger.tests.test_transition_gates_v2 import DirectTransitionGateTest
        self._gate_fixture = DirectTransitionGateTest()
        self._gate_fixture.setUp()
        self.addCleanup(self._gate_fixture.temporary.cleanup)

    def _fixture(self):
        return self._gate_fixture._fixture()

    def _report(self, *args, **kwargs):
        return self._gate_fixture._report(*args, **kwargs)
    def test_template_is_deterministic_blank_and_not_authority(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        report = self._report(database, run_id, expected)
        from ledger.domain.transition_gates_v2 import gate_report_sha256
        report["run_id"] = run_id
        report["gate_report_sha256"] = gate_report_sha256(report)
        provenance = {"code_commit": "commit-a", "code_bundle_sha256": "a" * 64, "gate_report_sha256": "b" * 64}
        first = build_owner_review(db, run_id, report, provenance=provenance)
        second = build_owner_review(db, run_id, report, provenance=provenance)
        self.assertEqual(serialize_owner_review(first), serialize_owner_review(second))
        self.assertEqual(first["manifest"]["authority_ready_count"], 0)
        self.assertEqual(first["manifest"]["gate5_resolved_count"], 0)
        self.assertTrue(all(row[field] == "" for row in first["events"] for field in ("decision_status", "allocation_items_json", "classification_items_json", "evidence_refs_json", "owner_rationale")))
        db.close()

    def test_tamper_and_fake_owner_payload_remain_fail_closed(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        report = self._report(database, run_id, expected)
        package = build_owner_review(db, run_id, report, provenance={})
        current = {"context": package["context"], "events": package["events"]}
        fake = json.loads(json.dumps(package))
        fake["events"][0]["merchant"] = "invented"
        with self.assertRaisesRegex(ValueError, "immutable_field:merchant"):
            validate_owner_review(fake, current)
        fake = json.loads(json.dumps(package))
        fake["events"][0]["decision_status"] = "confirmed"
        fake["events"][0]["allocation_items_json"] = json.dumps([{"target_code": "X", "amount_krw": fake["events"][0]["amount_krw"]}])
        fake["events"][0]["classification_items_json"] = json.dumps([{"dimension": "d", "value": "v"}])
        fake["events"][0]["evidence_refs_json"] = json.dumps([])
        fake["events"][0]["owner_rationale"] = "exact"
        result = validate_owner_review(fake, current)
        self.assertEqual(result["authority_ready_count"], 0)
        self.assertEqual(result["gate5_resolved_count"], 0)
        db.close()

    def test_edit_contract_strictly_rejects_enum_json_duplicates_and_refs(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        package = build_owner_review(db, run_id, self._report(database, run_id, expected), provenance={})
        current = {"context": package["context"], "events": package["events"]}
        for field, value, reason in (
            ("decision_status", "confirmedx", "decision_status_invalid"),
            ("allocation_items_json", "{", "allocation_items_json_invalid"),
            ("classification_items_json", json.dumps([{ "dimension": "d", "value": "v" }, { "dimension": "d", "value": "w" }]), "classification_item_invalid"),
            ("evidence_refs_json", json.dumps([{ "source_key": "fake", "source_sha256": "0" * 64 }]), "evidence_ref_unresolved"),
        ):
            row = json.loads(json.dumps(package)); row["events"][0][field] = value
            row["events"][0]["decision_status"] = row["events"][0].get("decision_status", "confirmed") or "confirmed"
            row["events"][0]["allocation_items_json"] = row["events"][0].get("allocation_items_json") or json.dumps([{ "target_code": "X", "amount_krw": row["events"][0]["amount_krw"] }])
            row["events"][0]["classification_items_json"] = row["events"][0].get("classification_items_json") or json.dumps([{ "dimension": "d", "value": "v" }])
            row["events"][0]["evidence_refs_json"] = row["events"][0].get("evidence_refs_json") or "[]"
            row["events"][0]["owner_rationale"] = "r"
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, reason):
                    validate_owner_review(row, current)
        db.close()

    def test_external_writer_is_atomic_and_rejects_repo_or_existing(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        package = build_owner_review(db, run_id, self._report(database, run_id, expected), provenance={})
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname) / "review"
            result = write_owner_review(package, target, repository_root=Path("/repo"))
            self.assertEqual(set(Path(result["path"]).iterdir()), {target / "manifest.json", target / "events.csv"})
            with self.assertRaises(FileExistsError):
                write_owner_review(package, target, repository_root=Path("/repo"))
        db.close()

    def test_serialized_edits_are_preserved_and_loader_requires_authoritative_current(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        report = self._report(database, run_id, expected)
        package = build_owner_review(db, run_id, report, provenance={})
        row = package["events"][0]
        row["decision_status"] = "needs_review"
        row["allocation_items_json"] = json.dumps([{"target_code": "X", "amount_krw": row["amount_krw"]}])
        row["classification_items_json"] = json.dumps([])
        row["evidence_refs_json"] = json.dumps([])
        row["owner_rationale"] = "review"
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname) / "package"
            write_owner_review(package, target, repository_root=Path("/repo"))
            loaded = __import__("ledger.domain.direct_owner_review", fromlist=["_load_package"])._load_package(target / "manifest.json", target / "events.csv")
            self.assertEqual(loaded["events"][0]["owner_rationale"], "review")
            with self.assertRaisesRegex(ValueError, "owner_review_manifest_context_mismatch"):
                tampered = json.loads(json.dumps(loaded))
                tampered["manifest"]["source_context"]["candidate_semantic_sha256"] = "f" * 64
                validate_owner_review(tampered, {"context": package["context"], "events": package["events"]})
        db.close()

    def test_dry_run_is_structural_only_and_context_drift_is_reported_as_invalid(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        report = self._report(database, run_id, expected)
        result = dry_run_owner_review(db, run_id, report, provenance={})
        self.assertEqual(result["status"], "template_valid")
        self.assertEqual(result["gate5_resolved_count"], 0)
        changed = json.loads(json.dumps(result["package"]))
        changed["context"]["candidate_semantic_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "manifest_context_mismatch"):
            validate_owner_review(changed, {"context": result["package"]["context"], "events": result["package"]["events"]})
        db.close()

    def test_adversarial_whitespace_refs_unknown_and_null_escape(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        package = build_owner_review(db, run_id, self._report(database, run_id, expected), provenance={})
        current = {"context": package["context"], "events": package["events"], "provenance": {}}
        base = package["events"][0]
        for field, value, reason in (("target_code", " ", "allocation_item_invalid"), ("dimension", " ", "classification_item_invalid"), ("value", 3, "classification_item_invalid")):
            candidate = json.loads(json.dumps(package)); candidate["events"][0]["decision_status"] = "needs_review"
            candidate["events"][0]["allocation_items_json"] = json.dumps([{"target_code": value if field == "target_code" else "X", "amount_krw": base["amount_krw"]}])
            candidate["events"][0]["classification_items_json"] = json.dumps([{"dimension": value if field == "dimension" else "d", "value": value if field == "value" else "v"}])
            candidate["events"][0]["evidence_refs_json"] = "[]"; candidate["events"][0]["owner_rationale"] = "r"
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, reason): validate_owner_review(candidate, current)
        candidate = json.loads(json.dumps(package)); candidate["extra"] = "pointer"
        with self.assertRaisesRegex(ValueError, "package_schema"): validate_owner_review(candidate, current)
        db.close()

    def test_b7_input_inventory_tamper_and_exact_gate5_fields(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        report = self._report(database, run_id, expected)
        package = build_owner_review(db, run_id, report, provenance={})
        current = {"context": package["context"], "events": package["events"], "provenance": {}}
        for field in ("input_manifest_sha256", "candidate_semantic_sha256", "decision_scope_sha256", "current_event_set_sha256"):
            tampered = json.loads(json.dumps(package)); tampered["context"][field] = "f" * 64
            with self.subTest(field=field):
                with self.assertRaises(ValueError): validate_owner_review(tampered, current)
        gate = next(g for g in report["gates"] if g["name"] == "allocation_and_decision_completeness")
        for field in ("decision_scope_format", "decision_scope_sha256", "decision_scope_count", "decision_scope_unique_count", "decision_scope_invalid_count", "decision_scope_duplicate_count"):
            altered = json.loads(json.dumps(report)); actual = next(g for g in altered["gates"] if g["name"] == gate["name"])["actual"]
            actual.pop(field)
            with self.subTest(missing=field):
                with self.assertRaisesRegex(ValueError, "gate5_scope_fields_missing"): build_owner_review(db, run_id, altered, provenance={})
        db.close()

    def test_b1_db_inventory_row_tamper_is_not_self_authoritative(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        report = self._report(database, run_id, expected)
        from ledger.domain.transition_gates_v2 import gate_report_sha256
        report["run_id"] = run_id
        report["gate_report_sha256"] = gate_report_sha256(report)
        package = build_owner_review(db, run_id, report, provenance={})
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname) / "owner"
            write_owner_review(package, target, repository_root=Path("/repo"))
            db.execute("UPDATE direct_projection_inputs SET raw_sha256=? WHERE run_id=? AND source_kind=(SELECT source_kind FROM direct_projection_inputs WHERE run_id=? LIMIT 1)", ("f" * 64, run_id, run_id))
            db.commit()
            from ledger.domain.direct_owner_review import load_owner_review
            with self.assertRaisesRegex(ValueError, "inventory_hash_mismatch"):
                load_owner_review(target / "manifest.json", target / "events.csv", db=db, run_id=run_id, report=report, provenance={})
        db.close()

    def test_b8_provenance_inventory_unknown_and_source_record_refs(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        package = build_owner_review(db, run_id, self._report(database, run_id, expected), provenance={})
        current = {"context": package["context"], "events": package["events"], "provenance": {}, "source_inventory": [], "source_records": [{"source_kind": "manual", "source_key": "M:1", "source_sha256": "a" * 64}]}
        row = package["events"][0]; row["decision_status"] = "needs_review"; row["allocation_items_json"] = json.dumps([{ "target_code": "x", "amount_krw": row["amount_krw"] }]); row["classification_items_json"] = "[]"; row["evidence_refs_json"] = json.dumps([{ "source_kind": "manual", "source_key": "M:1", "source_sha256": "a" * 64 }]); row["owner_rationale"] = "r"
        result = validate_owner_review(package, current)
        self.assertEqual(result["authority_ready_count"], 0)
        duplicate = json.loads(json.dumps(package)); duplicate["events"][0]["evidence_refs_json"] = json.dumps([{ "source_kind": "manual", "source_key": "M:1", "source_sha256": "a" * 64 }] * 2)
        with self.assertRaisesRegex(ValueError, "evidence_ref_duplicate"): validate_owner_review(duplicate, current)
        unknown = json.loads(json.dumps(package)); unknown["provenance"]["pointer"] = "legacy"
        with self.assertRaisesRegex(ValueError, "manifest_provenance_mismatch"): validate_owner_review(unknown, current)
        db.close()

    def test_b9_signed_noninteger_duplicate_reorder_missing_immutable_and_fake_payload(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database); package = build_owner_review(db, run_id, self._report(database, run_id, expected), provenance={}); current = {"context": package["context"], "events": package["events"], "provenance": {}}
        base = package["events"][0]
        for items, reason in (([{"target_code": "x", "amount_krw": base["amount_krw"] + 1}], "allocation_sum_mismatch"), ([{"target_code": "x", "amount_krw": 1.5}], "allocation_item_invalid"), ([{"target_code": "x", "amount_krw": base["amount_krw"]}, {"target_code": "x", "amount_krw": 0}], "allocation_target_duplicate")):
            candidate = json.loads(json.dumps(package)); row = candidate["events"][0]; row.update(decision_status="confirmed", allocation_items_json=json.dumps(items), classification_items_json="[]", evidence_refs_json="[]", owner_rationale="r")
            with self.assertRaisesRegex(ValueError, reason): validate_owner_review(candidate, current)
        for field in ("merchant", "occurred_on", "approval_number", "amount_krw", "transaction_type", "source_sha256"):
            candidate = json.loads(json.dumps(package)); candidate["events"][0][field] = "tampered"
            with self.subTest(field=field):
                with self.assertRaises(ValueError): validate_owner_review(candidate, current)
        reordered = json.loads(json.dumps(package)); reordered["events"].reverse()
        if len(reordered["events"]) > 1:
            with self.assertRaisesRegex(ValueError, "event_order_invalid"): validate_owner_review(reordered, current)
        missing = json.loads(json.dumps(package)); missing["events"] = missing["events"][:-1]
        with self.assertRaisesRegex(ValueError, "event_rows_invalid"): validate_owner_review(missing, current)
        fake = json.loads(json.dumps(package)); fake["manifest"]["gate5_resolved_count"] = 1
        with self.assertRaisesRegex(ValueError, "authority_fields_invalid"): validate_owner_review(fake, current)
        db.close()

    def test_b7_public_rebuild_cli_rejects_noncanonical_and_leaves_temp_clean(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database); package = build_owner_review(db, run_id, self._report(database, run_id, expected), provenance={}); db.close()
        with tempfile.TemporaryDirectory() as dirname:
            base = Path(dirname); write_owner_review(package, base / "owner", repository_root=Path("/repo"))
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            isolated_tmp = base / "tmp"; isolated_tmp.mkdir()
            env = dict(os.environ, TMPDIR=str(isolated_tmp))
            proc = subprocess.run(["python3", "-m", "ledger.domain.direct_owner_review", "--rebuild-current", "--ledger-dir", str(Path("ledger").resolve()), "--manifest", str(base / "owner/manifest.json"), "--events", str(base / "owner/events.csv")], capture_output=True, text=True, env=env)
            self.assertIn(proc.returncode, (0, 2)); self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest()); self.assertEqual(list(isolated_tmp.iterdir()), [])
            bad = subprocess.run(["python3", "-m", "ledger.domain.direct_owner_review", "--rebuild-current", "--ledger-dir", str(base), "--manifest", str(base / "owner/manifest.json"), "--events", str(base / "owner/events.csv")], capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2); self.assertIn("noncanonical", bad.stdout)

    def test_b7_atomic_replace_failure_leaves_no_staging_and_existing_target(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database); package = build_owner_review(db, run_id, self._report(database, run_id, expected), provenance={}); db.close()
        with tempfile.TemporaryDirectory() as dirname:
            parent = Path(dirname); target = parent / "review"
            with patch("ledger.domain.direct_owner_review.os.replace", side_effect=OSError("injected")):
                with self.assertRaises(OSError): write_owner_review(package, target, repository_root=Path("/repo"))
            self.assertFalse(target.exists()); self.assertEqual(list(parent.iterdir()), [])
            target.mkdir(); (target / "keep").write_text("old")
            with self.assertRaises(FileExistsError): write_owner_review(package, target, repository_root=Path("/repo"))
            self.assertEqual((target / "keep").read_text(), "old")

    def test_b7_direct_db_load_is_read_only_authorized_and_file_stable(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database)
        report = self._report(database, run_id, expected)
        from ledger.domain.transition_gates_v2 import gate_report_sha256
        report["run_id"] = run_id
        report["gate_report_sha256"] = gate_report_sha256(report)
        inventory = [dict(zip(("source_kind", "relative_path", "raw_sha256", "lf_sha256", "byte_count", "key_set_sha256", "record_count", "parser_version"), row)) for row in db.execute("SELECT source_kind, relative_path, raw_sha256, lf_sha256, byte_count, key_set_sha256, record_count, parser_version FROM direct_projection_inputs WHERE run_id=?", (run_id,))]
        package = build_owner_review(db, run_id, report, provenance={"source_inventory": inventory})
        db.execute("UPDATE direct_projection_runs SET gate_report_sha256=? WHERE run_id=?", (report["gate_report_sha256"], run_id)); db.commit(); db.close()
        before = hashlib.sha256(database.read_bytes()).hexdigest(); writes = []
        def authorizer(action, *_args):
            import sqlite3
            if action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_DROP_TABLE}:
                writes.append(action)
            return sqlite3.SQLITE_OK
        from ledger.domain.direct_owner_review import load_owner_review
        check = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True); check.execute("PRAGMA query_only=ON"); check.set_authorizer(authorizer)
        current = load_owner_review
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname) / "owner"; write_owner_review(package, target, repository_root=Path("/repo"))
            result = current(target / "manifest.json", target / "events.csv", db=check, run_id=run_id, report=report, provenance={})
            self.assertEqual(result["status"], "template_valid")
        check.close()
        self.assertEqual(writes, []); self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())

    def test_v6_binding_boundaries(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database); report = self._report(database, run_id, expected); package = build_owner_review(db, run_id, report, provenance={}); current = {"context": package["context"], "events": package["events"], "provenance": package["provenance"], "source_records": []}
        for field in ("current_event_set_sha256", "current_decision_scope_sha256"):
            altered = json.loads(json.dumps(report)); gate = next(g for g in altered["gates"] if g["name"] == "semantic_regression"); gate["actual"].pop(field, None)
            with self.subTest(gate6_missing=field):
                with self.assertRaisesRegex(ValueError, "gate6_scope_mismatch"): build_owner_review(db, run_id, altered, provenance={})
        altered = json.loads(json.dumps(report)); gate = next(g for g in altered["gates"] if g["name"] == "semantic_regression"); gate["actual"]["current_event_set_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "gate6_scope_mismatch"): build_owner_review(db, run_id, altered, provenance={})
        for mutation in ("pointer", "annex", "source_inventory"):
            altered = json.loads(json.dumps(package)); altered["manifest"]["provenance"][mutation] = "x" if mutation != "source_inventory" else [{"tampered": True}]
            altered["provenance"] = dict(altered["manifest"]["provenance"])
            with self.subTest(provenance=mutation):
                with self.assertRaises(ValueError): validate_owner_review(altered, current)
        for value in (None, True, [], {}):
            altered = json.loads(json.dumps(package)); altered["events"][0]["decision_status"] = "needs_review"; altered["events"][0]["allocation_items_json"] = json.dumps([{ "target_code": "x", "amount_krw": altered["events"][0]["amount_krw"] }]); altered["events"][0]["classification_items_json"] = "[]"; altered["events"][0]["evidence_refs_json"] = json.dumps([value]); altered["events"][0]["owner_rationale"] = "r"
            with self.subTest(ref_type=type(value).__name__):
                with self.assertRaises(ValueError): validate_owner_review(altered, current)
        physical = json.loads(json.dumps(package)); physical["events"][0]["decision_status"] = "needs_review"; physical["events"][0]["allocation_items_json"] = json.dumps([{ "target_code": "x", "amount_krw": physical["events"][0]["amount_krw"] }]); physical["events"][0]["classification_items_json"] = "[]"; physical["events"][0]["evidence_refs_json"] = json.dumps([{ "source_kind": "card_raw", "source_key": "ledger/data/x", "source_sha256": "a" * 64 }]); physical["events"][0]["owner_rationale"] = "r"
        with self.assertRaisesRegex(ValueError, "evidence_ref_unresolved"): validate_owner_review(physical, current)
        db.close()

    def test_v6_verifier_lifecycle(self) -> None:
        from unittest.mock import patch
        database, run_id, expected, _ = self._fixture(); import sqlite3
        db = sqlite3.connect(database); package = build_owner_review(db, run_id, self._report(database, run_id, expected), provenance={}); db.close()
        with tempfile.TemporaryDirectory() as dirname:
            base = Path(dirname); target = base / "owner"
            with patch("ledger.domain.direct_owner_review.os.replace", side_effect=OSError("replace")):
                with self.assertRaises(OSError): write_owner_review(package, target, repository_root=Path("/repo"))
            self.assertFalse(target.exists())
            target.mkdir(); (target / "keep").write_text("keep")
            with self.assertRaises(FileExistsError): write_owner_review(package, target, repository_root=Path("/repo"))
            self.assertEqual((target / "keep").read_text(), "keep")
            with self.assertRaisesRegex(ValueError, "owner_review_output_artifact_overlap"):
                from ledger.domain.direct_projection import build_direct_candidate
                build_direct_candidate(base / "candidate.db", Path("ledger"), output_dir=base / "artifacts", owner_review_output=base / "artifacts" / "child")
        self.assertNotIn("owner_review", package["manifest"].get("approved_transitions", {}))

    def test_v6_real_invariants_and_tamper(self) -> None:
        import subprocess
        from ledger.domain.direct_projection import build_direct_candidate
        with tempfile.TemporaryDirectory(prefix="r22-v6-real-") as dirname:
            base = Path(dirname); result = build_direct_candidate(base / "candidate.db", Path("ledger"), output_dir=base / "artifacts", owner_review_output=base / "owner")
            self.assertFalse(result["passed"]); self.assertIsNone(result["output_db"])
            manifest = json.loads((base / "owner/manifest.json").read_text()); context = manifest["source_context"]
            new_manifest_sha = "182ead7e7f7014fe6edfc4e38d305f8e6b6ef1c5f9344135705551534e78fbc7"
            old_manifest_sha = "e355f146e426d9147b3387bd98802d83b8b70090d5e6327f92ff60f6825f0199"
            self.assertTrue(all(item["parser_version"] == "direct-source-v4" for item in manifest["provenance"]["source_inventory"]))
            self.assertNotEqual(new_manifest_sha, old_manifest_sha)
            self.assertEqual((context["input_manifest_sha256"], context["candidate_semantic_sha256"], context["current_event_set_sha256"], context["decision_scope_sha256"]), (new_manifest_sha, "e36eeb47cff6336c717bd3fe79dc61a5ee41500664919a76d434e2c3facf40ee", "de1660be34fa259e7e4a2fe88d5e45c478c7707637f61cf43c69c33af3abce93", "22459391ce7696e03c62eeaedf3d59b9faec5307baa62fcb578f55cc4b1a1418"))
            with (base / "owner/events.csv").open(encoding="utf-8") as stream:
                rows = list(__import__("csv").DictReader(stream))
            self.assertEqual(len(rows), 5328); self.assertTrue(all(row[field] in ('""', 'null') for row in rows for field in ("decision_status", "allocation_items_json", "classification_items_json", "evidence_refs_json", "owner_rationale")))
            for field in context:
                if field.endswith("sha256"):
                    altered = json.loads((base / "owner/manifest.json").read_text()); altered["source_context"][field] = "f" * 64; (base / "owner/manifest.json").write_text(json.dumps(altered))
                    proc = subprocess.run(["python3", "-m", "ledger.domain.direct_owner_review", "--rebuild-current", "--ledger-dir", str(Path("ledger").resolve()), "--manifest", str(base / "owner/manifest.json"), "--events", str(base / "owner/events.csv")], capture_output=True, text=True); self.assertEqual(proc.returncode, 2)
                    (base / "owner/manifest.json").write_text(json.dumps(manifest))

    def test_v6_manifest_run_binding_and_container_tamper_cli(self) -> None:
        database, run_id, expected, _ = self._fixture()
        import sqlite3
        db = sqlite3.connect(database); report = self._report(database, run_id, expected); package = build_owner_review(db, run_id, report, provenance={}); db.close()
        current = {"context": package["context"], "events": package["events"], "provenance": package["provenance"]}
        forged = json.loads(json.dumps(package)); forged["manifest"]["source_run_id"] = "forged"
        with self.assertRaisesRegex(ValueError, "source_run_binding_invalid"): validate_owner_review(forged, current)
        for value in ([], [{"x": 1}], "bad"):
            malformed = json.loads(json.dumps(package)); malformed["manifest"]["provenance"] = value; malformed["provenance"] = value
            with self.subTest(provenance_type=type(value).__name__):
                with self.assertRaises(ValueError): validate_owner_review(malformed, current)
        from ledger.domain.direct_owner_review import _load_package
        with tempfile.TemporaryDirectory() as dirname:
            base = Path(dirname); events = base / "events.csv"; manifest = base / "manifest.json"; write_owner_review(package, base / "owner", repository_root=Path("/repo")); events.write_bytes((base / "owner/events.csv").read_bytes())
            for root in ([], "bad", {"x": 1}):
                manifest.write_text(json.dumps(root))
                with self.subTest(manifest_type=type(root).__name__):
                    with self.assertRaises(ValueError): _load_package(manifest, events)
