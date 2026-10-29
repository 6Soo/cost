"""Quarter expense buckets are assigned accounting destinations."""
import sqlite3

from app.assignment_status import row_assignment, sql_assignment_status
from app.automatic_classification import completion_for_row
from webapp.card_transactions import _filter_clause
from webapp.cards_all import _render_month_rows, card_detail_html


def test_unassigned_filter_excludes_quarter_buckets():
    where, params = _filter_clause(unassigned=True, valid_trip_ids=['trip-1'])
    assert 'COST_ASSIGNMENT_STATUS(display_tab_id,trip_id,?)' in where
    assert '"trip-1"' in params[0]


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
    assert not completion_for_row(quarter_with_stale_trip, valid)['complete']


def test_unassigned_sql_uses_same_verdict_and_preserves_refund_exclusion():
    where, params = _filter_clause(unassigned=True, valid_trip_ids=['trip-a'])
    conn = sqlite3.connect(':memory:')
    conn.create_function('COST_ASSIGNMENT_STATUS', 3, sql_assignment_status)
    conn.create_function('COST_REFUND_TAB_MEMBER', 1, lambda _tid: 0)
    for display, trip, expected in (
            ('quarter:2026:3', 'missing', 0),
            ('quarter:2026:9', 'trip-a', 0),
            ('', 'missing', 1),
            ('', '', 1)):
        got = conn.execute('SELECT 1 FROM (SELECT ? AS transaction_id, ? AS display_tab_id, '
                           '? AS trip_id) WHERE 1' + where,
                           [f'tx-{display}-{trip}', display, trip, *params]).fetchone()
        assert bool(got) is bool(expected)
    conn.create_function('COST_REFUND_TAB_MEMBER', 1, lambda _tid: 1)
    assert conn.execute('SELECT 1 FROM (SELECT ? AS transaction_id, ? AS display_tab_id, '
                        '? AS trip_id) WHERE 1' + where,
                        ['refund', 'quarter:2026:3', 'missing', *params]).fetchone() is None


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
    assert 'STALE_TRIP_DESTINATION' in detail
