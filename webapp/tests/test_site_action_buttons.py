"""Shared action decoration must preserve native interactions and dynamic labels."""
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from webapp import site_shell


def test_actions_preserve_labels_handlers_and_dynamic_content():
    original = '''<!doctype html><html lang="ko"><body><main>
    <button id="save" onclick="this.dataset.clicked='yes'">저장</button>
    <button id="disabled" disabled>삭제</button>
    <a id="back" href="/board">장부로 돌아가기</a>
    <table><tr><td><a id="merchant" href="/row?id=synthetic">합성 가맹점</a></td></tr></table>
    <details><summary id="upload">카드 사용내역 업로드</summary><p>내용</p></details>
    <button id="existing"><svg aria-hidden="true"></svg>검색</button>
    <div id="dynamic"></div></main></body></html>'''
    with patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"></aside>'):
        document = site_shell.wrap_document(original, '/import')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('http://synthetic.local/**', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=document))
            page.goto('http://synthetic.local/import')
            save = page.get_by_role('button', name='저장', exact=True)
            save.focus()
            page.keyboard.press('Enter')
            assert save.get_attribute('data-clicked') == 'yes'
            assert save.inner_text() == '저장'
            assert save.locator('*').count() == 0  # no children to disrupt legacy handlers
            assert page.locator('#disabled').is_disabled()
            assert page.locator('#merchant').get_attribute('class') is None
            assert 'site-action-icon' not in page.locator('#existing').get_attribute('class')
            page.locator('#upload').focus()
            page.keyboard.press('Space')
            assert page.locator('details').get_attribute('open') is not None
            page.evaluate("document.querySelector('#dynamic').innerHTML='<button id=late>수정</button>'")
            page.wait_for_function("document.querySelector('#late').classList.contains('site-action-icon')")
            page.evaluate("document.querySelector('#late').textContent='저장'")
            page.wait_for_function("document.querySelector('#late').style.getPropertyValue('--action-icon')===document.querySelector('#save').style.getPropertyValue('--action-icon')")
            for width in (320, 390, 1440):
                page.set_viewport_size({'width': width, 'height': 844})
                for theme in ('light', 'dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                    for selector in ('#save', '#back', '#upload', '#late'):
                        metrics = page.locator(selector).evaluate('''el=>({height:el.getBoundingClientRect().height,
                            mask:getComputedStyle(el,'::before').maskImage,
                            border:getComputedStyle(el).borderStyle})''')
                        assert metrics['height'] >= (44 if width < 760 else 36)
                        assert metrics['mask'].startswith('url(')
                        assert metrics['border'] == 'solid'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert errors == []
        finally:
            browser.close()
