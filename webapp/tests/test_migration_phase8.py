"""Phase 8 local synthetic import: seal, compare, decide, migrate, report.

Synthetic sources and a temporary migration DB only. There is no real Google
reference workbook, no production DB and no customer original in this file;
both sources are built here, sealed with the existing snapshot_descriptor and
then only read. `test_the_sources_are_never_written` checks the originals are
byte-identical afterwards.
"""

import copy
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from webapp import migration
from webapp.contracts import ContractError
from webapp.snapshot_descriptor import verify_snapshot

# The left source is the "google" side and the right one is the "db" side.
# entry ids differ between the sides on purpose: the join is by an explicit
# source identity, never by entry id.
LEFT = [
    # equal on both sides
    {"entry_id": "g1", "source_identity": "rsv-A1", "customer_name": "김민수",
     "occurred_on": "2026-04-01", "amount_krw": 120000, "sign": 1,
     "item": "숙박비", "reservation_no": "RSV-A1", "evidence_ref": "ev-1",
     "memo": "카드 내역", "memo_updated_at": "2026-04-02T00:00:00+00:00"},
    # amount differs
    {"entry_id": "g2", "source_identity": "rsv-A2", "customer_name": "이서연",
     "occurred_on": "2026-04-03", "amount_krw": 80000, "sign": 1,
     "item": "숙박비", "reservation_no": "RSV-A2", "evidence_ref": "ev-2",
     "memo": "환불 조정 전", "memo_updated_at": "2026-04-04T00:00:00+00:00"},
    # date differs
    {"entry_id": "g3", "source_identity": "rsv-A3", "customer_name": "박도윤",
     "occurred_on": "2026-04-05", "amount_krw": 45000, "sign": -1,
     "item": "식비", "reservation_no": "RSV-A3", "evidence_ref": "",
     "memo": "", "memo_updated_at": ""},
    # only on the left
    {"entry_id": "g4", "source_identity": "rsv-A4", "customer_name": "최유진",
     "occurred_on": "2026-04-07", "amount_krw": 30000, "sign": 1,
     "item": "교통비", "reservation_no": "RSV-A4", "evidence_ref": "ev-4",
     "memo": "현금 영수증", "memo_updated_at": "2026-04-08T00:00:00+00:00"},
    # no verified identity on the left, and d7 below looks the same but also
    # has none: they must not be merged
    {"entry_id": "g5", "source_identity": "", "customer_name": "정하늘",
     "occurred_on": "2026-04-09", "amount_krw": 60000, "sign": 1,
     "item": "숙박비", "reservation_no": "", "evidence_ref": "",
     "memo": "", "memo_updated_at": ""},
]

RIGHT = [
    {"entry_id": "d1", "source_identity": "rsv-A1", "customer_name": "김민수",
     "occurred_on": "2026-04-01", "amount_krw": 120000, "sign": 1,
     "item": "숙박비", "reservation_no": "RSV-A1", "evidence_ref": "ev-1",
     "memo": "카드 내역", "memo_updated_at": "2026-04-02T00:00:00+00:00"},
    # the same identity with a different amount
    {"entry_id": "d2", "source_identity": "rsv-A2", "customer_name": "이서연",
     "occurred_on": "2026-04-03", "amount_krw": 75000, "sign": 1,
     "item": "숙박비", "reservation_no": "RSV-A2", "evidence_ref": "ev-2",
     "memo": "환불 조정 후", "memo_updated_at": "2026-04-05T00:00:00+00:00"},
    # the same identity with a different date
    {"entry_id": "d3", "source_identity": "rsv-A3", "customer_name": "박도윤",
     "occurred_on": "2026-04-06", "amount_krw": 45000, "sign": -1,
     "item": "식비", "reservation_no": "RSV-A3", "evidence_ref": "",
     "memo": "", "memo_updated_at": ""},
    # only on the right, with a verified identity
    {"entry_id": "d6", "source_identity": "rsv-A6", "customer_name": "한지우",
     "occurred_on": "2026-04-10", "amount_krw": 25000, "sign": 1,
     "item": "숙박비", "reservation_no": "RSV-A6", "evidence_ref": "ev-6",
     "memo": "기존 장부", "memo_updated_at": "2026-04-11T00:00:00+00:00"},
    # looks exactly like g5 but has no verified identity either
    {"entry_id": "d7", "source_identity": "", "customer_name": "정하늘",
     "occurred_on": "2026-04-09", "amount_krw": 60000, "sign": 1,
     "item": "숙박비", "reservation_no": "", "evidence_ref": "",
     "memo": "", "memo_updated_at": ""},
]


