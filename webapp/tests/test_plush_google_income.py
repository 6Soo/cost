from webapp.tests.test_plush_api import bound_store, call
from webapp.tests.test_trip_google_income import income_context


def test_google_income_appears_without_creating_board_rows(bound_store, income_context, monkeypatch):
    from webapp import google_ledger_page as page
    store, _ = bound_store
    _, key = income_context
    monkeypatch.setattr(page, 'load_mapping', lambda *args: {key: 'trip-demo-a'})
    existing_income = store.tab_totals('trip-demo-a')['income']
    before = store.conn.total_changes
    status, result = call('/api/plush/ledger?tab=trip-demo-a&kind=income', 'syn-owner', store)
    assert status == 200
    google = [r for r in result['rows'] if r['id'].startswith('google-income|')]
    assert len(google) == 1
    assert google[0]['merchant'] == 'INCOME-NAME'
    assert google[0]['amount'] == '1000'
    assert google[0]['read_only'] is True
    # GGL-003 (보호): 내부 COST 수입과 Google 수입을 합산하지 않는다. The trip
    # summary's income is the COST figure the legacy KPI shows; the verified
    # Google block is separate evidence, reported through income_source.
    assert result['trip']['income'] == str(existing_income), result['trip']
    assert result['income_source']['available'] is True
    assert store.conn.total_changes == before
    status, detail = call('/api/plush/row?id='+google[0]['id'], 'syn-owner', store)
    assert status == 200 and detail['read_only'] is True and detail['actions'] == []


def test_ambiguous_google_mapping_never_exposes_source_rows(bound_store, income_context, monkeypatch):
    from webapp import google_ledger_page as page
    store, _ = bound_store
    _, key = income_context
    monkeypatch.setattr(page, 'load_mapping', lambda *args: {key: 'trip-demo-a', 'other': 'trip-demo-a'})
    _, result = call('/api/plush/ledger?tab=trip-demo-a&kind=income', 'syn-owner', store)
    assert not any(r['id'].startswith('google-income|') for r in result['rows'])
    assert result['income_source']['available'] is False


def test_missing_total_stays_unknown_and_summary_is_provisional(bound_store, income_context, monkeypatch):
    from webapp import google_ledger_page as page
    store, _ = bound_store
    _, key = income_context
    monkeypatch.setattr(page, 'load_mapping', lambda *args: {key: 'trip-demo-a'})
    monkeypatch.setattr(page, 'owner_rows', lambda *args: {'income': [
        dict(row=18, date='2026-10-01', name='SYNTHETIC', amount='', deposit=200000)], 'expense': []})
    _, result = call('/api/plush/ledger?tab=trip-demo-a&kind=income', 'syn-owner', store)
    google = [r for r in result['rows'] if r['id'].startswith('google-income|')]
    assert google[0]['amount'] == '미확인'
    assert '200000원' in google[0]['description']
    assert result['income_source']['verified'] is False
    _, bootstrap = call('/api/plush/bootstrap', 'syn-owner', store)
    trip = next(t for t in bootstrap['trips'] if t['id'] == 'trip-demo-a')
    assert trip['income_source']['verified'] is False


def test_viewer_needs_google_grant_before_private_load(bound_store, income_context, monkeypatch):
    from webapp import access_control, google_ledger_page as page
    store, access = bound_store
    _, key = income_context
    access.create_account(user_id='syn-viewer', role=access_control.ROLE_VIEWER)
    monkeypatch.setattr(access, 'visible_tabs', lambda user_id, **kwargs: {'trip-demo-a'})
    monkeypatch.setattr(page, 'load_mapping', lambda *args: {key: 'trip-demo-a'})
    def forbidden(*args):
        raise AssertionError('private rows loaded without Google grant')
    monkeypatch.setattr(page, '_load_consistent_measured', forbidden)
    status, result = call('/api/plush/ledger?tab=trip-demo-a&kind=income', 'syn-viewer', store)
    assert status == 200 and result['income_source']['reason'] == 'FORBIDDEN'
    assert not any(r['id'].startswith('google-income|') for r in result['rows'])
    status, _ = call('/api/plush/row?id=google-income|trip-demo-a|main|6', 'syn-viewer', store)
    assert status == 404


def test_authorized_viewer_reads_only_granted_google_rows(bound_store, income_context, monkeypatch):
    from webapp import access_control, google_ledger_page as page
    store, access = bound_store
    _, key = income_context
    access.create_account(user_id='syn-viewer', role=access_control.ROLE_VIEWER)
    monkeypatch.setattr(access, 'visible_tabs', lambda user_id, **kwargs: {'trip-demo-a'})
    monkeypatch.setattr(page, 'load_mapping', lambda *args: {key: 'trip-demo-a'})
    monkeypatch.setattr(page, 'load_grants', lambda *args: {'grants': {'syn-viewer': [key]}})
    _, result = call('/api/plush/ledger?tab=trip-demo-a&kind=income', 'syn-viewer', store)
    google = next(r for r in result['rows'] if r['id'].startswith('google-income|'))
    _, detail = call('/api/plush/row?id='+google['id'], 'syn-viewer', store)
    assert detail['read_only'] and detail['source'] is None and detail['history'] == []


