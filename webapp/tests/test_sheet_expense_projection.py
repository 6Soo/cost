import datetime as dt
import hashlib
import json
import sqlite3

import pytest

from app import google_authority as ga
from webapp import google_ledger_page
from webapp.sheet_expense_reconciliation import (_sheet_rows, export_for_trip,
    normalize_cost_rows, preview_for_trip)


TRIP_ID = 'cost-trip-a'
GOOGLE_KEY = '0101_TestTrip'
SHEET_ID = ga.SPREADSHEET_IDS['main']
SOURCE_HASH = hashlib.sha256(b'synthetic sheet source').hexdigest()


class Board:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.expenses = []

    def list_trips(self):
        return [{'tab_id': TRIP_ID, 'display_key': GOOGLE_KEY, 'deleted': 0}]

    def _expense_rows(self):
        return self.expenses


def _snapshot():
    now = dt.datetime.now(ga.KST).replace(microsecond=0).isoformat()
    block = {'sheet_total': 1000, 'row_sum': 1000, 'total': 1000, 'verified': True}
    copy = {'sheet': SHEET_ID, 'layout': 'rev', 'flags': [],
            'income': dict(block), 'expense': dict(block)}
    trip = {'key': GOOGLE_KEY, 'tab_id': SHEET_ID, 'closure': 'open', 'closure_current': True,
            'canonical_source': 'main', 'income_total': 0, 'expense_total': 1000,
            'net': None, 'verified': True, 'review': [],
            'copies': {'main': copy, 'archive': None}}
    return {'schema': ga.SCHEMA, 'synced_at': now, 'rows_generation': 'generation-a',
            'sources': {'main': {'status': 'ok', 'error_code': None, 'stale': False,
                                 'last_ok_at': now, 'checked_at': now,
                                 'content_sha256': SOURCE_HASH},
                        'archive': {'status': 'ok', 'error_code': None, 'stale': False,
                                    'last_ok_at': now, 'checked_at': now,
                                    'content_sha256': SOURCE_HASH}},
            'trips': [trip]}


def _rows_doc():
    return {
        'schema': ga.ROWS_SCHEMA, 'generation': 'generation-a', 'synced_at': 'synthetic',
        'sources': {
            'main': {'content_sha256': SOURCE_HASH, 'trips': {
                GOOGLE_KEY: {'income': [], 'expense': [
                    {'row': 12, 'cells': {'B': '2026-10-10', 'C': 'Synthetic Cafe',
                                          'D': 'Food', 'E': '', 'F': '', 'G': 'Card'},
                     'amount': 12000}]}}},
            'archive': {'content_sha256': SOURCE_HASH, 'trips': {}},
        },
    }


@pytest.fixture
def sources(tmp_path, monkeypatch):
    snapshot_path = tmp_path / 'google-snapshot.json'
    rows_path = tmp_path / 'google-rows.json'
    snapshot_path.write_text(json.dumps(_snapshot(), ensure_ascii=False), encoding='utf-8')
    ga._rows_file(rows_path, 'generation-a').write_text(
        json.dumps(_rows_doc(), ensure_ascii=False), encoding='utf-8')
    (tmp_path / 'google-tab-mapping.json').write_text(
        json.dumps({GOOGLE_KEY: TRIP_ID}), encoding='utf-8')
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT', str(snapshot_path))
    monkeypatch.setenv('WEBLEDGER_GOOGLE_LEDGER_ROWS', str(rows_path))
    return snapshot_path


def _cost(transaction_id='tx-a'):
    return {'transaction_id': transaction_id, 'trip_id': TRIP_ID, 'display_tab_id': TRIP_ID,
            'date': '2026-10-10', 'occurred_on': '2026-10-10', 'approval_date': '2026-10-10',
            'merchant': 'Synthetic Cafe', 'item': 'Food', 'description': '', 'amount_krw': 12000,
            'currency': 'KRW', 'transaction_direction': 'purchase', 'issuer': 'issuer',
            'card_tail': '1234', 'approval_number': 'approval-a', 'booking_ref': '',
            'service_period': '', 'evidence': 'card'}


