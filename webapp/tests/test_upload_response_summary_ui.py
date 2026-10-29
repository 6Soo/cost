from pathlib import Path

from playwright.sync_api import sync_playwright


SOURCE = Path(__file__).parents[1] / 'card_flow.py'


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
