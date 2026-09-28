"""Phase 6B provider-neutral dialog turn tests (synthetic adapters only).

Covers IMPLEMENTATION_PROMPT_WEB_LEDGER_APP 99~118 and PHASES Phase 6:
app-owned conversation, adapter injection, one Gemini switch on an explicit
Muse failure, attempt adoption against late or repeated answers, waiting on
total failure while row save and confirmed rules keep working, restart
restore, request idempotency, and the context allowlist.

No network, no key, no real provider call. The synthetic adapter reports
`is_real_call = False` and the tests assert that.
"""

import json
import tempfile
import unittest
from pathlib import Path

from webapp import ledger_board as board_mod
from webapp.dialog_turn import (
    ALLOWED_CONTEXT_FIELDS,
    EXCLUDED_CONTEXT_FIELDS,
    ProviderTransportError,
    SyntheticAdapter,
    build_context,
    build_qa,
    build_rule_view,
    guard_summary,
    run_turn,
)
from webapp.ledger_store import LedgerStore, SaveError

MUSE_MODEL = "opencode/muse-spark-1.3-contributor-free"
GEMINI_MODEL = "synthetic-gemini-placeholder"


def make_store():
    directory = tempfile.mkdtemp()
    path = Path(directory) / "webledger.sqlite"
    store = LedgerStore(path)
    return store, path


def learning_case(store, row_id="expense-demo-c3", request_id="p6b-case"):
    return store.save(
        row_id=row_id,
        expected_revision=store.get_row(row_id)["revision"],
        client_request_id=request_id,
        change_mode="rule_change",
        changes={"display_tab_id": "trip-demo-b"},
    )["learning_case_id"]


def valid_draft(case_id, item="교통비확인"):
    return {
        "learning_case_id": case_id,
        "conditions": {"merchant_normalized": "예시 이동"},
        "effects": {"item": item},
    }


def open_ready_dialog(store, case_id, request_id):
    """Open the dialog with its questions and no answer yet."""
    return store.open_rule_dialog(
        learning_case_id=case_id, draft=valid_draft(case_id),
        client_request_id=request_id)


