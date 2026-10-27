"""Contract: OTA review starts closed and does not fetch until requested."""
from webapp.ota_payment_review import render_import_section
from playwright.sync_api import sync_playwright, expect
import pytest


def test_ota_review_is_lazy_and_expandable():
    html = render_import_section("csrf-test")
    assert '<details id="ota-review"' in html
    assert '<summary id="ota-title"' in html
    assert "if(root.open)loadQueue();" in html
    assert "/api/imports/ota/summary" in html
    assert "location.hash==='#ota-review'" in html
    assert "root.addEventListener('toggle'" in html
    assert "/api/imports/ota" in html
    assert '<div id="ota-events"></div>' in html


def test_lazy_review_fetches_on_open_and_reopen_but_not_when_closed():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 375, 'height': 812})
            page.clock.install()
            requests = []
            def respond(route):
                requests.append(route.request.url)
                route.fulfill(json={'status': 'ready', 'generation': 1, 'fresh': True,
                                    'stale': False, 'refreshing': False, 'counts_by_queue': {}}
                              if route.request.url.endswith('/summary') else
                              {'generation': 1, 'items': [], 'next_cursor': None})
            page.route('**/api/imports/ota/**', respond)
            page.set_content("<base href='http://localhost/'>" + render_import_section('synthetic'))
            page.clock.run_for(200)
            assert requests == []
            summary = page.locator('#ota-review > summary')
            summary.click()
            expect(page.locator('#ota-status')).to_have_text('연결 검토 목록을 불러왔습니다.')
            assert len(requests) == 2
            page.locator('#ota-events').evaluate("el => el.innerHTML = '<div class=ota-card-row><input type=radio checked value=choice-syn></div>'")
            summary.click()
            expect(page.locator('#ota-review')).not_to_have_attribute('open', '')
            page.clock.run_for(11000)
            assert len(requests) == 2
            summary.click()
            page.wait_for_function("document.querySelector('#ota-review').open")
            page.clock.run_for(200)
            assert len(requests) == 2
            expect(page.locator('#ota-events input')).to_be_checked()
            page.locator('#ota-events input').evaluate('el => el.checked = false')
            page.clock.run_for(11000)
            expect(page.locator('#ota-events')).to_have_text('이 페이지에 표시할 거래가 없습니다.')
            assert len(requests) == 4
            assert all('/api/imports/ota' in url for url in requests)
            assert page.evaluate('document.documentElement.scrollWidth') <= 375
        finally:
            browser.close()


@pytest.mark.parametrize('suffix', ['#ota-review', '?transaction=synthetic'])
def test_explicit_review_deep_links_open_and_load(suffix):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route('http://localhost/', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=render_import_section('synthetic')))
            page.route('http://localhost/?transaction=synthetic', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=render_import_section('synthetic')))
            page.route('**/api/imports/ota/**', lambda route: route.fulfill(json={
                'status': 'ready', 'generation': 1, 'fresh': True, 'stale': False,
                'refreshing': False, 'counts_by_queue': {}}
                if route.request.url.endswith('/summary') else
                {'generation': 1, 'items': [], 'next_cursor': None}))
            page.goto('http://localhost/' + suffix)
            expect(page.locator('#ota-review')).to_have_attribute('open', '')
            expect(page.locator('#ota-status')).to_have_text('연결 검토 목록을 불러왔습니다.')
        finally:
            browser.close()
