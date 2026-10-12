"""The second design bundle: view state, the archived drawer, the shared chrome
on /row and /trips, and a refused plain form post.

Real clicks at 1440 and 390 against the product server. The JSON save contract
is asserted separately so the HTML error path cannot quietly change it.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from webapp import ledger_board as board_mod
from webapp.ledger_store import LedgerStore


class ViewStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "state.sqlite")
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

    def _page(self, width, height=900):
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        page = self._browser.new_context(
            viewport={"width": width, "height": height}).new_page()
        # APP_SPEC 4.1 raises a native leave-confirm when an edit is unsaved.
        # Playwright does not answer it, so the harness does.
        page.on("dialog", lambda d: d.accept()
                if d.type == "beforeunload" else None)
        return page

    def _url(self, query=""):
        return f"http://127.0.0.1:{self.port}/board{query}"

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as response:
            return response.status, response.read().decode("utf-8")

    # ------------------------------------------------------- search and filter
    def test_the_search_and_the_filter_live_in_the_url(self):
        page = self._page(1440)
        page.goto(self._url("?tab=trip-demo-a"))
        page.fill("#q", "숙소")
        page.click("#q-go")
        page.wait_for_load_state()
        self.assertEqual(
            page.evaluate("new URL(location.href).searchParams.get('q')"), "숙소")
        self.assertEqual(
            page.evaluate("new URL(location.href).searchParams.get('tab')"),
            "trip-demo-a")
        self.assertIn("예시 숙소", page.inner_text(".tw"))
        self.assertNotIn("교통비", page.inner_text(".tw"))
        # a refresh keeps the same state
        page.reload()
        page.wait_for_load_state()
        self.assertEqual(page.input_value("#q"), "숙소")
        self.assertIn("예시 숙소", page.inner_text(".tw"))
        # and so does going back to the list without a search
        page.click("#q-clear")
        page.wait_for_load_state()
        self.assertIsNone(
            page.evaluate("new URL(location.href).searchParams.get('q')"))

    def test_the_filter_keeps_itself_when_the_trip_changes(self):
        page = self._page(1440)
        page.goto(self._url("?tab=trip-demo-a"))
        with page.expect_navigation():
            page.select_option("#kind", "ex")
        page.wait_for_load_state()
        self.assertEqual(
            page.evaluate("new URL(location.href).searchParams.get('kind')"), "ex")
        self.assertIn("지출", page.inner_text("#sum"))
        table = page.inner_text(".tw")
        self.assertIn("수입 내역이 없어요", table)
        self.assertIn("예시 숙소", table)
        # switching trip in the nav keeps the filter
        href = page.get_attribute(".nav-list a[href*='tab=trip-demo-b']", "href")
        self.assertIn("kind=ex", href)
        page.click(".nav-list a[href*='tab=trip-demo-b']")
        page.wait_for_load_state()
        self.assertEqual(
            page.evaluate("new URL(location.href).searchParams.get('kind')"), "ex")
        self.assertEqual(
            page.evaluate("new URL(location.href).searchParams.get('tab')"),
            "trip-demo-b")
        # going back returns to the first trip with the filter still on
        page.go_back()
        page.wait_for_load_state()
        self.assertEqual(
            page.evaluate("new URL(location.href).searchParams.get('tab')"),
            "trip-demo-a")
        self.assertEqual(
            page.evaluate("new URL(location.href).searchParams.get('kind')"), "ex")

    def test_the_trip_search_submits_the_view_state_too(self):
        page = self._page(1440)
        page.goto(self._url("?tab=trip-demo-a&kind=ex"))
        nav_form = page.query_selector(".nav-q")
        self.assertEqual(nav_form.get_attribute("method"), "get")
        # the form carries the current tab and filter, so it does not lose them
        self.assertEqual(nav_form.query_selector("input[name='tab']").get_attribute("value"),
                         "trip-demo-a")
        self.assertEqual(nav_form.query_selector("input[name='kind']").get_attribute("value"),
                         "ex")
        page.fill("#tripq", "예시여행B")
        page.press("#tripq", "Enter")
        page.wait_for_load_state()
        self.assertIn("q=", page.url)
        self.assertIn("kind=ex", page.url)

    # -------------------------------------------------------- archived drawer
    def _archive_a_trip(self, tab_id="trip-demo-b"):
        trip = [t for t in self.store.list_trips(include_archived=True)
                if t["tab_id"] == tab_id][0]
        self.store.save_trip_meta(
            tab_id=tab_id, expected_revision=trip["revision"],
            client_request_id="state-archive", actor="owner", archived=True)
        return trip

    def test_the_archived_drawer_opens_from_the_url_and_restores_a_trip(self):
        self._archive_a_trip()
        page = self._page(1440)
        page.goto(self._url("?tab=trip-demo-a"))
        self.assertEqual(page.locator("#archived").count(), 0)
        self.assertIn("펼치기", page.inner_text("#arch-toggle"))
        # the toggle is a real link, so it works without script too
        self.assertTrue(page.get_attribute("#arch-toggle", "href").startswith("/board?"))
        page.click("#arch-toggle")
        page.wait_for_load_state()
        self.assertEqual(
            page.evaluate("new URL(location.href).searchParams.get('arch')"), "1")
        self.assertEqual(page.locator("#archived").count(), 1)
        self.assertIn("예시여행B", page.inner_text("#archived"))
        # a refresh keeps the drawer open
        page.reload()
        page.wait_for_load_state()
        self.assertEqual(page.locator("#archived").count(), 1)
        # restore goes through the existing trip meta contract
        page.click("#archived button[type='submit']")
        page.wait_for_load_state()
        trip = [t for t in self.store.list_trips(include_archived=True)
                if t["tab_id"] == "trip-demo-b"][0]
        self.assertFalse(trip["archived"])
        # with nothing left to show, the section itself is gone
        self.assertEqual(page.locator("#archived").count(), 0)
        self.assertEqual(page.locator("#arch-toggle").count(), 0)

    def test_the_drawer_state_survives_a_trip_switch(self):
        self._archive_a_trip()
        page = self._page(1440)
        page.goto(self._url("?tab=trip-demo-a&arch=1"))
        self.assertEqual(page.locator("#archived").count(), 1)
        href = page.get_attribute(".nav-list a[href*='tab=trip-demo-b']", "href")
        self.assertIn("arch=1", href)

    # ------------------------------------------------------------- /row screen
    def test_the_row_screen_uses_the_shared_chrome_and_keeps_its_meaning(self):
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/row?id=expense-demo-c1&edit=1")
        self.assertIn("숲길여행 회계", page.inner_text(".nav"))
        self.assertIn("여행 목록", page.inner_text(".nav"))
        self.assertTrue(page.is_visible(".page-body"))
        self.assertEqual(overflow(page), 0)
        self.assertIn("원천", page.inner_text(".page-body"))
        self.assertIn("변경 이력", page.inner_text(".page-body"))
        # revision is detail-secondary info: kept in the detail body, kept out
        # of the header/meta (internal identifier must not lead the page)
        self.assertNotIn("revision", page.inner_text(".meta"))
        self.assertIn("revision", page.inner_text(".page-body"))
        # the rule link is conditional: it appears once a learning case exists
        self.assertEqual(page.locator(".page-body a[href^='/rules?case=']").count(), 0)
        self.store.save(row_id="expense-demo-c1",
                        expected_revision=self.store.get_row("expense-demo-c1")["revision"],
                        client_request_id="state-row-rule", change_mode="rule_change",
                        changes={"display_tab_id": "trip-demo-b"})
        page.reload()
        self.assertEqual(page.locator(".page-body a[href^='/rules?case=']").count(), 1)
        # the save form still posts to the product endpoint with a return path
        action = page.get_attribute(".page-body form[action='/api/rows/expense-demo-c1/save']",
                                    "action")
        self.assertEqual(action, "/api/rows/expense-demo-c1/save")
        self.assertEqual(
            page.input_value("input[name='return_to']"),
            "/row?id=expense-demo-c1&edit=1")
        self.assertIn("취소", page.inner_text(".page-body"))

    def test_a_row_save_from_the_row_screen_still_saves(self):
        page = self._page(1440)
        before = self.store.get_row("expense-demo-c1")
        page.goto(f"http://127.0.0.1:{self.port}/row?id=expense-demo-c1&edit=1")
        page.fill("input[name='description']", "행 화면에서 저장")
        page.click(".page-body form[action='/api/rows/expense-demo-c1/save'] "
                   "button[type='submit']")
        page.wait_for_load_state()
        after = self.store.get_row("expense-demo-c1")
        self.assertEqual(after["revision"], before["revision"] + 1)
        self.assertEqual(after["description"].replace(" ", ""), "행화면에서저장")
        self.assertIn("변경 이력", page.inner_text(".page-body"))

    def test_the_allocation_split_screen_still_answers(self):
        # /income/<id>/split is outside this bundle, it only has to keep working
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/income/income-demo-i1/split")
        self.assertIsNotNone(page.query_selector(
            "form[action='/api/income/income-demo-i1/allocations']"))
        self.assertEqual(
            page.input_value(
                "input[name='expected_source_revision']"), "1")

    # ------------------------------------------------------------ /trips screen
    def test_the_trip_screen_uses_the_shared_chrome_and_keeps_its_actions(self):
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/trips")
        body = page.inner_text(".page-body")
        self.assertIn("여행 관리", body)
        self.assertIn("여행 목록", page.inner_text(".nav"))
        self.assertEqual(overflow(page), 0)
        self.assertIn("정보 저장", body)
        self.assertIn("보관", body)
        self.assertIn("삭제 미리보기", body)
        # revision is detail-secondary on the trip card (not in the title)
        self.assertIn("여행 revision 1", body)
        for action in ("/api/trips/trip-demo-a/meta", "/api/trips/trip-demo-b/meta"):
            self.assertIsNotNone(
                page.query_selector(f".page-body form[action='{action}']"), action)
        self.assertEqual(
            page.input_value(".page-body form[action='/api/trips/trip-demo-a/meta'] "
                             "input[name='return_to']"), "/trips")

    def test_archiving_from_the_trip_screen_moves_it_to_the_drawer(self):
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/trips")
        forms = page.query_selector_all(
            ".page-body form[action='/api/trips/trip-demo-b/meta']")
        archive = [f for f in forms
                   if f.query_selector("input[name='archived'][value='1']") is not None][0]
        archive.query_selector("button[type='submit']").click()
        page.wait_for_load_state()
        trip = [t for t in self.store.list_trips(include_archived=True)
                if t["tab_id"] == "trip-demo-b"][0]
        self.assertTrue(trip["archived"])
        page.goto(self._url("?tab=trip-demo-a&arch=1"))
        self.assertIn("예시여행B", page.inner_text("#archived"))

    def test_the_delete_preview_still_shows_and_confirms(self):
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/trips?preview_tab=trip-demo-b")
        body = page.inner_text(".page-body")
        self.assertIn("삭제 미리보기", body)
        self.assertIn("분류대기로 이동", body)
        self.assertIn("내역 이동 후 삭제 확정", body)
        self.assertEqual(
            page.input_value(".page-body form[action='/api/trips/trip-demo-b/delete'] "
                             "input[name='return_to']"),
            "/trips?preview_tab=trip-demo-b")
        page.click(".page-body form[action='/api/trips/trip-demo-b/delete'] "
                   "button[type='submit']")
        page.wait_for_load_state()
        self.assertIn("여행 관리", page.inner_text(".page-body"))

    def test_a_stale_trip_revision_is_reported_and_the_typed_name_is_kept(self):
        page = self._page(1440)
        page.goto(f"http://127.0.0.1:{self.port}/trips")
        # someone else saves the same trip first
        trip = [t for t in self.store.list_trips(include_archived=True)
                if t["tab_id"] == "trip-demo-a"][0]
        self.store.save_trip_meta(
            tab_id="trip-demo-a", expected_revision=trip["revision"],
            client_request_id="state-other-writer", actor="owner",
            display_key="남이 바꾼 이름")
        page.fill(".page-body form[action='/api/trips/trip-demo-a/meta'] "
                  "input[name='display_key']", "내가 적은 이름")
        page.click(".page-body form[action='/api/trips/trip-demo-a/meta'] "
                   "button[type='submit']")
        page.wait_for_load_state()
        self.assertIn("EDIT_CONFLICT", page.inner_text("body"))
        self.assertEqual(
            self.store.list_trips(include_archived=True)[0]["display_key"],
            "남이 바꾼 이름")

    # The plain form refusal moved to test_ledger_design_refusal.py, where it
    # checks the HTML status, the escaping, the re-save and the absence of any
    # typed value in the address.

    def test_the_json_contract_is_unchanged(self):
        status, body = self._post_json("/api/rows/expense-demo-c1/save", {
            "csrf": board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "state-json",
            "change_mode": "exception",
            "display_tab_id": "trip-demo-b",
            "return_to": "/board?tab=trip-demo-a",
        })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["outcome"], "saved")
        status, body = self._post_json("/api/rows/expense-demo-c1/save", {
            "csrf": board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "state-json-stale",
            "change_mode": "exception",
            "display_tab_id": "trip-demo-a",
        })
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["code"], "EDIT_CONFLICT")
        status, body = self._post_json("/api/rows/expense-demo-c2/save", {
            "csrf": board_mod.CSRF_TOKEN,
            "expected_revision": 1,
            "client_request_id": "state-json-amount",
            "change_mode": "exception",
            "amount_krw": 5,
        })
        self.assertEqual(status, 422)
        # amount_krw is a fixed field on a card expense, so it is refused there
        self.assertEqual(json.loads(body)["code"], "FIELD_READ_ONLY")

    def _post_json(self, path, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    # ----------------------------------------------------------- export facts
    def test_the_same_request_id_reuses_the_job_and_adds_no_file(self):
        payload = {"csrf": board_mod.CSRF_TOKEN, "tab_ids": ["trip-demo-a"],
                   "client_request_id": "state-export-same"}
        first = json.loads(self._post_json("/api/exports/xlsx", payload)[1])
        files_after_first = self._export_files()
        second = json.loads(self._post_json("/api/exports/xlsx", payload)[1])
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(first["output_path"], second["output_path"])
        self.assertEqual(self._export_files(), files_after_first)
        self.assertEqual(len(files_after_first), 1)

    def test_a_new_request_over_the_same_snapshot_publishes_its_own_file(self):
        payload = {"csrf": board_mod.CSRF_TOKEN, "tab_ids": ["trip-demo-a"],
                   "client_request_id": "state-export-one"}
        first = json.loads(self._post_json("/api/exports/xlsx", payload)[1])
        keep = Path(first["output_path"])
        before_digest = keep.read_bytes()
        second = json.loads(self._post_json("/api/exports/xlsx", {
            "csrf": board_mod.CSRF_TOKEN, "tab_ids": ["trip-demo-a"],
            "client_request_id": "state-export-two"})[1])
        self.assertNotEqual(first["job_id"], second["job_id"])
        self.assertNotEqual(first["output_path"], second["output_path"])
        files = self._export_files()
        self.assertEqual(len(files), 2)
        # the first file is untouched
        self.assertEqual(keep.read_bytes(), before_digest)
        self.assertTrue(Path(second["output_path"]).is_file())

    def _export_files(self):
        out = Path(os.environ["WEBLEDGER_EXPORT_DIR"])
        return sorted(p.name for p in out.glob("*.xlsx")) if out.is_dir() else []


def overflow(page):
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")


if __name__ == "__main__":
    unittest.main()
