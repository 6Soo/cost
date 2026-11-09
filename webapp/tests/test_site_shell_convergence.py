"""Targeted test for RF-201/202 shell and theme convergence.

Validates single theme toggle / controller ownership, 320/390/1440 viewports,
200% zoom, theme toggle interaction, and keyboard accessibility.
"""

from unittest.mock import patch
from playwright.sync_api import sync_playwright

from webapp import site_shell, site_theme, flight_passenger_page as flight_page


def test_single_theme_toggle_contract_across_native_and_standalone():
    """Verify exactly one #site-theme-toggle is injected across document types."""
    # 1. Native page (/board): contains id='nav' and id='btn-menu'
    native_doc = """<!doctype html><html lang="ko"><head><title>Board</title></head>
    <body><div id="btn-menu">Menu</div><div id="nav">Nav</div><main id="main"><h1>Content</h1></main></body></html>"""
    wrapped_native = site_shell.wrap_document(native_doc, '/board')
    assert wrapped_native.count('id="site-theme-toggle"') == 1
    assert wrapped_native.count('id="site-shell-style"') == 1

    # 2. Standalone page (/flight-passengers booking)
    with patch('webapp.site_shell._role', return_value='owner'), patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"></aside>'):
        wrapped_flight = site_shell.wrap_document(flight_page._page('csrf-synth'), '/flight-passengers')
    assert wrapped_flight.count('id="site-theme-toggle"') == 1
    assert wrapped_flight.count('id="site-content"') == 1
    assert wrapped_flight.count("id='site-more-dialog'") == 1

    # 3. Standalone legacy view (/flight-passengers?view=participants)
    with patch('webapp.site_shell._role', return_value='owner'), patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"></aside>'):
        wrapped_legacy = site_shell.wrap_document(flight_page._legacy_page('csrf-synth'), '/flight-passengers?view=participants')
    assert wrapped_legacy.count('id="site-theme-toggle"') == 1
    assert wrapped_legacy.count('id="site-content"') == 1


def test_browser_viewports_theme_and_keyboard_accessibility():
    """Synthetic browser tests across 320/390/1440 viewports, 200% zoom, theme, and keyboard."""
    with patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"><a class="brand brand-link" href="/">홈</a><div class="site-links"><a href="/cards/all">카드</a><a href="/flight-passengers">항공권</a></div></aside>'):
        doc_page = site_shell.wrap_document(flight_page._page('csrf-synth'), '/flight-passengers')

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            context = browser.new_context(viewport={'width': 320, 'height': 800}, color_scheme='light')
            context.route('http://test.local/flight-passengers', lambda route: route.fulfill(
                status=200, content_type='text/html; charset=utf-8', body=doc_page))
            page = context.new_page()
            page.goto('http://test.local/flight-passengers')

            # 1. Responsive viewports: 320, 390, 1440
            for width in (320, 390, 1440):
                page.set_viewport_size({'width': width, 'height': 800})
                scroll_w = page.evaluate('document.documentElement.scrollWidth')
                inner_w = page.evaluate('window.innerWidth')
                assert scroll_w <= inner_w, f"Horizontal overflow at {width}px: {scroll_w} > {inner_w}"
                toggle = page.locator('#site-theme-toggle')
                assert toggle.count() == 1
                assert toggle.is_visible()
                box = toggle.bounding_box()
                assert box['width'] >= 44 and box['height'] >= 44

            # 2. 200% Zoom reflow at desktop and mobile widths
            for width in (640, 1440):
                page.set_viewport_size({'width': width, 'height': 800})
                page.evaluate('document.documentElement.style.zoom="200%"')
                toggle = page.locator('#site-theme-toggle')
                assert toggle.is_visible()
                assert page.get_by_role('heading', name='항공권 예약 확인').is_visible()

            # 3. Theme toggle interaction: light -> dark -> light
            page.evaluate('document.documentElement.style.zoom="100%"')
            page.set_viewport_size({'width': 390, 'height': 800})
            toggle = page.locator('#site-theme-toggle')
            assert page.locator('html').get_attribute('data-theme') == 'light'
            toggle.click()
            assert page.locator('html').get_attribute('data-theme') == 'dark'
            assert page.evaluate("localStorage.getItem('cost-theme')") == 'dark'
            toggle.click()
            assert page.locator('html').get_attribute('data-theme') == 'light'
            assert page.evaluate("localStorage.getItem('cost-theme')") == 'light'

            # 4. Keyboard accessibility: Focus + Space on theme toggle
            toggle.focus()
            assert page.evaluate('document.activeElement.id') == 'site-theme-toggle'
            page.keyboard.press('Space')
            assert page.locator('html').get_attribute('data-theme') == 'dark'
            page.keyboard.press('Space')
            assert page.locator('html').get_attribute('data-theme') == 'light'

            # 5. Mobile more-dialog keyboard navigation
            menu = page.locator('.site-more-toggle')
            menu.focus()
            assert menu.evaluate('(el)=>el===document.activeElement')
            menu.press('Enter')
            assert page.locator('#site-more-dialog').evaluate('(el)=>el.open')
            page.keyboard.press('Escape')
            assert not page.locator('#site-more-dialog').evaluate('(el)=>el.open')

        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.close()
