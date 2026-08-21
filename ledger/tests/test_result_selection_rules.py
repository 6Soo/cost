from __future__ import annotations

import unittest
from datetime import date

from ledger.domain.result_selection_rules import (
    event_period_for_targets,
    normalize_merchant_name,
)


class ResultSelectionRulesTest(unittest.TestCase):
    def test_normalizes_country_and_city_suffix_and_whitespace(self) -> None:
        self.assertEqual(normalize_merchant_name("FAMILYMART Tokyo JP   "), "FAMILYMART")
        self.assertEqual(
            normalize_merchant_name("Hotel at Booking.com Amsterdam NL  "),
            "Hotel at Booking.com",
        )
        self.assertEqual(normalize_merchant_name("TOKYO JP"), "TOKYO")

    def test_preserves_city_inside_merchant_name(self) -> None:
        self.assertEqual(normalize_merchant_name("TOKYO DISNEY RESORT JP"), "TOKYO DISNEY RESORT")

    def test_canonical_trip_schedule_beats_payment_date(self) -> None:
        period = event_period_for_targets(
            "trip-2026",
            trips={"trip-2026": ("2026-07-01", "2026-07-03")},
            registries={},
        )
        self.assertEqual(period.starts_on, date(2026, 7, 1))
        self.assertEqual(period.ends_on, date(2026, 7, 3))
        self.assertTrue(period.eligible)

    def test_registry_period_can_cross_from_2025_into_2026(self) -> None:
        period = event_period_for_targets(
            "crossing-trip",
            trips={},
            registries={"crossing-trip": (("2025-12-29", "2026-01-03"),)},
            allow_registry=True,
        )
        self.assertEqual(period.starts_on, date(2025, 12, 29))
        self.assertEqual(period.ends_on, date(2026, 1, 3))
        self.assertTrue(period.eligible)

    def test_no_payment_date_fallback(self) -> None:
        period = event_period_for_targets(
            "unassigned",
            trips={},
            registries={},
            evidence_payloads=[{"payment_date": "2026-04-01"}],
        )
        self.assertFalse(period.eligible)
        self.assertEqual(period.reason, "event_period_unavailable")


if __name__ == "__main__":
    unittest.main()
