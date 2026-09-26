"""Phase 6C minimal rule dialog screen tests (real clicks, synthetic mode).

Drives the existing functional HTML with real clicks: rule_change save,
question and answer, synthetic turn, draft confirm, impact preview with
independent existing/future scope, explicit apply, close and resume, stale
preview, double click, and the memo-only case that must not open a dialog.
No network, no key, no real provider call.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from webapp import ledger_board as board_mod
from webapp.dialog_turn import SyntheticAdapter
from webapp.ledger_store import LedgerStore

MUSE_MODEL = "opencode/muse-spark-1.3-contributor-free"
GEMINI_MODEL = "synthetic-gemini-placeholder"


def overflow(page):
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")


def inner_overflow(page, selector):
    return page.eval_on_selector(selector, "e=>e.scrollWidth-e.clientWidth")


class RuleDialogScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "screen.sqlite")
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.muse = SyntheticAdapter("muse", MUSE_MODEL, status="failed",
                                     reason_code="connection_refused")
        self.gemini = SyntheticAdapter("gemini", GEMINI_MODEL, draft={
            "conditions": {"merchant_normalized": "예시 숙소"},
            "effects": {"display_tab_id": "trip-demo-b"},
            "scope": {"trip_id": "trip-demo-b", "event_year": 2026,
                      "applicability": "existing_and_future"},
        }, summary="합성 요약")
        board_mod.bind_dialog_adapters(muse=self.muse, gemini=self.gemini)

    def tearDown(self):
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

    # ---------------------------------------------------------------- helpers
    def _page(self, playwright, width, height):
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        return browser, page

    def _save_row(self, page, row_id, revision, changes, change_mode, request_id):
        page.goto(f"http://127.0.0.1:{self.port}/row?id={row_id}&edit=1")
        # the existing form keeps client_request_id in a hidden input
        page.eval_on_selector(
            "input[name='client_request_id']",
            "(el, value) => { el.value = value; }", request_id)
        page.select_option("select[name='change_mode']", change_mode)
        for field, value in changes.items():
            selector = f"input[name='{field}']"
            visible = page.locator(f"{selector}:visible")
            if visible.count():
                visible.fill(value)
            else:
                page.select_option(f"select[name='{field}']", value)
        page.click("form button[type='submit']")
        page.wait_for_load_state()

    def _open_dialog(self, page):
        page.goto(f"http://127.0.0.1:{self.port}/row?id=expense-demo-c1")
        self.assertIn("규칙 대화 열기", page.inner_text("#main, .sect, body"))
        page.click("text=규칙 대화 열기")
        page.wait_for_load_state()

    def _case_id(self, page):
        return page.evaluate("new URL(location.href).searchParams.get('case')")

    # ------------------------------------------------------------------ tests
    def test_full_flow_at_1440(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page = self._page(p, 1440, 900)
            try:
                # 1. rule_change save creates the learning case
                self._save_row(page, "expense-demo-c1", 1,
                               {"display_tab_id": "trip-demo-b"}, "rule_change",
                               "screen-save-1")
                case = self.store.conn.execute(
                    "SELECT case_id FROM board_learning_cases WHERE row_id=?",
                    ("expense-demo-c1",)).fetchone()[0]
                self.assertIsNotNone(case)

                # 2. the row page links into the dialog
                self._open_dialog(page)
                self.assertEqual(self._case_id(page), case)
                self.assertIn("합성 모드", page.inner_text("body"))
                self.assertNotIn("AI 연결됨", page.inner_text("body"))
                self.assertEqual(overflow(page) <= 0, True)

                # 3. free text evidence is stored as written
                page.fill("input[name='note']", "이번 거래는 같은 가맹점 반복이라 봅니다")
                page.click("text=근거 저장")
                page.wait_for_load_state()
                self.assertIn("근거 설명을 저장했습니다", page.inner_text("body"))
                self.assertEqual(page.input_value("input[name='note']"),
                                 "이번 거래는 같은 가맹점 반복이라 봅니다")
                stored = self.store.rule_dialog_state(case)
                self.assertEqual(stored["draft"]["note"],
                                 "이번 거래는 같은 가맹점 반복이라 봅니다")

                # 4. open the dialog state so questions exist, then answer one
                self.store.open_rule_dialog(
                    learning_case_id=case,
                    draft={"conditions": {"merchant_normalized": "예시 숙소"},
                           "effects": {"display_tab_id": "trip-demo-b"},
                           "scope": {"trip_id": "trip-demo-b", "event_year": 2026,
                                     "applicability": "existing_and_future"}},
                    client_request_id="screen-dialog")
                page.goto(f"http://127.0.0.1:{self.port}/rules?case={case}")
                prompts = [q["prompt"] for q in self.store.rule_dialog_state(case)["questions"]]
                self.assertTrue(prompts)
                for prompt in prompts:
                    self.assertIn(prompt, page.inner_text("body"))
                self.assertEqual([q["question_key"] for q in
                                  self.store.conversation_qa(case)][:2],
                                 ["rule_kind", "evidence_basis"])
                self.assertLessEqual(page.locator("form[action='/api/classification/dialog/answer']").count(), 5)
                page.check("input[value='repeatable']")
                page.click("text=답변 저장")
                page.wait_for_load_state()
                self.assertIn("답변을 저장했습니다", page.inner_text("body"))
                self.assertEqual(self.store.conversation_qa(case)[0]["answer"],
                                 "repeatable")

                # 5. synthetic turn with the fallback notice
                page.click("text=규칙 초안 요청 (합성 턴)")
                page.wait_for_load_state()
                self.assertIn("초안을 받았습니다", page.inner_text("body"))
                self.assertIn("gemini", page.inner_text("body"))
                self.assertIn("전환 1회", page.inner_text("body"))
                self.assertEqual(len(self.muse.calls), 1)
                self.assertEqual(len(self.gemini.calls), 1)

                # 6. confirm the draft as a rule
                page.click("text=초안 저장")
                page.wait_for_load_state()
                self.assertIn("규칙 초안을 저장했습니다", page.inner_text("body"))
                rule = self.store.get_rule(
                    self.store.conversation_for_case(case)["rule_id"])
                self.assertEqual(rule["status"], "draft")
                self.assertFalse(rule["apply_existing"])
                self.assertFalse(rule["apply_future"])

                # 7. impact preview with independent scope switches
                page.check("input[name='apply_existing']")
                page.click("text=영향 미리보기")
                page.wait_for_load_state()
                self.assertIn("영향 미리보기: 포함", page.inner_text("body"))
                self.assertIn("expense-demo-c4", page.inner_text("body"))
                self.assertEqual(overflow(page) <= 0, True)

                # 8. explicit apply
                page.click("text=이 범위로 적용")
                page.wait_for_load_state()
                self.assertIn("적용했습니다", page.inner_text("body"))
                self.assertIn("2건", page.inner_text("body"))
                self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"],
                                 "trip-demo-b")
                self.assertTrue(self.store.get_rule(rule["rule_id"])["apply_existing"])
                self.assertFalse(self.store.get_rule(rule["rule_id"])["apply_future"])
                self.assertEqual(overflow(page) <= 0, True)
            finally:
                browser.close()

    def test_memo_only_save_does_not_open_a_dialog(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page = self._page(p, 1440, 900)
            try:
                self._save_row(page, "expense-demo-c2", 1,
                               {"operator_note": "메모만 수정"}, "exception",
                               "screen-memo-1")
                self.assertNotIn(
                    "rule_change",
                    self.store.conn.execute(
                        "SELECT dialog_state FROM board_learning_cases"
                        " WHERE row_id=?", ("expense-demo-c2",)).fetchall().__str__())
                page.goto(f"http://127.0.0.1:{self.port}/row?id=expense-demo-c2")
                self.assertNotIn("규칙 대화 열기", page.inner_text("body"))
            finally:
                browser.close()

    def test_close_and_resume_keep_the_answers(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page = self._page(p, 1440, 900)
            try:
                self._save_row(page, "expense-demo-c1", 1,
                               {"display_tab_id": "trip-demo-b"}, "rule_change",
                               "screen-save-2")
                case = self.store.conn.execute(
                    "SELECT case_id FROM board_learning_cases WHERE row_id=?",
                    ("expense-demo-c1",)).fetchone()[0]
                self.store.open_rule_dialog(
                    learning_case_id=case,
                    draft={"conditions": {"merchant_normalized": "예시 숙소"},
                           "effects": {"item": "숙박비"}},
                    client_request_id="screen-dialog-2")
                state = self.store.rule_dialog_state(case)
                question = state["questions"][0]
                self.store.answer_rule_question(
                    question_id=question["question_id"], answer="repeatable",
                    expected_row_revision=state["row_revision"],
                    client_request_id="screen-answer-2")
                page.goto(f"http://127.0.0.1:{self.port}/rules?case={case}")
                page.click("text=대화 닫기")
                page.wait_for_load_state()
                self.assertIn("대화를 닫았습니다", page.inner_text("body"))
                self.assertIn("대화 재개", page.inner_text("body"))
                self.assertEqual(self.store.rule_dialog_state(case)["dialog_state"],
                                 "closed")
                page.click("text=대화 재개")
                page.wait_for_load_state()
                self.assertIn("답변 완료: 비슷한 거래에도", page.inner_text("body"))
                # the stored enum stays internal and is not shown
                self.assertNotIn("repeatable", page.inner_text("body"))
                self.assertIn("합성 모드입니다. 실제 AI 모델은 연결되지 않았습니다.",
                              page.inner_text("body"))
                self.assertEqual(self.store.rule_dialog_state(case)["answers"]
                                 ["rule_kind"], "repeatable")
            finally:
                browser.close()

    def test_stale_preview_is_reported_and_nothing_is_applied(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page = self._page(p, 1440, 900)
            try:
                self._save_row(page, "expense-demo-c1", 1,
                               {"display_tab_id": "trip-demo-b"}, "rule_change",
                               "screen-save-3")
                case = self.store.conn.execute(
                    "SELECT case_id FROM board_learning_cases WHERE row_id=?",
                    ("expense-demo-c1",)).fetchone()[0]
                self.store.open_conversation(
                    learning_case_id=case, client_request_id="screen-conv-3")
                self.store.run_dialog_turn(
                    conversation_id=f"conv-{case}", client_request_id="screen-turn-3",
                    muse=self.muse, gemini=self.gemini)
                self.store.confirm_dialog_draft(
                    learning_case_id=case, client_request_id="screen-confirm-3")
                rule_id = self.store.conversation_for_case(case)["rule_id"]
                self.store.preview_rule(rule_id=rule_id, apply_existing=True,
                                        apply_future=False)
                page.goto(f"http://127.0.0.1:{self.port}/rules?case={case}")
                # another writer changes a selected row after the preview
                self.store.save(
                    row_id="expense-demo-c4", expected_revision=1,
                    client_request_id="screen-race", change_mode="exception",
                    changes={"operator_note": "먼저 저장됨"})
                page.click("text=이 범위로 적용")
                page.wait_for_load_state()
                self.assertIn("PREVIEW_STALE", page.inner_text("body"))
                self.assertIn("새 미리보기", page.inner_text("body"))
                # the rule_change save already moved c1, and the rule must not
                # have touched c4 before the stale rejection
                self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"],
                                 "trip-demo-b")
                self.assertEqual(self.store.get_row("expense-demo-c4")["display_tab_id"],
                                 "trip-demo-a")
                self.assertEqual(self.store.get_row("expense-demo-c4")["revision"], 2)
            finally:
                browser.close()

    def test_double_click_applies_once(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page = self._page(p, 1440, 900)
            try:
                self._save_row(page, "expense-demo-c1", 1,
                               {"display_tab_id": "trip-demo-b"}, "rule_change",
                               "screen-save-4")
                case = self.store.conn.execute(
                    "SELECT case_id FROM board_learning_cases WHERE row_id=?",
                    ("expense-demo-c1",)).fetchone()[0]
                self.store.open_conversation(
                    learning_case_id=case, client_request_id="screen-conv-4")
                self.store.run_dialog_turn(
                    conversation_id=f"conv-{case}", client_request_id="screen-turn-4",
                    muse=self.muse, gemini=self.gemini)
                self.store.confirm_dialog_draft(
                    learning_case_id=case, client_request_id="screen-confirm-4")
                rule_id = self.store.conversation_for_case(case)["rule_id"]
                self.store.preview_rule(rule_id=rule_id, apply_existing=True,
                                        apply_future=False)
                page.goto(f"http://127.0.0.1:{self.port}/rules?case={case}")
                button = page.locator("text=이 범위로 적용")
                request_id = page.evaluate("""() => {
                    const form = [...document.querySelectorAll('form')]
                        .find(f => f.action.includes('/rules/apply'));
                    return form ? form.querySelector('[name=client_request_id]').value : null;
                }""")
                button.click()
                page.wait_for_load_state()
                button.click()
                page.wait_for_load_state()
                self.assertIn("적용했습니다", page.inner_text("body"))
                self.assertEqual(self.store.get_row("expense-demo-c1")["revision"], 2)
                self.assertEqual(self.store.get_row("expense-demo-c4")["revision"], 2)
                self.assertIsNotNone(request_id)
                applied = self.store.conn.execute(
                    "SELECT COUNT(*) FROM classification_rule_versions"
                    " WHERE rule_id=? AND change_kind='apply'", (rule_id,)).fetchone()[0]
                self.assertEqual(applied, 1)
            finally:
                browser.close()

    def test_unbound_providers_wait_and_the_screen_says_so(self):
        from playwright.sync_api import sync_playwright

        board_mod.bind_dialog_adapters(None, None)
        with sync_playwright() as p:
            browser, page = self._page(p, 1440, 900)
            try:
                self._save_row(page, "expense-demo-c1", 1,
                               {"display_tab_id": "trip-demo-b"}, "rule_change",
                               "screen-save-5")
                case = self.store.conn.execute(
                    "SELECT case_id FROM board_learning_cases WHERE row_id=?",
                    ("expense-demo-c1",)).fetchone()[0]
                self.store.open_rule_dialog(
                    learning_case_id=case,
                    draft={"conditions": {"merchant_normalized": "예시 숙소"},
                           "effects": {"item": "숙박비"}},
                    client_request_id="screen-dialog-5")
                page.goto(f"http://127.0.0.1:{self.port}/rules?case={case}")
                page.click("text=규칙 초안 요청 (합성 턴)")
                page.wait_for_load_state()
                self.assertIn("AI 초안 대기 중입니다", page.inner_text("body"))
                self.assertIn("행 저장과 확정 규칙 실행은 계속됩니다", page.inner_text("body"))
                self.assertNotIn("AI 연결됨", page.inner_text("body"))
            finally:
                browser.close()

    def test_same_flow_at_390(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page = self._page(p, 390, 844)
            try:
                self._save_row(page, "expense-demo-c1", 1,
                               {"display_tab_id": "trip-demo-b"}, "rule_change",
                               "screen-save-6")
                case = self.store.conn.execute(
                    "SELECT case_id FROM board_learning_cases WHERE row_id=?",
                    ("expense-demo-c1",)).fetchone()[0]
                self._open_dialog(page)
                self.assertIn("합성 모드", page.inner_text("body"))
                self.assertLessEqual(overflow(page), 0)
                self.assertLessEqual(inner_overflow(page, ".sect"), 0)
                self.store.open_rule_dialog(
                    learning_case_id=case,
                    draft={"conditions": {"merchant_normalized": "예시 숙소"},
                           "effects": {"item": "숙박비"}},
                    client_request_id="screen-dialog-6")
                page.goto(f"http://127.0.0.1:{self.port}/rules?case={case}")
                self.assertLessEqual(overflow(page), 0)
                page.check("input[value='repeatable']")
                page.click("text=답변 저장")
                page.wait_for_load_state()
                self.assertIn("답변을 저장했습니다", page.inner_text("body"))
                self.assertLessEqual(overflow(page), 0)
                page.click("text=규칙 초안 요청 (합성 턴)")
                page.wait_for_load_state()
                self.assertIn("초안을 받았습니다", page.inner_text("body"))
                self.assertLessEqual(overflow(page), 0)
                page.click("text=초안 저장")
                page.wait_for_load_state()
                page.check("input[name='apply_existing']")
                page.click("text=영향 미리보기")
                page.wait_for_load_state()
                self.assertIn("영향 미리보기: 포함", page.inner_text("body"))
                self.assertLessEqual(overflow(page), 0)
                page.click("text=이 범위로 적용")
                page.wait_for_load_state()
                self.assertIn("적용했습니다", page.inner_text("body"))
                self.assertLessEqual(overflow(page), 0)
                self.assertEqual(self.store.get_row("expense-demo-c1")["display_tab_id"],
                                 "trip-demo-b")
            finally:
                browser.close()

    def test_conversation_state_api_still_answers(self):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/classification/conversation"
                f"?conversation_id=conv-missing") as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["state"], "not_found")
        self.assertEqual(payload["excluded_context_fields"][0], "customer_name")

    def test_one_off_answer_stops_the_screen_and_keeps_the_row_edit(self):
        """this_only ends the dialog on the screen and on the server."""
        from playwright.sync_api import sync_playwright

        for width, row_id, tag in ((1440, "expense-demo-c3", "wide"),
                                   (390, "expense-demo-c2", "narrow")):
            with self.subTest(width=width), sync_playwright() as p:
                browser, page = self._page(p, width, 900 if width == 1440 else 844)
                try:
                    self._save_row(page, row_id, 1,
                                   {"display_tab_id": "trip-demo-b"}, "rule_change",
                                   f"screen-oneoff-save-{tag}")
                    case = self.store.conn.execute(
                        "SELECT case_id FROM board_learning_cases WHERE row_id=?",
                        (row_id,)).fetchone()[0]
                    self.store.open_rule_dialog(
                        learning_case_id=case,
                        draft={"conditions": {"merchant_normalized": "예시 이동"},
                               "effects": {"item": "교통비"}},
                        client_request_id=f"screen-oneoff-dialog-{tag}")
                    state = self.store.rule_dialog_state(case)
                    self.assertEqual(state["questions"][0]["question_key"], "rule_kind")
                    page.goto(f"http://127.0.0.1:{self.port}/rules?case={case}")
                    body = page.inner_text("body")
                    self.assertIn("이번 거래에만 적용할까요, 비슷한 거래에도 적용할까요?",
                                  body)
                    self.assertIn("이번 거래에만", body)
                    self.assertNotIn("this_only", body)
                    page.check("input[name='answer'][value='this_only']")
                    page.click("text=답변 저장")
                    page.wait_for_load_state()
                    body = page.inner_text("body")
                    self.assertIn("이번 거래만 적용하기로 하셨습니다", body)
                    # no turn, no draft, no preview and no apply control is offered
                    self.assertIsNone(
                        page.query_selector(
                            "form[action='/api/classification/conversation/advance']"))
                    self.assertIsNone(
                        page.query_selector(
                            "form[action='/api/classification/conversation/confirm-draft']"))
                    self.assertIsNone(page.query_selector("text=초안 저장"))
                    self.assertIsNone(
                        page.query_selector("form[action*='/rules/preview']"))
                    self.assertIsNone(page.query_selector("form[action*='/rules/apply']"))
                    # the row change the owner already saved stays
                    self.assertEqual(self.store.get_row(row_id)["display_tab_id"],
                                     "trip-demo-b")
                    self.assertEqual(self.store.rule_dialog_state(case)["dialog_state"],
                                     "one_off")
                    # the server refuses a direct request too
                    with self.assertRaises(Exception) as refused:
                        self.store.create_rule_draft(
                            draft={"learning_case_id": case,
                                   "conditions": {"merchant_normalized": "예시 이동"},
                                   "effects": {"item": "교통비"}},
                            client_request_id=f"screen-oneoff-direct-{tag}")
                    self.assertEqual(getattr(refused.exception, "code", None), "RULE_ONE_OFF")
                    self.assertEqual(overflow(page), 0)
                finally:
                    browser.close()

    def test_one_off_answer_keeps_the_stop_after_close_and_resume(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page = self._page(p, 1440, 900)
            try:
                self._save_row(page, "expense-demo-c4", 1,
                               {"display_tab_id": "trip-demo-b"}, "rule_change",
                               "screen-oneoff-save-2")
                case = self.store.conn.execute(
                    "SELECT case_id FROM board_learning_cases WHERE row_id=?",
                    ("expense-demo-c4",)).fetchone()[0]
                self.store.open_rule_dialog(
                    learning_case_id=case,
                    draft={"conditions": {"merchant_normalized": "예시 식당"},
                           "effects": {"item": "식비"}},
                    client_request_id="screen-oneoff-dialog-2")
                state = self.store.rule_dialog_state(case)
                question = state["questions"][0]
                self.store.answer_rule_question(
                    question_id=question["question_id"], answer="this_only",
                    expected_row_revision=state["row_revision"],
                    client_request_id="screen-oneoff-answer-2")
                page.goto(f"http://127.0.0.1:{self.port}/rules?case={case}")
                page.click("text=대화 닫기")
                page.wait_for_load_state()
                self.assertIn("대화를 닫았습니다", page.inner_text("body"))
                page.click("text=대화 재개")
                page.wait_for_load_state()
                body = page.inner_text("body")
                self.assertIn("이번 거래만 적용하기로 하셨습니다", body)
                self.assertNotIn("규칙 초안 요청", body)
                self.assertEqual(
                    self.store.rule_dialog_state(case)["open_questions"], [])
                # a future rule stays available for another case
                other = self.store.save(
                    row_id="expense-demo-c1",
                    expected_revision=self.store.get_row("expense-demo-c1")["revision"],
                    client_request_id="screen-oneoff-other", change_mode="exception",
                    changes={"display_tab_id": "trip-demo-a"})["learning_case_id"]
                self.assertFalse(self.store.case_is_one_off(other))
            finally:
                    browser.close()
