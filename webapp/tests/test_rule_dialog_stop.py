"""Phase 6C follow-up: one-off stop, provider return, process restart.

Synthetic adapters only. No network, no key, no real provider call, and no
claim that a real PC was powered off: the restart case opens a second store
instance on the same database file, which is the same code path a real restart
takes.
"""

import unittest

from webapp.classification_rules import (
    ONE_OFF_ANSWERS,
    OPTION_LABELS,
    QUESTION_SPECS,
    dialog_blocks_rule,
    question_view,
)
from webapp.dialog_turn import ProviderTransportError, SyntheticAdapter, run_turn
from webapp.ledger_store import _PROCESS_PID, _utc_now, SaveError
from webapp.tests.test_dialog_turns import (
    GEMINI_MODEL,
    MUSE_MODEL,
    RaisingAdapter,
    learning_case,
    make_store,
    valid_draft,
)


class QuestionWordingTests(unittest.TestCase):
    """The screen must read like normal work Korean."""

    EXPECTED = {
        "rule_kind": "이번 거래에만 적용할까요, 비슷한 거래에도 적용할까요?",
        "evidence_basis": "이렇게 분류한 근거는 무엇인가요?",
        "trip_scope": "어느 여행에 적용할까요?",
        "event_year": "어느 연도에 적용할까요?",
        "period": "적용 기간을 제한할까요?",
    }

    def test_every_prompt_is_the_confirmed_sentence(self):
        prompts = {spec["key"]: spec["prompt"] for spec in QUESTION_SPECS}
        self.assertEqual(prompts, self.EXPECTED)

    def test_stored_values_stay_internal_enums_with_korean_labels(self):
        for spec in QUESTION_SPECS:
            for value in spec["options"]:
                self.assertIn(value, OPTION_LABELS)
                self.assertRegex(OPTION_LABELS[value], r"[가-힣]")
        view = question_view({"question_key": "rule_kind",
                              "prompt": QUESTION_SPECS[0]["prompt"],
                              "options": ("this_only", "repeatable"),
                              "answer": "this_only"})
        self.assertEqual([item["value"] for item in view["options"]],
                         ["this_only", "repeatable"])
        self.assertEqual([item["label"] for item in view["options"]],
                         ["이번 거래에만", "비슷한 거래에도"])
        self.assertEqual(view["answer_label"], "이번 거래에만")

    def test_one_off_answers_are_the_documented_two(self):
        self.assertEqual(set(ONE_OFF_ANSWERS), {"this_only", "one_off_exception"})
        self.assertTrue(dialog_blocks_rule({"rule_kind": "this_only"}))
        self.assertTrue(dialog_blocks_rule({"evidence_basis": "one_off_exception"}))
        self.assertFalse(dialog_blocks_rule({"rule_kind": "repeatable"}))


