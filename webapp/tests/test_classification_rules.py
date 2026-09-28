"""Phase 6A classification rule tests (synthetic working DB only).

Covers DETAILED_CONTRACT 6.1~6.3 and IMPLEMENTATION_CONTRACT section 6:
allowed fields only, no amount or date effects, four independent scope
outcomes, per-field manual lock, stale preview rejection, request reuse,
no duplicate rule effect on re-upload, source amount and date protection,
rule conflict reporting, and the JSON API surface.
"""

import tempfile
import unittest
from pathlib import Path

from webapp.ledger_store import LedgerStore, SaveError


def make_store():
    directory = tempfile.mkdtemp()
    return LedgerStore(Path(directory) / "webledger.sqlite")


def learning_case(store, row_id="expense-demo-c3", changes=None, request_id="rule-case-1"):
    """Create the learning case through the existing save(rule_change) path."""
    result = store.save(
        row_id=row_id,
        expected_revision=store.get_row(row_id)["revision"],
        client_request_id=request_id,
        change_mode="rule_change",
        changes=changes or {"display_tab_id": "trip-demo-b"},
    )
    return result["learning_case_id"]


def placement_draft(case_id, merchant="예시 숙소", tab="trip-demo-b"):
    return {
        "learning_case_id": case_id,
        "conditions": {"merchant_normalized": merchant},
        "effects": {"display_tab_id": tab},
        "scope": {"trip_id": tab, "event_year": 2026, "applicability": "existing_and_future"},
    }


class DraftValidationTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)

    def tearDown(self):
        self.store.close()

    def _reject(self, draft, code):
        with self.assertRaises(SaveError) as caught:
            self.store.create_rule_draft(draft=draft, client_request_id=f"req-{code}")
        self.assertEqual(caught.exception.code, code)

    def test_amount_effect_is_rejected(self):
        draft = placement_draft(self.case)
        draft["effects"] = {"amount_krw": 1}
        self._reject(draft, "RULE_EFFECT_FORBIDDEN")

    def test_transaction_date_effect_is_rejected(self):
        draft = placement_draft(self.case)
        draft["effects"] = {"occurred_on": "2026-05-01"}
        self._reject(draft, "RULE_EFFECT_FORBIDDEN")

    def test_source_field_effect_is_rejected(self):
        draft = placement_draft(self.case)
        draft["effects"] = {"source_event_id": "SRC-NEW"}
        self._reject(draft, "RULE_EFFECT_FORBIDDEN")

    def test_unknown_condition_field_is_rejected(self):
        draft = placement_draft(self.case)
        draft["conditions"] = {"merchant_name": "예시"}
        self._reject(draft, "RULE_FIELD_NOT_ALLOWED")

    def test_unknown_effect_field_is_rejected(self):
        draft = placement_draft(self.case)
        draft["effects"] = {"display_tab_id": "trip-demo-b", "memo_text": "x"}
        self._reject(draft, "RULE_FIELD_NOT_ALLOWED")

    def test_template_placeholder_is_rejected(self):
        draft = placement_draft(self.case)
        draft["effects"] = {"description_template": "{amount} 원 {merchant}"}
        draft.pop("scope")
        self._reject(draft, "RULE_TEMPLATE_FORBIDDEN")

    def test_travel_placement_needs_full_scope(self):
        draft = placement_draft(self.case)
        draft["scope"] = {"trip_id": "trip-demo-b"}
        self._reject(draft, "RULE_SCOPE_INCOMPLETE")

    def test_condition_operator_is_restricted(self):
        draft = placement_draft(self.case)
        draft["conditions"] = {"merchant_normalized": {"op": "like", "value": "숙소"}}
        self._reject(draft, "RULE_OPERATOR_NOT_ALLOWED")

    def test_condition_value_type_is_restricted(self):
        draft = placement_draft(self.case)
        draft["conditions"] = {"merchant_normalized": {"op": "eq", "value": {"a": 1}}}
        self._reject(draft, "RULE_CONDITION_TYPE")

    def test_direction_value_is_restricted(self):
        draft = placement_draft(self.case)
        draft["conditions"] = {"transaction_direction": "refund_all"}
        self._reject(draft, "RULE_CONDITION_TYPE")

    def test_missing_learning_case_is_rejected(self):
        draft = placement_draft("case-does-not-exist")
        self._reject(draft, "INVALID_VALUE")

    def test_card_kind_rule_matches_only_that_card_kind(self):
        """The synthetic fixture declares card_kind, so the rule really matches."""
        draft = {
            "learning_case_id": self.case,
            "conditions": {"card_kind": "K1"},
            "effects": {"item": "카드확인"},
        }
        rule = self.store.create_rule_draft(draft=draft, client_request_id="req-card-kind")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        included = sorted(c["row_id"] for c in preview["candidates"])
        self.assertEqual(included, ["expense-demo-c1", "expense-demo-c2", "expense-demo-c4"])
        self.assertEqual(preview["unavailable_conditions"], [])
        report = preview["condition_source_report"]["card_kind"]
        self.assertEqual(report["with_source"], 4)
        self.assertEqual(report["missing_source"], 0)

    def test_direction_cancellation_matches_only_the_cancel_row(self):
        draft = {
            "learning_case_id": self.case,
            "conditions": {"transaction_direction": "cancellation"},
            "effects": {"item": "취소확인"},
        }
        rule = self.store.create_rule_draft(draft=draft, client_request_id="req-direction")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        included = sorted(c["row_id"] for c in preview["candidates"])
        self.assertEqual(included, ["expense-demo-c2"])
        self.assertEqual(preview["unavailable_conditions"], [])

    def test_three_base_conditions_narrow_the_match(self):
        draft = {
            "learning_case_id": self.case,
            "conditions": {
                "merchant_normalized": "예시 숙소",
                "card_kind": "K1",
                "transaction_direction": "purchase",
            },
            "effects": {"item": "세조건확인"},
        }
        rule = self.store.create_rule_draft(draft=draft, client_request_id="req-three")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        included = sorted(c["row_id"] for c in preview["candidates"])
        self.assertEqual(included, ["expense-demo-c1", "expense-demo-c4"])
        contract = preview["source_condition_contract"]
        self.assertTrue(contract["card"]["connected"])
        self.assertFalse(contract["bank_income"]["connected"])
        self.assertFalse(contract["manual_expense"]["connected"])


class ScopeOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)

    def tearDown(self):
        self.store.close()

    def _draft(self, request_id, draft=None):
        return self.store.create_rule_draft(
            draft=draft or placement_draft(self.case),
            client_request_id=request_id)

    def test_neither_scope_keeps_draft_only(self):
        rule = self._draft("scope-none")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=False, apply_future=False)
        result = self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=False, apply_future=False,
            client_request_id="apply-none")
        self.assertEqual(result["outcome"], "noop")
        self.assertEqual(result["status"], "draft")
        self.assertEqual(self.store.get_rule(rule["rule_id"])["status"], "draft")
        self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"], "trip-demo-a")
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"], 1)

    def test_existing_only_changes_rows_and_keeps_future_off(self):
        rule = self._draft("scope-existing")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        result = self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=False,
            client_request_id="apply-existing")
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(result["status"], "active")
        self.assertFalse(result["apply_future"])
        self.assertIsNone(result["future_boundary_rowid"])
        self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"], "trip-demo-b")
        self.assertEqual(self.store.get_row("expense-demo-c4")["display_tab_id"], "trip-demo-b")
        self.assertEqual(self.store.active_future_rules(), [])

    def test_future_only_leaves_existing_rows_untouched(self):
        rule = self._draft("scope-future")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=False, apply_future=True)
        self.assertEqual(preview["candidates"], [])
        self.assertEqual(preview["future"]["path_connected"],
                         ["card_import.import_row"])
        self.assertIn("bank_income", preview["future"]["path_not_connected"])
        result = self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=False, apply_future=True,
            client_request_id="apply-future")
        self.assertEqual(result["outcome"], "noop")
        self.assertEqual(result["status"], "active")
        self.assertIsNotNone(result["future_boundary_rowid"])
        self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"], "trip-demo-a")
        self.assertEqual(len(self.store.active_future_rules()), 1)

    def test_both_scopes_change_rows_and_activate_future(self):
        rule = self._draft("scope-both")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=True)
        result = self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=True,
            client_request_id="apply-both")
        self.assertEqual(result["applied_count"], 2)
        self.assertIsNotNone(result["future_boundary_rowid"])
        self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"], "trip-demo-b")

    def test_future_preview_does_not_list_future_transactions(self):
        rule = self._draft("scope-nofuturelist")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=False, apply_future=True)
        self.assertEqual(preview["amounts"], {})
        self.assertEqual(preview["counts"]["matched_rows"], 0)

    def test_existing_preview_reports_before_and_after_amounts(self):
        rule = self._draft("scope-amounts")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        tab_a = preview["amounts"]["trip-demo-a"]
        tab_b = preview["amounts"]["trip-demo-b"]
        self.assertEqual(tab_a["before"], 180000)
        self.assertEqual(tab_a["moving_out"], 200000)
        self.assertEqual(tab_a["after"], -20000)
        self.assertEqual(tab_b["before"], 30000)
        self.assertEqual(tab_b["moving_in"], 200000)
        self.assertEqual(tab_b["after"], 230000)


class ManualLockTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)

    def tearDown(self):
        self.store.close()

    def test_locked_field_is_skipped_and_other_field_applies(self):
        self.store.save(
            row_id="expense-demo-c1", expected_revision=1,
            client_request_id="lock-item", change_mode="exception",
            changes={"item": "수동 항목"})
        draft = {
            "learning_case_id": self.case,
            "conditions": {"merchant_normalized": "예시 숙소"},
            "effects": {"item": "숙박비", "display_tab_id": "trip-demo-b"},
            "scope": {"trip_id": "trip-demo-b", "event_year": 2026,
                      "applicability": "existing_and_future"},
        }
        rule = self.store.create_rule_draft(draft=draft, client_request_id="lock-draft")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        locked = [e for e in preview["excluded"] if e["row_id"] == "expense-demo-c1"]
        self.assertEqual(locked[0]["reason"], "MANUAL_LOCK")
        self.assertEqual(locked[0]["locked_fields"], ["item"])
        candidate = [c for c in preview["candidates"] if c["row_id"] == "expense-demo-c1"][0]
        self.assertNotIn("item", candidate["changes"])
        self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=False,
            client_request_id="lock-apply")
        row = self.store.get_row("expense-demo-c1")
        self.assertEqual(row["item"], "수동 항목")
        self.assertEqual(row["display_tab_id"], "trip-demo-b")

    def test_rule_apply_does_not_create_manual_override(self):
        rule = self.store.create_rule_draft(
            draft=placement_draft(self.case), client_request_id="no-override-draft")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=False,
            client_request_id="no-override-apply")
        self.assertEqual(self.store.manual_locked_fields("expense-demo-c1"), set())


class StalePreviewTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)

    def tearDown(self):
        self.store.close()

    def test_changed_row_rejects_whole_request(self):
        rule = self.store.create_rule_draft(
            draft=placement_draft(self.case), client_request_id="stale-draft")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        self.store.save(
            row_id="expense-demo-c4", expected_revision=1,
            client_request_id="stale-bump", change_mode="exception",
            changes={"operator_note": "사용자 확인"})
        with self.assertRaises(SaveError) as caught:
            self.store.apply_rule(
                preview_id=preview["preview_id"], apply_existing=True, apply_future=False,
                client_request_id="stale-apply")
        self.assertEqual(caught.exception.code, "PREVIEW_STALE")
        self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"], "trip-demo-a")

    def test_scope_change_against_same_preview_is_rejected(self):
        rule = self.store.create_rule_draft(
            draft=placement_draft(self.case), client_request_id="scopechange-draft")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        with self.assertRaises(SaveError) as caught:
            self.store.apply_rule(
                preview_id=preview["preview_id"], apply_existing=True, apply_future=True,
                client_request_id="scopechange-apply")
        self.assertEqual(caught.exception.code, "PREVIEW_STALE")

    def test_unknown_preview_is_rejected(self):
        with self.assertRaises(SaveError) as caught:
            self.store.apply_rule(
                preview_id="preview-missing", apply_existing=True, apply_future=False,
                client_request_id="missing-apply")
        self.assertEqual(caught.exception.code, "INVALID_VALUE")


class RequestReuseTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)
        self.rule = self.store.create_rule_draft(
            draft=placement_draft(self.case), client_request_id="reuse-draft")
        self.preview = self.store.preview_rule(
            rule_id=self.rule["rule_id"], apply_existing=True, apply_future=False)

    def tearDown(self):
        self.store.close()

    def test_same_request_returns_same_result_once(self):
        first = self.store.apply_rule(
            preview_id=self.preview["preview_id"], apply_existing=True, apply_future=False,
            client_request_id="reuse-apply")
        second = self.store.apply_rule(
            preview_id=self.preview["preview_id"], apply_existing=True, apply_future=False,
            client_request_id="reuse-apply")
        self.assertEqual(first, second)
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"], 2)

    def test_same_request_with_other_content_is_rejected(self):
        self.store.apply_rule(
            preview_id=self.preview["preview_id"], apply_existing=True, apply_future=False,
            client_request_id="reuse-apply-2")
        with self.assertRaises(SaveError) as caught:
            self.store.apply_rule(
                preview_id=self.preview["preview_id"], apply_existing=True, apply_future=False,
                selected_row_ids=["expense-demo-c1"],
                client_request_id="reuse-apply-2")
        self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")

    def test_draft_request_reuse_with_other_draft_is_rejected(self):
        draft = placement_draft(self.case, tab="trip-demo-a")
        with self.assertRaises(SaveError) as caught:
            self.store.create_rule_draft(draft=draft, client_request_id="reuse-draft")
        self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")

    def test_draft_request_reuse_with_same_draft_returns_same_rule(self):
        again = self.store.create_rule_draft(
            draft=placement_draft(self.case), client_request_id="reuse-draft")
        self.assertEqual(again["rule_hash"], self.rule["rule_hash"])


class SourceProtectionTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)

    def tearDown(self):
        self.store.close()

    def test_amount_and_date_survive_rule_apply(self):
        rule = self.store.create_rule_draft(
            draft=placement_draft(self.case), client_request_id="protect-draft")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        before = self.store.get_row("expense-demo-c1")
        self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=False,
            client_request_id="protect-apply")
        after = self.store.get_row("expense-demo-c1")
        self.assertEqual(after["amount_krw"], before["amount_krw"])
        self.assertEqual(after["occurred_on"], before["occurred_on"])
        self.assertEqual(after["source_event_id"], before["source_event_id"])
        self.assertEqual(after["revision"], before["revision"] + 1)
        history = self.store.list_history("expense-demo-c1")
        self.assertEqual(history[0]["change_mode"], "rule_apply")

    def test_negative_cancellation_row_is_not_matched_by_purchase_rule(self):
        case = learning_case(self.store, row_id="expense-demo-c1",
                             changes={"display_tab_id": "trip-demo-b"},
                             request_id="protect-case-2")
        draft = {
            "learning_case_id": case,
            "conditions": {"merchant_normalized": "예시 숙소 취소"},
            "optional_conditions": {"amount_range": {"min": 0}},
            "effects": {"item": "교통비"},
        }
        rule = self.store.create_rule_draft(draft=draft, client_request_id="protect-range")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        self.assertEqual(preview["counts"]["matched_rows"], 0)


class FutureUploadPathTests(unittest.TestCase):
    CSV = (
        "occurred_on,merchant,amount_krw,currency,card_last4,approval_no,"
        "cancel_flag,suggested_tab,memo\n"
        "2026-04-09,AGODA TEST,100000,KRW,1111,RX1,,,\n"
    ).encode("utf-8")

    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)
        self.importer = None
        from webapp.card_import import CardImporter

        self.importer = CardImporter(self.store.conn, self.store)

    def tearDown(self):
        self.store.close()

    def _activate_future_rule(self, request_id):
        draft = {
            "learning_case_id": self.case,
            "conditions": {"merchant_normalized": "agoda test",
                           "transaction_direction": "purchase"},
            "effects": {"item": "숙박비", "display_tab_id": "trip-demo-b"},
            "scope": {"trip_id": "trip-demo-b", "event_year": 2026,
                      "applicability": "future"},
        }
        rule = self.store.create_rule_draft(draft=draft, client_request_id=request_id)
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=False, apply_future=True)
        return self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=False, apply_future=True,
            client_request_id=f"{request_id}-apply")

    def test_upload_applies_active_future_rule(self):
        self._activate_future_rule("future-draft")
        received = self.importer.receive(self.CSV, "future.csv")
        self.importer.process_to_completion(received["batch_id"])
        rows = self.store.conn.execute(
            "SELECT row_id FROM board_rows WHERE payload_json LIKE '%AGODA TEST%'").fetchall()
        self.assertEqual(len(rows), 1)
        row = self.store.get_row(rows[0][0])
        self.assertEqual(row["display_tab_id"], "trip-demo-b")
        self.assertEqual(row["item"], "숙박비")
        self.assertEqual(row["amount_krw"], 100000)
        self.assertIn("영칙적용", row["classification_basis"])

    def test_reupload_does_not_apply_rule_twice(self):
        self._activate_future_rule("future-draft-2")
        first = self.importer.receive(self.CSV, "future.csv")
        self.importer.process_to_completion(first["batch_id"])
        before = self.store.conn.execute("SELECT COUNT(*) FROM board_rows").fetchone()[0]
        again = self.importer.receive(self.CSV, "future.csv")
        self.assertTrue(again["reused"])
        self.importer.process_to_completion(again["batch_id"])
        after = self.store.conn.execute("SELECT COUNT(*) FROM board_rows").fetchone()[0]
        self.assertEqual(before, after)
        rows = self.store.conn.execute(
            "SELECT row_id FROM board_rows WHERE payload_json LIKE '%AGODA TEST%'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.store.get_row(rows[0][0])["revision"], 1)


class RuleConflictTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)
        self.first = self.store.create_rule_draft(
            draft=placement_draft(self.case), client_request_id="conflict-first")
        preview = self.store.preview_rule(
            rule_id=self.first["rule_id"], apply_existing=True, apply_future=True)
        self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=True,
            client_request_id="conflict-first-apply")

    def tearDown(self):
        self.store.close()

    def test_second_rule_with_other_value_is_reported_as_conflict(self):
        case = learning_case(self.store, row_id="expense-demo-c1",
                             changes={"item": "수동 항목"},
                             request_id="conflict-case-2")
        draft = {
            "learning_case_id": case,
            "conditions": {"merchant_normalized": "예시 숙소"},
            "effects": {"display_tab_id": "trip-demo-a"},
            "scope": {"trip_id": "trip-demo-a", "event_year": 2026,
                      "applicability": "existing_and_future"},
        }
        second = self.store.create_rule_draft(draft=draft, client_request_id="conflict-second")
        preview = self.store.preview_rule(
            rule_id=second["rule_id"], apply_existing=True, apply_future=False)
        conflicts = [e for e in preview["excluded"] if e["reason"] == "RULE_CONFLICT"]
        self.assertTrue(conflicts)
        self.assertEqual(conflicts[0]["conflicts"][0]["rule_id"], self.first["rule_id"])
        self.assertEqual(preview["counts"]["included_rows"], 0)


