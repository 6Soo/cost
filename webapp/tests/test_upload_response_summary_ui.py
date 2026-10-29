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
    script = source[source.index('function renderUploadSummary'):source.index(' function render(j')]
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