class Phase8ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="phase8-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.left = migration.build_source_db(self.tmp / "google.sqlite",
                                              LEFT, side="google")
        self.right = migration.build_source_db(self.tmp / "db.sqlite",
                                               RIGHT, side="db")
        self.gate = self.tmp / "gate_report.json"
        self.gate.write_text(json.dumps({
            "run_id": "phase8-run-1",
            "candidate_semantic_sha256": "a" * 64,
        }, ensure_ascii=False), encoding="utf-8")
        self.work = self.tmp / "sealed"
        self.migration_db = self.tmp / "migration.sqlite"
        self.left_before = migration.sha256_file(self.left)
        self.right_before = migration.sha256_file(self.right)

    def tearDown(self):
        for path in (self.left, self.right):
            for suffix in ("-wal", "-shm", "-journal"):
                side = Path(str(path) + suffix)
                if side.exists():
                    side.unlink()

    def run_import(self, **kwargs):
        params = dict(left_db=self.left, right_db=self.right,
                      migration_db=self.migration_db, work_dir=self.work,
                      user_id="syn-owner-O", client_request_id="p8-1",
                      left_gate=self.gate, right_gate=self.gate)
        params.update(kwargs)
        return migration.run_import(**params)

    # ------------------------------------- 1. sealed sources, verified
    def test_both_sources_are_sealed_and_verified(self):
        result = self.run_import()
        sealed = result["sealed_sources"]
        self.assertTrue(sealed["google"]["verified"])
        self.assertTrue(sealed["db"]["verified"])
        for label in ("google", "db"):
            descriptor = json.loads(
                Path(sealed[label]["descriptor_path"]).read_text(encoding="utf-8"))
            self.assertTrue(verify_snapshot(sealed[label]["descriptor_path"])["ok"])
            self.assertEqual(descriptor["candidate_semantic_sha256"], "a" * 64)
            self.assertTrue(descriptor["candidate_db"]["sha256"])
            self.assertGreater(descriptor["candidate_db"]["size_bytes"], 0)
        # the hash recorded in the descriptor is the file's own hash
        self.assertEqual(sealed["google"]["sha256"],
                         migration.sha256_file(self.left))
        self.assertEqual(sealed["db"]["sha256"],
                         migration.sha256_file(self.right))

    def test_a_source_with_a_sidecar_is_refused_not_repaired(self):
        # an unsealed writer leaves a -wal next to the source
        stray = Path(str(self.left) + "-wal")
        stray.write_bytes(b"not a real wal")
        with self.assertRaises(ContractError):
            migration.seal_and_verify_sources(self.left, self.right, self.work,
                                              left_gate=self.gate,
                                              right_gate=self.gate)
        stray.unlink()

    def test_the_sources_are_never_written(self):
        self.run_import()
        self.assertEqual(migration.sha256_file(self.left), self.left_before)
        self.assertEqual(migration.sha256_file(self.right), self.right_before)
        # and the source is only ever opened read-only
        conn = migration.open_source_readonly(self.left)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM source_entries")
        finally:
            conn.close()
        self.assertEqual(migration.sha256_file(self.left), self.left_before)

    # --------------------------------- 2. explicit identity, no guessing
    def test_rows_are_joined_by_identity_and_never_by_looking_alike(self):
        summary = migration.compare_sources(
            migration.read_source_entries(self.left),
            migration.read_source_entries(self.right))
        # g5 and d7 have the same name, date and amount and no verified
        # identity, so they are an ambiguous pair and are not merged.
        self.assertEqual(summary["counts"]["ambiguous"], 1)
        ambiguous = summary["ambiguous"][0]
        self.assertIn("no verified source identity", ambiguous["reason"])
        self.assertEqual([r["entry_id"] for r in ambiguous["left"]], ["g5"])
        self.assertEqual([r["entry_id"] for r in ambiguous["right"]], ["d7"])
        # and they are held out of the one-sided lists, so the states stay
        # distinct and nothing is counted twice
        self.assertNotIn("g5", {g["entry_id"] for g in summary["google_only"]})
        self.assertNotIn("d7", {d["entry_id"] for d in summary["db_only"]})
        # the mismatch rows are joined by identity despite different entry ids
        joined = {m["entry_id"] for m in summary["mismatch"]}
        self.assertEqual(joined, {"g2", "g3"})
        # and the identity-based join reports the two sides' own entry ids
        by_id = {m["entry_id"]: m for m in summary["mismatch"]}
        self.assertEqual(by_id["g2"]["right_entry_id"], "d2")

    def test_two_rows_that_only_look_alike_stay_ambiguous(self):
        left = [{"entry_id": "x1", "source_identity": "",
                 "customer_name": "동명이인", "occurred_on": "2026-05-01",
                 "amount_krw": 10000, "sign": 1, "item": "", "reservation_no": ""}]
        right = [{"entry_id": "y1", "source_identity": "",
                  "customer_name": "동명이인", "occurred_on": "2026-05-01",
                  "amount_krw": 10000, "sign": 1, "item": "", "reservation_no": ""}]
        summary = migration.compare_sources(left, right)
        self.assertEqual(summary["counts"]["equal"], 0)
        self.assertEqual(summary["counts"]["mismatch"], 0)
        self.assertEqual(summary["counts"]["ambiguous"], 1)

    # ------------------------------------------- 3. the five comparison states
    def test_the_five_states_are_reported_separately(self):
        summary = migration.compare_sources(
            migration.read_source_entries(self.left),
            migration.read_source_entries(self.right))
        self.assertEqual(summary["counts"]["equal"], 1)
        self.assertEqual(summary["counts"]["mismatch"], 2)
        self.assertEqual(summary["counts"]["ambiguous"], 1)
        google_only = {g["entry_id"] for g in summary["google_only"]}
        db_only = {d["entry_id"] for d in summary["db_only"]}
        # a one-sided row with a verified identity is one-sided
        self.assertEqual(google_only, {"g4"})
        self.assertEqual(db_only, {"d6"})
        # the ambiguous pair is not folded into either one-sided list
        self.assertNotIn("g5", google_only)
        self.assertNotIn("d7", db_only)

    # --------------------------------------- 4. explicit per-field choice
    def test_a_mismatch_needs_an_explicit_field_choice_with_no_default(self):
        # no decisions at all: the mismatch rows stay unresolved
        result = self.run_import(client_request_id="p8-nodefault")
        undecided = result["unresolved"]["mismatch_undecided"]
        decided_fields = {u["entry_id"]: u["undecided_fields"] for u in undecided}
        self.assertEqual(decided_fields["g2"], ["amount_krw"])
        self.assertEqual(decided_fields["g3"], ["occurred_on"])
        self.assertGreater(result["unresolved"]["total"], 0)
        # nothing was written for the unresolved rows
        store = migration.MigrationStore(self.migration_db)
        try:
            rows = store.conn.execute(
                "SELECT COUNT(*) FROM migration_rows WHERE side='mismatch'"
            ).fetchone()[0]
        finally:
            store.close()
        self.assertEqual(rows, 0)

    def test_an_explicit_choice_migrates_the_row(self):
        result = self.run_import(
            client_request_id="p8-decided",
            decisions={"g2": {"amount_krw": "right"},
                       "g3": {"occurred_on": "left"}})
        self.assertEqual(result["unresolved"]["mismatch_undecided"], [])
        store = migration.MigrationStore(self.migration_db)
        try:
            row = store.conn.execute(
                "SELECT amount_krw FROM migration_rows WHERE side='mismatch'"
                " AND entry_id='g2'").fetchone()
            self.assertEqual(row[0], 75000)
            date_row = store.conn.execute(
                "SELECT occurred_on FROM migration_rows WHERE side='mismatch'"
                " AND entry_id='g3'").fetchone()
            self.assertEqual(date_row[0], "2026-04-05")
        finally:
            store.close()

    def test_an_unknown_field_or_side_is_refused(self):
        store = migration.MigrationStore(self.migration_db)
        left = migration.read_source_entries(self.left)
        right = migration.read_source_entries(self.right)
        summary = migration.compare_sources(left, right)
        store.record_comparison(comparison_id="cmp-x", left_rows=left,
                                right_rows=right, summary=summary)
        with self.assertRaises(migration.MigrationError):
            store.decide_field(comparison_id="cmp-x", entry_id="g2",
                               field="not_a_field", chosen_side="left",
                               user_id="syn-owner-O", left_rows=left,
                               right_rows=right)
        with self.assertRaises(migration.MigrationError):
            store.decide_field(comparison_id="cmp-x", entry_id="g2",
                               field="amount_krw", chosen_side="middle",
                               user_id="syn-owner-O", left_rows=left,
                               right_rows=right)
        store.close()

    # ------------------------- 5. amount and date disagreement is preserved
    def test_the_other_sides_value_is_preserved_next_to_the_display_choice(self):
        self.run_import(client_request_id="p8-prov",
                        decisions={"g2": {"amount_krw": "right"},
                                   "g3": {"occurred_on": "left"}})
        store = migration.MigrationStore(self.migration_db)
        comparison_id = store.conn.execute(
            "SELECT comparison_id FROM migration_rows LIMIT 1").fetchone()[0]
        provenance = store.provenance_rows(comparison_id)
        by_field = {p["field"]: p for p in provenance}
        # choosing the db amount did not erase the google amount
        self.assertEqual(by_field["amount_krw"]["left"], 80000)
        self.assertEqual(by_field["amount_krw"]["right"], 75000)
        # choosing the google date did not erase the db date
        self.assertEqual(by_field["occurred_on"]["left"], "2026-04-05")
        self.assertEqual(by_field["occurred_on"]["right"], "2026-04-06")
        store.close()

    # ------------------------------------- 6. decisions bound to both inputs
    def test_a_decision_is_bound_to_both_input_hashes(self):
        result = self.run_import(
            client_request_id="p8-bound",
            decisions={"g2": {"amount_krw": "right"},
                       "g3": {"occurred_on": "left"}})
        comparison_id = result["comparison_id"]
        store = migration.MigrationStore(self.migration_db)
        try:
            decision = store.decisions_for(comparison_id, "g2")["amount_krw"]
            self.assertEqual(decision["user_id"], "syn-owner-O")
            self.assertEqual(decision["chosen_side"], "right")
            self.assertEqual(decision["chosen_value"], 75000)
            hashes = store.input_hashes(comparison_id)
            self.assertEqual(decision["left_input_sha256"],
                             hashes["left_input_sha256"])
            self.assertEqual(decision["right_input_sha256"],
                             hashes["right_input_sha256"])
            self.assertTrue(decision["decided_at"])
        finally:
            store.close()

    def test_a_changed_input_makes_the_old_decision_unusable(self):
        first = self.run_import(
            client_request_id="p8-change-1",
            decisions={"g2": {"amount_krw": "right"},
                       "g3": {"occurred_on": "left"}})
        comparison_id = first["comparison_id"]
        left = migration.read_source_entries(self.left)
        right = migration.read_source_entries(self.right)
        # the left source changes after the decision was recorded
        changed = [dict(r) for r in left]
        for row in changed:
            if row["entry_id"] == "g1":
                row["amount_krw"] = 125000
        store = migration.MigrationStore(self.migration_db)
        try:
            with self.assertRaises(migration.MigrationError) as ctx:
                store.decide_field(comparison_id=comparison_id, entry_id="g2",
                                   field="amount_krw", chosen_side="left",
                                   user_id="syn-owner-O", left_rows=changed,
                                   right_rows=right)
            self.assertEqual(ctx.exception.code, "INPUT_CHANGED")
        finally:
            store.close()

    # --------------------------------------- 7. separate DB, idempotent apply
    def test_the_migration_writes_only_to_its_own_db(self):
        self.run_import(client_request_id="p8-only", decisions={
            "g2": {"amount_krw": "right"}, "g3": {"occurred_on": "left"}})
        self.assertTrue(self.migration_db.is_file())
        # the source files are untouched, and no migration table leaked into a
        # source
        self.assertEqual(migration.sha256_file(self.left), self.left_before)
        self.assertEqual(migration.sha256_file(self.right), self.right_before)
        for source in (self.left, self.right):
            conn = migration.open_source_readonly(source)
            try:
                names = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()
            self.assertNotIn("migration_rows", names)
            self.assertNotIn("migration_events", names)

    def test_applying_the_same_comparison_twice_has_no_second_effect(self):
        decisions = {"g2": {"amount_krw": "right"},
                     "g3": {"occurred_on": "left"}}
        first = self.run_import(client_request_id="p8-idem",
                                comparison_id="cmp-idem", decisions=decisions)
        store = migration.MigrationStore(self.migration_db)
        try:
            rows_after_first = store.conn.execute(
                "SELECT COUNT(*) FROM migration_rows").fetchone()[0]
            events_after_first = store.conn.execute(
                "SELECT COUNT(*) FROM migration_events").fetchone()[0]
        finally:
            store.close()
        # the same request id is a verified reuse
        again = self.run_import(client_request_id="p8-idem",
                                comparison_id="cmp-idem", decisions=decisions)
        self.assertTrue(again["reused"])
        # a different request id over the same inputs is also idempotent
        third = self.run_import(client_request_id="p8-idem-2",
                                comparison_id="cmp-idem", decisions=decisions)
        self.assertFalse(third["reused"])
        store = migration.MigrationStore(self.migration_db)
        try:
            self.assertEqual(store.conn.execute(
                "SELECT COUNT(*) FROM migration_rows").fetchone()[0],
                rows_after_first)
            self.assertEqual(store.conn.execute(
                "SELECT COUNT(*) FROM migration_events").fetchone()[0],
                events_after_first)
        finally:
            store.close()
        self.assertEqual(first["migrated_rows"], again["migrated_rows"])

    def test_the_same_request_id_with_different_inputs_is_refused(self):
        self.run_import(client_request_id="p8-conflict", decisions={
            "g2": {"amount_krw": "right"}, "g3": {"occurred_on": "left"}})
        changed_right = [dict(r) for r in RIGHT]
        for row in changed_right:
            if row["entry_id"] == "d1":
                row["amount_krw"] = 130000
        right_path = migration.build_source_db(
            self.tmp / "db2.sqlite", changed_right, side="db")
        with self.assertRaises(migration.MigrationError) as ctx:
            migration.run_import(
                left_db=self.left, right_db=right_path,
                migration_db=self.migration_db,
                work_dir=self.tmp / "sealed2", user_id="syn-owner-O",
                client_request_id="p8-conflict", left_gate=self.gate,
                right_gate=self.gate)
        self.assertEqual(ctx.exception.code, "REQUEST_ID_REUSED")

    # --------------------------------------------------- 8. the report
    def test_the_report_states_the_whole_state_not_just_totals(self):
        result = self.run_import(
            client_request_id="p8-report",
            decisions={"g2": {"amount_krw": "right"},
                       "g3": {"occurred_on": "left"}})
        # unresolved is stated, not folded into the counts
        self.assertEqual(result["counts"]["ambiguous"], 1)
        self.assertGreaterEqual(result["unresolved"]["total"], 1)
        self.assertEqual(result["unresolved"]["mismatch_undecided"], [])
        # migration events are counted
        self.assertGreater(result["migration_events"], 0)
        # signed totals keep the sign, not an absolute sum. The db-only row is
        # preserved too, so it is part of the total rather than dropped.
        totals = result["signed_totals"]
        self.assertEqual(totals["income_krw"],
                         120000 + 75000 + 30000 + 25000)
        self.assertEqual(totals["expense_krw"], -45000)
        self.assertEqual(totals["balance_krw"],
                         totals["income_krw"] + totals["expense_krw"])
        # the ambiguous pair contributed nothing, because it was not merged
        self.assertEqual(result["migrated_rows"], 5)
        # memo, evidence and provenance preservation is reported
        preservation = result["preservation"]
        self.assertTrue(preservation["memo_preserved"])
        self.assertTrue(preservation["evidence_preserved"])
        self.assertTrue(preservation["provenance_preserved"])
        self.assertGreater(preservation["provenance_records"], 0)
        # missing business fields are named
        self.assertIn("missing_business_fields", result)

    def test_memo_evidence_and_provenance_survive_the_move(self):
        self.run_import(client_request_id="p8-keep",
                        decisions={"g2": {"amount_krw": "right"},
                                   "g3": {"occurred_on": "left"}})
        store = migration.MigrationStore(self.migration_db)
        try:
            memo = store.conn.execute(
                "SELECT memo FROM migration_rows WHERE entry_id='g1'").fetchone()[0]
            self.assertEqual(memo, "카드 내역")
            evidence = store.conn.execute(
                "SELECT evidence_ref FROM migration_rows WHERE entry_id='g1'"
            ).fetchone()[0]
            self.assertEqual(evidence, "ev-1")
            # the db-only row keeps its own memo
            kept = store.conn.execute(
                "SELECT memo FROM migration_rows WHERE entry_id='d6'").fetchone()[0]
            self.assertEqual(kept, "기존 장부")
            # provenance is bound to both input hashes
            row = store.conn.execute(
                "SELECT left_input_sha256, right_input_sha256"
                " FROM migration_provenance LIMIT 1").fetchone()
            self.assertEqual(len(row[0]), 64)
            self.assertEqual(len(row[1]), 64)
        finally:
            store.close()

    def test_missing_business_fields_are_named_and_not_filled_in(self):
        # a source row with no item and no reservation number
        sparse_left = [{"entry_id": "s1", "source_identity": "rsv-S1",
                        "customer_name": "희망", "occurred_on": "2026-06-01",
                        "amount_krw": 1000, "sign": 1, "item": "",
                        "reservation_no": "", "evidence_ref": "",
                        "memo": "", "memo_updated_at": ""}]
        sparse_right = [{"entry_id": "t1", "source_identity": "rsv-S1",
                         "customer_name": "희망", "occurred_on": "2026-06-01",
                         "amount_krw": 1000, "sign": 1, "item": "",
                         "reservation_no": "", "evidence_ref": "",
                         "memo": "", "memo_updated_at": ""}]
        left_db = migration.build_source_db(self.tmp / "sp_left.sqlite",
                                            sparse_left, side="google")
        right_db = migration.build_source_db(self.tmp / "sp_right.sqlite",
                                             sparse_right, side="db")
        result = migration.run_import(
            left_db=left_db, right_db=right_db,
            migration_db=self.tmp / "sparse_migration.sqlite",
            work_dir=self.tmp / "sealed_sparse", user_id="syn-owner-O",
            client_request_id="p8-sparse", left_gate=self.gate,
            right_gate=self.gate)
        missing = result["missing_business_fields"]
        self.assertIn("item", missing)
        self.assertIn("reservation_no", missing)
        # nothing was invented to fill the gap
        store = migration.MigrationStore(self.tmp / "sparse_migration.sqlite")
        try:
            row = store.conn.execute(
                "SELECT item, reservation_no FROM migration_rows").fetchone()
            self.assertEqual(row[0], "")
            self.assertEqual(row[1], "")
        finally:
            store.close()


