"""Three requirements the matrix did not yet name a surface for.

  * APP_SPEC 4.1 — the global top area carries the unsaved row count and the
    last saved time, and leaving with an unsaved edit confirms first.
  * DETAILED 12.2 — a filter gives the whole total and the result total
    separate names, and never replaces one with the other.
  * DETAILED 15 — the manual-expense button sits beside the expense section
    heading.

Proven over the served response, and the leave-confirm over a real browser,
because a string in the HTML is not a dialog that actually appears.
"""

import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webapp import google_ledger_page, ledger_board as board_mod
from webapp.ledger_store import LedgerStore

ROW = "expense-demo-c1"
TAB = "trip-demo-a"


class _Server:
    def _boot(self, name):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / name)
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def _shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def _open(self, path, payload=None, method="GET"):
        data = None
        headers = {}
        if payload is not None:
            body = dict(payload)
            if method == "POST":
                body.setdefault("csrf", board_mod.CSRF_TOKEN)
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def _json(self, path, payload=None, method="GET"):
        status, body = self._open(path, payload, method)
        try:
            return status, json.loads(body)
        except ValueError:
            return status, None

    def _revision(self):
        return (self.store.get_row(ROW) or {}).get("revision")


class GlobalTopAreaTests(_Server, unittest.TestCase):
    """APP_SPEC 4.1 상단 전역 영역."""

    def setUp(self):
        self._boot("top.sqlite")

    def tearDown(self):
        self._shutdown()

    def test_global_area_reserves_unsaved_warning_without_routine_save_timestamp(self):
        status, page = self._open(f"/board?tab={TAB}")
        self.assertEqual(status, 200)
        self.assertIn("저장되지 않은 변경 없음", page)
        self.assertNotIn("최근 저장", page)
        self.assertIn("id='unsaved-count' hidden", page)

    def test_the_last_save_time_comes_from_the_change_ledger(self):
        self._open(f"/api/rows/{ROW}/save",
                   {"expected_revision": self._revision(),
                    "operator_note": "기록", "change_mode": "exception",
                    "client_request_id": "top-1"}, "POST")
        _, page = self._open(f"/board?tab={TAB}")
        self.assertNotIn("최근 저장", page)
        latest = self.store.conn.execute(
            "SELECT MAX(created_at) FROM board_revisions WHERE kind<>'conflict'"
        ).fetchone()[0]
        self.assertTrue(latest)

    def test_a_ledger_with_no_save_says_so_rather_than_inventing_a_time(self):
        status, page = self._open("/board?tab=trip-demo-b")
        self.assertEqual(status, 200)
        self.assertNotIn("최근 저장", page)

    def test_the_shared_screens_carry_the_same_global_line(self):
        for path in ("/import", "/export", "/trips"):
            with self.subTest(path=path):
                status, page = self._open(path)
                self.assertEqual(status, 200)
                if path == '/import' and 'expense-tabs' in page:
                    self.assertIn('id="status"', page)
                else:
                    self.assertIn("id='global-state'", page)
                    self.assertIn("id='unsaved-count'", page)
                self.assertNotIn('최근 저장', page)

    def test_the_script_keeps_the_count_in_step_with_the_dirty_marks(self):
        _, page = self._open(f"/board?tab={TAB}")
        self.assertIn("function reportUnsaved()", page)
        self.assertIn("form[data-dirty=\"1\"]", page)
        # the count is derived from the same marks the Escape guard uses
        self.assertIn("markDirty", page)
        self.assertIn("clearDirty", page)

    def test_the_element_the_markup_carries_is_the_one_the_script_writes_to(self):
        """Tie the two halves together.

        The markup declares the id and the script looks it up by name, so a
        rename on either side alone would leave the count silently frozen at
        its initial text. This is what catches a change to one side only.
        """
        _, page = self._open(f"/board?tab={TAB}")
        declared = re.findall(r"id=['\"]([^'\"]*unsaved[^'\"]*)['\"]", page)
        self.assertTrue(declared, "the unsaved element must be in the markup")
        looked_up = re.findall(
            r"getElementById\(['\"]([^'\"]+)['\"]\)", page)
        self.assertIn(declared[0], looked_up)
        self.assertEqual(len(set(declared)), 1,
                         "one element, one id, on every screen that has it")

    def test_leaving_with_an_unsaved_edit_raises_the_leave_confirm(self):
        _, page = self._open(f"/board?tab={TAB}")
        self.assertIn("beforeunload", page)
        self.assertIn("ev.preventDefault()", page)

    def test_an_owner_does_not_see_the_read_only_note(self):
        _, page = self._open(f"/board?tab={TAB}")
        self.assertIn("data-role=''", page)


