from types import SimpleNamespace

import pytest

from app import automatic_classification as policy
from app.classify import classify_transaction
from app.rules import transaction_region, normalize_rule
from webapp.card_trip_authority import retail_trip
from webapp.tests.test_automatic_classification_completion import setup


TRIPS = [dict(trip_id='foreign', tab_id='foreign', destination='알펜루트',
              starts_on='2026-10-20', ends_on='2026-10-24'),
         dict(trip_id='domestic', tab_id='domestic', destination='경주',
              starts_on='2026-10-20', ends_on='2026-10-24')]


def transaction(**changes):
    return dict(dict(card_tail='3820', card_kind='해외', foreign_currency='USD',
                     transaction_direction='purchase', transaction_kind='purchase',
                     amount_krw=8355, approval_date='2026-10-24', merchant='SYNTHETIC US',
                     item='현지경비'), **changes)


@pytest.mark.parametrize('country', ['US', 'SG', 'JP', ''])
def test_overseas_country_does_not_limit_trip(country):
    row = transaction(merchant='SYNTHETIC', raw_row={'country': country})
    result = policy._card3820_owner_policy(row, TRIPS)
    assert result['trip_id'] == 'foreign'
    assert result['source'] == 'inference' and 'AUTO_INFERRED' in result['basis']
    flow = SimpleNamespace(board=SimpleNamespace(list_trips=lambda: TRIPS), trip_valid=lambda _: True)
    assert retail_trip(flow, row, country or 'overseas', google_nets=lambda: {}) == 'foreign'


def test_overseas_period_end_and_domestic_boundary():
    assert policy._card3820_owner_policy(transaction(approval_date='2026-10-25'), TRIPS) is None
    assert policy._card3820_owner_policy(transaction(), TRIPS[1:]) is None
    assert policy.infer_trip(transaction(), TRIPS)[0] == 'foreign'
    assert policy.infer_trip(transaction(), TRIPS[1:])[0] == ''
    domestic = transaction(merchant='SYNTHETIC', card_kind='국내', foreign_currency='')
    assert transaction_region(domestic) == 'KR'
    assert policy.infer_trip(domestic, TRIPS)[0] == 'domestic'


def test_local_rule_and_category_use_region_with_no_country_code():
    row = transaction(merchant='SYNTHETIC', description_raw='card-category:음식점')
    flow = SimpleNamespace(board=SimpleNamespace(list_trips=lambda: TRIPS), trip_valid=lambda _: True)
    resolver = lambda tx, scope: retail_trip(flow, tx, scope, google_nets=lambda: {})
    result = classify_transaction(row, rules=[], trip_resolver=resolver)
    assert result['trip_id'] == 'foreign'
    for scope in ('local', 'overseas', 'JP'):
        rule = normalize_rule(dict(conditions={'merchant_normalized': 'synthetic'},
                                   optional={'travel_country': scope}, effects={'item': '현지경비'}))
        assert classify_transaction(row, rules=[rule], trip_resolver=resolver)['trip_id'] == 'foreign'
    manual = dict(item='사용자 항목', display_tab_id='domestic', trip_id='domestic')
    assert classify_transaction(row, rules=[], prior_decision=manual, trip_resolver=resolver)['trip_id'] == 'domestic'


def test_3820_parse_errors_and_refunds_remain_protected():
    for changes in ({'parse_error': 'bad'}, {'transaction_direction': 'cancellation'},
                    {'amount_krw': -8355}, {'approval_date': ''}):
        assert policy._card3820_owner_policy(transaction(**changes), TRIPS) is None


def test_existing_foreign_hold_is_completed_atomically_without_financial_writes(setup):
    from tools.complete_card_classification import protected_state
    board, _, _, rows = setup
    conn = board.conn
    tid = rows[0]['transaction_id']
    conn.execute("UPDATE transactions SET card_tail='3820',card_kind='해외',foreign_currency='USD',transaction_kind='purchase',"
                 "approval_date='2026-10-24',classification_source='travel_location_hold',"
                 "item='현지경비',trip_id='',display_tab_id='' WHERE transaction_id=?", (tid,))
    before = protected_state(conn)
    other = conn.execute('SELECT * FROM transactions WHERE transaction_id!=? ORDER BY transaction_id', (tid,)).fetchall()
    preview = policy.plan(conn, TRIPS, transaction_ids=[tid])
    assert len(preview['targets']) == 1
    policy.apply(conn, preview, TRIPS, transaction_ids=[tid])
    assert conn.execute('SELECT classification_state,trip_id FROM transactions WHERE transaction_id=?', (tid,)).fetchone() == ('classified','foreign')
    assert protected_state(conn) == before
    assert other == conn.execute('SELECT * FROM transactions WHERE transaction_id!=? ORDER BY transaction_id', (tid,)).fetchall()
    assert policy.plan(conn, TRIPS, transaction_ids=[tid])['targets'] == []