class ReviewedImportPlanTests(unittest.TestCase):
    """Sol-approved Phase B: deterministic read-only eligible-import plan.

    Synthetic dict fixtures only. No workbook, CSV, customer data, DB or
    external service is touched here except the no-side-effects check, which
    reuses the synthetic importer temporary DBs from this file.
    """

    SNAP = "a" * 64
    OTHER_SNAP = "b" * 64

    def row(self, ref, keys, *, disposition="matched", approved=True,
            chosen=None, note="", binding=None, count="auto"):
        if isinstance(keys, (list, tuple)):
            candidates = list(keys)
        else:
            candidates = keys
        payload = {
            "source_ref_snapshot_only": ref,
            "candidate_transaction_keys": candidates,
            "disposition": disposition,
            "approved": approved,
            "chosen_candidate_key": chosen,
            "review_note": note,
            "review_snapshot_sha256": self.SNAP if binding is None else binding,
        }
        if count == "auto":
            if isinstance(candidates, list):
                payload["candidate_count"] = len(candidates)
        elif count != "omit":
            payload["candidate_count"] = count
        return payload

    def test_empty_decisions_zero_eligible(self):
        plan = migration.build_reviewed_import_plan(self.SNAP, [])
        self.assertEqual(plan["counts"], {"eligible": 0, "refused": 0, "total": 0})
        self.assertEqual(plan["eligible"], [])
        self.assertEqual(plan["refused"], [])
        self.assertEqual(plan["snapshot_sha256"], self.SNAP)
        self.assertTrue(plan["plan_digest"])

    def test_single_candidate_unapproved_refused(self):
        plan = migration.build_reviewed_import_plan(
            self.SNAP, [self.row("ref-001", ["tx-1"], approved=False,
                                 chosen="tx-1", note="n1")])
        self.assertEqual(plan["counts"]["eligible"], 0)
        self.assertEqual(plan["refused"][0]["reason_code"], "NOT_APPROVED")
        self.assertEqual(plan["refused"][0]["review_note"], "n1")

    def test_single_candidate_explicit_approval_eligible(self):
        plan = migration.build_reviewed_import_plan(
            self.SNAP, [self.row("ref-001", ["tx-1"], approved=True,
                                 chosen="tx-1", note="ok")])
        self.assertEqual(plan["counts"]["eligible"], 1)
        item = plan["eligible"][0]
        self.assertEqual(item["source_ref_snapshot_only"], "ref-001")
        self.assertEqual(item["chosen_candidate_key"], "tx-1")
        self.assertEqual(item["review_note"], "ok")
        self.assertTrue(item["plan_id"].startswith("rip-"))

    def test_single_candidate_missing_or_wrong_selection_refused(self):
        missing = self.row("ref-001", ["tx-1"], approved=True,
                           chosen="", note="m")
        wrong = self.row("ref-002", ["tx-1"], approved=True,
                         chosen="tx-9", note="w")
        none_row = dict(self.row("ref-003", ["tx-1"], approved=True,
                                 note="n"))
        none_row["chosen_candidate_key"] = None
        plan = migration.build_reviewed_import_plan(
            self.SNAP, [missing, wrong, none_row])
        self.assertEqual(plan["counts"]["eligible"], 0)
        by_ref = {r["source_ref_snapshot_only"]: r for r in plan["refused"]}
        self.assertEqual(by_ref["ref-001"]["reason_code"], "MISSING_SELECTED_KEY")
        self.assertEqual(by_ref["ref-002"]["reason_code"],
                         "SELECTION_NOT_IN_CANDIDATES")
        self.assertEqual(by_ref["ref-003"]["reason_code"],
                         "INVALID_SELECTED_KEY_TYPE")
        # the selection is never inferred from the single candidate
        self.assertEqual(by_ref["ref-001"]["review_note"], "m")

    def test_multi_blank_hold_reject_refused(self):
        rows = [
            self.row("ref-001", ["tx-1", "tx-2"], approved=False, chosen="tx-1"),
            self.row("ref-002", ["tx-1", "tx-2"], approved=False,
                     chosen="tx-1"),
            self.row("ref-003", ["tx-1", "tx-2"], approved=False,
                     chosen="tx-2"),
            self.row("ref-004", ["tx-1", "tx-2"], approved="Approve",
                     chosen="tx-1"),
        ]
        plan = migration.build_reviewed_import_plan(self.SNAP, rows)
        self.assertEqual(plan["counts"]["eligible"], 0)
        self.assertEqual(plan["counts"]["refused"], 4)
        for entry in plan["refused"]:
            self.assertEqual(entry["reason_code"], "NOT_APPROVED")

    def test_multi_approval_with_one_valid_selected_key_eligible(self):
        plan = migration.build_reviewed_import_plan(
            self.SNAP, [self.row("ref-001", ["tx-1", "tx-2"],
                                 approved=True, chosen="tx-2",
                                 note="keep")])
        self.assertEqual(plan["counts"]["eligible"], 1)
        self.assertEqual(plan["eligible"][0]["chosen_candidate_key"], "tx-2")
        self.assertEqual(plan["eligible"][0]["review_note"], "keep")

    def test_multi_invalid_ambiguous_selection_refused(self):
        rows = [
            self.row("ref-001", ["tx-1", "tx-2"], approved=True,
                     chosen=""),
            self.row("ref-002", ["tx-1", "tx-2"], approved=True,
                     chosen="tx-9"),
            self.row("ref-003", ["tx-1", "tx-2"], approved=True,
                     chosen="tx-1,tx-2"),
            # strict exact match: padded whitespace is not the candidate
            self.row("ref-004", ["tx-1", "tx-2"], approved=True,
                     chosen=" tx-1 "),
        ]
        plan = migration.build_reviewed_import_plan(self.SNAP, rows)
        by_ref = {r["source_ref_snapshot_only"]: r for r in plan["refused"]}
        self.assertEqual(plan["counts"]["eligible"], 0)
        self.assertEqual(by_ref["ref-001"]["reason_code"], "MISSING_SELECTED_KEY")
        self.assertEqual(by_ref["ref-002"]["reason_code"],
                         "SELECTION_NOT_IN_CANDIDATES")
        self.assertEqual(by_ref["ref-003"]["reason_code"],
                         "SELECTION_NOT_IN_CANDIDATES")
        self.assertEqual(by_ref["ref-004"]["reason_code"],
                         "SELECTION_NOT_IN_CANDIDATES")

    def test_unmatched_approval_refused(self):
        plan = migration.build_reviewed_import_plan(
            self.SNAP, [self.row("ref-001", ["tx-1"], disposition="unmatched",
                                 approved=True, chosen="tx-1")])
        self.assertEqual(plan["counts"]["eligible"], 0)
        self.assertEqual(plan["refused"][0]["reason_code"],
                         "UNMATCHED_DISPOSITION")

    def test_zero_candidates_and_inconsistent_count_refused(self):
        zero = self.row("ref-001", [], approved=True, chosen="tx-1")
        inconsistent = self.row("ref-002", ["tx-1", "tx-2"], approved=True,
                                chosen="tx-1", count=1)
        plan = migration.build_reviewed_import_plan(self.SNAP, [zero, inconsistent])
        by_ref = {r["source_ref_snapshot_only"]: r for r in plan["refused"]}
        self.assertEqual(by_ref["ref-001"]["reason_code"], "ZERO_CANDIDATES")
        self.assertEqual(by_ref["ref-002"]["reason_code"],
                         "INCONSISTENT_CANDIDATES")

    def test_missing_ref_hash_target_binding_refused(self):
        no_ref = self.row("", ["tx-1"], approved=True, chosen="tx-1")
        no_binding = self.row("ref-002", ["tx-1"], approved=True,
                              chosen="tx-1", binding="")
        bad_binding = self.row("ref-003", ["tx-1"], approved=True,
                               chosen="tx-1", binding="c" * 64)
        no_target = self.row("ref-004", ["tx-1"], approved=True,
                             chosen="")
        plan = migration.build_reviewed_import_plan(
            self.SNAP, [no_ref, no_binding, bad_binding, no_target])
        by_ref = {r["source_ref_snapshot_only"]: r for r in plan["refused"]}
        self.assertEqual(by_ref[""]["reason_code"], "MISSING_REF")
        self.assertEqual(by_ref["ref-002"]["reason_code"], "MISSING_BINDING")
        self.assertEqual(by_ref["ref-003"]["reason_code"], "BINDING_MISMATCH")
        self.assertEqual(by_ref["ref-004"]["reason_code"], "MISSING_SELECTED_KEY")
        # missing current snapshot hash fails closed for every row
        empty_snap = migration.build_reviewed_import_plan(
            "", [self.row("ref-009", ["tx-1"], approved=True,
                          chosen="tx-1")])
        self.assertEqual(empty_snap["counts"]["eligible"], 0)
        self.assertEqual(empty_snap["refused"][0]["reason_code"],
                         "MISSING_SNAPSHOT_HASH")

    def test_duplicate_refs_refused(self):
        rows = [
            self.row("ref-dup", ["tx-1"], approved=True, chosen="tx-1"),
            self.row("ref-dup", ["tx-1"], approved=True, chosen="tx-1"),
            self.row("ref-ok", ["tx-1"], approved=True, chosen="tx-1"),
        ]
        plan = migration.build_reviewed_import_plan(self.SNAP, rows)
        self.assertEqual(plan["counts"]["eligible"], 1)
        self.assertEqual(plan["eligible"][0]["source_ref_snapshot_only"], "ref-ok")
        dups = [r for r in plan["refused"]
                if r["source_ref_snapshot_only"] == "ref-dup"]
        self.assertEqual(len(dups), 2)
        for entry in dups:
            self.assertEqual(entry["reason_code"], "DUPLICATE_REF")

    def test_changed_snapshot_hash_does_not_reuse_an_approval(self):
        rows = [self.row("ref-001", ["tx-1"], approved=True,
                         chosen="tx-1")]
        first = migration.build_reviewed_import_plan(self.SNAP, rows)
        self.assertEqual(first["counts"]["eligible"], 1)
        # same rows under a new snapshot hash: the old binding no longer matches
        second = migration.build_reviewed_import_plan(self.OTHER_SNAP, rows)
        self.assertEqual(second["counts"]["eligible"], 0)
        self.assertEqual(second["refused"][0]["reason_code"], "BINDING_MISMATCH")

    def test_deterministic_repeated_plan_and_ordering(self):
        rows = [
            self.row("ref-b", ["tx-2"], approved=True, chosen="tx-2"),
            self.row("ref-a", ["tx-1"], approved=True, chosen="tx-1"),
            self.row("ref-c", ["tx-3", "tx-4"], approved=True,
                     chosen="tx-4", note="z"),
        ]
        first = migration.build_reviewed_import_plan(self.SNAP, rows)
        second = migration.build_reviewed_import_plan(self.SNAP, list(rows))
        self.assertEqual(first, second)
        self.assertEqual([e["source_ref_snapshot_only"] for e in first["eligible"]],
                         ["ref-a", "ref-b", "ref-c"])
        self.assertEqual(first["plan_digest"], second["plan_digest"])
        ids_first = [e["plan_id"] for e in first["eligible"]]
        self.assertEqual(len(set(ids_first)), 3)
        # reversed input still yields the same deterministic order/ids/digest
        reversed_plan = migration.build_reviewed_import_plan(
            self.SNAP, list(reversed(rows)))
        self.assertEqual(reversed_plan["eligible"], first["eligible"])
        self.assertEqual(reversed_plan["plan_digest"], first["plan_digest"])

    def test_plan_generation_makes_no_db_changes(self):
        tmp = Path(tempfile.mkdtemp(prefix="phase8-plan-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        left = migration.build_source_db(tmp / "google.sqlite", LEFT,
                                         side="google")
        right = migration.build_source_db(tmp / "db.sqlite", RIGHT, side="db")
        gate = tmp / "gate_report.json"
        gate.write_text(json.dumps({
            "run_id": "phase8-plan-run",
            "candidate_semantic_sha256": "a" * 64,
        }, ensure_ascii=False), encoding="utf-8")
        migration_db = tmp / "migration.sqlite"
        migration.run_import(
            left_db=left, right_db=right, migration_db=migration_db,
            work_dir=tmp / "sealed", user_id="syn-owner-O",
            client_request_id="p8-plan-noop", left_gate=gate, right_gate=gate,
            decisions={"g2": {"amount_krw": "right"},
                       "g3": {"occurred_on": "left"}})
        store = migration.MigrationStore(migration_db)
        try:
            before_rows = store.conn.execute(
                "SELECT COUNT(*) FROM migration_rows").fetchone()[0]
            before_events = store.conn.execute(
                "SELECT COUNT(*) FROM migration_events").fetchone()[0]
            before_requests = store.conn.execute(
                "SELECT COUNT(*) FROM migration_requests").fetchone()[0]
        finally:
            store.close()
        digest_before = migration.sha256_file(migration_db)
        rows = [self.row("ref-001", ["tx-1"], approved=True,
                         chosen="tx-1")]
        for _ in range(2):
            plan = migration.build_reviewed_import_plan(self.SNAP, rows)
            self.assertEqual(plan["counts"]["eligible"], 1)
        self.assertEqual(migration.sha256_file(migration_db), digest_before)
        store = migration.MigrationStore(migration_db)
        try:
            self.assertEqual(store.conn.execute(
                "SELECT COUNT(*) FROM migration_rows").fetchone()[0],
                before_rows)
            self.assertEqual(store.conn.execute(
                "SELECT COUNT(*) FROM migration_events").fetchone()[0],
                before_events)
            self.assertEqual(store.conn.execute(
                "SELECT COUNT(*) FROM migration_requests").fetchone()[0],
                before_requests)
        finally:
            store.close()


    def test_raw_manifest_dispositions_refused_and_normalized_succeeds(self):
        raw = [
            self.row("ref-raw-1", ["tx-1"],
                     disposition="candidate_review_required",
                     approved=True, chosen="tx-1"),
            self.row("ref-raw-2", ["tx-1"],
                     disposition="unmatched_review_required",
                     approved=True, chosen="tx-1"),
        ]
        refused_plan = migration.build_reviewed_import_plan(self.SNAP, raw)
        self.assertEqual(refused_plan["counts"]["eligible"], 0)
        for entry in refused_plan["refused"]:
            self.assertEqual(entry["reason_code"], "UNMATCHED_DISPOSITION")
        # the same rows, validly normalized after human approval, succeed
        normalized = [
            self.row("ref-raw-1", ["tx-1"], disposition="matched",
                     approved=True, chosen="tx-1", note="human ok"),
            self.row("ref-raw-2", ["tx-1"], disposition="matched",
                     approved=True, chosen="tx-1"),
        ]
        plan = migration.build_reviewed_import_plan(self.SNAP, normalized)
        self.assertEqual(plan["counts"]["eligible"], 2)
        self.assertEqual(plan["eligible"][0]["review_note"], "human ok")

    def test_blank_approval_zero_eligible(self):
        rows = [
            self.row("ref-001", ["tx-1"], disposition="matched",
                     approved=False, chosen="tx-1"),
            self.row("ref-002", ["tx-1", "tx-2"], disposition="matched",
                     approved=False, chosen="tx-2"),
        ]
        plan = migration.build_reviewed_import_plan(self.SNAP, rows)
        self.assertEqual(plan["counts"]["eligible"], 0)
        for entry in plan["refused"]:
            self.assertEqual(entry["reason_code"], "NOT_APPROVED")
        missing = dict(self.row("ref-003", ["tx-1"], disposition="matched",
                                chosen="tx-1"))
        del missing["approved"]
        plan2 = migration.build_reviewed_import_plan(self.SNAP, [missing])
        self.assertEqual(plan2["counts"]["eligible"], 0)
        self.assertEqual(plan2["refused"][0]["reason_code"], "NOT_APPROVED")

    def test_candidate_set_change_changes_digest(self):
        base = [self.row("ref-001", ["tx-1", "tx-2"], disposition="matched",
                         approved=True, chosen="tx-1")]
        changed = [self.row("ref-001", ["tx-1", "tx-3"], disposition="matched",
                            approved=True, chosen="tx-1")]
        plan_base = migration.build_reviewed_import_plan(self.SNAP, base)
        plan_changed = migration.build_reviewed_import_plan(self.SNAP, changed)
        self.assertEqual(plan_base["counts"]["eligible"], 1)
        self.assertEqual(plan_changed["counts"]["eligible"], 1)
        self.assertNotEqual(plan_base["plan_digest"], plan_changed["plan_digest"])
        # candidate order is not meaningful: reordered keys, same digest
        reordered = [self.row("ref-001", ["tx-2", "tx-1"], disposition="matched",
                              approved=True, chosen="tx-1")]
        plan_reordered = migration.build_reviewed_import_plan(
            self.SNAP, reordered)
        self.assertEqual(plan_reordered["eligible"], plan_base["eligible"])
        self.assertEqual(plan_reordered["plan_digest"], plan_base["plan_digest"])
        self.assertEqual(plan_base["eligible"][0]["candidate_transaction_keys"],
                         ["tx-1", "tx-2"])
        # a tuple reaches the implementation as a tuple (the row helper's
        # list conversion is bypassed) yet yields the same plan and digest
        tuple_row = self.row("ref-001", ["tx-1", "tx-2"],
                             disposition="matched", approved=True,
                             chosen="tx-1")
        tuple_row["candidate_transaction_keys"] = ("tx-2", "tx-1")
        plan_tuple = migration.build_reviewed_import_plan(
            self.SNAP, [tuple_row])
        self.assertEqual(plan_tuple["eligible"], plan_base["eligible"])
        self.assertEqual(plan_tuple["plan_digest"], plan_base["plan_digest"])

    def test_different_string_containers_share_refusal_digest(self):
        # a raw string container is an invalid container: only its stable
        # kind marker feeds the digest, never its raw value
        first = [self.row("ref-001", "tx-1", disposition="matched",
                          approved=True, chosen="tx-1", count="omit")]
        second = [self.row("ref-001", "zz-9", disposition="matched",
                           approved=True, chosen="tx-1", count="omit")]
        plan_first = migration.build_reviewed_import_plan(self.SNAP, first)
        plan_second = migration.build_reviewed_import_plan(self.SNAP, second)
        self.assertEqual(plan_first["refused"][0]["reason_code"],
                         "INCONSISTENT_CANDIDATES")
        self.assertEqual(plan_second["refused"][0]["reason_code"],
                         "INCONSISTENT_CANDIDATES")
        self.assertEqual(plan_first["plan_digest"], plan_second["plan_digest"])

    def test_changed_valid_snapshot_matching_binding_changes_digest(self):
        rows = [self.row("ref-001", ["tx-1"], disposition="matched",
                         approved=True, chosen="tx-1")]
        first = migration.build_reviewed_import_plan(self.SNAP, rows)
        other_rows = [self.row("ref-001", ["tx-1"], disposition="matched",
                               approved=True, chosen="tx-1",
                               binding=self.OTHER_SNAP)]
        second = migration.build_reviewed_import_plan(self.OTHER_SNAP,
                                                      other_rows)
        self.assertEqual(first["counts"]["eligible"], 1)
        self.assertEqual(second["counts"]["eligible"], 1)
        self.assertNotEqual(first["plan_digest"], second["plan_digest"])
        self.assertNotEqual(first["eligible"][0]["plan_id"],
                            second["eligible"][0]["plan_id"])
        # mismatched binding under the new snapshot stays refused
        stale = migration.build_reviewed_import_plan(self.OTHER_SNAP, rows)
        self.assertEqual(stale["counts"]["eligible"], 0)
        self.assertEqual(stale["refused"][0]["reason_code"], "BINDING_MISMATCH")

    def test_strict_typing_rejected(self):
        rows = [
            # non-string ref
            self.row(123, ["tx-1"], approved=True, chosen="tx-1"),
            # non-string chosen key
            self.row("ref-int-chosen", ["tx-1"], approved=True, chosen=7),
            # non-string binding
            self.row("ref-int-binding", ["tx-1"], approved=True,
                     chosen="tx-1", binding=12345),
            # candidate list itself is a string
            self.row("ref-str-list", "tx-1", approved=True, chosen="tx-1",
                     count="omit"),
            # non-string candidate entry
            self.row("ref-int-entry", ["tx-1", 5], approved=True,
                     chosen="tx-1", count="omit"),
            # duplicate candidate entries
            self.row("ref-dup-entry", ["tx-1", "tx-1"], approved=True,
                     chosen="tx-1", count="omit"),
            # candidate_count float / bool / string / negative
            self.row("ref-float-count", ["tx-1"], approved=True,
                     chosen="tx-1", count=1.0),
            self.row("ref-bool-count", ["tx-1"], approved=True,
                     chosen="tx-1", count=True),
            self.row("ref-str-count", ["tx-1"], approved=True,
                     chosen="tx-1", count="1"),
            self.row("ref-neg-count", ["tx-1"], approved=True,
                     chosen="tx-1", count=-1),
            # approved truthy non-bool values
            self.row("ref-int-approved", ["tx-1"], approved=1, chosen="tx-1"),
            self.row("ref-str-approved", ["tx-1"], approved="approve",
                     chosen="tx-1"),
        ]
        plan = migration.build_reviewed_import_plan(self.SNAP, rows)
        self.assertEqual(plan["counts"]["eligible"], 0)
        self.assertEqual(plan["counts"]["refused"], len(rows))
        by_ref = {r["source_ref_snapshot_only"]: r for r in plan["refused"]}
        self.assertEqual(by_ref[""]["reason_code"], "INVALID_REF_TYPE")
        self.assertEqual(by_ref["ref-int-chosen"]["reason_code"],
                         "INVALID_SELECTED_KEY_TYPE")
        self.assertEqual(by_ref["ref-int-binding"]["reason_code"],
                         "INVALID_BINDING_TYPE")
        for ref in ("ref-str-list", "ref-int-entry", "ref-dup-entry",
                    "ref-float-count", "ref-bool-count", "ref-str-count",
                    "ref-neg-count"):
            self.assertEqual(by_ref[ref]["reason_code"],
                             "INCONSISTENT_CANDIDATES", ref)
        for ref in ("ref-int-approved", "ref-str-approved"):
            self.assertEqual(by_ref[ref]["reason_code"], "NOT_APPROVED", ref)
        # non-string current snapshot hash fails every row closed
        bad_snap = migration.build_reviewed_import_plan(
            12345, [self.row("ref-001", ["tx-1"], approved=True,
                             chosen="tx-1")])
        self.assertEqual(bad_snap["counts"]["eligible"], 0)
        self.assertEqual(bad_snap["refused"][0]["reason_code"],
                         "INVALID_SNAPSHOT_HASH_TYPE")

    def test_delimiter_collision_tuples_produce_distinct_plan_ids(self):
        left = [self.row("a|b", ["c"], disposition="matched",
                         approved=True, chosen="c")]
        right = [self.row("a", ["b|c"], disposition="matched",
                          approved=True, chosen="b|c")]
        plan_left = migration.build_reviewed_import_plan(self.SNAP, left)
        plan_right = migration.build_reviewed_import_plan(self.SNAP, right)
        self.assertEqual(plan_left["counts"]["eligible"], 1)
        self.assertEqual(plan_right["counts"]["eligible"], 1)
        # old delimiter-joined text would hash the same string for both
        legacy_left = f"{self.SNAP}|a|b|c"
        legacy_right = f"{self.SNAP}|a|b|c"
        self.assertEqual(legacy_left, legacy_right)
        self.assertNotEqual(plan_left["eligible"][0]["plan_id"],
                            plan_right["eligible"][0]["plan_id"])


    def test_whitespace_only_ref_rejected(self):
        plan = migration.build_reviewed_import_plan(
            self.SNAP, [self.row("   ", ["tx-1"], disposition="matched",
                                 approved=True, chosen="tx-1")])
        self.assertEqual(plan["counts"]["eligible"], 0)
        self.assertEqual(plan["refused"][0]["reason_code"], "MISSING_REF")

    def test_whitespace_only_chosen_key_rejected(self):
        plan = migration.build_reviewed_import_plan(
            self.SNAP, [self.row("ref-001", ["tx-1"], disposition="matched",
                                 approved=True, chosen="  \t ")])
        self.assertEqual(plan["counts"]["eligible"], 0)
        self.assertEqual(plan["refused"][0]["reason_code"],
                         "MISSING_SELECTED_KEY")

    def test_whitespace_only_candidate_entry_rejected(self):
        plan = migration.build_reviewed_import_plan(
            self.SNAP, [self.row("ref-001", ["tx-1", "   "],
                                 disposition="matched", approved=True,
                                 chosen="tx-1", count="omit")])
        self.assertEqual(plan["counts"]["eligible"], 0)
        self.assertEqual(plan["refused"][0]["reason_code"],
                         "INCONSISTENT_CANDIDATES")

    def test_whitespace_only_snapshot_and_binding_refused(self):
        # a whitespace-only snapshot is blank like a whitespace-only ref:
        # no eligible plan is built from it, whatever the binding says
        blank_snap = migration.build_reviewed_import_plan(
            "   ", [self.row("ref-001", ["tx-1"], disposition="matched",
                             approved=True, chosen="tx-1", binding="   ")])
        self.assertEqual(blank_snap["counts"]["eligible"], 0)
        self.assertEqual(blank_snap["refused"][0]["reason_code"],
                         "MISSING_SNAPSHOT_HASH")
        # a whitespace-only binding is blank too, not a mismatched binding
        blank_binding = migration.build_reviewed_import_plan(
            self.SNAP, [self.row("ref-001", ["tx-1"], disposition="matched",
                                 approved=True, chosen="tx-1",
                                 binding="  \t ")])
        self.assertEqual(blank_binding["counts"]["eligible"], 0)
        self.assertEqual(blank_binding["refused"][0]["reason_code"],
                         "MISSING_BINDING")

    def test_valid_identifiers_preserved_byte_for_byte(self):
        plan = migration.build_reviewed_import_plan(
            self.SNAP, [self.row("ref 001", ["tx 1", "tx-1"],
                                 disposition="matched", approved=True,
                                 chosen="tx 1", note="n")])
        self.assertEqual(plan["counts"]["eligible"], 1)
        item = plan["eligible"][0]
        self.assertEqual(item["source_ref_snapshot_only"], "ref 001")
        self.assertEqual(item["chosen_candidate_key"], "tx 1")
        self.assertEqual(item["candidate_transaction_keys"], ["tx 1", "tx-1"])

    def test_adding_or_removing_refused_row_changes_digest(self):
        base_rows = [
            self.row("ref-ok", ["tx-1"], disposition="matched",
                     approved=True, chosen="tx-1"),
            self.row("ref-bad", ["tx-9"], disposition="matched",
                     approved=False, chosen="tx-9"),
        ]
        base = migration.build_reviewed_import_plan(self.SNAP, base_rows)
        added_rows = base_rows + [
            self.row("ref-bad-2", ["tx-8"], disposition="unmatched",
                     approved=True, chosen="tx-8"),
        ]
        added = migration.build_reviewed_import_plan(self.SNAP, added_rows)
        removed = migration.build_reviewed_import_plan(self.SNAP, base_rows[:1])
        self.assertNotEqual(base["plan_digest"], added["plan_digest"])
        self.assertNotEqual(base["plan_digest"], removed["plan_digest"])
        # refused-row digest ordering is independent of input order
        reordered = migration.build_reviewed_import_plan(
            self.SNAP, list(reversed(added_rows)))
        self.assertEqual(reordered["plan_digest"], added["plan_digest"])

    def test_refusal_code_change_changes_digest(self):
        not_approved = [self.row("ref-001", ["tx-1"], disposition="matched",
                                 approved=False, chosen="tx-1")]
        unmatched = [self.row("ref-001", ["tx-1"], disposition="unmatched",
                              approved=True, chosen="tx-1")]
        plan_a = migration.build_reviewed_import_plan(self.SNAP, not_approved)
        plan_b = migration.build_reviewed_import_plan(self.SNAP, unmatched)
        self.assertEqual(plan_a["refused"][0]["reason_code"], "NOT_APPROVED")
        self.assertEqual(plan_b["refused"][0]["reason_code"],
                         "UNMATCHED_DISPOSITION")
        self.assertNotEqual(plan_a["plan_digest"], plan_b["plan_digest"])

    def test_display_prose_only_change_leaves_digest_unchanged(self):
        rows = [self.row("ref-001", ["tx-1"], disposition="matched",
                         approved=False, chosen="tx-1", note="first note")]
        plan = migration.build_reviewed_import_plan(self.SNAP, rows)
        self.assertEqual(plan["counts"]["eligible"], 0)
        self.assertEqual(plan["refused"][0]["reason_code"], "NOT_APPROVED")
        # the same helper the public plan uses, called over the refused
        # output record itself, reproduces the public digest
        self.assertEqual(
            migration._reviewed_plan_digest(
                plan["snapshot_sha256"], plan["eligible"],
                [copy.deepcopy(plan["refused"][0])]),
            plan["plan_digest"])
        # display-only copy: reason prose and review_note change while every
        # stable field including the reason code stays fixed
        altered = copy.deepcopy(plan["refused"][0])
        altered["reason"] = "entirely different display prose"
        altered["review_note"] = "entirely different note"
        self.assertNotEqual(altered["reason"], plan["refused"][0]["reason"])
        self.assertNotEqual(altered["review_note"],
                            plan["refused"][0]["review_note"])
        self.assertEqual(
            migration._reviewed_plan_digest(
                plan["snapshot_sha256"], plan["eligible"], [altered]),
            plan["plan_digest"])
        # eligible rows: note-only change also leaves the digest unchanged
        ok_a = [self.row("ref-002", ["tx-2"], disposition="matched",
                         approved=True, chosen="tx-2", note="one")]
        ok_b = [self.row("ref-002", ["tx-2"], disposition="matched",
                         approved=True, chosen="tx-2", note="two")]
        plan_ok_a = migration.build_reviewed_import_plan(self.SNAP, ok_a)
        plan_ok_b = migration.build_reviewed_import_plan(self.SNAP, ok_b)
        self.assertEqual(plan_ok_a["plan_digest"], plan_ok_b["plan_digest"])


if __name__ == "__main__":
    unittest.main()
