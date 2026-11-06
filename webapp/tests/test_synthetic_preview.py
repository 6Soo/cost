import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from tools.run_synthetic_preview import preview_server
from webapp import google_ledger_page, ledger_board
from webapp.tests.test_receipt_review import PNG


def test_saved_receipt_filename_reflows_after_upload_and_reload():
    """A saved filename remains readable at mobile width and enlarged text."""
    name = 'synthetic_trip_20270803_receipt_' + '1234567890' * 13 + '.png'
    with preview_server() as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as api:
                browser = api.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 320, 'height': 900})
                    base = f'http://127.0.0.1:{server.server_address[1]}'
                    page.goto(base + '/preview')
                    page.goto(base + '/receipts')
                    page.locator('#selected-trip').select_option(index=1)
                    page.locator('#img-file').set_input_files(
                        dict(name=name, mimeType='image/png', buffer=PNG))
                    page.locator('#img-go').click()
                    page.locator('#upload-results').get_by_text(name + ' · 원본 저장됨', exact=False).wait_for()
                    page.reload()
                    stored = page.locator('section[aria-label="저장된 파일"] > ul > li').first
                    assert name in stored.inner_text()
                    for theme in ('light', 'dark'):
                        if page.locator('html').get_attribute('data-theme') != theme:
                            page.locator('#site-theme-toggle').click()
                        for width, zoom in ((320, '100%'), (640, '200%')):
                            page.set_viewport_size({'width': width, 'height': 900})
                            page.evaluate('(zoom)=>document.documentElement.style.zoom=zoom', zoom)
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                            assert stored.evaluate('(el)=>el.scrollWidth <= el.clientWidth + 1')
                    assert page.request.get(base + '/api/receipts').json()['uploads'][0]['name'] == name
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_preview_completes_card_and_manual_receipt_without_operational_files():
    with tempfile.TemporaryDirectory() as directory:
        original_db = Path(directory) / 'do-not-open.sqlite'
        original_db.write_bytes(b'USER FILE - NOT A DATABASE')
        with patch.dict(os.environ, {'WEBLEDGER_DB': str(original_db),
                                     'WEBLEDGER_GOOGLE_CLIENT_SECRET': 'do-not-use',
                                     'WEBLEDGER_CARD_SCHEMA_POLICY': 'require'}):
            with preview_server() as server:
                root = Path(os.environ['WEBLEDGER_RECEIPTS_STORE']).parent
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    assert server.server_address[0] == '127.0.0.1'
                    assert os.environ.get('WEBLEDGER_GOOGLE_CLIENT_SECRET') is None
                    with sync_playwright() as api:
                        browser = api.chromium.launch()
                        context = browser.new_context(viewport={'width': 375, 'height': 812},
                            permissions=['clipboard-read', 'clipboard-write'])
                        pg = context.new_page()
                        copy_warnings = []
                        pg.on('dialog', lambda dialog: (copy_warnings.append(dialog.message), dialog.accept()))
                        base = f'http://127.0.0.1:{server.server_address[1]}'
                        assert pg.request.get(base + '/api/receipts').status in (401, 403)
                        pg.goto(base + '/preview')
                        assert '로컬 합성 미리보기' in pg.inner_text('body')
                        pg.locator('.home-trip').filter(has_text='0803_합성여행').click()
                        pg.wait_for_url('**/board?**tab=**')
                        pg.get_by_role('button', name='전체 메뉴 열기').click()
                        pg.locator('#nav a[href="/import"]').click()
                        pg.locator('.expense-tools > summary').click()
                        pg.get_by_role('tab', name='저장된 자료', exact=True).click()
                        form = pg.locator('form[data-index]').first
                        form.locator('input[name=item]').fill('소모품비')
                        trip = server.card_store.list_trips()[0]['tab_id']
                        form.locator('select[name=display_tab_id]').select_option(trip)
                        form.locator('input[name=description]').fill('합성 여행 준비')
                        form.locator('button').click()
                        pg.locator('#status').get_by_text('저장했습니다.', exact=True).wait_for()
                        # Select the disposable workbook before the real duplicate-check/copy boundary.
                        google_ledger_page.record_choice(
                            Path(os.environ['WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT']),
                            key='0803_합성여행', source='main', at='2026-10-26T00:00:00+09:00')
                        pg.goto(base + '/board?tab=' + trip)
                        pg.locator('#copy-trip-expenses').click()
                        pg.locator('#copy-status.success').wait_for()
                        copied = pg.evaluate('navigator.clipboard.readText()')
                        assert '37000' in copied
                        assert len(copied.strip().split('\t')) == 7
                        pg.wait_for_function('(trip)=>Boolean(localStorage.getItem("gcopy-trip:"+trip))', arg=trip)
                        # 실제 여행 일정 원본을 검사하며 trip_valid를 대체하지 않는다.
                        row = server.card_store.conn.execute(
                            'SELECT amount_krw,decided_at IS NOT NULL,display_tab_id FROM transactions').fetchone()
                        assert row == (37000, 1, trip)
                        pg.goto(base + '/')
                        pg.get_by_role('button', name='전체 메뉴 열기').click()
                        pg.locator('#nav').get_by_role('link', name='영수증 처리', exact=True).click()
                        pg.locator('#selected-trip').select_option(trip)
                        pg.locator('#img-file').set_input_files(dict(name='synthetic.png', mimeType='image/png', buffer=PNG))
                        with pg.expect_response('**/api/receipts/image') as uploaded:
                            pg.locator('#img-go').click()
                        assert uploaded.value.status == 200
                        pg.locator("img[src*='/api/receipts/image/']").first.wait_for()
                        pg.wait_for_load_state()
                        pg.locator('#other-methods > summary').click()
                        pg.locator('#r-merchant').fill('합성 현금 상점')
                        pg.locator('#r-date').fill('2027-08-03')
                        pg.locator('#r-total').fill('1200')
                        pg.locator('#region-go').click()
                        candidate = pg.locator('tr[data-version]').first
                        candidate.locator('[data-trip]').select_option(trip)
                        candidate.locator('[data-edit]').click()
                        pg.get_by_text('영수증 변경을 저장했습니다.', exact=False).wait_for()
                        candidate.locator('[data-payee]').fill('합성 지급처')
                        candidate.locator('[data-category]').fill('식비')
                        candidate.locator('[data-edit]').click()
                        pg.get_by_text('영수증 변경을 저장했습니다.', exact=False).wait_for()
                        pg.locator('#copy-trip').select_option(trip)
                        pg.locator('#copy-tsv').click()
                        pg.get_by_text('영수증 1행을 클립보드에 복사했습니다.', exact=False).wait_for()
                        receipt_copy = pg.evaluate('navigator.clipboard.readText()')
                        assert '12000' in receipt_copy
                        assert len(receipt_copy.strip().split('\t')) == 7
                        assert any('중복' in warning for warning in copy_warnings)
                        pg.goto(base + '/board?tab=' + trip)
                        income_amount = pg.locator('#google-trip-income td.income-total').first
                        income_amount.wait_for()
                        assert income_amount.inner_text() == '900,000원'
                        assert pg.locator('#live-sum #sum > div > b').all_inner_texts() == [
                            '900,000원', '37,000원', '863,000원']
                        assert pg.evaluate('document.documentElement.scrollWidth-innerWidth') == 0
                        browser.close()
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
            assert not root.exists()
            assert os.environ['WEBLEDGER_DB'] == str(original_db)
            assert os.environ['WEBLEDGER_GOOGLE_CLIENT_SECRET'] == 'do-not-use'
            assert os.environ['WEBLEDGER_CARD_SCHEMA_POLICY'] == 'require'
            assert original_db.read_bytes() == b'USER FILE - NOT A DATABASE'
