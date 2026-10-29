from pathlib import Path
import re

from playwright.sync_api import sync_playwright
from webapp import card_flow, site_shell


SOURCE = Path(__file__).parents[1] / 'card_flow.py'


def _rgb(value):
    if value.startswith('#'):
        value = value[1:]
        if len(value) == 3:
            value = ''.join(channel * 2 for channel in value)
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
    return tuple(int(part) for part in re.findall(r'\d+', value)[:3])


def _contrast_ratio(first, second):
    def luminance(value):
        channels = [channel / 255 for channel in _rgb(value)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
                  for channel in channels]
        return sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear))

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _same_color(first, second):
    return _rgb(first) == _rgb(second)


def test_upload_response_summary_contract_is_ui_only():
    source = SOURCE.read_text(encoding='utf-8')
    for token in ('renderUploadSummary', 'upload_summary', 'monthly_reconciliation',
                  'unknown_date_reconciliation', 'financial_warning', 'masked_identity',
                  "['T','업로드 거래']", "['R','취소 원결제 미연결']"):
        assert token in source
    assert 'CREATE TABLE' not in source[source.index('function renderUploadSummary'):source.index('function render(j')]


def test_summary_browser_escape_layout_warning_and_keyboard():
    source = SOURCE.read_text(encoding='utf-8')
    script = source[source.index('let uploadFailurePage='):source.index(' function render(j')]
    css = next(line for line in source.splitlines() if line.startswith('.upload-table{'))
    counts = dict(T=2, E=1, N=1, C=2, U=0, H=0, P=0, R=1)
    summary = dict(counts=counts, status='passed', rate=100,
                   file=dict(filename='<img src=x onerror=alert(1)>', issuers=['synthetic'],
                             period_start='2026-04-01', period_end='2026-04-30'),
                   duplicate_rows=0, monthly_reconciliation=[dict(month='2026-04', **counts)],
                   unknown_date_reconciliation=[], financial_warning='Original payment unverified', failures=[])
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            for width in (320, 390, 1280):
                page.set_viewport_size(dict(width=width, height=844))
                page.set_content('<style>' + css + '</style><div id="summary"></div>')
                page.evaluate('''() => {
                    window.el = id => document.getElementById(id);
                    window.esc = value => {const node = document.createElement('span');
                        node.textContent = String(value ?? ''); return node.innerHTML;};
                }''')
                page.add_script_tag(content=script)
                page.evaluate('(s) => renderUploadSummary({upload_summary:s})', summary)
                assert page.get_by_role('status').count() == 1
                assert page.get_by_role('alert').count() == 1
                assert page.locator('img').count() == 0
                page.get_by_text('월별 대조', exact=True).focus()
                page.keyboard.press('Enter')
                assert page.locator('details').get_attribute('open') is not None
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#summary').evaluate('(node) => node.innerHTML=""')
                empty = dict(summary, status='empty', rate=None, counts=dict.fromkeys(counts, 0),
                             financial_warning='', monthly_reconciliation=[])
                page.evaluate('(s) => renderUploadSummary({upload_summary:s})', empty)
                assert '검증할 거래 없음' in page.locator('#summary').inner_text()
                assert page.get_by_role('alert').count() == 0
        finally:
            browser.close()


def test_summary_failure_details_include_masked_row_evidence_and_review_link():
    source = SOURCE.read_text(encoding='utf-8')
    script = source[source.index('let uploadFailurePage='):source.index(' function render(j')]
    summary = dict(
        counts=dict(T=1, E=0, N=0, C=0, U=1, H=0, P=0, R=0),
        status='incomplete', rate=0,
        file=dict(filename='synthetic.csv', issuers=['synthetic'],
                  period_start='2026-04-01', period_end='2026-04-01'),
        duplicate_rows=0, monthly_reconciliation=[], unknown_date_reconciliation=[],
        financial_warning='', failures=[dict(
            row_number=17, date='2026-04-01', masked_identity='****1234',
            merchant='Synthetic cafe', amount=1200, currency='KRW', matched=False,
            trip_id='trip-synthetic', item='식비', reason='TRIP_UNRESOLVED',
            basis='synthetic candidate evidence',
            review_url='/import?batch=synthetic&transaction=row-17')])
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content('<div id="summary"></div>')
            page.evaluate('''() => {
                window.el = id => document.getElementById(id);
                window.esc = value => {const node = document.createElement('span');
                    node.textContent = String(value ?? ''); return node.innerHTML;};
            }''')
            page.add_script_tag(content=script)
            page.evaluate('(s) => renderUploadSummary({upload_summary:s})', summary)
            detail = page.locator('#summary .upload-result')
            text = detail.inner_text()
            for value in ('행 17', '****1234', 'Synthetic cafe', 'TRIP_UNRESOLVED',
                          'synthetic candidate evidence'):
                assert value in text
            link = detail.get_by_role('link', name='거래 검토')
            assert link.get_attribute('href') == '/import?batch=synthetic&transaction=row-17'
            assert page.get_by_role('status').count() == 1
        finally:
            browser.close()


