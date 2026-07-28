from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger.domain.ledger_db import connect, initialize
from ledger.domain.ota_reporting import (
    classify_accounting_state,
    classify_payment_state,
    current_payment_decision_states,
)


class OtaReportingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "reporting.db")
        initialize(self.db)
        self.db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint,
                source_system, merchant, amount_krw, transaction_type
            ) VALUES ('BOOK-1', 'card:BOOK-1', 'fp:BOOK-1',
                      'KBO', 'BOOKING.COM', 1000, 'purchase')
            """
        )
        self.payment_id = int(
            self.db.execute(
                "SELECT id FROM payment_transactions WHERE external_key='BOOK-1'"
            ).fetchone()[0]
        )

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def _decision(
        self, group_key: str, status: str, actor: str, reason: str
    ) -> None:
        self.db.execute(
            """
            INSERT INTO match_groups(group_key, provider, status)
            VALUES (?, 'booking.com', ?)
            """,
            (group_key, status),
        )
        group_id = int(
            self.db.execute(
                "SELECT id FROM match_groups WHERE group_key=?", (group_key,)
            ).fetchone()[0]
        )
        self.db.execute(
            """
            INSERT INTO match_group_payments(group_id, payment_id, amount_krw)
            VALUES (?, ?, 1000)
            """,
            (group_id, self.payment_id),
        )
        self.db.execute(
            """
            INSERT INTO match_decisions(
                decision_id, group_id, status, actor, reason_code, rationale
            ) VALUES (?, ?, ?, ?, ?, 'test')
            """,
            (f"decision:{group_key}", group_id, status, actor, reason),
        )

    def test_direct_confirmation_overrides_legacy_proposal(self) -> None:
        self._decision(
            "legacy-link:BOOK-1", "proposed", "legacy_import",
            "legacy_verified_link",
        )
        self._decision(
            "booking-direct:BOOK-1", "confirmed_strong",
            "direct_evidence_reconciler", "unique_direct_payment_intersection",
        )
        states = current_payment_decision_states(self.db)
        self.assertEqual(states["BOOK-1"]["status"], "confirmed_strong")
        self.assertEqual(
            classify_payment_state("BOOK-1", "booking", states),
            {
                "state": "confirmed_strong",
                "disposition": "confirmed",
                "evidence_state": "confirmed_strong",
                "evidence_disposition": "direct_link_confirmed",
                "reason_code": "unique_direct_payment_intersection",
                "decision_id": "decision:booking-direct:BOOK-1",
                "decision_actor": "direct_evidence_reconciler",
                "concurrent_states": ["confirmed_strong", "proposed"],
                "review_complete": True,
            },
        )

    def test_concurrent_conflict_blocks_confirmation(self) -> None:
        self._decision(
            "booking-direct:BOOK-1",
            "confirmed_strong",
            "direct_evidence_reconciler",
            "unique_direct_payment_intersection",
        )
        self._decision(
            "legacy-link:BOOK-1",
            "conflict",
            "legacy_import",
            "legacy_signal_conflict",
        )
        result = classify_payment_state(
            "BOOK-1", "booking", current_payment_decision_states(self.db)
        )
        self.assertEqual(result["state"], "conflict")
        self.assertEqual(result["disposition"], "hold")
        self.assertEqual(result["evidence_disposition"], "direct_link_conflict")
        self.assertEqual(
            result["concurrent_states"],
            ["confirmed_strong", "conflict"],
        )

    def test_json_only_proposal_never_becomes_confirmed(self) -> None:
        self._decision(
            "legacy-link:BOOK-1", "proposed", "legacy_import",
            "legacy_verified_link",
        )
        result = classify_payment_state(
            "BOOK-1", "booking", current_payment_decision_states(self.db)
        )
        self.assertEqual(result["state"], "proposed")
        self.assertEqual(result["disposition"], "pending")
        self.assertEqual(result["evidence_disposition"], "direct_link_unproven")
        self.assertFalse(result["review_complete"])

    def test_mutable_group_status_without_decision_never_confirms(self) -> None:
        self.db.execute(
            """
            INSERT INTO match_groups(group_key, provider, status)
            VALUES ('unsafe-group-only', 'booking.com', 'confirmed_strong')
            """
        )
        group_id = int(
            self.db.execute(
                "SELECT id FROM match_groups WHERE group_key='unsafe-group-only'"
            ).fetchone()[0]
        )
        self.db.execute(
            """
            INSERT INTO match_group_payments(group_id, payment_id, amount_krw)
            VALUES (?, ?, 1000)
            """,
            (group_id, self.payment_id),
        )
        states = current_payment_decision_states(self.db)
        self.assertNotIn("BOOK-1", states)
        result = classify_payment_state("BOOK-1", "booking", states)
        self.assertEqual(result["state"], "not_investigated_pending")
        self.assertFalse(result["review_complete"])

    def test_no_matcher_is_not_reported_as_hold(self) -> None:
        result = classify_payment_state("TRIP-1", "trip", {})
        self.assertEqual(result["state"], "not_investigated_no_matcher")
        self.assertEqual(result["disposition"], "pending")
        self.assertEqual(result["reason_code"], "provider_matcher_not_implemented")

    def test_accounting_state_is_independent_from_direct_link_state(self) -> None:
        self.assertEqual(
            classify_accounting_state({"bucket": "0404_에히메"}),
            {
                "accounting_state": "classified",
                "filing_state": "included_in_canonical",
                "accounting_review_complete": True,
            },
        )
        self.assertEqual(
            classify_accounting_state({"bucket": "여행_미배정"})[
                "accounting_state"
            ],
            "travel_unassigned",
        )


if __name__ == "__main__":
    unittest.main()
