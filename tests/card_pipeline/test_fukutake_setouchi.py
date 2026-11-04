from types import SimpleNamespace

import pytest

from app.automatic_classification import infer_trip
from app.classify import classify_transaction
from app.provisional_assignment import card_trip_candidates
from app.trip_selection import fukutake_trips
from webapp.card_trip_authority import retail_trip


TRIPS = [dict(trip_id=key, tab_id=key, display_key=name, destination=destination,
              starts_on=start, ends_on=end) for key, name, destination, start, end in (
    ('old', '0501_세토우치', '세토우치', '2026-05-01', '2026-05-06'),
    ('sejong', '0912_세종', '세종', '2026-09-12', '2026-09-14'),
    ('near', '0918_세토우치', '세토우치', '2026-09-18', '2026-09-23'),
    ('next', '0401_세토우치', '세토우치', '2027-04-01', '2027-04-06'))]
ROW = dict(merchant='FUKUTAKE FOUNDATION', approval_date='2026-09-13',
           transaction_direction='purchase', card_kind='해외', card_tail='8835',
           amount_krw=129440, trip_id='sejong', display_tab_id='sejong')


@pytest.mark.parametrize('day,target', [('2026-09-13', 'near'), ('2026-09-18', 'near'),
                                       ('2026-09-19', 'next'), ('2027-04-07', ''), ('', '')])
def test_nearest_upcoming_setouchi_uses_transaction_date_and_replaces_generic_assignment(day, target):
    row = dict(ROW, approval_date=day, posting_date='2026-09-13')
    assert infer_trip(row, TRIPS)[0] == target
    assert [r['trip_id'] for r in card_trip_candidates(row, TRIPS)] == ([target] if target else [])


def test_invalid_trips_are_excluded_and_merchant_normalization_is_narrow():
    trips = [dict(t, archived=t['trip_id'] == 'near') for t in TRIPS]
    assert infer_trip(dict(ROW, merchant=' fukutake   foundation TOKYO JP'), trips)[0] == 'next'
    assert fukutake_trips(dict(ROW, merchant='OTHER FOUNDATION'), TRIPS) is None
    assert fukutake_trips(dict(ROW, merchant='FUKUTAKE FOUNDATIONX'), TRIPS) is None
    assert infer_trip(ROW, [TRIPS[1]])[0] == ''


def resolver(row, country):
    flow = SimpleNamespace(board=SimpleNamespace(list_trips=lambda: TRIPS), trip_valid=lambda key: key != 'old')
    return retail_trip(flow, row, country, google_nets=lambda: {})


def test_primary_classifier_and_authority_override_generic_dates_and_card3820():
    for tail in ('8835', '3820'):
        result = classify_transaction(dict(ROW, card_tail=tail), rules=[], trip_resolver=resolver,
                                      residual_policy=True)
        assert result['trip_id'] == result['display_tab_id'] == 'near'
        assert result['item'] == '입장료'
        assert result['classification_source'] == 'rule'
        assert 'FUKUTAKE' in result['classification_basis']


def test_manual_decisions_and_refunds_are_not_overridden():
    result = classify_transaction(ROW, rules=[], trip_resolver=resolver,
        prior_decision=dict(item='입장료', trip_id='sejong', display_tab_id='sejong'))
    assert result['trip_id'] == 'sejong'
    for field, value in [('transaction_direction', 'refund'), ('parse_error', 'bad'),
                         ('duplicate_of', 'other'), ('conflict_reason', 'conflict')]:
        assert fukutake_trips(dict(ROW, **{field: value}), TRIPS) is None


def test_primary_classifier_does_not_fall_back_to_an_unrelated_trip_without_future_setouchi():
    result = classify_transaction(dict(ROW, approval_date='2028-01-01'), rules=[], trip_resolver=resolver)
    assert result['trip_id'] == ''
    assert result['display_tab_id'] == 'unclassified'


def test_explicit_fukutake_category_beats_a_legacy_automatic_local_expense_rule():
    from app.normalize import normalize_merchant
    rule = dict(rule_id='synthetic-old',status='active',
                conditions={'merchant_normalized':normalize_merchant(ROW['merchant'])},
                effects={'item':'현지경비'},optional={})
    result=classify_transaction(ROW,rules=[rule],trip_resolver=resolver)
    assert result['item']=='입장료'
    assert result['trip_id']=='near'
    manual=classify_transaction(ROW,rules=[rule],trip_resolver=resolver,
        prior_decision=dict(item='기타경비',trip_id='sejong',display_tab_id='sejong'))
    assert manual['item']=='기타경비' and manual['trip_id']=='sejong'


def test_completion_uses_owner_category_without_overriding_manual_or_refund_items():
    from app.automatic_classification import infer_item
    assert infer_item(dict(ROW,item='현지경비'))[0]=='입장료'
    assert infer_item(dict(ROW,item=''))[0]=='입장료'
    assert infer_item(dict(ROW,item='기타경비',classification_source='user_decision'))[0]=='기타경비'
    assert infer_item(dict(ROW,item='취소·환불',transaction_direction='cancellation'))[0]=='취소·환불'
