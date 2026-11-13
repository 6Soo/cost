import pytest

from app.automatic_classification import _card3820_owner_policy
from app.rules import is_online_purchase_for_owner_card

TRIPS = {'trip-jp': dict(trip_id='trip-jp', destination='도쿄', starts_on='2026-07-01', ends_on='2026-07-10')}


def row(**changes):
    return dict(dict(card_tail='3820', transaction_direction='purchase', transaction_kind='purchase',
                     card_kind='해외', foreign_currency='JPY', merchant='SYNTHETIC SHOP',
                     approval_date='2026-07-05', amount_krw=37000), **changes)


def policy(r):
    return _card3820_owner_policy(r, list(TRIPS.values()), _canonical=TRIPS)


@pytest.mark.parametrize('merchant', [
    'SYNTHETIC HOTEL TOKYO', 'SYNTHETIC RYOKAN', 'RAKUTENPAY SYNTHETICSTORE', 'ALIPAY SYNTHETIC TAXI',
    'PAYPAY SYNTHETIC', 'NICE DINING', 'APPLEBEES', 'GOOGLE STATION CAFE', 'TRIPLE CAFE', 'SYNTHETIC.COM CAFE',
    'CLAUDE BAKERY', 'SYNTHETIC SHOP'])
def test_onsite_payment_in_the_trip_country_stays_in_the_trip(merchant):
    result = policy(row(merchant=merchant))
    assert result['trip_id'] == 'trip-jp'
    assert result['source'] == 'inference'


@pytest.mark.parametrize('merchant', [
    'ANTHROPIC* CLAUDE SUB', 'CLAUDE.AI SUBSCRIPTION', 'OPENAI *CHATGPT', 'ALIEXPRESS.COM', 'TEMU.COM',
    'SYNTHETIC GOTOGATE', 'AGODA.COM', 'TRIP.COM', 'KLOOK TRAVEL', 'BOOKING.COM HOTEL', 'GOOGLE *CLOUD',
    'APPLE.COM/BILL', 'PAYPAL *SYNTHETIC'])
def test_subscription_online_mall_and_ota_go_to_quarter_residual(merchant):
    result = policy(row(merchant=merchant, foreign_currency='USD'))
    assert result['trip_id'] == ''
    assert result['display_tab_id'] == 'quarter:2026:3'
    assert result['item'] == '분기 기타비용'
    assert result['source'] == 'owner_card_residual'


def test_category_only_online_in_local_currency_of_the_trip_country_is_onsite():
    category = 'card-category:인터넷상거래'
    shop = row(description_raw=category, merchant='SYNTHETIC SHOP', raw_row={'country': 'JP'})
    assert is_online_purchase_for_owner_card(shop, []) is True
    assert is_online_purchase_for_owner_card(shop, list(TRIPS.values())) is False
    assert policy(shop)['trip_id'] == 'trip-jp'
    assert is_online_purchase_for_owner_card(dict(shop, foreign_currency='USD'), list(TRIPS.values())) is True