class TurnPolicyTests(unittest.TestCase):
    """Pure policy, no store."""

    def test_muse_success_never_calls_gemini(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, draft={"item": "교통비"})
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL)
        outcome = run_turn(turn_id="t1", context={"row_id": "r"}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "answered")
        self.assertEqual(outcome.provider, "muse")
        self.assertEqual(outcome.switch_count, 0)
        self.assertEqual(len(gemini.calls), 0)
        self.assertEqual(len(muse.calls), 1)
        self.assertFalse(outcome.is_real_call)

    def test_explicit_failure_switches_to_gemini_once(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="connection_refused")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft={"item": "교통비"})
        outcome = run_turn(turn_id="t2", context={}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.provider, "gemini")
        self.assertEqual(outcome.switch_count, 1)
        self.assertEqual(len(gemini.calls), 1)
        self.assertEqual([a["slot"] for a in outcome.attempts], ["primary", "fallback"])
        self.assertEqual(outcome.as_dict()["fallback_notice"],
                         "Muse 연결 실패로 Gemini fallback 사용 중")

    def test_third_attempt_is_impossible(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="timeout")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, status="failed",
                                  reason_code="auth_failed")
        outcome = run_turn(turn_id="t3", context={}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "waiting")
        self.assertIsNone(outcome.adopted_attempt_id)
        self.assertEqual(len(outcome.attempts), 2)
        self.assertEqual(len(muse.calls) + len(gemini.calls), 2)

    def test_free_quota_exhausted_waits_without_extra_switch(self):
        # DETAILED_CONTRACT 7: a spent free quota parks the dialogue and keeps
        # the row, the draft and the answers. It must not spend the one allowed
        # switch, because Gemini is billed under the same quota and a second
        # attempt would turn a wait into a wrong answer.
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="free_quota_exhausted")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, status="failed",
                                  reason_code="free_quota_exhausted")
        outcome = run_turn(turn_id="t4", context={}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "waiting")
        self.assertEqual(outcome.switch_count, 0)
        self.assertEqual(outcome.reason_code, "free_quota_exhausted")
        self.assertEqual(len(outcome.attempts), 1)
        # the fallback was not even asked
        self.assertEqual(gemini.calls, [])

    def test_a_healthy_fallback_is_still_not_used_after_a_quota_wait(self):
        # The point of the rule above: the turn waits rather than adopting an
        # answer the operator's own quota decision was meant to pause.
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="free_quota_exhausted")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, status="ok",
                                  draft={"conditions": {"card_kind": "체크"}})
        outcome = run_turn(turn_id="t4b", context={}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "waiting")
        self.assertEqual(outcome.switch_count, 0)
        self.assertIsNone(outcome.adopted_attempt_id)
        self.assertEqual(gemini.calls, [])

    def test_an_exhausted_budget_also_waits_without_switching(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="budget_exhausted")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, status="ok", draft={})
        outcome = run_turn(turn_id="t4c", context={}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "waiting")
        self.assertEqual(outcome.switch_count, 0)
        self.assertEqual(gemini.calls, [])

    def test_missing_gemini_leaves_the_turn_waiting(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="service_error")
        outcome = run_turn(turn_id="t5", context={}, muse=muse, gemini=None)
        self.assertEqual(outcome.state, "waiting")
        self.assertEqual(len(outcome.attempts), 1)

    def test_attempt_ids_are_unique_and_ordered(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="rate_limited")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, status="ok")
        outcome = run_turn(turn_id="t6", context={}, muse=muse, gemini=gemini)
        ids = [a["attempt_id"] for a in outcome.attempts]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([a["seq"] for a in outcome.attempts], [1, 2])
        self.assertTrue(outcome.adopted_attempt_id in ids)

    def test_context_uses_the_allowlist_only(self):
        row = {
            "row_id": "expense-demo-c3", "row_kind": "expense", "revision": 2,
            "item": "교통비", "source_merchant": "  AGODA   TEST ", "event_kind": "purchase",
            "card_kind": "K2", "amount_krw": 123456, "occurred_on": "2026-04-11",
            "display_tab_id": "trip-demo-b",
            "customer_name": "김민수", "rsv": "RSV-SECRET-1234",
            "operator_note": "비밀 메모", "memo": "메일 본문",
            "email": "a@b.c", "api_key": "SECRET-KEY",
        }
        ctx = build_context(conversation_id="conv-1", turn_id="turn-1", row=row,
                            rule={"rule_id": "rule-1", "version": 2},
                            answers={"rule_kind": "repeatable"},
                            handoff_summary="요약")
        self.assertEqual(set(ctx), set(ALLOWED_CONTEXT_FIELDS))
        for field in EXCLUDED_CONTEXT_FIELDS:
            self.assertNotIn(field, ctx)
        blob = " ".join(str(v) for v in ctx.values())
        for secret in ("김민수", "RSV-SECRET-1234", "비밀 메모", "메일 본문",
                       "a@b.c", "SECRET-KEY"):
            self.assertNotIn(secret, blob)
        self.assertEqual(ctx["merchant_normalized"], "agoda test")
        self.assertEqual(ctx["amount_bucket_krw"], 100000)
        self.assertEqual(ctx["occurred_month"], "2026-04")
        self.assertEqual(ctx["row_revision"], 2)
        self.assertEqual(ctx["rule_version"], 2)


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.store, self.path = make_store()
        self.case = learning_case(self.store)
        self.conversation = self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p6b-open")

    def tearDown(self):
        self.store.close()

    def test_conversation_is_app_owned_and_reopens_without_a_new_id(self):
        state = self.conversation_state = self.store.conversation_state(
            self.conversation["conversation_id"])
        self.assertEqual(state["conversation_id"], f"conv-{self.case}")
        self.assertEqual(state["case_id"], self.case)
        self.assertEqual(state["state"], "open")
        self.assertEqual(state["turn_count"], 0)
        again = self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p6b-open-again")
        self.assertEqual(again["conversation_id"], state["conversation_id"])

    def test_conversation_open_is_idempotent_per_request(self):
        first = self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p6b-open-dup")
        second = self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p6b-open-dup")
        self.assertEqual(first["conversation_id"], second["conversation_id"])
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM rule_conversations").fetchone()[0], 1)

    def test_answers_and_rule_version_survive_in_the_conversation(self):
        opened = self.store.open_rule_dialog(
            learning_case_id=self.case, draft=valid_draft(self.case),
            client_request_id="p6b-dialog")
        question = opened["questions"][0]["question_id"]
        self.store.answer_rule_question(
            question_id=question, answer="repeatable",
            expected_row_revision=opened["row_revision"],
            client_request_id="p6b-answer")
        rule = self.store.create_rule_draft(
            draft=valid_draft(self.case), client_request_id="p6b-rule")
        self.store.conn.execute(
            "UPDATE rule_conversations SET rule_id=?, rule_version=?,"
            " handoff_summary=? WHERE conversation_id=?",
            (rule["rule_id"], rule["version"], "이전 대화 요약",
             self.conversation["conversation_id"]))
        self.store.conn.commit()
        state = self.store.conversation_state(self.conversation["conversation_id"])
        self.assertEqual(state["answers"].get("rule_kind"), "repeatable")
        self.assertEqual(state["rule_id"], rule["rule_id"])
        self.assertEqual(state["rule_version"], rule["version"])
        self.assertEqual(state["handoff_summary"], "이전 대화 요약")
        self.assertEqual(state["open_questions"],
                         ["evidence_basis", "event_year", "period"])

    def test_turn_stores_every_attempt_and_adopts_one(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="connection_refused")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL,
                                  draft=valid_draft(self.case), summary="요약 내용")
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-1", muse=muse, gemini=gemini)
        turn = result["turn"]
        self.assertEqual(turn["state"], "answered")
        self.assertEqual(turn["adopted_provider"], "gemini")
        self.assertEqual(turn["switch_count"], 1)
        self.assertEqual([a["slot"] for a in turn["attempts"]], ["primary", "fallback"])
        self.assertEqual([a["adopted"] for a in turn["attempts"]], [False, True])
        self.assertFalse(result["is_real_call"])
        self.assertEqual(result["notice"], "Muse 연결 실패로 Gemini fallback 사용 중")
        self.assertEqual(result["draft"]["effects"], {"item": "교통비확인"})
        self.assertEqual(self.store.conversation_state(
            self.conversation["conversation_id"])["active_provider"], "gemini")

    def test_invalid_model_draft_is_refused_and_writes_nothing(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, draft={
            "conditions": {"merchant_normalized": "예시 이동"},
            "effects": {"amount_krw": 1}})
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-bad", muse=muse)
        self.assertEqual(result["draft"], {})
        self.assertEqual(result["draft_error"]["code"], "RULE_EFFECT_FORBIDDEN")
        self.assertEqual(self.store.conversation_state(
            self.conversation["conversation_id"])["turns"][-1]["draft"]["rule"], {})
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM classification_rules").fetchone()[0], 0)
        self.assertEqual(self.store.get_row("expense-demo-c3")["display_tab_id"],
                         "trip-demo-b")

    def test_model_draft_never_writes_the_ledger(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, draft=valid_draft(self.case))
        before = self.store.get_row("expense-demo-c3")
        self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-nowrite", muse=muse)
        after = self.store.get_row("expense-demo-c3")
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["item"], before["item"])
        self.assertEqual(after["display_tab_id"], before["display_tab_id"])
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM board_revisions WHERE row_id=?",
            (before["row_id"],)).fetchone()[0], 1)

    def test_no_provider_or_key_is_stored(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, draft=valid_draft(self.case),
                                summary="키 없는 요약")
        self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-key", muse=muse)
        tables = [r[0] for r in self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        for table in tables:
            cols = [r[1] for r in self.store.conn.execute(
                f"PRAGMA table_info({table})").fetchall()]
            for col in cols:
                lowered = col.lower()
                for marker in ("api_key", "gemini_key", "secret", "token", "password"):
                    self.assertNotIn(marker, lowered,
                                     f"{table}.{col} looks like a secret column")
        for table in ("rule_turns", "rule_turn_attempts", "rule_conversations"):
            for row in self.store.conn.execute(f"SELECT * FROM {table}").fetchall():
                blob = " ".join(str(v) for v in row)
                self.assertNotIn("SECRET", blob)
                self.assertNotIn("api_key", blob)

    def test_late_muse_response_cannot_overwrite_the_adopted_gemini(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="connection_refused")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-late", muse=muse, gemini=gemini)
        turn = result["turn"]
        muse_attempt = [a for a in turn["attempts"] if a["provider"] == "muse"][0]
        adopted = turn["adopted_attempt_id"]
        late = self.store.adopt_late_response(
            conversation_id=self.conversation["conversation_id"],
            turn_id=turn["turn_id"], attempt_id=muse_attempt["attempt_id"],
            client_request_id="p6b-late-1")
        self.assertEqual(late["late"]["status"], "refused")
        self.assertEqual(late["late"]["reason"], "stale_attempt")
        self.assertEqual(late["turns"][-1]["adopted_attempt_id"], adopted)

    def test_repeated_response_for_the_adopted_attempt_is_idempotent(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, draft=valid_draft(self.case))
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-adopt", muse=muse)
        turn = result["turn"]
        again = self.store.adopt_late_response(
            conversation_id=self.conversation["conversation_id"],
            turn_id=turn["turn_id"], attempt_id=turn["adopted_attempt_id"],
            client_request_id="p6b-late-adopted")
        self.assertEqual(again["late"]["reason"], "already_adopted")
        self.assertEqual(self.store.conversation_state(
            self.conversation["conversation_id"])["turns"][-1]["adopted_attempt_id"],
            turn["adopted_attempt_id"])

    def test_turn_request_retransmission_is_idempotent(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="timeout")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
        first = self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-retry", muse=muse, gemini=gemini)
        self.assertEqual(len(gemini.calls), 1)
        second = self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-retry", muse=muse, gemini=gemini)
        self.assertEqual(second["turn"]["turn_id"], first["turn"]["turn_id"])
        self.assertEqual(len(gemini.calls), 1)
        self.assertEqual(self.store.conversation_state(
            self.conversation["conversation_id"])["turn_count"], 1)
        with self.assertRaises(SaveError) as caught:
            self.store.run_dialog_turn(
                conversation_id="conv-different",
                client_request_id="p6b-turn-retry", muse=muse, gemini=gemini)
        self.assertEqual(caught.exception.code, "REQUEST_ID_REUSED")

    def test_context_sent_to_the_provider_is_allowlisted(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, draft=valid_draft(self.case))
        self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-context", muse=muse)
        request = muse.calls[0]
        self.assertEqual(set(request) - {"attempt_id", "slot"}, set(ALLOWED_CONTEXT_FIELDS))
        self.assertEqual(request["row_id"], "expense-demo-c3")
        self.assertEqual(request["conversation_id"], self.conversation["conversation_id"])

    def test_waiting_turn_keeps_row_save_and_confirmed_rules_working(self):
        rule = self.store.create_rule_draft(
            draft={"learning_case_id": self.case,
                   "conditions": {"merchant_normalized": "agoda test",
                                  "transaction_direction": "purchase"},
                   "effects": {"display_tab_id": "trip-demo-b"},
                   "scope": {"trip_id": "trip-demo-b", "event_year": 2026,
                             "applicability": "future"}},
            client_request_id="p6b-wait-rule")
        preview = self.store.preview_rule(
            rule_id=rule["rule_id"], apply_existing=False, apply_future=True)
        self.store.apply_rule(
            preview_id=preview["preview_id"], apply_existing=False, apply_future=True,
            client_request_id="p6b-wait-apply")
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="free_quota_exhausted")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, status="failed",
                                  reason_code="free_quota_exhausted")
        waiting = self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-wait", muse=muse, gemini=gemini)
        self.assertEqual(waiting["turn"]["state"], "waiting")
        self.assertIsNone(waiting["turn"]["adopted_attempt_id"])
        # 행 저장은 그대로 동작한다
        saved = self.store.save(
            row_id="expense-demo-c1",
            expected_revision=self.store.get_row("expense-demo-c1")["revision"],
            client_request_id="p6b-wait-save", change_mode="exception",
            changes={"operator_note": "대화 대기 중에도 저장"})
        self.assertEqual(saved["outcome"], "saved")
        # 이미 확정된 규칙은 계속 실행된다
        from webapp.card_import import CardImporter

        importer = CardImporter(self.store.conn, self.store)
        body = ("occurred_on,merchant,amount_krw,currency,card_last4,approval_no,"
                "cancel_flag,suggested_tab,memo,card_kind\n"
                "2026-04-09,AGODA TEST,100000,KRW,1111,WB1,,,,K1\n").encode("utf-8")
        received = importer.receive(body, "p6b.csv")
        importer.process_to_completion(received["batch_id"])
        row_id = self.store.conn.execute(
            "SELECT row_id FROM board_rows WHERE payload_json LIKE '%AGODA TEST%'"
        ).fetchone()[0]
        self.assertEqual(self.store.get_row(row_id)["display_tab_id"], "trip-demo-b")
        self.assertEqual(self.store.get_rule(rule["rule_id"])["status"], "active")

    def test_restart_restores_the_conversation_context(self):
        muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                reason_code="service_error")
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL,
                                  draft=valid_draft(self.case), summary="재개 요약")
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6b-turn-restart", muse=muse, gemini=gemini)
        conversation_id = self.conversation["conversation_id"]
        self.store.close()
        reopened = LedgerStore(self.path)
        try:
            state = reopened.conversation_state(conversation_id)
            self.assertEqual(state["turn_count"], 1)
            self.assertEqual(state["active_provider"], "gemini")
            self.assertEqual(state["handoff_summary"], "재개 요약")
            self.assertEqual(state["turns"][0]["turn_id"], result["turn"]["turn_id"])
            self.assertEqual([a["slot"] for a in state["turns"][0]["attempts"]],
                             ["primary", "fallback"])
            self.assertFalse(state["turns"][0]["is_real_call"])
            self.assertEqual(state["row_id"], "expense-demo-c3")
            second_turn = reopened.run_dialog_turn(
                conversation_id=conversation_id, client_request_id="p6b-turn-after-restart",
                muse=SyntheticAdapter("muse", MUSE_MODEL, status="ok"))
            self.assertEqual(second_turn["turn"]["turn_id"],
                             f"turn-{conversation_id}-002")
        finally:
            reopened.close()



