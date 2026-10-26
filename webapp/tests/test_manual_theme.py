import re
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from webapp import ledger_design, site_shell, card_catalog, flight_passenger_page, receipt_review


def document(css, native=False):
    content = '<input id="draft" value="unsaved"><article id="card">Synthetic</article>'
    if native:
        content = "<div class='app'><aside id='nav'></aside><main class='main' id='main'>" + content + '</main></div>'
    source = '<html><head><meta charset="utf-8"><style>' + css + '</style></head><body>' + content + '</body></html>'
    with patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"></aside>'):
        return site_shell.wrap_document(source, '/board' if native else '/cards/all')


def test_theme_button_overrides_system_and_preserves_only_local_choice():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(color_scheme='dark')
        context.route('http://theme.test/**', lambda route: route.fulfill(
            body=document(card_catalog.CATALOG_STYLE), content_type='text/html'))
        page = context.new_page()
        page.goto('http://theme.test/first')
        button = page.locator('#site-theme-toggle')
        assert button.count() == 1
        assert button.inner_text() == ''
        assert button.get_attribute('aria-label') == '라이트모드로 전환'
        assert page.evaluate("getComputedStyle(document.body).backgroundColor") == 'rgb(17, 24, 32)'
        page.locator('#draft').fill('keep this text')
        requests = []
        page.on('request', lambda request: requests.append(request.url))
        button.focus()
        page.keyboard.press('Enter')
        assert button.get_attribute('aria-label') == '다크모드로 전환'
        assert page.evaluate("getComputedStyle(document.body).backgroundColor") == 'rgb(247, 249, 252)'
        assert page.locator('#draft').input_value() == 'keep this text'
        assert requests == []
        assert page.evaluate('Object.keys(localStorage)') == ['cost-theme']
        page.goto('http://theme.test/second')
        assert page.locator('html').get_attribute('data-theme') == 'light'
        page.emulate_media(color_scheme='dark')
        assert page.locator('html').get_attribute('data-theme') == 'light'
        page.reload()
        assert page.locator('html').get_attribute('data-theme') == 'light'
        browser.close()


def test_system_storage_failures_and_responsive_theme_control():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(color_scheme='light')
        context.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw Error('blocked')}})")
        context.route('http://theme.test/**', lambda route: route.fulfill(
            body=document('body{background:var(--shell-bg)}', native=True), content_type='text/html'))
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://theme.test/')
        assert page.locator('html').get_attribute('data-theme') == 'light'
        page.emulate_media(color_scheme='dark')
        page.wait_for_function("document.documentElement.dataset.theme==='dark'")
        for width in (375, 390, 759, 760, 1280):
            page.set_viewport_size({'width': width, 'height': 800})
            button = page.locator('#site-theme-toggle')
            box = button.bounding_box()
            assert box['width'] >= 44 and box['height'] >= 44
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
        button.focus()
        page.keyboard.press('Space')
        assert page.locator('html').get_attribute('data-theme') == 'light'
        assert not errors
        browser.close()


def test_real_page_palettes_follow_choice_with_invalid_storage_and_cross_tab_updates():
    flight_css = re.search(r'<style>(.*?)</style>', flight_passenger_page._page(''), re.S)[1]
    palettes = {'ledger': ledger_design.STYLE, 'flight': flight_css, 'receipt': receipt_review.PAGE_CSS}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(color_scheme='light')
        context.add_init_script("if(!localStorage.getItem('cost-theme'))localStorage.setItem('cost-theme','invalid')")
        def serve_palette(route):
            if route.request.resource_type != 'document':
                route.abort()
                return
            route.fulfill(body=document(palettes[route.request.url.rsplit('/', 1)[-1]], native=True),
                          content_type='text/html')
        context.route('http://theme.test/**', serve_palette)
        page = context.new_page()
        for name in palettes:
            page.goto('http://theme.test/' + name)
            assert page.locator('html').get_attribute('data-theme') == 'light'
            page.locator('#site-theme-toggle').click()
            assert page.locator('html').get_attribute('data-theme') == 'dark'
            assert page.evaluate('getComputedStyle(document.body).backgroundColor') == 'rgb(15, 23, 42)'
            assert page.evaluate("getComputedStyle(document.querySelector('#nav')).backgroundColor") == 'rgb(15, 23, 42)'
            page.emulate_media(color_scheme='light')
            assert page.locator('html').get_attribute('data-theme') == 'dark'
            page.locator('#site-theme-toggle').click()
            assert page.evaluate('getComputedStyle(document.body).backgroundColor') == 'rgb(248, 250, 252)'
            page.evaluate("document.documentElement.style.zoom='2'")
            page.set_viewport_size({'width': 760, 'height': 800})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.evaluate("document.documentElement.style.zoom='1'")
        other = context.new_page()
        other.goto('http://theme.test/flight')
        other.locator('#site-theme-toggle').click()
        page.wait_for_function("document.documentElement.dataset.theme==='dark'")
        other.evaluate("localStorage.removeItem('cost-theme')")
        page.wait_for_function("document.documentElement.dataset.theme==='light'")
        browser.close()
