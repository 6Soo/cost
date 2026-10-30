from types import SimpleNamespace

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
    for value in (True, None, '1.2', 'NaN', float('inf'), 'unknown'):
        try:
            service._amount(value)
        except ValueError as error:
            assert str(error) == 'AMOUNT_UNCERTAIN'
        else:
            raise AssertionError(f'accepted uncertain amount: {value!r}')


def test_build_uses_whole_rows_with_board_ids_and_ignores_legacy_results(monkeypatch):
    captured = {}
    preview = {
        'source_available': True,
        'cost_rows': [],
        'sheet_rows': [
            {'sheet_row_key': 'g1', 'amount_krw': 500, 'currency': 'KRW'},
            {'sheet_row_key': 'g2', 'amount_krw': 500, 'currency': 'KRW'},
        ],
        'results': [{'transaction_id': 'c1', 'status': 'NEW_EXPENSE'}],
        'revision': {'synced_at': '2026-10-30T10:00:00+09:00'},
    }
    monkeypatch.setattr(service.sheet_expense_reconciliation, 'preview_for_trip',
                        lambda *args, **kwargs: preview)

    def reconcile(trip_id, costs, google, **kwargs):
        captured.update(trip_id=trip_id, costs=costs, google=google, kwargs=kwargs)
        return {'available': True, 'reason': '', 'last_success_at': kwargs['last_success_at'],
                'groups': [{'group_id': 'trip-a:500', 'trip_id': 'trip-a',
                            'amount_krw': 500, 'status': 'matched', 'cost_count': 2,
                            'google_count': 2, 'candidate_count': 4,
                            'cost_rows': ['board-row-1', 'board-row-2'],
                            'google_rows': ['g1', 'g2']}],
                'by_cost_id': {'board-row-1': {'group_id': 'trip-a:500', 'status': 'matched'},
                               'board-row-2': {'group_id': 'trip-a:500', 'status': 'matched'}},
                'summary': {'matched': 1, 'partial': 0, 'unrecorded': 0,
                            'google_only': 0, 'unavailable': 0}}

    import sys
    import types
    core = types.ModuleType('app.expense_amount_groups')
    core.reconcile_expense_amount_groups = reconcile
    monkeypatch.setitem(sys.modules, 'app.expense_amount_groups', core)
    board = SimpleNamespace(current_role=lambda: 'owner')
    whole = [
        {'row_id': 'board-row-1', 'source_event_id': 'event-1',
         'display_tab_id': 'trip-a', 'display_amount_krw': 500, 'currency': 'KRW'},
        {'row_id': 'board-row-2', 'source_event_id': 'event-2',
         'display_tab_id': 'trip-a', 'display_amount_krw': 500, 'currency': 'KRW'},
    ]
    state = service.build_state(board, 'trip-a', cost_rows=whole)
    assert len(captured['costs']) == 2
    assert [row['row_id'] for row in captured['costs']] == ['board-row-1', 'board-row-2']
    assert [row['source_identity'] for row in captured['costs']] == ['event-1', 'event-2']
    assert len(captured['google']) == 2
    assert captured['kwargs']['available'] is True
    assert state['groups'][0]['candidate_count'] == 4


def test_unavailable_source_fails_closed(monkeypatch):
    monkeypatch.setattr(service.sheet_expense_reconciliation, 'preview_for_trip',
                        lambda *args, **kwargs: {'source_available': False,
                                                 'source_info': {'reason': 'TRIP_MAPPING_UNAVAILABLE'}})
    state = service.build_state(SimpleNamespace(current_role=lambda: 'owner'), 'trip-a')
    assert state['available'] is False
    assert state['reason'] == 'TRIP_MAPPING_UNAVAILABLE'
    assert state['groups'] == []