class RaisingAdapter(SyntheticAdapter):
    """Adapter whose send raises, to exercise the failure classification."""

    def __init__(self, name, model_id, exc, calls=None):
        super().__init__(name, model_id, calls=calls)
        self.exc = exc

    def send(self, request):
        self.calls.append(request)
        raise self.exc


class ContextMeaningTests(unittest.TestCase):
    """The provider must receive the question and answer meaning, not keys only."""

    def test_qa_carries_verified_answers(self):
        qa = build_qa([
            {"question_key": "rule_kind", "options": ["this_only", "repeatable"],
             "answer": "repeatable"},
            {"question_key": "evidence_basis", "options": ["schedule_or_booking"],
             "answer": "schedule_or_booking"},
        ])
        self.assertEqual(qa, [
            {"question_key": "evidence_basis", "answer": "schedule_or_booking",
             "verified": True},
            {"question_key": "rule_kind", "answer": "repeatable", "verified": True},
        ])

    def test_unrecognised_free_text_is_not_forwarded(self):
        qa = build_qa([
            {"question_key": "rule_kind", "options": ["this_only", "repeatable"],
             "answer": "이번 건만요 마음대로 적어봄"},
        ])
        self.assertEqual(qa, [{"question_key": "rule_kind", "answer": None,
                               "verified": False, "unrecognised": True}])
        self.assertNotIn("마음대로", str(qa))

    def test_same_key_different_answer_changes_the_meaning_sent(self):
        first = build_qa([{"question_key": "rule_kind",
                           "options": ["this_only", "repeatable"],
                           "answer": "repeatable"}])
        second = build_qa([{"question_key": "rule_kind",
                            "options": ["this_only", "repeatable"],
                            "answer": "this_only"}])
        self.assertNotEqual(first, second)
        self.assertEqual(first[0]["answer"], "repeatable")
        self.assertEqual(second[0]["answer"], "this_only")

    def test_rule_view_keeps_the_structured_draft(self):
        view = build_rule_view({
            "rule_id": "rule-1", "version": 2, "base_rule_version": 1,
            "status": "active", "rule_hash": "abc",
            "rule": {"conditions": {"merchant_normalized": {"op": "eq", "value": "x"}},
                     "effects": {"item": "교통비"},
                     "scope": {"trip_id": "trip-demo-b", "event_year": 2026,
                               "applicability": "existing_and_future"},
                     "optional_conditions": {}},
        })
        self.assertEqual(view["version"], 2)
        self.assertEqual(view["base_rule_version"], 1)
        self.assertEqual(view["effects"], {"item": "교통비"})
        self.assertEqual(view["scope"]["applicability"], "existing_and_future")
        self.assertEqual(view["rule_hash"], "abc")

    def test_handoff_summary_is_guarded_and_digested(self):
        ok = guard_summary("이번 거래는 반복 규칙으로 정리")
        self.assertEqual(ok["text"], "이번 거래는 반복 규칙으로 정리")
        self.assertTrue(ok["sha256"])
        secret = guard_summary("api_key=SK-1234567890abcdef")
        self.assertIsNone(secret["text"])
        self.assertEqual(secret["reason"], "unverified_value")
        source = guard_summary("예약번호 RSV-20260408-HOTEL-7781-KR")
        self.assertIsNone(source["text"])
        self.assertEqual(source["reason"], "unverified_value")
        long_text = guard_summary("가" * 500)
        self.assertIsNone(long_text["text"])
        self.assertEqual(long_text["reason"], "length")
        empty = guard_summary("")
        self.assertFalse(empty["present"])

    def test_context_contains_qa_rule_and_handoff(self):
        ctx = build_context(
            conversation_id="conv-1", turn_id="turn-1",
            row={"row_id": "r1", "revision": 3, "item": "교통비"},
            rule={"rule_id": "rule-1", "version": 2, "status": "draft",
                  "rule": {"conditions": {}, "effects": {"item": "교통비"},
                           "scope": {}}},
            qa=[{"question_key": "rule_kind", "options": ["this_only", "repeatable"],
                 "answer": "repeatable"}],
            handoff_summary="요약")
        self.assertEqual(set(ctx), set(ALLOWED_CONTEXT_FIELDS))
        self.assertEqual(ctx["qa"][0]["answer"], "repeatable")
        self.assertEqual(ctx["rule"]["version"], 2)
        self.assertEqual(ctx["handoff"]["text"], "요약")
        self.assertNotIn("answered_keys", ctx)


