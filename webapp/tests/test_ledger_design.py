"""The A/Ramp/Pretendard design on the real ledger screen.

Real clicks at 1440 and 390 against the product server and its real store:
row edit panel, save, cancel, stale revision, classification move, upload,
select trip XLSX, rule dialog entry and return, and the static font asset.
No demo data and no demo script: every action goes through the product
endpoints.
"""

import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from webapp import ledger_board as board_mod
from webapp import ledger_design
from webapp.ledger_store import LedgerStore


def overflow(page):
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")


class DesignScreenTests(unittest.TestCase):
    def test_trip_header_controls_align_and_management_remains_keyboard_accessible(self):
        self.store.conn.execute('CREATE TABLE IF NOT EXISTS requests(request_id TEXT PRIMARY KEY, scope TEXT NOT NULL, payload_sha256 TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL)')
        self.store.conn.commit()
        for width in (320, 390, 760, 1440):
            with self.subTest(width=width):
                page = self._page(width)
                self._board(page, '?tab=trip-demo-a')
                controls = '.trip-close-form button, #trip-settings>summary, .act>a'
                boxes = page.locator(controls).evaluate_all(
                    'els=>els.map(e=>{const r=e.getBoundingClientRect();return {top:r.top,height:r.height}})')
                self.assertEqual(len(boxes), 4)
                self.assertAlmostEqual(boxes[0]['top'], boxes[1]['top'], delta=1)
                self.assertTrue(all(abs(b['height'] - boxes[0]['height']) <= 1 for b in boxes))
                self.assertEqual(overflow(page), 0)
                summary = page.locator('#trip-settings>summary')
                summary.focus()
                page.keyboard.press('Enter')
                self.assertTrue(page.locator('#trip-settings').evaluate('e=>e.open'))
                self.assertTrue(page.get_by_role('button', name='정보 저장', exact=True).is_visible())
                self.assertEqual(overflow(page), 0)
                page.keyboard.press('Enter')
                self.assertFalse(page.locator('#trip-settings').evaluate('e=>e.open'))
                page.close()

    def test_manual_expense_dialog_preserves_errors_and_saves_selected_trip(self):
        for width in (390, 1280):
            with self.subTest(width=width):
                page = self._page(width)
                self._board(page, '?tab=trip-demo-b')
                trigger = '.trip-actions #add-manual-expense'
                page.click(trigger)
                self.assertTrue(page.locator('#manual-expense-dialog').evaluate('e=>e.open'))
                self.assertEqual(page.input_value('#mx-tab'), 'trip-demo-b')
                page.fill('#mx-date', '2026-10-31')
                page.fill('#mx-desc', 'Synthetic modal expense')
                page.fill('#mx-amount', 'invalid')
                request_id = page.input_value('#manual-expense-dialog [name=client_request_id]')
                page.click('#manual-expense-dialog [type=submit]')
                page.wait_for_function("document.querySelector('.mx-error').textContent.length>0")
                self.assertEqual(page.input_value('#mx-desc'), 'Synthetic modal expense')
                self.assertEqual(page.input_value('#manual-expense-dialog [name=client_request_id]'), request_id)
                self.assertTrue(page.locator('#manual-expense-dialog').evaluate('e=>e.open'))
                self.assertEqual(overflow(page), 0)
                page.keyboard.press('Escape')
                self.assertFalse(page.locator('#manual-expense-dialog').evaluate('e=>e.open'))
                page.click(trigger)
                self.assertEqual(page.input_value('#mx-desc'), 'Synthetic modal expense')
                page.fill('#mx-amount', '-1,250')
                with page.expect_navigation():
                    page.click('#manual-expense-dialog [type=submit]')
                rows = [r for r in self.store.list_tab_rows('trip-demo-b')
                        if r.get('description') == 'Synthetic modal expense']
                self.assertEqual(len(rows), 1 + (width == 1280))
                self.assertEqual(rows[-1]['amount_krw'], -1250)
                self.assertIn('tab=trip-demo-b', page.url)
                page.close()

    def test_document_stays_in_viewport_while_ledger_and_drawer_scroll_independently(self):
        for width in (375, 390, 759, 760, 1280):
            with self.subTest(width=width):
                page = self._page(width, 600)
                self._board(page, '?tab=trip-demo-a')
                page.evaluate("""() => {
                    for (const selector of ['#main', '#nav']) {
                        const tail = document.createElement('div');
                        tail.style.height = '1800px';
                        tail.textContent = 'Synthetic scroll boundary';
                        document.querySelector(selector).append(tail);
                    }
                }""")
                if width < 760:
                    page.click('.site-menu-toggle')
                    page.wait_for_timeout(300)
                page.locator('#nav').evaluate('e => e.scrollTop = e.scrollHeight')
                self.assertGreater(page.locator('#nav').evaluate('e => e.scrollTop'), 0)
                self.assertEqual(page.locator('#main').evaluate('e => e.scrollTop'), 0)
                if width < 760:
                    page.keyboard.press('Escape')
                    page.wait_for_timeout(300)
                page.locator('#main').focus()
                page.keyboard.press('PageDown')
                page.wait_for_timeout(300)
                self.assertGreater(page.locator('#main').evaluate('e => e.scrollTop'), 0)
                page.locator('#main').evaluate('e => e.scrollTop = e.scrollHeight')
                self.assertLessEqual(page.locator('#main').evaluate(
                    'e => Math.abs(e.scrollHeight-e.clientHeight-e.scrollTop)'), 1)
                self.assertEqual(page.evaluate('window.scrollY'), 0)
                self.assertLessEqual(page.evaluate(
                    'document.documentElement.scrollHeight-innerHeight'), 1)
                self.assertEqual(overflow(page), 0)
                page.close()

    def test_sidebar_shows_trip_dates_and_board_carries_the_record_note_at_both_widths(self):
        for width in (390, 1440):
            with self.subTest(width=width):
                page = self._page(width)
                self._board(page, '?tab=trip-demo-a')
                if width == 390:
                    page.click('.site-menu-toggle')
                page.locator('#previous-trips > summary').click()
                page.locator('#previous-trips .prev-q > summary').nth(1).click()
                trip_link = page.locator('#previous-trips a[href*="tab=trip-demo-a"]').first.inner_text()
                self.assertIn('04.08~04.14', trip_link)
                self.assertNotIn('수입', trip_link)
                self.assertNotIn('미배정 지출', page.inner_text('.nav'))
                self.assertEqual(page.locator('#nav .nav-ft').count(), 1)
                self.assertEqual(page.locator('#nav .all-trips-link').count(), 1)
                self.assertEqual(page.locator('#nav .all-trips-link').get_attribute('href'), '/trips')
                self.assertIn('전체 여행 보기', page.locator('#nav .nav-ft').inner_text())
                self.assertEqual(page.locator('#nav .footer-help').count(), 0)
                self.assertEqual(page.locator('#ledger-note').count(), 0)
                self.assertNotIn('기록된 거래', page.locator('#live-sum').inner_text())
                self.assertEqual(page.locator('.act a[href="/import#newupload"]').count(), 0)
                self.assertEqual(page.locator('.nav a[href="/import"]').count(), 1)
                self.assertEqual(overflow(page), 0)
                self.assertLessEqual(page.locator('.nav').evaluate('e=>e.scrollWidth-e.clientWidth'), 0)
                page.locator('.nav a[href*="tab=trip-demo-b"]').first.click()
                page.wait_for_url('**/board?**tab=trip-demo-b**')
                self.assertEqual(overflow(page), 0)
                page.close()

    def setUp(self):
        from unittest.mock import patch
        legacy_mode = patch.dict(os.environ, {'WEBLEDGER_CARD_FLOW': '0', 'WEBLEDGER_UNIFIED_DB': '0'})
        legacy_mode.start()
        self.addCleanup(legacy_mode.stop)
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "design.sqlite")
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]), seed_demo=True)
        # the export writes real files, so keep them out of the working tree
        self._prev_export = os.environ.get("WEBLEDGER_EXPORT_DIR")
        os.environ["WEBLEDGER_EXPORT_DIR"] = str(Path(self.tmp) / "exports")
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False, seed_demo=True)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self._playwright = None
        self._browser = None

    def tearDown(self):
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        board_mod.bind_store(None)
        self.store.close()
        if self._prev_export is None:
            os.environ.pop("WEBLEDGER_EXPORT_DIR", None)
        else:
            os.environ["WEBLEDGER_EXPORT_DIR"] = self._prev_export
        if self._prev_db is None:
            os.environ.pop("WEBLEDGER_DB", None)
        else:
            os.environ["WEBLEDGER_DB"] = self._prev_db

    def _page(self, width, height=900):
        from playwright.sync_api import sync_playwright

        if self._playwright is None:
            self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        context = self._browser.new_context(
            viewport={"width": width, "height": height})
        page = context.new_page()
        # APP_SPEC 4.1 raises a native leave-confirm when an edit is
        # unsaved. Playwright does not answer that one, so the factory
        # does. Other dialogs are left to a test's own handler.
        page.on("dialog", lambda d: d.accept()
                if d.type == "beforeunload" else None)
        return page

    def _board(self, page, query=""):
        page.goto(f"http://127.0.0.1:{self.port}/board{query}")
        page.wait_for_load_state()

    def _wait_for_reload(self, page, tab):
        """Wait for the reload the move does on its own to have finished.

        A successful move writes its status line and then navigates to the same
        `unclassified` board with the message in the query string, so the screen
        ends up saying the same thing twice. Waiting on the status text alone can be
        satisfied by the document that is on screen *before* that navigation, and the
        next `goto` then races a navigation the browser has already started: two
        navigations at once, and the later one can time out waiting for a load event
        that the earlier one cancelled.

        So the wait is on the arrival, not on the text: the query string carrying the
        message is the one thing only the reloaded document can have, and the load
        state is read after it rather than instead of it. Nothing here widens a
        timeout or relaxes what is checked, it only stops the test reading the
        previous document's status as if the page had settled.
        """
        page.wait_for_url(
            lambda url: "tab=" + tab in url and "msg=" in url,
            wait_until="load")
        page.wait_for_function(
            "document.getElementById('status')"
            "&&document.getElementById('status').textContent.indexOf('옮겼습니다')>=0")

    def _api(self, path, payload=None, method="GET"):
        data = None
        headers = {}
        if payload is not None:
            import json

            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers=headers, method=method)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    # ------------------------------------------------------------ static assets
    def test_only_the_allowed_font_assets_are_served(self):
        status, body = self._api("/assets/fonts/PretendardVariable.woff2")
        self.assertEqual(status, 200)
        self.assertEqual(body[:4], b"wOF2")
        self.assertEqual(len(body), 2057688)
        status, body = self._api("/assets/fonts/OFL.txt")
        self.assertEqual(status, 200)
        self.assertIn(b"SIL OPEN FONT LICENSE", body)
        for name in ("ledger_store.py", "webapp%2Fledger_store.py", "..%2F..%2Fwebapp%2Fledger_store.py",
                     "static%2Ffonts%2FPretendardVariable.woff2", "missing.woff2"):
            status, _ = self._api(f"/assets/fonts/{name}")
            self.assertEqual(status, 404, name)
        status, _ = self._api("/assets/fonts/")
        self.assertEqual(status, 404)
        # the allowlist is the only door, whatever the module is asked for
        self.assertIsNone(ledger_design.static_asset("../ledger_board.py"))
        self.assertIsNone(ledger_design.static_asset("sub/PretendardVariable.woff2"))
        self.assertIsNotNone(ledger_design.static_asset("OFL.txt"))

    def test_the_font_is_really_loaded_in_the_browser(self):
        page = self._page(1440)
        self._board(page)
        self.assertTrue(page.evaluate(
            "document.fonts.check('14px \"Pretendard Variable\"')"))
        family = page.evaluate("getComputedStyle(document.body).fontFamily")
        self.assertIn("Pretendard Variable", family)
        loaded = page.evaluate(
            "Array.from(document.fonts).map(f=>f.family+':'+f.status).join(',')")
        self.assertIn("Pretendard Variable:loaded", loaded)

    # ------------------------------------------------------------------ layout
    def test_previous_trips_are_grouped_by_quarter_and_focus_moves_into_an_opened_group(self):
        page = self._page(1440)
        self._board(page, "?tab=trip-demo-a")
        page.locator('#previous-trips > summary').click()
        nav = page.inner_text(".nav")
        self.assertIn("1분기", nav)
        self.assertIn("2분기", nav)
        self.assertIn("3분기 기타비용", nav)
        self.assertEqual(page.locator('#previous-trips .prev-q').count(), 2)
        page.locator('#previous-trips > summary').click()
        page.locator('#previous-trips > summary').click()
        page.wait_for_timeout(50)
        self.assertIn("분기", page.evaluate("document.activeElement.textContent"))

    def test_the_1440_layout_has_the_trip_list_action_bar_and_two_tables(self):
        page = self._page(1440)
        self._board(page, "?tab=trip-demo-a")
        self.assertEqual(overflow(page), 0)
        nav = page.inner_text(".nav")
        self.assertIn("여행 목록", nav)
        self.assertFalse(page.locator('#previous-trips').evaluate('el=>el.open'))
        page.locator('#previous-trips > summary').click()
        page.locator('#previous-trips .prev-q > summary').nth(1).click()
        nav = page.inner_text(".nav")
        self.assertIn("0408_예시여행A", nav)
        self.assertNotIn("미배정 지출", nav)
        # The action bar contains management, reservation link, and export, but no secondary actions.
        self.assertEqual(page.inner_text(".act").replace("\n", " ").strip(), "마감 여행 관리 예약·참가자 XLSX 출력")
        self.assertEqual(page.locator('.secondary-actions').count(), 0)
        self.assertTrue(page.locator('#reserve-link').is_visible())
        self.assertEqual(page.locator('.act a[href="/import#newupload"]').count(), 0)
        self.assertEqual(page.locator('.nav a[href="/import"]').count(), 1)
        # income is above expense, both on the screen
        order = page.eval_on_selector_all(
            "tbody.grp th:first-child", "els=>els.map(e=>e.innerText.trim())")
        self.assertEqual(order, ["수입 (COST 기록) 수입내역 보기", "지출"])
        tops = page.eval_on_selector_all(
            "tbody.grp th:first-child", "els=>els.map(e=>e.getBoundingClientRect().top)")
        self.assertLess(tops[0], tops[1])
        self.assertIn("1,000,000원", page.inner_text("#sum"))
        self.assertIn("180,000원", page.inner_text("#sum"))
        # the mobile list is not shown at this width
        self.assertFalse(page.is_visible(".lst"))
        self.assertTrue(page.is_visible(".tw"))

    def test_one_trip_button_and_a_short_notice_at_390(self):
        page = self._page(390, 844)
        self._board(page, "?tab=trip-demo-a")
        self.assertEqual(overflow(page), 0)
        self.assertTrue(page.is_visible(".lst"))
        self.assertFalse(page.is_visible(".tw"))
        self.assertEqual(page.locator('.site-menu-toggle:visible').count(), 1)
        status = page.inner_text(".status")
        self.assertEqual(len(status.strip().split("\n")), 1)
        # the first transaction must not be pushed far down
        top = page.evaluate(
            "document.querySelector('.li').getBoundingClientRect().top")
        self.assertLess(top, page.evaluate('innerHeight'))
        # the nav drawer opens from the one button
        page.click('.site-menu-toggle')
        self.assertTrue(page.is_visible(".nav.open"))
        page.locator("#nav-mask").click(position={"x": 380, "y": 400})
        self.assertFalse(page.evaluate("document.getElementById('nav').className.includes('open')"))

    def test_the_panel_footer_stays_reachable_and_two_saves_work_at_390(self):
        # The inline editor scrolls with the list. Both actions must be reachable
        # and a second real save must still work after the status message appears.
        page = self._page(390, 844)
        # at 390 the table is hidden and the row lives in the vertical list
        self._board(page, "?tab=trip-demo-a")
        page.click(".lst .li[data-id='expense-demo-c1']")
        page.wait_for_selector("#panel")
        self.assertEqual(overflow(page), 0)

        inner_height = page.evaluate("window.innerHeight")

        def footer_box():
            return page.eval_on_selector(
                "#panel button[type='submit']",
                "e=>{const r=e.getBoundingClientRect();"
                "return {top:r.top, bottom:r.bottom};}")

        # Inline editors scroll with the document; both actions must be reachable.
        for selector in ("#panel button[type='submit']", "#p-cancel"):
            page.locator(selector).scroll_into_view_if_needed()
            box = page.eval_on_selector(
                selector, "e=>{const r=e.getBoundingClientRect();"
                          "return {top:r.top, bottom:r.bottom};}")
            self.assertLessEqual(box["bottom"], inner_height, selector)
            self.assertGreaterEqual(box["top"], 0, selector)

        page.click("#panel .p-extra > summary")

        # 2. the first save by real click
        before = self.store.get_row("expense-demo-c1")["revision"]
        page.fill("#f-description", "390 첫 번째 저장")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "document.querySelector('.f-msg')"
            "&&document.querySelector('.f-msg').textContent"
            ".indexOf('저장했습니다')>=0")
        self.assertIn("저장했습니다", page.inner_text(".f-msg"))
        self.assertEqual(
            self.store.get_row("expense-demo-c1")["revision"], before + 1)
        self.assertEqual(overflow(page), 0)

        # The footer remains reachable after the message grows the editor.
        page.locator("#panel button[type='submit']").scroll_into_view_if_needed()
        box = footer_box()
        self.assertLessEqual(box["bottom"], inner_height)
        self.assertGreaterEqual(box["top"], 0)

        # 5. the second save by real click, and it lands
        page.fill("#f-description", "390 두 번째 저장")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "document.querySelector('.f-msg')"
            "&&document.querySelector('.f-msg').textContent"
            ".indexOf('저장했습니다')>=0")
        self.assertIn("저장했습니다", page.inner_text(".f-msg"))
        stored = self.store.get_row("expense-demo-c1")
        self.assertEqual(stored["revision"], before + 2)
        self.assertEqual(stored["description"].replace(" ", ""),
                         "390두번째저장")
        self.assertLessEqual(footer_box()["bottom"],
                             page.evaluate("window.innerHeight"))
        self.assertEqual(overflow(page), 0)

    # ------------------------------------------------------------- edit panel
    def _open_panel(self, page, row_id, width=1440):
        self._board(page, "?tab=trip-demo-a")
        page.click(f"tr[data-id='{row_id}']")
        page.wait_for_selector("#panel")
        if page.locator("#panel .p-extra").count():
            page.click("#panel .p-extra > summary")
        return page.inner_text("#panel")

    def test_compact_inline_expense_layout_and_motion(self):
        """One-row edit stays compact; the inline container opens and closes smoothly."""
        instrument = """(() => {
            window.__editorMotions = [];
            const original = Element.prototype.animate;
            Element.prototype.animate = function(keyframes, options) {
                if (this.id === 'panel-slot') window.__editorMotions.push(options.duration);
                return original.call(this, keyframes, options);
            };
        })();"""
        for width in (390, 1440):
            with self.subTest(width=width):
                page = self._page(width)
                page.emulate_media(reduced_motion="no-preference")
                page.add_init_script(instrument)
                self._board(page, "?tab=trip-demo-a")
                row = (".lst .li[data-id='expense-demo-c1']" if width < 760
                       else "tr[data-id='expense-demo-c1']")
                page.click(row)
                page.wait_for_selector("#panel[data-edit-kind='expense']")
                page.wait_for_timeout(260)
                self.assertFalse(page.locator("#panel .p-extra").evaluate("el => el.open"))
                self.assertFalse(page.locator("#panel .p-src").evaluate("el => el.open"))
                self.assertTrue(page.is_visible("#f-trip-search"))
                self.assertTrue(page.is_visible("#f-display_tab_id"))
                self.assertTrue(page.is_visible("#f-item"))
                self.assertLess(page.locator("#panel").bounding_box()["height"],
                                600 if width < 760 else 350)
                self.assertEqual(overflow(page), 0)
                if width >= 760:
                    search = page.locator("#f-trip-search").bounding_box()
                    trip = page.locator("#f-display_tab_id").bounding_box()
                    item = page.locator("#f-item").bounding_box()
                    self.assertLess(abs(search["y"] - trip["y"]), 5)
                    self.assertLess(abs(trip["y"] - item["y"]), 5)
                self.assertIn(220, page.evaluate("window.__editorMotions"))
                page.click("#p-close")
                page.wait_for_selector("#panel", state="detached")
                self.assertIn(170, page.evaluate("window.__editorMotions"))
                self.assertEqual(page.locator(".inline-editor-row,.inline-editor-mobile").count(), 0)
                page.close()

    def test_reduced_motion_opens_and_closes_inline_editor_without_animation(self):
        page = self._page(390)
        page.emulate_media(reduced_motion="reduce")
        page.add_init_script("""(() => {
            window.__editorMotions = [];
            const original = Element.prototype.animate;
            Element.prototype.animate = function(keyframes, options) {
                if (this.id === 'panel-slot') window.__editorMotions.push(options.duration);
                return original.call(this, keyframes, options);
            };
        })();""")
        self._board(page, "?tab=trip-demo-a")
        page.click(".lst .li[data-id='expense-demo-c1']")
        page.wait_for_selector("#panel")
        self.assertEqual(page.evaluate("window.__editorMotions"), [])
        page.click("#p-close")
        page.wait_for_selector("#panel", state="detached")
        self.assertEqual(page.evaluate("window.__editorMotions"), [])
        page.close()

    def test_expense_extra_fields_are_collapsed_and_keyboard_accessible(self):
        page = self._page(390, 844)
        self._board(page, "?tab=trip-demo-a")
        page.click(".lst .li[data-id='expense-demo-c1']")
        page.wait_for_selector("#panel .p-extra")
        self.assertFalse(page.is_visible("#f-description"))
        summary = page.locator("#panel .p-extra > summary")
        summary.focus()
        page.keyboard.press("Enter")
        self.assertTrue(page.is_visible("#f-description"))
        page.fill("#f-description", "extra details saved")
        page.click("#panel button[type='submit']")
        page.wait_for_function("document.querySelector('.f-msg').textContent.includes('\uC800\uC7A5\uD588\uC2B5\uB2C8\uB2E4')")
        self.assertEqual(self.store.get_row("expense-demo-c1")["description"], "extra details saved")
        self.assertEqual(overflow(page), 0)

    def test_refusal_opens_collapsed_extra_field_and_focuses_it(self):
        page = self._page(1440)
        self._board(page, "?tab=trip-demo-a")
        page.click("tr[data-id='expense-demo-c1']")
        page.wait_for_selector("#panel .p-extra")
        page.route("**/api/rows/expense-demo-c1/save", lambda route: route.fulfill(
            status=400, content_type="application/json",
            body='{"code":"INVALID","field":"description","message":"Invalid value"}'))
        page.click("#panel button[type='submit']")
        page.wait_for_selector("#f-description[aria-invalid='true']")
        self.assertTrue(page.is_visible("#f-description"))
        self.assertEqual(page.evaluate("document.activeElement.id"), "f-description")
        self.assertTrue(page.locator("#panel .p-extra").evaluate("el => el.open"))

    def test_the_row_panel_keeps_the_source_locked_and_saves_for_real(self):
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c1")
        self.assertEqual(page.input_value("#f-amount_krw"), "100,000")
        self.assertFalse(page.is_editable("#f-amount_krw"))
        self.assertFalse(page.is_editable("#f-occurred_on"))
        self.assertFalse(page.is_editable("#f-reservation_no"))
        # a locked source field carries no name, so no post can send it
        self.assertEqual(page.get_attribute("#f-amount_krw", "name"), None)
        self.assertEqual(page.get_attribute("#f-description", "name"), "description")
        before = self.store.get_row("expense-demo-c1")["revision"]
        page.fill("#f-description", "예시 숙소 정정")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "document.querySelector('.f-msg').textContent.indexOf('저장했습니다')>=0")
        self.assertIn("저장했습니다", page.inner_text(".f-msg"))
        stored = self.store.get_row("expense-demo-c1")
        self.assertEqual(stored["description"].replace(" ", ""), "예시숙소정정")
        self.assertEqual(stored["revision"], before + 1)
        # the panel shows the new revision, and the summary was re-read
        self.assertEqual(
            page.input_value("#panel input[name='expected_revision']"),
            str(stored["revision"]))
        self.assertIn("180,000원", page.inner_text("#sum"))
        self.assertIn("1,000,000원", page.inner_text("#sum"))

    def test_cancel_closes_the_panel_and_changes_nothing(self):
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c4")
        before = self.store.get_row("expense-demo-c4")
        page.fill("#f-description", "취소되어야 하는 값")
        page.once("dialog", lambda dialog: dialog.accept())
        page.click("#p-cancel")
        page.wait_for_selector("#panel", state="detached")
        page.wait_for_load_state()
        self.assertIsNone(page.query_selector("#panel"))
        after = self.store.get_row("expense-demo-c4")
        self.assertEqual(after["description"], before["description"])
        self.assertEqual(after["revision"], before["revision"])

    def test_enter_alone_does_not_save_and_ctrl_enter_does(self):
        # DETAILED_CONTRACT 12.3: Enter must not quietly save a whole row, and
        # the shortcut that does is printed on the button.
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c1")
        before = self.store.get_row("expense-demo-c1")
        page.fill("#f-description", "엔터로는 저장되면 안 됨")
        page.focus("#f-description")
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        mid = self.store.get_row("expense-demo-c1")
        self.assertEqual(mid["description"], before["description"])
        self.assertEqual(mid["revision"], before["revision"])
        # the visible hint names the shortcut
        self.assertIn("Ctrl", page.inner_text("#panel .p-ft"))
        # the explicit shortcut saves. Wait for the finished reply rather than
        # the "saving" placeholder, then let the store settle before reading it.
        page.keyboard.press("Control+Enter")
        page.wait_for_function(
            "() => document.querySelector('.f-msg')"
            ".textContent.indexOf('저장했습니다')>=0")
        after = before
        for _ in range(100):
            after = self.store.get_row("expense-demo-c1")
            if after["revision"] == before["revision"] + 1:
                break
            page.wait_for_timeout(50)
        self.assertEqual(after["description"], "엔터로는 저장되면 안 됨")
        self.assertEqual(after["revision"], before["revision"] + 1)

    def test_enter_in_a_note_keeps_its_newline(self):
        # A note needs line breaks, so Enter there must not be swallowed and
        # must not turn into a save.
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c1")
        before = self.store.get_row("expense-demo-c1")
        page.click("#f-operator_note")
        page.keyboard.type("첫 줄")
        page.keyboard.press("Enter")
        page.keyboard.type("둘째 줄")
        value = page.input_value("#f-operator_note")
        self.assertIn("\n", value)
        self.assertTrue(value.startswith("첫 줄"))
        # a newline in a note is not a save
        page.wait_for_timeout(300)
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"],
                         before["revision"])

    def test_escape_asks_before_dropping_an_unsaved_edit(self):
        # Escape cancels the current edit and never undoes a saved change.
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c1")
        before = self.store.get_row("expense-demo-c1")
        page.fill("#f-description", "버려질 값")
        # One handler for both presses: the first refuses, the second accepts.
        answers = [False, True]
        asked = []
        page.on("dialog", lambda d: (asked.append(d.message),
                                     d.accept() if answers.pop(0) else d.dismiss()))
        # refuse the confirmation: the panel stays and the draft stays
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        self.assertEqual(len(asked), 1)
        self.assertIsNotNone(page.query_selector("#panel"))
        self.assertEqual(page.input_value("#f-description"), "버려질 값")
        # accept it: the panel closes and nothing was written
        page.keyboard.press("Escape")
        page.wait_for_function("() => !document.querySelector('#panel')")
        page.wait_for_load_state()
        self.assertIsNone(page.query_selector("#panel"))
        self.assertEqual(len(asked), 2)
        after = self.store.get_row("expense-demo-c1")
        self.assertEqual(after["description"], before["description"])
        self.assertEqual(after["revision"], before["revision"])

    def test_escape_closes_a_clean_panel_without_asking(self):
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c1")
        asked = []
        page.on("dialog", lambda d: (asked.append(d.message), d.dismiss()))
        page.keyboard.press("Escape")
        page.wait_for_function("() => !document.querySelector('#panel')")
        page.wait_for_load_state()
        self.assertIsNone(page.query_selector("#panel"))
        # nothing was edited, so there is nothing to confirm
        self.assertEqual(asked, [])

    def test_a_refused_field_is_named_next_to_the_input_and_focused(self):
        # The error is not colour alone and the first error takes focus.
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c1")
        before = self.store.get_row("expense-demo-c1")
        page.evaluate("""() => {
            const f = document.querySelector("form[data-js-save]");
            const bad = document.createElement("input");
            bad.name = "amount_krw"; bad.type = "text"; bad.id = "probe-amount";
            f.appendChild(bad);
        }""")
        page.fill("#probe-amount", "999999")
        page.keyboard.press("Control+Enter")
        page.wait_for_function(
            "document.querySelector('.f-msg').className.indexOf('err')>=0")
        self.assertEqual(page.get_attribute("#probe-amount", "aria-invalid"),
                         "true")
        # the field carries a text flag, not only a colour
        self.assertIsNotNone(page.query_selector("#probe-amount ~ .f-flag, "
                                                 ".f-flag"))
        self.assertEqual(page.evaluate(
            "() => document.activeElement.id"), "probe-amount")
        # the fixed amount was not changed
        self.assertEqual(self.store.get_row("expense-demo-c1")["amount_krw"],
                         before["amount_krw"])

    def test_a_stale_revision_is_reported_and_the_typed_value_is_kept(self):
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c1")
        page.fill("#f-description", "첫 번째 저장")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "document.querySelector('.f-msg').textContent.indexOf('저장했습니다')>=0")
        # someone else saves the same row afterwards
        status, _ = self._api("/api/rows/expense-demo-c1/save", {
            "csrf": board_mod.CSRF_TOKEN,
            "expected_revision": self.store.get_row("expense-demo-c1")["revision"],
            "client_request_id": "design-other-writer",
            "change_mode": "exception",
            "item": "다른 사람이 바꿈",
        }, method="POST")
        self.assertEqual(status, 200)
        page.fill("#f-description", "내 입력은 남아 있어야 해요")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "document.querySelector('.f-msg').className.indexOf('err')>=0")
        message = page.inner_text(".f-msg")
        self.assertIn("EDIT_CONFLICT", message)
        self.assertEqual(page.input_value("#f-description"), "내 입력은 남아 있어야 해요")
        self.assertEqual(self.store.get_row("expense-demo-c1")["item"], "다른 사람이 바꿈")

    def test_the_rule_dialog_opens_from_the_panel_and_comes_back(self):
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c1")
        page.select_option("#f-change_mode", "rule_change")
        page.fill("#f-description", "규칙으로 남길 값")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "document.querySelector('.f-msg').textContent.indexOf('저장했습니다')>=0")
        page.wait_for_selector("#rule-open:not([hidden])")
        case = self.store.conn.execute(
            "SELECT case_id FROM board_learning_cases WHERE row_id=?",
            ("expense-demo-c1",)).fetchone()[0]
        self.assertEqual(page.get_attribute("#rule-open", "href"), f"/rules?case={case}")
        page.click("#rule-open")
        page.wait_for_load_state()
        body = page.inner_text("body")
        self.assertIn("규칙 대화", body)
        self.assertIn("합성 모드입니다", body)
        self.assertNotIn("expense-demo-c1", body)
        self.assertEqual(page.get_by_role('link', name='내용으로 돌아가기').get_attribute('href'),
                         '/row?id=expense-demo-c1')
        # the way back to the ledger is there from the first screen
        page.click("text=목록으로")
        page.wait_for_load_state()
        self.assertIn("여행 목록", page.inner_text(".nav"))
        self.assertEqual(
            page.locator("tr[data-id='expense-demo-c1']").count(), 1)
        self.assertIn("규칙으로 남길 값",
                      page.inner_text("tr[data-id='expense-demo-c1']"))
        # and the dialog can be started, closed and resumed without losing it
        page.click(f"tr[data-id='expense-demo-c1']")
        page.wait_for_selector("#panel")
        page.click("#rule-open")
        page.wait_for_load_state()
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
        self.assertEqual(
            self.store.rule_dialog_state(case)["answers"].get("rule_kind"), None)

    def test_the_panel_keeps_the_existing_links_reachable(self):
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c1")
        links = page.eval_on_selector_all(
            ".p-links a", "els=>els.map(a=>a.getAttribute('href'))")
        self.assertIn("/row?id=expense-demo-c1", links)
        self.assertIn("/trips", links)
        self.assertIn("/export", links)
        page.click(".p-links a[href='/row?id=expense-demo-c1']")
        page.wait_for_load_state()
        self.assertIn("변경 이력", page.inner_text("body"))
        # the allocation screen and the trip screen both answer
        status, _ = self._api("/trips")
        self.assertEqual(status, 200)
        status, _ = self._api("/income/income-demo-i1/split")
        self.assertEqual(status, 200)
        status, _ = self._api("/export")
        self.assertEqual(status, 200)

    def test_the_income_panel_offers_the_bank_fields_and_the_split_link(self):
        page = self._page(1440)
        self._open_panel(page, "income-demo-i1")
        self.assertEqual(page.get_attribute("#f-customer_name", "name"), "customer_name")
        self.assertIn("배분", page.inner_text(".p-links"))
        self.assertTrue(page.is_editable("#f-customer_name"))

    # ------------------------------------------------- classification waiting
    def test_a_waiting_row_moves_to_a_trip_from_the_list(self):
        page = self._page(1440)
        self._board(page, "?tab=unclassified")
        self.assertIn("30,000원", page.inner_text("#sum"))
        self.assertEqual(len(self.store._unclassified_rows()) if hasattr(
            self.store, "_unclassified_rows") else 1, 1)
        page.select_option("#move-expense-demo-c3", "trip-demo-b")
        page.click("form[data-js-move] button[type='submit']")
        # the move reloads the bucket it came from; wait for that to land before
        # reading the store or going anywhere else
        self._wait_for_reload(page, "unclassified")
        row = self.store.get_row("expense-demo-c3")
        self.assertEqual(row["display_tab_id"], "trip-demo-b")
        self.assertEqual(row["revision"], 2)
        # the other trip's total picked it up
        self._board(page, "?tab=trip-demo-b")
        self.assertIn("30,000원", page.inner_text("#sum"))

    def test_the_waiting_move_works_at_390_with_a_full_width_control(self):
        page = self._page(390, 844)
        self._board(page, "?tab=unclassified")
        self.assertEqual(overflow(page), 0)
        page.select_option(".lst form[data-js-move] select[name='display_tab_id']",
                           "trip-demo-a")
        page.click(".lst form[data-js-move] button[type='submit']")
        # same reload as the desktop form: this one is a control-width and overflow
        # test, so it does not navigate afterwards, but the status it can read is
        # the one on the reloaded document rather than the one about to be discarded
        self._wait_for_reload(page, "unclassified")
        self.assertEqual(self.store.get_row("expense-demo-c3")["display_tab_id"],
                         "trip-demo-a")

    # ------------------------------------------------------------- other routes
    def test_the_upload_and_the_selected_trip_xlsx_still_work(self):
        status, _ = self._api("/import")
        self.assertEqual(status, 200)
        page = self._page(1440)
        self._board(page, "?tab=trip-demo-a")
        page.click(".nav a[href='/import']")
        page.wait_for_load_state()
        self.assertIn("카드 가져오기", page.inner_text("body"))
        page.goto(f"http://127.0.0.1:{self.port}/board?tab=trip-demo-a")
        page.wait_for_load_state()
        page.click(".act a[href^='/export?tab=']")
        page.wait_for_load_state()
        self.assertIn("출력", page.inner_text("body"))
        status, body = self._api("/api/exports/xlsx", {
            "csrf": board_mod.CSRF_TOKEN,
            "tab_ids": ["trip-demo-a"],
            "client_request_id": "design-xlsx",
        }, method="POST")
        self.assertEqual(status, 200)
        self.assertIn(b"job_id", body)
        self.assertIn(b'"status": "ready"', body)

    def _poll_progress(self, batch_id, tries=100):
        import json
        import time

        progress = {}
        for _ in range(tries):
            status, body = self._api(f"/api/imports/{batch_id}")
            progress = json.loads(body.decode("utf-8"))
            if progress.get("status") not in ("reconciling", "parsing", "processing"):
                return progress
            time.sleep(0.05)
        return progress

    def test_a_card_upload_through_the_product_endpoint_reaches_the_board(self):
        # this one needs the reconciliation worker, so it gets its own server
        self.thread.join(timeout=1)
        self.server.shutdown()
        self.server.server_close()
        self.server = board_mod.serve(port=0, with_worker=True)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        csv_body = (
            "occurred_on,merchant,amount_krw,currency,card_last4,approval_no\r\n"
            "2026-04-12,예시 카페,9000,KRW,1234,APPROVAL-DESIGN\r\n"
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/imports", data=csv_body,
            headers={"X-CSRF-Token": board_mod.CSRF_TOKEN,
                     "X-Filename": "design.csv",
                     "Content-Type": "text/csv"},
            method="POST")
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            accepted = response.read()
        import json

        self.assertIn(b"batch_id", accepted)
        progress = self._poll_progress(json.loads(accepted.decode("utf-8"))["batch_id"])
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["result"]["new_events"], 1)
        stored = [r for r in self.store.list_tab_rows(None)
                  if "예시 카페" in (r.get("source_merchant") or "")]
        self.assertTrue(stored, "the uploaded row is not in the store")
        row = stored[0]
        page = self._page(1440)
        self._board(page, f"?tab={row['display_tab_id'] or 'unclassified'}")
        body = page.inner_text(".tw") + page.inner_text(".lst")
        self.assertIn("예시 카페", body)
        # and it is reachable for editing from the new board
        self.assertEqual(
            page.locator(f"tr[data-id='{row['row_id']}']").count(), 1)

    def test_the_form_policy_is_shared_with_the_save_endpoint(self):
        for kind, source in (("expense", "카드"), ("expense", "현금"),
                             ("income", "은행"), ("income", "직접 입력")):
            allowed, fixed = board_mod.editable_fields(kind, source, False)
            self.assertIn("display_tab_id", allowed)
            self.assertNotIn("source_event_id", allowed)
            self.assertIn("source_event_id", fixed)
        allowed, fixed = board_mod.editable_fields("income", "직접 입력", True)
        self.assertEqual(
            set(allowed),
            {"customer_id", "customer_name", "nickname", "display_tab_id", "income_kind"})
        self.assertEqual(fixed, ())
        page = self._page(1440)
        self._open_panel(page, "expense-demo-c1")
        names = page.eval_on_selector_all(
            "#panel [name]", "els=>els.map(e=>e.getAttribute('name'))")
        allowed, fixed = board_mod.editable_fields("expense", "카드", False)
        for name in names:
            if name in ("csrf", "expected_revision", "client_request_id",
                        "change_mode", "return_to"):
                continue
            self.assertIn(name, allowed, name)
            self.assertNotIn(name, fixed, name)


def test_trip_rail_badges_show_dates_never_income_in_initial_render_and_live_fragment(tmp_path):
    """항목 7 회귀: 여행 badge는 날짜이며 초기 렌더·live nav 모두 수입 금액을 표시하지 않는다."""
    store = LedgerStore(tmp_path / 'badges.sqlite')
    previous = board_mod._STORE
    board_mod.bind_store(store)
    try:
        for markup in (ledger_design._nav_region_inner('', '', '', ''),
                       ledger_design.nav_part('', '', '', '')):
            assert '미배정 지출' not in markup
            assert '04.08~04.14' in markup
            assert '수입' not in markup
            assert '수입 0원' not in markup
    finally:
        board_mod.bind_store(previous)
        store.close()


if __name__ == "__main__":
    unittest.main()
