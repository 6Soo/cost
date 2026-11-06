"""Name actions in the trip ledger replace the standalone comparison page."""
import copy
import pytest
from playwright.sync_api import sync_playwright
from webapp import ledger_design_assets, participant_trip_panel as panel
from webapp.tests.test_participant_trip_panel import sample_state


@pytest.mark.parametrize('matched', [False, True])
@pytest.mark.parametrize('ambiguous', [False, True])
def test_name_selects_its_income_and_only_unique_confirmed_person_without_saving(matched, ambiguous):
    value = sample_state(2)
    value['google']['generation'] = 'one'
    value['roster']['participants'][0]['display_name'] = '김민수'
    if ambiguous:
        value['roster']['participants'][1]['display_name'] = '김철수'
    value['insurance_review'] = {'available': True, 'counts': {'contracts': 1, 'rows': 1},
        'contracts': [{'rows': [{'masked_name': '김*수', 'match_state': 'matched' if matched else 'unmatched',
                                'matches': [{'ref': value['income_rows'][1]['ref']}] if matched else []}]}]}
    before = copy.deepcopy(value)
    response = panel.render(value, csrf='synthetic-csrf')
    rows = ''.join(f"<tr><td>합성</td><td class='participant-insurance-cell' data-income-ref='{row['ref']}'></td></tr>" for row in value['income_rows'])
    document = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<style>' + ledger_design_assets.STYLE + '</style><main id="main"><section id="google-trip-income">'
                '<table id="income-tbl" data-google-generation="one"><tbody>' + rows + '</tbody></table></section>'
                + panel.shell(trip_id='trip-synthetic') + '</main><script>' + ledger_design_assets.SCRIPT + '</script>')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 900})
            requests = []
            def serve(route):
                requests.append(route.request.method)
                route.fulfill(content_type='text/html', body=response if '/trip-panel?' in route.request.url else document)
            page.route('http://synthetic.test/**', serve)
            page.goto('http://synthetic.test/')
            page.locator('#participant-trip-panel summary').click()
            page.locator('.participant-insurance-cell .insurance-candidate-button').nth(1).click()
            candidate = page.locator('.insurance-candidate-row')
            assert candidate.locator('footer,a').count() == 0
            name = candidate.locator('.insurance-participant-name')
            assert name.inner_text() == '김*수'
            name.focus()
            page.keyboard.press('Enter')
            assert page.locator('.insurance-candidate-row').count() == 0
            form = page.locator('.participant-keyboard-link')
            assert form.locator('[name=income_ref]').input_value() == value['income_rows'][1]['ref']
            assert form.locator('[name=participant_id]').input_value() == ('' if ambiguous else 'person-0')
            assert form.locator('[name=participant_id]').evaluate('(el)=>el===document.activeElement')
            assert page.locator('dialog[open]').count() == 0
            assert set(requests) == {'GET'}
            assert value == before
        finally:
            browser.close()
