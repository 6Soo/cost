"""Shared shell mobile header keeps navigation and theme control in one row."""
from webapp import site_shell
from webapp.static_assets import inline_document


def test_standalone_header_uses_bottom_more_sheet_for_menu_and_theme():
    doc = '<!doctype html><html><head><title>Flight</title></head><body><main>예약</main></body></html>'
    html = site_shell.wrap_document(doc, '/flight-passengers')
    header = html.split('<header class="site-topbar">', 1)[1].split('</header>', 1)[0]
    assert 'site-menu-toggle' not in header
    assert 'Flight' in header
    assert 'site-theme-toggle' in header
    assert html.count('id="site-theme-toggle"') == 1
    assert 'site-more-bottom' in html
    assert 'site-more-theme-slot' in html


def test_native_header_uses_current_title_and_shared_typography_tokens():
    doc = '<html><head><title>장부 &amp; 여행</title></head><body><aside id="nav"></aside><main id="main"><div class="page-hd"><h1>장부</h1></div></main></body></html>'
    result = inline_document(site_shell.wrap_document(doc, '/board'))
    header = result.split('<header class="site-topbar">', 1)[1].split('</header>', 1)[0]
    # The top bar names the screen exactly as its h1 does (2026-11-15 shell requirement).
    assert ">장부</span>" in header and '장부 &amp; 여행' not in header
    assert '<title>장부 · 숲길여행 회계</title>' in result
    assert result.count('id="site-theme-toggle"') == 1
    assert '--shell-title-size: var(--t-h1)' in result
    assert '--t-h1: 1.5rem' in result


def test_theme_remains_visible_on_desktop_and_shares_mobile_row():
    from playwright.sync_api import sync_playwright
    from unittest.mock import patch
    with patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"></aside>'):
        html = inline_document(site_shell.wrap_document('<html><head></head><body><main>Flight</main></body></html>', '/flight-passengers'))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        for width in (375, 1280):
            page.set_viewport_size({'width': width, 'height': 800})
            button = page.locator('#site-theme-toggle')
            if width < 1024:
                assert page.locator('.site-more-bottom').count() == 1
                page.locator('.site-more-bottom').click()
            assert button.count() == 1 and button.is_visible()
            box = button.bounding_box()
            assert box['width'] >= 44 and box['height'] >= 44
            if width < 1024:
                assert page.locator('.site-more-theme-slot #site-theme-toggle').count() == 1
                page.locator('.site-more-close button').click()
        browser.close()
