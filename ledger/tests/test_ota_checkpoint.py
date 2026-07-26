from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger.domain.ota_checkpoint import OtaCheckpointStore
from ledger.domain.source_adapters import forbidden_ota_fields


def portal_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "provider": "agoda",
        "booking_id": "1696845387",
        "current_url": "https://www.agoda.com/account/bookings/1696845387",
        "portal_list_name": "completed",
        "portal_list_position": 4,
        "observed_at": "2026-07-26T10:20:00+09:00",
        "product_type": "lodging",
        "merchant": "Lotte Arai Resort",
        "service_start_on": "2026-06-23",
        "service_end_on": "2026-06-24",
        "currency": "JPY",
        "booking_display_amount": "36499",
        "card_last4": "8835",
        "record_type": "charge",
        "booking_confirmation_status": "confirmed",
        "status": "completed",
    }
    record.update(overrides)
    return record


class OtaCheckpointStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "ota-checkpoints.db"
        self.store = OtaCheckpointStore(self.path)

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def test_capture_commits_one_booking_immediately_and_reopens_at_next(self) -> None:
        result = self.store.capture(portal_record())
        self.assertTrue(result.inserted)
        self.assertTrue(result.complete)

        # A separate connection sees the row before another booking is read.
        observer = sqlite3.connect(self.path)
        try:
            self.assertEqual(
                observer.execute(
                    "SELECT COUNT(*) FROM ota_booking_observations"
                ).fetchone()[0],
                1,
            )
        finally:
            observer.close()

        self.store.close()
        self.store = OtaCheckpointStore(self.path)
        resume = self.store.resume_state("agoda")
        self.assertEqual(resume.last_completed_booking_id, "1696845387")
        self.assertEqual(resume.last_completed_position, 4)
        self.assertEqual(resume.next_position, 5)
        self.assertEqual(resume.completed_booking_ids, ("1696845387",))

    def test_exact_retry_is_idempotent_by_provider_and_booking(self) -> None:
        first = self.store.capture(portal_record())
        second = self.store.capture(portal_record())
        self.assertEqual(first.observation_id, second.observation_id)
        self.assertFalse(second.inserted)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM ota_booking_observations"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM ota_booking_current"
            ).fetchone()[0],
            1,
        )

    def test_changed_observation_appends_and_advances_current(self) -> None:
        incomplete = portal_record(merchant="", observed_at="2026-07-26T01:00:00Z")
        first = self.store.capture(incomplete)
        self.assertFalse(first.complete)
        self.assertEqual(first.missing_fields, ("merchant",))
        self.assertIsNone(self.store.resume_state("agoda").next_position)

        second = self.store.capture(
            portal_record(observed_at="2026-07-26T01:01:00Z")
        )
        self.assertTrue(second.complete)
        self.assertNotEqual(first.observation_id, second.observation_id)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM ota_booking_observations"
            ).fetchone()[0],
            2,
        )
        self.assertEqual(len(self.store.completed_records("agoda")), 1)

    def test_complete_true_rejects_missing_fields_without_partial_write(self) -> None:
        with self.assertRaisesRegex(ValueError, "merchant"):
            self.store.capture(portal_record(merchant=""), complete=True)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM ota_booking_observations"
            ).fetchone()[0],
            0,
        )

    def test_older_retry_does_not_regress_current_or_cursor(self) -> None:
        self.store.capture(portal_record(observed_at="2026-07-26T02:00:00Z"))
        self.store.capture(
            portal_record(
                observed_at="2026-07-26T01:00:00Z",
                portal_list_position=1,
                merchant="Old stale value",
            )
        )
        resume = self.store.resume_state("agoda")
        self.assertEqual(resume.last_completed_position, 4)
        current = self.store.completed_records("agoda")[0]
        self.assertEqual(current["merchant"], "Lotte Arai Resort")

    def test_pre_2025_booking_is_outside_scope(self) -> None:
        with self.assertRaisesRegex(ValueError, "pre-2025"):
            self.store.capture(portal_record(service_start_on="2024-12-31"))

    def test_export_uses_existing_privacy_allowlist_and_omits_url(self) -> None:
        self.store.capture(
            portal_record(
                email="guest@example.com",
                pin="1234",
                password="secret",
            )
        )
        exported = self.store.completed_records()[0]
        self.assertNotIn("current_url", exported)
        self.assertFalse(forbidden_ota_fields(exported))
        self.assertEqual(
            exported["source_channel"], "authenticated_booking_portal"
        )
        self.assertEqual(exported["message_id"], "portal:agoda:1696845387")
        self.assertEqual(exported["booking_number"], "1696845387")
        self.assertEqual(exported["portal_list_position"], 4)


if __name__ == "__main__":
    unittest.main()
