"""에어비앤비·라쿠텐·숲나들e·마이트립 가맹점 별칭이 파서 근거와 어긋나지 않는지 고정한다."""

import pytest

from app.ota_matching_defaults import load_defaults, provider_for_merchant


def test_existing_nine_providers_keep_their_aliases():
    aliases = load_defaults()['provider_merchant_aliases']
    assert aliases['agoda'] == ['agoda', '아고다']
    assert aliases['trip'] == ['trip.com', 'trip.com korea', '트립닷컴', '트립']
    assert aliases['klook'] == ['klook', '클룩']
    assert aliases['booking'] == ['booking.com', 'booking', '부킹닷컴']
    assert aliases['asiana'] == ['아시아나항공', 'flyasiana']
    assert aliases['jeju'] == ['제주항공', 'jejuair', 'jeju air']
    assert aliases['traveloka'] == ['traveloka', '트래블로카']
    assert aliases['skyticket'] == ['skyticket', '스카이티켓', '주식회사 어드벤처코리아', '어드벤처코리아']


@pytest.mark.parametrize('merchant,provider', [
    ('트립닷컴(구)_NICE', 'trip'),
    ('AGODA_NICE-Agoda', 'agoda'),
    ('AGODA.COM', 'agoda'),
    ('BKG*BOOKING.COM HOTEL', 'booking'),
    ('아고다_나이스', 'agoda'),
    ('어드벤처코리아', 'skyticket'),
    ('KLOOK', 'klook'),
    ('부킹닷컴', 'booking'),
    ('아시아나항공', 'asiana'),
    ('제주항공', 'jeju'),
    ('TRAVELOKA', 'traveloka'),
    ('트래블로카', 'traveloka'),
])
def test_measured_card_descriptors_still_resolve(merchant, provider):
    assert provider_for_merchant(merchant) == provider


@pytest.mark.parametrize('merchant,provider', [
    # 운영 실측 28건. 숲나들e 파서가 후보 검색에서 쓰는 표기와 같은 계열이다.
    ('NICE_산림휴양시설-국립진안고원산림치유원', 'forest'),
    ('숲나들e 결제', 'forest'),
    # 운영 실측 10건. 파서의 카드 정규식(공백 있음)과 붙여 쓴 표기를 모두 받는다.
    ('RAKUTENTRAVELKOKUNAISH   TOKYO', 'rakuten'),
    ('RAKUTEN TRAVEL', 'rakuten'),
    ('라쿠텐 트래블', 'rakuten'),
    ('AIRBNB * HMSYNTH001', 'airbnb'),
    ('에어비앤비 예약', 'airbnb'),
])
def test_new_providers_resolve_measured_descriptors(merchant, provider):
    assert provider_for_merchant(merchant) == provider


@pytest.mark.parametrize('merchant', ['MYTRIP', 'MYTRIP KOREA', 'NICE_MYTRIP'])
def test_mytrip_descriptor_resolves_to_the_parser_provider_not_its_own_name(merchant):
    """mytrip 메일 파서는 `provider='gotogate'`를 낸다. 표시 경로도 gotogate 별칭으로 카드를 찾는다."""
    assert provider_for_merchant(merchant) == 'gotogate'


def test_mytrip_dot_com_is_claimed_by_the_longer_trip_com_alias():
    """기존 결함 기록: `trip.com`이 `mytrip.com`의 부분 문자열이라 더 긴 별칭이 먼저 이긴다.

    이번 변경 전에도 같았다(변경 전 정책으로 실행해 확인). 고치려면 별칭 매칭을
    단어 경계로 바꾸는 정책 결정이 필요하므로 여기서는 사실만 고정한다.
    `_descriptor_matches`는 이미 단어 경계를 쓰지만 게이트는 부분 문자열을 쓴다.
    """
    assert provider_for_merchant('MYTRIP.COM') == 'trip'


@pytest.mark.parametrize('merchant', ['GOTOGATE', '이니시스(일반)-고투게이트코리아유'])
def test_mytrip_alias_does_not_displace_the_existing_gotogate_descriptors(merchant):
    assert provider_for_merchant(merchant) == 'gotogate'


@pytest.mark.parametrize('merchant', [
    # 라쿠텐페이 호텔 결제는 라쿠텐 트래블 결제가 아니다. 파서 발신 도메인과 상품이 다르다.
    'RAKUTENPAY HOTELSOL HOKKAIDO JP',
    # 파서가 쓰지 않는 일반 단어. 별칭에 넣으면 일반 상호가 걸린다.
    '시장할매국밥',
    '유스호스텔',
    '힐튼 호텔',
    '토요코인 대구동성로',
    '국립자연휴양림',
])
def test_unrelated_merchants_are_not_taken_for_the_four_providers(merchant):
    assert provider_for_merchant(merchant) is None


def test_forest_and_rakuten_aliases_are_narrower_than_the_bare_english_and_nice_words():
    aliases = load_defaults()['provider_merchant_aliases']
    assert 'forest' not in aliases['forest']
    assert 'rakuten' not in aliases['rakuten']
    assert all(alias.strip() == alias and alias for group in aliases.values() for alias in group)
