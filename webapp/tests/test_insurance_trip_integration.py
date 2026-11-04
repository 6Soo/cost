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


def test_insurance_column_loads_automatically_for_both_received_and_review_rosters(monkeypatch, tmp_path):
    from webapp import participant_income_page
    path = tmp_path / 'missing.sqlite'
    monkeypatch.setattr(participant_income_page, 'store_path', lambda: path)
    monkeypatch.setenv('WEBLEDGER_INSURANCE_REVIEW_MANIFEST', 'synthetic-config')
    assert "data-auto-load='1'" in panel.shell(trip_id='trip-a')
    assert not path.exists()
    path.touch()
    assert "data-auto-load='1'" in panel.shell(trip_id='trip-a')


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
    assert [r['row'] for r in result['rows']] == list(range(30,5,-1))
    assert value == before


def test_candidate_rows_toggle_independently_and_keep_income_table_usable():
    from playwright.sync_api import sync_playwright
    from webapp import ledger_design_assets
    from webapp.tests.test_participant_trip_panel import sample_state
    value = sample_state(2)
    value['google']['generation'] = 'one'
    value['insurance_review'] = {'available': True, 'counts': {'contracts': 1, 'rows': 12},
        'trip_period': {'start': '2026-10-01', 'end': '2026-10-05'},
        'contracts': [{'travel_start': '2026-10-01', 'travel_end': '2026-10-05',
                       'rows': [{'masked_name': f'합성{i}*', 'matches': []} for i in range(12)]}]}
    response = panel.render(value)
    rows = ''.join(f"<tr><td class='income-date'>10월1일</td><td class='income-person'>합성{i}</td>"
                   "<td class='income-breakdown'></td><td class='income-breakdown'></td>"
                   "<td class='income-breakdown'></td><td class='income-total'>1,000원</td>"
                   f"<td class='participant-insurance-cell' data-income-ref='{row['ref']}'></td></tr>"
                   for i, row in enumerate(value['income_rows']))
    document = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<style>' + ledger_design_assets.STYLE + '</style><main id="main"><section id="google-trip-income">'
                '<table id="income-tbl" data-google-generation="one"><tbody>' + rows + '</tbody></table></section>'
                + panel.shell(trip_id='trip-a') + '</main><script>' + ledger_design_assets.SCRIPT + '</script>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            calls = []
            def serve(route):
                calls.append(route.request.method)
                route.fulfill(status=200, content_type='text/html',
                              body=response if '/trip-panel?' in route.request.url else document)
            page.route('http://synthetic.test/**', serve)
            page.goto('http://synthetic.test/')
            page.locator('#participant-trip-panel summary').first.click()
            buttons = page.locator('.insurance-candidate-button')
            buttons.nth(0).click()
            buttons.nth(1).click()
            assert page.locator('.insurance-candidate-row').count() == 2
            for row in page.locator('.insurance-candidate-row').all():
                assert row.locator('td').get_attribute('colspan') == '7'
                assert row.locator('li').count() == 12
                assert '보험 기간' not in row.inner_text() and '1,000원' not in row.inner_text()
                assert row.evaluate('(el)=>el.previousElementSibling.querySelector(".insurance-candidate-button").getAttribute("aria-controls")===el.id')
            for width in (320, 390, 759, 900, 1280):
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert page.locator('.insurance-candidate-row li:visible').count() == 24
                assert page.locator('dialog[open]').count() == 0
            buttons.nth(0).click()
            assert page.locator('.insurance-candidate-row').count() == 1
            assert buttons.nth(0).get_attribute('aria-expanded') == 'false'
            page.locator('.insurance-candidate-row a').focus()
            page.keyboard.press('Escape')
            assert page.locator('.insurance-candidate-row').count() == 0
            assert buttons.nth(1).evaluate('(el)=>el===document.activeElement')
            assert set(calls) == {'GET'}
        finally:
            browser.close()


