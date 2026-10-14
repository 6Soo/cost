"""OTA 캐시·포인트 사용분: 원화 환산이 있으면 그 금액, 없으면 간편환율로 기장하고, 이용일 기준으로 여행을 정한다."""
from app.ota_cash_use import (agoda_cash_use, agoda_mail_cash, cash_expense_rows, jpy_to_krw,
                              klook_points, klook_pickup_day)

TRIPS = [{"tab_id": "trip-north", "starts_on": "2026-09-27", "ends_on": "2026-10-01"},
         {"tab_id": "trip-osaka", "starts_on": "2026-04-20", "ends_on": "2026-04-23"},
         {"tab_id": "trip-aomori", "starts_on": "2026-04-17", "ends_on": "2026-04-23"}]


def use(**changes):
    base = {"provider": "klook", "booking_ref": "FBQ214585", "item": "렌터카", "cash_krw": 19835,
            "basis": "자료 원화 금액", "service_start": "2026-09-28", "payment_date": "2026-09-17"}
    return {**base, **changes}


def test_jpy_uses_the_simple_rate_of_100_yen_to_1000_won():
    assert jpy_to_krw(12312) == 123120


def test_klook_points_and_pickup_day_are_read_from_the_mail_layout():
    text = "결제 금액 ₩ 65,865\n합계 ₩ 85,700\n클룩 포인트 -₩ 19,835\n픽업 날짜 및 시간: 2026년 9월 28일 10:00 AM"
    assert klook_points(text) == {"cash_krw": 19835, "card_krw": 65865}
    assert klook_pickup_day(text) == "2026-09-28"


def test_agoda_portal_cash_is_recorded_with_or_without_a_card_payment():
    with_card = {"card_last4": "4886", "price_components": [
        {"kind": "agoda_cash", "currency": "JPY", "decimal_text": "-28343"},
        {"kind": "paid_today", "currency": "JPY", "decimal_text": "110417"}]}
    cash_only = {"price_components": [{"kind": "agoda_cash", "currency": "KRW", "decimal_text": "-87881"}]}
    assert agoda_cash_use(with_card)["cash_krw"] == 283430
    assert agoda_cash_use(cash_only) == {"cash_krw": 87881, "basis": "자료 원화 금액", "card_last4": None}


def test_agoda_confirmation_mail_gives_the_cash_amount_and_check_in_day():
    text = ("Booking ID: 1718900708 체크인 2026년 4월 20일 (월요일) 15:00 "
            "예약 확정 및 결제 완료 AgodaCash -¥ 12,312 총 금액 ¥ 0")
    found = agoda_mail_cash(text)
    assert found == {"cash_krw": 123120, "basis": "간편환율 100엔=1,000원",
                     "check_in": "2026-04-20", "booking_ref": "1718900708"}


def test_cash_part_is_dated_by_service_day_and_placed_in_the_one_covering_trip():
    rows, skipped = cash_expense_rows([use()], trips=TRIPS, review_from="2026-04-01")
    assert skipped == []
    assert rows == [{"display_tab_id": "trip-north", "occurred_on": "2026-09-28", "amount_krw": 19835,
                     "item": "렌터카", "description": "klook FBQ214585 캐시 사용분",
                     "evidence_type": "클룩 포인트", "reservation_no": "FBQ214585",
                     "service_period": "2026-09-28", "memo": "자료 원화 금액"}]


def test_cash_only_booking_is_recorded_and_goes_unassigned_when_no_single_trip_covers_it():
    rows, _ = cash_expense_rows([use(provider="agoda", booking_ref="1748521808", item="숙박비",
                                     cash_krw=87881, service_start="2026-07-18")],
                                trips=TRIPS, review_from="2026-04-01")
    assert rows[0]["display_tab_id"] == "unclassified" and rows[0]["amount_krw"] == 87881
    rows2, _ = cash_expense_rows([use(provider="agoda", booking_ref="1718900708", service_start="2026-04-20")],
                                 trips=TRIPS, review_from="2026-04-01")
    assert rows2[0]["display_tab_id"] == "unclassified"


def test_cancelled_and_out_of_period_bookings_are_skipped_with_reasons():
    rows, skipped = cash_expense_rows(
        [use(booking_ref="CANCEL1"), use(booking_ref="OLD1", service_start="2026-01-05")],
        cancelled_refs=[("klook", "CANCEL1")], trips=TRIPS, review_from="2026-04-01")
    assert rows == []
    assert dict(skipped) == {("klook", "CANCEL1"): "취소·환불된 예약",
                             ("klook", "OLD1"): "기장 기간 밖이거나 날짜 없음"}
