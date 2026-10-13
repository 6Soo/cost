import pytest
import json
from playwright.sync_api import sync_playwright

from app.receipt_candidates import Region, build_candidates
from webapp.tests import test_receipt_review as receipt_tests


@pytest.fixture
def app():
    case = receipt_tests.ReceiptReviewTests()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


def test_krw_is_not_converted_and_corporate_receipts_are_only_evidence():
    region = Region('synthetic', (0, 0, 100, 100), '합성 상점', '2026-10-12', 'KRW', 12500, 'cash', 1)
    result = build_candidates([region], [])
    candidate = result['candidates'][0]
    assert candidate.amount_krw == 12500
    assert candidate.total_original == 12500 and candidate.total_jpy is None
    region.payment = 'corporate_card'
    card = {'transaction_id': 'domestic-one', 'date': region.date, 'merchant': region.merchant, 'original_krw': 12500}
    candidate = build_candidates([region], [card])['candidates'][0]
    assert candidate.card_transaction_id == 'domestic-one' and candidate.amount_krw is None


def test_krw_manual_review_edit_reload_and_copy_preserves_original_amount(app):
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            context = browser.new_context(viewport={'width': 390, 'height': 844}, permissions=['clipboard-read', 'clipboard-write'])
            page = context.new_page()
            page.goto(app.base + '/receipts')
            page.evaluate("document.getElementById('other-methods') && (document.getElementById('other-methods').open=true)")
            page.locator('#r-currency').select_option('KRW')
            for field, value in (('r-merchant', '원화 합성 매장'), ('r-date', '2026-10-12'), ('r-total', '12500')):
                page.locator('#' + field).fill(value)
            page.locator('#region-go').click()
            page.locator('[data-total]').wait_for()
            assert page.locator('[data-total]').get_attribute('aria-label') == '금액(KRW)'
            page.locator('[data-total]').fill('13000')
            page.locator('[data-trip]').select_option(app.trip)
            page.locator('[data-edit]').click()
            page.get_by_role('status').filter(has_text='변경을 저장했습니다').wait_for()
            page.locator('[data-payee]').fill('원화 합성 매장')
            page.locator('[data-category]').fill('식비')
            page.locator('[data-confirm]').click()
            page.get_by_role('status').filter(has_text='변경을 저장했습니다').wait_for()
            page.reload()
            page.locator('#copy-trip').select_option(app.trip)
            page.locator('#copy-tsv').click()
            page.get_by_role('status').filter(has_text='1행을 클립보드에 복사했습니다').wait_for()
            text = page.evaluate('navigator.clipboard.readText()')
            assert len(text.strip().split('\t')) == 7 and text.strip().endswith('13000')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            _, saved = app.request('/api/receipts')
            candidate = saved['candidates'][0]
            assert candidate['currency'] == 'KRW' and candidate['total_original'] == 13000
            assert candidate['total_jpy'] is None and candidate['amount_krw'] == 13000
        finally:
            browser.close()


def test_late_domestic_card_blocks_cash_copy_and_preserves_card_when_linked(app):
    from webapp.card_flow import CardFlow
    region = dict(receipt_tests.REGIONS['regions'][0], currency='KRW', total=12500,
                  merchant='합성 원화 카드', date='2026-10-12', box=[0, 0, 100, 100])
    status, result = app.request('/api/receipts/scan', {'regions': [region]}, token=app.csrf())
    assert status == 200 and result['added'] == 1
    assert app.request('/api/receipts/scan', {'regions': [region]}, token=app.csrf())[1]['added'] == 0
    candidate = app.request('/api/receipts')[1]['candidates'][0]
    identity = candidate['identity']
    app.request('/api/receipts/edit', {'identity': identity, 'trip_id': app.trip}, token=app.csrf())
    app.request('/api/receipts/edit', {'identity': identity, 'payee': region['merchant'], 'category': '식비'}, token=app.csrf())
    assert app.request('/api/receipts/tsv?trip=' + app.trip)[1]['row_count'] == 1
    board = app.server.card_store
    batch = CardFlow(board).pipeline.receive(receipt_tests.CARD, 'synthetic-krw.csv')['batch_id']
    receipt_tests._card_purchase(board, batch, 'domestic-late', region['merchant'], 1250, region['date'])
    board.conn.execute("UPDATE transactions SET foreign_currency='', foreign_amount='' WHERE transaction_id='domestic-late'")
    board.conn.commit()
    before = board.conn.execute("SELECT * FROM transactions WHERE transaction_id='domestic-late'").fetchone()
    result = app.request('/api/receipts/tsv?trip=' + app.trip)[1]
    assert result['row_count'] == 0
    assert any(h['reason'] == 'CARD_PAYMENT_CONFLICT' for h in result['held'])
    status, linked = app.request('/api/receipts/edit', {'identity': identity, 'payment': 'corporate_card'}, token=app.csrf())
    assert status == 200 and linked['card_transaction_id'] == 'domestic-late'
    assert linked['total_original'] == 12500 and linked['amount_krw'] is None
    status, denied = app.request('/api/receipts/edit', {'identity': identity, 'payment': 'cash'}, token=app.csrf())
    assert status == 400 and denied['code'] == 'CARD_LINKED_NOT_EDITABLE'
    assert app.request('/api/receipts/tsv?trip=' + app.trip)[1]['row_count'] == 0
    assert board.conn.execute("SELECT * FROM transactions WHERE transaction_id='domestic-late'").fetchone() == before


def test_existing_jpy_store_without_currency_fields_is_not_rewritten_on_read(app):
    identity = app._confirmed_cash_receipt()
    data = json.loads(app.store.read_text(encoding='utf-8'))
    for candidate in data['candidates']:
        candidate.pop('currency', None)
        candidate.pop('total_original', None)
    app.store.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    before = app.store.read_bytes()
    status, result = app.request('/api/receipts/tsv?trip=' + app.trip)
    assert status == 200 and result['row_count'] == 1 and result['tsv'].strip().endswith('12340')
    assert app.store.read_bytes() == before
    stored = app.request('/api/receipts')[1]['candidates'][0]
    assert stored['identity'] == identity and stored['total_jpy'] == 1234
