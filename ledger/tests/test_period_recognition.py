from __future__ import annotations

import unittest

from ledger.domain.period_recognition import (
    is_prepaid_future_trip,
    is_refundable_deposit_pending,
    structured_service_start_on,
)


class PeriodRecognitionTest(unittest.TestCase):
    def test_kbd_1029_requires_structured_booking_start(self) -> None:
        note_only = {
            "note": "메일확정 | trip_hotel/리틀 프린스 호텔&콘도/체크인2026-08-27"
        }
        booking = {"service_start_on": "2026-08-27"}
        self.assertIsNone(structured_service_start_on(note_only))
        self.assertEqual(structured_service_start_on(booking), "2026-08-27")
        self.assertTrue(is_prepaid_future_trip(structured_service_start_on(booking)))

    def test_unknown_or_in_period_service_is_not_auto_excluded(self) -> None:
        self.assertIsNone(structured_service_start_on({"period": "숙박_0827_0829"}))
        self.assertFalse(is_prepaid_future_trip(None))
        self.assertFalse(is_prepaid_future_trip("2026-06-30"))

    def test_refundable_deposit_is_not_a_normal_prepayment(self) -> None:
        self.assertTrue(
            is_refundable_deposit_pending(
                {"settlement_condition": "refundable_deposit_pending"}
            )
        )
        self.assertFalse(is_refundable_deposit_pending({"service_start_on": "2026-08-27"}))


if __name__ == "__main__":
    unittest.main()
