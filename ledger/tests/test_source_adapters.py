from __future__ import annotations

import unittest

from ledger.domain.source_adapters import (
    forbidden_ota_fields,
    mark_identity_collisions,
    normalize_service_period,
    reconcile_amount,
    sanitize_ota_record,
    stable_card_event_identity,
)


class SourceAdapterTest(unittest.TestCase):
    def test_approval_identity_ignores_enrichment_and_legacy_uid(self) -> None:
        base = {
            "src": "KBD",
            "card4": "8835",
            "appr": "12345678",
            "krw": "10000",
            "merchant": "A",
            "uid": "OLD-1",
        }
        changed = {**base, "merchant": "정규화된 A", "uid": "NEW-999"}
        self.assertEqual(
            stable_card_event_identity(base).card_event_id,
            stable_card_event_identity(changed).card_event_id,
        )

    def test_overseas_identity_preserves_same_amount_duplicate_rows(self) -> None:
        base = {
            "src": "KBO",
            "card4": "8835",
            "use_date": "2026-03-12",
            "post_date": "2026-03-14",
            "currency": "JPY",
            "foreign": "6500.00",
            "krw": "62496",
        }
        first = stable_card_event_identity({**base, "raw_record_id": "KBO:E:41"})
        second = stable_card_event_identity({**base, "raw_record_id": "KBO:E:42"})
        self.assertNotEqual(first.card_event_id, second.card_event_id)

    def test_structural_collision_is_reviewed_not_merged(self) -> None:
        row = {
            "src": "KBO",
            "card4": "8835",
            "use_date": "2026-03-12",
            "currency": "JPY",
            "foreign": "6500",
            "krw": "62496",
        }
        identities = mark_identity_collisions(
            [stable_card_event_identity(row), stable_card_event_identity(row)]
        )
        self.assertEqual([item.identity_status for item in identities], ["collision", "collision"])

    def test_ota_allowlist_drops_personal_and_authentication_data(self) -> None:
        record = {
            "provider": "trip.com",
            "booking_number": "1400823716285910",
            "service_start_on": "2026-07-02",
            "pin": "2647",
            "생년월일": "1956-08-02",
            "phone": "010-1234-5678",
            "email": "person@example.com",
            "passport_number": "M12345678",
        }
        self.assertTrue(forbidden_ota_fields(record))
        clean = sanitize_ota_record(record)
        self.assertEqual(clean["booking_number"], "1400823716285910")
        self.assertEqual(clean["redaction_version"], "ota-allowlist-v1")
        self.assertFalse(forbidden_ota_fields(clean))

    def test_amount_reconciliation_distinguishes_supported_tolerance(self) -> None:
        self.assertEqual(reconcile_amount(100_000, 100_000)[0], "exact")
        self.assertEqual(
            reconcile_amount(996_000, 1_000_000, discount_krw=4_000)[0],
            "discount_adjusted",
        )
        self.assertEqual(
            reconcile_amount(1_015_000, 1_000_000, overseas_krw=True)[0],
            "within_2_percent",
        )
        self.assertEqual(
            reconcile_amount(1_015_000, 1_000_000, overseas_krw=False)[0],
            "mismatch",
        )

    def test_month_day_period_does_not_assume_a_year(self) -> None:
        self.assertEqual(
            normalize_service_period("0417", "0419"),
            ("0417", "0419", "month_day", "0417"),
        )
        self.assertEqual(
            normalize_service_period("2026-04-17", "2026-04-19")[:3],
            ("2026-04-17", "2026-04-19", "day"),
        )


if __name__ == "__main__":
    unittest.main()
