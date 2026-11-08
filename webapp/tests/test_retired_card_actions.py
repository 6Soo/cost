"""Historical card questions cannot remain a second user workflow or write path."""
import json

import pytest

from webapp import ledger_board
from webapp.tests.test_signed_session_http import OWNER, VIEWER


@pytest.fixture
def signed_server():
    from webapp.tests.test_signed_session_http import SignedSessionHttpTests
    fixture = SignedSessionHttpTests('runTest')
    fixture.setUp()
    try:
        yield fixture
    finally:
        fixture.tearDown()


def test_legacy_workflow_get_redirects_without_task_or_financial_writes(signed_server):
    server = signed_server
    before = list(server.store.conn.iterdump())
    status, _, headers = server.request('/my-actions', cookie=server.cookie(OWNER))
    assert status == 303 and headers['Location'] == '/cards/all'
    status, _, headers = server.request('/review', cookie=server.cookie(OWNER))
    assert status == 303 and headers['Location'] == '/cards/all'
    assert list(server.store.conn.iterdump()) == before
    assert server.request('/my-actions')[0] == 403
    assert server.request('/my-actions', cookie=server.cookie(VIEWER))[0] == 403


def test_retired_answer_preserves_auth_csrf_and_never_consumes_history(signed_server):
    server = signed_server
    payload = dict(action_id='historical',answer='anything',revision='1',digest='original')
    before = list(server.store.conn.iterdump())
    assert server.request('/api/user-actions/answer',payload=payload)[0] == 401
    assert server.request('/api/user-actions/answer',cookie=server.cookie(VIEWER),payload=payload)[0] == 403
    assert server.request('/api/user-actions/answer',cookie=server.cookie(OWNER),payload=payload)[0] == 403
    assert server.request('/api/user-actions/answer',cookie=server.cookie(OWNER),payload=[])[0] == 400
    payload['csrf'] = ledger_board.CSRF_TOKEN
    status, body, _ = server.request('/api/user-actions/answer',cookie=server.cookie(OWNER),payload=payload)
    assert status == 410 and json.loads(body)['code'] == 'CARD_ACTIONS_RETIRED'
    assert list(server.store.conn.iterdump()) == before


def test_legacy_adapter_imports_cannot_create_or_apply_questions():
    from webapp import user_action_adapters as adapter
    class NoStore:
        def execute(self,*args,**kwargs):
            raise AssertionError('retired adapter must not read or write customer data')
    assert adapter.register_card_item_tasks(NoStore(), [('legacy',)], lambda *_: {'status':'p2_applied'}) == 0
    assert adapter.apply_card_item_answers(NoStore(), object()) == 0
