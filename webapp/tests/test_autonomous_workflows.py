"""Synthetic end-to-end HTTP journeys; no operating data or external services."""
from __future__ import annotations

import json
import os
import sys
import time
import zipfile
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import pytest

from tests.card_pipeline.fixtures import domestic_row, make_xlsx
from webapp import google_oidc, ledger_board

OWNER = 'synthetic-owner-sub'
VIEWER = 'synthetic-viewer-sub'


def seed_synthetic_trip(service):
    """Reuse signed identity and Google snapshot fixtures for a ready Q2 tab."""
    from copy import deepcopy
    from app import google_authority
    from webapp.tests.test_google_canonical_workflow import healthy_snapshot

    tab_id = 'quarter:2026:2'
    snapshot = healthy_snapshot()
    trip = deepcopy(snapshot['trips'][0])
    stamp = __import__('datetime').datetime.now(google_authority.KST).isoformat()
    trip.update(key='2분기_기타비용', kind='quarter', quarter=2, ledger_year=2026,
                canonical_source='main', closure='open', closure_current=True,
                verified=True, review=[])
    trip['copies'] = {'main': {
        'sheet': '2분기_기타비용', 'kind': 'quarter', 'ledger_year': 2026,
        'layout': 'rev', 'flags': [],
        'income': {'sheet_total': 0, 'row_sum': 0, 'total': 0, 'verified': True},
        'expense': {'sheet_total': 0, 'row_sum': 0, 'total': 0, 'verified': True},
    }, 'archive': None}
    trip.update(income_total=0, expense_total=0, net=None,
                reported={'income_total': 0, 'expense_total': 0, 'net': None})
    snapshot.update(trips=[trip], synced_at=stamp)
    for source in snapshot['sources'].values():
        source.update(status='ok', stale=False, last_ok_at=stamp, checked_at=stamp)
    service.snapshot.write_text(json.dumps(snapshot), encoding='utf-8')
    store = service.server.card_store
    created = store.create_trip(starts_on='2026-04-01', ends_on='2026-06-29',
        destination='Synthetic Q2 source', display_key='2분기_기타비용',
        client_request_id='autonomous-quarter-source-trip')
    quarter_trip = store.get_trip(created['tab_id'])
    quarter_trip.update(tab_id=tab_id, key='2분기_기타비용', kind='quarter', quarter=2,
        ledger_year=2026, canonical_source='main', closure='open', closure_current=True,
        verified=True, review=[])
    required_trip_keys = {
        'tab_id', 'display_key', 'destination', 'starts_on', 'ends_on', 'prepared_on',
        'prepared_by_name', 'archived', 'revision', 'event_year', 'tab_kind',
        'authority_status', 'source_sha256', 'assignee_source',
    }
    assert required_trip_keys <= quarter_trip.keys()
    list_trips = store.list_trips
    service.server.card_store.list_trips = lambda include_archived=True: (
        list_trips(include_archived=include_archived) + [quarter_trip])
    return tab_id


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
    from webapp.card_flow import CardFlow
    monkeypatch.setattr(CardFlow, 'trip_valid', lambda self, target: target == trip_id)
    trip_id = seed_synthetic_trip(service)
    trip = next(item for item in service.server.card_store.list_trips()
                if item['tab_id'] == trip_id)
    trips_code, trips_html, _ = service.request(
        '/trips?state=quarter', cookie=service.cookie(OWNER))
    assert trips_code == 200, trips_html[:500]
    assert f"id='manage-{trip_id}'" in trips_html
    assert f'name=\'prepared_on\' value=\'{trip["prepared_on"]}\'' in trips_html
    assert '담당자' in trips_html
    source_trip = next(item for item in service.server.card_store.list_trips()
                       if item['destination'] == 'Synthetic Q2 source')
    submitted = {
        'csrf': ledger_board.CSRF_TOKEN,
        'expected_revision': str(source_trip['revision'] - 1),
        'client_request_id': 'autonomous-trip-stale-input',
        'return_to': '/trips',
        'display_key': 'SYNTHETIC REJECTED TITLE',
        'prepared_on': '2026-04-02',
        'prepared_by_name': source_trip['prepared_by_name'],
        'assignee_form': '1',
    }
    rejected_request = Request(
        f'http://127.0.0.1:{service.port}/api/trips/{quote(source_trip["tab_id"])}/meta',
        data=urlencode(submitted).encode(),
        headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Cookie': f'{google_oidc.COOKIE_NAME}={service.cookie(OWNER)}',
        })
    try:
        rejected_response = service.opener.open(rejected_request, timeout=5)
    except HTTPError as error:
        rejected_response = error
    rejected_html = rejected_response.read().decode('utf-8')
    assert rejected_response.code == 409, rejected_html[:500]
    assert 'SYNTHETIC REJECTED TITLE' in rejected_html
    assert '2026-04-02' in rejected_html
    unchanged_trip = service.server.card_store.get_trip(source_trip['tab_id'])
    assert unchanged_trip['display_key'] == source_trip['display_key']
    assert unchanged_trip['prepared_on'] == source_trip['prepared_on']
    from webapp import card_upload_jobs
    process_calls = []
    process_lock = __import__('threading').Lock()
    original_process = card_upload_jobs.process

    def count_process(*args, **kwargs):
        with process_lock:
            process_calls.append(True)
        return original_process(*args, **kwargs)

    monkeypatch.setattr(card_upload_jobs, 'process', count_process)
    threading = __import__('threading')
    original_thread_start = threading.Thread.start
    held_upload_threads = []

    def hold_upload_start(thread, *args, **kwargs):
        if thread.name == 'card-upload':
            held_upload_threads.append(thread)
            return None
        return original_thread_start(thread, *args, **kwargs)

    monkeypatch.setattr(threading.Thread, 'start', hold_upload_start)
    raw = make_xlsx([
        domestic_row(merchant='SYNTHETIC JOURNEY CAFE', amount=18400,
                     approval='SYN-JOURNEY-001', issuer='SYNTHETIC ISSUER', card='****3820', kind='매입'),
        domestic_row(merchant='SYNTHETIC MANUAL CAFE', amount=7000,
                     approval='SYN-JOURNEY-002', issuer='SYNTHETIC ISSUER', card='****1111', kind='매입'),
    ])
    # Owner upload returns 202 after durable source ingestion; refresh receives
    # only the shell and status polling eventually returns the completed result.
    code, body, _ = binary_request(service, '/api/imports', raw, headers={
        'X-Filename': quote('synthetic-journey.xlsx'), 'X-Upload-Async': '1'})
    assert code == 202, body
    ack = json.loads(body)
    assert ack['source_rows_persisted'] is True
    legacy_code, _, legacy_headers = service.request('/import', cookie=service.cookie(OWNER))
    assert legacy_code == 302
    assert legacy_headers.get('Location') == '/cards/all?panel=upload'
    assert len(held_upload_threads) == 1
    state_code, state_body, _ = service.request('/api/imports/' + ack['batch_id'],
                                                 cookie=service.cookie(OWNER))
    assert state_code == 200, state_body
    manual_row = next(row for row in json.loads(state_body)['rows']
                      if row['merchant'] == 'SYNTHETIC MANUAL CAFE')
    manual_id = manual_row['transaction_id']
    monkeypatch.setattr(threading.Thread, 'start', original_thread_start)
    original_thread_start(held_upload_threads.pop())
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
    assert status['result']['summary']['status'] == 'classified'

    # A correction made after completion must refresh the cached replay result
    # without launching another classifier or ledger writer.
    state_code, state_body, _ = service.request('/api/imports/' + ack['batch_id'],
                                                 cookie=service.cookie(OWNER))
    assert state_code == 200, state_body
    manual_row = next(row for row in json.loads(state_body)['rows']
                      if row['transaction_id'] == manual_id)
    decision_code, decision_body, _ = json_post(service, '/api/imports/' + ack['batch_id'] + '/decision', {
        'transaction_id': manual_row['transaction_id'], 'revision': manual_row['revision'],
        'item': '분기 기타비용', 'description': 'OWNER MANUAL CORRECTION',
        'display_tab_id': trip_id, 'request_id': 'autonomous-manual-correction',
    })
    assert decision_code == 200, decision_body

    # Reposting identical workbook is idempotent: one source transaction and no
    # second ledger entry. Denied roles / missing CSRF cause no database effect.
    entries_after_first = board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0]
    code, replay_body, _ = binary_request(service, '/api/imports', raw, headers={
        'X-Filename': quote('synthetic-journey.xlsx'), 'X-Upload-Async': '1'})
    assert code == 202
    replay = json.loads(replay_body)
    assert replay['batch_id'] == ack['batch_id']
    assert replay['status_url'] == ack['status_url']
    assert 'refresh_required' not in replay['result']
    replay_manual = next(row for row in replay['result']['rows']
                         if row['transaction_id'] == manual_id)
    assert replay_manual['description'] == 'OWNER MANUAL CORRECTION'
    assert len(process_calls) == 1
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 2
    rows = board.conn.execute(
        'SELECT transaction_id, source_hash, revision FROM transactions '
        'WHERE transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?)',
        (ack['batch_id'],)).fetchall()
    assert len(rows) == 2
    source_id = board.conn.execute(
        "SELECT transaction_id FROM transactions WHERE merchant='SYNTHETIC JOURNEY CAFE'").fetchone()[0]
    source_hash, revision = board.conn.execute(
        'SELECT source_hash, revision FROM transactions WHERE transaction_id=?', (source_id,)).fetchone()
    identities = [row[0] for row in rows]
    immutable_before = {tid: board.conn.execute(
        'SELECT source_hash, issuer, card_tail, amount_krw, transaction_direction '
        'FROM transactions WHERE transaction_id=?', (tid,)).fetchone() for tid in identities}
    assert sum(board.conn.execute(
        'SELECT COUNT(*) FROM ledger_entries WHERE transaction_id=?', (tid,)).fetchone()[0]
        for tid in identities) == 2
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == entries_after_first == 2
    manual_after = board.conn.execute(
        'SELECT item, description, classification_source FROM transactions WHERE transaction_id=?',
        (manual_id,)).fetchone()
    assert manual_after == ('분기 기타비용', 'OWNER MANUAL CORRECTION', 'user_decision')
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

    # The verified fixture provides a successful copy payload without mutating
    # card, ledger, source, or Google fixture state.
    before_copy = board.conn.total_changes
    google_snapshot = service.snapshot.read_bytes()
    copy_code, copy_body, _ = service.request(
        '/api/imports/' + ack['batch_id'] + '/google-tsv?tab=' + quote(trip_id),
        cookie=service.cookie(OWNER))
    assert copy_code == 200, copy_body
    copied = json.loads(copy_body)
    fields = copied['tsv'].rstrip('\n').split('\t')
    copied_rows = [line.split('\t') for line in copied['tsv'].rstrip('\n').splitlines()]
    assert copied['row_count'] == 2 and all(len(row) == 7 for row in copied_rows), copy_body
    assert {row[1] for row in copied_rows} == {'SYNTHETIC JOURNEY CAFE', 'SYNTHETIC MANUAL CAFE'}
    viewer_copy, _, _ = service.request(
        '/api/imports/' + ack['batch_id'] + '/google-tsv?tab=' + quote(trip_id),
        cookie=service.cookie(VIEWER))
    assert viewer_copy == 403
    assert board.conn.total_changes == before_copy
    assert service.snapshot.read_bytes() == google_snapshot
    assert board.conn.execute('SELECT source_hash FROM transactions WHERE transaction_id=?',
                              (source_id,)).fetchone()[0] == source_hash
    assert {tid: board.conn.execute(
        'SELECT source_hash, issuer, card_tail, amount_krw, transaction_direction '
        'FROM transactions WHERE transaction_id=?', (tid,)).fetchone() for tid in identities} == immutable_before
    assert board.conn.execute(
        'SELECT item, description, classification_source FROM transactions WHERE transaction_id=?',
        (manual_id,)).fetchone() == manual_after

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
    manual_payload = {
        'amount_krw': '7200', 'occurred_on': '2026-04-10', 'pay_method': '현금',
        'item': 'OTHER_EXPENSE', 'description': 'SYNTHETIC EXPORT MERCHANT',
        'display_tab_id': created['tab_id'], 'client_request_id': 'autonomous-export-expense',
    }
    manual_code, manual_body, _ = json_post(service, '/api/expenses/manual', manual_payload)
    assert manual_code == 200, manual_body
    manual_row_id = json.loads(manual_body)['row_id']
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
    from openpyxl import load_workbook
    workbook = load_workbook(BytesIO(xlsx), read_only=True, data_only=True)
    values = [value for sheet in workbook.worksheets for row in sheet.iter_rows(values_only=True)
              for value in row if value is not None]
    assert sum(value == 'SYNTHETIC EXPORT MERCHANT' for value in values) == 1
    assert sum(value == 7200 for value in values) == 1
    assert sum(value == 'OTHER_EXPENSE' for value in values) == 1
    assert store.conn.execute('SELECT COUNT(*) FROM board_rows WHERE row_id=?',
                              (manual_row_id,)).fetchone()[0] == 1
    workbook.close()


