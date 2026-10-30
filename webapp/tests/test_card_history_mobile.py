"""Exercise visible card history layout, touch targets and destination links."""
import sqlite3
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright

from webapp import cards_all, ledger_board, ledger_design, site_shell
from webapp.tests.test_cards_all import card_db_path


def test_mobile_history_keeps_compact_table_and_contained_scrolling(card_db_path, monkeypatch):
    long_merchant = '합성 숙박 가맹점 ' * 12
    long_trip = '합성 여행 · 아주 긴 여행 이름과 일정 ' * 5
    with closing(sqlite3.connect(card_db_path)) as conn, conn:
        conn.execute("UPDATE transactions SET transaction_direction='purchase', approval_number='SYN100', "
                     "merchant=?, classification_state='preserved' WHERE transaction_id='TX-A-01'", (long_merchant,))
        conn.execute("UPDATE transactions SET transaction_direction='cancellation', original_approval_number='SYN100', "
                     "amount_krw=-150000, foreign_amount='', foreign_currency='KRW', "
                     "classification_state='preserved' WHERE transaction_id='TX-A-02'")
    monkeypatch.setattr(cards_all, '_trip_context', lambda: ({'T-C': long_trip}, {'T-C'}))
    monkeypatch.setattr(ledger_board, 'current_role', lambda: 'owner')
    monkeypatch.setattr(ledger_board, 'live_trips', lambda **kwargs: [{'tab_id': 'T-C', 'display_key': long_trip}])
    monkeypatch.setattr(ledger_design, 'nav_region', lambda *args: '')
    document = site_shell.wrap_document(cards_all.cards_all_page(
        {'year': ['2026'], 'month': ['3']}, db_path=card_db_path), '/cards/all')
    output = Path('.local-archive/card-inline-details-20261029')
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.route('http://cost.test/cards/all*', lambda route: route.fulfill(
                status=200, content_type='text/html; charset=utf-8', body=document))
            page.goto('http://cost.test/cards/all?year=2026&month=3')
            for theme in ('light', 'dark'):
                page.emulate_media(color_scheme=theme)
                for width in (320, 390, 600, 759, 760, 1280):
                    page.set_viewport_size({'width': width, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    rows = page.locator('tr[data-tx-id]')
                    assert rows.count() == 3
                    assert page.locator('thead th').count() == 4
                    assert page.locator('.detail-cell, .preserved').count() == 0
                    assert page.locator('.card-all-table-wrap').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
                    assert rows.first.locator('td').first.evaluate('(e)=>getComputedStyle(e).borderBottomWidth') == '1px'
                    if width <= 759:
                        assert rows.first.evaluate('(e)=>getComputedStyle(e).display') == 'table-row'
                        assert all(row.bounding_box()['height'] <= 80 for row in rows.all())
                        for row in rows.all():
                            button = row.locator('.card-all-row-toggle').bounding_box()
                            name = row.locator('.merchant-name').bounding_box()
                            identity = row.locator('.card-identity').bounding_box()
                            assert button['height'] >= 44
                            assert button['height'] >= name['height']
                            assert 0 <= identity['y'] - (name['y'] + name['height']) <= 28
                            tops = [cell.bounding_box()['y'] for cell in row.locator('td').all()]
                            assert max(tops) - min(tops) <= 1
                        for selector in ('.card-all-table-wrap', '.card-all-filters input[type=search]',
                                         '.card-all-filters select', '.card-all-filters button'):
                            for element in page.locator(selector).all():
                                box = element.bounding_box()
                                assert box and box['x'] >= 0 and box['x'] + box['width'] <= width + 1
                        for link in page.locator('td.trip>a').all():
                            assert link.bounding_box()['height'] >= 44
                        assert page.locator('.card-all-filters input[type=search]').evaluate(
                            '(e)=>parseFloat(getComputedStyle(e).fontSize)>=16')
                        merchant = page.locator("tr[data-tx-id='TX-A-01'] td.merchant")
                        assert merchant.get_attribute('title') == long_merchant.strip()
                        assert page.locator("tr[data-tx-id='TX-B-01'] td.trip").get_attribute('title').strip() == long_trip.strip()
                    else:
                        assert page.locator('.card-all-table').evaluate('(e)=>getComputedStyle(e).display') == 'table'
                    if width == 390:
                        page.screenshot(path=str(output / f'mobile-{theme}.png'), full_page=True)
                        page.locator("tr[data-tx-id='TX-A-02']").scroll_into_view_if_needed()
                        page.screenshot(path=str(output / f'mobile-transaction-{theme}.png'))
            assert page.locator("tr[data-tx-id='TX-A-01'] .merchant-name").inner_text() == long_merchant.strip()
            assert page.locator("tr[data-tx-id='TX-B-01'] .card-all-trip-name").inner_text() == long_trip.strip()
            assert page.locator("td.trip a[href='/board?tab=refunds']").count() == 2
            assert page.locator('.card-all-help').get_attribute('open') is None
            page.locator('.card-all-help summary').click()
            assert page.locator('.card-all-help p').is_visible()
            page.set_viewport_size({'width': 640, 'height': 844})
            page.evaluate('document.documentElement.style.zoom="200%"')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('.card-all-table').evaluate('(e)=>getComputedStyle(e).display') == 'table'
            link = page.locator('.card-all-row-toggle').first
            link.focus()
            assert link.evaluate('(e)=>e===document.activeElement')
            assert link.get_attribute('aria-expanded') == 'false'
            assert page.locator('.card-all-table-wrap').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            page.evaluate('document.documentElement.style.zoom="100%"')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.route('http://cost.test/board*', lambda route: route.fulfill(status=200, body='<p>synthetic detail</p>'))
            original = 'http://cost.test/cards/all?year=2026&month=3'
            pending = []
            page.route('http://cost.test/api/cards/transactions/detail*', lambda route: pending.append(route))
            # All ordinary cells expand in place, including source-only transactions.
            for cell in ('td.use-datetime', 'td.amount-cell', 'td.trip'):
                page.goto(original)
                page.locator("tr[data-tx-id='TX-B-01'] " + cell).click()
                detail = page.locator('#card-detail-TX-B-01')
                from playwright.sync_api import expect
                expect(detail.locator('[role=status]')).to_be_visible()
                assert detail.locator('.card-all-expanded-content').get_attribute('aria-busy') == 'true'
                if cell == 'td.use-datetime':
                    page.screenshot(path=str(output / 'detail-loading.png'), full_page=True)
                from webapp import card_transactions as ct
                pending.pop().fulfill(json={'html': cards_all.card_detail_html(ct.transaction_detail('TX-B-01', card_db_path))})
                expect(detail).to_contain_text('AGODA')
                expect(detail.locator('.card-all-spinner')).to_have_count(0)
                assert page.url == original
                for expanded_width in (320, 390, 600, 759, 760, 1280):
                    page.set_viewport_size({'width': expanded_width, 'height': 844})
                    assert page.locator('.card-all-table-wrap').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
                page.set_viewport_size({'width': 390, 'height': 844})
                if cell == 'td.use-datetime':
                    page.screenshot(path=str(output / 'detail-expanded.png'), full_page=True)
                page.locator("tr[data-tx-id='TX-B-01'] " + cell).click()
                expect(detail).to_be_hidden()
            page.goto(original)
            link = page.locator("tr[data-tx-id='TX-A-02'] .card-all-row-toggle")
            link.focus()
            link.press('Enter')
            expect(page.locator('#card-detail-TX-A-02')).to_be_visible()
            pending.pop().fulfill(status=503, json={'code': 'UNAVAILABLE'})
            expect(page.locator('#card-detail-TX-A-02')).to_contain_text('닫았다 다시 열어')
            link.press('Escape')
            expect(page.locator('#card-detail-TX-A-02')).to_be_hidden()
            link.press('Space')
            expect(page.locator('#card-detail-TX-A-02 .card-all-spinner')).to_be_visible()
            pending.pop().fulfill(json={'html': '<p>재시도 성공</p>'})
            expect(page.locator('#card-detail-TX-A-02')).to_contain_text('재시도 성공')
            # Nested refund links retain their separate destination.
            page.goto(original)
            page.locator("tr[data-tx-id='TX-A-02'] td.trip a").click()
            page.wait_for_url('**/board?tab=refunds')
            # Selecting source text must not open details.
            page.goto(original)
            row = page.locator("tr[data-tx-id='TX-B-01']")
            row.locator('.merchant-name').evaluate('''e=>{
                const range=document.createRange(); range.selectNodeContents(e);
                const selection=getSelection(); selection.removeAllRanges(); selection.addRange(range);
            }''')
            row.locator('td.amount-cell').dispatch_event('click', {'button': 0})
            assert page.url == original
            assert page.locator('#card-detail-TX-B-01').is_hidden()
            page.evaluate('getSelection().removeAllRanges()')
            # Hold navigation at submission so the old document's loading state can be inspected.
            page.locator('.card-all-filters').evaluate("e=>e.addEventListener('submit',e=>e.preventDefault())")
            page.locator('.card-all-filters input[name=q]').fill('loading')
            page.locator('.card-all-filters button').click()
            expect(page.locator('.card-all-page-loading .card-all-spinner')).to_be_visible()
            page.evaluate("window.dispatchEvent(new Event('pageshow'))")
            expect(page.locator('.card-all-page-loading')).to_be_hidden()
        finally:
            browser.close()
