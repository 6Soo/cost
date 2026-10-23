"""예약 자료 확인: 같은 금액의 예약 메일 내용을 그대로 보여 준다 (배정은 하지 않는다)."""
from datetime import date

from app import booking_evidence as be

MAIL = ("예약 번호\n1400829364445735\n체크인: 2026년 11월 5일\n체크아웃: 2026년 11월 6일\n"
        "카드사전승인\n149,927원\n이 금액은 객실 확보를 위해 사용되며, 체크아웃 후 돌려드립니다\n"
        "결제는 아피 고겐 모리 노 호텔에서 처리합니다\n")


def test_summary_keeps_the_reservation_stay_amount_and_refund_sentence():
    entry = be.summarize('[예약 확정 안내] 호텔 예약이 확정되었습니다', date(2026, 9, 23), MAIL)
    assert entry['refs'] == ['1400829364445735']
    assert (entry['starts_on'], entry['ends_on']) == ('2026-11-05', '2026-11-06')
    assert 149927 in entry['amounts']
    assert '이 금액은 객실 확보를 위해 사용되며, 체크아웃 후 돌려드립니다' in entry['notes']


def test_lookup_needs_the_same_amount_within_the_window():
    index = {'by_amount': {149927: [be.summarize('예약', date(2026, 9, 23), MAIL)]}, 'count': 1}
    assert len(be.find(index, 149927, '2026-09-23')[0]) == 1
    assert be.find(index, 149927, '2027-09-23')[0] == []
    assert be.find(index, 1234, '2026-09-23')[0] == []
    index['by_amount'][149927] *= 4
    assert len(be.find(index, 149927, '2026-09-23')[0]) == 3
    assert len(be.find(index, 149927, '2026-09-23', limit=None)[0]) == 4


def test_direct_hotel_requires_branch_confirmation_without_refundable_deposit():
    subject = '[예약 확정 안내] 토요코인 대구 동성로 예약이 확정되었습니다'
    good = be.summarize(subject, date(2026, 9, 21),
                        '예약 번호 1400829364445735\n체크인: 2026년 11월 5일\n'
                        '체크아웃: 2026년 11월 6일\n237,500원')
    assert be.matches_direct_hotel(good, '토요코인 대구동성로')
    assert not be.matches_direct_hotel(good, '토요코인 부산')
    assert not be.matches_direct_hotel(good, '토요코인')
    refunded = dict(good, notes=['이 금액은 객실 확보를 위해 사용되며 체크아웃 후 돌려드립니다'])
    assert not be.matches_direct_hotel(refunded, '토요코인 대구동성로')
    assert not be.matches_direct_hotel(good, '토요코인 대구동성로', amount=237500)
    paid = be.summarize(subject, date(2026, 9, 21),
                        '예약 번호 1400829364445735\n체크인: 2026년 11월 5일\n'
                        '체크아웃: 2026년 11월 6일\n237,500원 결제 완료')
    assert be.matches_direct_hotel(paid, '토요코인 대구동성로', amount=237500)
    assert not be.matches_direct_hotel(paid, '토요코인 대구동성로', amount=149927)
    assert be.same_direct_hotel_branch('토요코인 대구 동성로', '토요코인호텔 대구동성로')
    assert not be.same_direct_hotel_branch('토요코인 대구동성로', '토요코인 부산')
    unpaid = be.summarize(subject, date(2026, 9, 21),
                          '예약 번호 1400829364445735\n체크인: 2026년 11월 5일\n'
                          '체크아웃: 2026년 11월 6일\n237,500원 결제 완료 예정')
    assert not be.matches_direct_hotel(unpaid, '토요코인 대구동성로', amount=237500)


def test_payment_completion_cannot_borrow_a_nearby_unrelated_amount():
    subject = '[예약 확정 안내] 토요코인 대구 동성로 예약이 확정되었습니다'
    base = ('예약 번호 1400829364445735\n체크인: 2026년 11월 5일\n'
            '체크아웃: 2026년 11월 6일\n')
    single = be.summarize(subject, date(2026, 9, 21),
                          base + '객실요금 237,500원\n결제 완료')
    assert single['paid_amounts'] == [237500]
    ambiguous = be.summarize(subject, date(2026, 9, 21),
                             base + '객실요금 237,500원\n결제 완료\n보증금 150,000원')
    assert ambiguous['paid_amounts'] == []
    assert not be.matches_direct_hotel(ambiguous, '토요코인 대구동성로', amount=237500)
    explicit = be.summarize(subject, date(2026, 9, 21),
                            base + '객실요금 237,500원 결제 완료\n기타 안내 15,000원')
    assert explicit['paid_amounts'] == [237500]


def test_ref_lookup_finds_cancelled_mail_without_payment_amount():
    reference = '1400829364445735'
    cancelled = be.summarize('토요코인 대구 동성로 예약 취소', date(2026, 10, 25),
                             f'예약 번호 {reference}\n취소되었습니다')
    assert be.find_refs({'by_ref': {reference: [cancelled]}}, [reference]) == [cancelled]


def test_description_keeps_only_the_decision_lines():
    entry = be.summarize('[예약 확정 안내] 토요코인 대구 동성로 예약이 확정되었습니다-NoReply', date(2026, 9, 21), MAIL)
    lines = be.describe(entry)
    assert lines[0] == '토요코인 대구 동성로 · 확정'
    assert '예약번호 1400829364445735' in lines
    assert '이용 2026-11-05 ~ 2026-11-06' in lines
    assert not any('원화 금액' in line for line in lines)


def test_toyoko_seven_digit_reservation_and_nights_remain_unpaid_evidence():
    text = '예약번호: 1234567\n숙박일:2026년 10월 24일 (토) 부터 2 박\n합계금액: 140,000원'
    entry = be.summarize('토요코인 대구 동성로 예약 확인', date(2026, 10, 1), text)
    assert entry['refs'] == ['1234567']
    assert (entry['starts_on'], entry['ends_on']) == ('2026-10-24', '2026-10-26')
    assert entry['paid_amounts'] == []
    assert not be.matches_direct_hotel(entry, '토요코인 대구 동성로', amount=140000)
    assert '예약 확인' in be.describe(entry)[0]
    conflicting = be.summarize('토요코인 예약 확인', None,
                              text + '\n숙박일:2026년 10월 25일 (일) 부터 2 박')
    assert conflicting['starts_on'] == ''
    assert be.summarize('다른 업체 예약 확인', None, text)['refs'] == []
    corporate = be.summarize('토요코인 코퍼레이트 예약 확인', None,
                             text + '\n토요코인 부산해운대2\n합계금액: 12,000엔')
    assert corporate['currency_totals'] == {'KRW': [140000], 'JPY': [12000]}
    assert be.direct_hotel_branch_matches(corporate, '토요코인 부산해운대II')
