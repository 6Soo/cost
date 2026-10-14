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
