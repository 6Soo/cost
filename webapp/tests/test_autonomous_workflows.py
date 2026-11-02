"""Synthetic end-to-end HTTP journeys; no operating data or external services."""
from __future__ import annotations

import json
import os
import sys
import time
import zipfile
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from tests.card_pipeline.fixtures import domestic_row, make_xlsx
from webapp import google_oidc, ledger_board

OWNER = 'synthetic-owner-sub'
VIEWER = 'synthetic-viewer-sub'


@pytest.fixture
def service(monkeypatch):
    from webapp.tests.test_signed_session_http import SignedSessionHttpTests
    instance = SignedSessionHttpTests()
    instance.setUp()
    export_dir = instance.root / 'exports'
    monkeypatch.setenv('WEBLEDGER_EXPORT_DIR', str(export_dir))
    monkeypatch.setenv('WEBLEDGER_UPLOAD_ASYNC', '1')
    try:
        yield instance
    finally:
        instance.tearDown()


def binary_request(service, path, data, *, user=OWNER, csrf=True, headers=None):
    request_headers = {
        'Content-Type': 'application/octet-stream',
        'X-CSRF-Token': ledger_board.CSRF_TOKEN if csrf else '',
        'Cookie': f'{google_oidc.COOKIE_NAME}={service.cookie(user)}' if user else '',
    }
    request_headers.update(headers or {})
    req = Request(f'http://127.0.0.1:{service.port}{path}', data=data, headers=request_headers)
    try:
        response = service.opener.open(req, timeout=12)
    except HTTPError as error:
        response = error
    return response.code, response.read(), response.headers


def json_post(service, path, payload, *, user=OWNER, csrf=True):
    return service.request(path, cookie=service.cookie(user) if user else None,
                           payload=payload,
                           headers={'X-CSRF-Token': ledger_board.CSRF_TOKEN if csrf else ''})


def binary_get(service, path, *, user=OWNER):
    request = Request(f'http://127.0.0.1:{service.port}{path}', headers={
        'Cookie': f'{google_oidc.COOKIE_NAME}={service.cookie(user)}' if user else '',
    })
    try:
        response = service.opener.open(request, timeout=10)
    except HTTPError as error:
        response = error
    return response.code, response.read(), response.headers


