"""Boundary contract plus runtime menu checks at rounded iframe viewports.

Headless Chromium rounds fractional iframe widths differently from the live
Windows browser. The CSSOM check guards the fractional interval explicitly;
the real-browser before/after reproduction is recorded separately.
"""
import html
from unittest.mock import patch

import pytest
from playwright.sync_api import sync_playwright, expect

from webapp import ledger_design, site_shell


@pytest.mark.parametrize('native', [False, True])
def test_fractional_mobile_breakpoint_has_no_menu_gap(native):
    nav = '<aside id="nav" class="nav"><a href="/board">장부</a></aside><div id="nav-mask" class="nav-mask" hidden></div>'
    content = "<div class='app'>" + nav + "<main id='main' class='main'><button id='btn-menu' type='button' aria-label='전체 메뉴 열기' aria-expanded='false'>메뉴</button><h1>합성 장부</h1></main></div>" if native else '<main><h1>합성 화면</h1></main>'
    source = '<html><head><meta charset="utf-8"><style>' + ledger_design.STYLE + '</style></head><body>' + content + '</body></html>'
    with patch('webapp.ledger_design._nav_html', return_value=nav):
        document = site_shell.wrap_document(source, '/board' if native else '/flight-passengers')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        screen = browser.new_page(viewport={'width': 1280, 'height': 900}, device_scale_factor=1.25)
        screen.set_content('<iframe style="width:759.25px;height:800px;border:0" srcdoc="' + html.escape(document, quote=True) + '"></iframe>')
        frame = screen.frames[1]
        media = frame.evaluate("[...document.styleSheets].flatMap(s=>[...s.cssRules]).filter(r=>r.type===CSSRule.MEDIA_RULE).map(r=>r.conditionText)")
        assert any('759.98px' in condition for condition in media)
        assert not any('759px' in condition for condition in media)
        assert frame.evaluate("matchMedia('(width < 760px)').matches")
        menu = frame.locator('#btn-menu' if native else '.site-menu-toggle')
        expect(menu).to_be_visible()
        assert frame.locator('#nav').evaluate('e=>e.getBoundingClientRect().right') <= 1
        menu.click()
        expect(menu).to_have_attribute('aria-expanded', 'true')
        expect(frame.locator('#nav')).to_have_class('nav open')
        screen.keyboard.press('Escape')
        expect(menu).to_have_attribute('aria-expanded', 'false')
        screen.locator('iframe').evaluate("e=>e.style.width='760px'")
        expect(menu).not_to_be_visible()
        assert frame.evaluate('document.documentElement.scrollWidth<=innerWidth')
        browser.close()
