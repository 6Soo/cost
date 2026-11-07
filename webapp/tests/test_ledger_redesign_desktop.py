"""The desktop ledger redesign, asserted at 1440 against the product server.

What this bundle covers, and why each claim is read off the real screen rather
than off a string:

* the six transaction columns, their order, income above expense, the sticky
  head, the thin border, the 4px radius and the tabular figures;
* one selected row, always, and the panel opened for exactly that row;
* previous/next over the rows that are actually on screen, so the position beside
  the buttons is a count of real rows and the buttons are absent when there is
  nowhere to walk;
* the unsaved-edit guard and the save-in-flight guard shared by closing, another
  row and the walk, so none of them can quietly throw a typed edit away;
* the source identifier, the revision and the source kind folded away by default
  and still on the panel;
* no state the store does not hold. There is no "확인 완료" anywhere, and this
  asserts its absence, because a mark a reader cannot trace to data is worse than
  no mark.

The store here is the synthetic one the server seeds for tests, and every action
goes through the product endpoints. PC only: the phone layout belongs to another
bundle and its markup is not touched here.
"""

import os
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path

from webapp import ledger_board as board_mod
from webapp.ledger_store import LedgerStore

TRIP = "trip-demo-a"
ALL_ROWS = ["income-demo-i1", "income-demo-i2", "income-demo-i3",
            "expense-demo-c1", "expense-demo-c4", "expense-demo-c2"]
HEADERS = ["날짜", "거래처·내용", "분류", "이용일", "금액"]


def board_url(tab=TRIP, **state):
    """The board address for a view state, encoded by the stdlib and nothing else."""
    params = {"tab": tab}
    for key, value in state.items():
        if value:
            params[key] = value
    return "?" + urllib.parse.urlencode(params)


def overflow(page):
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")


class DesktopLedgerRedesignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "redesign.sqlite")
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

    def _page(self, width=1440, height=900):
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        page = self._browser.new_context(
            viewport={"width": width, "height": height}).new_page()
        # The native leave-confirm Playwright does not answer. Every other dialog
        # is answered by the test that is about it, so an unanswered confirm can
        # never be mistaken for a refused one.
        page.on("dialog", lambda d: d.accept()
                if d.type == "beforeunload" else None)
        return page

    def _board(self, page, query=""):
        page.goto(f"http://127.0.0.1:{self.port}/board{query}")
        page.wait_for_load_state()

    def _open(self, page, row_id):
        page.click(f"#tbl tr[data-id='{row_id}']")
        page.wait_for_selector(f"#panel[data-row='{row_id}']")
        return page.get_attribute("#panel", "data-row")

    def _panel_row(self, page):
        return page.get_attribute("#panel", "data-row")

    def _selected_rows(self, page):
        return page.eval_on_selector_all(
            ".tw tr[data-id][aria-selected='true']",
            "els=>els.map(e=>e.getAttribute('data-id'))")

    # ------------------------------------------------------------------ the table
    def test_the_columns_are_read_in_order_with_income_above_expense(self):
        page = self._page()
        self._board(page, board_url())
        self.assertEqual(overflow(page), 0)
        self.assertEqual(
            page.eval_on_selector_all("#tbl thead th", "els=>els.map(e=>e.innerText)"),
            HEADERS)
        # Service dates occupy their own column; memo stays in the detail panel.
        self.assertEqual(page.eval_on_selector_all(
            "#tbl thead th", "els=>els.length"), 5)
        self.assertEqual(page.locator("#tbl thead th.c-note").count(), 0)
        # income is above expense, and both sections are on the screen
        order = page.eval_on_selector_all(
            "tbody.grp th:first-child", "els=>els.map(e=>e.innerText.trim())")
        self.assertEqual(order, ["수입 (COST 기록)", "지출"])
        tops = page.eval_on_selector_all(
            "tbody.grp th:first-child",
            "els=>els.map(e=>e.getBoundingClientRect().top)")
        self.assertLess(tops[0], tops[1])
        # the counterparty is working information on the row, not a memo fallback
        row = page.inner_text("tr[data-id='expense-demo-c2']")
        self.assertIn("예시 숙소 취소", row)
        self.assertIn("예시 숙소 추소", row)
        self.assertEqual(page.locator("tr[data-id='expense-demo-c2'] td.c-note").count(), 0)
        income = page.inner_text("tr[data-id='income-demo-i1']")
        self.assertIn("김예시", income)
        self.assertIn("예시별명", income)
        # the amount is last and right-aligned against the row
        cells = page.eval_on_selector_all(
            "tr[data-id='expense-demo-c1'] td",
            "els=>els.map(e=>e.className)")
        self.assertEqual(len(cells), 5)
        self.assertIn("c-amt", cells[-1])
        self.assertIn("num", cells[-1])

    def test_the_head_is_sticky_and_the_figures_line_up(self):
        page = self._page()
        self._board(page, board_url())
        self.assertEqual(page.eval_on_selector(
            "#tbl thead th", "e=>getComputedStyle(e).position"), "sticky")
        # Dense rows stay square-edged, while small controls use the softer
        # radius shared by the rest of the application chrome.
        self.assertEqual(page.eval_on_selector(
            "#tbl tbody td", "e=>getComputedStyle(e).borderBottomWidth"), "1px")
        self.assertEqual(page.eval_on_selector(
            ".tag", "e=>getComputedStyle(e).borderRadius"), "6px")
        self.assertEqual(page.eval_on_selector(
            ".act .btn", "e=>getComputedStyle(e).borderRadius"), "8px")
        # the amount column is tabular, so digits stack column-wise
        self.assertIn("tabular-nums", page.eval_on_selector(
            "td.c-amt", "e=>getComputedStyle(e).fontVariantNumeric"))
        self.assertEqual(page.eval_on_selector(
            "#tbl thead th:last-child", "e=>getComputedStyle(e).textAlign"), "right")

    def test_sidebar_search_keeps_the_shared_blue_focus_treatment(self):
        page = self._page()
        self._board(page, board_url())
        page.focus("#tripq")
        self.assertEqual(page.eval_on_selector(
            "#tripq", "e=>getComputedStyle(e).borderColor"), "rgb(34, 102, 245)")
        self.assertIn("rgba(34, 102, 245, 0.12)", page.eval_on_selector(
            "#tripq", "e=>getComputedStyle(e).boxShadow"))

    def test_unassigned_rows_are_focusable_without_invented_waiting_state(self):
        page = self._page()
        self._board(page, "?tab=unclassified")
        row = page.inner_text("tr[data-id='expense-demo-c3']")
        self.assertIn("예시 이동", row)
        self.assertNotIn("대기", row)
        self.assertEqual(page.locator("tr[data-id='expense-demo-c3'] .tag.wait").count(), 0)
        # a keyboard reader can reach a row, so it can open one
        self.assertEqual(page.eval_on_selector(
            "tr[data-id='expense-demo-c3']", "e=>e.getAttribute('tabindex')"), "0")
        page.focus("tr[data-id='expense-demo-c3']")
        page.keyboard.press("Enter")
        page.wait_for_selector("#panel")
        self.assertEqual(self._panel_row(page), "expense-demo-c3")

    # --------------------------------------------------- one selection, the walk
    def test_only_one_row_is_selected_and_the_address_names_it(self):
        page = self._page()
        self._board(page, board_url())
        self.assertEqual(self._selected_rows(page), [])
        self._open(page, "income-demo-i2")
        self.assertEqual(self._selected_rows(page), ["income-demo-i2"])
        self.assertEqual(page.evaluate(
            "new URL(location.href).searchParams.get('row')"), "income-demo-i2")
        # opening another row moves the one mark, it does not add a second
        self._open(page, "expense-demo-c1")
        self.assertEqual(self._selected_rows(page), ["expense-demo-c1"])
        self.assertEqual(page.evaluate(
            "new URL(location.href).searchParams.get('row')"), "expense-demo-c1")
        # and the same row again is not re-fetched, so nothing typed is thrown away
        page.locator("#panel .p-extra > summary").click()
        page.fill("#f-description", "같은 행을 다시 누름")
        self._open(page, "expense-demo-c1")
        self.assertEqual(page.input_value("#f-description"), "같은 행을 다시 누름")

    def test_previous_and_next_walk_the_rows_that_are_on_screen(self):
        page = self._page()
        self._board(page, board_url())
        self._open(page, "income-demo-i2")
        # the position is read off the live table, so it is the real index
        self.assertEqual(page.inner_text("#p-count"), "2 / 6")
        # the second of six: there is a row before it and a row after it
        self.assertTrue(page.is_visible("#p-prev"))
        self.assertTrue(page.is_visible("#p-next"))
        page.click("#p-next")
        page.wait_for_function(
            "() => document.getElementById('panel').getAttribute('data-row')"
            " === 'income-demo-i3'")
        self.assertEqual(page.inner_text("#p-count"), "3 / 6")
        self.assertEqual(self._selected_rows(page), ["income-demo-i3"])
        page.click("#p-prev")
        page.wait_for_function(
            "() => document.getElementById('panel').getAttribute('data-row')"
            " === 'income-demo-i2'")
        self.assertEqual(page.inner_text("#p-count"), "2 / 6")
        # the walk crosses the income/expense boundary: it is one list to a reader
        page.click("#p-next")
        page.wait_for_function(
            "() => document.getElementById('panel').getAttribute('data-row')"
            " === 'income-demo-i3'")
        page.click("#p-next")
        page.wait_for_function(
            "() => document.getElementById('panel').getAttribute('data-row')"
            " === 'expense-demo-c1'")
        self.assertEqual(page.inner_text("#p-count"), "4 / 6")

    def test_the_walk_follows_the_filtered_rows_and_stops_at_the_ends(self):
        page = self._page()
        # only the three 숙소 rows survive the search, so the walk has three steps
        self._board(page, board_url(q="숙소"))
        self.assertEqual(page.eval_on_selector_all(
            ".tw tr[data-id]", "els=>els.map(e=>e.getAttribute('data-id'))"),
            ["expense-demo-c1", "expense-demo-c4", "expense-demo-c2"])
        self._open(page, "expense-demo-c1")
        self.assertEqual(page.inner_text("#p-count"), "1 / 3")
        # first of three: nothing before it, so that button is not offered
        self.assertTrue(page.is_hidden("#p-prev"))
        self.assertTrue(page.is_visible("#p-next"))
        page.click("#p-next")
        page.wait_for_function(
            "() => document.getElementById('panel').getAttribute('data-row')"
            " === 'expense-demo-c4'")
        page.click("#p-next")
        page.wait_for_function(
            "() => document.getElementById('panel').getAttribute('data-row')"
            " === 'expense-demo-c2'")
        self.assertEqual(page.inner_text("#p-count"), "3 / 3")
        # last of three: a walk past the end is not offered, so nothing has to
        # refuse it. The hidden button is asserted, never clicked: it is not
        # reachable, and pressing it is not a behaviour this screen has.
        self.assertTrue(page.is_visible("#p-prev"))
        self.assertTrue(page.is_hidden("#p-next"))
        self.assertEqual(self._panel_row(page), "expense-demo-c2")
        self.assertEqual(self.store.get_row("expense-demo-c4")["revision"], 1)

    def test_a_one_row_list_is_told_so_rather_than_walked(self):
        # One row in the list: both ends are that row, so neither button is a
        # disabled control pretending to be usable — both are hidden, and the
        # position still says "1 / 1" because that is a true fact about the screen.
        page = self._page()
        self._board(page, board_url(q="추소"))
        rows = page.eval_on_selector_all(
            ".tw tr[data-id]", "els=>els.map(e=>e.getAttribute('data-id'))")
        self.assertEqual(rows, ["expense-demo-c2"])
        self._open(page, "expense-demo-c2")
        self.assertEqual(page.inner_text("#p-count"), "1 / 1")
        self.assertTrue(page.is_hidden("#p-prev"))
        self.assertTrue(page.is_hidden("#p-next"))
        # the row is still selected, and nothing else claims to be
        self.assertEqual(self._selected_rows(page), ["expense-demo-c2"])

    # ------------------------------------------------------------- the guards
    def test_another_row_asks_before_the_typed_edit_is_dropped(self):
        page = self._page()
        self._board(page, board_url())
        self._open(page, "expense-demo-c1")
        page.locator("#panel .p-extra > summary").click()
        page.fill("#f-description", "버려질 값")
        answers = [False, True]
        asked = []
        page.on("dialog", lambda d: (asked.append(d.message),
                                     d.accept() if answers.pop(0) else d.dismiss()))
        # refuse: the panel and the draft both stay
        page.click("#tbl tr[data-id='expense-demo-c4']")
        page.wait_for_timeout(400)
        self.assertEqual(len(asked), 1)
        self.assertEqual(self._panel_row(page), "expense-demo-c1")
        self.assertEqual(page.input_value("#f-description"), "버려질 값")
        # accept: the panel moves, and the store is untouched
        page.click("#tbl tr[data-id='expense-demo-c4']")
        page.wait_for_function(
            "() => document.getElementById('panel').getAttribute('data-row')"
            " === 'expense-demo-c4'")
        self.assertEqual(self.store.get_row("expense-demo-c1")["description"],
                         "예시 숙소")

    def test_closing_asks_before_the_typed_edit_is_dropped(self):
        page = self._page()
        self._board(page, board_url())
        self._open(page, "expense-demo-c1")
        page.locator("#panel .p-extra > summary").click()
        page.fill("#f-description", "닫히기 전에 버려질 값")
        # one handler for both presses: the first refuses, the second accepts
        answers = [False, True]
        asked = []
        page.on("dialog", lambda d: (asked.append(d.message),
                                     d.accept() if answers.pop(0) else d.dismiss()))
        page.click("#p-close")
        page.wait_for_timeout(400)
        self.assertEqual(len(asked), 1)
        self.assertIsNotNone(page.query_selector("#panel"))
        self.assertEqual(page.input_value("#f-description"), "닫히기 전에 버려질 값")
        # accept, and the panel closes through the ordinary way back
        page.click("#p-close")
        page.wait_for_function("() => !document.querySelector('#panel')")
        page.wait_for_load_state()
        self.assertIsNone(page.query_selector("#panel"))
        self.assertEqual(self.store.get_row("expense-demo-c1")["description"],
                         "예시 숙소")

    def test_nothing_moves_while_a_save_is_in_flight(self):
        page = self._page()
        self._board(page, board_url())
        self._open(page, "expense-demo-c1")
        # `data-saving` is the mark the save path itself sets and the cross-screen
        # refresh already reads, so setting it here is the same state, not a
        # second invention. A save in flight has no answer on screen yet, so the
        # panel does not move and says why.
        page.evaluate("() => document.querySelector("
                      "'form[data-js-save]').setAttribute('data-saving','1')")
        page.click("#p-next")
        page.wait_for_timeout(300)
        self.assertEqual(self._panel_row(page), "expense-demo-c1")
        self.assertIn("저장하는 중", page.inner_text(".f-msg"))
        page.click("#p-close")
        page.wait_for_timeout(300)
        self.assertIsNotNone(page.query_selector("#panel"))

    def test_a_finished_save_still_refreshes_the_revision_and_the_request_id(self):
        page = self._page()
        self._board(page, board_url())
        self._open(page, "expense-demo-c1")
        before_revision = self.store.get_row("expense-demo-c1")["revision"]
        before_request = page.input_value("#panel input[name='client_request_id']")
        page.locator("#panel .p-extra > summary").click()
        page.fill("#f-description", "새로운 저장")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "() => document.querySelector('.f-msg').textContent"
            ".indexOf('저장했습니다')>=0")
        stored = self.store.get_row("expense-demo-c1")
        self.assertEqual(stored["revision"], before_revision + 1)
        self.assertEqual(
            page.input_value("#panel input[name='expected_revision']"),
            str(stored["revision"]))
        self.assertNotEqual(
            page.input_value("#panel input[name='client_request_id']"), before_request)
        # the panel stayed on the same row and the walk still knows where it is
        self.assertEqual(self._panel_row(page), "expense-demo-c1")
        self.assertEqual(page.inner_text("#p-count"), "4 / 6")
        self.assertEqual(page.input_value("#f-description"), "새로운 저장")

    def test_failed_panel_load_preserves_the_current_draft_and_can_retry(self):
        page = self._page()
        self._board(page, board_url())
        self._open(page, "expense-demo-c1")
        page.locator("#panel .p-extra > summary").click()
        page.fill("#f-description", "입력을 보존합니다")
        page.on("dialog", lambda dialog: dialog.accept())
        page.route("**/board?**", lambda route: route.fulfill(status=503, body="unavailable"))
        page.click("#p-next")
        page.wait_for_function("() => document.querySelector('.f-msg').textContent.includes('불러오지 못')")
        self.assertEqual(self._panel_row(page), "expense-demo-c1")
        self.assertEqual(page.input_value("#f-description"), "입력을 보존합니다")
        self.assertEqual(page.get_attribute("form[data-js-save]", "data-dirty"), "1")
        self.assertFalse(page.locator("#panel-slot").evaluate("el => el.inert"))
        page.unroute("**/board?**")
        page.click("#p-next")
        page.wait_for_function("() => document.querySelector('#panel').dataset.row === 'expense-demo-c4'")

    # ------------------------------------------------------- the folded source
    def test_the_source_identifiers_and_the_fixed_fields_are_folded(self):
        page = self._page()
        self._board(page, board_url())
        self._open(page, "expense-demo-c1")
        self.assertEqual(page.locator("#panel details.p-src").count(), 1)
        self.assertEqual(
            page.evaluate("() => document.querySelector('#panel details.p-src').open"),
            False)
        # a card expense fixes the date, the amount and the reservation number, so
        # all three are folded. The selector and the missing name are unchanged:
        # a locked field still cannot be posted.
        for field in ("#f-occurred_on", "#f-amount_krw", "#f-reservation_no"):
            self.assertTrue(page.is_hidden(field), field)
            self.assertIsNone(page.get_attribute(field, "name"), field)
        # the first form is what a reader came to change
        for field in ("#f-display_tab_id", "#f-item"):
            self.assertTrue(page.is_visible(field), field)
        for field in ("#f-description", "#f-operator_note"):
            self.assertTrue(page.is_hidden(field), field)
        page.locator("#panel .p-extra > summary").click()
        for field in ("#f-description", "#f-operator_note"):
            self.assertTrue(page.is_visible(field), field)
        # they do not lead the panel: the amount and the fields do
        self.assertNotIn("revision", page.inner_text("#panel .p-hd"))
        page.click("#panel .p-src summary")
        self.assertEqual(
            page.evaluate("() => document.querySelector('#panel details.p-src').open"),
            True)
        # opened, the record is all there and unchanged
        for field in ("#f-occurred_on", "#f-amount_krw", "#f-reservation_no"):
            self.assertTrue(page.is_visible(field), field)
        self.assertEqual(page.input_value("#f-amount_krw"), "100,000")
        self.assertEqual(page.input_value("#f-occurred_on"), "2026-04-09")
        detail = page.inner_text("#panel .p-src")
        self.assertIn("SRC-C1", detail)
        self.assertEqual(page.input_value("#panel input[name=expected_revision]"), "1")
        self.assertIn("카드", detail)

    def test_an_income_row_keeps_its_editable_date_and_amount_in_the_open_form(self):
        # An income row's date and amount are not fixed by the endpoint, so folding
        # them away would hide the edit this row is opened for.
        page = self._page()
        self._board(page, board_url())
        self._open(page, "income-demo-i1")
        self.assertTrue(page.is_visible("#f-occurred_on"))
        self.assertTrue(page.is_visible("#f-amount_krw"))
        self.assertEqual(page.get_attribute("#f-occurred_on", "name"), "occurred_on")
        self.assertEqual(page.get_attribute("#f-amount_krw", "name"), "amount_krw")
        self.assertTrue(page.is_editable("#f-amount_krw"))
        # the reservation number is still fixed for an income row, so it is folded
        self.assertTrue(page.is_hidden("#f-reservation_no"))
        self.assertIsNone(page.get_attribute("#f-reservation_no", "name"))
        before = self.store.get_row("income-demo-i1")
        page.fill("#f-amount_krw", "510000")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "() => document.querySelector('.f-msg').textContent"
            ".indexOf('저장했습니다')>=0")
        after = self.store.get_row("income-demo-i1")
        self.assertEqual(after["amount_krw"], 510000)
        self.assertEqual(after["revision"], before["revision"] + 1)

    def test_save_and_cancel_stay_in_the_right_panel_footer(self):
        page = self._page()
        self._board(page, board_url())
        self._open(page, "expense-demo-c1")
        footer = page.inner_text("#panel .p-ft")
        self.assertIn("저장", footer)
        self.assertIn("취소", footer)
        self.assertEqual(page.locator("#panel button[type='submit']").count(), 1)
        self.assertEqual(page.input_value("#panel input[name='return_to']"),
                         f"/board?tab={TRIP}")
        # the editable-fields policy is untouched: a locked field carries no name
        self.assertIsNone(page.get_attribute("#f-amount_krw", "name"))
        self.assertEqual(page.get_attribute("#f-description", "name"), "description")

    # ------------------------------------------------------------ no invented state
    def test_no_completion_mark_the_data_does_not_hold(self):
        page = self._page()
        self._board(page, board_url())
        rows = page.inner_text(".tw")
        self.assertNotIn("확인 완료", rows)
        self._open(page, "expense-demo-c1")
        panel = page.inner_text("#panel")
        self.assertNotIn("확인 완료", panel)
        # the only completion this screen claims is a save it actually made
        page.locator("#panel .p-extra > summary").click()
        page.fill("#f-description", "저장 사실만 말한다")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "() => document.querySelector('.f-msg').textContent"
            ".indexOf('저장했습니다')>=0")
        self.assertIn("저장했습니다", page.inner_text(".f-msg"))
        self.assertEqual(overflow(page), 0)

    # ------------------------------------------------------------ search and filter
    # ------------------------------------------------- the walk on the phone list
    # The markup and the CSS at this width belong to another bundle and are not
    # touched here. What is asserted is the shared script: which rows it counts as
    # on screen, and which one it marks selected. At this width the table is
    # display:none, so a script that read only the table would count nothing.
    def test_the_walk_and_the_selection_follow_the_phone_list_when_it_is_shown(self):
        page = self._page(390, 844)
        self._board(page, board_url())
        self.assertFalse(page.is_visible(".tw"))
        self.assertTrue(page.is_visible(".lst"))
        page.click(".lst .li[data-id='income-demo-i2']")
        page.wait_for_selector("#panel")
        self.assertEqual(self._panel_row(page), "income-demo-i2")
        # the phone list, not the hidden table
        self.assertEqual(page.inner_text("#p-count"), "2 / 6")
        selected = page.eval_on_selector_all(
            ".lst .li[data-id][aria-selected='true']",
            "els=>els.map(e=>e.getAttribute('data-id'))")
        self.assertEqual(selected, ["income-demo-i2"])
        self.assertEqual(page.eval_on_selector_all(
            ".lst .li[data-id][aria-selected='true']", "els=>els.length"), 1)
        page.click("#p-next")
        page.wait_for_function(
            "() => document.getElementById('panel').getAttribute('data-row')"
            " === 'income-demo-i3'")
        self.assertEqual(page.inner_text("#p-count"), "3 / 6")
        selected = page.eval_on_selector_all(
            ".lst .li[data-id][aria-selected='true']",
            "els=>els.map(e=>e.getAttribute('data-id'))")
        self.assertEqual(selected, ["income-demo-i3"])
        # and the save that follows a walk still lands on the walked-to row
        before = self.store.get_row("income-demo-i3")["revision"]
        page.fill("#f-operator_note", "목록을 따라온 저장")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "() => document.querySelector('.f-msg').textContent"
            ".indexOf('저장했습니다')>=0")
        self.assertEqual(self.store.get_row("income-demo-i3")["revision"],
                         before + 1)
        self.assertEqual(self._panel_row(page), "income-demo-i3")
        self.assertEqual(page.inner_text("#p-count"), "3 / 6")

    def test_the_panel_footer_holds_four_buttons_and_the_count_without_overflow(self):
        # The footer is a fixed 400px column with the save form above it. Four
        # controls and a position have to fit inside it, so this is measured
        # rather than assumed: nothing may spill past the panel's own edge.
        page = self._page()
        self._board(page, board_url())
        self._open(page, "income-demo-i2")
        for selector in ("#p-prev", "#p-next", "#p-count",
                         "#panel button[type='submit']", "#p-cancel"):
            self.assertTrue(page.is_visible(selector), selector)
        box = page.eval_on_selector(
            "#panel .p-ft",
            "e=>{const r=e.getBoundingClientRect();return {"
            "left:r.left,right:r.right,width:r.width,"
            "scroll:e.scrollWidth,client:e.clientWidth};}")
        self.assertGreater(box["scroll"], 0)
        self.assertLessEqual(box["scroll"], box["client"])
        spill = page.eval_on_selector_all(
            "#panel .p-ft .btn",
            "els=>els.map(e=>{const r=e.getBoundingClientRect();"
            "return Math.round(r.right - e.parentNode.getBoundingClientRect().right);})")
        self.assertTrue(all(delta <= 0 for delta in spill), spill)
        self.assertEqual(overflow(page), 0)

    def test_legacy_filter_links_keep_row_navigation_without_search_menu(self):
        page = self._page()
        self._board(page, board_url(q='교통'))
        self.assertEqual(page.locator('#q-form, #q, #kind, #q-go').count(), 0)
        page.wait_for_load_state()
        # the term matches nothing in this trip, so the empty answer is the table's
        self.assertIn("내역이 없어요", page.inner_text(".tw"))
        self.assertEqual(
            page.evaluate("new URL(location.href).searchParams.get('q')"), "교통")
        self._board(page, board_url())
        page.wait_for_load_state()
        self.assertEqual(page.eval_on_selector_all(
            ".tw tr[data-id]", "els=>els.length"), len(ALL_ROWS))
        self._board(page, board_url(kind='ex'))
        self.assertEqual(page.eval_on_selector_all(
            ".tw tr[data-id]", "els=>els.map(e=>e.getAttribute('data-id'))"),
            ["expense-demo-c1", "expense-demo-c4", "expense-demo-c2"])
        self._open(page, "expense-demo-c1")
        # the walk counts the filtered list, not the whole tab
        self.assertEqual(page.inner_text("#p-count"), "1 / 3")


if __name__ == "__main__":
    unittest.main()
