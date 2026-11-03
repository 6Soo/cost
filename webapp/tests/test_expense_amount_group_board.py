from copy import deepcopy

from playwright.sync_api import sync_playwright

from app.expense_amount_groups import reconcile_expense_amount_groups
from webapp import ledger_board as board, ledger_design as design


def fixture_state():
    costs = [{'row_id': f'cost-{i}', 'trip_id': 'trip-synthetic',
              'display_tab_id': 'trip-synthetic', 'amount_krw': 50000,
              'currency': 'KRW', 'occurred_on': '2026-10-01', 'description': '합성 지출'}
             for i in range(3)]
    google = [{'ref': f'google-{i}', 'trip_id': 'trip-synthetic',
               'amount_krw': 50000, 'currency': 'KRW'} for i in range(3)]
    return costs, reconcile_expense_amount_groups('trip-synthetic', costs, google)


def test_full_trip_group_counts_are_stable_in_search_and_live_fragments(monkeypatch):
    costs, state = fixture_state()
    before = deepcopy(costs)
    received = []
    monkeypatch.setattr(design, '_STORE_missing', lambda: False)
    monkeypatch.setattr(design, '_selected_rows', lambda *a: ([], costs[:1], [], costs))
    monkeypatch.setattr(design, '_google_match_annotations', lambda *a: {})
    monkeypatch.setattr(design, '_trip_copy_html', lambda *a: '<p>original-copy-controls</p>')
    monkeypatch.setattr(design, '_is_trip_tab', lambda *a: True)
    monkeypatch.setattr(board, 'current_role', lambda: 'owner')
    monkeypatch.setattr(board, '_active_store', lambda: object())
    monkeypatch.setattr(board, 'live_trips', lambda **kwargs: [])
    from webapp import expense_amount_group_service as service
    monkeypatch.setattr(service, 'build_state', lambda *a, **kw: received.append(kw['cost_rows']) or state)
    for renderer in (design.rows_region, design.rows_part):
        html = renderer('trip-synthetic', query='합성')
        assert '3/3' in html and '9개 관계' in html
        assert html.count('original-copy-controls') == 1
        assert "data-id='cost-1'" not in html
    assert received == [costs, costs]
    assert costs == before


def test_non_owner_and_non_trip_do_not_load_private_groups(monkeypatch):
    from webapp import expense_amount_group_service as service
    monkeypatch.setattr(service, 'build_state', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('private read')))
    monkeypatch.setattr(board, 'current_role', lambda: 'viewer')
    assert design._amount_group_state('trip-synthetic', []) is None
    monkeypatch.setattr(board, 'current_role', lambda: 'owner')
    monkeypatch.setattr(design, '_is_trip_tab', lambda *a: False)
    for trip in ('refunds', 'unclassified', 'quarter:2026:Q4'):
        assert design._amount_group_state(trip, []) is None


def test_board_status_opens_its_group_without_opening_transaction_panel():
    costs, state = fixture_state()
    html = design._tables_html([], costs, selected='', unclassified=False, amount_groups=state)
    document = design.render("<main id='main'>" + html + "<div id='panel-slot'></div></main>")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            calls = []
            page.on('request', lambda request: calls.append(request.url))
            page.set_content(document)
            button = page.locator('[data-gemn-group]').first
            assert page.locator('.gemn-summary').count() == 0
            assert page.locator('.gemn-dialog').is_hidden()
            button.click()
            target = button.get_attribute('data-gemn-group')
            assert page.locator('#' + target).get_attribute('open') is not None
            assert not any('/api/rows' in url or '/api/row/' in url for url in calls)
            assert page.locator('#' + target + ' li').count() == 6
            assert page.locator('.gemn-dialog').is_visible()
            page.set_viewport_size({'width': 899, 'height': 900})
            page.wait_for_function('!document.querySelector(".gemn-dialog").matches(":modal")')
            assert not page.locator('.gemn-dialog').evaluate('e => e.matches(":modal")')
            page.set_viewport_size({'width': 1280, 'height': 900})
            button.click()
            page.locator('[data-gemn-close]').click()
            assert page.locator('.gemn-dialog').is_hidden()
            for width in (899, 900, 1280):
                page.set_viewport_size({'width': width, 'height': 900})
                assert button.is_visible() == (width >= 900)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('col.gemn-column').evaluate('e => getComputedStyle(e).display') == 'table-column'
        finally:
            browser.close()


def test_google_row_order_groups_matches_first_without_mutation():
    from webapp.expense_amount_group_service import sort_for_display
    costs = [{'row_id': key, 'trip_id': 't', 'amount_krw': amount, 'currency': 'KRW', 'occurred_on': '2026-10-01'}
             for key, amount in [('missing', 99), ('late', 20), ('partial-a', 30),
                                 ('early', 10), ('partial-b', 30)]]
    google = [{'ref': str(i), 'row_number': i, 'trip_id': 't', 'amount_krw': amount, 'currency': 'KRW'}
              for i, amount in [(100, 20), (8, 10), (3, 30)]]
    before = deepcopy((costs, google))
    state = reconcile_expense_amount_groups('t', costs, google)
    expected = ['early', 'late', 'partial-a', 'partial-b', 'missing']
    assert [r['row_id'] for r in sort_for_display(costs, state)] == expected
    assert [r['row_id'] for r in sort_for_display(costs[1:4], state)] == ['early', 'late', 'partial-a']
    assert sort_for_display(costs, {'available': False}) == costs
    assert (costs, google) == before
    markup = design._tables_html([], costs, selected='', unclassified=False, amount_groups=state)
    positions = [markup.index("data-id='" + key + "'") for key in expected]
    assert positions == sorted(positions)


def test_full_and_live_renderers_sort_table_but_keep_original_copy_order(monkeypatch):
    costs, _ = fixture_state()
    for i, row in enumerate(costs):
        row['amount_krw'] = (i + 1) * 100
    google = [{'ref': str(i), 'row_number': i, 'trip_id': 'trip-synthetic',
               'amount_krw': amount, 'currency': 'KRW'} for i, amount in [(5, 300), (10, 200)]]
    state = reconcile_expense_amount_groups('trip-synthetic', costs, google)
    monkeypatch.setattr(design, '_STORE_missing', lambda: False)
    monkeypatch.setattr(design, '_selected_rows', lambda *a: ([], costs, [], costs))
    monkeypatch.setattr(design, '_amount_group_state', lambda *a: state)
    monkeypatch.setattr(design, '_google_match_annotations', lambda *a: {})
    copied = []
    monkeypatch.setattr(design, '_trip_copy_html', lambda tid, rows, preview=None: copied.append([r['row_id'] for r in rows]) or '')
    for renderer in (design.rows_region, design.rows_part):
        markup = renderer('trip-synthetic')
        positions = [markup.index("data-id='cost-" + str(i) + "'") for i in (2, 1, 0)]
        assert positions == sorted(positions)
        assert "class='gemn-desktop gemn-summary'" not in markup
    assert copied == [['cost-0', 'cost-1', 'cost-2']] * 2
