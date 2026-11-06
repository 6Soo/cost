from copy import deepcopy

from webapp import ledger_board as board, ledger_design as design
from webapp.google_ledger_page import fmt_google_amount


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
    assert body.count("<th scope='col'>구분</th>") == 0
    assert body.count("<th scope='col'>이용일</th>") == 2
    assert "c-note" not in body and '>메모</th>' not in body
    assert "class='move-row' data-move-for='waiting'" in body
    assert "action='/api/rows/waiting/save'" in body
    for name in ('csrf', 'expected_revision', 'client_request_id', 'display_tab_id'):
        assert f"name='{name}'" in body
    assert "colspan='5'" in body
    assert row == before
    assert 'Preserved note' not in body
    assert '수입 내역이 없어요' not in body and '수입 (COST 기록)' not in body
    mobile = design._mobile_html([], [row], selected='', unclassified=True)
    assert '수입 내역이 없어요' not in mobile and '<span>수입</span>' not in mobile
    assert "data-id='waiting'" in mobile


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
    dated = [dict(rows[0], occurred_on='2026-04-06'), dict(rows[4], occurred_on='2026-04-07'),
             dict(rows[1], occurred_on='2026-04-01'), dict(rows[2], occurred_on='')]
    assert [r['row_id'] for r in design._sort_expenses_for_display(dated)] == ['food','local','air','stay-b']


def test_merchant_first_reservation_sub_no_duplicate_descriptions():
    row = expense('assigned', '교통비', display_tab_id='trip-syn')
    before = deepcopy(row)
    cell = design._party_cell(row)
    # Merchant first, reservation appears in sub as '예약번호 ...'
    assert cell.index('Synthetic merchant') < cell.index('예약번호 SYN-123')
    assert 'Synthetic stay' in cell
    # Sub should contain reservation, not duplicate description as separate line
    sub = design._row_party_sub(row)
    assert '예약번호 SYN-123' in sub
    # Description may still appear in sub when merchant and description differ; just assert no raw reservation as main
    mobile = design._mobile_html([], [row], selected='', unclassified=False)
    assert mobile.index('Synthetic merchant') < mobile.index('예약번호 SYN-123')
    # Mobile displays reservation and merchant; both present, order handled by layout
    # Income fallback preserved
    income = dict(row, row_kind='income', customer_name='Synthetic customer')
    assert design._row_party_main(income) == 'Synthetic stay'
    # No reservation: merchant/description stays main
    no_reservation = dict(row, reservation_no='')
    assert design._row_party_main(no_reservation) == 'Synthetic merchant'
    assert design._row_party_sub(no_reservation) == 'Synthetic stay'
    assert design._row_party_sub(dict(income, source_merchant='', nickname='Synthetic nickname')) == 'Synthetic nickname'
    # Source merchant missing -> description fallback
    no_merchant = dict(row, source_merchant='')
    assert design._row_party_main(no_merchant) == 'Synthetic stay'
    assert row == before


def test_amount_format_integer_decimal_negative_empty_non_digit():
    # Integer with commas, decimal preserved, negative preserved, empty preserved
    assert fmt_google_amount(420000.0) == '420,000'
    assert fmt_google_amount(-420000.0) == '-420,000'
    assert fmt_google_amount(420000.5) == '420,000.5'
    assert fmt_google_amount('') == ''
    assert fmt_google_amount(None) == ''
    # Non-digit text escaped, original unchanged content preserved (escape via board.esc)
    assert fmt_google_amount('test') == 'test'
    assert fmt_google_amount('<script>&') == '&lt;script&gt;&amp;'
    assert fmt_google_amount('12,34') == '12,34'
    assert fmt_google_amount('NaN') == 'NaN'
    assert fmt_google_amount('Infinity') == 'Infinity'
    assert fmt_google_amount('1,234.50') == '1,234.5'
    assert fmt_google_amount('12345678901234567890.123') == '12,345,678,901,234,567,890.123'
    # Verify no float-rounding mutation of source: format from string to avoid float error
    assert fmt_google_amount('420000.0') == '420,000'


def test_party_cell_escapes_non_digit_text():
    row = dict(row_kind='expense', item='숙박비', occurred_on='2026-10-01',
               amount_krw=1200, description='<script>', source_merchant='A & B',
               reservation_no='R-1', row_id='esc')
    cell = design._party_cell(row)
    assert '<script>' not in cell
    # Escaped form preserved
    assert '&amp;' in cell


def test_screen_order_uses_lodging_service_start_and_keeps_unknown_dates_last(monkeypatch):
    periods = {
        'late': '2026-11-09 ~ 2026-11-10',
        'early': '2026-11-01 ~ 2026-11-02',
        'same': '2026-11-01 ~ 2026-11-03',
        'invalid': '2026-02-30 ~ 2026-03-01',
        'reversed': '2026-11-08 ~ 2026-11-01',
        'long': '2026-01-01 ~ 2028-01-01',
    }
    monkeypatch.setattr(design, '_stay_period', lambda row: periods.get(row['row_id'], ''))
    rows = [expense('food', '식비'), expense('late', '숙박비'),
            expense('air-b', '항공료'), expense('unknown', '숙박비'),
            expense('early', '숙박비'), expense('other', '기타경비'),
            expense('same', '숙박비'), expense('air-a', '항공권'),
            expense('invalid', '숙박비'), expense('reversed', '숙박비'),
            expense('long', '숙박비')]
    before = deepcopy(rows)
    expected = ['air-b', 'air-a', 'early', 'same', 'late', 'unknown',
                'invalid', 'reversed', 'long', 'food', 'other']
    assert [r['row_id'] for r in design._group_expenses_for_display(rows)] == expected
    assert rows == before
    assert design._group_expenses_for_display([]) == []


def test_screen_order_resolves_the_same_lodging_evidence_as_the_date_label(monkeypatch):
    monkeypatch.setattr(design, '_ledger_stay_index', lambda: {'synthetic': {}})
    from webapp import ledger_stay_evidence
    monkeypatch.setattr(ledger_stay_evidence, 'period_for', lambda row, index: '2026-10-02 ~ 2026-10-03')
    inferred = expense('card-synthetic', '숙박비')
    stored = expense('stored', '숙박비', service_period='2026-10-05 ~ 2026-10-06')
    before = deepcopy([stored, inferred])
    assert design._group_expenses_for_display([stored, inferred]) == [inferred, stored]
    assert [stored, inferred] == before