class SourceLineageTests(unittest.TestCase):
    HEADER = (
        "occurred_on,merchant,amount_krw,currency,card_last4,approval_no,"
        "cancel_flag,suggested_tab,memo,card_kind\n"
    )

    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)
        from webapp.card_import import CardImporter

        self.importer = CardImporter(self.store.conn, self.store)

    def tearDown(self):
        self.store.close()

    def _upload(self, name, body):
        received = self.importer.receive(body, name)
        self.importer.process_to_completion(received["batch_id"])
        rows = self.store.conn.execute(
            "SELECT row_id FROM board_rows WHERE payload_json LIKE '%AGODA TEST%'"
            " ORDER BY rowid").fetchall()
        return [r[0] for r in rows]

    def _row(self, row_id):
        return self.store.get_row(row_id)

    def test_preexisting_row_resolves_keys_from_card_source_lineage(self):
        body = (self.HEADER + "2026-04-09,AGODA TEST,100000,KRW,1111,LX1,,,,K1\n").encode("utf-8")
        row_id = self._upload("lineage.csv", body)[0]
        stripped = dict(self._row(row_id))
        for key in ("source_merchant", "event_kind", "card_kind"):
            stripped[key] = ""
        self.store.conn.execute(
            "UPDATE board_rows SET payload_json=? WHERE row_id=?",
            (__import__("json").dumps(stripped, ensure_ascii=False, sort_keys=True), row_id))
        self.store.conn.commit()
        keys = self.store.card_source_keys(self._row(row_id))
        self.assertEqual(keys["source_merchant"], "AGODA TEST")
        self.assertEqual(keys["event_kind"], "purchase")
        self.assertEqual(keys["card_kind"], "K1")

    def test_row_without_card_source_reports_no_keys(self):
        created = self.store.create_manual_expense(
            fields={"display_tab_id": None, "occurred_on": "2026-04-09",
                    "amount_krw": 25000, "item": "교통비",
                    "description": "AGODA TEST", "pay_method": "현금"},
            client_request_id="manual-1")
        keys = self.store.card_source_keys(self._row(created["row_id"]))
        self.assertEqual(keys, {})

    def test_edited_description_does_not_change_the_source(self):
        body = (self.HEADER + "2026-04-09,AGODA TEST,100000,KRW,1111,EX1,,,,K1\n").encode("utf-8")
        row_id = self._upload("edit.csv", body)[0]
        self.store.save(
            row_id=row_id, expected_revision=1, client_request_id="edit-desc",
            change_mode="exception", changes={"description": "직접 고친 내용"})
        row = self._row(row_id)
        self.assertEqual(row["description"], "직접 고친 내용")
        self.assertEqual(row["source_merchant"], "AGODA TEST")
        keys = self.store.card_source_keys(row)
        self.assertEqual(keys["source_merchant"], "AGODA TEST")

    def test_rule_does_not_match_a_row_only_through_edited_description(self):
        body = (self.HEADER + "2026-04-09,AGODA TEST,100000,KRW,1111,ED1,,,,K1\n").encode("utf-8")
        row_id = self._upload("edited-match.csv", body)[0]
        self.store.save(
            row_id=row_id, expected_revision=1, client_request_id="edit-desc-2",
            change_mode="exception",
            changes={"description": "OTHER MERCHANT"})
        draft = {
            "learning_case_id": self.case,
            "conditions": {"merchant_normalized": "other merchant"},
            "effects": {"item": "誤매칭"},
        }
        rule = self.store.create_rule_draft(draft=draft, client_request_id="edited-rule")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        self.assertEqual(preview["counts"]["included_rows"], 0)
        self.assertNotIn(row_id, [c["row_id"] for c in preview["candidates"]])
        self.assertEqual(preview["condition_source_report"]["merchant_normalized"]
                         ["missing_source"], 0)

    def test_the_four_scope_combinations_are_each_accepted_and_independent(self):
        """DETAILED 17.3: 규칙 미리보기의 네 가지 범위 선택.

        The two switches are independent, so all four combinations have to be a
        valid request and the flags have to come back exactly as sent. A preview
        that quietly forced one switch on would make the owner's choice a lie.
        """
        store = make_store()
        try:
            case_id = store.save(
                row_id="expense-demo-c1",
                expected_revision=store.get_row("expense-demo-c1")["revision"],
                client_request_id="scope4-move", change_mode="rule_change",
                changes={"display_tab_id": "trip-demo-b"})["learning_case_id"]
            store.open_rule_dialog(
                learning_case_id=case_id,
                draft={"conditions": {"merchant_normalized":
                                      {"op": "eq", "value": "아구다호텔"}},
                       "effects": {"item": "호텔 숙박"}},
                client_request_id="scope4-dialog")
            rule = store.create_rule_draft(
                draft={"conditions": {"merchant_normalized":
                                      {"op": "eq", "value": "아구다호텔"}},
                       "effects": {"item": "호텔 숙박"},
                       "learning_case_id": case_id},
                client_request_id="scope4-draft")
            rule_id = rule["rule_id"]

            seen = {}
            for existing in (False, True):
                for future in (False, True):
                    plan = store.build_rule_preview(
                        rule_id, apply_existing=existing, apply_future=future)
                    key = (existing, future)
                    seen[key] = plan
                    # the request is answered, and the switches came back as sent
                    self.assertEqual(plan["apply_existing"], existing, key)
                    self.assertEqual(plan["apply_future"], future, key)
                    self.assertIn("candidates", plan)
                    self.assertIsNotNone(plan.get("preview_id"))
            # all four really were distinct requests
            ids = {plan["preview_id"] for plan in seen.values()}
            self.assertEqual(len(ids), 4)
        finally:
            store.close()

    def test_existing_and_future_conditions_agree(self):
        first = (self.HEADER + "2026-04-09,AGODA TEST,100000,KRW,1111,EQ1,,,,K1\n").encode("utf-8")
        existing_id = self._upload("equal-existing.csv", first)[0]
        draft = {
            "learning_case_id": self.case,
            "conditions": {
                "merchant_normalized": "agoda test",
                "card_kind": "K1",
                "transaction_direction": "purchase",
            },
            "effects": {"item": "동일확인", "display_tab_id": "trip-demo-b"},
            "scope": {"trip_id": "trip-demo-b", "event_year": 2026,
                      "applicability": "existing_and_future"},
        }
        rule = self.store.create_rule_draft(draft=draft, client_request_id="equal-draft")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=True)
        self.assertIn(existing_id, [c["row_id"] for c in preview["candidates"]])
        self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=True,
            client_request_id="equal-apply")
        second = (self.HEADER + "2026-04-10,AGODA TEST,50000,KRW,1111,EQ2,,,,K1\n").encode("utf-8")
        future_id = [r for r in self._upload("equal-future.csv", second) if r != existing_id][0]
        existing_row = self._row(existing_id)
        future_row = self._row(future_id)
        self.assertEqual(existing_row["item"], future_row["item"])
        self.assertEqual(existing_row["display_tab_id"], future_row["display_tab_id"])
        self.assertEqual(future_row["display_tab_id"], "trip-demo-b")
        self.assertEqual(future_row["card_kind"], "K1")
        self.assertEqual(future_row["event_kind"], "purchase")

    def test_card_kind_condition_skips_other_card_kind_on_upload(self):
        draft = {
            "learning_case_id": self.case,
            "conditions": {"card_kind": "K2"},
            "effects": {"item": "K2확인"},
        }
        rule = self.store.create_rule_draft(draft=draft, client_request_id="k2-draft")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=False, apply_future=True)
        self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=False, apply_future=True,
            client_request_id="k2-apply")
        body = (self.HEADER + "2026-04-11,AGODA TEST,30000,KRW,2222,K9A,,,,K1\n").encode("utf-8")
        row_id = self._upload("k1-upload.csv", body)[0]
        self.assertNotEqual(self._row(row_id)["item"], "K2확인")

    def test_manual_expense_row_is_not_matched_by_a_card_rule(self):
        self.store.create_manual_expense(
            fields={"display_tab_id": None, "occurred_on": "2026-04-09",
                    "amount_krw": 25000, "item": "교통비",
                    "description": "AGODA TEST", "pay_method": "현금"},
            client_request_id="manual-2")
        draft = {
            "learning_case_id": self.case,
            "conditions": {"merchant_normalized": "agoda test"},
            "effects": {"item": "카드규칙"},
        }
        rule = self.store.create_rule_draft(draft=draft, client_request_id="manual-rule")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        manual_id = [c["row_id"] for c in preview["candidates"]
                     if c["row_id"].startswith("manual")]
        self.assertEqual(manual_id, [])
        self.assertFalse(preview["source_condition_contract"]["manual_expense"]["connected"])


class StrictValueTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)

    def tearDown(self):
        self.store.close()

    def _reject(self, draft, code, request_id):
        with self.assertRaises(SaveError) as caught:
            self.store.create_rule_draft(draft=draft, client_request_id=request_id)
        self.assertEqual(caught.exception.code, code)

    def test_impossible_calendar_date_is_rejected(self):
        draft = placement_draft(self.case)
        draft["optional_conditions"] = {
            "date_or_service_period": {"from": "2026-02-30", "to": "2026-03-01"}}
        self._reject(draft, "RULE_CONDITION_TYPE", "date-impossible")

    def test_wrong_date_format_is_rejected(self):
        draft = placement_draft(self.case)
        draft["optional_conditions"] = {"date_or_service_period": {"from": "2026-2-3"}}
        self._reject(draft, "RULE_CONDITION_TYPE", "date-format")

    def test_float_amount_is_rejected(self):
        draft = placement_draft(self.case)
        draft["optional_conditions"] = {"amount_range": {"min": 100.5}}
        self._reject(draft, "RULE_CONDITION_TYPE", "amount-float")

    def test_integral_float_amount_is_rejected(self):
        draft = placement_draft(self.case)
        draft["optional_conditions"] = {"amount_range": {"max": 100.0}}
        self._reject(draft, "RULE_CONDITION_TYPE", "amount-integral-float")

    def test_bool_amount_is_rejected(self):
        draft = placement_draft(self.case)
        draft["optional_conditions"] = {"amount_range": {"min": True}}
        self._reject(draft, "RULE_CONDITION_TYPE", "amount-bool")

    def test_truncating_amount_string_is_rejected(self):
        draft = placement_draft(self.case)
        draft["optional_conditions"] = {"amount_range": {"min": "100.5"}}
        self._reject(draft, "RULE_CONDITION_TYPE", "amount-string")

    def test_exponent_amount_string_is_rejected(self):
        draft = placement_draft(self.case)
        draft["optional_conditions"] = {"amount_range": {"min": "1e3"}}
        self._reject(draft, "RULE_CONDITION_TYPE", "amount-exp")

    def test_integer_string_amount_is_accepted(self):
        draft = placement_draft(self.case)
        draft["optional_conditions"] = {"amount_range": {"min": "100", "max": 900}}
        rule = self.store.create_rule_draft(draft=draft, client_request_id="amount-ok")
        self.assertEqual(rule["status"], "draft")
        self.assertEqual(rule["rule"]["optional_conditions"]["amount_range"],
                         {"min": 100, "max": 900})

    def test_float_event_year_is_rejected(self):
        draft = placement_draft(self.case)
        draft["scope"] = {"trip_id": "trip-demo-b", "event_year": 2026.0,
                          "applicability": "existing_and_future"}
        self._reject(draft, "RULE_CONDITION_TYPE", "year-float")


class AtomicityTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)
        self.rule = self.store.create_rule_draft(
            draft=placement_draft(self.case), client_request_id="atomic-draft")
        self.preview = self.store.preview_rule(
            rule_id=self.rule["rule_id"], apply_existing=True, apply_future=False)

    def tearDown(self):
        self.store.close()

    def test_mid_apply_failure_leaves_no_partial_change(self):
        from unittest import mock

        original = self.store._enqueue_ledger
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("outbox failure")
            return original(*args, **kwargs)

        with mock.patch.object(self.store, "_enqueue_ledger", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                self.store.apply_rule(
                    preview_id=self.preview["preview_id"], apply_existing=True,
                    apply_future=False, client_request_id="atomic-apply")
        self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"], "trip-demo-a")
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"], 1)
        self.assertEqual(self.store.get_row("expense-demo-c4")["display_tab_id"], "trip-demo-a")
        self.assertEqual(self.store.get_row("expense-demo-c4")["revision"], 1)
        stored = self.store.conn.execute(
            "SELECT COUNT(*) FROM rule_apply_requests").fetchone()[0]
        self.assertEqual(stored, 0)
        self.assertEqual(self.store.get_rule(self.rule["rule_id"])["status"], "draft")

    def test_retry_after_rejection_succeeds_with_a_new_preview(self):
        self.store.save(
            row_id="expense-demo-c4", expected_revision=1,
            client_request_id="atomic-bump", change_mode="exception",
            changes={"operator_note": "확인"})
        with self.assertRaises(SaveError) as caught:
            self.store.apply_rule(
                preview_id=self.preview["preview_id"], apply_existing=True,
                apply_future=False, client_request_id="atomic-retry")
        self.assertEqual(caught.exception.code, "PREVIEW_STALE")
        fresh = self.store.preview_rule(
            rule_id=self.rule["rule_id"], apply_existing=True, apply_future=False)
        self.assertNotEqual(fresh["preview_id"], self.preview["preview_id"])
        result = self.store.apply_rule(
            preview_id=fresh["preview_id"], apply_existing=True, apply_future=False,
            client_request_id="atomic-retry-2")
        self.assertEqual(result["applied_count"], 2)


class RuleLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)

    def tearDown(self):
        self.store.close()

    def _activate(self, request_id, tab="trip-demo-b"):
        rule = self.store.create_rule_draft(
            draft=placement_draft(self.case, tab=tab), client_request_id=request_id)
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=True)
        result = self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=True,
            client_request_id=f"{request_id}-apply")
        return rule, preview, result

    def test_conflict_reports_both_conditions_and_an_example(self):
        self._activate("life-first")
        case = learning_case(self.store, row_id="expense-demo-c3",
                             changes={"display_tab_id": "trip-demo-a"},
                             request_id="life-case-2")
        second = self.store.create_rule_draft(
            draft={
                "learning_case_id": case,
                "conditions": {"merchant_normalized": "예시 숙소"},
                "effects": {"display_tab_id": "trip-demo-a"},
                "scope": {"trip_id": "trip-demo-a", "event_year": 2026,
                          "applicability": "existing_and_future"},
            },
            client_request_id="life-second")
        preview = self.store.preview_rule(
            rule_id=second["rule_id"], apply_existing=True, apply_future=False)
        self.assertFalse(preview["conflict_policy"]["latest_rule_wins"])
        self.assertFalse(preview["conflict_policy"]["auto_resolve"])
        self.assertEqual(preview["conflict_policy"]["requires"],
                         "explicit_supersede_or_narrow_draft")
        conflicts = [e for e in preview["excluded"] if e["reason"] == "RULE_CONFLICT"]
        self.assertTrue(conflicts)
        detail = conflicts[0]["conflicts"][0]
        self.assertIn("merchant_normalized", detail["existing_conditions"])
        self.assertIn("merchant_normalized", detail["new_conditions"])
        self.assertTrue(detail["example"]["row_id"].startswith("expense-demo-"))
        self.assertEqual(detail["example"]["event_kind"], "purchase")
        self.assertIn("card_kind", detail["example"])
        self.assertFalse(detail["auto_resolved"])

    def test_newer_rule_does_not_supersede_the_older_one(self):
        first, _preview, _result = self._activate("life-older")
        case = learning_case(self.store, row_id="expense-demo-c3",
                             changes={"display_tab_id": "trip-demo-a"},
                             request_id="life-case-3")
        second = self.store.create_rule_draft(
            draft={
                "learning_case_id": case,
                "conditions": {"merchant_normalized": "예시 숙소"},
                "effects": {"display_tab_id": "trip-demo-a"},
                "scope": {"trip_id": "trip-demo-a", "event_year": 2026,
                          "applicability": "existing_and_future"},
            },
            client_request_id="life-newer")
        self.store.preview_rule(
            rule_id=second["rule_id"], apply_existing=True, apply_future=False)
        self.assertEqual(self.store.get_rule(first["rule_id"])["status"], "active")
        self.assertEqual(self.store.get_rule(second["rule_id"])["status"], "draft")

    def test_explicit_supersede_keeps_applied_rows(self):
        first, _preview, result = self._activate("life-sup-old")
        before = self.store.get_row("expense-demo-c1")
        case = learning_case(self.store, row_id="expense-demo-c3",
                             changes={"display_tab_id": "trip-demo-a"},
                             request_id="life-sup-case")
        second = self.store.create_rule_draft(
            draft={
                "learning_case_id": case,
                "conditions": {"merchant_normalized": "예시 숙소"},
                "effects": {"display_tab_id": "trip-demo-a"},
                "scope": {"trip_id": "trip-demo-a", "event_year": 2026,
                          "applicability": "existing_and_future"},
            },
            client_request_id="life-sup-new")
        superseded = self.store.supersede_rule(
            new_rule_id=second["rule_id"], old_rule_id=first["rule_id"],
            client_request_id="life-supersede")
        self.assertEqual(superseded["rows_changed"], 0)
        self.assertTrue(superseded["history_kept"])
        self.assertEqual(self.store.get_rule(first["rule_id"])["status"], "superseded")
        self.assertFalse(self.store.get_rule(first["rule_id"])["apply_future"])
        after = self.store.get_row("expense-demo-c1")
        self.assertEqual(after["display_tab_id"], before["display_tab_id"])
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(result["applied_count"], 2)

    def test_supersede_is_idempotent_and_bound_to_content(self):
        first, _preview, _result = self._activate("life-idem-old")
        case = learning_case(self.store, row_id="expense-demo-c3",
                             changes={"display_tab_id": "trip-demo-a"},
                             request_id="life-idem-case")
        second = self.store.create_rule_draft(
            draft={
                "learning_case_id": case,
                "conditions": {"merchant_normalized": "예시 숙소"},
                "effects": {"display_tab_id": "trip-demo-a"},
                "scope": {"trip_id": "trip-demo-a", "event_year": 2026,
                          "applicability": "existing_and_future"},
            },
            client_request_id="life-idem-new")
        again = self.store.supersede_rule(
            new_rule_id=second["rule_id"], old_rule_id=first["rule_id"],
            client_request_id="life-supersede-idem")
        self.assertEqual(again["outcome"], "superseded")
        with self.assertRaises(SaveError) as caught:
            self.store.supersede_rule(
                new_rule_id=first["rule_id"], old_rule_id=second["rule_id"],
                client_request_id="life-supersede-idem")
        self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")

    def test_apply_after_supersede_is_refused(self):
        first, preview, _result = self._activate("life-refuse-old")
        case = learning_case(self.store, row_id="expense-demo-c3",
                             changes={"display_tab_id": "trip-demo-a"},
                             request_id="life-refuse-case")
        second = self.store.create_rule_draft(
            draft={
                "learning_case_id": case,
                "conditions": {"merchant_normalized": "예시 이동"},
                "effects": {"item": "교통비"},
            },
            client_request_id="life-refuse-new")
        self.store.supersede_rule(
            new_rule_id=second["rule_id"], old_rule_id=first["rule_id"],
            client_request_id="life-refuse-supersede")
        with self.assertRaises(SaveError) as caught:
            self.store.apply_rule(
                preview_id=preview["preview_id"], apply_existing=True, apply_future=True,
                client_request_id="life-refuse-apply")
        self.assertEqual(caught.exception.code, "RULE_SUPERSEDED")

    def test_revision_bumps_version_and_blocks_the_old_preview(self):
        first, preview, _result = self._activate("life-rev")
        old_revision = self.store.get_row("expense-demo-c1")["revision"]
        revised = self.store.revise_rule(
            rule_id=first["rule_id"],
            draft={
                "learning_case_id": self.case,
                "conditions": {"merchant_normalized": "예시 숙소"},
                "effects": {"display_tab_id": "trip-demo-a"},
                "scope": {"trip_id": "trip-demo-a", "event_year": 2026,
                          "applicability": "existing_and_future"},
            },
            client_request_id="life-revise")
        self.assertEqual(revised["version"], first["version"] + 1)
        self.assertEqual(revised["base_rule_version"], first["version"])
        self.assertEqual(revised["status"], "draft")
        self.assertFalse(revised["apply_future"])
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"], old_revision)
        versions = self.store.list_rule_versions(first["rule_id"])
        self.assertEqual([v["change_kind"] for v in versions],
                         ["created", "apply", "revise"])
        with self.assertRaises(SaveError) as caught:
            self.store.apply_rule(
                preview_id=preview["preview_id"], apply_existing=True, apply_future=True,
                client_request_id="life-rev-apply-second")
        self.assertEqual(caught.exception.code, "PREVIEW_STALE")

    def test_future_switch_off_does_not_revert_rows(self):
        _rule, _preview, result = self._activate("life-future-off")
        self.assertTrue(result["apply_future"])
        row = self.store.get_row("expense-demo-c1")
        updated = self.store.update_rule_scope(
            rule_id=result["rule_id"], apply_existing=True, apply_future=False,
            client_request_id="life-scope-off")
        self.assertEqual(updated["rows_changed"], 0)
        self.assertTrue(updated["history_kept"])
        self.assertFalse(self.store.get_rule(result["rule_id"])["apply_future"])
        self.assertEqual(self.store.get_rule(result["rule_id"])["status"], "active")
        after = self.store.get_row("expense-demo-c1")
        self.assertEqual(after["display_tab_id"], row["display_tab_id"])
        self.assertEqual(after["revision"], row["revision"])
        history = self.store.list_history("expense-demo-c1")
        self.assertTrue(any(h["change_mode"] == "rule_apply" for h in history))
        self.assertEqual(self.store.active_future_rules(), [])

    def test_scope_update_failure_keeps_the_previous_flags(self):
        _rule, _preview, result = self._activate("life-scope-atomic")
        with self.assertRaises(SaveError):
            self.store.update_rule_scope(
                rule_id=result["rule_id"], apply_existing=True, apply_future=False,
                client_request_id="")
        stored = self.store.get_rule(result["rule_id"])
        self.assertTrue(stored["apply_future"])
        self.assertEqual(stored["status"], "active")

    def test_same_effect_rule_is_reported_and_not_applied_twice(self):
        first, _preview, _result = self._activate("life-same-old", tab="trip-demo-b")
        case = learning_case(self.store, row_id="expense-demo-c3",
                             changes={"display_tab_id": "trip-demo-a"},
                             request_id="life-same-case")
        second = self.store.create_rule_draft(
            draft={
                "learning_case_id": case,
                "conditions": {"merchant_normalized": "예시 숙소"},
                "effects": {"display_tab_id": "trip-demo-b"},
                "scope": {"trip_id": "trip-demo-b", "event_year": 2026,
                          "applicability": "existing_and_future"},
            },
            client_request_id="life-same-new")
        preview = self.store.preview_rule(
            rule_id=second["rule_id"], apply_existing=True, apply_future=False)
        self.assertEqual(
            [e for e in preview["excluded"] if e["reason"] == "RULE_CONFLICT"], [])
        for candidate in preview["candidates"]:
            self.assertTrue(candidate["same_effect_rules"])
            self.assertEqual(candidate["same_effect_rules"][0]["rule_id"], first["rule_id"])
        self.assertEqual(preview["counts"]["included_rows"], 0)
        self.assertEqual(preview["counts"]["matched_rows"], 2)

    def test_rule_apply_failure_after_supersede_leaves_no_partial_state(self):
        first, _preview, _result = self._activate("life-atomic-old")
        case = learning_case(self.store, row_id="expense-demo-c3",
                             changes={"display_tab_id": "trip-demo-a"},
                             request_id="life-atomic-case")
        second = self.store.create_rule_draft(
            draft={
                "learning_case_id": case,
                "conditions": {"merchant_normalized": "예시 이동"},
                "effects": {"item": "이동비"},
            },
            client_request_id="life-atomic-new")
        from unittest import mock

        original = self.store._record_rule_version

        def flaky(*args, **kwargs):
            raise RuntimeError("version write failure")

        with mock.patch.object(self.store, "_record_rule_version", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                self.store.supersede_rule(
                    new_rule_id=second["rule_id"], old_rule_id=first["rule_id"],
                    client_request_id="life-atomic-supersede")
        self.assertEqual(self.store.get_rule(first["rule_id"])["status"], "active")
        self.assertTrue(self.store.get_rule(first["rule_id"])["apply_future"])
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM rule_supersessions").fetchone()[0], 0)
        self.assertTrue(callable(original))


class RuleDialogTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)
        self.draft = placement_draft(self.case)

    def tearDown(self):
        self.store.close()

    def test_open_dialog_asks_only_missing_questions(self):
        state = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=self.draft,
            client_request_id="dialog-open")
        keys = [q["question_key"] for q in state["questions"]]
        self.assertLessEqual(len(keys), 5)
        self.assertIn("rule_kind", keys)
        self.assertIn("evidence_basis", keys)
        self.assertNotIn("trip_scope", keys)
        self.assertNotIn("event_year", keys)
        self.assertFalse(state["provider"]["is_real_model_call"])
        self.assertEqual(state["provider"]["model"], None)
        self.assertEqual(state["dialog_state"], "open")
        self.assertEqual(state["row_id"], "expense-demo-c3")

    def test_complete_draft_asks_nothing(self):
        draft = dict(self.draft)
        draft["rule_kind"] = "repeatable"
        draft["evidence_basis"] = "schedule_or_booking"
        draft["optional_conditions"] = {"date_or_service_period": {"from": "2026-04-01"}}
        state = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=draft,
            client_request_id="dialog-complete")
        self.assertEqual(state["questions"], [])
        self.assertEqual(state["open_questions"], [])

    def test_answers_are_not_asked_again_after_resume(self):
        state = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=self.draft,
            client_request_id="dialog-open-2")
        first = state["questions"][0]
        answered = self.store.answer_rule_question(
            question_id=first["question_id"], answer="repeatable",
            expected_row_revision=state["row_revision"],
            client_request_id="dialog-answer-1")
        self.assertEqual(answered["answers"][first["question_key"]], "repeatable")
        self.assertNotIn(first["question_key"],
                         [q["question_key"] for q in answered["open_questions"]])
        self.store.close_rule_dialog(
            learning_case_id=self.case, client_request_id="dialog-close")
        resumed = self.store.resume_rule_dialog(
            learning_case_id=self.case, client_request_id="dialog-resume")
        self.assertEqual(resumed["answers"][first["question_key"]], "repeatable")
        self.assertNotIn(first["question_key"],
                         [q["question_key"] for q in resumed["open_questions"]])
        self.assertEqual(resumed["dialog_state"], "open")

    def test_scope_selection_survives_close_and_resume(self):
        state = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=self.draft,
            apply_existing=True, apply_future=True,
            client_request_id="dialog-scope")
        self.assertTrue(state["apply_existing"])
        self.assertTrue(state["apply_future"])
        self.store.close_rule_dialog(
            learning_case_id=self.case, client_request_id="dialog-scope-close")
        resumed = self.store.resume_rule_dialog(
            learning_case_id=self.case, client_request_id="dialog-scope-resume")
        self.assertTrue(resumed["apply_existing"])
        self.assertTrue(resumed["apply_future"])

    def test_duplicate_answer_request_returns_the_same_result(self):
        state = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=self.draft,
            client_request_id="dialog-open-3")
        question = state["questions"][0]["question_id"]
        first = self.store.answer_rule_question(
            question_id=question, answer="repeatable",
            expected_row_revision=state["row_revision"],
            client_request_id="dialog-answer-dup")
        second = self.store.answer_rule_question(
            question_id=question, answer="repeatable",
            expected_row_revision=state["row_revision"],
            client_request_id="dialog-answer-dup")
        self.assertEqual(first["answers"], second["answers"])
        with self.assertRaises(SaveError) as caught:
            self.store.answer_rule_question(
                question_id=question, answer="this_only",
                expected_row_revision=state["row_revision"],
                client_request_id="dialog-answer-dup")
        self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")

    def test_row_revision_change_refuses_the_answer(self):
        state = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=self.draft,
            client_request_id="dialog-open-4")
        question = state["questions"][0]["question_id"]
        self.store.save(
            row_id="expense-demo-c3",
            expected_revision=self.store.get_row("expense-demo-c3")["revision"],
            client_request_id="dialog-row-bump", change_mode="exception",
            changes={"operator_note": "확인"})
        with self.assertRaises(SaveError) as caught:
            self.store.answer_rule_question(
                question_id=question, answer="repeatable",
                expected_row_revision=state["row_revision"],
                client_request_id="dialog-answer-stale")
        self.assertEqual(caught.exception.code, "DIALOG_STALE")

    def test_closed_dialog_refuses_answers(self):
        state = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=self.draft,
            client_request_id="dialog-open-5")
        question = state["questions"][0]["question_id"]
        self.store.close_rule_dialog(
            learning_case_id=self.case, client_request_id="dialog-close-5")
        with self.assertRaises(SaveError) as caught:
            self.store.answer_rule_question(
                question_id=question, answer="repeatable",
                expected_row_revision=state["row_revision"],
                client_request_id="dialog-answer-closed")
        self.assertEqual(caught.exception.code, "DIALOG_CLOSED")

    def test_one_off_answer_marks_no_permanent_rule(self):
        state = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=self.draft,
            client_request_id="dialog-open-6")
        question = [q for q in state["questions"]
                    if q["question_key"] == "rule_kind"][0]
        answered = self.store.answer_rule_question(
            question_id=question["question_id"], answer="this_only",
            expected_row_revision=state["row_revision"],
            client_request_id="dialog-answer-oneoff")
        self.assertTrue(answered["rule_should_not_be_created"])

    def test_answer_failure_keeps_the_dialog_unchanged(self):
        state = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=self.draft,
            client_request_id="dialog-open-7")
        question = state["questions"][0]
        from unittest import mock

        with mock.patch.object(self.store, "rule_dialog_state",
                               side_effect=RuntimeError("read failure")):
            with self.assertRaises(RuntimeError):
                self.store.answer_rule_question(
                    question_id=question["question_id"], answer="repeatable",
                    expected_row_revision=state["row_revision"],
                    client_request_id="dialog-answer-boom")
        stored = self.store.rule_dialog_state(self.case)
        self.assertIsNone(
            [q for q in stored["questions"] if q["question_id"] == question["question_id"]][0]["answer"])
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM rule_answer_requests").fetchone()[0], 0)