def test_summary_failure_pages_bound_large_dom_and_system_errors_are_distinct():
    source = SOURCE.read_text(encoding='utf-8')
    script = source[source.index('let uploadFailurePage='):
                    source.index(' function render(j')]
    failures = [dict(row_number=n + 1, date='2026-04-01', masked_identity='****1234',
                     merchant='Synthetic merchant', amount=1200, currency='KRW',
                     matched=False, trip_id='', item='', reason='TRIP_UNRESOLVED',
                     basis='synthetic', review_url='/import?transaction=row-' + str(n + 1))
                for n in range(10000)]
    summary = dict(counts=dict(T=10000, E=0, N=10000, C=0, U=10000, H=0, P=0, R=0),
                   status='incomplete', rate=0,
                   file=dict(filename='synthetic.csv', issuers=['synthetic'],
                             period_start='2026-04-01', period_end='2026-04-01'),
                   duplicate_rows=0, monthly_reconciliation=[],
                   unknown_date_reconciliation=[], financial_warning='', failures=failures)
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.set_content('<div id="summary"></div>')
            page.evaluate('''() => {
                window.el = id => document.getElementById(id);
                window.esc = value => {const node = document.createElement('span');
                    node.textContent = String(value ?? ''); return node.innerHTML;};
            }''')
            page.add_script_tag(content=script)
            page.evaluate('(s) => renderUploadSummary({upload_summary:s})', summary)
            assert page.locator('#summary .upload-result li').count() == 50
            assert '1–50건 표시' in page.locator('#summary').inner_text()
            page.locator('[data-upload-failure-next]').click()
            assert page.locator('#summary .upload-result li').count() == 50
            assert '51–100건 표시' in page.locator('#summary').inner_text()
            page.locator('[data-upload-failure-next]').click()
            assert page.locator('#summary .upload-result li').count() == 50
            assert '실패 상세 (10000건)' in page.locator('#summary').inner_text()
            assert '101–150건 표시' in page.locator('#summary').inner_text()
            assert page.locator('#summary .upload-result').count() == 1
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

            error_script = source[source.index('function renderUploadSystemError'):
                                  source.index('function renderUploadSummary')]
            page.add_script_tag(content=error_script)
            page.evaluate("() => renderUploadSystemError('합성 시스템 오류')")
            assert page.get_by_role('alert').inner_text().startswith('검증 불가 (파일/시스템 오류)')
            assert '합성 시스템 오류' in page.get_by_role('alert').inner_text()
            assert page.locator('#summary .upload-result').count() == 1
        finally:
            browser.close()