class SendFailureTests(unittest.TestCase):
    def test_transport_error_switches_once_to_gemini(self):
        muse = RaisingAdapter("muse", MUSE_MODEL,
                              ProviderTransportError("connection_refused"))
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft={"item": "교통비"})
        outcome = run_turn(turn_id="e1", context={}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "answered")
        self.assertEqual(outcome.provider, "gemini")
        self.assertEqual(outcome.switch_count, 1)
        self.assertEqual(outcome.attempts[0]["reason_code"], "connection_refused")
        self.assertEqual(outcome.attempts[0]["send_error"], "transport_error")

    def test_timeout_error_switches_once(self):
        muse = RaisingAdapter("muse", MUSE_MODEL, TimeoutError())
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft={})
        outcome = run_turn(turn_id="e2", context={}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.provider, "gemini")
        self.assertEqual(outcome.attempts[0]["reason_code"], "timeout")

    def test_connection_error_switches_once(self):
        muse = RaisingAdapter("muse", MUSE_MODEL, ConnectionRefusedError("refused"))
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft={})
        outcome = run_turn(turn_id="e3", context={}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.attempts[0]["reason_code"], "connection_refused")

    def test_both_raise_leaves_the_turn_waiting(self):
        muse = RaisingAdapter("muse", MUSE_MODEL,
                              ProviderTransportError("timeout"))
        gemini = RaisingAdapter("gemini", GEMINI_MODEL, RuntimeError("bug"))
        outcome = run_turn(turn_id="e4", context={}, muse=muse, gemini=gemini)
        self.assertEqual(outcome.state, "waiting")
        self.assertIsNone(outcome.adopted_attempt_id)
        self.assertEqual(len(outcome.attempts), 2)
        self.assertEqual(outcome.reason_code, "adapter_error")

    def test_programming_error_is_not_a_success_and_leaks_nothing(self):
        muse = RaisingAdapter("muse", MUSE_MODEL,
                              RuntimeError("key=SECRET-1234 at https://x?api_key=SECRET"))
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft={"item": "x"})
        outcome = run_turn(turn_id="e5", context={}, muse=muse, gemini=gemini)
        # adapter_error is not an explicit failure, so no switch is attempted
        self.assertEqual(outcome.state, "waiting")
        self.assertEqual(outcome.reason_code, "adapter_error")
        self.assertEqual(outcome.attempts[0]["reason_code"], "adapter_error")
        self.assertEqual(outcome.attempts[0]["send_error"], "RuntimeError")
        self.assertEqual(len(gemini.calls), 0)
        self.assertNotIn("SECRET", str(outcome.as_dict()))
        self.assertNotIn("https://x", str(outcome.as_dict()))