class RuleApiTests(unittest.TestCase):
    def setUp(self):
        import os
        import threading

        from webapp import ledger_board as board_mod

        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "server.sqlite")
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        board_mod.bind_store(self.store)
        self.board_mod = board_mod
        self.server = board_mod.serve(port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        import os

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

    def _post(self, path, payload):
        import json
        import urllib.error
        import urllib.request

        body = dict(payload)
        body.setdefault("csrf", self.board_mod.CSRF_TOKEN)
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_draft_preview_apply_over_http(self):
        case = learning_case(self.store)
        status, rule = self._post("/api/classification/rules/draft", {
            "client_request_id": "api-draft",
            "draft": placement_draft(case),
        })
        self.assertEqual(status, 200)
        self.assertEqual(rule["status"], "draft")
        status, preview = self._post("/api/classification/rules/preview", {
            "client_request_id": "api-preview",
            "rule_id": rule["rule_id"],
            "apply_existing": True,
            "apply_future": False,
        })
        self.assertEqual(status, 200)
        self.assertEqual(preview["counts"]["included_rows"], 2)
        status, applied = self._post("/api/classification/rules/apply", {
            "client_request_id": "api-apply",
            "preview_id": preview["preview_id"],
            "apply_existing": True,
            "apply_future": False,
        })
        self.assertEqual(status, 200)
        self.assertEqual(applied["applied_count"], 2)

    def test_amount_effect_rejected_with_422(self):
        case = learning_case(self.store)
        draft = placement_draft(case)
        draft["effects"] = {"amount_krw": 5}
        status, body = self._post("/api/classification/rules/draft", {
            "client_request_id": "api-bad-effect", "draft": draft})
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "RULE_EFFECT_FORBIDDEN")

    def test_stale_preview_returns_409(self):
        case = learning_case(self.store)
        _status, rule = self._post("/api/classification/rules/draft", {
            "client_request_id": "api-stale-draft", "draft": placement_draft(case)})
        _status, preview = self._post("/api/classification/rules/preview", {
            "client_request_id": "api-stale-preview", "rule_id": rule["rule_id"],
            "apply_existing": True, "apply_future": False})
        self.store.save(
            row_id="expense-demo-c4", expected_revision=1,
            client_request_id="api-stale-bump", change_mode="exception",
            changes={"operator_note": "확인"})
        status, body = self._post("/api/classification/rules/apply", {
            "client_request_id": "api-stale-apply", "preview_id": preview["preview_id"],
            "apply_existing": True, "apply_future": False})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "PREVIEW_STALE")


class RuleVersionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)

    def tearDown(self):
        self.store.close()

    def _draft(self, tab="trip-demo-b", item=None, note=""):
        effects = {"display_tab_id": tab}
        if item:
            effects["item"] = item
        draft = {
            "learning_case_id": self.case,
            "conditions": {"merchant_normalized": "예시 숙소"},
            "effects": effects,
            "scope": {"trip_id": tab, "event_year": 2026,
                      "applicability": "existing_and_future"},
        }
        if note:
            draft["note"] = note
        return draft

    def _activate(self, request_id, tab="trip-demo-b"):
        rule = self.store.create_rule_draft(
            draft=self._draft(tab), client_request_id=request_id)
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=True)
        result = self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=True,
            client_request_id=f"{request_id}-apply")
        return rule, preview, result

    def test_first_version_stores_the_whole_draft(self):
        rule = self.store.create_rule_draft(
            draft=self._draft(item="숙박비", note="운영자 메모"), client_request_id="hist-1")
        history = self.store.rule_history(rule["rule_id"])
        self.assertEqual(history["version_count"], 1)
        first = history["versions"][0]
        self.assertEqual(first["version"], 1)
        self.assertIsNone(first["previous_version"])
        self.assertEqual(first["previous_rule_hash"], "")
        self.assertEqual(first["change_kind"], "created")
        self.assertEqual(first["conditions"],
                         {"merchant_normalized": {"op": "eq", "value": "예시 숙소"}})
        self.assertEqual(first["effects"],
                         {"display_tab_id": "trip-demo-b", "item": "숙박비"})
        self.assertEqual(first["scope"]["trip_id"], "trip-demo-b")
        self.assertEqual(first["scope"]["event_year"], 2026)
        self.assertEqual(first["scope"]["applicability"], "existing_and_future")
        self.assertEqual(first["exceptions"], [])
        self.assertEqual(first["optional_conditions"], {})
        self.assertEqual(first["note"], "운영자 메모")
        self.assertEqual(first["evidence_case_ids"], [self.case])
        self.assertEqual(first["rule_hash"], rule["rule_hash"])

    def test_revision_links_to_the_previous_version_and_keeps_it(self):
        first = self.store.create_rule_draft(
            draft=self._draft(), client_request_id="hist-rev-1")
        before = self.store.rule_history(first["rule_id"])["versions"][0]
        revised = self.store.revise_rule(
            rule_id=first["rule_id"], draft=self._draft(tab="trip-demo-a", item="이동비"),
            client_request_id="hist-rev-2")
        history = self.store.rule_history(first["rule_id"])
        self.assertEqual(history["version_count"], 2)
        kept, latest = history["versions"]
        self.assertEqual(kept["rule_hash"], before["rule_hash"])
        self.assertEqual(kept["rule"], before["rule"])
        self.assertEqual(latest["version"], 2)
        self.assertEqual(latest["previous_version"], 1)
        self.assertEqual(latest["previous_rule_hash"], before["rule_hash"])
        self.assertEqual(latest["base_rule_version"], 1)
        self.assertEqual(latest["effects"]["display_tab_id"], "trip-demo-a")
        self.assertEqual(latest["effects"]["item"], "이동비")
        self.assertEqual(revised["version"], 2)

    def test_apply_writes_the_confirmation_basis(self):
        rule, preview, result = self._activate("hist-apply")
        history = self.store.rule_history(rule["rule_id"])["versions"]
        self.assertEqual(len(history), 2)
        created, applied = history
        self.assertEqual(created["change_kind"], "created")
        self.assertIsNone(created["confirmation"]["preview_id"])
        self.assertEqual(applied["change_kind"], "apply")
        self.assertEqual(applied["status"], "active")
        confirmation = applied["confirmation"]
        self.assertEqual(confirmation["preview_id"], preview["preview_id"])
        self.assertEqual(confirmation["preview_rule_hash"], preview["rule_hash"])
        self.assertEqual(confirmation["applied_rows"], result["applied_count"])
        self.assertEqual(len(confirmation["applied_row_ids"]), result["applied_count"])
        self.assertTrue(confirmation["apply_existing"])
        self.assertTrue(confirmation["apply_future"])
        self.assertEqual(confirmation["learning_case_id"], self.case)
        self.assertIn("confirmed_at", confirmation)
        self.assertIn("answers", confirmation)

    def test_dialog_answers_are_captured_in_the_confirmation(self):
        self.store.open_rule_dialog(
            learning_case_id=self.case, draft=self._draft(),
            client_request_id="hist-dialog-open")
        state = self.store.rule_dialog_state(self.case)
        question = state["questions"][0]
        self.store.answer_rule_question(
            question_id=question["question_id"], answer="repeatable",
            expected_row_revision=state["row_revision"],
            client_request_id="hist-dialog-answer")
        rule, _preview, _result = self._activate("hist-dialog-apply")
        applied = self.store.rule_history(rule["rule_id"])["versions"][-1]
        self.assertEqual(applied["change_kind"], "apply")
        confirmation = applied["confirmation"]
        self.assertEqual(confirmation["answers"].get(question["question_key"]), "repeatable")

    def test_scope_change_adds_history_and_keeps_earlier_versions(self):
        rule, _preview, _result = self._activate("hist-scope")
        before = self.store.rule_history(rule["rule_id"])["versions"]
        updated = self.store.update_rule_scope(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False,
            client_request_id="hist-scope-off")
        self.assertEqual(updated["rows_changed"], 0)
        after = self.store.rule_history(rule["rule_id"])["versions"]
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(after[0]["rule"], before[0]["rule"])
        self.assertEqual(after[0]["rule_hash"], before[0]["rule_hash"])
        latest = after[-1]
        self.assertEqual(latest["change_kind"], "scope")
        self.assertEqual(latest["previous_version"], latest["version"])
        self.assertEqual(latest["previous_rule_hash"], latest["rule_hash"])
        self.assertFalse(latest["confirmation"]["apply_future"])
        self.assertTrue(latest["confirmation"]["apply_existing"])
        self.assertEqual(latest["status"], "active")

    def test_supersede_records_history_without_touching_earlier_versions(self):
        first, _preview, result = self._activate("hist-sup-old")
        before = self.store.rule_history(first["rule_id"])["versions"]
        row_before = self.store.get_row("expense-demo-c1")
        case = learning_case(self.store, row_id="expense-demo-c3",
                             changes={"display_tab_id": "trip-demo-a"},
                             request_id="hist-sup-case")
        second = self.store.create_rule_draft(
            draft={
                "learning_case_id": case,
                "conditions": {"merchant_normalized": "예시 이동"},
                "effects": {"item": "이동비"},
            },
            client_request_id="hist-sup-new")
        self.store.supersede_rule(
            new_rule_id=second["rule_id"], old_rule_id=first["rule_id"],
            client_request_id="hist-supersede")
        after = self.store.rule_history(first["rule_id"])["versions"]
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(after[0]["rule"], before[0]["rule"])
        self.assertEqual(after[0]["rule_hash"], before[0]["rule_hash"])
        self.assertEqual(after[0]["confirmation"], before[0]["confirmation"])
        closing = after[-1]
        self.assertEqual(closing["change_kind"], "superseded")
        self.assertEqual(closing["status"], "superseded")
        self.assertEqual(closing["confirmation"]["superseded_by"], second["rule_id"])
        self.assertEqual(closing["confirmation"]["rows_changed"], 0)
        self.assertTrue(closing["confirmation"]["history_kept"])
        history = self.store.rule_history(first["rule_id"])
        self.assertEqual(history["superseded_by"][0]["superseded_by"], second["rule_id"])
        self.assertEqual(history["supersedes"], [])
        self.assertEqual(self.store.rule_history(second["rule_id"])["supersedes"][0]
                         ["supersedes"], first["rule_id"])
        row_after = self.store.get_row("expense-demo-c1")
        self.assertEqual(row_after["display_tab_id"], row_before["display_tab_id"])
        self.assertEqual(row_after["revision"], row_before["revision"])
        self.assertEqual(result["applied_count"], 2)

    def test_duplicate_revise_request_does_not_create_a_version(self):
        first = self.store.create_rule_draft(
            draft=self._draft(), client_request_id="hist-dup-1")
        payload = self._draft(tab="trip-demo-a", item="이동비")
        one = self.store.revise_rule(
            rule_id=first["rule_id"], draft=payload, client_request_id="hist-dup-revise")
        again = self.store.revise_rule(
            rule_id=first["rule_id"], draft=payload, client_request_id="hist-dup-revise")
        self.assertEqual(one["version"], again["version"])
        self.assertEqual(self.store.rule_history(first["rule_id"])["version_count"], 2)
        with self.assertRaises(SaveError) as caught:
            self.store.revise_rule(
                rule_id=first["rule_id"], draft=self._draft(tab="trip-demo-b"),
                client_request_id="hist-dup-revise")
        self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")
        self.assertEqual(self.store.rule_history(first["rule_id"])["version_count"], 2)
        self.assertEqual(
            self.store.rule_history(first["rule_id"])["version_numbers"], [1, 2])

    def test_duplicate_scope_request_does_not_add_history(self):
        rule, _preview, _result = self._activate("hist-dup-scope")
        first = self.store.update_rule_scope(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False,
            client_request_id="hist-dup-scope-off")
        again = self.store.update_rule_scope(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False,
            client_request_id="hist-dup-scope-off")
        self.assertEqual(first, again)
        self.assertEqual(self.store.rule_history(rule["rule_id"])["version_count"], 3)
        with self.assertRaises(SaveError) as caught:
            self.store.update_rule_scope(
                rule_id=rule["rule_id"], apply_existing=True, apply_future=True,
                client_request_id="hist-dup-scope-off")
        self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")
        self.assertEqual(self.store.rule_history(rule["rule_id"])["version_count"], 3)

    def test_request_id_cannot_cross_operations(self):
        rule, _preview, _result = self._activate("hist-cross")
        self.store.update_rule_scope(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False,
            client_request_id="hist-cross-id")
        with self.assertRaises(SaveError) as caught:
            self.store.revise_rule(
                rule_id=rule["rule_id"], draft=self._draft(tab="trip-demo-a"),
                client_request_id="hist-cross-id")
        self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")

    def test_apply_failure_records_no_history_and_no_confirmation(self):
        rule = self.store.create_rule_draft(
            draft=self._draft(), client_request_id="hist-fail-apply")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=True, apply_future=False)
        from unittest import mock

        original = self.store._store_lifecycle_request

        def flaky(*args, **kwargs):
            raise RuntimeError("request store failure")

        with mock.patch.object(self.store, "_store_lifecycle_request", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                self.store.apply_rule(
                    preview_id=preview["preview_id"], apply_existing=True,
                    apply_future=False, client_request_id="hist-fail-apply-run")
        self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"],
                         "trip-demo-a")
        self.assertEqual(self.store.get_rule(rule["rule_id"])["status"], "draft")
        history = self.store.rule_history(rule["rule_id"])["versions"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["change_kind"], "created")
        self.assertEqual(history[0]["confirmation"]["applied_rows"], 0)
        self.assertIsNone(history[0]["confirmation"]["preview_id"])
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM rule_apply_requests").fetchone()[0], 0)
        self.assertTrue(callable(original))

    def test_revision_failure_keeps_the_previous_version_only(self):
        first = self.store.create_rule_draft(
            draft=self._draft(), client_request_id="hist-fail-revise")
        from unittest import mock

        def flaky(*args, **kwargs):
            raise RuntimeError("version record failure")

        with mock.patch.object(self.store, "_record_rule_version", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                self.store.revise_rule(
                    rule_id=first["rule_id"], draft=self._draft(tab="trip-demo-a"),
                    client_request_id="hist-fail-revise-run")
        history = self.store.rule_history(first["rule_id"])
        self.assertEqual(history["version_count"], 1)
        self.assertEqual(history["current"]["version"], 1)
        self.assertEqual(history["current"]["status"], "draft")
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM rule_lifecycle_requests").fetchone()[0], 0)


class ApplyHistoryAppendTests(unittest.TestCase):
    """A confirmed apply appends history; it never edits a committed entry."""

    def setUp(self):
        self.store = make_store()
        self.case = learning_case(self.store)
        self.rule = self.store.create_rule_draft(
            draft=placement_draft(self.case), client_request_id="append-1")
        self.created = self.store.rule_history(self.rule["rule_id"])["versions"][0]

    def tearDown(self):
        self.store.close()

    def _apply(self, request_id="append-apply"):
        preview = self.store.preview_rule(
            rule_id=self.rule["rule_id"], apply_existing=True, apply_future=True)
        return preview, self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=True,
            client_request_id=request_id)

    def test_apply_appends_a_full_entry(self):
        preview, result = self._apply()
        history = self.store.rule_history(self.rule["rule_id"])["versions"]
        self.assertEqual(len(history), 2)
        entry = history[-1]
        self.assertEqual(entry["change_kind"], "apply")
        self.assertEqual(entry["version"], self.created["version"])
        self.assertEqual(entry["previous_version"], self.created["version"])
        self.assertEqual(entry["previous_rule_hash"], self.created["rule_hash"])
        self.assertEqual(entry["rule_hash"], self.created["rule_hash"])
        self.assertEqual(entry["rule"], self.created["rule"])
        self.assertEqual(entry["status"], "active")
        self.assertEqual(entry["client_request_id"], "append-apply")
        self.assertEqual(entry["actor"], "owner")
        self.assertTrue(entry["created_at"])
        confirmation = entry["confirmation"]
        self.assertEqual(confirmation["preview_id"], preview["preview_id"])
        self.assertEqual(confirmation["applied_rows"], result["applied_count"])
        self.assertEqual(sorted(confirmation["applied_row_ids"]),
                         ["expense-demo-c1", "expense-demo-c4"])
        self.assertTrue(confirmation["apply_existing"])
        self.assertTrue(confirmation["apply_future"])
        self.assertEqual(confirmation["actor"], "owner")
        self.assertEqual(confirmation["confirmed_at"], entry["created_at"])

    def test_committed_entry_is_unchanged_by_the_apply(self):
        _preview, _result = self._apply()
        after = self.store.rule_history(self.rule["rule_id"])["versions"][0]
        self.assertEqual(after, self.created)
        self.assertIsNone(after["confirmation"]["preview_id"])

    def test_same_request_retry_adds_no_history(self):
        preview, first = self._apply()
        again = self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=True, apply_future=True,
            client_request_id="append-apply")
        self.assertEqual(first, again)
        self.assertEqual(
            self.store.rule_history(self.rule["rule_id"])["version_count"], 2)
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"], 2)

    def test_new_request_keeps_the_earlier_confirmation(self):
        preview, _first = self._apply()
        entry_before = self.store.rule_history(self.rule["rule_id"])["versions"][-1]
        self.store.save(
            row_id="expense-demo-c4",
            expected_revision=self.store.get_row("expense-demo-c4")["revision"],
            client_request_id="append-bump", change_mode="exception",
            changes={"operator_note": "확인"})
        fresh = self.store.preview_rule(
            rule_id=self.rule["rule_id"], apply_existing=True, apply_future=True)
        self.assertNotEqual(fresh["preview_id"], preview["preview_id"])
        self.store.apply_rule(
            preview_id=fresh["preview_id"], apply_existing=True, apply_future=True,
            client_request_id="append-apply-second")
        history = self.store.rule_history(self.rule["rule_id"])["versions"]
        self.assertEqual(len(history), 3)
        self.assertEqual(history[1], entry_before)
        self.assertEqual(history[1]["confirmation"]["preview_id"], preview["preview_id"])
        self.assertEqual(history[2]["change_kind"], "apply")
        self.assertEqual(history[2]["confirmation"]["preview_id"], fresh["preview_id"])

    def test_failure_rolls_back_the_new_entry(self):
        preview = self.store.preview_rule(
            rule_id=self.rule["rule_id"], apply_existing=True, apply_future=True)
        from unittest import mock

        original = self.store._record_rule_version

        def flaky(*args, **kwargs):
            raise RuntimeError("history write failure")

        with mock.patch.object(self.store, "_record_rule_version", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                self.store.apply_rule(
                    preview_id=preview["preview_id"], apply_existing=True,
                    apply_future=True, client_request_id="append-apply-boom")
        history = self.store.rule_history(self.rule["rule_id"])["versions"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0], self.created)
        self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"],
                         "trip-demo-a")
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"], 1)
        self.assertEqual(self.store.get_rule(self.rule["rule_id"])["status"], "draft")
        self.assertTrue(callable(original))

    def test_entry_ids_increase_and_stay_unique(self):
        self._apply()
        self.store.update_rule_scope(
            rule_id=self.rule["rule_id"], apply_existing=True, apply_future=False,
            client_request_id="append-scope")
        entries = [item["entry_id"]
                   for item in self.store.rule_history(self.rule["rule_id"])["versions"]]
        self.assertEqual(entries, sorted(entries))
        self.assertEqual(len(entries), len(set(entries)))
        self.assertEqual(
            [item["change_kind"] for item in
             self.store.rule_history(self.rule["rule_id"])["versions"]],
            ["created", "apply", "scope"])


