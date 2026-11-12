"""Owner decision 2026-11-12: ordinary gaps end in the payment quarter."""
import pytest

from app.automatic_classification import _card3820_owner_policy, infer_trip
from app.trip_selection import canonical_trip_periods, period_or_preparation
from webapp.card_trip_authority import retail_trip


TRIPS = [dict(trip_id='previous', tab_id='previous', destination='도쿠시마', starts_on='2026-10-10', ends_on='2026-10-13'),
         dict(trip_id='oze', tab_id='oze', destination='오제', starts_on='2026-10-15', ends_on='2026-10-20'),
         dict(trip_id='alpine', tab_id='alpine', destination='알펜루트', starts_on='2026-10-20', ends_on='2026-10-24'),
         dict(trip_id='karuizawa', tab_id='karuizawa', destination='가루이자와', starts_on='2026-10-26', ends_on='2026-10-30')]


@pytest.mark.parametrize('item', ['숙박비', '교통비', '식비', '항공료', '기타경비', '현지경비'])
@pytest.mark.parametrize('day,target', [('2026-10-14', 'oze'), ('2026-10-25', 'karuizawa')])
def test_all_costs_in_a_gap_prefer_next_trip_over_an_equally_close_previous_trip(item, day, target):
    row = dict(approval_date=day, item=item, foreign_currency='JPY', transaction_direction='purchase',
               card_tail='3820', transaction_kind='purchase', amount_krw=1000)
    identity, basis = infer_trip(row, TRIPS)
    assert identity == '' and 'PROC-004' in basis
    owner = _card3820_owner_policy(row, TRIPS)
    assert owner is None  # Shared completion falls through to the observed quarter.


def test_preparation_preserves_existing_destination_and_does_not_extend_the_last_trip():
    assert infer_trip(dict(approval_date='2026-10-14', trip_id='previous'), TRIPS)[0] == 'previous'
    assert period_or_preparation(TRIPS, '2026-10-31') == ([], False)
    assert period_or_preparation(TRIPS, '') == ([], False)
    assert period_or_preparation(TRIPS, '2026-10-13') == ([TRIPS[0]], False)


def test_domestic_preparation_uses_domestic_next_trip_and_keeps_the_3820_residual_exception():
    domestic = [dict(trip_id='domestic-before', destination='양평', starts_on='2026-10-10', ends_on='2026-10-13'),
                dict(trip_id='domestic-next', destination='부산', starts_on='2026-10-16', ends_on='2026-10-20')]
    row = dict(approval_date='2026-10-14', card_kind='국내', item='식비')
    target, basis = infer_trip(row, domestic + TRIPS)
    assert target == '' and 'PROC-004' in basis
    owner = _card3820_owner_policy(dict(row,card_tail='3820',transaction_direction='purchase',
                                       transaction_kind='purchase',amount_krw=1000), domestic + TRIPS)
    assert owner['display_tab_id'] == 'quarter:2026:4'


def test_open_periods_same_start_and_flags_keep_their_authority_contract():
    rows = [dict(trip_id='a', starts_on='2026-10-01'), dict(trip_id='b', starts_on='2026-10-01'),
            dict(trip_id='c', starts_on='2026-10-05'),
            dict(trip_id='bad', starts_on='2026-10-03', flags=['PERIOD_DATE_INVALID'])]
    valid = canonical_trip_periods(rows)
    assert set(valid) == {'a', 'b', 'c'}
    assert valid['a']['ends_on'] == valid['b']['ends_on'] == '2026-10-04'
    assert not rows[0].get('ends_on')


@pytest.mark.parametrize('day,target', [('2026-10-14', 'oze'), ('2026-10-25', 'karuizawa')])
def test_primary_retail_resolver_uses_the_same_preparation_rule(day, target):
    class Board:
        def list_trips(self):
            return TRIPS

    class Flow:
        board = Board()

        def trip_valid(self, identity):
            return identity in {'previous', 'oze', 'alpine', 'karuizawa'}

    assert retail_trip(Flow(), dict(approval_date=day, foreign_currency='JPY'), 'overseas', google_nets=lambda: {}) == ''
