import datetime as dt
import hashlib
import json
import sqlite3
import sys
import types

import pytest

from app import google_authority as ga
from webapp import google_ledger_page
from webapp.sheet_expense_reconciliation import _sheet_rows, export_for_trip, preview_for_trip


TRIP_ID = 'cost-trip-a'
GOOGLE_KEY = '0101_TestTrip'
SHEET_ID = 'sheet-main-a'
SOURCE_HASH = hashlib.sha256(b'synthetic sheet source').hexdigest()


class Board:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')

    def list_trips(self):
        return [{'tab_id': TRIP_ID, 'display_key': GOOGLE_KEY, 'deleted': 0}]


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
                                          'D': '식비', 'E': '', 'F': '', 'G': '카드'},
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


def _engine(monkeypatch, statuses):
    module = types.ModuleType('app.sheet_expense_dedup')

    def reconcile(cost_rows, sheet_rows, *, trip_id, source_available=True, existing_links=None):
        results = []
        for index, cost in enumerate(cost_rows):
            sheet = sheet_rows[0] if sheet_rows and statuses[index] == 'MATCHED_MANUAL' else None
            results.append({'transaction_id': cost['transaction_id'], 'status': statuses[index],
                            'sheet_row_key': sheet.get('sheet_row_key') if sheet else None,
                            'basis': ['synthetic'], 'differences': {}, 'reason': ''})
        from collections import Counter
        counts = Counter(statuses)
        return {'results': results, 'counts': {name: counts[name] for name in (
            'MATCHED_MANUAL', 'MATCHED_EXISTING', 'NEW_EXPENSE', 'REVIEW_CONFLICT', 'SOURCE_UNAVAILABLE')}}

    module.reconcile = reconcile
    monkeypatch.setitem(sys.modules, 'app.sheet_expense_dedup', module)


def _cost(transaction_id='tx-a'):
    return {'transaction_id': transaction_id, 'trip_id': TRIP_ID, 'display_tab_id': TRIP_ID,
            'date': '2026-10-10', 'occurred_on': '2026-10-10', 'approval_date': '2026-10-10',
            'merchant': 'Synthetic Cafe', 'item': '식비', 'description': '', 'amount_krw': 12000,
            'currency': 'KRW', 'transaction_direction': 'purchase', 'issuer': 'issuer',
            'card_tail': '1234', 'approval_number': 'approval-a', 'booking_ref': '',
            'service_period': '', 'evidence': 'card'}


def test_fresh_selected_trip_projects_private_expense_rows_without_writes(sources, monkeypatch):
    _engine(monkeypatch, ['MATCHED_MANUAL'])
    board = Board()
    before = list(board.conn.iterdump())
    result = preview_for_trip(board, TRIP_ID, [_cost()])
    assert result['source_available'] is True
    assert result['source_info']['trip_key'] == GOOGLE_KEY
    assert result['source_info']['sheet_id'] == SHEET_ID
    assert result['source_info']['source'] == 'main'
    matched = result['results'][0]
    assert matched['row_number'] == 12
    assert matched['trip_id'] == TRIP_ID and matched['sheet_id'] == SHEET_ID
    assert matched['source'] == 'main' and matched['sheet_fingerprint']
    assert matched['sheet_row_key'] != '12'
    assert list(board.conn.iterdump()) == before
    assert result['counts']['MATCHED_MANUAL'] == 1
    assert not (sources.parent / 'manual-expense-links.json').exists()


def test_sheet_key_survives_row_movement_and_duplicate_rows_are_distinct():
    line = {'date': '2026-10-10', 'payee': 'Synthetic', 'category': '식비',
            'period': '', 'reservation': '', 'evidence': '카드', 'amount': 1000}
    first = _sheet_rows([dict(line, row=12)], trip_id=TRIP_ID, google_key=GOOGLE_KEY,
                        sheet_id=SHEET_ID, source='main')
    moved = _sheet_rows([dict(line, row=17)], trip_id=TRIP_ID, google_key=GOOGLE_KEY,
                        sheet_id=SHEET_ID, source='main')
    duplicates = _sheet_rows([dict(line, row=17), dict(line, row=18)], trip_id=TRIP_ID,
                             google_key=GOOGLE_KEY, sheet_id=SHEET_ID, source='main')
    assert first[0]['sheet_row_key'] == moved[0]['sheet_row_key']
    assert duplicates[0]['sheet_row_key'] != duplicates[1]['sheet_row_key']


