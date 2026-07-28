from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ledger.domain.direct_sources import import_legacy_verified_links
from ledger.domain.ledger_db import LEDGER_DIR, connect, initialize
from ledger.domain.reconciliation import (
    create_match_group,
    manual_decision_projection,
    record_match_decision,
)


class LegacyVerifiedLinkImportTest(unittest.TestCase):
    CASES = {
        "KBD-0927": ("대표_카카오페이", 1_081_000, "KBD", "proposed"),
        "HAN-3011": ("트립닷컴_이니시스", 792_768, "HAN", "proposed"),
        "HAN-3047": ("트립닷컴_이니시스", 762_870, "HAN", "proposed"),
        "TRIP-0113": ("마이트립", 698_720, "KBD", "proposed"),
        # source_message_id belongs to a 267,472 Trip hotel message, while
        # this legacy payment is a 1,185,597 Mytrip air item.
        "TRIP-0089": ("마이트립", 1_185_597, "KBD", "conflict"),
        "TRIP-0002": ("트립닷컴_호텔 클레멘", 297_136, "KBO", "proposed"),
        "TRIP-0025": ("트립닷컴", 257_856, "KBO", "conflict"),
        "TRIP-0037": ("트립닷컴_하시다테호텔", 95_477, "KBO", "conflict"),
        "TRIP-0085": ("Tango Kairiku Kotsu", 32_000, "MAN", "conflict"),
        "TRIP-0112": ("마이트립", 242_690, "KBD", "proposed"),
    }

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "legacy-links.db")
        initialize(self.db)
        for index, (external_key, (merchant, amount, source_system, _)) in enumerate(
            self.CASES.items(),
            start=1,
        ):
            occurred_on = "2026-04-11" if external_key == "TRIP-0085" else None
            self.db.execute(
                """
                INSERT INTO payment_transactions(
                    external_key, source_event_id, identity_fingerprint,
                    source_system, merchant, amount_krw, occurred_on,
                    transaction_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'purchase')
                """,
                (
                    external_key,
                    f"source:{external_key}",
                    f"fingerprint:{index}",
                    source_system,
                    merchant,
                    amount,
                    occurred_on,
                ),
            )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def test_legacy_inventory_never_becomes_confirmed_manual(self) -> None:
        path = LEDGER_DIR / "data" / "ota_event_links_verified.json"
        first = import_legacy_verified_links(self.db, path)
        decisions = {
            str(row["external_key"]): row
            for row in self.db.execute(
                """
                SELECT payment.external_key, decision.decision_id,
                       decision.status, decision.actor, decision.evidence_json,
                       group_row.id AS group_id
                FROM match_decisions decision
                JOIN match_groups group_row ON group_row.id=decision.group_id
                JOIN match_group_payments member ON member.group_id=group_row.id
                JOIN payment_transactions payment ON payment.id=member.payment_id
                WHERE payment.external_key IN (
                    'KBD-0927','HAN-3011','HAN-3047','TRIP-0113','TRIP-0089',
                    'TRIP-0002','TRIP-0025','TRIP-0037','TRIP-0085','TRIP-0112'
                )
                """
            ).fetchall()
        }
        self.assertEqual(set(decisions), set(self.CASES))
        for external_key, (_, _, _, expected_status) in self.CASES.items():
            with self.subTest(external_key=external_key):
                row = decisions[external_key]
                self.assertEqual(row["status"], expected_status)
                self.assertEqual(row["actor"], "legacy_import")
                self.assertIsNone(
                    manual_decision_projection(self.db, int(row["group_id"]))
                )
        self.assertNotIn(
            "confirmed_manual",
            {str(row["status"]) for row in decisions.values()},
        )
        signal_statuses = {
            str(row["external_key"]): {
                str(signal["signal_name"]): str(signal["signal_status"])
                for signal in self.db.execute(
                    """
                    SELECT signal_name, signal_status
                    FROM match_signal_results WHERE group_id=?
                    """,
                    (int(row["group_id"]),),
                ).fetchall()
            }
            for row in decisions.values()
        }
        self.assertEqual(
            signal_statuses["TRIP-0002"],
            {
                "provider": "match",
                "amount": "match",
                "product": "match",
                "service_date": "unavailable",
                "card_last4": "unavailable",
            },
        )
        self.assertEqual(signal_statuses["TRIP-0025"]["amount"], "mismatch")
        self.assertEqual(
            signal_statuses["TRIP-0025"]["service_date"],
            "unavailable",
        )
        self.assertEqual(signal_statuses["TRIP-0037"]["product"], "mismatch")
        self.assertEqual(signal_statuses["TRIP-0037"]["service_date"], "match")
        self.assertEqual(
            signal_statuses["TRIP-0085"],
            {
                "provider": "mismatch",
                "amount": "mismatch",
                "product": "mismatch",
                "service_date": "mismatch",
                "card_last4": "unavailable",
            },
        )
        self.assertEqual(
            signal_statuses["TRIP-0112"],
            {
                "provider": "unavailable",
                "amount": "unavailable",
                "product": "match",
                "service_date": "unavailable",
                "card_last4": "unavailable",
            },
        )

        stable_ids = {
            key: str(row["decision_id"]) for key, row in decisions.items()
        }
        second = import_legacy_verified_links(self.db, path)
        replay_ids = {
            str(row["external_key"]): str(row["decision_id"])
            for row in self.db.execute(
                """
                SELECT payment.external_key, decision.decision_id
                FROM match_decisions decision
                JOIN match_group_payments member
                  ON member.group_id=decision.group_id
                JOIN payment_transactions payment ON payment.id=member.payment_id
                WHERE payment.external_key IN (
                    'KBD-0927','HAN-3011','HAN-3047','TRIP-0113','TRIP-0089',
                    'TRIP-0002','TRIP-0025','TRIP-0037','TRIP-0085','TRIP-0112'
                )
                """
            ).fetchall()
        }
        self.assertEqual(replay_ids, stable_ids)
        self.assertEqual(second["created"], 0)
        self.assertGreaterEqual(first["created"], len(self.CASES))

    def test_booking_payment_completion_date_is_not_service_date(self) -> None:
        self.db.execute(
            """
            INSERT INTO payment_transactions(
                external_key, source_event_id, identity_fingerprint,
                source_system, merchant, amount_krw, transaction_type
            ) VALUES (
                'KBO-PAYMENT-DATE', 'source:KBO-PAYMENT-DATE',
                'fingerprint:booking-payment-date', 'KBO',
                'BKG*BOOKING.COM HOTEL', 716289, 'purchase'
            )
            """
        )
        self.db.commit()
        root = Path(self.temp.name)
        links_path = root / "ota_event_links_verified.json"
        links_path.write_text(
            json.dumps(
                {
                    "KBO-PAYMENT-DATE": {
                        "provider": "booking.com",
                        "source_message_id": "mail-payment-complete",
                        "period": "0418_0419",
                        "category": "숙박",
                    }
                }
            ),
            encoding="utf-8",
        )
        (root / "ota_mail_index.json").write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "messageId": "mail-payment-complete",
                            "provider": "booking",
                            "subject": "결제가 완료되었습니다",
                            "travelDates": ["0414"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = import_legacy_verified_links(self.db, links_path)

        self.assertEqual(result["proposed"], 1)
        row = self.db.execute(
            """
            SELECT decision.status, signal.signal_status
            FROM match_decisions decision
            JOIN match_groups group_row ON group_row.id=decision.group_id
            JOIN match_group_payments member ON member.group_id=group_row.id
            JOIN payment_transactions payment ON payment.id=member.payment_id
            JOIN match_signal_results signal ON signal.group_id=group_row.id
            WHERE payment.external_key='KBO-PAYMENT-DATE'
              AND signal.signal_name='service_date'
            """
        ).fetchone()
        self.assertEqual(dict(row), {
            "status": "proposed",
            "signal_status": "unavailable",
        })

    def test_manual_projection_is_derived_from_append_only_current_chain(self) -> None:
        payment_id = int(
            self.db.execute(
                "SELECT id FROM payment_transactions WHERE external_key='KBD-0927'"
            ).fetchone()[0]
        )
        group_id = create_match_group(
            self.db,
            "representative-review:KBD-0927",
            status="proposed",
            payment_ids=[payment_id],
        )
        self.assertIsNone(manual_decision_projection(self.db, group_id))
        self.assertTrue(
            record_match_decision(
                self.db,
                "REP-KBD-0927-1",
                group_id,
                status="confirmed_manual",
                actor="representative",
                reason_code="manual_review",
                rationale="대표자 카드 원문·후보 육안확인",
                evidence=[],
            )
        )
        projection = manual_decision_projection(self.db, group_id)
        self.assertIsNotNone(projection)
        manual = projection["pythonManualDecision"]
        self.assertEqual(projection["pythonProjectionStatus"], "confirmed_manual")
        self.assertEqual(manual["decisionId"], "REP-KBD-0927-1")
        self.assertEqual(len(manual["evidenceHash"]), 64)
        self.assertTrue(manual["replayVerified"])
        self.assertTrue(manual["matchedFresh"])
        self.assertTrue(manual["currentDecisionVerified"])
        self.assertTrue(manual["supersedesChainVerified"])
        replay_projection = manual_decision_projection(self.db, group_id)
        self.assertEqual(
            replay_projection["pythonManualDecision"]["evidenceHash"],
            manual["evidenceHash"],
        )
        self.db.execute(
            """
            INSERT INTO match_signal_results(
                group_id, signal_name, signal_status, left_value, right_value,
                rule_id, evidence_json
            ) VALUES (?, 'amount', 'mismatch', '1081000', '999999',
                      'test:stale', '[]')
            """,
            (group_id,),
        )
        stale = manual_decision_projection(self.db, group_id)
        self.assertFalse(stale["pythonManualDecision"]["matchedFresh"])
        self.db.execute(
            "DELETE FROM match_signal_results WHERE group_id=?",
            (group_id,),
        )

        self.assertTrue(
            record_match_decision(
                self.db,
                "REP-KBD-0927-2",
                group_id,
                status="conflict",
                actor="representative",
                reason_code="new_conflict",
                rationale="추가 충돌 발견",
                evidence=[],
                supersedes="REP-KBD-0927-1",
            )
        )
        self.assertIsNone(manual_decision_projection(self.db, group_id))
        self.assertTrue(
            record_match_decision(
                self.db,
                "REP-KBD-0927-3",
                group_id,
                status="confirmed_manual",
                actor="representative",
                reason_code="conflict_resolved",
                rationale="충돌 원문 재검토 완료",
                evidence=[],
                supersedes="REP-KBD-0927-2",
            )
        )
        current = manual_decision_projection(self.db, group_id)
        self.assertEqual(
            current["pythonManualDecision"]["decisionId"],
            "REP-KBD-0927-3",
        )
        self.assertTrue(
            current["pythonManualDecision"]["supersedesChainVerified"]
        )

    def test_representative_can_resolve_legacy_conflict_without_losing_history(self) -> None:
        path = LEDGER_DIR / "data" / "ota_event_links_verified.json"
        import_legacy_verified_links(self.db, path)
        legacy = self.db.execute(
            """
            SELECT group_row.id AS group_id, group_row.group_key,
                   decision.decision_id
            FROM match_decisions decision
            JOIN match_groups group_row ON group_row.id=decision.group_id
            JOIN match_group_payments member ON member.group_id=group_row.id
            JOIN payment_transactions payment ON payment.id=member.payment_id
            WHERE payment.external_key='TRIP-0085'
            """
        ).fetchone()
        self.assertEqual(
            self.db.execute(
                "SELECT status FROM current_match_decisions WHERE group_id=?",
                (legacy["group_id"],),
            ).fetchone()["status"],
            "conflict",
        )

        resolved_signals = []
        for signal in self.db.execute(
            """
            SELECT signal_name, left_value, right_value
            FROM match_signal_results WHERE group_id=?
            """,
            (legacy["group_id"],),
        ).fetchall():
            value = str(signal["left_value"] or signal["right_value"] or "")
            resolved_signals.append(
                {
                    "name": signal["signal_name"],
                    "status": "match" if value else "unavailable",
                    "left": value or None,
                    "right": value or None,
                    "rule_id": "representative-resolution",
                }
            )
        create_match_group(
            self.db,
            str(legacy["group_key"]),
            status="conflict",
            payment_ids=[
                int(
                    self.db.execute(
                        """
                        SELECT payment_id FROM match_group_payments
                        WHERE group_id=?
                        """,
                        (legacy["group_id"],),
                    ).fetchone()[0]
                )
            ],
            signals=resolved_signals,
        )
        self.assertTrue(
            record_match_decision(
                self.db,
                "REP-TRIP-0085-RESOLVED",
                int(legacy["group_id"]),
                status="confirmed_manual",
                actor="representative",
                reason_code="conflict_resolved",
                rationale="provider·amount·product·date 원문 재확인",
                evidence=[],
                supersedes=str(legacy["decision_id"]),
            )
        )
        history = self.db.execute(
            """
            SELECT decision_id, status, actor, supersedes_decision_id
            FROM match_decisions WHERE group_id=? ORDER BY rowid
            """,
            (legacy["group_id"],),
        ).fetchall()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["actor"], "legacy_import")
        self.assertEqual(history[0]["status"], "conflict")
        self.assertEqual(
            history[1]["supersedes_decision_id"],
            history[0]["decision_id"],
        )
        projection = manual_decision_projection(
            self.db,
            int(legacy["group_id"]),
        )
        self.assertEqual(
            projection["pythonManualDecision"]["decisionId"],
            "REP-TRIP-0085-RESOLVED",
        )


if __name__ == "__main__":
    unittest.main()
