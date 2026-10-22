"""가맹점 표기 변형은 포괄하고 결제일만으로 숙박 여행을 정하지 않는다."""

import pytest

from app.classify import classify_transaction


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
])
def test_recognizes_restaurant_suffixes_and_hotel_branch_variations(merchant, item):
    result = classify_transaction(transaction(merchant), rules=[])
    assert result['classification_state'] == 'classified'
    assert result['item'] == item
    assert result['trip_id'] == ''


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