def test_real_sheet_parser_preserves_blank_income_total_in_private_index(bound_store, income_context, monkeypatch):
    import openpyxl
    from app import google_authority as ga
    from tests.card_pipeline.test_google_authority import rev_sheet
    from webapp import google_ledger_page as page
    store, _ = bound_store
    _, key = income_context
    wb = openpyxl.Workbook()
    ws = rev_sheet(wb, key, [None, 1000], [30])
    ws['B6'], ws['C6'], ws['E6'] = None, 'SYNTHETIC BLANK TOTAL', 200000
    cached = rev_sheet(openpyxl.Workbook(), key, [None, 1000], [30])
    cached['B6'], cached['C6'], cached['E6'] = None, 'SYNTHETIC BLANK TOTAL', 200000
    # Real data_only workbooks expose no formula text as a participant name.
    cached['C9'] = None
    parsed = ga.parse_trip_sheet(ws, cached)
    assert len(parsed['rows']['income']) == 1
    assert parsed['name_index']['income'][0]['amount_state'] == 'blank'
    parsed['name_index']['income'].append(dict(row=28, cells={'B': '총 금액 (A)', 'C': 1000},
        name='1000', nickname='', amount=None, amount_state='blank'))
    sources = {'main': {'trips': {key: parsed['rows']}, 'income_names': {key: parsed['name_index']}}}
    monkeypatch.setattr(page.google_authority, 'load_consistent', lambda *args: (income_context[0], sources))
    monkeypatch.setattr(page, 'load_mapping', lambda *args: {key: 'trip-demo-a'})
    _, result = call('/api/plush/ledger?tab=trip-demo-a&kind=income', 'syn-owner', store)
    google = [r for r in result['rows'] if r['id'].startswith('google-income|')]
    assert len(google) == 2
    missing = next(r for r in google if r['merchant'] == 'SYNTHETIC BLANK TOTAL')
    assert missing['amount'] == '미확인' and '200000원' in missing['description']
    assert result['income_source']['total'] == '1000' and result['income_source']['verified'] is False


def test_cost_income_and_google_are_never_summed_in_the_trip_summary(bound_store):
    """GGL-003: the summary income is COST alone; Google rides in income_source."""
    from webapp import plush_projection

    rows = [
        {"row_id": "cost-1", "row_kind": "income", "display_amount_krw": 1000000},
        {"row_id": "google-income|t|main|9", "row_kind": "income",
         "google_income": True, "display_amount_krw": 1000},
    ]
    verified = plush_projection.trip_summary(dict(tab_id="t", google_verified=True), rows)
    assert verified["income"] == "1000000", verified
    # the Google figure is nowhere in the summary figures
    assert verified["profit"] == "1000000", verified

    unverified = plush_projection.trip_summary(dict(tab_id="t", google_verified=False), rows)
    assert unverified["income"] == "1000000", unverified


def test_a_verified_google_block_stands_in_only_when_there_is_no_cost_income():
    """GGL-003·GGL-014: verified Google substitutes for an absent COST figure.

    The legacy KPI does exactly this (``_trip_kpi_html``): a verified block is
    used when the tab has no recorded income. It is used *instead of* COST, never
    added to it.
    """
    from webapp import plush_projection

    google_only = [{"row_id": "google-income|t|main|9", "row_kind": "income",
                    "google_income": True, "display_amount_krw": 1000}]
    summary = plush_projection.trip_summary(dict(tab_id="t", google_verified=True),
                                            google_only)
    assert summary["income"] == "1000", summary


def test_an_unverified_google_block_never_becomes_a_confirmed_income():
    """GGL-014: unverified Google is not a confirmed 수입 or 차액; it is unknown."""
    from webapp import plush_projection

    google_only = [{"row_id": "google-income|t|main|9", "row_kind": "income",
                    "google_income": True, "display_amount_krw": 1000}]
    summary = plush_projection.trip_summary(dict(tab_id="t", google_verified=False),
                                            google_only)
    assert summary["income"] == "미확인", summary
    assert summary["profit"] == "미확인", summary


def test_a_google_row_with_no_amount_keeps_the_verified_figure_unknown():
    """GGL-014 / §11.2.1 계약 4: 미확인은 0원이 아니다."""
    from webapp import plush_projection

    google_only = [{"row_id": "google-income|t|main|9", "row_kind": "income",
                    "google_income": True, "amount_missing": True, "amount_krw": None}]
    summary = plush_projection.trip_summary(dict(tab_id="t", google_verified=True),
                                            google_only)
    assert summary["income"] == "미확인", summary
