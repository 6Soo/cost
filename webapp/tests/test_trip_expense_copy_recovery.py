"""A rejected clipboard must leave complete, selectable expense TSV to finish."""
import json

import pytest
from playwright.sync_api import expect, sync_playwright

from webapp import ledger_design as design
from webapp.static_assets import inline_document
from webapp.tests.test_expense_copy_states import copy_state


HTML = '<table><tbody><tr><td style="text-align:left">합성 거래처</td></tr></tbody></table>'


@pytest.mark.parametrize('width', [1440, 390, 320])
def test_pending_clipboard_recovers_and_native_retry_pastes_exact_tsv(copy_state, width):
    rows, preview = copy_state
    tsv = '2026-10-01\t합성 거래처\t식비\t\t\t카드\t1000'
    document = inline_document(design.render(
        "<main id='main'>" + design._trip_copy_html('trip-synthetic', rows, preview) + '</main>'))
    calls = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000},
                                    permissions=['clipboard-read', 'clipboard-write'])
            page.route('http://127.0.0.1:9876/board**', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=document))

            def api(route):
                calls.append(route.request.method)
                route.fulfill(json=dict(tsv=tsv, row_count=1, total_krw=1000,
                                        source_available=True, held=[], matched=[]))

            page.route('http://127.0.0.1:9876/api/**', api)
            page.goto('http://127.0.0.1:9876/board')
            page.evaluate('''() => {
                window.originalExec = document.execCommand.bind(document);
                window.clipboardCalls = 0;
                navigator.clipboard.writeText = () => {
                    window.clipboardCalls++;
                    return new Promise(resolve => {window.resolveClipboard = resolve;});
                };
                document.execCommand = () => false;
            }''')
            button = page.get_by_role('button', name='Google 장부용 복사', exact=True)
            button.click()
            content = page.get_by_role('textbox', name='Google 시트에 붙여넣을 지출내용')
            expect(content).to_be_visible(timeout=3000)
            expect(button).to_be_enabled(timeout=4000)
            expect(content).to_have_value(tsv)
            expect(content).to_be_focused()
            expect(page.locator('#copy-status')).to_contain_text('선택된 내용을 복사')
            expect(page.locator('.trip-copy-wrap')).not_to_have_attribute('aria-busy', 'true')
            assert page.evaluate('window.clipboardCalls') == 1
            # A late API resolution must not announce success or hide recovery.
            page.evaluate('window.resolveClipboard()')
            expect(content).to_be_visible()
            expect(page.locator('#copy-status')).not_to_contain_text('복사되었습니다')
            page.evaluate('document.execCommand = window.originalExec')
            retry = page.get_by_role('button', name='다시 복사', exact=True)
            retry.focus()
            retry.press('Enter')
            expect(page.locator('#copy-status')).to_contain_text('지출내용이 복사되었습니다')
            assert page.evaluate('window.clipboardCalls') == 1
            page.evaluate('''() => {
                const input = document.createElement('textarea');
                input.id = 'paste-verification';
                document.body.appendChild(input);
                input.focus();
            }''')
            page.keyboard.press('Control+V')
            expect(page.locator('#paste-verification')).to_have_value(tsv)
            assert calls == ['GET']
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()


def test_rich_copy_keeps_html_alignment_and_retry_payload(copy_state):
    rows, preview = copy_state
    tsv = '2026-10-01\t합성 거래처\t식비\t\t\t카드\t1000'
    document = inline_document(design.render(
        "<main id='main'>" + design._trip_copy_html('trip-synthetic', rows, preview) + '</main>'))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(permissions=['clipboard-read', 'clipboard-write'])
            page.route('http://127.0.0.1:9876/board**', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=document))
            page.route('http://127.0.0.1:9876/api/**', lambda route: route.fulfill(
                json=dict(tsv=tsv, html=HTML, row_count=1, total_krw=1000,
                          source_available=True, held=[], matched=[])))
            page.goto('http://127.0.0.1:9876/board')
            page.evaluate('''() => {
                window.copyPayloads = [];
                document.addEventListener('copy', event => {
                    window.copyPayloads.push({
                        plain: event.clipboardData.getData('text/plain'),
                        html: event.clipboardData.getData('text/html'),
                        cancelled: event.defaultPrevented,
                    });
                });
            }''')

            page.get_by_role('button', name='Google 장부용 복사', exact=True).click()
            expect(page.locator('#copy-status')).to_contain_text('지출내용이 복사되었습니다')
            assert page.evaluate('window.copyPayloads[0].plain') == tsv
            assert page.evaluate('window.copyPayloads[0].html') == HTML
            assert page.evaluate('window.copyPayloads[0].cancelled')

            clipboard = page.evaluate('''async () => {
                const values = [];
                for (const item of await navigator.clipboard.read()) {
                    for (const type of item.types) {
                        values.push({type, value: await (await item.getType(type)).text()});
                    }
                }
                return values;
            }''')
            types = {item['type']: item['value'] for item in clipboard}
            assert types['text/plain'] == tsv
            assert types['text/html'] == HTML
            assert 'text-align:left' in types['text/html']

            prepared = page.locator('.trip-copy-manual textarea')
            assert prepared.evaluate('e => e.dataset.html') == HTML
            # The retry control stays in the prepared snapshot so a second copy
            # cannot lose the alignment metadata after the first success.
            page.locator('[data-copy-prepared]').evaluate('element => element.click()')
            expect(page.locator('#copy-status')).to_contain_text('지출내용이 복사되었습니다')
            assert len(page.evaluate('window.copyPayloads')) == 2
            assert page.evaluate('window.copyPayloads[1].plain') == tsv
            assert page.evaluate('window.copyPayloads[1].html') == HTML

            page.evaluate('''() => {
                const input = document.createElement('textarea');
                input.id = 'paste-verification';
                document.body.appendChild(input);
                input.focus();
            }''')
            page.keyboard.press('Control+V')
            expect(page.locator('#paste-verification')).to_have_value(tsv)
        finally:
            browser.close()


