"""Owner correction -> deterministic rule draft -> preview -> explicit apply, and its link to card imports.

Synthetic data only. No model is configured anywhere in these tests.
"""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from webapp.card_flow import CardFlow
from webapp.ledger_store import LedgerStore, SaveError

MERCHANT = "예시편의점"


def make_store():
    return LedgerStore(Path(tempfile.mkdtemp()) / "webledger.sqlite")


def set_source_merchant(store, row_id, merchant=MERCHANT):
    row = store.conn.execute("SELECT payload_json FROM board_rows WHERE row_id=?", (row_id,)).fetchone()
    payload = json.loads(row[0])
    payload["source_merchant"] = merchant
    store.conn.execute("UPDATE board_rows SET payload_json=? WHERE row_id=?",
                       (json.dumps(payload, ensure_ascii=False), row_id))


def correct(store, row_id, changes, request_id):
    return store.save(row_id=row_id, expected_revision=store.get_row(row_id)["revision"],
                      client_request_id=request_id, change_mode="rule_change",
                      changes=changes)["learning_case_id"]


class OwnerCorrectionDraftTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        for row_id in ("expense-demo-c1", "expense-demo-c3"):
            set_source_merchant(self.store, row_id)
        self.addCleanup(self.store.close)

    def test_the_draft_is_built_from_the_saved_correction_and_source_merchant_only(self):
        case = correct(self.store, "expense-demo-c3", {"item": "소모품비"}, "fix-1")
        rule = self.store.owner_correction_draft(learning_case_id=case, client_request_id="draft-1")
        body = rule["rule"]
        self.assertEqual(rule["status"], "draft")
        self.assertEqual(list(body["conditions"]), ["merchant_normalized"])
        self.assertEqual(body["conditions"]["merchant_normalized"]["value"], MERCHANT)
        self.assertEqual(body["effects"], {"item": "소모품비"})
        self.assertEqual(body["evidence_case_ids"], [case])
        # a draft changes nothing by itself
        self.assertEqual(self.store.get_row("expense-demo-c1")["item"],
                         self.store.get_row("expense-demo-c1")["item"])
        page = self.store.dialog_page_state(case)
        self.assertEqual(page["rule"]["rule_id"], rule["rule_id"])

    def test_a_trip_correction_carries_trip_and_year_scope(self):
        case = correct(self.store, "expense-demo-c3", {"display_tab_id": "trip-demo-b"}, "fix-2")
        body = self.store.owner_correction_draft(learning_case_id=case, client_request_id="draft-2")["rule"]
        self.assertEqual(body["effects"], {"display_tab_id": "trip-demo-b"})
        self.assertEqual(body["scope"]["trip_id"], "trip-demo-b")
        self.assertIsInstance(body["scope"]["event_year"], int)

    def test_without_a_saved_correction_no_draft_is_made(self):
        case = correct(self.store, "expense-demo-c3", {"item": "소모품비"}, "fix-3")
        original = self.store.get_row("expense-demo-c3")
        self.store.save(row_id="expense-demo-c3", expected_revision=original["revision"],
                        client_request_id="fix-3-back", change_mode="exception", changes={"item": "교통비"})
        with self.assertRaises(SaveError) as caught:
            self.store.owner_correction_draft(learning_case_id=case, client_request_id="draft-3")
        self.assertEqual(caught.exception.code, "RULE_NO_CORRECTION")

    def test_a_row_without_a_card_source_merchant_gets_no_draft(self):
        row_id = "expense-demo-c4"
        set_source_merchant(self.store, row_id, "")
        case = correct(self.store, row_id, {"item": "소모품비"}, "fix-4")
        with self.assertRaises(SaveError) as caught:
            self.store.owner_correction_draft(learning_case_id=case, client_request_id="draft-4")
        self.assertEqual(caught.exception.code, "RULE_SOURCE_MISSING")

    def test_the_same_request_id_returns_the_same_draft(self):
        case = correct(self.store, "expense-demo-c3", {"item": "소모품비"}, "fix-5")
        first = self.store.owner_correction_draft(learning_case_id=case, client_request_id="draft-5")
        second = self.store.owner_correction_draft(learning_case_id=case, client_request_id="draft-5")
        self.assertEqual(first["rule_id"], second["rule_id"])

    def test_preview_then_apply_existing_moves_other_rows_but_not_the_edited_one(self):
        case = correct(self.store, "expense-demo-c3", {"item": "소모품비"}, "fix-6")
        rule = self.store.owner_correction_draft(learning_case_id=case, client_request_id="draft-6")
        before_other = self.store.get_row("expense-demo-c1")["item"]
        preview = self.store.preview_rule(rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        self.assertEqual(preview["counts"]["included_rows"], 1)
        # previewing is read only
        self.assertEqual(self.store.get_row("expense-demo-c1")["item"], before_other)
        self.store.apply_rule(preview_id=preview["preview_id"], apply_existing=True, apply_future=False,
                              client_request_id="apply-6")
        self.assertEqual(self.store.get_row("expense-demo-c1")["item"], "소모품비")
        self.assertEqual(self.store.active_future_rules(), [])

    def test_future_only_leaves_existing_rows_and_turns_the_rule_on_for_imports(self):
        case = correct(self.store, "expense-demo-c3", {"item": "소모품비"}, "fix-7")
        rule = self.store.owner_correction_draft(learning_case_id=case, client_request_id="draft-7")
        before_other = self.store.get_row("expense-demo-c1")["item"]
        preview = self.store.preview_rule(rule_id=rule["rule_id"], apply_existing=False, apply_future=True)
        self.store.apply_rule(preview_id=preview["preview_id"], apply_existing=False, apply_future=True,
                              client_request_id="apply-7")
        self.assertEqual(self.store.get_row("expense-demo-c1")["item"], before_other)
        self.assertEqual([r["rule_id"] for r in self.store.active_future_rules()], [rule["rule_id"]])


class BoardRulesToCardRulesTests(unittest.TestCase):
    def flow(self, stored):
        flow = CardFlow.__new__(CardFlow)
        flow.board = SimpleNamespace(active_future_rules=lambda: stored)
        return flow

    @staticmethod
    def stored(conditions, effects, *, optional=None, scope=None, exceptions=None, rule_id="rule-a"):
        rule = {"conditions": conditions, "effects": effects, "optional_conditions": optional or {},
                "scope": scope or {}, "exceptions": exceptions or []}
        return {"rule_id": rule_id, "version": 1, "rule": rule}

    def test_a_merchant_rule_becomes_a_card_rule(self):
        stored = self.stored({"merchant_normalized": {"op": "eq", "value": "예시편의점"}}, {"item": "소모품비"})
        converted = self.flow([stored])._board_future_rules()
        self.assertEqual(len(converted), 1)
        self.assertEqual(converted[0]["conditions"], {"merchant_normalized": "예시편의점"})
        self.assertEqual(converted[0]["effects"], {"item": "소모품비"})
        self.assertEqual(converted[0]["origin"], "board-rule")

    def test_rules_the_card_side_cannot_evaluate_are_not_widened(self):
        narrow = self.stored({"merchant_normalized": {"op": "eq", "value": "a"},
                              "card_kind": {"op": "eq", "value": "국내"}}, {"item": "x"})
        excepted = self.stored({"merchant_normalized": {"op": "eq", "value": "b"}}, {"item": "x"},
                               exceptions=[{"field": "merchant_normalized", "op": "eq", "value": "c"}])
        self.assertEqual(self.flow([narrow, excepted])._board_future_rules(), [])

    def test_a_trip_rule_is_limited_to_its_event_year(self):
        stored = self.stored({"merchant_normalized": {"op": "eq", "value": "예시"}},
                             {"display_tab_id": "trip-1"}, scope={"trip_id": "trip-1", "event_year": 2026,
                                                                   "applicability": "existing_and_future"})
        converted = self.flow([stored])._board_future_rules()
        self.assertEqual(converted[0]["optional"]["date_or_service_period"],
                         {"start": "2026-01-01", "end": "2026-12-31"})

    def test_an_explicitly_applied_rule_replaces_the_general_card_rule_for_the_same_merchant(self):
        board_rules = [{"rule_id": "board-1", "conditions": {"merchant_normalized": "예시"},
                        "effects": {"item": "소모품비"}, "optional": {}}]
        old = {"rule_id": "card-1", "conditions": {"merchant_normalized": "예시", "card_kind": "국내"},
               "effects": {"item": "사무용품비", "description": "사무용품비"}, "optional": {}}
        bound = {"rule_id": "card-2", "conditions": {"merchant_normalized": "예시"},
                 "effects": {"item": "숙박비"}, "optional": {"source_hash": "h1"}}
        other = {"rule_id": "card-3", "conditions": {"merchant_normalized": "다른곳"},
                 "effects": {"item": "식비"}, "optional": {}}
        kept, merged = CardFlow._board_rules_supersede([old, bound, other], board_rules)
        self.assertEqual([r["rule_id"] for r in kept], ["card-2", "card-3"])
        self.assertEqual(merged[0]["effects"], {"item": "소모품비", "description": "사무용품비"})

    def test_a_dated_board_rule_does_not_replace_the_general_rule(self):
        board_rules = [{"rule_id": "board-1", "conditions": {"merchant_normalized": "예시"},
                        "effects": {"item": "소모품비"},
                        "optional": {"date_or_service_period": {"start": "2026-01-01"}}}]
        old = {"rule_id": "card-1", "conditions": {"merchant_normalized": "예시"},
               "effects": {"item": "사무용품비"}, "optional": {}}
        kept, merged = CardFlow._board_rules_supersede([old], board_rules)
        self.assertEqual([r["rule_id"] for r in kept], ["card-1"])
        self.assertEqual(merged, board_rules)


class UnassignedRowSaveTests(unittest.TestCase):
    """A row waiting for a trip posts an empty trip select; fixing its item must still save."""

    def setUp(self):
        from webapp import ledger_board as board_mod
        self.board_mod = board_mod
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        self.tmp = tempfile.mkdtemp()
        db_path = str(Path(self.tmp) / "server.sqlite")
        os.environ["WEBLEDGER_DB"] = db_path
        self.store = LedgerStore(Path(db_path))
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        worker = getattr(self.server, "card_worker", None)
        if worker is not None:
            worker.stop(timeout=5)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.board_mod.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def post(self, row_id, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/rows/{row_id}/save",
            data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_an_item_fix_with_an_empty_trip_select_keeps_the_row_unassigned(self):
        row = self.store.get_row("expense-demo-c3")
        self.assertIsNone(row["display_tab_id"])
        status, result = self.post("expense-demo-c3", {
            "csrf": self.board_mod.CSRF_TOKEN, "expected_revision": row["revision"],
            "client_request_id": "unassigned-1", "change_mode": "exception",
            "display_tab_id": "", "item": "소모품비"})
        self.assertEqual(status, 200, result)
        saved = self.store.get_row("expense-demo-c3")
        self.assertEqual(saved["item"], "소모품비")
        self.assertIsNone(saved["display_tab_id"])


if __name__ == "__main__":
    unittest.main()
