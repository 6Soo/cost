from __future__ import annotations

import unittest

from ledger.domain.source_adapters import (
    forbidden_ota_fields,
    mark_identity_collisions,
    normalize_service_period,
    reconcile_amount,
    sanitize_ota_record,
    adapt_ota_record,
    stable_card_event_identity,
)


class SourceAdapterTest(unittest.TestCase):
    def test_ota_candidates_are_typed_and_scalars_only_when_unique(self) -> None:
        clean = adapt_ota_record({
            "messageId": "m1", "amounts": [1000, 2000],
            "pnrs": ["AB12345"], "bookingRefs": ["12345678"],
            "travelDates": ["0701"],
        })
        self.assertEqual(clean["amount_candidates"], [1000, 2000])
        self.assertEqual(clean["pnr_candidates"], ["AB12345"])
        self.assertEqual(clean["booking_ref_candidates"], ["12345678"])
        self.assertNotIn("booking_number", clean)
        self.assertNotIn("period_original", clean)
        self.assertEqual(clean["redaction_version"], "ota-allowlist-v3")

        many = adapt_ota_record({"bookingRefs": ["12345678", "87654321"]})
        self.assertEqual(many["booking_ref_candidates"], ["12345678", "87654321"])
        self.assertNotIn("booking_number", many)

        formatted = adapt_ota_record({"bookingRefs": ["1083-192-723"]})
        self.assertEqual(formatted["booking_ref_candidates"], ["1083-192-723"])

    def test_ota_candidate_type_and_pattern_violations_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "ota_candidate_pattern"):
            adapt_ota_record({"pnrs": [" AB1234 "]})
        with self.assertRaisesRegex(ValueError, "ota_candidate_type"):
            adapt_ota_record({"amounts": ["1000"]})
        with self.assertRaisesRegex(ValueError, "ota_candidate_pattern"):
            adapt_ota_record({"pnrs": ["ab12345"]})
        with self.assertRaisesRegex(ValueError, "ota_candidate_type"):
            adapt_ota_record({"amounts": [True]})
        with self.assertRaisesRegex(ValueError, "ota_candidate_pattern"):
            adapt_ota_record({"pnrs": ["too-long-pnr"]})
        with self.assertRaisesRegex(ValueError, "ota_candidate_pattern"):
            adapt_ota_record({"travelDates": ["2026/07/01"]})
        with self.assertRaisesRegex(ValueError, "ota_candidate_date"):
            adapt_ota_record({"travelDates": ["0231"]})

    def test_approval_identity_ignores_enrichment_and_legacy_uid(self) -> None:
        base = {
            "src": "KBD",
            "card4": "8835",
            "appr": "12345678",
            "use_date": "2026-03-12",
            "krw": "10000",
            "merchant": "A",
            "uid": "OLD-1",
            "post_date": "2026-03-14",
            "raw_record_id": "KBD:1",
        }
        changed = {
            **base,
            "merchant": "정규화된 A",
            "uid": "NEW-999",
            "krw": "99999",
            "post_date": "2026-03-15",
            "raw_record_id": "KBD:999",
        }
        self.assertEqual(
            stable_card_event_identity(base).card_event_id,
            stable_card_event_identity(changed).card_event_id,
        )

    def test_approval_identity_dates_are_distinct(self) -> None:
        base = {
            "src": "HAN",
            "card4": "4595",
            "appr": "00107633",
            "use_date": "2026-06-10",
            "krw": "392606",
        }
        self.assertNotEqual(
            stable_card_event_identity(base).card_event_id,
            stable_card_event_identity({**base, "use_date": "2026-06-06"}).card_event_id,
        )

    def test_approval_missing_or_invalid_date_is_legacy_fallback(self) -> None:
        base = {"src": "HAN", "card4": "4595", "appr": "00107633"}
        self.assertEqual(stable_card_event_identity(base).identity_status, "legacy_fallback")
        self.assertEqual(
            stable_card_event_identity({**base, "use_date": "2026-02-30"}).identity_status,
            "legacy_fallback",
        )
        self.assertEqual(
            stable_card_event_identity({**base, "use_date": "2026-6-06"}).identity_status,
            "legacy_fallback",
        )

    def test_same_date_approval_duplicate_remains_collision(self) -> None:
        row = {
            "src": "HAN",
            "card4": "4595",
            "appr": "00107633",
            "use_date": "2026-06-10",
            "krw": "392606",
        }
        identities = mark_identity_collisions(
            [stable_card_event_identity(row), stable_card_event_identity(dict(row))]
        )
        self.assertEqual([item.identity_status for item in identities], ["collision", "collision"])

    def test_approval_purchase_and_cancellation_kinds_remain_distinct(self) -> None:
        base = {
            "src": "HAN",
            "card4": "4595",
            "appr": "00107633",
            "use_date": "2026-06-10",
            "krw": "392606",
        }
        cancellation = {**base, "cancel": "1", "krw": "-392606"}
        purchase_identity = stable_card_event_identity(base)
        cancellation_identity = stable_card_event_identity(cancellation)
        self.assertNotEqual(purchase_identity.card_event_id, cancellation_identity.card_event_id)
        self.assertEqual(purchase_identity.structural_payload["event_kind"], "purchase")
        self.assertEqual(cancellation_identity.structural_payload["event_kind"], "refund")

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
        self.assertEqual(clean["redaction_version"], "ota-allowlist-v3")
        self.assertFalse(forbidden_ota_fields(clean))

    def test_amount_reconciliation_requires_exact_or_sourced_adjustment(self) -> None:
        self.assertEqual(reconcile_amount(100_000, 100_000)[0], "exact")
        self.assertEqual(
            reconcile_amount(996_000, 1_000_000, discount_krw=4_000)[0],
            "discount_adjusted",
        )
        self.assertEqual(
            reconcile_amount(1_015_000, 1_000_000, overseas_krw=True)[0],
            "mismatch",
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

    def test_ota_policy_cancellation_is_not_a_completed_cancel(self) -> None:
        clean = adapt_ota_record({
            "provider": "Agoda",
            "subject": "무료 취소 가능 예약 확정",
            "sentAt": "2025-12-20T10:00:00",
            "messageHash": "a" * 64,
        })
        self.assertEqual(clean["message_status"], "confirmation")
        self.assertEqual(clean["message_template_class"], "confirmation")
        self.assertEqual(clean["lifecycle_parser_version"], "ota-lifecycle-v2")
        self.assertEqual(clean["message_status_rule_version"], "ota-status-v2")

    def test_ota_completed_cancel_is_detected(self) -> None:
        clean = adapt_ota_record({
            "provider": "Agoda",
            "subject": "예약 취소 안내 및 환불 완료",
        })
        self.assertEqual(clean["message_status"], "cancel")


if __name__ == "__main__":
    unittest.main()
