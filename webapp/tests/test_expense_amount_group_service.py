from types import SimpleNamespace

import pytest

from webapp import expense_amount_group_service as service


def test_non_owner_returns_without_reading_source(monkeypatch):
    called = []
    monkeypatch.setattr(service.sheet_expense_reconciliation, 'preview_for_trip',
                        lambda *args, **kwargs: called.append(True))
    state = service.build_state(SimpleNamespace(current_role=lambda: 'viewer'), 'trip-a')
    assert state['available'] is False
    assert state['reason'] == 'OWNER_REQUIRED'
    assert state['groups'] == [] and state['by_cost_id'] == {}
    assert called == []


def test_invalid_trip_stops_before_source_read(monkeypatch):
    called = []
    monkeypatch.setattr(service.sheet_expense_reconciliation, 'preview_for_trip',
                        lambda *args, **kwargs: called.append(True))
    state = service.build_state(SimpleNamespace(current_role=lambda: 'owner'), 'unclassified')
    assert state['reason'] == 'COST_TRIP_UNAVAILABLE'
    assert called == []


def test_amount_parser_accepts_exact_signed_integer_only():
    assert service._amount('-1,250') == -1250
    assert service._amount(0) == 0
    for value in (True, None, '1.2', 'NaN', float('inf'), 'unknown', '1,2',
                  9007199254740994.0):
        try:
            service._amount(value)
        except ValueError as error:
            assert str(error) == 'AMOUNT_UNCERTAIN'
        else:
            raise AssertionError(f'accepted uncertain amount: {value!r}')


@pytest.mark.parametrize('archived', [False, True])
def test_build_loads_whole_rows_preserves_board_ids_and_detail(monkeypatch, archived):
    captured = {}
    trip = {'tab_id': 'trip-a', 'archived': archived}
    board = SimpleNamespace(current_role=lambda: 'owner',
        list_trips=lambda include_archived=False: [trip] if include_archived or not archived else [],
        store=SimpleNamespace(conn=SimpleNamespace(execute=lambda *a: [])))
    monkeypatch.setattr(service.sheet_expense_reconciliation, '_cost_preview_rows',
                        lambda *args: [
                            {'row_id': 'board-row-1', 'source_event_id': 'event-1',
                             'display_tab_id': 'trip-a', 'display_amount_krw': 500,
                             'currency': 'KRW', 'description': 'Coffee',
                             'source_merchant': 'Cafe', 'display_occurred_on': '2026-10-01'},
                            {'row_id': 'board-row-2', 'source_event_id': 'event-2',
                             'display_tab_id': 'trip-a', 'display_amount_krw': 500,
                             'currency': 'KRW', 'description': 'Meal',
                             'source_merchant': 'Diner', 'display_occurred_on': '2026-10-02'},
                        ])
    monkeypatch.setattr(service.google_ledger_page, 'enabled', lambda: True)
    monkeypatch.setattr(service.google_ledger_page, 'snapshot_path', lambda: __import__('pathlib').Path('snapshot.json'))
    monkeypatch.setattr(service.google_ledger_page, 'rows_path', lambda: __import__('pathlib').Path('rows.json'))
    monkeypatch.setattr(service.google_authority, 'load_consistent', lambda *a: ({
        'rows_generation': 'gen', 'synced_at': '2026-10-30T10:00:00+09:00',
        'sources': {'main': {'content_sha256': 'a' * 64, 'status': 'ok', 'stale': False,
                             'last_ok_at': '2026-10-30T10:00:00+09:00'}}},
        {'main': {'content_sha256': 'a' * 64, 'trips': {'google-a': {}}}}))
    monkeypatch.setattr(service.google_ledger_page, 'load_mapping', lambda *a: {'google-a': 'trip-a'})
    monkeypatch.setattr(service.google_ledger_page, 'load_choices', lambda *a: {})
    monkeypatch.setattr(service.google_ledger_page, 'owner_payload', lambda *a: {
        'trips': [{'key': 'google-a', 'chosen_source': 'main',
                   'copies': {'main': {'sheet': 'sheet-1', 'layout': 'rev',
                                       'expense': {'verified': True}}}}],
        'sources': {'main': {'status': 'ok', 'stale': False,
                             'last_ok_at': '2026-10-30T10:00:00+09:00'}}})
    monkeypatch.setattr(service.google_ledger_page, 'snapshot_for_display', lambda s: s)
    monkeypatch.setattr(service.google_ledger_page, 'owner_rows', lambda *a: {'expense': [
        {'row': 12, 'amount': 500, 'date': '2026-10-03', 'payee': 'Hotel',
         'category': 'Stay', 'evidence': 'card'},
        {'row': 13, 'amount': 500, 'date': '2026-10-04', 'payee': 'Taxi',
         'category': 'Ride', 'evidence': 'cash'},
    ]})

    from app.expense_amount_groups import reconcile_expense_amount_groups
    original_core = reconcile_expense_amount_groups

    def capture_core(trip_id, costs, google, **kwargs):
        captured.update(trip_id=trip_id, costs=costs, google=google, kwargs=kwargs)
        return original_core(trip_id, costs, google, **kwargs)

    monkeypatch.setattr('app.expense_amount_groups.reconcile_expense_amount_groups', capture_core)
    state = service.build_state(board, 'trip-a')
    assert state['available'] is True, state
    assert len(captured['costs']) == 2
    assert [row['row_id'] for row in captured['costs']] == ['board-row-1', 'board-row-2']
    assert [row['source_identity'] for row in captured['costs']] == ['event-1', 'event-2']
    assert captured['costs'][0]['date'] == '2026-10-01'
    assert captured['costs'][0]['payee'] == 'Cafe'
    assert captured['google'][0]['ref']
    assert captured['google'][0]['row_number'] == 12
    assert [r['row_number'] for r in state['groups'][0]['google_rows']] == [12, 13]
    assert captured['google'][0]['payee'] == 'Hotel'
    assert len(captured['google']) == 2
    assert captured['kwargs']['available'] is True
    assert state['groups'][0]['candidate_count'] == 4
    assert state['by_cost_id']['board-row-1']['status'] == 'matched'


