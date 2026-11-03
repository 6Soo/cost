"""Shared shell mobile header keeps navigation and theme control in one row."""
from webapp import site_shell


def test_standalone_header_theme_is_inline_not_before_menu():
    doc = '<!doctype html><html><head><title>Flight</title></head><body><main>예약</main></body></html>'
    html = site_shell.wrap_document(doc, '/flight-passengers')
    header = html.split('<header class="site-topbar">', 1)[1].split('</header>', 1)[0]
    assert 'site-menu-toggle' in header
    assert 'Flight' in header
    assert 'site-theme-toggle' in header
    assert html.count('id="site-theme-toggle"') == 1
    assert 'site-topbar>.site-theme-bar' in html


def test_theme_remains_visible_on_desktop_and_shares_mobile_row():
    from playwright.sync_api import sync_playwright
    from unittest.mock import patch
    with patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"></aside>'):
        html = site_shell.wrap_document('<html><head></head><body><main>Flight</main></body></html>', '/flight-passengers')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        for width in (375, 1280):
            page.set_viewport_size({'width': width, 'height': 800})
            button = page.locator('#site-theme-toggle')
            assert button.count() == 1 and button.is_visible()
            box = button.bounding_box()
            assert box['width'] >= 44 and box['height'] >= 44
            if width == 375:
                menu = page.locator('.site-menu-toggle').bounding_box()
                assert abs(menu['y'] - box['y']) < 10
        browser.close()
