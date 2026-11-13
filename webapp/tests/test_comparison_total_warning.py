import json

import pytest

from webapp import expense_amount_group_service as service
from webapp.expense_amount_group_ui import render_summary
from webapp.ledger_design import _tables_html
from webapp.sheet_expense_reconciliation import export_for_trip
from webapp.tests.test_sheet_expense_projection import Board, TRIP_ID, _cost, sources


@pytest.mark.parametrize('failure', ['', 'missing', 'wrong_sum', 'invalid_amount', 'legacy'])
def test_sum_formula_warning_allows_only_complete_valid_rows(sources, failure):
    snapshot = json.loads(sources.read_text(encoding='utf-8'))
    trip = snapshot['trips'][0]
    trip['review'] = ['TOTAL_MISMATCH', 'TOTAL_RANGE_MISMATCH']
    copy = trip['copies']['main']
    copy['flags'] = list(trip['review'])
    copy['expense'] = {'verified': False, 'sheet_total': 0, 'total': 0, 'row_sum': 12000}
    if failure == 'missing':
        copy['expense']['row_sum'] = None
    elif failure == 'wrong_sum':
        copy['expense']['row_sum'] = 12001
    elif failure == 'invalid_amount':
        copy['flags'].append('AMOUNT_MISSING')
    elif failure == 'legacy':
        copy['layout'] = 'nonstandard'
    sources.write_text(json.dumps(snapshot), encoding='utf-8')
    board = Board()
    board.current_role = lambda: 'owner'
    trips = board.list_trips()
    board.list_trips = lambda include_archived=False: trips
    try:
        state = service.build_state(board, TRIP_ID, cost_rows=[_cost()])
        if failure:
            assert state['available'] is False
            assert state['groups'] == []
            if failure == 'legacy':
                assert state['reason'] == 'SOURCE_LAYOUT_UNSUPPORTED'
        else:
            assert state['available'] is True, state
            assert state['total_warning'] is True
            assert state['groups'][0]['status'] == 'matched'
            assert '시트 합계 수식을 확인해 주세요' in render_summary(state)
            markup = _tables_html([], [], selected='', unclassified=False, amount_groups=state)
            assert "class='gemn-total-warning'" in markup
            assert '개별 지출 행 기준 비교' in markup
        # Read-only count comparison never authorizes a new-row export.
        result = export_for_trip(board, [_cost()], TRIP_ID)
        assert result['row_count'] == 0
        assert result['source_available'] is False
    finally:
        board.conn.close()
