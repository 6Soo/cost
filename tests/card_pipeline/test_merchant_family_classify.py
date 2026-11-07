"""가맹점 표기 변형은 포괄하고 결제일만으로 숙박 여행을 정하지 않는다."""

import pytest

from app.classify import classify_transaction
from app.ota_matching_defaults import provider_for_merchant
from ledger.cardindex import account


def transaction(merchant, **changes):
    return dict({'merchant': merchant, 'merchant_normalized': merchant,
                 'approval_date': '2026-10-04', 'transaction_direction': 'purchase',
                 'amount_krw': 66000, 'description_raw': ''}, **changes)


@pytest.mark.parametrize('merchant, item', [
    ('시장할매국밥', '식비'),
    ('시장 할매 국밥', '식비'),
    ('OO손칼국수', '식비'),
    ('명동 김밥', '식비'),
    ('토요코인 대구동성로', '숙박비'),
    ('토요코인호텔-대구 동성로', '숙박비'),
    ('Toyoko Inn Daegu Dongseongro', '숙박비'),
    ('HOTEL FRONT INN FUKUOKA AFukuoka JP', '숙박비'),
    ('MOTOSUPHOENIXHOTEL 0555-20-6800 JP', '숙박비'),
    ('WASHINGTON HOTEL PLAZA TAKAYAMA JP', '숙박비'),
    ('TWIN-LINEHOTEL KARUIZAWA JP', '숙박비'),
    ('YUMOTO KANKO HOTEL SAIKYO Tokyo JP', '숙박비'),
    ('RAKUTENPAY HOTELSOL HOKKAIDO JP', '숙박비'),
    ('(주)파라타항공', '항공료'),
    ('철도승차권 발매', '교통비'),
    ('국립세종수목원', '입장료'),
    ('우리네코다리', '식비'),
])
def test_recognizes_restaurant_suffixes_and_hotel_branch_variations(merchant, item):
    result = classify_transaction(transaction(merchant), rules=[])
    assert result['classification_state'] == 'classified'
    assert result['item'] == item
    assert result['trip_id'] == ''


def test_adventure_korea_is_skyticket_airfare():
    result = classify_transaction(transaction('어드벤처코리아'), rules=[])
    assert result['classification_state'] == 'classified'
    assert result['item'] == '항공료'
    assert result['trip_id'] == ''
    assert provider_for_merchant('어드벤처코리아') == 'skyticket'
    assert account('', '어드벤처코리아', '') == '항공료'


@pytest.mark.parametrize('merchant', ['토요코인 편의점', '국밥거리', '호텔예약확인', '토요코인상사'])
def test_does_not_guess_unrelated_merchants_from_partial_words(merchant):
    result = classify_transaction(transaction(merchant), rules=[])
    assert result['item'] not in ('숙박비', '식비')


def test_hotel_payment_date_is_not_treated_as_stay_even_with_a_trip_resolver():
    calls = []
    result = classify_transaction(transaction('토요코인 대구동성로'), rules=[],
                                  trip_resolver=lambda *_args: calls.append(_args) or 'trip-id')
    assert result['item'] == '숙박비'
    assert result['trip_id'] == '' and calls == []


def test_a_cancelled_card_does_not_get_local_trip_assignment(monkeypatch):
    from app import rules
    monkeypatch.setattr(rules, 'merchant_country', lambda _: 'KR')
    result = classify_transaction(transaction('시장할매국밥', transaction_direction='cancellation'),
                                  rules=[], trip_resolver=lambda *_: 'trip-id')
    assert result['trip_id'] == ''


@pytest.mark.parametrize('merchant,item', [('식당','식비'),('철도승차권 발매','교통비'),('숙소','숙박비')])
def test_item_only_rule_also_resolves_local_use_but_never_service_payment_dates(merchant, item):
    rule = dict(rule_id='item-only',version=1,conditions={'merchant_normalized':merchant},
                effects={'item':item},optional={})
    tx = transaction(merchant, card_kind='국내')
    result = classify_transaction(tx,rules=[rule],trip_resolver=lambda *_:'verified-trip')
    assert result['trip_id'] == ('verified-trip' if item=='식비' else '')
    rule['effects']['display_tab_id']='unclassified'
    explicit = classify_transaction(tx,rules=[rule],trip_resolver=lambda *_:'verified-trip')
    assert explicit['trip_id']=='' and explicit['display_tab_id']=='unclassified'
