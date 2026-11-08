"""User-visible duplicate protection in the existing trip expense list."""
from copy import deepcopy

import pytest

from webapp import ledger_board as board, ledger_design as design


@pytest.fixture
def copy_state(monkeypatch):
    monkeypatch.setattr(board, 'current_role', lambda: 'owner')
    monkeypatch.setattr(design, '_is_trip_tab', lambda tab: tab == 'trip-synthetic')
    rows = [dict(row_id=f'row-{i}', source_event_id=f'tx-{i}', row_kind='expense',
                 display_tab_id='trip-synthetic', occurred_on='2026-10-01',
                 source_merchant='합성 거래처', item='식비', evidence_type='카드',
                 amount_krw=1000) for i in range(4)]
    statuses = ('MATCHED_MANUAL', 'MATCHED_EXISTING', 'NEW_EXPENSE', 'REVIEW_CONFLICT')
    preview = dict(source_available=True,
                   results=[dict(transaction_id=f'tx-{i}', status=status, basis=[])
                            for i, status in enumerate(statuses)],
                   counts={status: 1 for status in statuses})
    return rows, preview


def test_trip_copy_excludes_existing_and_ambiguous_rows_without_mutation(copy_state):
    rows, preview = copy_state
    before = deepcopy((rows, preview))
    markup = design._trip_copy_html('trip-synthetic', rows, preview)
    assert '복사 가능 1건 · 1,000원 · Google 장부 일치 2건 제외 · Google 대조 보류 1건 제외' in markup
    assert 'Google 대조 보류 건의 정체와 사유 보기' in markup
    assert 'Google 원장 대조를 확정하지 못함' in markup
    assert ' disabled' not in markup
    assert 'expense-reconciliation' not in markup and '수기 지출 대조' not in markup
    assert 'trip-expense-copy' in markup
    assert (rows, preview) == before


def test_source_failure_has_one_notice_no_per_transaction_tasks(copy_state):
    rows, preview = copy_state
    preview.update(source_available=False)
    annotations = design._google_match_annotations('trip-synthetic', rows, preview)
    assert annotations == {}
    markup = design._trip_copy_html('trip-synthetic', rows, preview)
    assert markup.count('Google 장부를 불러오지 못해') == 1
    assert ' disabled' in markup and '안전 보류' not in markup
    assert '0건' not in markup and 'SOURCE_NOT_VERIFIED' not in markup
    table = design._tables_html([], rows, selected='', unclassified=False,
                                amount_groups={'available': False, 'reason': 'SOURCE_NOT_VERIFIED'})
    assert '비교 불가' not in table and 'SOURCE_NOT_VERIFIED' not in table


def test_all_recorded_disables_copy_and_viewer_has_no_copy_controls(copy_state, monkeypatch):
    rows, preview = copy_state
    markup = design._trip_copy_html('trip-synthetic', rows[:2], {
        **preview, 'results': preview['results'][:2]})
    assert '복사 가능 0건' in markup and 'Google 장부 일치 2건 제외' in markup
    assert ' disabled' in markup
    monkeypatch.setattr(board, 'current_role', lambda: 'viewer')
    assert design._trip_copy_html('trip-synthetic', rows, preview) == ''
    assert design._google_match_annotations('trip-synthetic', rows, preview) == {}


def test_total_mismatch_explains_real_cause_and_offers_source_recovery(copy_state):
    rows, preview = copy_state
    preview.update(source_available=True,
                   source_info={'warning': 'SOURCE_EXPENSE_TOTAL_MISMATCH'})
    markup = design._trip_copy_html('trip-synthetic', rows, preview)
    assert 'Google 합계 수식은 확인 필요' in markup
    assert '복사 가능 1건' in markup
    assert "aria-describedby='trip-copy-desc'" in markup
    assert ' disabled' not in markup


def test_blocked_and_company_excluded_rows_never_count_as_copyable(copy_state):
    rows, preview = copy_state
    for flag in ('blocked', 'excluded_from_company'):
        costs = deepcopy(rows)
        costs[2][flag] = True
        markup = design._trip_copy_html('trip-synthetic', costs, preview)
        assert '복사 가능 0건' in markup and ' disabled' in markup
        annotations = design._google_match_annotations('trip-synthetic', costs, preview)
        assert annotations['row-2']['label'] == '복사 제외 · 거래 상세 확인'


