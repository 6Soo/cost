import pytest

from app.automatic_classification import _card3820_owner_policy

TRIPS = {'trip-jp': dict(trip_id='trip-jp', destination='도쿄',
                         starts_on='2026-07-01', ends_on='2026-07-10')}


def row(**changes):
    return dict(dict(card_tail='3820', transaction_direction='purchase', transaction_kind='purchase',
                     card_kind='해외', foreign_currency='USD', merchant='SYNTHETIC SHOP',
                     approval_date='2026-07-05', amount_krw=37000), **changes)


def policy(r):
    return _card3820_owner_policy(r, list(TRIPS.values()), _canonical=TRIPS)


def test_overseas_onsite_purchase_still_joins_the_trip():
    result = policy(row())
    assert result['trip_id'] == 'trip-jp'


@pytest.mark.parametrize('merchant', ['SYNTHETIC.COM', 'AI CLAUDE SUB', 'ANTHROPIC* PLAN',
                                      'ALIEXPRESS', 'SYNTHETIC GOTOGATE'])
def test_overseas_online_or_subscription_purchase_goes_to_quarter_residual(merchant):
    result = policy(row(merchant=merchant))
    assert result['trip_id'] == ''
    assert result['display_tab_id'] == 'quarter:2026:3'
    assert result['item'] == '분기 기타비용'
    assert result['source'] == 'owner_card_residual'
