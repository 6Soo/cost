from copy import deepcopy

from webapp import ledger_board as board, ledger_design as design


def expense(row_id, item, **values):
    return dict(row_id=row_id, row_kind='expense', item=item,
                occurred_on='2026-10-01', amount_krw=1200,
                description='Synthetic stay', source_merchant='Synthetic merchant',
                reservation_no='SYN-123', operator_note='Preserved note', **values)


def test_expense_headers_and_move_form_survive_memo_column_removal(monkeypatch):
    monkeypatch.setattr(board, 'live_trips', lambda: [])
    row = expense('waiting', '숙박비')
    before = deepcopy(row)
    body = design._tables_html([], [row], selected='', unclassified=True)
    assert '<tbody class=\'colhead\'><tr><th scope=\'col\'>날짜</th>' in body
    assert body.count("<th scope='col'>구분</th>") == 2
    assert "c-note" not in body and '>메모</th>' not in body
    assert "class='move-row' data-move-for='waiting'" in body
    assert "action='/api/rows/waiting/save'" in body
    for name in ('csrf', 'expected_revision', 'client_request_id', 'display_tab_id'):
        assert f"name='{name}'" in body
    assert "colspan='5'" in body
    assert row == before
    assert 'Preserved note' not in body


def test_expense_display_order_is_stable_and_preserves_original_rows():
    rows = [expense('local', '현지경비'), expense('food', '식비'),
            expense('stay-b', '숙박비'), expense('transit', '여비교통비'),
            expense('air', '항공권'), expense('stay-a', '숙박비'),
            expense('other', '기타비용')]
    before = deepcopy(rows)
    shown = design._sort_expenses_for_display(rows)
    assert [r['row_id'] for r in shown] == [
        'air', 'stay-b', 'stay-a', 'transit', 'food', 'local', 'other']
    assert rows == before
    assert all(any(r is original for original in rows) for r in shown)


def test_reservation_precedes_merchant_on_desktop_and_mobile():
    row = expense('assigned', '숙박비', display_tab_id='trip-syn')
    before = deepcopy(row)
    cell = design._party_cell(row)
    assert cell.index('SYN-123') < cell.index('Synthetic merchant')
    assert 'Synthetic stay' in cell
    mobile = design._mobile_html([], [row], selected='', unclassified=False)
    assert mobile.index('SYN-123') < mobile.index('Synthetic merchant')
    income = dict(row, row_kind='income', customer_name='Synthetic customer')
    assert design._row_party_main(income) == 'Synthetic stay'
    no_reservation = dict(row, reservation_no='')
    assert design._row_party_main(no_reservation) == 'Synthetic stay'
    assert row == before