def test_rich_copy_failure_shows_manual_retry_without_text_only_downgrade(copy_state):
    rows, preview = copy_state
    tsv = '2026-10-01\t합성 거래처\t식비\t\t\t카드\t1000'
    document = inline_document(design.render(
        "<main id='main'>" + design._trip_copy_html('trip-synthetic', rows, preview) + '</main>'))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route('http://127.0.0.1:9876/board**', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=document))
            page.route('http://127.0.0.1:9876/api/**', lambda route: route.fulfill(
                json=dict(tsv=tsv, html=HTML, row_count=1, total_krw=1000,
                          source_available=True, held=[], matched=[])))
            page.goto('http://127.0.0.1:9876/board')
            page.evaluate('''() => {
                window.originalWriteText = navigator.clipboard.writeText.bind(navigator.clipboard);
                window.writeTextCalls = 0;
                navigator.clipboard.writeText = async () => {
                    window.writeTextCalls++;
                    return undefined;
                };
                document.execCommand = () => false;
            }''')
            page.get_by_role('button', name='Google 장부용 복사', exact=True).click()
            content = page.get_by_role('textbox', name='Google 시트에 붙여넣을 지출내용')
            expect(content).to_be_visible()
            expect(content).to_have_value(tsv)
            expect(page.locator('.trip-copy-manual')).to_be_visible()
            expect(page.locator('#copy-status')).to_contain_text('선택된 내용을 복사')
            expect(page.locator('#copy-status')).not_to_contain_text('복사되었습니다')
            assert page.evaluate('window.writeTextCalls') == 0
            assert content.evaluate('e => e.dataset.html') == HTML
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1440, 390, 320])
def test_unfocused_clipboard_leaves_selectable_tsv_and_retry_copies(copy_state, width):
    rows, preview = copy_state
    tsv = '2026-10-01\t합성 거래처\t식비\t\t\t카드\t1000'
    exported = dict(tsv=tsv, row_count=1, total_krw=1000, source_available=True,
                    held=[{'transaction_id': 'tx-2', 'reason': 'ambiguous'}], matched=[{}, {}],
                    reconciliation={'cost_rows': [dict(transaction_id='tx-2', row_id='fresh&row',
                        occurred_on='2026-10-02', merchant='<새 대조 거래>', amount_krw=2000)]})
    document = inline_document(design.render(
        "<main id='main'>" + design._trip_copy_html('trip-synthetic', rows, preview) + '</main>'))
    requests = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            context = browser.new_context(viewport={'width': width, 'height': 1000},
                                          permissions=['clipboard-read', 'clipboard-write'])
            page = context.new_page()
            page.route('http://127.0.0.1:9876/board**', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=document))

            def api(route):
                request = route.request
                requests.append((request.method, request.url))
                payload = exported if '/tsv' in request.url or request.method == 'POST' else {
                    **preview, 'links_revision': 0, 'preview_digest': 'synthetic'}
                route.fulfill(content_type='application/json', body=json.dumps(payload))

            page.route('http://127.0.0.1:9876/api/**', api)
            page.goto('http://127.0.0.1:9876/board?tab=trip-synthetic&q=Cafe&kind=ex')
            page.evaluate('''() => {
                window.originalWrite = navigator.clipboard.writeText.bind(navigator.clipboard);
                window.originalExec = document.execCommand.bind(document);
                navigator.clipboard.writeText = async () => {
                    throw new DOMException("Failed to execute 'writeText' on 'Clipboard': Document is not focused.", 'NotAllowedError');
                };
                document.execCommand = () => false;
            }''')
            page.get_by_role('button', name='Google 장부용 복사', exact=True).click()
            content = page.get_by_role('textbox', name='Google 시트에 붙여넣을 지출내용')
            expect(content).to_be_visible()
            expect(content).to_have_value(tsv)
            expect(content).to_be_focused()
            assert content.evaluate('e => e.selectionEnd - e.selectionStart') == len(tsv)
            expect(page.locator('#copy-status')).to_contain_text('선택된 내용을 복사')
            expect(page.locator('#copy-status')).not_to_contain_text('복사되었습니다')
            assert requests == [('GET', 'http://127.0.0.1:9876/api/tabs/trip-synthetic/tsv?q=Cafe&kind=ex')]
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            detail = page.locator('.trip-copy-excluded')
            expect(detail).to_contain_text('2026-10-02 · <새 대조 거래> · 2,000원')
            expect(detail.locator('a')).to_have_attribute('href', '/row?id=fresh%26row')
            assert detail.locator('새').count() == 0
            page.evaluate('''() => {
                navigator.clipboard.writeText = window.originalWrite;
                document.execCommand = window.originalExec;
            }''')
            page.get_by_role('button', name='다시 복사', exact=True).click()
            expect(page.locator('#copy-status')).to_contain_text('지출내용이 복사되었습니다')
            assert page.evaluate('navigator.clipboard.readText()') == tsv
            assert len(requests) == 1
            expect(content).not_to_be_visible()
            expect(page.get_by_role('button', name='Google 장부용 복사', exact=True)).to_be_focused()
        finally:
            browser.close()


