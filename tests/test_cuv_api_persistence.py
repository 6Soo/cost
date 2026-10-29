"""Synthetic HTTP boundary checks for durable card uploads and safe retries."""
from urllib.parse import urlparse

from tests.card_pipeline.fixtures import domestic_row, make_xlsx


class Handler:
    def __init__(self):
        self.headers = {'X-CSRF-Token': 'csrf', 'X-Filename': 'synthetic.xlsx'}
        self.response = None

    def _send_json(self, data, status=200):
        self.response = data, status


def _bind(monkeypatch, tmp_path):
    from webapp import ledger_board
    from webapp.ledger_store import LedgerStore

    monkeypatch.setenv('WEBLEDGER_CARD_FLOW', '1')
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    ledger_board.bind_store(board)
    monkeypatch.setattr(ledger_board, 'current_role', lambda: 'owner')
    return board


def _upload(monkeypatch, content):
    from webapp import card_flow

    handler = Handler()
    assert card_flow.dispatch(handler, urlparse('/api/imports'), raw=content, csrf='csrf')
    return handler.response


def test_upload_requires_owner_before_persisting(monkeypatch, tmp_path):
    from webapp import card_flow, ledger_board

    board = _bind(monkeypatch, tmp_path)
    monkeypatch.setattr(ledger_board, 'current_role', lambda: 'viewer')
    content = make_xlsx([domestic_row(merchant='합성 상점', amount=1000, approval='API-1')])
    handler = Handler()
    assert card_flow.dispatch(handler, urlparse('/api/imports'), raw=content, csrf='csrf')
    payload, status = handler.response
    assert status == 403
    assert payload['code'] == 'FORBIDDEN'
    assert board.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 0
    board.close()


def test_http_body_limit_matches_card_upload_preflight():
    from app.card_preflight import MAX_BYTES
    from webapp.board_http_shapes import MAX_CONTENT_LENGTH

    assert MAX_CONTENT_LENGTH == MAX_BYTES


def test_post_receive_failure_is_explicit_and_same_file_retry_is_idempotent(
        monkeypatch, tmp_path):
    from webapp import card_flow

    board = _bind(monkeypatch, tmp_path)
    content = make_xlsx([domestic_row(merchant='합성 상점', amount=1000, approval='API-2')])
    original = card_flow.CardFlow.classify
    monkeypatch.setattr(card_flow.CardFlow, 'classify', lambda self, batch_id: (_ for _ in ()).throw(RuntimeError()))

    payload, status = _upload(monkeypatch, content)
    assert status == 503
    assert payload['code'] == 'UPLOAD_PROCESSING_INCOMPLETE'
    assert payload['source_rows_persisted'] is True
    assert payload['verification_status'] == 'unavailable'
    assert payload['retry_same_file'] is True
    assert board.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 1

    monkeypatch.setattr(card_flow.CardFlow, 'classify', original)
    payload, status = _upload(monkeypatch, content)
    assert status == 200
    assert payload['upload_summary']['counts']['T'] == 1
    assert payload['upload_summary']['counts']['N'] == 0
    assert board.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 1
    board.close()
