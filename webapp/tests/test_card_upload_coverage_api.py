"""Coverage route boundaries on a synthetic SQLite store."""
import json
import sqlite3
import threading
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from app.db import Store
from app import Pipeline
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


def test_transaction_dates_make_legacy_uploaded_file_assessable(board):
    """Observed transaction dates are enough for the dashboard gap view."""
    raw = (
        '카드사,카드번호,카드종류,가맹점,이용금액,승인일,매입일,승인번호\\n'
        'SYNTH,1234-56**-****-1111,신용,SHOP,10,2026-04-03,2026-04-08,SYNTH-A\\n'
    ).replace('\\n', '\n').encode('utf-8-sig')
    batch_id = Pipeline(board.conn).receive(raw, 'history.csv')['batch_id']
    before = list(board.conn.iterdump())
    summary = coverage.get_coverage_summary(board)

    assert summary['overview']['card_count'] == 1
    assert summary['overview']['gap_count'] == 0
    assert summary['overview']['gaps_assessable'] is True
    assert summary['overview']['files_need_review'] == 0
    assert summary['coverage_state'] == 'transaction_dates'
    source = next(row for row in summary['files'] if row['batch_id'] == batch_id)
    assert source['coverage_status'] == 'transaction_dates'
    assert source['query_periods'] == []
    assert source['issuer_hint'] == 'SYNTH'
    assert source['card_tail_hint'] == ''
    assert source['card_hint_scope'] == 'issuer'
    assert source['transaction_start'] == '2026-04-03'
    # Reading the summary cannot promote any uploaded original to coverage.
    assert list(board.conn.iterdump()) == before

    inspected = coverage.batch_inspection(board, batch_id)
    assert inspected['evidence']['card_id']
    assert inspected['records'] == []


def test_empty_import_has_no_inferred_card_identity(board):
    raw = '카드사,카드번호,카드종류,가맹점,이용금액,승인일,매입일,승인번호\\n'.replace('\\n', '\n').encode('utf-8-sig')
    batch_id = Pipeline(board.conn).receive(raw, 'empty.csv')['batch_id']
    summary = coverage.get_coverage_summary(board)
    item = next(row for row in summary['files'] if row['batch_id'] == batch_id)
    assert item['zero_rows'] is True
    assert item['card_hint_scope'] == 'unknown'
    assert item['issuer_hint'] == ''
    assert item['card_tail_hint'] == ''
    assert summary['overview']['gaps_assessable'] is False


def test_gap_uses_each_observed_day_and_an_overlapping_upload_fills_it(board):
    header = '카드사,카드번호,카드종류,가맹점,이용금액,승인일,매입일,승인번호\n'
    rows = ('SYNTH,1234-56**-****-1111,신용,SHOP,10,2026-04-01,2026-04-10,A\n'
            'SYNTH,1234-56**-****-1111,신용,SHOP,11,2026-04-03,2026-04-10,B\n')
    pipeline = Pipeline(board.conn)
    pipeline.receive((header + rows).encode('utf-8-sig'), 'first.csv')
    assert coverage.get_coverage_summary(board)['cards'][0]['gaps'] == [
        {'start': '2026-04-02', 'end': '2026-04-02'}]
    pipeline.receive((header +
        'SYNTH,1234-56**-****-1111,신용,SHOP,12,2026-04-02,2026-04-10,C\n'
        + rows).encode('utf-8-sig'), 'overlap.csv')
    before = list(board.conn.iterdump())
    summary = coverage.get_coverage_summary(board, date_basis='거래일자')
    assert summary['cards'][0]['gaps'] == []
    assert summary['cards'][0]['periods'] == [{'start': '2026-04-01', 'end': '2026-04-03'}]
    assert summary['overview']['file_count'] == 2
    assert coverage.get_coverage_summary(board, date_basis='unknown')['cards'] == []
    assert coverage.get_coverage_summary(board, issuer='OTHER')['cards'] == []
    assert list(board.conn.iterdump()) == before


def test_mixed_card_file_unions_cards_by_issuer_and_keeps_file_total_unique(board):
    raw = ('카드사,카드번호,카드종류,가맹점,이용금액,승인일,매입일,승인번호\n'
           'SYNTH,1234-56**-****-1111,신용,A,10,2026-04-01,2026-04-01,A\n'
           'SYNTH,1234-56**-****-2222,신용,B,11,2026-04-03,2026-04-03,B\n')
    Pipeline(board.conn).receive(raw.encode('utf-8-sig'), 'mixed.csv')
    summary = coverage.get_coverage_summary(board)
    assert summary['overview']['card_count'] == 1
    assert summary['overview']['file_count'] == 1
    assert summary['overview']['gap_count'] == 1
    assert summary['cards'][0]['issuer'] == 'SYNTH'
    assert summary['cards'][0]['periods'] == [
        {'start': '2026-04-01', 'end': '2026-04-01'},
        {'start': '2026-04-03', 'end': '2026-04-03'}]
    assert summary['cards'][0]['gaps'] == [{'start': '2026-04-02', 'end': '2026-04-02'}]
    assert summary['files'][0]['unique_transactions'] == 2
    assert summary['files'][0]['card_tail_hint'] == ''
    assert coverage.get_coverage_summary(board, card_tail='1111')['overview']['card_count'] == 1
