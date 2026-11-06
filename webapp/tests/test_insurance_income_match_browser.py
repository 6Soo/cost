"""Name actions in the trip ledger replace the standalone comparison page."""
import copy
from unittest.mock import patch
import pytest
from playwright.sync_api import sync_playwright
from webapp import ledger_design_assets, participant_trip_panel as panel, site_shell
from webapp.tests.test_participant_trip_panel import sample_state


@pytest.mark.parametrize('matched', [False, True])
@pytest.mark.parametrize('ambiguous', [False, True])
def test_name_action_keeps_income_and_never_guesses_ambiguous_identity(matched, ambiguous):
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
    document = ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<style>' + ledger_design_assets.STYLE + '</style></head><body><main id="main"><section id="google-trip-income">'
                '<table id="income-tbl" data-google-generation="one"><tbody>' + rows + '</tbody></table></section>'
                + panel.shell(trip_id='trip-synthetic') + '</main><script>' + ledger_design_assets.SCRIPT + '</script></body></html>')
    with patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"></aside>'):
        document = site_shell.wrap_document(document, '/board')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 900})
            requests = []
            writes = []
            def serve(route):
                requests.append(route.request.method)
                if route.request.method == 'POST':
                    writes.append(route.request.post_data)
                    route.fulfill(status=409, content_type='application/json', body='{"code":"STALE_INPUT"}')
                else:
                    route.fulfill(content_type='text/html', body=response if '/trip-panel?' in route.request.url else document)
            page.route('http://synthetic.test/**', serve)
            page.goto('http://synthetic.test/')
            page.locator('#participant-trip-panel summary').click()
            page.locator('.participant-insurance-cell .insurance-candidate-button').nth(1).click()
            candidate = page.locator('.insurance-candidate-row')
            assert candidate.locator('footer,a').count() == 0
            name = candidate.locator('.insurance-participant-name')
            assert name.inner_text() == '김*수'
            assert name.evaluate('(el)=>getComputedStyle(el).color===getComputedStyle(el.closest("td")).color')
            name.focus()
            page.keyboard.press('Enter')
            assert page.locator('.insurance-candidate-row').count() == 1
            form = page.locator('.insurance-candidate-row .participant-keyboard-link')
            assert form.locator('[name=income_ref]').input_value() == value['income_rows'][1]['ref']
            assert form.locator('[name=participant_id]').input_value() == ('' if ambiguous else 'person-0')
            assert form.locator('select').count() == 0
            assert form.locator('legend').count() == 0
            assert form.locator('fieldset').get_attribute('aria-label') == '연결할 이름'
            assert form.locator('[data-pick-participant]').evaluate_all('els=>els.every(el=>!el.classList.contains("site-action")&&getComputedStyle(el).color===getComputedStyle(el.closest("td")).color)')
            assert page.locator('dialog[open]').count() == 0
            if ambiguous:
                assert writes == []
                assert form.locator('[data-pick-participant]').first.evaluate('(el)=>el===document.activeElement')
            else:
                page.wait_for_function("document.querySelector('.participant-inline-status').textContent.includes('자료가 변경')")
                from urllib.parse import parse_qs
                saved = parse_qs(writes[0])
                assert len(writes) == 1
                assert saved['income_ref'] == [value['income_rows'][1]['ref']]
                assert saved['participant_id'] == ['person-0']
                assert saved['csrf'] == ['synthetic-csrf']
                assert saved['input_fingerprint'] == ['synthetic-fingerprint']
                assert form.locator('[data-pick-participant]:disabled').count() == 0
            assert value == before
        finally:
            browser.close()
