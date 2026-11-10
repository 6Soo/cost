"""KPI presentation must use the established COST-first income source."""
import pytest
from webapp import google_ledger_page, ledger_design as design


@pytest.mark.parametrize('cost,google,income,balance,note', [
    ([{'amount_krw': 100}], {'show_rows': True, 'amount': 80, 'count': 2}, '100원', '70원', '수입 1건'),
    ([], {'show_rows': True, 'amount': 80, 'count': 2}, '80원', '50원', '수입 2건'),
    ([{'amount_krw': 100}], {'show_rows': False, 'verified': False}, '100원', '70원', '수입 1건'),
    ([], None, '—', '—', '장부 사본 선택 필요'),
])
def test_kpi_keeps_cost_income_priority_and_uses_google_only_as_fallback(monkeypatch, cost, google, income, balance, note):
    expenses = [{'amount_krw': 30}]
    monkeypatch.setattr(design, '_STORE_missing', lambda: False)
    monkeypatch.setattr(design, '_selected_rows', lambda *_: (cost, expenses, cost, expenses))
    monkeypatch.setattr(design.board, '_shown_amount', lambda row: row['amount_krw'])
    monkeypatch.setattr(google_ledger_page, 'get_trip_income_summary', lambda *_: google)
    markup = design._trip_kpi_html('trip-synthetic')
    assert f'<dt>수입</dt><dd>{income}</dd>' in markup
    assert '<dt>지출</dt><dd>30원</dd>' in markup
    assert f'<dt>차액</dt><dd>{balance}</dd>' in markup
    assert note in markup
