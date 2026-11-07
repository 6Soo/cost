"""390px 모바일 재설계 검증. 합성 데이터와 실제 HTTP만 사용한다."""
import os
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request
from pathlib import Path

from webapp import ledger_board as board_mod
from webapp import ledger_design
from webapp.ledger_store import LedgerStore


def overflow(page):
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")


class LedgerRedesignMobileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev_db = os.environ.get("WEBLEDGER_DB")
        os.environ["WEBLEDGER_DB"] = str(Path(self.tmp) / "mobile.sqlite")
        self._prev_export = os.environ.get("WEBLEDGER_EXPORT_DIR")
        os.environ["WEBLEDGER_EXPORT_DIR"] = str(Path(self.tmp) / "exports")
        self.store = LedgerStore(Path(os.environ["WEBLEDGER_DB"]))
        board_mod.bind_store(self.store)
        self.server = board_mod.serve(port=0, with_worker=False)
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

    def _page(self, width=390, height=844):
        from playwright.sync_api import sync_playwright
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        context = self._browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        page.on("dialog", lambda d: d.accept() if d.type == "beforeunload" else None)
        return page

    def _board(self, page, query=""):
        page.goto(f"http://127.0.0.1:{self.port}/board{query}")
        page.wait_for_load_state()

    def test_work_menu_and_trip_selection_at_mobile_and_desktop(self):
        with mock.patch.object(board_mod, '_receipts_owner_request', return_value=True), mock.patch.dict(os.environ, {
            'WEBLEDGER_CARD_FLOW': '1',
            'WEBLEDGER_RECEIPTS_STORE': str(Path(self.tmp) / 'receipts.json'),
            'WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT': '',
            'WEBLEDGER_GOOGLE_LEDGER_ROWS': '',
        }):
            for width in (375, 390, 1440):
                with self.subTest(width=width):
                    page = self._page(width)
                    self._board(page, '?tab=trip-demo-a')
                    self.assertEqual(overflow(page), 0)
                    self.assertIn('수입 장부가 연결되지 않았습니다', page.locator('#google-trip-income').inner_text())
                    # 접힌 여행 메뉴가 작업 영역의 너비를 차지하지 않는다.
                    if width < 760:
                        self.assertGreaterEqual(page.locator('#main').bounding_box()['width'], width - 1)
                        self.assertLessEqual(page.locator('#nav').bounding_box()['x'] +
                                             page.locator('#nav').bounding_box()['width'], 0)
                        page.click('#btn-menu')
                    page.locator('#nav a[href*="tab=trip-demo-b"]').first.click()
                    page.wait_for_url('**/board?**tab=trip-demo-b**')
                    # 지금 할 업무 메뉴는 홈 본문에만 한 번 있다.
                    page.goto(f'http://127.0.0.1:{self.port}/')
                    self.assertEqual(page.locator('#work-menu').count(), 1)
                    self.assertIn('카드 내역', page.locator('#work-menu').inner_text())
                    self.assertIn('OTA 내역', page.locator('#work-menu').inner_text())
                    self.assertEqual(page.locator('#work-menu a[href="/cards/all"]').count(), 1)
                    page.locator('#work-menu a[href="/receipts"]').click()
                    page.wait_for_url('**/receipts')
                    self.assertTrue(page.locator('#img-file').is_visible())
                    page.close()

    def test_work_menu_hides_owner_actions_for_viewer(self):
        with mock.patch.object(board_mod, 'current_role', return_value='viewer'):
            self.assertEqual(ledger_design.work_menu_html(), '')

    def test_income_note_distinguishes_empty_ledger_from_google_and_filters(self):
        empty = ledger_design._summary_html([], [])
        self.assertIn('수입 0건 · 지출 0건', empty)
        # 수입 행이 필터로 숨겨져도 미기록이라고 안내하지 않는다.
        for html in (ledger_design.page('trip-demo-a', kind='ex'),
                     ledger_design.summary_part('trip-demo-a', kind='ex')):
            self.assertNotIn('수입이 아직 기록되지', html)
            self.assertIn('수입', html)

    def test_mobile_list_shows_two_line_summary_without_origin_details(self):
        html = ledger_design._mobile_html(
            board_mod._income_rows(), board_mod._expense_rows(),
            selected="", unclassified=False)
        self.assertIn("data-id='expense-demo-c1'", html)
        # 날짜·거래처·용도·분류·금액이 두 줄 요약으로 보인다
        self.assertIn("2026-04-09", html)
        self.assertIn("예시 숙소", html)
        self.assertIn("숙박비", html)
        self.assertIn("100,000원", html)
        # 원본은 상세패널에서 보므로 목록에 details를 두지 않는다
        self.assertNotIn("<details", html)
        self.assertNotIn("m-src", html)
        # raw id·원본위치·후보키는 목록에 직접 노출하지 않는다
        self.assertNotIn("SRC-C1", html)
        self.assertNotIn("expense-demo-c1", html.replace("data-id='expense-demo-c1'", ""))
        self.assertNotIn("후보", html)
        # 여행 배정 폼 계약 유지 (모바일 id는 desktop과 중복되지 않는다)
        move_html = ledger_design._mobile_html(
            [], board_mod._unclassified_rows(),
            selected="", unclassified=True)
        self.assertIn("form method='post' action='/api/rows/", move_html)
        self.assertIn("data-js-move", move_html)
        self.assertIn("name='display_tab_id'", move_html)
        self.assertIn("name='expected_revision'", move_html)
        self.assertIn("id='mobile-move-", move_html)
        self.assertIn("for='mobile-move-", move_html)

    def test_search_filter_select_save_trip_assign_at_390(self):
        page = self._page()
        self._board(page, "?tab=trip-demo-a")
        self.assertEqual(overflow(page), 0)
        # The trip body has no search menu; legacy filter links still render.
        self.assertEqual(page.locator('#q-form, #q, #kind, #q-go').count(), 0)
        self._board(page, "?tab=trip-demo-a&q=예시 숙소")
        page.wait_for_load_state()
        self.assertIn("tab=trip-demo-a", page.url)
        self.assertGreaterEqual(page.locator(".lst .li").count(), 1)
        self.assertEqual(overflow(page), 0)
        # 선택·수정·저장
        page.goto(f"http://127.0.0.1:{self.port}/board?tab=trip-demo-a")
        page.wait_for_load_state()
        page.click(".lst .li[data-id='expense-demo-c1']")
        page.wait_for_selector("#panel")
        before = self.store.get_row("expense-demo-c1")["revision"]
        page.locator("#panel .p-extra > summary").click()
        page.fill("#f-description", "모바일 재설계 저장")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "document.querySelector('.f-msg')&&document.querySelector('.f-msg')"
            ".textContent.indexOf('저장했습니다')>=0")
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"], before + 1)
        box = page.eval_on_selector(
            "#panel button[type='submit']",
            "e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom};}")
        self.assertLessEqual(box["bottom"], page.evaluate("window.innerHeight"))
        # 터치 44px
        for selector in (".lst .li",):
            box = page.eval_on_selector(
                selector, "e=>e.getBoundingClientRect().height")
            self.assertGreaterEqual(box, 40, selector)
        # 여행 배정
        page.goto(f"http://127.0.0.1:{self.port}/board?tab=unclassified")
        page.wait_for_load_state()
        self.assertEqual(overflow(page), 0)
        page.select_option(".lst form[data-js-move] select[name='display_tab_id']",
                           "trip-demo-a")
        page.click(".lst form[data-js-move] button[type='submit']")
        page.wait_for_url(lambda url: "tab=unclassified" in url and "msg=" in url,
                          wait_until="load")
        self.assertEqual(self.store.get_row("expense-demo-c3")["display_tab_id"],
                         "trip-demo-a")
        # 여행 drawer 유지
        page.goto(f"http://127.0.0.1:{self.port}/board?tab=trip-demo-a")
        page.wait_for_load_state()
        page.click("#btn-menu")
        self.assertTrue(page.is_visible(".nav.open"))
        page.click("#nav-mask")

    def test_mobile_expense_new_link_visible_and_clickable(self):
        # 4폭 + 경계 759: .tw 숨김/.lst 표시에서 지출 헤더 링크를 실제 클릭한다.
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        try:
            for width, height in [(375, 844), (390, 844), (391, 844),
                                  (430, 900), (759, 844)]:
                with self.subTest(width=width, height=height):
                    ctx = browser.new_context(
                        viewport={"width": width, "height": height})
                    page = ctx.new_page()
                    page.on("dialog", lambda d: d.accept()
                            if d.type == "beforeunload" else None)
                    page.goto(f"http://127.0.0.1:{self.port}"
                              "/board?tab=trip-demo-a")
                    page.wait_for_load_state()
                    page.evaluate("document.fonts.ready.then(()=>0)")
                    self.assertFalse(page.is_visible(".tw"),
                                     f"{width}px에서 .tw는 숨김")
                    self.assertTrue(page.is_visible(".lst"),
                                    f"{width}px에서 .lst는 표시")
                    link = page.locator(
                        ".trip-actions a[href^='/expense/new?']")
                    self.assertEqual(link.count(), 1, f"{width}px 링크 1개")
                    self.assertTrue(link.is_visible(), f"{width}px 링크 visible")
                    self.assertIn("수기 지출 추가", link.inner_text())
                    self.assertIn("btn", link.get_attribute("class"))
                    link.click()
                    page.wait_for_load_state()
                    self.assertIn("/expense/new", page.url, f"{width}px 진입")
                    self.assertIn("수기 지출 추가", page.content())
                    ctx.close()
        finally:
            browser.close()
            pw.stop()

    def test_mobile_expense_new_link_with_empty_expenses(self):
        # 빈 지출 목록(kind=in)에서도 같은 링크로 /expense/new 진입한다.
        html = ledger_design._mobile_html(
            board_mod._income_rows(), [],
            selected="", unclassified=False)
        self.assertNotIn("id='add-manual-expense-mobile'", html)
        self.assertIn("href='/expense/new?", ledger_design._trip_actions("trip-demo-a", "/board?tab=trip-demo-a"))
        self.assertIn("지출 내역이 없어요", html)
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        try:
            for query in ["?tab=trip-demo-a&kind=in",
                          "?tab=trip-demo-a&q=없는검색어000"]:
                with self.subTest(query=query):
                    ctx = browser.new_context(
                        viewport={"width": 390, "height": 844})
                    page = ctx.new_page()
                    page.on("dialog", lambda d: d.accept()
                            if d.type == "beforeunload" else None)
                    page.goto(f"http://127.0.0.1:{self.port}/board{query}")
                    page.wait_for_load_state()
                    page.evaluate("document.fonts.ready.then(()=>0)")
                    self.assertTrue(page.is_visible(".lst"))
                    link = page.locator(
                        ".trip-actions a[href^='/expense/new?']")
                    self.assertEqual(link.count(), 1)
                    self.assertTrue(link.is_visible())
                    link.click()
                    page.wait_for_load_state()
                    self.assertIn("/expense/new", page.url)
                    self.assertIn("수기 지출 추가", page.content())
                    ctx.close()
        finally:
            browser.close()
            pw.stop()



if __name__ == "__main__":
    unittest.main()