class ConversationMeaningTests(unittest.TestCase):
    """The stored meaning must reach both providers and survive a restart."""

    def setUp(self):
        self.store, self.path = make_store()
        self.case = learning_case(self.store)
        self.conversation = self.store.open_conversation(
            learning_case_id=self.case, client_request_id="p6c-open")

    def tearDown(self):
        self.store.close()

    def _answer(self, key, value, request_id):
        state = self.store.rule_dialog_state(self.case)
        question = [q for q in state["questions"] if q["question_key"] == key][0]
        return self.store.answer_rule_question(
            question_id=question["question_id"], answer=value,
            expected_row_revision=state["row_revision"],
            client_request_id=request_id)

    def test_qa_reaches_muse_and_gemini_with_the_same_meaning(self):
        self.store.open_rule_dialog(
            learning_case_id=self.case, draft=valid_draft(self.case),
            client_request_id="p6c-dialog")
        self._answer("evidence_basis", "merchant_service", "p6c-answer-1")
        muse = RaisingAdapter("muse", MUSE_MODEL,
                              ProviderTransportError("connection_refused"))
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
        self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6c-turn", muse=muse, gemini=gemini)
        self.assertEqual(len(muse.calls), 1)
        self.assertEqual(len(gemini.calls), 1)
        muse_qa = muse.calls[0]["qa"]
        gemini_qa = gemini.calls[0]["qa"]
        self.assertEqual(muse_qa, gemini_qa)
        basis = [q for q in gemini_qa if q["question_key"] == "evidence_basis"][0]
        self.assertEqual(basis["answer"], "merchant_service")
        self.assertTrue(basis["verified"])
        self.assertIn("conversation_id", gemini.calls[0])
        self.assertEqual(gemini.calls[0]["handoff"]["present"], False)

    def test_changing_the_answer_changes_what_the_provider_receives(self):
        self.store.open_rule_dialog(
            learning_case_id=self.case, draft=valid_draft(self.case),
            client_request_id="p6c-dialog-2")
        self._answer("evidence_basis", "schedule_or_booking", "p6c-answer-2")
        first = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
        self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6c-turn-2",
            muse=SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                  reason_code="connection_refused"),
            gemini=first)
        got_first = [q for q in first.calls[0]["qa"]
                     if q["question_key"] == "evidence_basis"][0]
        self.assertEqual(got_first["answer"], "schedule_or_booking")
        self._answer("evidence_basis", "merchant_service", "p6c-answer-3")
        second = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
        self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6c-turn-3",
            muse=SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                  reason_code="connection_refused"),
            gemini=second)
        got_second = [q for q in second.calls[0]["qa"]
                      if q["question_key"] == "evidence_basis"][0]
        self.assertEqual(got_second["answer"], "merchant_service")
        self.assertNotEqual(got_first, got_second)

    def test_meaning_and_rule_survive_a_restart(self):
        self.store.open_rule_dialog(
            learning_case_id=self.case, draft=valid_draft(self.case),
            client_request_id="p6c-dialog-3")
        self._answer("rule_kind", "repeatable", "p6c-answer-4")
        rule = self.store.create_rule_draft(
            draft=valid_draft(self.case), client_request_id="p6c-rule-3")
        self.store.conn.execute(
            "UPDATE rule_conversations SET rule_id=?, rule_version=?,"
            " handoff_summary=? WHERE conversation_id=?",
            (rule["rule_id"], rule["version"], "재개용 요약",
             self.conversation["conversation_id"]))
        self.store.conn.commit()
        self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6c-turn-4",
            muse=SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                  reason_code="connection_refused"),
            gemini=SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case)))
        conversation_id = self.conversation["conversation_id"]
        self.store.close()
        reopened = LedgerStore(self.path)
        try:
            after = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
            reopened.run_dialog_turn(
                conversation_id=conversation_id, client_request_id="p6c-turn-5",
                muse=SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                      reason_code="connection_refused"),
                gemini=after)
            sent = after.calls[0]
            rule_kind = [q for q in sent["qa"] if q["question_key"] == "rule_kind"][0]
            self.assertEqual(rule_kind["answer"], "repeatable")
            self.assertEqual(sent["rule"]["rule_id"], rule["rule_id"])
            self.assertEqual(sent["rule"]["version"], rule["version"])
            self.assertEqual(sent["rule"]["effects"], {"item": "교통비확인"})
            self.assertEqual(sent["handoff"]["text"], "재개용 요약")
            self.assertTrue(sent["handoff"]["sha256"])
        finally:
            reopened.close()

    def test_send_error_is_recorded_without_leaking(self):
        muse = RaisingAdapter("muse", MUSE_MODEL,
                              RuntimeError("key=SECRET-9999"))
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6c-turn-6", muse=muse, gemini=gemini)
        turn = result["turn"]
        self.assertEqual(turn["state"], "waiting")
        self.assertEqual(turn["reason_code"], "adapter_error")
        self.assertEqual(turn["attempts"][0]["send_error"], "RuntimeError")
        blob = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("SECRET-9999", blob)
        self.assertEqual(len(gemini.calls), 0)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM classification_rules").fetchone()[0], 0)

    def test_transport_error_recorded_in_the_turn(self):
        muse = RaisingAdapter("muse", MUSE_MODEL,
                              ProviderTransportError("timeout"))
        gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
        result = self.store.run_dialog_turn(
            conversation_id=self.conversation["conversation_id"],
            client_request_id="p6c-turn-7", muse=muse, gemini=gemini)
        turn = result["turn"]
        self.assertEqual(turn["state"], "answered")
        self.assertEqual(turn["attempts"][0]["reason_code"], "timeout")
        self.assertEqual(turn["attempts"][0]["send_error"], "transport_error")
        self.assertEqual(turn["attempts"][1]["provider"], "gemini")

