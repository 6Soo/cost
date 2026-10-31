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
    assert '복사 가능 1건 · 1,000원 · 장부에 있음 2건 제외 · 확인 필요 1건 제외' in markup
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
    assert '복사 가능 0건' in markup and '장부에 있음 2건 제외' in markup
    assert ' disabled' in markup
    monkeypatch.setattr(board, 'current_role', lambda: 'viewer')
    assert design._trip_copy_html('trip-synthetic', rows, preview) == ''
    assert design._google_match_annotations('trip-synthetic', rows, preview) == {}


def test_blocked_and_company_excluded_rows_never_count_as_copyable(copy_state):
    rows, preview = copy_state
    for flag in ('blocked', 'excluded_from_company'):
        costs = deepcopy(rows)
        costs[2][flag] = True
        markup = design._trip_copy_html('trip-synthetic', costs, preview)
        assert '복사 가능 0건' in markup and ' disabled' in markup
        annotations = design._google_match_annotations('trip-synthetic', costs, preview)
        assert annotations['row-2']['label'] == '복사 제외 · 거래 상세 확인'


def test_integrated_labels_escape_source_text_and_are_visible_on_mobile(copy_state):
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
                    labels = scope.locator('.expense-copy-state')
                    assert labels.count() == 4
                    assert all(labels.nth(i).is_visible() for i in range(4))
                    assert page.get_by_role('button', name='지출내용 복사').is_enabled()
        finally:
            browser.close()
    assert rows == before