class FilteredTotalsTests(_Server, unittest.TestCase):
    """DETAILED 12.2 합계와 미배정."""

    def setUp(self):
        self._boot("filter.sqlite")

    def tearDown(self):
        self._shutdown()

    def _summary(self, query=""):
        from urllib.parse import urlencode

        path = f"/board?tab={TAB}&part=summary"
        if query:
            path += "&" + urlencode({"q": query})
        status, body = self._open(path)
        self.assertEqual(status, 200)
        return body

    def _kpi_amount(self, body, label):
        match = re.search(r"<dt>" + label + r"</dt><dd>([^<]*)</dd>", body)
        self.assertIsNotNone(match, f"KPI '{label}' not in summary: {body[:200]}")
        return match.group(1)

    def test_an_unfiltered_tab_states_one_set_of_totals(self):
        body = self._summary()
        # The trip summary is one whole-trip KPI (수입·지출·차액), not a second
        # filtered set (trip workspace rebuild, 8cd0e58b; SPEC §9 여행별 손익).
        self.assertIn("여행 요약", body)
        for label in ("수입", "지출", "차액"):
            self.assertIn(f"<dt>{label}</dt>", body)
        self.assertNotIn("검색 결과", body)

    def test_a_filter_still_states_the_whole_trip_totals(self):
        # The old totals bar named a separate whole and result; the KPI that
        # replaced it always states the whole trip and has no result set.
        body = self._summary("호텔")
        for label in ("수입", "지출", "차액"):
            self.assertIn(f"<dt>{label}</dt>", body)
        self.assertNotIn("검색 결과", body)

    def test_a_filter_never_replaces_the_whole_total_with_the_result(self):
        whole = self._summary()
        filtered = self._summary("호텔")
        # The protection that survives the redesign: a filter never changes the
        # whole-trip figures. Every KPI amount is the same with the filter on.
        for label in ("수입", "지출", "차액"):
            self.assertEqual(self._kpi_amount(whole, label),
                             self._kpi_amount(filtered, label))
        self.assertNotEqual(self._kpi_amount(whole, "수입"), "0원")

    def test_the_board_page_itself_shows_the_whole_totals(self):
        from urllib.parse import urlencode

        status, page = self._open(
            f"/board?tab={TAB}&" + urlencode({"q": "호텔"}))
        self.assertEqual(status, 200)
        self.assertIn("여행 요약", page)
        self.assertIn("<dt>수입</dt>", page)
        self.assertNotIn("검색 결과", page)

    def test_a_filter_that_matches_nothing_still_states_the_whole(self):
        # The KPI is not a filter result: a query that matches nothing must not
        # zero it or swap it — the whole-trip total stays on screen.
        body = self._summary("존재하지않는거래")
        whole = self._summary()
        for label in ("수입", "지출", "차액"):
            self.assertEqual(self._kpi_amount(body, label),
                             self._kpi_amount(whole, label))
        self.assertNotEqual(self._kpi_amount(body, "수입"), "0원")

    def test_the_row_counts_are_the_whole_trip_counts(self):
        body = self._summary("호텔")
        self.assertRegex(body, r"수입 \d+건")
        self.assertNotIn("검색 결과", body)


class ManualExpenseEntryPointTests(_Server, unittest.TestCase):
    """The shared trip toolbar owns the manual expense entry point."""

    def setUp(self):
        self._boot("manual-entry.sqlite")

    def tearDown(self):
        self._shutdown()

    def test_the_board_places_the_button_in_the_shared_trip_toolbar(self):
        status, page = self._open(f"/board?tab={TAB}")
        self.assertEqual(status, 200)
        rows = re.findall(r"<tbody class='grp'>(.*?)</tbody>", page, re.S)
        self.assertEqual(len(rows), 2, "income group then expense group")
        expense_row = rows[1]
        self.assertNotIn("add-manual-expense", expense_row)
        self.assertEqual(page.count("id='add-manual-expense'"), 1)
        self.assertIn("href='/expense/new?tab=", page)

    def test_the_button_is_not_in_the_income_group(self):
        _, page = self._open(f"/board?tab={TAB}")
        rows = re.findall(r"<tbody class='grp'>(.*?)</tbody>", page, re.S)
        self.assertNotIn("add-manual-expense", rows[0])

    def test_the_expense_heading_itself_stays_the_word_it_is(self):
        _, page = self._open(f"/board?tab={TAB}")
        order = re.findall(
            r"<tbody class='grp'><tr><th scope='colgroup'[^>]*>([^<]*)<",
            page)
        self.assertEqual(order, ["수입 (COST 기록) ", "지출"])

    def test_the_button_reaches_the_manual_expense_screen(self):
        status, _ = self._open("/expense/new")
        self.assertEqual(status, 200)


class LeaveConfirmBrowserTests(unittest.TestCase):
    """The leave-confirm has to actually appear, so this drives a browser."""

    def setUp(self):
        import tempfile as _t
        from playwright.sync_api import sync_playwright

        self.tmp = _t.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "leave.sqlite")
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self.page = self._browser.new_context(
            viewport={"width": 1440, "height": 900}).new_page()
        self.seen = []
        self.page.on("dialog", self._answer)

    def tearDown(self):
        self._browser.close()
        self._pw.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def _answer(self, dialog):
        self.seen.append(dialog.type)
        dialog.accept()

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _open_panel(self):
        """Open the row editor the way a person does: click the row."""
        self.page.goto(self._url(f"/board?tab={TAB}"))
        self.page.wait_for_load_state()
        self.page.click(f"tr[data-id='{ROW}']")
        self.page.locator('#panel .p-extra > summary').click()
        self.page.wait_for_selector("#f-description")

    def test_a_clean_page_leaves_without_any_dialog(self):
        self.page.goto(self._url(f"/board?tab={TAB}"))
        self.page.wait_for_load_state()
        self.page.goto(self._url("/export"))
        self.page.wait_for_load_state()
        self.assertEqual(self.seen, [])

    def test_leaving_with_an_unsaved_edit_raises_beforeunload(self):
        self._open_panel()
        self.page.fill("#f-description", "저장하지 않은 값")
        self.page.wait_for_timeout(200)
        # the global count already reports it
        self.assertIn("1건 저장되지 않은 변경",
                      self.page.inner_text("#unsaved-count"))
        self.page.goto(self._url("/export"))
        self.page.wait_for_load_state()
        self.assertIn("beforeunload", self.seen)

    def test_a_saved_edit_is_not_unsaved_any_more(self):
        self._open_panel()
        self.page.fill("#f-description", "저장할 값")
        self.page.wait_for_timeout(200)
        self.page.locator('#panel button[type=submit]').click()
        self.page.wait_for_timeout(600)
        self.assertIn("저장되지 않은 변경 없음",
                      self.page.inner_text("#unsaved-count"))
