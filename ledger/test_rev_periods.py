import unittest

from rev_periods import (
    fill_unique_item_periods,
    resolve_item_period,
    resolve_period,
    split_content,
)


class SplitContentTests(unittest.TestCase):
    def test_one_way_flight_uses_departure_date(self):
        self.assertEqual(split_content("항공_0408_김정화 김원복"), ("항공_김정화 김원복", "0408"))

    def test_round_trip_flight_uses_departure_and_arrival(self):
        self.assertEqual(split_content("항공_0404_0407_김효정"), ("항공_김효정", "0404_0407"))

    def test_legacy_expense_suffix_is_normalized(self):
        self.assertEqual(split_content("숙박비_0502_0503"), ("숙박", "0502_0503"))

    def test_travel_insurance_period_is_separated(self):
        self.assertEqual(split_content("여행자보험_0413_0416"), ("여행자보험", "0413_0416"))

    def test_rental_uses_pickup_and_return_dates(self):
        self.assertEqual(split_content("렌터카_0509_0510"), ("렌트", "0509_0510"))

    def test_rental_does_not_accept_pickup_date_only(self):
        self.assertEqual(split_content("렌트_0509"), ("렌트_0509", ""))

    def test_no_verified_period_stays_blank(self):
        self.assertEqual(split_content("숙박"), ("숙박", ""))

    def test_air_period_can_come_from_ota_item_name(self):
        self.assertEqual(
            resolve_item_period("항공_이상희", "", "트립닷컴_0417_0429"),
            ("항공_이상희", "0417_0429"),
        )

    def test_verified_ota_period_fills_booking(self):
        verified = {"1400": {"category": "숙박", "period": "0607_0610"}}
        self.assertEqual(resolve_period("숙박", "", "1400", verified), ("숙박", "0607_0610"))

    def test_verified_rental_fills_pickup_and_return_period(self):
        verified = {"CAR1": {"category": "렌터카", "period": "0509_0510"}}
        self.assertEqual(resolve_period("렌트", "", "CAR1", verified), ("렌트", "0509_0510"))

    def test_verified_rental_rejects_incomplete_period(self):
        verified = {"CAR1": {"category": "렌터카", "period": "0509"}}
        self.assertEqual(resolve_period("렌트", "", "CAR1", verified), ("렌트", ""))

    def test_unique_item_period_fills_only_same_item(self):
        rows = [
            (None, "AGODA.COM HOTEL PEAR", "숙박", "0411_0412", "A", "국민", 1),
            (None, "AGODA.COM HOTEL PEAR", "숙박", "", "B", "국민", 2),
            (None, "OTHER HOTEL", "숙박", "", "C", "국민", 3),
        ]
        filled = fill_unique_item_periods(rows)
        self.assertEqual(filled[1][3], "0411_0412")
        self.assertEqual(filled[2][3], "")


if __name__ == "__main__":
    unittest.main()
