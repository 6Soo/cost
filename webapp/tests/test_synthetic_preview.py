import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from tools.run_synthetic_preview import preview_server
from webapp import ledger_board
from webapp.tests.test_receipt_review import PNG


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
                        form = pg.locator('form[data-index]').first
                        form.locator('input[name=item]').fill('소모품비')
                        trip = server.card_store.list_trips()[0]['tab_id']
                        form.locator('select[name=display_tab_id]').select_option(trip)
                        form.locator('input[name=description]').fill('합성 여행 준비')
                        form.locator('button').click()
                        pg.get_by_text('답변을 적용했습니다.', exact=False).wait_for()
                        pg.locator(f'[data-google-copy="{trip}"]').click()
                        pg.wait_for_function('navigator.clipboard.readText().then(s=>s.includes("37000"))')
                        assert len(pg.evaluate('navigator.clipboard.readText()').strip().split('\t')) == 7
                        pg.wait_for_function('(trip)=>Boolean(localStorage.getItem("gcopy-trip:"+trip))', arg=trip)
                        # 실제 여행 일정 원본을 검사하며 trip_valid를 대체하지 않는다.
                        row = server.card_store.conn.execute(
                            'SELECT amount_krw,user_confirmed,display_tab_id FROM transactions').fetchone()
                        assert row == (37000, 1, trip)
                        pg.goto(base + '/')
                        pg.locator('#work-menu a[href="/receipts"]').click()
                        pg.locator('#img-file').set_input_files(dict(name='synthetic.png', mimeType='image/png', buffer=PNG))
                        with pg.expect_response('**/api/receipts/image') as uploaded:
                            pg.locator('#img-go').click()
                        assert uploaded.value.status == 200
                        pg.locator("img[src*='/api/receipts/image/']").first.wait_for()
                        pg.wait_for_load_state()
                        for index, value in enumerate((0, 0, 100, 100), 1):
                            pg.locator(f'#box{index}').fill(str(value))
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
                        candidate.locator('[data-confirm]').click()
                        pg.get_by_text('영수증 변경을 저장했습니다.', exact=False).wait_for()
                        pg.locator('#copy-trip').select_option(trip)
                        pg.locator('#copy-tsv').click()
                        pg.wait_for_function('navigator.clipboard.readText().then(s=>s.includes("12000"))')
                        assert any('중복' in warning for warning in copy_warnings)
                        pg.goto(base + '/')
                        pg.locator('#work-menu a[href="/google-ledger"]').click()
                        assert pg.locator('td[data-label="수입"]').count() == 1
                        pg.get_by_role('button', name='main 최종 장부로 선택').click()
                        pg.wait_for_function('document.querySelector("td[data-label=수입]").textContent.includes("900,000")')
                        assert '780,000' in pg.locator('td[data-label="순수익"]').inner_text()
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
