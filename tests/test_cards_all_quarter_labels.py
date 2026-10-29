"""Card history must distinguish accounting buckets from missing assignments."""
from webapp.cards_all import _classification_source_label, _render_month_rows, card_detail_html


def _row(**extra):
    row = dict(transaction_id='test-quarter', use_date='2026-06-30',
               approval_date='2026-06-30', merchant='한국도로공사',
               amount_krw=4800, card_label='국민 · 3820',
               display_tab_id='quarter:2026:3', trip_id='',
               trip_assignment_valid=False, classification_source='owner_card_residual',
               item='분기 기타비용')
    row.update(extra)
    return row


def test_quarter_bucket_visible_even_when_not_valid_real_trip():
    html = _render_month_rows([_row()], trip_names={})
    assert '2026년 3분기 기타비용' in html
    assert 'card-all-trip-name unassigned' not in html


def test_raw_internal_source_is_not_shown_in_details():
    html = card_detail_html(_row())
    assert '자동 분류 · 카드 잔여 비용 규칙' in html
    assert 'owner_card_residual' not in html


def test_unknown_source_does_not_expose_internal_identifier():
    assert _classification_source_label('internal_future_source') == '자동 분류 · 기타 근거'
