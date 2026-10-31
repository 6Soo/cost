"""Embedded masked evidence never registers identities or crosses trip scope."""
import copy
import pytest
from webapp import insurance_income_match_service as service, participant_trip_panel as panel
from webapp.tests.test_insurance_income_match_service import inputs


def state():
    return {'trip_id': 'trip-a', 'configured': False, 'participants': [], 'roster': {},
            'google': {'available': True, 'generation': 'one', 'key': 'sheet'},
            'income_rows': [{'ref': 'income-1', 'fingerprint': 'fp', 'name': '가나다',
                             'nickname': '', 'amount': 1000, 'cells': {'B': '2026-10-01'}}]}


def test_same_generation_masked_evidence_works_without_participant_db():
    review, trips, _ = inputs()
    value = state()
    before = copy.deepcopy((review, trips, value))
    result = service.trip_review(value, review=review, trips=trips)
    assert result['available'] and result['counts']['matched'] == 1
    markup = panel.render(dict(value, insurance_review=result))
    assert "id='participant-trip-panel'" in markup
    assert '글자 일치 · 가*다' in markup and "data-income-ref='income-1'" in markup
    assert '/api/participants/link' not in markup and 'draggable' not in markup
    assert '참가자 확정·입금 수령을 확인한 결과는 아닙니다' in markup
    assert (review, trips, value) == before


def test_embedded_scope_excludes_unrelated_periods_and_other_explicit_mapping():
    review, trips, _ = inputs()
    value = state()
    review['contracts'][0]['cost_trip_id'] = 'trip-b'
    assert service.trip_review(value, review=review, trips=trips)['counts']['contracts'] == 0
    review['contracts'][0]['cost_trip_id'] = None
    value['trip_id'] = 'trip-b'
    assert service.trip_review(value, review=review, trips=trips)['counts']['contracts'] == 0
    review['contracts'][0]['cost_trip_id'] = 'trip-b'
    assert service.trip_review(value, review=review, trips=trips)['counts']['contracts'] == 1


def test_stale_source_and_unknown_trip_never_become_uninsured_or_matched():
    review, trips, _ = inputs()
    value = state()
    value['google']['stale'] = True
    result = service.trip_review(value, review=review, trips=trips)
    assert result['counts']['source_unavailable'] == 1
    assert result['counts']['matched'] == 0
    markup = panel.render(dict(value, insurance_review=result))
    assert '보험·수입 자료 확인 필요' in markup
    assert '글자 일치 없음' not in markup
    value['trip_id'] = 'not-an-actual-trip'
    assert service.trip_review(value, review=review, trips=trips)['available'] is False
    value = state()
    value['google']['generation'] = None
    assert service.trip_review(value, review=review, trips=trips)['counts']['source_unavailable'] == 1


def test_duplicate_contract_candidates_are_not_a_single_identity_and_masks_are_escaped():
    review, trips, _ = inputs()
    review['contracts'].append(copy.deepcopy(review['contracts'][0]))
    value = state()
    result = service.trip_review(value, review=review, trips=trips)
    markup = panel.render(dict(value, insurance_review=result))
    assert '보험 명단 후보 2건' in markup and '글자 일치 ·' not in markup
    result['contracts'] = result['contracts'][:1]
    result['contracts'][0]['rows'][0]['masked_name'] = '<img onerror=alert(1)>'
    markup = panel.render(dict(value, insurance_review=result))
    assert '<img onerror' not in markup and '&lt;img' in markup


def test_automatic_review_is_only_for_missing_confirmed_store(monkeypatch, tmp_path):
    from webapp import participant_income_page
    path = tmp_path / 'missing.sqlite'
    monkeypatch.setattr(participant_income_page, 'store_path', lambda: path)
    monkeypatch.setenv('WEBLEDGER_INSURANCE_REVIEW_MANIFEST', 'synthetic-config')
    assert "data-auto-load='1'" in panel.shell(trip_id='trip-a')
    assert not path.exists()
    path.touch()
    assert "data-auto-load='0'" in panel.shell(trip_id='trip-a')


