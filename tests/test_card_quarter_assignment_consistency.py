"""Quarter expense buckets are assigned accounting destinations."""
from webapp.card_transactions import _filter_clause
from webapp.cards_all import _render_month_rows, card_detail_html


def test_unassigned_filter_excludes_quarter_buckets():
    where, params = _filter_clause(unassigned=True, valid_trip_ids=['trip-1'])
    assert 'COST_IS_QUARTER_DESTINATION(' in where
    assert 'trip-1' in params


def test_quarter_card_shows_assigned_destination_despite_trip_validity_flag():
    row = dict(transaction_id='quarter-1', approval_date='2026-06-30',
               merchant='한국도로공사', amount_krw=4800, card_label='국민 3820',
               display_tab_id='quarter:2026:3', trip_id='',
               trip_assignment_valid=False, classification_source='owner_card_residual',
               item='분기 기타비용')
    html = _render_month_rows([row], trip_names={})
    assert '2026년 3분기 기타비용' in html
    assert 'card-all-trip-name unassigned' not in html
    detail = card_detail_html(row)
    assert '자동 분류 · 카드 잔여 비용 규칙' in detail
    assert 'owner_card_residual' not in detail