def test_stale_or_unselected_source_fails_closed_for_every_cost_row(sources, monkeypatch):
    _engine(monkeypatch, ['NEW_EXPENSE'])
    snapshot = json.loads(sources.read_text(encoding='utf-8'))
    snapshot['sources']['main']['last_ok_at'] = '2020-01-01T00:00:00+09:00'
    sources.write_text(json.dumps(snapshot), encoding='utf-8')
    result = preview_for_trip(Board(), TRIP_ID, [_cost()])
    assert result['source_available'] is False
    assert result['counts']['SOURCE_UNAVAILABLE'] == 1
    assert result['results'][0]['status'] == 'SOURCE_UNAVAILABLE'


def test_user_correction_provenance_is_distinct_from_manual_sheet_match(sources, monkeypatch):
    links = sources.with_name('manual-expense-links.json')
    from app.sheet_expense_links import save_links
    save_links(links, [{'transaction_id': 'tx-a', 'trip_id': TRIP_ID, 'sheet_id': SHEET_ID,
                       'source': 'main', 'sheet_row_key': 'synthetic-key',
                       'sheet_fingerprint': 'synthetic-fingerprint', 'status': 'MATCHED_MANUAL',
                       'basis': ['synthetic'], 'user_override': True, 'link_method': 'owner-review'}],
               expected_revision=0, request_id='correction', source_digest='synthetic')
    _engine(monkeypatch, ['MATCHED_MANUAL'])
    result = preview_for_trip(Board(), TRIP_ID, [_cost()])
    item = result['results'][0]
    assert item['status'] == 'MATCHED_MANUAL'
    assert item['user_corrected'] is True
    assert item['correction_source'] == 'owner-review'


def test_export_reloads_source_and_only_passes_new_expenses_to_tsv(sources, monkeypatch):
    _engine(monkeypatch, ['NEW_EXPENSE', 'MATCHED_MANUAL'])
    rows = [_cost('new'), _cost('manual')]
    result = export_for_trip(Board(), rows, TRIP_ID)
    assert result['source_available'] is True
    assert result['row_count'] == 1 and result['total_krw'] == 12000
    assert result['tsv'].split('\t')[1] == 'Synthetic Cafe'
    assert len(result['matched']) == 1 and result['matched'][0]['transaction_id'] == 'manual'
    assert result['held_results'] == []


@pytest.mark.parametrize(('block', 'reason'), [
    ({'sheet_total': 1000, 'row_sum': 2000, 'verified': False}, 'SOURCE_EXPENSE_TOTAL_MISMATCH'),
    ({'sheet_total': None, 'row_sum': None, 'verified': False}, 'SOURCE_EXPENSE_UNVERIFIED'),
])
def test_unverified_expense_has_specific_cause_and_never_exports(sources, monkeypatch, block, reason):
    def unexpected(*args, **kwargs):
        raise AssertionError('Unverified source must never reach the matching engine')
    import app.sheet_expense_dedup as engine
    monkeypatch.setattr(engine, 'reconcile', unexpected)
    snapshot = json.loads(sources.read_text(encoding='utf-8'))
    snapshot['trips'][0]['copies']['main']['expense'] = block
    sources.write_text(json.dumps(snapshot), encoding='utf-8')
    board = Board()
    before = list(board.conn.iterdump())
    result = preview_for_trip(board, TRIP_ID, [_cost()])
    assert result['source_available'] is False
    assert result['source_info']['reason'] == reason
    from webapp.sheet_expense_review import _public_payload
    from webapp.expense_copy_state import source_message
    assert _public_payload(result, TRIP_ID)['message'] == source_message(reason)
    exported = export_for_trip(board, [_cost()], TRIP_ID)
    assert exported['source_available'] is False and exported['tsv'] == ''
    assert list(board.conn.iterdump()) == before
