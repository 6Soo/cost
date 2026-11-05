"""Coverage route boundaries on a synthetic SQLite store."""
import json
import sqlite3
import threading
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from app.db import Store
from webapp import card_upload_coverage as coverage
from webapp import ledger_board


@pytest.fixture
def board(monkeypatch):
    conn = sqlite3.connect(':memory:')
    Store(conn)
    monkeypatch.setattr(ledger_board, 'current_role', lambda: 'owner')
    yield SimpleNamespace(conn=conn, _lock=threading.RLock())
    conn.close()


class Handler:
    def __init__(self, token='csrf'):
        self.headers = {'X-CSRF-Token': token}
    def _send_json(self, value, status=200):
        self.value, self.status = value, status


def request(board, path, *, raw=None, token='csrf', csrf='csrf'):
    h = Handler(token)
    assert coverage.dispatch(h, urlparse(path), board, raw=raw, csrf=csrf)
    return h


def test_summary_read_without_schema_never_writes(board):
    before = board.conn.iterdump()
    snapshot = list(before)
    h = request(board, '/api/cards/coverage/summary')
    assert h.status == 200 and h.value['available'] is True
    assert list(board.conn.iterdump()) == snapshot


@pytest.mark.parametrize('role', ['viewer', 'member', None])
def test_coverage_reads_and_writes_require_owner(board, monkeypatch, role):
    monkeypatch.setattr(ledger_board, 'current_role', lambda: role)
    for path, raw in [('/api/cards/coverage/summary', None), ('/api/imports/x/coverage/confirm', b'{}')]:
        assert request(board, path, raw=raw).status == 403


@pytest.mark.parametrize('token,csrf', [('', 'csrf'), ('wrong', 'csrf'), ('', '')])
def test_confirm_rejects_absent_or_stale_csrf(board, token, csrf):
    h = request(board, '/api/imports/x/coverage/confirm', raw=b'{}', token=token, csrf=csrf)
    assert h.status == 403 and h.value['code'] == 'CSRF_REQUIRED'


def test_missing_upload_history_fails_closed_without_creating_schema():
    conn=sqlite3.connect(':memory:')
    empty=SimpleNamespace(conn=conn,_lock=threading.RLock())
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ledger_board,'current_role',lambda:'owner')
        assert coverage.get_coverage_summary(empty)['available'] is False
        payload=json.dumps({'evidence':{'complete':True}}).encode()
        h=request(empty,'/api/imports/x/coverage/confirm',raw=payload)
        assert h.status==409 and h.value['code']=='COVERAGE_NOT_READY'
        assert conn.execute('SELECT name FROM sqlite_master').fetchall()==[]
    conn.close()


def test_batch_get_uses_path_id_and_reports_missing_batch(board):
    h = request(board, '/api/imports/not-present/coverage')
    assert h.status == 409 and h.value['code'] == 'BATCH_NOT_FOUND'


def test_confirm_requires_explicit_complete_result(board):
    for payload in ([], None, 'bad', {}, {'evidence': []}, {'evidence': {'complete': 'true'}}):
        assert request(board, '/api/imports/x/coverage/confirm', raw=json.dumps(payload).encode()).status == 422


def test_get_on_confirm_and_post_on_summary_are_rejected(board):
    assert request(board, '/api/imports/x/coverage/confirm').status == 405
    assert request(board, '/api/cards/coverage/summary', raw=b'{}').status == 405


def test_baseline_route_requires_owner_and_csrf(board, monkeypatch):
    h = request(board, '/api/cards/coverage/baseline', raw=b'{}', token='')
    assert h.status == 403
    monkeypatch.setattr(ledger_board, 'current_role', lambda: 'member')
    h = request(board, '/api/cards/coverage/baseline', raw=b'{}')
    assert h.status == 403


def test_baseline_post_validates_known_card_without_creating_identity(board):
    payload = json.dumps({'card_id':'fake', 'issuer':'TEST', 'card_tail':'1234',
                          'date_basis':'이용일','management_start':'2026-04-01',
                          'expected_revision':0}).encode()
    h = request(board,'/api/cards/coverage/baseline',raw=payload)
    assert h.status == 409 and h.value['code'] == 'CARD_IDENTITY_REQUIRED'
    no_data = request(board,'/api/cards/coverage/baseline')
    assert no_data.status == 405
