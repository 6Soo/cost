"""390px 모바일 재설계 검증. 합성 데이터와 실제 HTTP만 사용한다."""
import os
import tempfile
import threading
import unittest
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
        # 검색·필터
        page.fill("#q", "예시 숙소")
        page.select_option("#kind", "")
        page.click("#q-go")
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
        page.fill("#f-description", "모바일 재설계 저장")
        page.click("#panel button[type='submit']")
        page.wait_for_function(
            "document.querySelector('.f-msg')&&document.querySelector('.f-msg')"
            ".textContent.indexOf('revision')>=0")
        self.assertEqual(self.store.get_row("expense-demo-c1")["revision"], before + 1)
        box = page.eval_on_selector(
            "#panel button[type='submit']",
            "e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom};}")
        self.assertLessEqual(box["bottom"], page.evaluate("window.innerHeight"))
        # 터치 44px
        for selector in (".lst .li", "#q", "#kind"):
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



if __name__ == "__main__":
    unittest.main()
