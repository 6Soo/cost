from webapp import ledger_design as design
import pytest


def test_empty_local_income_does_not_compete_with_google_income():
    body = design._summary_html([], [], recorded_income_count=0)
    assert '>수입</i>' not in body and '>차액</i>' not in body
    assert '지출 0건' in body


def test_expense_search_preserves_whole_and_result_totals():
    body = design._summary_html([], [], recorded_income_count=0,
                                filtered=(0, 100, 0, 1), whole=(0, 300, 0, 2))
    assert '전체 지출' in body and '300원' in body
    assert '검색 결과 지출' in body and '100원' in body


def test_existing_local_income_is_still_visible():
    body = design._summary_html([{'amount_krw': 1000}], [], recorded_income_count=1)
    assert '>수입</i>' in body and '1,000원' in body


@pytest.mark.parametrize('numeric_gap,verified,status', [
    (True, True, '합계 차이 있음'),
    (True, False, '합계 차이 있음'),
    (False, False, '확인 필요'),
])
@pytest.mark.parametrize('search', [False, True])
def test_google_income_warning_preserves_expense_scope_without_balance(numeric_gap, verified, status, search):
    body = design._summary_html(
        [], [{'amount_krw': 100 if search else 300}], recorded_income_count=0,
        filtered=(0, 100, 0, 1) if search else None,
        whole=(0, 300, 0, 2) if search else None,
        google_income={'show_rows': False, 'numeric_gap': numeric_gap,
                       'verified': verified, 'amount': 9999, 'count': 9})
    assert status in body
    assert '300원' in body
    assert '차액' not in body and '9,999원' not in body
    if search:
        assert '전체 지출' in body and '검색 결과 지출' in body
        assert '100원' in body
        assert '전체 지출 2건 · 검색 결과 지출 1건' in body
    else:
        assert '검색 결과' not in body and '지출 1건' in body
