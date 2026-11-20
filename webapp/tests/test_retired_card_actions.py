"""Historical card questions cannot remain a second user workflow or write path."""
import pytest

from webapp import ledger_board
from webapp.tests.test_signed_session_http import OWNER, VIEWER


@pytest.fixture
def signed_server():
    from webapp.tests.test_signed_session_http import SignedSessionHttpTests
    fixture = SignedSessionHttpTests('runTest')
    fixture.setUp()
    try:
        conn = fixture.server.card_store.conn
        conn.execute(
            "INSERT INTO requests(request_id, scope, payload_sha256, response_json, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("historical-action", "user_action_task_v1", "synthetic-history",
             '{"state":"REPROCESSING","answer":{"value":"식비"}}', "2026-11-05T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO transaction_review_holds(transaction_id, source_hash, kind, reason)"
            " VALUES (?, ?, ?, ?)",
            ("synthetic-card", "synthetic-source", "user_hold", "합성 수동 확인"),
        )
        conn.commit()
        yield fixture
    finally:
        fixture.tearDown()


def test_legacy_workflow_get_redirects_without_task_or_financial_writes(signed_server):
    server = signed_server
    board_before = list(server.store.conn.iterdump())
    cards_before = list(server.server.card_store.conn.iterdump())
    status, _, headers = server.request('/my-actions', cookie=server.cookie(OWNER))
    assert status == 303 and headers['Location'] == '/cards/all'
    status, _, headers = server.request('/review', cookie=server.cookie(OWNER))
    assert status == 303 and headers['Location'] == '/cards/all'
    assert list(server.store.conn.iterdump()) == board_before
    assert list(server.server.card_store.conn.iterdump()) == cards_before
    assert server.request('/my-actions')[0] == 403
    assert server.request('/my-actions', cookie=server.cookie(VIEWER))[0] == 403


@pytest.mark.parametrize('path', [
    '/api/user-actions/answer',
    '/api/imports/reclassify-pending',
])
def test_retired_write_addresses_return_not_found_without_changes(signed_server, path):
    server = signed_server
    payload = dict(action_id='historical', answer='anything', revision='1', digest='original')
    board_before = list(server.store.conn.iterdump())
    cards_before = list(server.server.card_store.conn.iterdump())
    assert server.request(path, payload=payload)[0] == 401
    assert server.request(path, cookie=server.cookie(VIEWER), payload=payload)[0] == 403
    owner = server.cookie(OWNER)
    assert server.request(path, cookie=owner)[0] == 404
    assert server.request(path, cookie=owner, payload=payload)[0] == 404
    payload['csrf'] = ledger_board.CSRF_TOKEN
    headers = {'X-CSRF-Token': ledger_board.CSRF_TOKEN}
    assert server.request(path, cookie=owner, headers=headers, payload=payload)[0] == 404
    assert list(server.store.conn.iterdump()) == board_before
    assert list(server.server.card_store.conn.iterdump()) == cards_before