@pytest.mark.parametrize('response,code,message', [
    ({'message': '다시 로그인해 주세요.'}, 401, '다시 로그인'),
    ({'source_available': False}, 200, '장부를 동기화'),
    ({'source_available': True, 'row_count': 0, 'held': [{}]}, 200, '복사할 수 있는 지출이 없습니다'),
    ({'source_available': True, 'row_count': 1, 'tsv': ''}, 200, '내용을 확인하지 못했습니다'),
])
def test_copy_failure_restores_action_without_exposing_stale_text(copy_state, response, code, message):
    rows, preview = copy_state
    document = inline_document(design.render(
        "<main id='main'>" + design._trip_copy_html('trip-synthetic', rows, preview) + '</main>'))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route('http://127.0.0.1:9876/board**', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=document))
            page.route('http://127.0.0.1:9876/api/**', lambda route: route.fulfill(
                status=code, json=response))
            page.goto('http://127.0.0.1:9876/board')
            button = page.get_by_role('button', name='Google 장부용 복사', exact=True)
            button.click()
            expect(page.locator('#copy-status')).to_contain_text(message)
            expect(button).to_be_enabled()
            expect(page.locator('.trip-copy-manual')).not_to_be_visible()
            expect(page.locator('#copy-status')).not_to_contain_text('복사되었습니다')
        finally:
            browser.close()


def test_excluded_transactions_are_identifiable_and_escaped(copy_state):
    rows, preview = copy_state
    rows[3].update(source_merchant='<img src=x>', row_id='row&3')
    markup = design._trip_copy_html('trip-synthetic', rows, preview)
    assert '2026-10-01' in markup and '&lt;img src=x&gt;' in markup and '1,000원' in markup and '<img src=x>' not in markup
    # Detail opens in place now; the row id rides on the toggle, escaped.
    assert "data-row-id='row&amp;3'" in markup and 'aria-controls=' in markup
    assert '<img src=x>' not in markup


@pytest.mark.parametrize('code,body', [(502, '<!DOCTYPE html><title>Bad Gateway</title>'),
                                     (200, '<!DOCTYPE html><title>Unexpected login page</title>')])
def test_html_response_has_recovery_message_and_retry_fetches_fresh_content(copy_state, code, body):
    rows, preview = copy_state
    document = inline_document(design.render(
        "<main id='main'>" + design._trip_copy_html('trip-synthetic', rows, preview) + '</main>'))
    calls = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 320, 'height': 1000})
            page.route('http://127.0.0.1:9876/board**', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=document))

            def api(route):
                calls.append(route.request.method)
                if len(calls) == 1:
                    route.fulfill(status=code, content_type='text/html', body=body)
                else:
                    route.fulfill(json={'source_available': True, 'row_count': 0, 'held': []})

            page.route('http://127.0.0.1:9876/api/**', api)
            page.goto('http://127.0.0.1:9876/board')
            button = page.get_by_role('button', name='Google 장부용 복사', exact=True)
            button.click()
            expect(page.locator('#copy-status')).to_contain_text('잠시 후 다시 복사해 주세요')
            expect(page.locator('#copy-status')).not_to_contain_text('Unexpected token')
            expect(button).to_be_enabled()
            expect(page.locator('.trip-copy-manual')).not_to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            button.focus()
            button.press('Enter')
            expect(page.locator('#copy-status')).to_contain_text('복사할 지출이 없습니다')
            assert calls == ['GET', 'GET']
        finally:
            browser.close()