def test_fresh_selected_trip_projects_private_expense_rows_without_writes(sources, monkeypatch):
    board = Board()
    before = list(board.conn.iterdump())
    result = preview_for_trip(board, TRIP_ID, [_cost()])
    assert result['source_available'] is True
    assert result['source_info']['trip_key'] == GOOGLE_KEY
    assert result['source_info']['sheet_id'] == SHEET_ID
    assert result['source_info']['source'] == 'main'
    assert '_sheet_rows' not in result and '_cost_rows' not in result
    matched = result['results'][0]
    assert matched['row_number'] == 12
    assert matched['trip_id'] == TRIP_ID and matched['sheet_id'] == SHEET_ID
    assert matched['source'] == 'main' and matched['sheet_fingerprint']
    assert matched['sheet_row_key'] != '12'
    assert list(board.conn.iterdump()) == before
    assert result['counts']['MATCHED_MANUAL'] == 1
    assert type(result['revision']) is int
    assert result['source_revision']['generation'] == 'generation-a'
    assert not (sources.parent / 'manual-expense-links.json').exists()


def test_sheet_key_survives_row_movement_and_duplicate_rows_are_distinct():
    line = {'date': '2026-10-10', 'payee': 'Synthetic', 'category': 'Food',
            'period': '', 'reservation': '', 'evidence': 'Card', 'amount': 1000}
    first = _sheet_rows([dict(line, row=12)], trip_id=TRIP_ID, google_key=GOOGLE_KEY,
                        sheet_id=SHEET_ID, source='main')
    moved = _sheet_rows([dict(line, row=17)], trip_id=TRIP_ID, google_key=GOOGLE_KEY,
                        sheet_id=SHEET_ID, source='main')
    duplicates = _sheet_rows([dict(line, row=17), dict(line, row=18)], trip_id=TRIP_ID,
                             google_key=GOOGLE_KEY, sheet_id=SHEET_ID, source='main')
    assert first[0]['sheet_row_key'] == moved[0]['sheet_row_key']
    assert first[0]['sheet_fingerprint'] == moved[0]['sheet_fingerprint']
    assert duplicates[0]['sheet_row_key'] == duplicates[1]['sheet_row_key']


def test_sheet_datetime_and_negative_refund_are_normalized():
    projected = _sheet_rows([{'row': 2, 'date': dt.datetime(2026, 10, 10),
        'payee': 'Refund', 'category': 'Item', 'amount': -500}],
        trip_id=TRIP_ID, google_key=GOOGLE_KEY, sheet_id=SHEET_ID, source='main')[0]
    assert projected['date'] == '2026-10-10'
    assert projected['transaction_direction'] == 'refund'


def test_stale_or_unselected_source_fails_closed_for_every_cost_row(sources, monkeypatch):
    snapshot = json.loads(sources.read_text(encoding='utf-8'))
    snapshot['sources']['main']['last_ok_at'] = '2020-01-01T00:00:00+09:00'
    sources.write_text(json.dumps(snapshot), encoding='utf-8')
    result = preview_for_trip(Board(), TRIP_ID, [_cost()])
    assert result['source_available'] is False
    assert result['counts']['SOURCE_UNAVAILABLE'] == 1
    assert result['results'][0]['status'] == 'SOURCE_UNAVAILABLE'


def test_user_correction_provenance_is_distinct_from_manual_sheet_match(sources, monkeypatch):
    links = sources.with_name('manual-expense-links.json')
    sheet = _sheet_rows([{'row': 12, 'date': '2026-10-10', 'payee': 'Synthetic Cafe',
        'category': 'Food', 'period': '', 'reservation': '', 'evidence': 'Card',
        'amount': 12000}], trip_id=TRIP_ID, google_key=GOOGLE_KEY,
        sheet_id=SHEET_ID, source='main')[0]
    links.write_text(json.dumps({'revision': 7, 'links': [{
        'transaction_id': 'tx-a', 'trip_id': TRIP_ID, 'sheet_id': SHEET_ID,
        'source': 'main', 'stable_key': sheet['sheet_row_key'],
        'sheet_row_key': sheet['sheet_row_key'], 'sheet_fingerprint': sheet['sheet_fingerprint'],
        'status': 'MATCHED_EXISTING', 'user_override': True,
        'provenance': {'link_method': 'owner-review'}}], 'history': []}),
        encoding='utf-8')
    result = preview_for_trip(Board(), TRIP_ID, [_cost()])
    item = result['results'][0]
    assert item['status'] == 'MATCHED_EXISTING'
    assert item['user_corrected'] is True
    assert item['correction_source'] == 'owner-review'


def _live_tab(payee='Synthetic Cafe'):
    return {'sheet': GOOGLE_KEY, 'layout': 'rev', 'verified': True,
            'rows': {'expense': [{'row': 12, 'cells': {'B': '2026-10-10', 'C': payee,
                'D': 'Food', 'E': '', 'F': '', 'G': 'Card'}, 'amount': 12000}]}}