class ConversationApiTests(unittest.TestCase):
    def setUp(self):
        import os
        import threading

        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "p6b.sqlite")
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        board_mod.bind_store(self.store)
        self.case = learning_case(self.store)
        self.server = board_mod.serve(port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                     reason_code="connection_refused")
        self.gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft=valid_draft(self.case))
        board_mod.bind_dialog_adapters(muse=self.muse, gemini=self.gemini)

    def tearDown(self):
        import os

        worker = getattr(self.server, "card_worker", None)
        if worker is not None:
            worker.stop(timeout=5)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_dialog_adapters(None, None)
        board_mod.bind_store(None)
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
        body.setdefault("csrf", board_mod.CSRF_TOKEN)
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def _get(self, path):
        import json
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_conversation_flow_over_http(self):
        status, conversation = self._post("/api/classification/conversation/open", {
            "client_request_id": "p6b-api-open", "learning_case_id": self.case})
        self.assertEqual(status, 200)
        conversation_id = conversation["conversation_id"]
        status, turn = self._post("/api/classification/conversation/turn", {
            "client_request_id": "p6b-api-turn", "conversation_id": conversation_id,
            "provider": "gemini", "gemini_key": "SECRET-KEY-IN-BODY"})
        self.assertEqual(status, 200)
        self.assertEqual(turn["turn"]["adopted_provider"], "gemini")
        self.assertEqual(turn["notice"], "Muse 연결 실패로 Gemini fallback 사용 중")
        self.assertFalse(turn["is_real_call"])
        status, state = self._get(f"/api/classification/conversation?conversation_id={conversation_id}")
        self.assertEqual(status, 200)
        self.assertEqual(state["turn_count"], 1)
        self.assertEqual(state["active_provider"], "gemini")
        self.assertNotIn("SECRET-KEY-IN-BODY", json.dumps(state, ensure_ascii=False))
        self.assertIn("excluded_context_fields", state)
        self.assertEqual(len(self.muse.calls), 1)
        self.assertEqual(len(self.gemini.calls), 1)

    def test_request_body_cannot_pick_a_provider(self):
        _status, conversation = self._post("/api/classification/conversation/open", {
            "client_request_id": "p6b-api-open-2", "learning_case_id": self.case})
        _status, turn = self._post("/api/classification/conversation/turn", {
            "client_request_id": "p6b-api-turn-2",
            "conversation_id": conversation["conversation_id"],
            "muse": False, "provider": "gemini", "slot": "fallback"})
        self.assertEqual(turn["turn"]["attempts"][0]["provider"], "muse")
        self.assertEqual(turn["turn"]["attempts"][0]["slot"], "primary")

    def test_turn_without_bound_providers_waits(self):
        board_mod.bind_dialog_adapters(None, None)
        _status, conversation = self._post("/api/classification/conversation/open", {
            "client_request_id": "p6b-api-open-3", "learning_case_id": self.case})
        status, turn = self._post("/api/classification/conversation/turn", {
            "client_request_id": "p6b-api-turn-3",
            "conversation_id": conversation["conversation_id"]})
        self.assertEqual(status, 200)
        self.assertEqual(turn["turn"]["state"], "waiting")
        self.assertEqual(turn["turn"]["attempts"], [])
        self.assertIsNone(turn["turn"]["adopted_attempt_id"])