def test_unavailable_source_fails_closed(monkeypatch):
    monkeypatch.setattr(service.sheet_expense_reconciliation, '_store_and_trip',
                        lambda *args: (SimpleNamespace(), {'tab_id': 'trip-a'}))
    monkeypatch.setattr(service.sheet_expense_reconciliation, '_cost_preview_rows', lambda *a: [])
    monkeypatch.setattr(service.google_ledger_page, 'enabled', lambda: False)
    state = service.build_state(SimpleNamespace(current_role=lambda: 'owner'), 'trip-a')
    assert state['available'] is False
    assert state['reason'] == 'GOOGLE_SOURCE_DISABLED'
    assert state['groups'] == []


def test_duplicate_source_projection_keeps_board_aliases_and_conflicts_fail_closed(monkeypatch):
    monkeypatch.setattr(service.sheet_expense_reconciliation, '_store_and_trip',
                        lambda *args: (SimpleNamespace(), {'tab_id': 'trip-a'}))
    monkeypatch.setattr(service.google_ledger_page, 'enabled', lambda: False)
    monkeypatch.setattr(service.google_ledger_page, 'enabled', lambda: True)
    monkeypatch.setattr(service.google_ledger_page, 'snapshot_path',
                        lambda: __import__('pathlib').Path('snapshot.json'))
    monkeypatch.setattr(service.google_ledger_page, 'rows_path',
                        lambda: __import__('pathlib').Path('rows.json'))
    snapshot = {'rows_generation': 'g', 'synced_at': '2026-10-30T10:00:00+09:00',
                'sources': {'main': {'status': 'ok', 'stale': False,
                                     'content_sha256': 'b' * 64,
                                     'last_ok_at': '2026-10-30T10:00:00+09:00'}}}
    rows = {'main': {'content_sha256': 'b' * 64, 'trips': {'g-trip': {}}}}
    monkeypatch.setattr(service.google_authority, 'load_consistent', lambda *a: (snapshot, rows))
    monkeypatch.setattr(service.google_ledger_page, 'snapshot_for_display', lambda value: value)
    monkeypatch.setattr(service.google_ledger_page, 'load_mapping', lambda *a: {'g-trip': 'trip-a'})
    monkeypatch.setattr(service.google_ledger_page, 'load_choices', lambda *a: {})
    monkeypatch.setattr(service.google_ledger_page, 'owner_payload', lambda *a: {
        'trips': [{'key': 'g-trip', 'chosen_source': 'main', 'copies': {'main': {
            'sheet': 's', 'layout': 'rev', 'expense': {'verified': True}}}}],
        'sources': {'main': {'status': 'ok', 'stale': False,
                             'last_ok_at': '2026-10-30T10:00:00+09:00'}}})
    monkeypatch.setattr(service.google_ledger_page, 'owner_rows', lambda *a: {'expense': [
        {'row': 2, 'amount': 500, 'payee': 'Hotel', 'category': 'Stay'}]})
    base = {'display_tab_id': 'trip-a', 'display_amount_krw': 500}
    board = SimpleNamespace(current_role=lambda: 'owner')
    state = service.build_state(board, 'trip-a', cost_rows=[
        {**base, 'row_id': 'r1', 'source_event_id': 'event-1'},
        {**base, 'row_id': 'r2', 'source_event_id': 'event-1'},
    ])
    assert state['available'] is True
    assert state['groups'][0]['cost_count'] == 1
    assert state['by_cost_id']['r1']['status'] == 'matched'
    assert state['by_cost_id']['r2']['status'] == 'matched'

    conflict = service.build_state(board, 'trip-a', cost_rows=[
        {**base, 'row_id': 'r1', 'source_event_id': 'event-1'},
        {**base, 'row_id': 'r2', 'source_event_id': 'event-1',
         'display_amount_krw': 501},
    ])
    assert conflict['available'] is False
    assert conflict['groups'] == []