class OneOffStopTests(unittest.TestCase):
    """A one-off answer ends the dialog on the server, not only on the screen."""

    def setUp(self):
        self.store, self.path = make_store()
        self.case = learning_case(self.store, request_id="p6d-case")
        self.store.open_rule_dialog(
            learning_case_id=self.case, draft=valid_draft(self.case),
            client_request_id="p6d-dialog")
        self.conversation = self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p6d-open")["conversation_id"]

    def tearDown(self):
        self.store.close()

    def _answer(self, key, value, request_id):
        state = self.store.rule_dialog_state(self.case)
        question = [q for q in state["questions"] if q["question_key"] == key][0]
        return self.store.answer_rule_question(
            question_id=question["question_id"], answer=value,
            expected_row_revision=state["row_revision"],
            client_request_id=request_id)

    def test_one_off_answer_asks_nothing_further_and_keeps_the_row_edit(self):
        row = self.store.get_row("expense-demo-c3")
        self._answer("rule_kind", "this_only", "p6d-answer")
        state = self.store.rule_dialog_state(self.case)
        self.assertEqual(state["open_questions"], [])
        self.assertEqual(state["dialog_state"], "one_off")
        self.assertTrue(state["rule_should_not_be_created"])
        # the row change the owner already saved is not reverted
        after = self.store.get_row("expense-demo-c3")
        self.assertEqual(after["display_tab_id"], "trip-demo-b")
        self.assertEqual(after["revision"], row["revision"])
        # reopening the dialog does not add a question back
        reopened = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=valid_draft(self.case),
            client_request_id="p6d-dialog-2")
        self.assertEqual(reopened["open_questions"], [])

    def test_one_off_answer_refuses_draft_turn_preview_and_apply(self):
        self._answer("evidence_basis", "one_off_exception", "p6d-answer")
        self.assertEqual(self.store.rule_dialog_state(self.case)["dialog_state"],
                         "one_off")
        self.assertEqual(
            self.store.rule_dialog_state(self.case)["open_questions"], [])
        with self.assertRaises(SaveError) as draft_error:
            self.store.create_rule_draft(
                draft=valid_draft(self.case), client_request_id="p6d-rule")
        self.assertEqual(draft_error.exception.code, "RULE_ONE_OFF")
        with self.assertRaises(SaveError) as turn_error:
            self.store.run_dialog_turn(
                conversation_id=self.conversation, client_request_id="p6d-turn",
                muse=SyntheticAdapter("muse", MUSE_MODEL, draft=valid_draft(self.case)))
        self.assertEqual(turn_error.exception.code, "RULE_ONE_OFF")
        # no rule row was created by any of the refused calls
        self.assertEqual(
            self.store.conn.execute(
                "SELECT COUNT(*) FROM classification_rules").fetchone()[0], 0)

    def test_one_off_answer_blocks_preview_and_apply_even_when_called_directly(self):
        self._answer("rule_kind", "this_only", "p6d-answer")
        # the rule and the preview rows are inserted directly, so the guard is
        # exercised on the store path and not through the screen
        created = self._force_rule_for_case()
        with self.assertRaises(SaveError) as preview_error:
            self.store.preview_rule(
                rule_id=created["rule_id"], apply_existing=True, apply_future=False)
        self.assertEqual(preview_error.exception.code, "RULE_ONE_OFF")
        with self.assertRaises(SaveError) as build_error:
            self.store.build_rule_preview(
                created["rule_id"], apply_existing=True, apply_future=False)
        self.assertEqual(build_error.exception.code, "RULE_ONE_OFF")
        preview = self._force_preview_for(created)
        with self.assertRaises(SaveError) as apply_error:
            self.store.apply_rule(
                preview_id=preview, apply_existing=True, apply_future=False,
                client_request_id="p6d-apply")
        self.assertEqual(apply_error.exception.code, "RULE_ONE_OFF")
        # nothing was written to the ledger
        self.assertEqual(
            self.store.get_row("expense-demo-c3")["display_tab_id"], "trip-demo-b")
        self.assertEqual(
            self.store.conn.execute("SELECT COUNT(*) FROM rule_apply_requests"
                                    ).fetchone()[0], 0)

    def test_one_off_survives_close_and_resume(self):
        self._answer("rule_kind", "this_only", "p6d-answer")
        self.store.close_rule_dialog(
            learning_case_id=self.case, client_request_id="p6d-close")
        resumed = self.store.resume_rule_dialog(
            learning_case_id=self.case, client_request_id="p6d-resume")
        self.assertTrue(resumed["rule_should_not_be_created"])
        self.assertEqual(resumed["open_questions"], [])
        with self.assertRaises(SaveError):
            self.store.create_rule_draft(
                draft=valid_draft(self.case), client_request_id="p6d-rule-2")
        # a future rule and an ordinary row save stay independent
        self.assertEqual(
            self.store.get_row("expense-demo-c3")["display_tab_id"], "trip-demo-b")
        other_case = self.store.save(
            row_id="expense-demo-c1",
            expected_revision=self.store.get_row("expense-demo-c1")["revision"],
            client_request_id="p6d-other-save", change_mode="exception",
            changes={"display_tab_id": "trip-demo-a"})["learning_case_id"]
        self.assertEqual(
            self.store.get_row("expense-demo-c1")["display_tab_id"], "trip-demo-a")
        # the other case keeps its own dialog, and this one-off case does not
        # block it
        self.assertFalse(self.store.case_is_one_off(other_case))
        self.assertTrue(self.store.case_is_one_off(self.case))

    def _force_preview_for(self, created):
        import json as _json

        self.store.conn.execute(
            "INSERT INTO rule_previews(preview_id, rule_id, rule_hash, rule_version,"
            " apply_existing, apply_future, plan_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            ("preview-forced", created["rule_id"], created["rule_hash"],
             created["version"], 1, 0, _json.dumps({"include": [], "exclude": []}),
             "2026-09-26T00:00:00+00:00"))
        return "preview-forced"

    def _force_rule_for_case(self):
        """Insert a rule for this one-off case, bypassing the guard on purpose."""
        import json as _json

        from webapp.classification_rules import normalize_draft, rule_hash

        normalized = normalize_draft(
            dict(valid_draft(self.case), learning_case_id=self.case),
            learning_case_id=self.case, rule_id=f"{self.case}-forced", version=1,
            base_rule_version=0)
        now = "2026-09-26T00:00:00+00:00"
        digest = rule_hash(normalized)
        self.store.conn.execute(
            "INSERT INTO classification_rules(rule_id, version, base_rule_version, status,"
            " apply_existing, apply_future, rule_hash, rule_json, learning_case_id,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"{self.case}-forced", 1, 0, "draft", 0, 0, digest,
             _json.dumps(normalized, ensure_ascii=False), self.case, now, now))
        return {"rule_id": f"{self.case}-forced", "version": 1,
                "rule_hash": digest}


