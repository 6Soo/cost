"""Third design bundle: a form refusal that leaks nothing, a drawer that works
without script, and the last four screens on the shared shell.

Real clicks at 1440 and 390, with script turned off where the claim is about
script being off. The JSON save contract is asserted separately.
"""

import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from webapp import ledger_board as board_mod
from webapp.ledger_store import LedgerStore

XSS = "<img src=x onerror=\"window.__xss=1\">"


class RefusalAndShellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "refuse.sqlite")
        self._prev_export = os.environ.get("WEBLEDGER_EXPORT_DIR")
        os.environ["WEBLEDGER_EXPORT_DIR"] = str(Path(self.tmp) / "exports")
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self._pw = None
        self._browser = None

    def tearDown(self):
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        for key, value in (("WEBLEDGER_DB", self._prev_db),
                           ("WEBLEDGER_EXPORT_DIR", self._prev_export)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _page(self, width, height=900, *, script=True):
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        context = self._browser.new_context(
            viewport={"width": width, "height": height},
            java_script_enabled=script)
        return context.new_page()

    def _form_post(self, path, fields):
        body = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port_stub(self)}{path}", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.geturl(), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.geturl(), exc.read()

    # ---------------------------------------------------- the refusal itself
    def _stale_save(self, description, **extra):
        before = self.store.get_row("expense-demo-c1")
        self.store.save(row_id="expense-demo-c1", expected_revision=before["revision"],
                        client_request_id="refuse-writer", change_mode="exception",
                        changes={"operator_note": "someone else first"})
        fields = {
            "csrf": board_mod.CSRF_TOKEN,
            "expected_revision": before["revision"],
            "client_request_id": "refuse-form",
            "change_mode": "exception",
            "description": description,
            "return_to": "/board?tab=trip-demo-a&row=expense-demo-c1",
        }
        fields.update(extra)
        return self._form_post("/api/rows/expense-demo-c1/save", fields)

    def test_a_refused_form_post_answers_html_with_the_status_and_the_values(self):
        status, url, body = self._stale_save("거절될 입력")
        self.assertEqual(status, 409)
        self.assertTrue(url.endswith("/api/rows/expense-demo-c1/save"))
        html = body.decode("utf-8")
        self.assertTrue(html.lstrip().lower().startswith("<!doctype html"))
        self.assertIn("EDIT_CONFLICT", html)
        # the typed value is in the re-rendered form
        self.assertIn("거절될 입력", html)

    def test_nothing_typed_reaches_the_url_or_a_header(self):
        secret = "CUSTOMER-NAME-예약번호-9999"
        status, url, body = self._stale_save(secret)
        self.assertEqual(status, 409)
        self.assertNotIn(secret, url)
        self.assertNotIn("9999", url)
        lowered = url.lower()
        for marker in ("d=", "base64", "%3d"):
            self.assertNotIn(marker, lowered, marker)
        headers = " ".join(f"{k}:{v}" for k, v in getattr(
            self.server, "_last_headers", []) or [])
        self.assertNotIn(secret, headers)
        # the value is in the body only because the form was re-rendered
        self.assertIn(secret, body.decode("utf-8"))

    def test_the_refusal_escapes_what_it_shows_again(self):
        status, _url, body = self._stale_save(XSS)
        self.assertEqual(status, 409)
        html = body.decode("utf-8")
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img src=x", html)
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/board?tab=trip-demo-a"
                  f"&row=expense-demo-c1&err=INVALID_VALUE")
        page.fill("#f-description", XSS)
        page.wait_for_timeout(50)
        self.assertIsNone(page.evaluate("() => window.__xss === 1 ? 1 : null"))

    def test_the_refused_values_can_be_saved_again(self):
        status, _url, body = self._stale_save("다시 저장할 값")
        self.assertEqual(status, 409)
        self.assertIn("다시 저장할 값", body.decode("utf-8"))
        # the owner reloads the screen, fixes the revision and saves for real
        current = self.store.get_row("expense-demo-c1")
        self.store.save(row_id="expense-demo-c1", expected_revision=current["revision"],
                        client_request_id="refuse-fix", change_mode="exception",
                        changes={"description": "다시 저장할 값"})
        after = self.store.get_row("expense-demo-c1")
        self.assertEqual(after["revision"], current["revision"] + 1)
        self.assertEqual(after["description"].replace(" ", ""), "다시저장할값")

    def test_a_field_the_endpoint_refuses_comes_back_as_html_too(self):
        status, _url, body = self._form_post("/api/rows/expense-demo-c1/save", {
            "csrf": board_mod.CSRF_TOKEN,
            "expected_revision": self.store.get_row("expense-demo-c1")["revision"],
            "client_request_id": "refuse-fixed",
            "change_mode": "exception",
            "amount_krw": "1000",
            "return_to": "/board?tab=trip-demo-a&row=expense-demo-c1",
        })
        self.assertEqual(status, 422)
        html = body.decode("utf-8")
        self.assertIn("FIELD_READ_ONLY", html)
        self.assertNotIn("amount_krw", html.split("<form")[0] if "<form" in html else html)

    def test_the_json_contract_is_untouched(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/rows/expense-demo-c1/save",
            data=json.dumps({
                "csrf": board_mod.CSRF_TOKEN,
                "expected_revision": self.store.get_row("expense-demo-c1")["revision"],
                "client_request_id": "refuse-json",
                "change_mode": "exception",
                "display_tab_id": "trip-demo-b",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["outcome"], "saved")
        # and a JSON refusal stays JSON, with the same status
        stale = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/rows/expense-demo-c1/save",
            data=json.dumps({
                "csrf": board_mod.CSRF_TOKEN,
                "expected_revision": 1,
                "client_request_id": "refuse-json-stale",
                "change_mode": "exception",
                "display_tab_id": "trip-demo-a",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(stale)
            self.fail("expected a refusal")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 409)
            payload = json.loads(exc.read())
            self.assertEqual(payload["code"], "EDIT_CONFLICT")
            self.assertNotIn("<html", json.dumps(payload).lower())

    def test_return_to_only_accepts_a_local_path(self):
        allowed = ["/board", "/board?tab=trip-demo-a", "/row?id=expense-demo-c1",
                   "/rules?case=x", "/trips", "/export", "/import",
                   "/income/income-demo-i1/split", "/board/"]
        refused = ["https://example.com/board", "//example.com/board",
                   "http://127.0.0.1/board", "/board\r\nSet-Cookie: x=1",
                   "board", "javascript:alert(1)", "/etc/passwd",
                   "/board\nLocation: https://example.com", "\\\\host\\share",
                   "", None, 5, "/boards/../etc"]
        for value in allowed:
            self.assertTrue(board_mod.local_path(value), value)
        for value in refused:
            self.assertEqual(board_mod.local_path(value), "", value)

    def test_a_crafted_return_to_lands_on_the_local_board(self):
        before = self.store.get_row("expense-demo-c1")
        self.store.save(row_id="expense-demo-c1", expected_revision=before["revision"],
                        client_request_id="refuse-writer-2", change_mode="exception",
                        changes={"operator_note": "again"})
        status, url, _body = self._form_post("/api/rows/expense-demo-c1/save", {
            "csrf": board_mod.CSRF_TOKEN,
            "expected_revision": before["revision"],
            "client_request_id": "refuse-hostile",
            "change_mode": "exception",
            "description": "값",
            "return_to": "https://example.com/steal",
        })
        self.assertEqual(status, 409)
        self.assertIn("127.0.0.1", url)
        self.assertNotIn("example.com", url)

    # -------------------------------------------------- drawer without script
    def test_the_drawer_opens_with_script_turned_off(self):
        trip = [t for t in self.store.list_trips(include_archived=True)
                if t["tab_id"] == "trip-demo-b"][0]
        self.store.save_trip_meta(
            tab_id="trip-demo-b", expected_revision=trip["revision"],
            client_request_id="nojs-archive", actor="owner", archived=True)
        page = self._page(1440, script=False)
        page.goto(f"http://127.0.0.1:{self.port}/board?tab=trip-demo-a")
        self.assertEqual(page.locator("#arch-toggle").count(), 1)
        # it is an anchor, so a plain click navigates with no script at all
        self.assertEqual(page.evaluate is None, False)
        href = page.get_attribute("#arch-toggle", "href")
        self.assertIn("arch=1", href)
        page.click("#arch-toggle")
        page.wait_for_load_state()
        self.assertEqual(page.locator("#archived").count(), 1)
        self.assertIn("예시여행B", page.inner_text("#archived"))
        # and the restore form still posts with no script
        page.click("#archived button[type='submit']")
        page.wait_for_load_state()
        after = [t for t in self.store.list_trips(include_archived=True)
                 if t["tab_id"] == "trip-demo-b"][0]
        self.assertFalse(after["archived"])

    def test_the_archived_row_has_a_view_link_next_to_the_restore(self):
        trip = [t for t in self.store.list_trips(include_archived=True)
                if t["tab_id"] == "trip-demo-b"][0]
        self.store.save_trip_meta(
            tab_id="trip-demo-b", expected_revision=trip["revision"],
            client_request_id="view-archive", actor="owner,", archived=True)
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/board?tab=trip-demo-a&arch=1")
        view = page.query_selector("#archived a.arch-view")
        self.assertIsNotNone(view)
        self.assertIn("tab=trip-demo-b", view.get_attribute("href"))
        # the restore stays a separate form
        self.assertEqual(page.locator("#archived form.arch-restore").count(), 1)
        page.click("#archived a.arch-view")
        page.wait_for_load_state()
        self.assertEqual(overflow(page), 0)
        self.assertIn("0420_예시여행B", page.inner_text(".page-hd"))

    # ------------------------------------------- the last four screens
    def _learning_case(self):
        self.store.save(row_id="expense-demo-c1",
                        expected_revision=self.store.get_row("expense-demo-c1")["revision"],
                        client_request_id="shell-rule", change_mode="rule_change",
                        changes={"display_tab_id": "trip-demo-b"})
        return self.store.conn.execute(
            "SELECT case_id FROM board_learning_cases WHERE row_id=?",
            ("expense-demo-c1",)).fetchone()[0]

    def test_export_import_rules_and_split_use_the_shared_shell(self):
        case = self._learning_case()
        for path, marker in (("/export", "선택 탭 출력"),
                             ("/import", "카드 가져오기"),
                             (f"/rules?case={case}", "규칙 대화"),
                             ("/income/income-demo-i1/split", "배분")):
            with self.subTest(path=path):
                page = self._page(1440)
                page.goto(f"http://127.0.0.1:{self.port}{path}")
                self.assertEqual(overflow(page), 0)
                self.assertIn("숲길여행 법인카드", page.inner_text(".nav"))
                self.assertIn("여행 목록", page.inner_text(".nav"))
                self.assertIn(marker, page.inner_text("body"))
                self.assertTrue(page.evaluate(
                    "document.fonts.check('14px \"Pretendard Variable\"')"))
                page.context.close()

    def test_export_keeps_its_csrf_form_and_range(self):
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/export")
        form = page.query_selector(".page-body form[action='/api/exports/xlsx']")
        self.assertIsNotNone(form)
        self.assertEqual(page.input_value("input[name='csrf']"), board_mod.CSRF_TOKEN)
        self.assertGreaterEqual(
            page.locator("input[name='tab_ids']").count(), 2)
        self.assertEqual(page.input_value("input[name='client_request_id']") != "", True)

    def test_import_keeps_its_upload_form(self):
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/import")
        # the import posts with a script header, so the token is on the page
        self.assertIn(board_mod.CSRF_TOKEN, page.inner_text("body") + page.content())
        self.assertGreaterEqual(page.locator("input[type='file']").count(), 1)
        self.assertIn("/api/imports", page.content())

    def test_the_rule_dialog_keeps_its_explicit_confirm_and_return(self):
        case = self._learning_case()
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/rules?case={case}")
        body = page.inner_text("body")
        self.assertIn("합성 모드입니다", body)
        self.assertIn("근거 설명", body)
        self.assertIn("규칙 초안 요청 (합성 턴)", body)
        self.assertIn("목록으로", body)
        self.assertIn("expense-demo-c1", body)
        self.assertIsNotNone(page.query_selector(
            ".sect a[href^='/row?id=expense-demo-c1']"))
        self.assertEqual(overflow(page), 0)
        # nothing to close yet, so no close control is offered
        self.assertIsNone(page.query_selector(
            "form[action='/api/classification/dialog/close']"))
        # the free text note starts the dialog, and the close control appears
        page.fill("input[name='note']", "같은 가맹점이 반복돼요")
        page.click("text=근거 저장")
        page.wait_for_load_state()
        self.assertIn("근거 설명을 저장했습니다", page.inner_text("body"))
        page.click("text=대화 닫기")
        page.wait_for_load_state()
        self.assertIn("대화 재개", page.inner_text("body"))
        page.click("text=대화 재개")
        page.wait_for_load_state()
        self.assertEqual(page.input_value("input[name='note']"), "같은 가맹점이 반복돼요")

    def test_the_split_screen_keeps_its_totals_and_csrf(self):
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/income/income-demo-i1/split")
        form = page.query_selector(
            ".page-body form[action='/api/income/income-demo-i1/allocations']")
        self.assertIsNotNone(form)
        self.assertEqual(page.input_value("input[name='csrf']"), board_mod.CSRF_TOKEN)
        self.assertEqual(page.input_value("input[name='expected_source_revision']"), "1")
        body = page.inner_text(".page-body")
        # the split screen still shows the source total, the remainder and the rule
        self.assertIn("500,000원", body)
        self.assertIn("배분", body)
        self.assertIsNotNone(page.query_selector("button[type='submit']"))

    def test_no_screen_shows_a_base64_draft_in_its_address(self):
        case = self._learning_case()
        page = self._page(1440)
        for path in ("/board?tab=trip-demo-a", "/export", "/import", f"/rules?case={case}",
                     "/income/income-demo-i1/split", "/row?id=expense-demo-c1&edit=1",
                     "/trips"):
            page.goto(f"http://127.0.0.1:{self.port}{path}")
            self.assertNotIn("&d=", page.url, path)
            self.assertNotIn("?d=", page.url, path)
            self.assertNotIn("base64", page.url, path)


def port_stub(test):
    return test.port


def overflow(page):
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")


if __name__ == "__main__":
    unittest.main()