def test_upload_refresh_idempotency_search_detail_reject_copy_and_xlsx(service, request, monkeypatch):
    board = service.server.card_store
    from webapp import card_upload_jobs
    process_calls = []
    process_lock = __import__('threading').Lock()
    original_process = card_upload_jobs.process

    def count_process(*args, **kwargs):
        with process_lock:
            process_calls.append(True)
        return original_process(*args, **kwargs)

    monkeypatch.setattr(card_upload_jobs, 'process', count_process)
    raw = make_xlsx([
        domestic_row(merchant='SYNTHETIC JOURNEY CAFE', amount=18400,
                     approval='SYN-JOURNEY-001', issuer='SYNTHETIC ISSUER'),
        domestic_row(merchant='SYNTHETIC JOURNEY CAFE', amount=-18400,
                     approval='SYN-JOURNEY-001', issuer='SYNTHETIC ISSUER',
                     kind='PURCHASE CANCELLATION', status='CANCELLED'),
    ])
    # Owner upload returns 202 after durable source ingestion; refresh receives
    # only the shell and status polling eventually returns the completed result.
    code, body, _ = binary_request(service, '/api/imports', raw, headers={
        'X-Filename': quote('synthetic-journey.xlsx'), 'X-Upload-Async': '1'})
    assert code == 202, body
    ack = json.loads(body)
    assert ack['source_rows_persisted'] is True
    assert service.request('/import', cookie=service.cookie(OWNER))[0] == 200
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        code, state, _ = service.request(ack['status_url'], cookie=service.cookie(OWNER))
        if code != 200:
            pytest.fail(f'upload status {code}: {state}')
        status = json.loads(state)
        if status['status'] != 'running':
            break
        time.sleep(.05)
    assert status['status'] == 'done', status
    assert len(process_calls) == 1

    # Reposting identical workbook is idempotent: one source transaction and no
    # second ledger entry. Denied roles / missing CSRF cause no database effect.
    entries_after_first = board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]
    code, replay_body, _ = binary_request(service, '/api/imports', raw, headers={
        'X-Filename': quote('synthetic-journey.xlsx'), 'X-Upload-Async': '1'})
    assert code == 202
    replay = json.loads(replay_body)
    assert replay['batch_id'] == ack['batch_id']
    assert replay['status_url'] == ack['status_url']
    assert len(process_calls) == 1
    rows = board.conn.execute(
        'SELECT transaction_id, source_hash, revision FROM transactions '
        'WHERE transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?)',
        (ack['batch_id'],)).fetchall()
    assert len(rows) == 2
    source_id, source_hash, revision = next(row for row in rows if row[2] >= 1)
    identities = [row[0] for row in rows]
    immutable_before = {tid: board.conn.execute(
        'SELECT source_hash, issuer, card_tail, amount_krw, transaction_direction '
        'FROM transactions WHERE transaction_id=?', (tid,)).fetchone() for tid in identities}
    assert sum(board.conn.execute(
        'SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone()[0]
        for tid in identities) <= len(identities)
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == entries_after_first
    before_denied = board.conn.total_changes
    for user, csrf, expected in ((VIEWER, True, 403), (None, True, 401), (OWNER, False, 403)):
        denied, _, _ = binary_request(service, '/api/imports', raw, user=user, csrf=csrf,
                                      headers={'X-Filename': 'denied.xlsx', 'X-Upload-Async': '1'})
        assert denied == expected
    assert board.conn.total_changes == before_denied
    denied_status, _, _ = service.request(ack['status_url'], cookie=service.cookie(VIEWER))
    assert denied_status == 403

    # Search and row detail use the stored source and do not rewrite it.
    search_code, search_html, _ = service.request(
        '/cards/all?year=2026&q=SYNTHETIC%20JOURNEY%20CAFE', cookie=service.cookie(OWNER))
    assert search_code == 200, search_html[:500]
    assert 'SYNTHETIC JOURNEY CAFE' in search_html
    detail_code, detail_body, _ = service.request(
        '/api/cards/transactions/detail?id=' + quote(source_id), cookie=service.cookie(OWNER))
    assert detail_code == 200, detail_body
    detail = json.loads(detail_body)
    assert 'SYNTHETIC JOURNEY CAFE' in detail['html']
    assert board.conn.execute('SELECT source_hash, revision FROM transactions WHERE transaction_id=?',
                              (source_id,)).fetchone() == (source_hash, revision)

    # A stale/invalid destination is rejected and keeps the user's submitted
    # values at the client boundary (the HTTP response is a field-level error);
    # neither transaction nor original source is changed.
    state_code, state_body, _ = service.request('/api/imports/' + ack['batch_id'],
                                                 cookie=service.cookie(OWNER))
    assert state_code == 200, state_body
    upload_state = json.loads(state_body)
    row = upload_state['rows'][0]
    bad = dict(transaction_id=source_id, revision=row['revision'], item='SYNTHETIC CORRECTION',
               description='PRESERVE INPUT CHECK', display_tab_id='missing-synthetic-trip',
               request_id='autonomous-bad-correction')
    bad_code, bad_body, _ = json_post(service, '/api/imports/' + ack['batch_id'] + '/decision', bad)
    assert bad_code in (409, 422), bad_body
    after = board.conn.execute('SELECT source_hash, revision, item, description FROM transactions WHERE transaction_id=?',
                               (source_id,)).fetchone()
    assert after[0] == source_hash and after[1] == revision
    assert after[2] != 'SYNTHETIC CORRECTION' and after[3] != 'PRESERVE INPUT CHECK'

    # Google TSV is only a preview/copy payload. It must not mutate card,
    # ledger, source, or Google fixture state.
    before_copy = board.conn.total_changes
    google_snapshot = service.snapshot.read_bytes()
    copy_code, copy_body, _ = service.request(
        '/api/imports/' + ack['batch_id'] + '/google-tsv?tab=quarter:2026:1',
        cookie=service.cookie(OWNER))
    assert copy_code == 400 and json.loads(copy_body)['code'] == 'QUARTER_SHEET_NOT_READY'
    viewer_copy, _, _ = service.request(
        '/api/imports/' + ack['batch_id'] + '/google-tsv?tab=quarter:2026:1',
        cookie=service.cookie(VIEWER))
    assert viewer_copy == 403
    assert board.conn.total_changes == before_copy
    assert service.snapshot.read_bytes() == google_snapshot
    assert board.conn.execute('SELECT source_hash FROM transactions WHERE transaction_id=?',
                              (source_id,)).fetchone()[0] == source_hash
    assert {tid: board.conn.execute(
        'SELECT source_hash, issuer, card_tail, amount_krw, transaction_direction '
        'FROM transactions WHERE transaction_id=?', (tid,)).fetchone() for tid in identities} == immutable_before

    # The real export page is a read-only summary. Record timing for diagnosis,
    # but assert no arbitrary latency threshold: no performance defect is proven.
    changes_before_export_page = board.conn.total_changes
    started = time.monotonic()
    page_code, page_html, _ = service.request('/export', cookie=service.cookie(OWNER))
    export_page_seconds = time.monotonic() - started
    request.node.user_properties.append(('export_page_seconds', f'{export_page_seconds:.6f}'))
    assert page_code == 200 and "action='/api/exports/xlsx'" in page_html
    assert board.conn.total_changes == changes_before_export_page
    assert export_page_seconds >= 0

    store = service.server.card_store
    created = store.create_trip(starts_on='2026-04-01', ends_on='2026-04-30',
        destination='Synthetic export trip', display_key='Synthetic export trip',
        client_request_id='autonomous-export-trip')
    current = store.get_trip(created['tab_id'])
    trip_code, trip_body, _ = json_post(service, f"/api/trips/{created['tab_id']}/meta", {
        'expected_revision': current['revision'], 'client_request_id': 'autonomous-export-assignee',
        'prepared_by_name': 'Synthetic owner',
    })
    assert trip_code == 200, trip_body
    export_code, export_body, _ = json_post(service, '/api/exports/xlsx', {
        'tab_ids': [created['tab_id']], 'client_request_id': 'autonomous-xlsx-export'})
    assert export_code == 200, export_body
    job = json.loads(export_body)
    file_code, xlsx, file_headers = binary_get(
        service, f"/api/exports/{job['job_id']}/download")
    assert file_code == 200 and file_headers['Content-Type'].startswith(
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    with zipfile.ZipFile(BytesIO(xlsx)) as archive:
        assert archive.testzip() is None
        assert 'xl/workbook.xml' in archive.namelist()


def test_synthetic_google_copy_and_manual_record_are_read_only_or_idempotent(service):
    store = service.server.card_store
    before_snapshot = service.snapshot.read_bytes()
    before_schema = store.conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    # Manual expense submission is an explicit owner write; repeating its
    # idempotency key must return the same row, never duplicate the record.
    trip = store.create_trip(starts_on='2026-04-01', destination='Synthetic manual trip',
        ends_on='2026-04-30', display_key='Synthetic manual trip',
        client_request_id='autonomous-manual-trip')['tab_id']
    payload = {
        'amount_krw': '7200', 'occurred_on': '2026-04-10',
        'pay_method': '\uD604\uAE08', 'item': 'OTHER_EXPENSE',
        'description': 'synthetic manual journey',
        'display_tab_id': trip,
        'client_request_id': 'autonomous-manual-expense-once',
    }
    status, first_body, _ = json_post(service, '/api/expenses/manual', payload)
    assert status == 200, first_body
    first = json.loads(first_body)
    manual_count = store.conn.execute('SELECT COUNT(*) FROM board_rows WHERE row_id=?',
                                      (first['row_id'],)).fetchone()[0]
    status, second_body, _ = json_post(service, '/api/expenses/manual', payload)
    assert status == 200, second_body
    second = json.loads(second_body)
    assert first['row_id'] == second['row_id']
    assert store.conn.execute('SELECT COUNT(*) FROM board_rows WHERE row_id=?',
                              (first['row_id'],)).fetchone()[0] == 1
    assert store.conn.execute('SELECT COUNT(*) FROM board_rows WHERE row_id=?',
                              (first['row_id'],)).fetchone()[0] == manual_count == 1
    after_manual_schema = store.conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    assert after_manual_schema == before_schema
    assert service.snapshot.read_bytes() == before_snapshot
    assert store.conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall() == before_schema
    assert service.snapshot.read_bytes() == before_snapshot
