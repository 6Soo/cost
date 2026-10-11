from unittest.mock import patch

import pytest

from webapp import ledger_board
from webapp.tests import test_rule_review as existing


@pytest.fixture
def app():
    case = existing.RuleReviewTests()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


def payload(case, **changes):
    return dict(transaction_id=case.tx[0], revision=case.rows[0]['revision'],
                exclusion_revision=0, excluded=True, confirmed=True, request_id='exclude-http', **changes)


def test_owner_exclusion_undo_and_retry_over_http(app):
    route = f'/api/imports/{app.batch}/company-exclusion'
    before = app.server.card_store.conn.execute('SELECT * FROM transactions').fetchall()
    with patch.object(ledger_board, '_receipts_owner_request', return_value=True):
        body = payload(app)
        status, result = app.post(route, body, token=ledger_board.CSRF_TOKEN)
        assert status == 200, result
        assert result['state']['preview']['excluded'] == 1
        assert next(r for r in result['state']['preview']['rows'] if r['transaction_id'] == app.tx[0])['blocked'] == 'company_excluded'
        assert app.post(route, body, token=ledger_board.CSRF_TOKEN)[0] == 200
        undo = dict(body, excluded=False, exclusion_revision=1, request_id='undo-http')
        status, result = app.post(route, undo, token=ledger_board.CSRF_TOKEN)
        assert status == 200, result
        assert result['state']['preview']['excluded'] == 0
    assert app.server.card_store.conn.execute('SELECT * FROM transactions').fetchall() == before


def test_owner_csrf_and_separate_confirmation_are_required(app):
    route = f'/api/imports/{app.batch}/company-exclusion'
    body = payload(app)
    assert app.post(route, body, token=ledger_board.CSRF_TOKEN)[0] == 403
    with patch.object(ledger_board, '_receipts_owner_request', return_value=True):
        assert app.post(route, body)[0] == 403
        status, result = app.post(route, dict(body, confirmed=False), token=ledger_board.CSRF_TOKEN)
        assert (status, result['code']) == (409, 'EXCLUSION_CONFIRMATION_REQUIRED')


def test_saved_exclusion_survives_state_failure_and_retry(app):
    from webapp.card_flow import CardFlow
    route = f'/api/imports/{app.batch}/company-exclusion'
    body = payload(app)
    before = app.server.card_store.conn.execute('SELECT * FROM transactions').fetchall()
    with patch.object(ledger_board, '_receipts_owner_request', return_value=True):
        with patch.object(CardFlow, 'state', side_effect=RuntimeError('private state failure')):
            status, result = app.post(route, body, token=ledger_board.CSRF_TOKEN)
        assert status == 200
        assert result['refresh_required'] is True
        assert result['state'] is None
        assert 'private state failure' not in str(result)
        status, replay = app.post(route, body, token=ledger_board.CSRF_TOKEN)
        assert status == 200
        assert replay['state']['preview']['excluded'] == 1
        assert replay['result'] == result['result']
    assert app.server.card_store.conn.execute('SELECT * FROM transactions').fetchall() == before


@pytest.mark.parametrize('status', [200, 500])
def test_delayed_exclusion_response_keeps_new_batch_status_and_proposal(app, status):
    from playwright.sync_api import sync_playwright
    second = app.flow.pipeline.receive(existing.CARD.replace(b'A123', b'A999'), 'second.csv')['batch_id']
    pending = []
    with patch.object(ledger_board, '_receipts_owner_request', return_value=True), sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        page = browser.new_page()
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(app.base + '/import')
        page.locator(f'[data-batch="{app.batch}"]').click()
        page.wait_for_function('(id)=>model.batch_id===id', arg=app.batch)
        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
        page.select_option('#rule-focus', app.tx[0])
        page.fill('#rule-text', '회사 경비 아님')
        page.click('#rule-propose')
        page.locator('#company-exclude').wait_for()
        page.route('**/company-exclusion', lambda route: pending.append(route))
        with page.expect_request('**/company-exclusion'):
            page.click('#company-exclude')
        if status == 200:
            code, result = app.post(f'/api/imports/{app.batch}/company-exclusion',
                                    pending[0].request.post_data_json, token=ledger_board.CSRF_TOKEN)
            assert code == 200
        else:
            result = {'message': 'OLD-EXCLUSION-ERROR'}
        page.locator(f'[data-batch="{second}"]').click()
        page.wait_for_function('(id)=>model.batch_id===id', arg=second)
        page.evaluate("document.getElementById('status').textContent='CURRENT-SELECTION';document.getElementById('rule-result').textContent='CURRENT-PROPOSAL'")
        with page.expect_response('**/company-exclusion'):
            pending.pop().fulfill(status=status, json=result)
        page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        assert page.locator('#status').inner_text() == 'CURRENT-SELECTION'
        assert page.locator('#rule-result').inner_text() == 'CURRENT-PROPOSAL'
        assert page.evaluate('model.batch_id') == second
        assert app.flow.state(app.batch)['preview']['excluded'] == (1 if status == 200 else 0)
        browser.close()


@pytest.mark.parametrize('width', [390, 1440])
def test_browser_proposes_exclusion_and_can_restore(app, width):
    from playwright.sync_api import sync_playwright
    with patch.object(ledger_board, '_receipts_owner_request', return_value=True), sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': width, 'height': 900})
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(app.base + '/import')
        page.locator('#rule-focus option').first.wait_for(state='attached')
        page.select_option('#rule-focus', app.tx[0])
        page.fill('#rule-text', '회사 경비 아님')
        page.click('#rule-propose')
        page.locator('#company-exclude').click()
        page.get_by_text('회사 경비에서 제외했습니다.', exact=False).wait_for()
        page.locator('[data-company-restore]').click()
        page.get_by_text('회사 경비 제외를 되돌렸습니다.', exact=False).wait_for()
        assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
        browser.close()
