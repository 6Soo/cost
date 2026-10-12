from webapp import ledger_design as design


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