def test_export_reloads_semantic_source_and_only_passes_new_expenses_to_tsv(sources, monkeypatch):
    requested = []
    def fetch(url, **kwargs):
        requested.append(url)
        return b'fresh-xlsx'
    monkeypatch.setattr(ga, '_download', fetch)
    monkeypatch.setattr(ga, 'parse_workbook', lambda data, rollover: [_live_tab()])
    rows = [_cost('new') | {'merchant': 'Different merchant', 'date': '2026-10-11',
                            'occurred_on': '2026-10-11', 'amount_krw': 8000}, _cost('manual')]
    result = export_for_trip(Board(), rows, TRIP_ID)
    assert result['source_available'] is True
    assert result['row_count'] == 1 and result['total_krw'] == 8000
    assert result['tsv'].splitlines()[0].split('\t')[1] == 'Different merchant'
    assert len(result['matched']) == 1
    assert result['matched'][0]['transaction_id'] == 'manual'
    assert result['held_results'] == []
    assert len(requested) == 1 and SHEET_ID in requested[0]


def test_export_without_explicit_cost_rows_uses_trip_card_and_receipt_projection(sources, monkeypatch):
    monkeypatch.setattr(ga, '_download', lambda url, **kwargs: b'fresh')
    monkeypatch.setattr(ga, 'parse_workbook', lambda data, rollover: [_live_tab()])
    board = Board()
    board.expenses = [dict(_cost('receipt-a'), transaction_id='', source_event_id='receipt-a',
        row_id='row-a', evidence_type='receipt', display_amount_krw=9000,
        amount_krw=9000, source_merchant='Receipt Vendor', merchant='',
        display_tab_id=TRIP_ID)]
    result = export_for_trip(board, None, TRIP_ID)
    assert result['source_available'] is True
    assert result['row_count'] == 1
    assert result['tsv'].split('\t')[1] == 'Receipt Vendor'
    assert result['tsv'].split('\t')[5] == '영수증'


@pytest.mark.parametrize(('failure', 'reason'), [
    (TimeoutError('synthetic'), 'SOURCE_UNAVAILABLE'),
    (ga.SourceError('SOURCE_ACCESS_DENIED'), 'SOURCE_ACCESS_DENIED'),
])
def test_live_recheck_failure_holds_every_cost(sources, monkeypatch, failure, reason):
    def fail(url, **kwargs):
        raise failure
    monkeypatch.setattr(ga, '_download', fail)
    result = export_for_trip(Board(), [_cost()], TRIP_ID)
    assert result['source_available'] is False
    assert result['reconciliation']['source_info']['reason'] == reason
    assert len(result['held_results']) == 1
    assert result['held_results'][0]['status'] == 'SOURCE_UNAVAILABLE'


def test_live_recheck_semantic_change_fails_closed(sources, monkeypatch):
    monkeypatch.setattr(ga, '_download', lambda url, **kwargs: b'live')
    monkeypatch.setattr(ga, 'parse_workbook', lambda data, rollover: [_live_tab('Different Cafe')])
    result = export_for_trip(Board(), [_cost()], TRIP_ID)
    assert result['source_available'] is False
    assert result['reconciliation']['source_info']['reason'] == 'SOURCE_CHANGED'


def test_adc_recheck_uses_only_configured_authenticated_fetcher(sources, monkeypatch):
    monkeypatch.setenv('WEBLEDGER_GOOGLE_AUTH', 'adc')
    called = []
    def fetcher_factory(*, timeout, max_bytes):
        def fetch(url):
            called.append(url)
            return b'private-readonly'
        return fetch
    import app.google_adc_export as adc
    monkeypatch.setattr(adc, 'authorized_export_fetcher', fetcher_factory)
    monkeypatch.setattr(ga, '_download', lambda *args, **kwargs: pytest.fail('public fallback'))
    monkeypatch.setattr(ga, 'parse_workbook', lambda data, rollover: [_live_tab()])
    result = export_for_trip(Board(), [_cost()], TRIP_ID)
    assert result['source_available'] is True
    assert len(called) == 1 and SHEET_ID in called[0]


def test_normalize_board_expenses_preserves_receipt_and_stable_source_identity():
    rows = normalize_cost_rows(None, [dict(_cost(), transaction_id='', source_event_id='event-a',
        row_id='row-a', evidence_type='receipt', display_amount_krw=-20,
        amount_krw=-20, occurred_on='2026-10-10', display_tab_id=TRIP_ID,
        source_merchant='Supplier', service_period='stay')], TRIP_ID)
    assert rows[0]['transaction_id'] == 'event-a'
    assert rows[0]['merchant'] == 'Supplier'
    assert rows[0]['evidence'] == 'receipt'
    assert rows[0]['service_period'] == 'stay'