def test_summary_shell_theme_contrast_mobile_overflow_and_paging_focus():
    source = SOURCE.read_text(encoding='utf-8')
    script = source[source.index('let uploadFailurePage='):source.index(' function render(j')]
    error_script = source[source.index('function renderUploadSystemError'):
                          source.index('function renderUploadSummary')]
    app_css = re.search(r'<style>(.*?)</style>', card_flow.PAGE, re.S).group(1)
    document = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<style>' + app_css + '</style></head><body><main>'
                '<section id="summary"></section></main></body></html>')
    wrapped = site_shell.wrap_document(document, '/import')
    failures = [dict(row_number=n + 1, date='2026-04-01', masked_identity='****1234',
                     merchant='Synthetic merchant', amount=1200, currency='KRW',
                     matched=False, trip_id='trip-synthetic', item='식비',
                     reason='TRIP_UNRESOLVED', basis='synthetic evidence',
                     review_url='/import?transaction=row-' + str(n + 1))
                for n in range(101)]
    counts = dict(T=101, E=0, N=101, C=0, U=101, H=0, P=0, R=1)
    summary = dict(counts=counts, status='incomplete', rate=0,
                   file=dict(filename='synthetic.csv', issuers=['synthetic'],
                             period_start='2026-04-01', period_end='2026-04-01'),
                   duplicate_rows=0,
                   monthly_reconciliation=[dict(month='2026-04', **counts)],
                   unknown_date_reconciliation=[],
                   financial_warning='합성 환불 원결제 미확인', failures=failures)

    def snapshot(page, selector):
        return page.locator(selector).evaluate('''element => {
          const style=getComputedStyle(element),root=getComputedStyle(document.documentElement);
          return {theme:document.documentElement.dataset.theme,
            paper:root.getPropertyValue('--shell-paper').trim(),ink:root.getPropertyValue('--shell-ink').trim(),
            warn:root.getPropertyValue('--shell-warn').trim(),bg:style.backgroundColor,color:style.color,
            border:style.borderTopColor};
        }''')

    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={'width': 320, 'height': 844}, color_scheme='light')
            page = context.new_page()
            page.set_content(wrapped)
            assert page.locator('html').get_attribute('data-theme') == 'light'
            page.evaluate('''() => {
                window.el = id => document.getElementById(id);
                window.esc = value => {const node = document.createElement('span');
                    node.textContent = String(value ?? ''); return node.innerHTML;};
            }''')
            page.add_script_tag(content=script)
            page.add_script_tag(content=error_script)
            page.evaluate('(s) => renderUploadSummary({upload_summary:s})', summary)

            for theme in ('light', 'dark'):
                if page.locator('html').get_attribute('data-theme') != theme:
                    page.locator('#site-theme-toggle').focus()
                    page.keyboard.press('Enter')
                    assert page.locator('html').get_attribute('data-theme') == theme

                panel = snapshot(page, '#summary .upload-result')
                warning = snapshot(page, '#summary .financial-warning')
                button = snapshot(page, '[data-upload-failure-prev]')
                assert _same_color(panel['bg'], panel['paper'])
                assert _same_color(panel['color'], panel['ink'])
                assert _same_color(warning['border'], warning['warn'])
                assert _same_color(warning['color'], panel['ink'])
                assert _contrast_ratio(warning['color'], panel['bg']) >= 4.5
                assert _contrast_ratio(warning['border'], panel['bg']) >= 3
                assert _same_color(button['bg'], button['paper'])
                assert _same_color(button['color'], button['ink'])
                assert _contrast_ratio(button['color'], button['bg']) >= 4.5
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

                if theme == 'light':
                    next_button = page.locator('[data-upload-failure-next]')
                    next_button.focus()
                    page.keyboard.press('Enter')
                    assert '2 / 3 페이지' in page.locator('.upload-failure-pages').inner_text()
                    assert page.locator('[data-upload-failure-next]').evaluate(
                        'el => el === document.activeElement')
                    page.keyboard.press('Enter')
                    assert '3 / 3 페이지' in page.locator('.upload-failure-pages').inner_text()
                    assert page.locator('[data-upload-failure-prev]').evaluate(
                        'el => el === document.activeElement')

            page.evaluate("() => renderUploadSystemError('합성 시스템 장애')")
            system_error = snapshot(page, '#summary .upload-system-error')
            assert system_error['theme'] == 'dark'
            assert _same_color(system_error['bg'], system_error['paper'])
            assert _same_color(system_error['color'], system_error['ink'])
            assert _same_color(system_error['border'], system_error['warn'])
            assert _contrast_ratio(system_error['color'], system_error['bg']) >= 4.5
            assert _contrast_ratio(system_error['border'], system_error['bg']) >= 3

            page.locator('#site-theme-toggle').focus()
            page.keyboard.press('Enter')
            page.evaluate("() => renderUploadSystemError('합성 시스템 장애')")
            system_error_light = snapshot(page, '#summary .upload-system-error')
            assert system_error_light['theme'] == 'light'
            assert _same_color(system_error_light['bg'], system_error_light['paper'])
            assert _same_color(system_error_light['color'], system_error_light['ink'])
            assert _same_color(system_error_light['border'], system_error_light['warn'])
            assert _contrast_ratio(system_error_light['color'], system_error_light['bg']) >= 4.5
            assert _contrast_ratio(system_error_light['border'], system_error_light['bg']) >= 3
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()
