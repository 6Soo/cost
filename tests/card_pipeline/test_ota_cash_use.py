"""OTA 캐시·포인트 사용분: 카드 결제가 같은 예약에 있을 때만 기장하고, 환산 금액과 이용일 규칙을 지킨다."""
from app.ota_cash_use import cash_expense_rows, jpy_to_krw, klook_points, klook_pickup_day, agoda_cash_use

TRIPS = [{"tab_id": "trip-north", "starts_on": "2026-09-27", "ends_on": "2026-10-01"}]


def klook_use(**changes):
    use = {"provider": "klook", "booking_ref": "FBQ214585", "item": "렌터카", "cash_krw": 19835,
           "basis": "자료 원화 금액", "service_start": "2026-09-28", "payment_date": "2026-09-17"}
    return {**use, **changes}


def test_jpy_uses_the_simple_rate_of_100_yen_to_1000_won():
    assert jpy_to_krw(28343) == 283430


def test_klook_points_and_pickup_day_are_read_from_the_mail_layout():
    text = "결제 금액 ₩ 65,865\n합계 ₩ 85,700\n클룩 포인트 -₩ 19,835\n픽업 날짜 및 시간: 2026년 9월 28일 10:00 AM"
    assert klook_points(text) == {"cash_krw": 19835, "card_krw": 65865}
    assert klook_pickup_day(text) == "2026-09-28"


def test_agoda_cash_is_recorded_only_when_a_card_payment_exists():
    record = {"card_last4": "4886", "price_components": [
        {"kind": "agoda_cash", "currency": "JPY", "decimal_text": "-28343"},
        {"kind": "paid_today", "currency": "JPY", "decimal_text": "110417"}]}
    assert agoda_cash_use(record) == {"cash_krw": 283430, "basis": "간편환율 100엔=1,000원", "card_last4": "4886"}
    assert agoda_cash_use({"price_components": [{"kind": "agoda_cash", "currency": "KRW", "decimal_text": "-87881"}]}) is None


def test_cash_part_follows_the_service_date_trip_and_the_card_booking_number():
    rows, skipped = cash_expense_rows([klook_use()], card_linked_refs=[("klook", "FBQ214585")],
                                      trips=TRIPS, review_from="2026-04-01")
    assert skipped == []
    assert rows == [{"display_tab_id": "trip-north", "occurred_on": "2026-09-28", "amount_krw": 19835,
                     "item": "렌터카", "description": "klook FBQ214585 캐시 사용분",
                     "evidence_type": "클룩 포인트", "reservation_no": "FBQ214585",
                     "service_period": "2026-09-28",
                     "memo": "자료 원화 금액; 카드 결제분은 같은 예약번호의 카드 거래"}]


def test_cash_only_cancelled_and_out_of_period_bookings_are_not_recorded():
    rows, skipped = cash_expense_rows(
        [klook_use(), klook_use(booking_ref="CANCEL1"), klook_use(booking_ref="OLD1", service_start="2026-01-05")],
        card_linked_refs=[("klook", "FBQ214585"), ("klook", "CANCEL1"), ("klook", "OLD1")],
        cancelled_refs=[("klook", "CANCEL1")], trips=TRIPS, review_from="2026-04-01")
    assert [row["reservation_no"] for row in rows] == ["FBQ214585"]
    reasons = dict(skipped)
    assert reasons[("klook", "CANCEL1")] == "취소·환불된 예약"
    assert reasons[("klook", "OLD1")] == "기장 기간 밖이거나 날짜 없음"
    rows2, skipped2 = cash_expense_rows([klook_use(booking_ref="ONLYCASH")], card_linked_refs=[],
                                        trips=TRIPS, review_from="2026-04-01")
    assert rows2 == [] and skipped2 == [(("klook", "ONLYCASH"), "같은 예약의 카드 결제가 없어 보관")]