def test_confirmed_manual_links_are_not_replaced_by_masked_candidates():
    from webapp.tests.test_participant_trip_panel import sample_state
    value = sample_state(1)
    ref = value['income_rows'][0]['ref']
    value['participants'] = [{'participant_id': 'confirmed', 'display_name': 'manual person',
                              'links': [{'income_ref': ref, 'method': 'manual'}]}]
    value['insurance_review'] = {'available': True, 'counts': {'rows': 1, 'matched': 1},
        'contracts': [{'rows': [{'masked_name': 'do-not-override', 'match_state': 'matched',
                                 'matches': [{'ref': ref}]}]}]}
    markup = panel.render(value)
    assert 'manual person' in markup and 'do-not-override' not in markup
    assert markup.count('participant-income-status') == 1


def test_income_status_page_uses_the_same_date_order_as_the_visible_income_table():
    from webapp.tests.test_participant_trip_panel import sample_state
    value = sample_state(25)
    for i, row in enumerate(value['income_rows']):
        row['cells']['B'] = f'2026-10-{25-i:02d}'
    before = copy.deepcopy(value)
    result = panel.project(value)
    assert [r['row'] for r in result['rows']] == list(range(30,10,-1))
    assert [r['row'] for r in panel.project(value, income_offset=20)['rows']] == list(range(10,5,-1))
    assert value == before


def test_capped_candidate_list_does_not_claim_unlisted_rows_have_no_match():
    value = state()
    value['insurance_review'] = {'available': True, 'counts': {'contracts':1,'rows':1},
        'contracts': [{'rows': [{'match_state':'ambiguous','matches':[], 'candidate_count':21}]}]}
    markup = panel.render(value)
    assert '후보 목록 확인 필요' in markup and '글자 일치 없음' not in markup


@pytest.mark.parametrize('generation', ['one', 'changed'])
def test_browser_missing_store_auto_load_updates_cells_without_error_or_write(monkeypatch, tmp_path, generation):
    from playwright.sync_api import sync_playwright
    from webapp import ledger_design_assets, participant_income_page
    monkeypatch.setattr(participant_income_page, 'store_path', lambda: tmp_path / 'missing.sqlite')
    monkeypatch.setenv('WEBLEDGER_INSURANCE_REVIEW_MANIFEST', 'synthetic-config')
    review, trips, _ = inputs()
    value = state()
    value['google']['generation'] = generation
    result = service.trip_review(value, review=review, trips=trips)
    response = panel.render(dict(value, insurance_review=result))
    document = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<style>' + ledger_design_assets.STYLE + '</style><body><main id="main">'
                '<a href="#participant-trip-panel">보험 명단</a>'
                '<table id="income-tbl" data-google-generation="one"><tr><td class="participant-insurance-cell" data-income-ref="income-1">'
                '보험 명단 확인<button class="participant-row-connect">대조</button></td></tr></table>'
                + panel.shell(trip_id='trip-a') + '</main><script>' + ledger_design_assets.SCRIPT + '</script></body>')
    calls = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            def route(request):
                calls.append((request.request.method, request.request.url))
                request.fulfill(status=200, content_type='text/html',
                                body=response if '/api/participants/trip-panel?' in request.request.url else document)
            page.route('http://synthetic.test/**', route)
            page.goto('http://synthetic.test/')
            expected = '글자 일치 · 가*다' if generation == 'one' else '자료 변경 · 새로고침 필요'
            page.wait_for_function('(value)=>document.querySelector(".participant-insurance-cell").textContent===value', arg=expected)
            assert page.locator('.participant-insurance-cell').inner_text() == expected
            assert page.locator('.participant-row-connect').count() == 0
            for width in (320,390,900):
                page.set_viewport_size({'width':width,'height':900})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.locator('a[href="#participant-trip-panel"]').click()
            assert page.locator('#participant-trip-panel').get_attribute('open') is not None
            assert '불러오지 못했습니다' not in page.locator('#participant-trip-panel').inner_text()
            assert page.locator('form').count() == 0
            assert len([url for method, url in calls if '/trip-panel?' in url]) == 1
            assert all(method == 'GET' for method, _ in calls)
            assert not (tmp_path / 'missing.sqlite').exists()
        finally:
            browser.close()
