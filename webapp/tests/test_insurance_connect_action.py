"""Income connection action is available without changing source or saved links."""
from copy import deepcopy
from html.parser import HTMLParser
import pytest
from webapp import participant_trip_panel as panel,google_ledger_page as google
from webapp.tests.test_participant_trip_panel import sample_state


class Templates(HTMLParser):
    def __init__(self):
        super().__init__();self.ref=None;self.data={}
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='template' and 'data-income-ref' in attrs:
            self.ref=attrs['data-income-ref'];self.data[self.ref]=[]
        elif self.ref:self.data[self.ref].append((tag,attrs))
    def handle_endtag(self,tag):
        if tag=='template':self.ref=None


@pytest.mark.parametrize('available',[True,False])
def test_unlinked_action_is_only_offered_for_current_income(available):
    state=sample_state(2);state['google']['available']=available
    state['income_rows'][1]['amount']=0
    before=deepcopy(state);view=Templates();view.feed(panel.render(state))
    ref=state['income_rows'][0]['ref'];refund=state['income_rows'][1]['ref']
    assert any('data-connect-income' in attrs for tag,attrs in view.data[ref])==available
    assert not any('data-connect-income' in attrs for tag,attrs in view.data[refund])
    assert state==before


def test_linked_status_keeps_names_and_existing_unlink_protection_without_connect_action():
    state=sample_state(1);ref=state['income_rows'][0]['ref']
    state['participants']=[{'participant_id':'person-0','display_name':'합*성',
                            'links':[{'income_ref':ref,'method':'manual'}]}]
    before=deepcopy(state);body=panel.render(state,csrf='synthetic-csrf')
    assert '<summary><span>1명 연결 · 합*성</span></summary>' in body
    assert 'data-connect-income' not in body
    assert "action='/api/participants/unlink'" in body
    assert "value='synthetic-csrf'" in body and "value='synthetic-fingerprint'" in body
    assert state==before


def test_no_selectable_roster_keeps_action_and_explains_missing_form_without_inventing_people():
    state=sample_state(1);state['roster']['participants']=[]
    body=panel.render(state)
    assert 'data-connect-income' in body
    assert 'participant-connect-notice' in body
    assert "class='participant-keyboard-link'" not in body
    assert '/participants/insurance-match' not in body


def test_initial_income_cell_uses_same_action_and_refund_stays_status_only():
    assert 'data-connect-income' in google._participant_insurance_cell({'amount':1000},{})
    assert google._participant_insurance_cell({'amount':0},{})=='환불완료'


def test_ambiguous_confirmed_masked_people_explain_why_auto_connection_is_blocked():
    from app import participant_income as pi
    state = sample_state(1)
    row = state['income_rows'][0]
    row.update(name='김가람', fingerprint='synthetic-row', amount_state='amounted')
    people = [dict(state['roster']['participants'][0], participant_id=f'p-{i}',
                   display_name='김*람') for i in range(2)]
    result = pi.reconcile(trip_id=state['trip_id'], participants=people,
                          income_rows=[row], index_available=True)
    state.update(participants=result['participants'], unlinked_income=result['unlinked_income'])
    state['roster']['participants'] = people
    state['insurance_review'] = {'available': True, 'counts': {'contracts': 1},
        'contracts': [{'rows': [{'masked_name': '김*람', 'match_state': 'matched',
                                 'matches': [{'ref': row['ref']}]}]}]}
    before = deepcopy(state)
    body = panel.render(state)
    assert '이름 일치 후보 2명 · 자동 연결 불가' in body
    assert 'data-connect-income' in body
    assert not any(p['links'] for p in result['participants'])
    assert state == before


def test_inline_connection_toggles_and_name_submits_only_its_own_income():
    from playwright.sync_api import sync_playwright
    from webapp import ledger_design_assets
    state = sample_state(2)
    markup = panel.render(state, csrf='synthetic-csrf')
    rows = ''.join(f"<tr><td>합성</td><td class='participant-insurance-cell' data-income-ref='{row['ref']}'>{panel.connect_button()}</td></tr>" for row in state['income_rows'])
    document = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>' + ledger_design_assets.STYLE + '</style><main id="main">'
        '<section id="google-trip-income"><table id="income-tbl">'+rows+'</table></section>'
        + panel.shell(trip_id=state['trip_id']) + '</main><script>' + ledger_design_assets.SCRIPT + '</script>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            writes = []
            def serve(route):
                if route.request.method == 'POST':
                    writes.append(route.request.post_data)
                    route.fulfill(status=409, content_type='application/json', body='{"code":"STALE_INPUT"}')
                else:
                    route.fulfill(status=200, content_type='text/html',
                                  body=markup if '/trip-panel?' in route.request.url else document)
            page.route('http://synthetic.test/**', serve)
            page.goto('http://synthetic.test/')
            # Lazy loading from the row must keep the separate panel closed.
            page.locator('[data-connect-income]').first.click()
            inline = page.locator('.insurance-candidate-row')
            inline.locator('[data-pick-participant]').first.wait_for()
            assert not page.locator('#participant-trip-panel').evaluate('(node)=>node.open')
            assert inline.locator('td').get_attribute('colspan') == '2'
            assert inline.locator('button[type=submit]').first.bounding_box()['height'] >= 44
            assert inline.locator('select').count() == 0
            assert inline.locator('[name=income_ref]').input_value() == state['income_rows'][0]['ref']
            page.locator('[data-connect-income]').nth(1).click()
            assert inline.count() == 2
            assert len(set(inline.evaluate_all('(rows)=>rows.map(row=>row.id)'))) == 2
            inline.nth(1).locator('[data-pick-participant]').first.press('Escape')
            assert inline.count() == 1
            assert page.locator('[data-connect-income]').nth(1).evaluate('(node)=>node===document.activeElement')
            assert writes == []
            inline.locator('[data-pick-participant="person-0"]').click()
            page.wait_for_function("document.querySelector('.participant-inline-status').textContent.includes('자료가 변경')")
            from urllib.parse import parse_qs
            saved = parse_qs(writes[0])
            assert len(writes) == 1 and page.locator('dialog[open]').count() == 0
            assert saved['income_ref'] == [state['income_rows'][0]['ref']]
            assert saved['csrf'] == ['synthetic-csrf']
            assert saved['input_fingerprint'] == ['synthetic-fingerprint']
            assert saved['participant_id'] == ['person-0']
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.locator('[data-connect-income]').first.click()
            assert inline.count() == 0
        finally:
            browser.close()
