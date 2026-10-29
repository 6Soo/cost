"""Synthetic HTTP boundary checks for durable card uploads and safe retries."""
import json
import time
from urllib.parse import urlparse

from tests.card_pipeline.fixtures import domestic_row, make_csv, make_xlsx


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
    monkeypatch.setattr(ledger_board, '_STORE', board)
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
    from webapp.board_http_shapes import MAX_CONTENT_LENGTH, max_content_length

    assert max_content_length('/api/imports') == MAX_BYTES
    assert max_content_length('/api/imports/extra') == MAX_CONTENT_LENGTH
    assert max_content_length('/api/income') == MAX_CONTENT_LENGTH


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


def test_dispatch_api_10k_rows_and_same_file_retry_metrics(monkeypatch, tmp_path):
    """Exercise the actual upload dispatch with isolated SQLite and synthetic CSV."""
    board = _bind(monkeypatch, tmp_path)
    content = make_csv([
        domestic_row(merchant=f'합성상점{i}', amount=1000 + i,
                     approval=f'BENCH-{i:06d}')
        for i in range(10_000)
    ])

    started = time.perf_counter()
    first, first_status = _upload(monkeypatch, content)
    first_seconds = time.perf_counter() - started
    first_bytes = len(json.dumps(first, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    assert first_status == 200
    first_counts = first['upload_summary']['counts']
    assert first_counts['T'] == 10_000
    assert first_counts['T'] == first_counts['E'] + first_counts['N'] + first_counts['H'] + first_counts['P']
    assert first_counts['N'] == 10_000

    started = time.perf_counter()
    retry, retry_status = _upload(monkeypatch, content)
    retry_seconds = time.perf_counter() - started
    retry_bytes = len(json.dumps(retry, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    assert retry_status == 200
    retry_counts = retry['upload_summary']['counts']
    assert retry_counts['T'] == 10_000
    assert retry_counts['T'] == retry_counts['E'] + retry_counts['N'] + retry_counts['H'] + retry_counts['P']
    assert retry_counts['E'] == 10_000
    assert retry_counts['N'] == 0
    assert board.conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 10_000

    metrics = {
        'synthetic_rows': 10_000,
        'first_upload': {'elapsed_seconds': round(first_seconds, 3), 'response_bytes': first_bytes,
                         'T': first_counts['T'], 'E': first_counts['E'], 'N': first_counts['N']},
        'same_file_retry': {'elapsed_seconds': round(retry_seconds, 3), 'response_bytes': retry_bytes,
                            'T': retry_counts['T'], 'E': retry_counts['E'], 'N': retry_counts['N']},
        'database_transaction_rows_after_retry': 10_000,
    }
    (tmp_path / 'cuv_api_10k_benchmark.json').write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    print('CUV_API_10K_METRICS=' + json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    board.close()
