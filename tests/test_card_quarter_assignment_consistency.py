"""Quarter expense buckets are assigned accounting destinations."""
import sqlite3

from app.assignment_status import assignment_conflict_label, row_assignment, sql_assignment_status
from app.automatic_classification import completion_for_row
from webapp.card_transactions import _filter_clause
from webapp.cards_all import _render_month_rows, card_detail_html


def test_legacy_unassigned_filter_is_accepted_without_classification_filtering():
    where, params = _filter_clause(unassigned=True, valid_trip_ids=['trip-1'])
    assert (where, params) == ('', [])


def test_effective_destination_and_conflicts_are_separate_for_all_cases():
    cases = [
        ({'display_tab_id': 'quarter:2026:3', 'trip_id': ''}, 'quarter:2026:3', 'ASSIGNED', []),
        ({'display_tab_id': 'quarter:2026:3', 'trip_id': 'missing'}, 'quarter:2026:3',
         'ASSIGNED', ['DESTINATION_CONFLICT', 'STALE_TRIP_DESTINATION']),
        ({'display_tab_id': 'trip-b', 'trip_id': 'trip-a'}, 'trip-b', 'ASSIGNED',
         ['DESTINATION_CONFLICT']),
        ({'display_tab_id': 'quarter:2026:9', 'trip_id': 'trip-a'}, 'trip-a', 'ASSIGNED',
         ['DESTINATION_CONFLICT', 'STALE_DISPLAY_DESTINATION']),
        ({'display_tab_id': 'quarter:2026:9', 'trip_id': ''}, 'quarter:2026:9', 'UNASSIGNED', []),
        ({'display_tab_id': '', 'trip_id': 'missing'}, 'missing', 'UNASSIGNED', []),
        ({'display_tab_id': '', 'trip_id': ''}, '', 'UNASSIGNED', []),
    ]
    valid = {'trip-a', 'trip-b'}
    for row, destination, status, conflicts in cases:
        verdict = row_assignment(row, valid)
        assert (verdict['destination'], verdict['status'], verdict['conflicts']) == (
            destination, status, conflicts)
        assert sql_assignment_status(row.get('display_tab_id'), row.get('trip_id'),
                                    '["trip-a","trip-b"]') == status

    quarter_with_stale_trip = {
        'transaction_id': 'synthetic-quarter-conflict',
        'transaction_direction': 'purchase', 'transaction_kind': '승인',
        'classification_state': 'classified', 'classification_source': 'inference',
        'item': '기타경비', 'display_tab_id': 'quarter:2026:3',
        'trip_id': 'missing',
    }
    assert row_assignment(quarter_with_stale_trip, valid)['status'] == 'ASSIGNED'
    assert not completion_for_row(quarter_with_stale_trip, {key: {'tab_id': key} for key in valid})['complete']


def test_legacy_unassigned_sql_keeps_all_source_rows_including_refunds():
    where, params = _filter_clause(unassigned=True, valid_trip_ids=['trip-a'])
    conn = sqlite3.connect(':memory:')
    conn.create_function('COST_ASSIGNMENT_STATUS', 3, sql_assignment_status)
    conn.create_function('COST_REFUND_TAB_MEMBER', 1, lambda _tid: 0)
    for display, trip, expected in (
            ('quarter:2026:3', 'missing', 1),
            ('quarter:2026:9', 'trip-a', 1),
            ('', 'missing', 1),
            ('', '', 1)):
        got = conn.execute('SELECT 1 FROM (SELECT ? AS transaction_id, ? AS display_tab_id, '
                           '? AS trip_id) WHERE 1' + where,
                           [f'tx-{display}-{trip}', display, trip, *params]).fetchone()
        assert bool(got) is bool(expected)
    conn.create_function('COST_REFUND_TAB_MEMBER', 1, lambda _tid: 1)
    assert conn.execute('SELECT 1 FROM (SELECT ? AS transaction_id, ? AS display_tab_id, '
                        '? AS trip_id) WHERE 1' + where,
                        ['refund', 'quarter:2026:3', 'missing', *params]).fetchone() == (1,)


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
    assert '<dt>분류 출처</dt><dd>자동</dd>' in detail
    assert 'owner_card_residual' not in detail


def test_card_row_and_detail_use_effective_quarter_but_show_stale_trip_conflict():
    row = dict(transaction_id='quarter-conflict', approval_date='2026-06-30',
               merchant='한국도로공사', amount_krw=4800,
               display_tab_id='quarter:2026:3', trip_id='missing',
               trip_assignment_valid=False, item='분기 기타비용')
    html = _render_month_rows([row], trip_names={})
    detail = card_detail_html(row)
    assert '2026년 3분기 기타비용' in html
    assert 'card-all-trip-name unassigned' not in html
    assert '2026년 3분기 기타비용' in detail
    assert '저장된 여행 배정을 확인해야 합니다' in detail
    assert 'STALE_TRIP_DESTINATION' not in detail


def test_legacy_card_row_fallback_uses_quarter_without_trip_name_context():
    row = {'transaction_id': 'legacy-trip', 'approval_date': '2026-06-30',
           'trip_id': 'opaque-trip-id', 'merchant': '상점', 'amount_krw': 1}
    html = _render_month_rows([row])
    assert '2026년 3분기 기타비용' in html
    assert 'opaque-trip-id' not in html
    assert row['trip_id'] == 'opaque-trip-id'
    assert 'card-all-trip-name unassigned' not in html


def test_unknown_assignment_conflicts_do_not_leak_internal_identifiers():
    label = assignment_conflict_label(['DESTINATION_CONFLICT', 'new_internal_reason'])
    assert 'DESTINATION_CONFLICT' not in label
    assert 'new_internal_reason' not in label
    assert '여행 배정 값이 서로 다릅니다' in label
