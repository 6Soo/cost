import sqlite3
import unittest

from ledger.domain.direct_trip_schedule_authority import ScheduleRecord
from tools.build_agoda_accounting_draft_v3 import build_rows


class AgodaAccountingDraftV3Tests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE payment_transactions(id INTEGER PRIMARY KEY, occurred_on TEXT)")
        self.db.executemany(
            "INSERT INTO payment_transactions(id,occurred_on) VALUES (?,?)",
            [(1, "2026-01-15"), (2, "2025-12-20")],
        )

    def tearDown(self):
        self.db.close()

    def source(self, payment_id, start, end):
        return {
            "link_authority_id": f"{payment_id:064d}"[-64:],
            "payment_id": payment_id,
            "booking_id": payment_id + 100,
            "booking_number": str(1700000000 + payment_id),
            "external_key": f"KBO-{payment_id}",
            "amount_krw": 1000 + payment_id,
            "service_start_on": start,
            "service_end_on": end,
            "booking_evidence_set_sha256": "e" * 64,
        }

    def test_legacy_unique_is_candidate_only_and_2025_lane_is_separate(self):
        legacy = [
            ScheduleRecord(
                "0408_교토", 2026, __import__("datetime").date(2026, 4, 8),
                __import__("datetime").date(2026, 4, 14), "교토",
                "legacy_window_candidate", "ledger/data/trips.json#/1", "l" * 64,
                "candidate_only",
            )
        ]
        rows = build_rows(
            self.db,
            [self.source(1, "2026-04-08", "2026-04-10"), self.source(2, "2025-12-20", "2025-12-21")],
            [],
            legacy,
            input_database_sha256="a" * 64,
            input_audit_sha256="b" * 64,
            authority_document_sha256="c" * 64,
            legacy_schedule_sha256="d" * 64,
        )
        self.assertEqual(rows[0]["target_match_status"], "legacy_window_candidate_only")
        self.assertEqual(rows[0]["allocation_target"], "여행_미배정")
        self.assertEqual(rows[0]["old_window_match_status"], "unique_service_period")
        self.assertEqual(rows[1]["payment_lane"], "2025년 결제")
        self.assertEqual(rows[1]["target_match_status"], "authority_missing")

    def test_explicit_unique_authority_can_bind(self):
        authority = [
            ScheduleRecord(
                "0408_교토", 2026, __import__("datetime").date(2026, 4, 8),
                __import__("datetime").date(2026, 4, 14), "교토",
                "official_event_schedule", "evidence://0408", "f" * 64,
                "authoritative",
            )
        ]
        rows = build_rows(
            self.db, [self.source(1, "2026-04-08", "2026-04-10")], authority, [],
            input_database_sha256="a" * 64, input_audit_sha256="b" * 64,
            authority_document_sha256="c" * 64, legacy_schedule_sha256="d" * 64,
        )
        self.assertEqual(rows[0]["target_match_status"], "bound_unique")
        self.assertEqual(rows[0]["allocation_target"], "0408_교토")
        self.assertEqual(rows[0]["target_authority"], "authoritative_explicit_period")


if __name__ == "__main__":
    unittest.main()
