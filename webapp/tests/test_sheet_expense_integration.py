"""Cross-module contracts: real sheet projection, matcher, persistence and HTTP."""
import json
from http.server import ThreadingHTTPServer
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app import google_authority as ga
from app.sheet_expense_links import load_links
from webapp import access_control, ledger_board, ledger_design
from webapp import sheet_expense_reconciliation as reconciliation
from webapp import sheet_expense_review as review
from webapp.ledger_store import LedgerStore
from webapp.tests.test_sheet_expense_projection import (
    Board, TRIP_ID, GOOGLE_KEY, _cost, sources,
)
from webapp.tests.test_sheet_expense_review import FakeHandler


@pytest.fixture
def integrated(sources, monkeypatch):
    board = Board()
    costs = [_cost(), {**_cost('new'), 'merchant': 'Different Shop', 'amount_krw': 7000,
                       'already_booked': True}]
    monkeypatch.setattr(reconciliation, '_cost_preview_rows', lambda *_: costs)
    monkeypatch.setattr(review, '_active_board', lambda: board)
    monkeypatch.setattr(review, '_owner_request', lambda: True)
    return board, costs, sources


def _preview():
    handler = FakeHandler()
    review.dispatch(handler, type('URL', (), {'path': review.API_PATH})(),
                    query={'trip': [TRIP_ID]})
    assert handler.response[0] == 200
    return handler.response[1]


def _export(payload, **updates):
    body = dict(action='export', trip_id=TRIP_ID, request_id='export:integration',
                expected_revision=payload['links_revision'], preview_digest=payload['preview_digest'])
    body.update(updates)
    handler = FakeHandler('POST')
    review.dispatch(handler, type('URL', (), {'path': review.API_PATH})(),
                    raw=json.dumps(body).encode(), csrf='csrf-synthetic')
    return handler.response


def test_real_preview_save_reload_replay_and_cost_change(integrated):
    board, costs, snapshot = integrated
    before = snapshot.read_bytes()
    preview = _preview()
    assert preview['counts']['MATCHED_MANUAL'] == 1
    assert preview['results'][0]['merchant'] == 'Synthetic Cafe'
    assert preview['results'][0]['card'] == '•••• 1234'
    assert preview['links_revision'] == 0
    status, result = _export(preview)
    assert status == 200, result
    assert result['row_count'] == 1 and 'Different Shop' in result['tsv']
    assert 'Synthetic Cafe' not in result['tsv']
    links_path = snapshot.with_name('manual-expense-links.json')
    saved = links_path.read_bytes()
    assert load_links(links_path)['revision'] == 1
    assert _preview()['counts']['MATCHED_EXISTING'] == 1
    status, replay = _export(preview)
    assert status == 200 and replay['replayed'], replay
    assert links_path.read_bytes() == saved
    costs[1]['amount_krw'] = 8000
    status, refused = _export(preview)
    assert status == 409 and 'tsv' not in refused
    assert links_path.read_bytes() == saved and snapshot.read_bytes() == before


def test_real_sheet_move_then_delete_revalidates_saved_link(integrated):
    board, costs, snapshot = integrated
    assert _export(_preview())[0] == 200
    path = ga._rows_file(snapshot.with_name('google-rows.json'), 'generation-a')
    document = json.loads(path.read_text(encoding='utf-8'))
    document['sources']['main']['trips'][GOOGLE_KEY]['expense'][0]['row'] = 25
    path.write_text(json.dumps(document), encoding='utf-8')
    moved = _preview()
    assert moved['counts']['MATCHED_EXISTING'] == 1
    assert moved['results'][0]['row_number'] == 25
    document['sources']['main']['trips'][GOOGLE_KEY]['expense'] = []
    path.write_text(json.dumps(document), encoding='utf-8')
    deleted = _preview()
    assert deleted['counts']['REVIEW_CONFLICT'] == 1
    assert deleted['results'][0]['reason'] == 'EXISTING_LINK_STALE'


def test_actual_board_row_shape_reaches_tsv_and_missing_ids_fail_closed(integrated, monkeypatch):
    board, _, snapshot = integrated
    expense = {'row_id': 'board-new', 'source_event_id': 'source-new', 'row_kind': 'expense',
               'display_tab_id': TRIP_ID, 'occurred_on': '2026-10-11',
               'source_merchant': 'Receipt Shop', 'item': '식비', 'amount_krw': 4000,
               'evidence_type': '영수증'}
    monkeypatch.setattr(ledger_design, '_is_trip_tab', lambda _: True)
    monkeypatch.setattr(ledger_design, '_selected_rows', lambda *_: ([], [expense], [], [expense]))
    monkeypatch.setattr(ledger_board, '_active_store', lambda: board)
    exported = ledger_design.tsv_for_trip_expenses(TRIP_ID)
    assert exported['row_count'] == 1 and 'Receipt Shop' in exported['tsv']
    invalid = reconciliation.export_for_trip(board, [{'amount_krw': 100}], TRIP_ID)
    assert not invalid['source_available'] and not invalid['tsv']