def test_trip_metadata_stale_http_edit_preserves_saved_state(service):
    store = service.server.card_store
    created = store.create_trip(
        starts_on='2026-05-01', ends_on='2026-05-31',
        destination='Synthetic metadata conflict trip',
        display_key='Synthetic metadata original',
        client_request_id='autonomous-trip-meta-conflict-create')
    tab_id = created['tab_id']
    current = store.get_trip(tab_id)
    page_code, page_html, _ = service.request(
        '/trips?state=previous', cookie=service.cookie(OWNER))
    assert page_code == 200, page_html[:500]
    assert f"name='display_key' value='{current['display_key']}'" in page_html

    # Save permitted metadata through the real authenticated HTTP endpoint.
    saved_code, saved_body, _ = json_post(service, f'/api/trips/{quote(tab_id)}/meta', {
        'expected_revision': current['revision'],
        'client_request_id': 'autonomous-trip-meta-conflict-first-save',
        'display_key': 'Synthetic metadata accepted',
        'prepared_by_name': 'Synthetic metadata owner',
    })
    assert saved_code == 200, saved_body
    saved = store.get_trip(tab_id)
    assert saved['revision'] == current['revision'] + 1
    assert saved['display_key'] == 'Synthetic metadata accepted'
    assert saved['prepared_by_name'] == 'Synthetic metadata owner'

    snapshot_before_stale = service.snapshot.read_bytes()

    def database_rows():
        names = [row[0] for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND name != 'rule_process_leases' ORDER BY name")]
        return {name: sorted(store.conn.execute(f'SELECT * FROM "{name}"').fetchall(), key=repr)
                for name in names}

    database_before_stale = database_rows()
    history_before_stale = store.conn.execute(
        'SELECT revision, prev_json, new_json FROM trip_tab_history WHERE tab_id=? ORDER BY revision',
        (tab_id,)).fetchall()
    requests_before_stale = store.conn.execute(
        'SELECT client_request_id FROM trip_tab_requests WHERE tab_id=? ORDER BY client_request_id',
        (tab_id,)).fetchall()
    stale_code, stale_body, _ = json_post(service, f'/api/trips/{quote(tab_id)}/meta', {
        'expected_revision': current['revision'],
        'client_request_id': 'autonomous-trip-meta-conflict-stale-save',
        'display_key': 'Synthetic stale title',
        'prepared_by_name': 'Synthetic stale owner',
    })
    assert stale_code == 409, stale_body
    assert database_rows() == database_before_stale
    assert store.get_trip(tab_id) == saved
    assert store.conn.execute(
        'SELECT revision, prev_json, new_json FROM trip_tab_history WHERE tab_id=? ORDER BY revision',
        (tab_id,)).fetchall() == history_before_stale
    assert store.conn.execute(
        'SELECT client_request_id FROM trip_tab_requests WHERE tab_id=? ORDER BY client_request_id',
        (tab_id,)).fetchall() == requests_before_stale
    assert service.snapshot.read_bytes() == snapshot_before_stale


def test_trip_metadata_conflict_keeps_browser_draft_and_latest_saved_value(service):
    from playwright.sync_api import sync_playwright

    store = service.server.card_store
    trip = store.create_trip(starts_on='2026-05-01', ends_on='2026-05-31',
                             destination='Synthetic conflict trip',
                             display_key='Synthetic original',
                             client_request_id='browser-conflict-create')
    tab_id = trip['tab_id']
    base = f'http://127.0.0.1:{service.port}'
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        try:
            context.add_cookies([{'name': google_oidc.COOKIE_NAME,
                                  'value': service.cookie(OWNER), 'url': base}])
            page = context.new_page()
            page.goto(f'{base}/trips?state=previous')
            row = page.locator(f'[id="manage-{tab_id}"]')
            row.locator('.trip-meta > summary').click()
            form = row.locator('form').first
            for field, label in (('display_key', '표시 이름'), ('prepared_on', '작성일'),
                                 ('prepared_by_name', '담당자')):
                assert form.locator(f'[name={field}]').evaluate(
                    '(input, expected) => Array.from(input.labels).some(label => label.textContent.includes(expected))',
                    label)
            revision = int(form.locator('[name=expected_revision]').input_value())
            code, body, _ = json_post(service, f'/api/trips/{quote(tab_id)}/meta', {
                'expected_revision': revision, 'client_request_id': 'browser-conflict-concurrent',
                'display_key': 'Synthetic latest', 'prepared_by_name': 'Latest owner',
            })
            assert code == 200, body
            latest = store.get_trip(tab_id)
            form.locator('[name=display_key]').fill('Synthetic draft')
            form.locator('[name=prepared_on]').fill('2026-05-02')
            form.locator('[name=prepared_by_name]').fill('Draft owner')
            with page.expect_response(lambda response: '/meta' in response.url and response.status == 409):
                form.locator('button[type=submit]').click()
            assert page.get_by_text('EDIT_CONFLICT', exact=False).is_visible()
            assert page.locator('input[name=display_key][readonly]').input_value() == 'Synthetic draft'
            assert page.locator('input[name=prepared_on][readonly]').input_value() == '2026-05-02'
            assert page.locator('input[name=prepared_by_name][readonly]').input_value() == 'Draft owner'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert store.get_trip(tab_id) == latest
        finally:
            context.close()
            browser.close()


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


def test_unprepared_quarter_copy_stays_rejected_without_writes(service):
    board = service.server.card_store
    raw = make_xlsx([domestic_row(merchant='SYNTHETIC UNPREPARED CAFE', amount=5100,
                                  approval='SYN-UNPREPARED-001', issuer='SYNTHETIC ISSUER')])
    from webapp.card_flow import CardFlow
    batch = CardFlow(board).pipeline.receive(raw, 'synthetic-unprepared.xlsx')['batch_id']
    before_changes = board.conn.total_changes
    before_snapshot = service.snapshot.read_bytes()
    code, body, _ = service.request(
        f'/api/imports/{batch}/google-tsv?tab=quarter:2026:2', cookie=service.cookie(OWNER))
    assert code == 400 and json.loads(body)['code'] == 'QUARTER_SHEET_NOT_READY'
    assert board.conn.total_changes == before_changes
    assert service.snapshot.read_bytes() == before_snapshot


@pytest.mark.parametrize(('legacy', 'canonical'), [
    ('no_item', 'classification'),
    ('no_trip', 'classification'),
    ('protected', 'evidence'),
    ('other_review', 'classification'),
])
def test_import_cleanup_keeps_legacy_filter_bookmarks(service, legacy, canonical):
    code, _, headers = service.request(
        '/import?cleanup_reason=' + quote(legacy), cookie=service.cookie(OWNER))
    assert code == 302
    target = f'/cards/all?cleanup_reason={canonical}&legacy_cleanup=1'
    assert headers.get('Location') == target
    page_code, body, _ = service.request(target, cookie=service.cookie(OWNER))
    assert page_code == 200, body[:500]
    assert '거래 확인 업무는 내 확인 필요에서 처리합니다.' in body
    assert "href='/my-actions'" in body

    invalid_code, _, _ = service.request(
        '/import?cleanup_reason=unknown', cookie=service.cookie(OWNER))
    duplicate_code, _, _ = service.request(
        '/import?cleanup_reason=no_item&cleanup_reason=no_trip',
        cookie=service.cookie(OWNER))
    assert invalid_code == 400
    assert duplicate_code == 400


def test_browser_home_trip_export_download(service):
    """A signed owner selects a trip from home and downloads its actual workbook."""
    from playwright.sync_api import sync_playwright
    from openpyxl import load_workbook

    store = service.server.card_store
    trip = store.create_trip(starts_on='2026-04-01', ends_on='2026-04-30',
        destination='Synthetic export trip', display_key='Synthetic export trip',
        client_request_id='browser-export-trip')
    tab = trip['tab_id']
    current = store.get_trip(tab)
    status, body, _ = json_post(service, f'/api/trips/{tab}/meta', {
        'expected_revision': current['revision'], 'client_request_id': 'browser-export-owner',
        'prepared_by_name': 'Synthetic owner'})
    assert status == 200, body
    status, body, _ = json_post(service, '/api/expenses/manual', {
        'amount_krw': '7200', 'occurred_on': '2026-04-10', 'pay_method': '현금',
        'item': 'OTHER_EXPENSE', 'description': 'SYNTHETIC EXPORT MERCHANT',
        'display_tab_id': tab, 'client_request_id': 'browser-export-expense'})
    assert status == 200, body
    base = f'http://127.0.0.1:{service.port}'
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
            context.add_cookies([{'name': google_oidc.COOKIE_NAME, 'value': service.cookie(OWNER), 'url': base}])
            page = context.new_page()
            page.goto(base + '/')
            page.locator("nav[aria-label='주요 메뉴'] a[href='/board']").click()
            history = page.locator('#previous-trips')
            history.locator(':scope > summary').click()
            quarter = history.locator('.prev-q').filter(has=page.locator(f"a[href*='tab={tab}']"))
            quarter.locator(':scope > summary').click()
            history.locator(f"a[href*='tab={tab}']").click()
            assert f'tab={tab}' in page.url
            page.get_by_role('link', name='XLSX 출력', exact=True).click()
            assert page.locator(f"input[name=tab_ids][value='{tab}']").is_checked()
            with page.expect_download(timeout=30000) as received:
                page.get_by_role('button', name='출력', exact=True).click()
            download = received.value
            assert download.failure() is None
            workbook = load_workbook(BytesIO(download.path().read_bytes()), read_only=True, data_only=True)
            try:
                assert workbook.sheetnames == ['Synthetic export trip']
                rows = list(workbook['Synthetic export trip'].iter_rows(values_only=True))
                matches = [row for row in rows if row[3] == 'SYNTHETIC EXPORT MERCHANT']
                assert len(matches) == 1
                assert matches[0][2] == 'OTHER_EXPENSE'
                assert matches[0][7] == 7200
            finally:
                workbook.close()
        finally:
            browser.close()