class RuleHistoryApiTests(RuleApiTests):
    def _get(self, path):
        import json
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_versions_endpoint_returns_the_real_history(self):
        case = learning_case(self.store)
        status, rule = self._post("/api/classification/rules/draft", {
            "client_request_id": "api-hist-draft", "draft": placement_draft(case)})
        self.assertEqual(status, 200)
        _status, preview = self._post("/api/classification/rules/preview", {
            "client_request_id": "api-hist-preview", "rule_id": rule["rule_id"],
            "apply_existing": True, "apply_future": True})
        self._post("/api/classification/rules/apply", {
            "client_request_id": "api-hist-apply", "preview_id": preview["preview_id"],
            "apply_existing": True, "apply_future": True})
        status, history = self._get(f"/api/classification/rules/{rule['rule_id']}/versions")
        self.assertEqual(status, 200)
        self.assertEqual(history["version_count"], 2)
        created, applied = history["versions"]
        self.assertEqual(created["change_kind"], "created")
        self.assertIsNone(created["confirmation"]["preview_id"])
        self.assertEqual(applied["change_kind"], "apply")
        self.assertEqual(created["conditions"],
                         {"merchant_normalized": {"op": "eq", "value": "예시 숙소"}})
        self.assertEqual(created["effects"], {"display_tab_id": "trip-demo-b"})
        self.assertEqual(created["scope"]["event_year"], 2026)
        self.assertEqual(created["evidence_case_ids"], [case])
        self.assertEqual(applied["confirmation"]["preview_id"], preview["preview_id"])
        self.assertEqual(applied["confirmation"]["applied_rows"], 2)
        self.assertEqual(history["current"]["version"], 1)
        self.assertEqual(history["current"]["status"], "active")

    def test_versions_endpoint_404_for_unknown_rule(self):
        status, body = self._get("/api/classification/rules/rule-missing/versions")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "RESOURCE_NOT_FOUND")

    def test_revise_over_http_then_history(self):
        case = learning_case(self.store)
        _status, rule = self._post("/api/classification/rules/draft", {
            "client_request_id": "api-rev-draft", "draft": placement_draft(case)})
        status, revised = self._post("/api/classification/rules/revise", {
            "client_request_id": "api-rev-revise", "rule_id": rule["rule_id"],
            "draft": {
                "learning_case_id": case,
                "conditions": {"merchant_normalized": "예시 숙소"},
                "effects": {"display_tab_id": "trip-demo-a"},
                "scope": {"trip_id": "trip-demo-a", "event_year": 2026,
                          "applicability": "existing_and_future"},
            }})
        self.assertEqual(status, 200)
        self.assertEqual(revised["version"], 2)
        _status, history = self._get(f"/api/classification/rules/{rule['rule_id']}/versions")
        self.assertEqual(history["version_count"], 2)
        self.assertEqual(history["versions"][1]["previous_version"], 1)
        self.assertEqual(history["versions"][0]["effects"]["display_tab_id"], "trip-demo-b")
        self.assertEqual(history["versions"][1]["effects"]["display_tab_id"], "trip-demo-a")


class RuleLifecycleApiTests(RuleApiTests):
    def test_supersede_and_scope_over_http(self):
        case = learning_case(self.store)
        _status, first = self._post("/api/classification/rules/draft", {
            "client_request_id": "life-api-first", "draft": placement_draft(case)})
        _status, preview = self._post("/api/classification/rules/preview", {
            "client_request_id": "life-api-preview", "rule_id": first["rule_id"],
            "apply_existing": True, "apply_future": True})
        self._post("/api/classification/rules/apply", {
            "client_request_id": "life-api-apply", "preview_id": preview["preview_id"],
            "apply_existing": True, "apply_future": True})
        status, scoped = self._post("/api/classification/rules/scope", {
            "client_request_id": "life-api-scope", "rule_id": first["rule_id"],
            "apply_existing": True, "apply_future": False})
        self.assertEqual(status, 200)
        self.assertEqual(scoped["rows_changed"], 0)
        self.assertFalse(scoped["apply_future"])
        second_case = learning_case(self.store, row_id="expense-demo-c3",
                                    changes={"display_tab_id": "trip-demo-a"},
                                    request_id="life-api-case-2")
        _status, second = self._post("/api/classification/rules/draft", {
            "client_request_id": "life-api-second",
            "draft": {
                "learning_case_id": second_case,
                "conditions": {"merchant_normalized": "예시 이동"},
                "effects": {"item": "이동비"},
            }})
        status, superseded = self._post("/api/classification/rules/supersede", {
            "client_request_id": "life-api-supersede",
            "new_rule_id": second["rule_id"], "old_rule_id": first["rule_id"]})
        self.assertEqual(status, 200)
        self.assertEqual(superseded["old_status"], "superseded")
        self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"],
                         "trip-demo-b")

    def test_dialog_lifecycle_over_http(self):
        case = learning_case(self.store)
        status, opened = self._post("/api/classification/dialog/open", {
            "client_request_id": "api-dialog-open", "learning_case_id": case,
            "draft": placement_draft(case)})
        self.assertEqual(status, 200)
        self.assertTrue(opened["questions"])
        question = opened["questions"][0]["question_id"]
        status, answered = self._post("/api/classification/dialog/answer", {
            "client_request_id": "api-dialog-answer", "question_id": question,
            "answer": "repeatable", "expected_row_revision": opened["row_revision"]})
        self.assertEqual(status, 200)
        self.assertIn("repeatable", answered["answers"].values())
        status, closed = self._post("/api/classification/dialog/close", {
            "client_request_id": "api-dialog-close", "learning_case_id": case})
        self.assertEqual(status, 200)
        self.assertEqual(closed["dialog_state"], "closed")
        status, resumed = self._post("/api/classification/dialog/resume", {
            "client_request_id": "api-dialog-resume", "learning_case_id": case})
        self.assertEqual(status, 200)
        self.assertEqual(resumed["dialog_state"], "open")
        status, stale = self._post("/api/classification/dialog/answer", {
            "client_request_id": "api-dialog-stale",
            "question_id": opened["questions"][1]["question_id"],
            "answer": "schedule_or_booking",
            "expected_row_revision": opened["row_revision"] - 1})
        self.assertEqual(status, 409)
        self.assertEqual(stale["code"], "DIALOG_STALE")