def test_internal_copy_labels_do_not_inflate_transaction_rows(copy_state):
    from playwright.sync_api import sync_playwright
    rows, preview = copy_state
    before = deepcopy(rows)
    annotations = design._google_match_annotations('trip-synthetic', rows, preview)
    annotations['row-3']['label'] += '<img src=x onerror=alert(1)>'
    markup = (design._tables_html([], rows, selected='', unclassified=False,
                                 match_annotations=annotations)
              + design._mobile_html([], rows, selected='', unclassified=False,
                                    match_annotations=annotations)
              + design._trip_copy_html('trip-synthetic', rows, preview))
    assert '<img src=x' not in markup and '&lt;img' in markup
    document = design.render("<main id='main'>" + markup + '</main>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(document)
            for theme in ('light', 'dark'):
                page.emulate_media(color_scheme=theme)
                for width in (320, 390, 760, 1280):
                    page.set_viewport_size({'width': width, 'height': 850})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    scope = page.locator('.lst') if width < 760 else page.locator('#tbl')
                    assert scope.locator('.expense-copy-state').count() == 0
                    visible_text = scope.evaluate('''element => {
                        const copy = element.cloneNode(true);
                        copy.querySelectorAll('.sr').forEach(node => node.remove());
                        return copy.textContent;
                    }''')
                    assert '장부에 있음' not in visible_text
                    assert '복사 제외' not in visible_text
                    assert '대조 후보' not in visible_text
                    dates = scope.locator('.d' if width < 760 else '.c-date')
                    assert dates.count() == len(rows)
                    assert all(date.inner_text() == '2026-10-01' for date in dates.all())
                    # The same transaction stays the same height regardless of its
                    # internal copy status; no extra status column or mobile line.
                    selector = '.li' if width < 760 else 'tr[data-id]'
                    heights = scope.locator(selector).evaluate_all(
                        'rows => rows.map(row => row.getBoundingClientRect().height)')
                    assert max(heights) - min(heights) < 1
                    assert page.get_by_role('button', name='지출내용 복사').is_enabled()
        finally:
            browser.close()
    assert rows == before


def test_copy_card_sync_uses_own_csrf_and_status_and_recheck_keeps_filters(copy_state):
    from playwright.sync_api import sync_playwright
    rows, preview = copy_state
    preview.update(source_available=False, source_info={'reason': 'SOURCE_EXPENSE_TOTAL_MISMATCH'})
    markup = ("<div class='income-sync'><span data-google-sync-status>수입 안내</span></div>"
              "<input name='csrf' value='stale-token'>" + design._trip_copy_html('trip-synthetic', rows, preview))
    document = design.render("<main id='main'>" + markup + '</main>')
    calls = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 320, 'height': 850})
            page.route('http://synthetic.test/board**', lambda route: route.fulfill(
                content_type='text/html', body=document))
            def sync(route):
                calls.append(route.request.headers.get('x-csrf-token'))
                route.fulfill(status=503, json={'code': 'UNAVAILABLE'})
            page.route('http://synthetic.test/api/google-ledger/sync', sync)
            url = 'http://synthetic.test/board?tab=trip-synthetic&q=Cafe&kind=ex'
            page.goto(url)
            page.get_by_role('button', name='장부 동기화').click()
            page.wait_for_function("document.getElementById('copy-status').textContent.includes('동기화를 시작하지 못했습니다')")
            assert calls == [board.CSRF_TOKEN]
            assert page.locator('.income-sync [data-google-sync-status]').inner_text() == '수입 안내'
            assert page.get_by_role('button', name='장부 동기화').is_enabled()
            assert page.get_by_role('button', name='지출내용 복사').is_disabled()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            for control in page.locator('.trip-copy-box .btn:visible').all():
                assert control.bounding_box()['height'] >= 44
            with page.expect_navigation():
                page.get_by_role('button', name='다시 확인').click()
            assert page.url == url
        finally:
            browser.close()


def test_copy_evidence_is_escaped_and_available_in_collapsed_detail(copy_state, monkeypatch):
    rows, preview = copy_state
    preview['results'][3]['basis'] = ['<img src=x onerror=alert(1)>']
    monkeypatch.setattr(design, '_selected_rows', lambda tab: ([], rows, [], rows))
    monkeypatch.setattr(design, '_expense_copy_preview', lambda tab, costs: preview)
    detail = design._google_match_detail(rows[3])
    assert "<details class='p-src google-match-detail'>" in detail
    assert '<summary>Google 장부 대조 근거</summary>' in detail
    assert '중복 확인 필요 · 복사 제외' in detail
    assert '<details open' not in detail
    assert '<img' not in detail
    # Candidate evidence is also escaped, without changing the copy outcome.
    preview['sheet_rows'] = [{'amount_krw': 1000, 'date': '2026-10-01'}]
    detail = design._google_match_detail(rows[3])
    assert 'Google 장부 대조 후보: 복수 후보' in detail
    assert '같은 거래로 확정된 것은 아닙니다' in detail
    assert preview['results'][3]['status'] == 'REVIEW_CONFLICT'
    monkeypatch.setattr(board, 'current_role', lambda: 'viewer')
    assert design._google_match_detail(rows[3]) == ''


def test_unavailable_source_does_not_add_detail_or_user_task(copy_state, monkeypatch):
    rows, preview = copy_state
    preview['source_available'] = False
    monkeypatch.setattr(design, '_selected_rows', lambda tab: ([], rows, [], rows))
    monkeypatch.setattr(design, '_expense_copy_preview', lambda tab, costs: preview)
    assert design._google_match_detail(rows[0]) == ''
