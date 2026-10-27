from webapp import ledger_design, google_ledger_page


def test_net_income_label_explains_calculation_and_preserves_values():
    incomes = [{'amount_krw': 10000}]
    expenses = [{'amount_krw': 3000}]
    markup = ledger_design._summary_html(incomes, expenses)
    assert '총수입' in markup and '총수입 − 지출' in markup
    assert '10,000원' in markup and '3,000원' in markup and '7,000원' in markup
    assert '차액' not in markup and '수입, 총수입에서 지출을 뺀 금액' in markup
    filtered = ledger_design._summary_html(incomes, expenses, filtered=(2000, 500, 1, 1), whole=(10000, 3000, 2, 3))
    assert '전체 총수입' in filtered and '검색 결과 총수입' in filtered
    assert '검색 결과 수입' in filtered and '1,500원' in filtered
    unverified = ledger_design._summary_html([], expenses, recorded_income_count=0,
        google_income={'show_rows': False, 'verified': False})
    assert 'net-income' not in unverified and '확인 필요' in unverified


def test_expense_table_keeps_full_service_dates_in_a_dedicated_wrapping_column(monkeypatch):
    monkeypatch.setattr(ledger_design.board, 'current_role', lambda: 'owner')
    row = {'row_id': 'synthetic-expense', 'row_kind': 'expense', 'source_kind': 'manual',
           'amount_krw': 12345, 'item': '숙박비', 'description': '합성 숙소 ' * 30,
           'occurred_on': '2026-06-30', 'service_period': '2026-06-30~2026-07-01'}
    # Verify the actual table markup, including the source period text.
    markup = ledger_design._tables_html([], [row], selected='', unclassified=False)
    assert "width:280px" in markup and "width:28%" in markup
    assert "class='c-stay'" in markup
    assert '6월 30일(화) ~ 7월 1일(수)' in markup
    assert 'text-overflow:clip' in ledger_design.STYLE