def test_source_changes_between_export_and_final_check_return_no_tsv(integrated, monkeypatch):
    preview = _preview()
    original = review._export_for_trip

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        integrated[1][1]['amount_krw'] = 9999
        return result

    monkeypatch.setattr(review, '_export_for_trip', mutate)
    status, result = _export(preview)
    assert status == 409 and 'tsv' not in result
    assert not integrated[2].with_name('manual-expense-links.json').exists()


def test_real_http_owner_csrf_and_viewer_boundary(sources, tmp_path, monkeypatch):
    store = LedgerStore(tmp_path / 'http.sqlite')
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner('sdd-owner')
    access.create_account(user_id='sdd-viewer', role=access_control.ROLE_VIEWER)
    trip = {**store.list_trips()[0], 'tab_id': TRIP_ID}
    monkeypatch.setattr(store, 'list_trips', lambda **_: [trip])
    monkeypatch.setattr(reconciliation, '_cost_preview_rows', lambda *_: [_cost()])
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), ledger_board.Handler)
    server.card_store = store
    server.store_lock = threading.RLock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(user=None, body=None, csrf=True, path=review.API_PATH):
        headers = {}
        if user:
            headers[access_control.SyntheticSessionAdapter.HEADER] = user
        if body is not None:
            headers['Content-Type'] = 'application/json'
            if csrf:
                headers['X-CSRF-Token'] = ledger_board.CSRF_TOKEN
        request = urllib.request.Request(
            f'http://127.0.0.1:{server.server_address[1]}' + path + '?trip=' + TRIP_ID,
            data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode()

    try:
        assert call()[0] in (401, 403)
        assert call('sdd-viewer')[0] == 403
        code, raw = call('sdd-owner')
        assert code == 200, raw
        preview = json.loads(raw)
        assert preview['counts']['MATCHED_MANUAL'] == 1
        body = dict(action='export', trip_id=TRIP_ID, request_id='export:http',
                    expected_revision=preview['links_revision'], preview_digest=preview['preview_digest'])
        assert call('sdd-viewer', body)[0] == 403
        assert call('sdd-owner', body, csrf=False)[0] == 403
        code, raw = call('sdd-owner', body)
        assert code == 200, raw
        assert json.loads(raw)['matched_count'] == 1
        assert call('sdd-owner', path=review.PAGE_PATH)[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        ledger_board.bind_store(None)
        ledger_board.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        store.close()


def test_actual_copy_javascript_sends_link_revision_and_keeps_board_scope():
    from playwright.sync_api import sync_playwright
    calls = []
    with sync_playwright() as api:
        browser = api.chromium.launch()
        page = browser.new_page()
        page.route('https://synthetic.test/board**', lambda route: route.fulfill(
            content_type='text/html', body="<main id='main'><section class='trip-copy-wrap'>"
            "<button id='copy-trip-expenses' data-tab='trip-synthetic' data-csrf='token'>Copy</button>"
            "<span class='copy-status'></span></section></main>"))

        def endpoint(route):
            if route.request.method == 'GET':
                route.fulfill(json={'source_available': True, 'links_revision': 7,
                                    'revision': {'generation': 'different-shape'}, 'preview_digest': 'digest'})
            else:
                calls.append(route.request.post_data_json)
                assert route.request.headers['x-csrf-token'] == 'token'
                route.fulfill(json={'tsv': 'synthetic-tsv', 'row_count': 1, 'held': [], 'total_krw': 1000})

        page.route('https://synthetic.test/api/google-ledger/expense-reconciliation**', endpoint)
        page.goto('https://synthetic.test/board?q=Cafe&kind=ex')
        page.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:async t=>window.copied=t}})")
        page.add_script_tag(path=str(Path(ledger_design.__file__).parent / 'static/js/ledger_design.js'))
        page.click('#copy-trip-expenses')
        page.wait_for_function("window.copied==='synthetic-tsv'")
        assert calls[0]['expected_revision'] == 7
        assert calls[0]['request_id'].startswith('export:')
        assert calls[0]['scope'] == 'board' and calls[0]['query'] == 'Cafe'
        assert calls[0]['kind'] == 'ex'
        browser.close()