class ProviderReturnTests(unittest.TestCase):
    """Turn 1 falls back to Gemini, turn 2 uses a recovered Muse."""

    def setUp(self):
        self.store, self.path = make_store()
        self.case = learning_case(self.store, request_id="p6d-case-2")
        self.store.open_rule_dialog(
            learning_case_id=self.case, draft=valid_draft(self.case),
            client_request_id="p6d-dialog")
        self.conversation = self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p6d-open")["conversation_id"]

    def tearDown(self):
        self.store.close()

    def _answer(self, key, value, request_id):
        state = self.store.rule_dialog_state(self.case)
        question = [q for q in state["questions"] if q["question_key"] == key][0]
        return self.store.answer_rule_question(
            question_id=question["question_id"], answer=value,
            expected_row_revision=state["row_revision"],
            client_request_id=request_id)

    def test_muse_returns_on_the_next_turn_and_keeps_the_same_meaning(self):
        self._answer("rule_kind", "repeatable", "p6d-answer")
        self._answer("evidence_basis", "schedule_or_booking", "p6d-answer-2")
        broken_muse = RaisingAdapter("muse", MUSE_MODEL,
                                     ProviderTransportError("connection_refused"))
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
        first = self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p6d-turn-1",
            muse=broken_muse, gemini=gemini)
        self.assertEqual(first["active_provider"], "gemini")
        self.assertEqual(first["turns"][-1]["adopted_provider"], "gemini")
        self.assertEqual(first["turns"][-1]["switch_count"], 1)

        healthy_muse = SyntheticAdapter("muse", MUSE_MODEL,
                                        draft=valid_draft(self.case, "항공비확인"))
        second = self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p6d-turn-2",
            muse=healthy_muse, gemini=gemini)
        self.assertEqual(second["turns"][-1]["adopted_provider"], "muse")
        self.assertEqual(second["turns"][-1]["switch_count"], 0)
        self.assertEqual(len(gemini.calls), 1)
        # same conversation, same answers, and the rule the owner confirmed
        self.assertEqual(healthy_muse.calls[0]["conversation_id"], self.conversation)
        self.assertEqual(healthy_muse.calls[0]["qa"], gemini.calls[0]["qa"])
        self.assertEqual(second["answers"], first["answers"])
        # the provider shown on the screen follows the adopted answer
        self.assertEqual(
            self.store.conversation_state(self.conversation)["active_provider"], "muse")
        # the first turn's Gemini answer cannot be replaced by a late Muse answer
        first_turn = second["turns"][0]
        late = self.store.adopt_late_response(
            conversation_id=self.conversation, turn_id=first_turn["turn_id"],
            attempt_id=[a for a in first_turn["attempts"]
                        if a["provider"] == "muse"][0]["attempt_id"],
            client_request_id="p6d-late")
        self.assertEqual(late["late"]["status"], "refused")
        self.assertEqual(late["late"]["reason"], "stale_attempt")
        self.assertEqual(
            self.store.conversation_state(self.conversation)["turns"][0]["adopted_provider"],
            "gemini")

    def test_muse_pc_unreachable_uses_the_same_fallback_path(self):
        offline = RaisingAdapter("muse", MUSE_MODEL,
                                 ProviderTransportError("connection_refused"))
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p6d-turn-off",
            muse=offline, gemini=gemini)
        self.assertEqual(result["turns"][-1]["adopted_provider"], "gemini")
        self.assertEqual(result["turns"][-1]["switch_count"], 1)
        attempts = result["turns"][-1]["attempts"]
        self.assertEqual([a["slot"] for a in attempts], ["primary", "fallback"])
        self.assertEqual(attempts[0]["send_error"], "transport_error")
        self.assertEqual(attempts[0]["reason_code"], "connection_refused")
        # a row save and a confirmed rule keep working while a provider is away
        self.assertEqual(
            self.store.get_row("expense-demo-c3")["display_tab_id"], "trip-demo-b")

    def test_a_second_store_in_this_process_is_not_a_restart(self):
        """A new store in the same process keeps the pending turn.

        The previous version of this file treated a second store instance as a
        new process and expected the turn to be abandoned. That was wrong: a
        second connection in the same process, and any other process that is
        still running, still owns its turn. The real restart boundary with a
        real subprocess is in test_rule_process_ownership.py.
        """
        pending = SyntheticAdapter("muse", MUSE_MODEL, status="pending")
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p6d-pending",
            muse=pending, gemini=SyntheticAdapter("gemini", GEMINI_MODEL))
        turn = result["turns"][-1]
        self.assertEqual(turn["state"], "pending")

        self.store.close()
        same_process = type(self.store)(self.path)
        try:
            late = same_process.adopt_late_response(
                conversation_id=self.conversation, turn_id=turn["turn_id"],
                attempt_id=turn["attempts"][0]["attempt_id"],
                client_request_id="p6d-late-same-process")
            self.assertEqual(late["late"]["status"], "adopted")
            stored = [t for t in late["turns"]
                      if t["turn_id"] == turn["turn_id"]][0]
            self.assertEqual(stored["state"], "answered")
            self.assertEqual(stored["abandoned_reason"], "")
        finally:
            same_process.close()
            self.store = type(self.store)(self.path)

    def test_a_pending_turn_of_another_live_process_is_not_abandoned(self):
        """A turn owned by a process that is still running is left alone."""
        pending = SyntheticAdapter("muse", MUSE_MODEL, status="pending")
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p6d-pending-owner",
            muse=pending, gemini=SyntheticAdapter("gemini", GEMINI_MODEL))
        turn = result["turns"][-1]
        # hand the turn to a run id that is alive, this process, and inside its
        # lease window
        self.store.conn.execute(
            "INSERT OR REPLACE INTO rule_process_leases(run_id, pid, started_at,"
            " heartbeat_at) VALUES ('another-live-run', ?, '2020-01-01T00:00:00+00:00', ?)",
            (_PROCESS_PID, _utc_now()))
        self.store.conn.execute(
            "UPDATE rule_turns SET process_run_id='another-live-run' WHERE turn_id=?",
            (turn["turn_id"],))
        self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p6d-replay-live-owner")
        stored = [t for t in self.store.conversation_state(self.conversation)["turns"]
                  if t["turn_id"] == turn["turn_id"]][0]
        self.assertEqual(stored["state"], "pending")
        self.assertIsNone(stored["owner_review"])

    def test_a_live_process_keeps_its_pending_turn(self):
        pending = SyntheticAdapter("muse", MUSE_MODEL, status="pending")
        self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p6d-live-pending",
            muse=pending, gemini=SyntheticAdapter("gemini", GEMINI_MODEL))
        state = self.store.conversation_state(self.conversation)
        self.assertEqual(state["turns"][-1]["state"], "pending")
        self.assertEqual(state["turns"][-1]["state_label"], "응답 대기 중")

    def test_a_pending_answer_for_a_live_turn_is_adopted(self):
        pending = SyntheticAdapter("muse", MUSE_MODEL, status="pending")
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p6d-pending-2",
            muse=pending, gemini=SyntheticAdapter("gemini", GEMINI_MODEL))
        turn = result["turns"][-1]
        late = self.store.adopt_late_response(
            conversation_id=self.conversation, turn_id=turn["turn_id"],
            attempt_id=turn["attempts"][0]["attempt_id"],
            client_request_id="p6d-late-live")
        self.assertEqual(late["late"]["status"], "adopted")
        self.assertEqual(late["late"]["reason"], "accepted")
        self.assertEqual(
            [t for t in late["turns"] if t["turn_id"] == turn["turn_id"]][0]["state"],
            "answered")

    def test_a_late_answer_for_a_turn_that_never_persisted_is_recorded_as_refused(self):
        self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p6d-turn-known",
            muse=SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                  reason_code="auth_failed"),
            gemini=SyntheticAdapter("gemini", GEMINI_MODEL, status="failed",
                                    reason_code="auth_failed"))
        late = self.store.adopt_late_response(
            conversation_id=self.conversation, turn_id="turn-does-not-exist",
            attempt_id="attempt-does-not-exist", client_request_id="p6d-late-unknown")
        self.assertEqual(late["late"]["status"], "refused")
        self.assertEqual(late["late"]["reason"], "unknown_turn")

    def test_a_waiting_turn_refuses_a_late_answer(self):
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation, client_request_id="p6d-turn-waiting",
            muse=SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                  reason_code="service_error"),
            gemini=SyntheticAdapter("gemini", GEMINI_MODEL, status="failed",
                                    reason_code="service_error"))
        turn = result["turns"][-1]
        self.assertEqual(turn["state"], "waiting")
        late = self.store.adopt_late_response(
            conversation_id=self.conversation, turn_id=turn["turn_id"],
            attempt_id=turn["attempts"][-1]["attempt_id"],
            client_request_id="p6d-late-waiting")
        self.assertEqual(late["late"]["status"], "refused")
        self.assertEqual(late["late"]["reason"], "turn_already_concluded")


class PendingPolicyTests(unittest.TestCase):
    """A pending answer is neither a success nor a reason to switch."""

    def test_pending_waits_without_a_second_send(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="pending")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft={"item": "교통비"})
        outcome = run_turn(turn_id="t-pending", context={}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "pending")
        self.assertEqual(outcome.switch_count, 0)
        self.assertFalse(outcome.adopted)
        self.assertEqual(len(gemini.calls), 0)
        self.assertEqual(outcome.as_dict()["state_label"], "응답 대기 중")

    def test_a_later_turn_may_still_use_the_fallback_slot(self):
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft={"item": "교통비"})
        second = run_turn(turn_id="t-pending-2", context={},
                          muse=SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                                reason_code="auth_failed"),
                          gemini=gemini)
        self.assertEqual(second.provider, "gemini")
        self.assertEqual(second.switch_count, 1)


if __name__ == "__main__":
    unittest.main()
