"""Closed batch review must not compete with the visible expense list."""
import pytest
from playwright.sync_api import sync_playwright, expect
from webapp.card_flow import page


@pytest.mark.parametrize('query', ['', '?batch=synthetic'])
def test_detail_reads_start_once_on_open_and_deep_links_still_start(query):
    document = page('synthetic-csrf').replace(
        '<h1>지출 정리</h1>',
        '<h1>지출 정리</h1><details id="card-review-detail"><summary>Detail</summary>', 1
    ).replace('</main>', '</details></main>', 1)
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            screen = browser.new_page()
            calls, errors = [], []
            screen.on('pageerror', lambda error: errors.append(str(error)))
            screen.route('http://synthetic.test/import*', lambda r: r.fulfill(
                content_type='text/html', body=document))
            def respond(route):
                calls.append((route.request.method, route.request.url))
                route.fulfill(json={'rules': [], 'batches': []})
            screen.route('**/api/imports**', respond)
            screen.goto('http://synthetic.test/import' + query)
            if not query:
                assert calls == []
                screen.locator('#card-review-detail > summary').click()
            expect(screen.locator('#newupload')).to_have_attribute('open', '')
            assert len(calls) == 2 and all(method == 'GET' for method, _ in calls)
            screen.locator('#card-review-detail > summary').click()
            screen.locator('#card-review-detail > summary').click()
            assert len(calls) == 2
            assert errors == []
        finally:
            browser.close()
