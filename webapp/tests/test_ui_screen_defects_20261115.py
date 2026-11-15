"""Screen-level UI defects from the M4 review (items 4, 5, 8, 10, 11, 12, 13) rendered by the synthetic preview."""
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import run_synthetic_preview as preview  # noqa: E402


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ScreenDefectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = preview.preview_server(0)
        cls.server = cls.manager.__enter__()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            opener.open(cls.base + '/preview')
        except urllib.error.HTTPError as error:
            cls.cookie = error.headers['Set-Cookie'].split(';')[0]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(5)
        cls.manager.__exit__(None, None, None)

    def get(self, path):
        request = urllib.request.Request(self.base + path, headers={'Cookie': self.cookie, 'Accept': 'text/html'})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode('utf-8')

    def trip_tab(self):
        status, text = self.get('/trips')
        self.assertEqual(status, 200)
        match = re.search(r"/board\?tab=([^'\"&]+)", text)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_10_unknown_trip_is_404_with_trip_list_link(self):
        status, text = self.get('/board?tab=no-such-trip-20261115')
        self.assertEqual(status, 404)
        self.assertIn('찾을 수 없', text)
        self.assertIn("href='/trips'", text)
        self.assertEqual(self.get('/board?tab=' + self.trip_tab())[0], 200)
        self.assertEqual(self.get('/board?tab=unclassified')[0], 200)

    def test_11_trip_menu_is_a_plain_disclosure_closed_by_escape(self):
        status, text = self.get('/board?tab=' + self.trip_tab())
        self.assertEqual(status, 200)
        self.assertIn("id='trip-settings'", text)
        for token in ("role='menu'", "role='menuitem'", "aria-haspopup='menu'"):
            self.assertNotIn(token, text)
        script = (ROOT / 'webapp/static/js/ledger_design.js').read_text(encoding='utf-8')
        self.assertRegex(script, r"tripMore\.addEventListener\('keydown'.*Escape.*tripMore\.open=false")

    def test_8_inputs_use_control_border_44px_and_shared_close_buttons(self):
        status, text = self.get('/board?tab=' + self.trip_tab())
        self.assertIn("id='drawer-close'", text)
        self.assertRegex(text, r"<button class='btn ghost' type='button' id='drawer-close'[^>]*>닫기</button>")
        self.assertEqual(text.count('id=\'drawer-close\''), 1)
        self.assertIn('.mx-card .mx-field select{height:44px', text)
        self.assertIn('border:1px solid var(--c-border-control)', text)
        self.assertRegex(text, r"<button type='button' class='btn ghost' data-manual-close>닫기</button>")
        status, cards = self.get('/cards/all')
        self.assertEqual(status, 200)
        self.assertNotIn('min-height:42px', cards)
        self.assertNotIn('border:1px solid var(--ca-border);border-radius:var(--r-md);background:var(--ca-paper);color:var(--ca-ink);font:inherit}', cards)
        self.assertNotIn("class='card-workspace-secondary' data-card-panel-close", cards)
        self.assertIn('.card-all-ledger-link{display:inline-block;margin-top', cards)

    def test_8_amount_inputs_allow_a_minus_sign(self):
        status, text = self.get('/expense/new')
        self.assertEqual(status, 200)
        self.assertRegex(text, r"id='mx-amount'[^>]*inputmode='text'")

    def test_4_light_and_dark_text_uses_accent_text_token(self):
        for name in ('collection_status.py', 'receipt_review.py'):
            source = (ROOT / 'webapp' / name).read_text(encoding='utf-8')
            self.assertNotIn('.home-collection .ok{color:var(--grn)}', source)
            self.assertNotIn('.work-back{color:var(--grn-dk)', source)
        self.assertIn('.home-collection .ok{color:var(--c-accent-text)}',
                      (ROOT / 'webapp/collection_status.py').read_text(encoding='utf-8'))
        self.assertIn('.work-back{color:var(--c-accent-text)',
                      (ROOT / 'webapp/receipt_review.py').read_text(encoding='utf-8'))

    def test_5_and_13_ota_disclosure_cue_and_single_empty_sentence(self):
        status, text = self.get('/ota')
        self.assertEqual(status, 200)
        self.assertIn('summary::after{content:""', text)
        self.assertNotIn("content:;", text)
        self.assertIn('<summary>추가 조회</summary>', text)
        source = (ROOT / 'webapp/ota_catalog.py').read_text(encoding='utf-8')
        self.assertNotIn('수집 자료 연결 상태', source)
        self.assertNotIn('empty_state(', source)
        self.assertEqual(source.count('조회된 OTA 예약이 없습니다.'), 2)
        css = (ROOT / 'webapp/static/css/card_catalog.css').read_text(encoding='utf-8')
        self.assertRegex(css, r"\.header-button\{[^}]*font-size:var\(--t-body-sm\)")

    def test_13_form_page_has_no_unrelated_header_buttons_and_no_empty_tab_link(self):
        status, text = self.get('/expense/new')
        self.assertEqual(status, 200)
        header = text.split("<div class='act'>", 1)[1].split("</div></div>", 1)[0]
        self.assertNotIn('XLSX', header)
        self.assertNotRegex(text, r"href='/board\?tab='")
        status, export = self.get('/export')
        self.assertEqual(status, 200)
        self.assertNotRegex(export, r"href='/board\?tab=(?:&[^']*)?'")

    def test_12_terms_and_retired_links(self):
        status, text = self.get('/board?tab=' + self.trip_tab())
        self.assertNotIn('실제 자료 검토', text)
        self.assertIn("<label for='kind'>구분</label>", text)
        self.assertNotIn('XLSX 출력', text)
        reserve = (ROOT / 'webapp/reserve_link_ui.py').read_text(encoding='utf-8')
        self.assertNotIn('관리자가 설정', reserve)
        self.assertNotIn('back-review', reserve)
        status, form = self.get('/expense/new')
        self.assertIn("<label for='mx-item'>분류</label>", form)

    def test_error_page_title_uses_the_heading_token(self):
        from webapp import error_page
        document = error_page.render(404, '없음', '메시지', [('홈', '/')])
        self.assertIn('.error-page h1{margin:0 0 12px;font-size:var(--t-h1,1.5rem)', document)

    def test_receipt_manual_entry_heading_is_distinct_from_the_summary(self):
        source = (ROOT / 'webapp/receipt_review.py').read_text(encoding='utf-8')
        self.assertIn('<h3>영수증 내용 직접 입력</h3>', source)


if __name__ == '__main__':
    unittest.main()