def test_capped_candidate_list_does_not_claim_unlisted_rows_have_no_match():
    value = state()
    value['insurance_review'] = {'available': True, 'counts': {'contracts':1,'rows':1},
        'contracts': [{'rows': [{'match_state':'ambiguous','matches':[], 'candidate_count':21}]}]}
    markup = panel.render(value)
    assert '후보 목록 확인 필요' in markup and '글자 일치 없음' not in markup


def test_no_match_button_opens_roster_and_preselects_income_without_writing():
    from playwright.sync_api import sync_playwright
    from webapp import ledger_design_assets
    from webapp.tests.test_participant_trip_panel import sample_state
    value = sample_state(1)
    value['google']['generation'] = 'one'
    value['insurance_review'] = {'available': True, 'counts': {'contracts': 1, 'rows': 1},
        'contracts': [{'travel_start': '2026-10-01', 'travel_end': '2026-10-05',
                       'rows': [{'masked_name': '김*수', 'match_state': 'unmatched', 'matches': []}]}]}
    before = copy.deepcopy(value)
    response = panel.render(value, csrf='token')
    ref = value['income_rows'][0]['ref']
    document = ('<!doctype html><meta charset="utf-8"><style>' + ledger_design_assets.STYLE + '</style>'
                '<main id="main"><section id="google-trip-income"><table id="income-tbl" data-google-generation="one">'
                f'<tr><td class="participant-insurance-cell" data-income-ref="{ref}"></td></tr></table></section>'
                + panel.shell(trip_id='trip-synthetic') + '</main><script>' + ledger_design_assets.SCRIPT + '</script>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            requests = []
            def serve(route):
                requests.append(route.request.method)
                route.fulfill(status=200, content_type='text/html',
                              body=response if '/trip-panel?' in route.request.url else document)
            page.route('http://synthetic.test/**', serve)
            page.goto('http://synthetic.test/')
            page.locator('#participant-trip-panel summary').first.click()
            button = page.locator('.participant-insurance-cell .insurance-candidate-button')
            assert button.inner_text() == '이름 일치 없음'
            button.click()
            dialog = page.locator('.insurance-candidate-row')
            assert dialog.is_visible()
            assert '김*수' in dialog.inner_text()
            assert page.locator('dialog[open]').count() == 0
            assert button.get_attribute('aria-expanded') == 'true'
            assert page.locator('#income-tbl').is_visible()
            assert dialog.locator('.insurance-candidate-list li:visible').count() == 1
            assert dialog.evaluate('(row)=>row.previousElementSibling.contains(document.querySelector(".insurance-candidate-button"))')
            assert dialog.locator('td').get_attribute('colspan') == '1'
            dialog.locator('[data-insurance-connect-ref]').click()
            assert not dialog.is_visible()
            assert page.locator('.participant-keyboard-link [name=income_ref]').input_value() == ref
            assert page.locator('.participant-keyboard-link [name=participant_id]').input_value() == ''
            assert set(requests) == {'GET'}
            assert value == before
        finally:
            browser.close()


def test_connected_roster_people_are_excluded_from_candidate_lists():
    from webapp.tests.test_participant_trip_panel import sample_state
    value = sample_state(2)
    value['roster']['participants'][0]['display_name'] = '김민수'
    value['roster']['participants'][1]['display_name'] = '이영희'
    value['participants'] = [{'participant_id': 'person-0', 'display_name': '김민수',
                              'links': [{'income_ref': value['income_rows'][0]['ref'], 'method': 'manual'}]}]
    ref = value['income_rows'][1]['ref']
    value['insurance_review'] = {'available': True, 'counts': {'contracts': 1, 'rows': 2},
        'contracts': [{'rows': [
            {'masked_name': '김*수', 'match_state': 'ambiguous', 'matches': [{'ref': ref}]},
            {'masked_name': '이*희', 'match_state': 'ambiguous', 'matches': [{'ref': ref}]},
        ]}]}
    markup = panel.render(value)
    assert '김*수' not in markup
    assert '이*희' in markup and '보험 명단 후보 1건' in markup


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
            page.goto('http://synthetic.test/?participant_q=')
            expected = '글자 일치 · 가*다' if generation == 'one' else '자료 변경 · 새로고침 필요'
            page.wait_for_function('(value)=>document.querySelector(".participant-insurance-cell").textContent===value', arg=expected)
            assert page.locator('.participant-insurance-cell').inner_text() == expected
            assert page.locator('.participant-row-connect').count() == 0
            assert page.locator('#participant-trip-panel').get_attribute('open') is not None
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


def test_browser_loading_retry_and_candidate_dialog_are_actionable_and_readonly(monkeypatch, tmp_path):
    from playwright.sync_api import sync_playwright
    from webapp import ledger_design_assets, participant_income_page
    monkeypatch.setattr(participant_income_page, 'store_path', lambda: tmp_path / 'absent.sqlite')
    monkeypatch.setenv('WEBLEDGER_INSURANCE_REVIEW_MANIFEST', 'synthetic')
    review, trips, _ = inputs()
    review['contracts'].append(copy.deepcopy(review['contracts'][0]))
    value = state()
    response = panel.render(dict(value, insurance_review=service.trip_review(value, review=review, trips=trips)))
    document = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<style>' + ledger_design_assets.STYLE + '</style><main id="main">'
                '<table id="income-tbl" data-google-generation="one"><tr><td class="participant-insurance-cell" data-income-ref="income-1"></td></tr></table>'
                + panel.shell(trip_id='trip-a') + '</main><script>' + ledger_design_assets.SCRIPT + '</script>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width':390,'height':844})
            requests, held = [], []
            def serve(route):
                requests.append(route.request.method)
                if '/trip-panel?' in route.request.url:
                    held.append(route)
                else:
                    route.fulfill(status=200,content_type='text/html',body=document)
            page.route('http://synthetic.test/**',serve)
            page.goto('http://synthetic.test/')
            page.wait_for_function('document.querySelector("#participant-trip-panel").getAttribute("aria-busy")==="true"')
            assert page.locator('.participant-insurance-cell').inner_text() == '보험 명단 대조 중…'
            page.wait_for_timeout(100)
            held[0].fulfill(status=503,body='unavailable')
            assert page.locator('.participant-insurance-cell button').count() == 0
            page.locator('#participant-trip-panel .participant-review-retry').click()
            page.wait_for_timeout(100)
            assert len(held) == 2
            held[1].fulfill(status=200,content_type='text/html',body=response)
            button=page.locator('.insurance-candidate-button')
            button.click()
            dialog=page.locator('.insurance-candidate-row')
            assert dialog.is_visible() and dialog.locator('.insurance-candidate-list li').count()==2
            assert '가*다' in dialog.inner_text() and '1,000원' not in dialog.inner_text()
            assert dialog.locator('.insurance-selected-income').count() == 0
            assert dialog.locator('a').get_attribute('href').endswith('trip=trip-a')
            assert page.locator('#participant-trip-panel').get_attribute('aria-busy')=='false'
            for width in (320,390,1280):
                page.set_viewport_size({'width':width,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.keyboard.press('Escape')
            assert not dialog.is_visible()
            assert button.evaluate('(el)=>document.activeElement===el')
            assert page.locator('form').count()==0 and set(requests)=={'GET'}
            assert not (tmp_path/'absent.sqlite').exists()
        finally:
            browser.close()


@pytest.mark.parametrize('same_period', [True, False])
def test_candidate_period_is_grouped_and_only_shown_when_different(same_period):
    value = state()
    value['insurance_review'] = {'available': True, 'counts': {'contracts': 1, 'rows': 2},
        'trip_period': {'start': '2026-10-01', 'end': '2026-10-05' if same_period else '2026-10-06'},
        'contracts': [{'travel_start': '2026-10-01', 'travel_end': '2026-10-05',
                       'rows': [{'masked_name': name, 'matches': []} for name in ('김*수', '이*희')]}]}
    before = copy.deepcopy(value)
    roster = panel.render(value).split("id='insurance-roster-candidates'>", 1)[1].split('</template>', 1)[0]
    assert roster.count('<li>') == 2
    assert roster.count("class='insurance-period-difference'") == (0 if same_period else 1)
    assert value == before
