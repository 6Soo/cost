from __future__ import annotations

import sqlite3
import unittest

from ledger.domain.direct_accounting_shadow import (
    CARD_CLEARING_ACCOUNT,
    SHADOW_SCHEMA,
    _sha,
    _insert_batch,
    _make_member,
    apply_shadow_schema,
    promote_shadow_to_posting,
    validate_shadow_accounting,
)


class DirectAccountingShadowTest(unittest.TestCase):
    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(":memory:")
        db.executescript(SHADOW_SCHEMA)
        db.execute(
            """CREATE TABLE allocation_plans(
                 id INTEGER PRIMARY KEY, payment_id INTEGER)"""
        )
        db.execute(
            """CREATE TABLE cost_allocations(
                 id INTEGER PRIMARY KEY, plan_id INTEGER)"""
        )
        db.execute(
            """CREATE TABLE journal_entries(
                 id INTEGER PRIMARY KEY, allocation_id INTEGER,
                 posting_status TEXT)"""
        )
        return db

    def _member(self, amount: int, key: str = "component") -> dict[str, object]:
        payment = type(
            "Payment", (), {
                "payment_id": 1,
                "external_key": "redacted-external-key",
                "direct_event_key": "event#purchase",
                "occurred_on": "2025-01-02T03:04:05",
                "amount_krw": amount,
                "source_currency": None,
                "foreign_amount": None,
                "source_currency_status": "unknown",
                "currency_evidence_sha256": "a" * 64,
            },
        )()
        return _make_member(
            payment,
            family_id="test_family",
            component_key=key,
            signed_amount=amount,
            member_role="purchase",
            expense_account="기타비용",
        )

    def _shadow_manifest(self, db: sqlite3.Connection) -> None:
        db.execute(
            """INSERT INTO direct_accounting_shadow_manifests(
                 run_id,mode,schema_version,selected_payment_count,batch_count,
                 member_count,line_count,family_set_sha256,membership_sha256,
                 policy_sha256,ledger_mapping_sha256,status,payload_json)
               VALUES ('run','base','accounting-shadow-v2',1,1,1,2,
                       ?,?,?,?, 'shadow_balanced',?)""",
            (
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "e" * 64,
                '{"posting_status":"shadow_only","external_posting":false}',
            ),
        )
        db.commit()

    def test_signed_member_creates_balanced_two_line_batch(self) -> None:
        db = self._db()
        try:
            member = self._member(-1000)
            _insert_batch(db, "run", "test_family", "test-rule", [member])
            row = db.execute(
                "SELECT side,account_code,amount_krw FROM direct_accounting_shadow_lines"
            ).fetchall()
            self.assertEqual(
                row,
                [("debit", CARD_CLEARING_ACCOUNT, 1000), ("credit", "기타비용", 1000)],
            )
            self.assertEqual(
                db.execute(
                    "SELECT debit_total_krw,credit_total_krw FROM "
                    "direct_accounting_shadow_batches"
                ).fetchone(),
                (1000, 1000),
            )
        finally:
            db.close()

    def test_validation_rejects_line_imbalance(self) -> None:
        db = self._db()
        try:
            member = self._member(1000)
            _insert_batch(db, "run", "test_family", "test-rule", [member])
            db.execute(
                "UPDATE direct_accounting_shadow_lines SET amount_krw=999 "
                "WHERE side='credit'"
            )
            db.commit()
            db.execute(
                """INSERT INTO direct_accounting_shadow_manifests(
                     run_id,mode,schema_version,selected_payment_count,batch_count,
                     member_count,line_count,family_set_sha256,membership_sha256,
                     policy_sha256,ledger_mapping_sha256,status,payload_json)
                   VALUES ('run','base','accounting-shadow-v2',1,1,1,2,
                           ?,?,?,?, 'shadow_balanced',?)""",
                (
                    "b" * 64, "c" * 64, "d" * 64, "e" * 64,
                    '{"posting_status":"shadow_only","external_posting":false}',
                ),
            )
            result = validate_shadow_accounting(db, "run", mode="base")
            self.assertFalse(result["passed"])
            self.assertIn("shadow_batch_unbalanced_lines", " ".join(result["issues"]))
        finally:
            db.close()

    def test_schema_is_idempotent(self) -> None:
        db = sqlite3.connect(":memory:")
        try:
            apply_shadow_schema(db)
            apply_shadow_schema(db)
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                    "AND name LIKE 'direct_accounting_shadow_%'"
                ).fetchone()[0],
                4,
            )
        finally:
            db.close()

    def test_posting_is_blocked_without_family_approval(self) -> None:
        db = self._db()
        try:
            _insert_batch(db, "run", "test_family", "test-rule", [self._member(1000)])
            self._shadow_manifest(db)
            result = promote_shadow_to_posting(
                db,
                "run",
                mode="base",
                approved_rule_ids=(),
                production_account_mapping={"기타비용": "기타비용"},
            )
            self.assertFalse(result["passed"])
            self.assertEqual(result["reason"], "family_approval_missing")
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM direct_accounting_posting_batches"
                ).fetchone()[0],
                0,
            )
        finally:
            db.close()

    def test_posting_candidate_is_balanced_and_idempotent(self) -> None:
        db = self._db()
        try:
            _insert_batch(db, "run", "test_family", "test-rule", [self._member(1000)])
            self._shadow_manifest(db)
            kwargs = {
                "mode": "base",
                "approved_rule_ids": {"test-rule"},
                "release_ready": False,
                "production_account_mapping": {
                    "기타비용": "기타비용",
                    CARD_CLEARING_ACCOUNT: CARD_CLEARING_ACCOUNT,
                },
                "authorize": False,
            }
            first = promote_shadow_to_posting(db, "run", **kwargs)
            replay = promote_shadow_to_posting(db, "run", **kwargs)
            self.assertTrue(first["passed"])
            self.assertEqual(first["status"], "candidate")
            self.assertEqual(first["candidate_payment_count"], 1)
            self.assertEqual(first["posted_payment_count"], 0)
            self.assertTrue(replay["idempotent_replay"])
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM direct_accounting_posting_batches"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                db.execute(
                    "SELECT SUM(CASE WHEN side='debit' THEN amount_krw ELSE 0 END),"
                    "SUM(CASE WHEN side='credit' THEN amount_krw ELSE 0 END) "
                    "FROM direct_accounting_posting_lines"
                ).fetchone(),
                (1000, 1000),
            )
        finally:
            db.close()

    def test_authorize_requires_content_attestations(self) -> None:
        db = self._db()
        try:
            _insert_batch(db, "run", "test_family", "test-rule", [self._member(1000)])
            self._shadow_manifest(db)
            result = promote_shadow_to_posting(
                db,
                "run",
                mode="base",
                approved_rule_ids={"test-rule"},
                release_ready=True,
                authorize=True,
                production_account_mapping={
                    "기타비용": "기타비용",
                    CARD_CLEARING_ACCOUNT: CARD_CLEARING_ACCOUNT,
                },
            )
            self.assertFalse(result["passed"])
            self.assertIn("family_approval_attestation_missing_or_invalid", result["blocked_reasons"])
            self.assertIn("release_attestation_missing_or_invalid", result["blocked_reasons"])
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM direct_accounting_posting_batches"
                ).fetchone()[0],
                0,
            )
        finally:
            db.close()

    def test_valid_attestations_create_only_local_posted_shadow(self) -> None:
        db = self._db()
        try:
            _insert_batch(db, "run", "test_family", "test-rule", [self._member(1000)])
            self._shadow_manifest(db)
            approval_payload = {
                "run_id": "run",
                "mode": "base",
                "approved_rule_ids": ["test-rule"],
                "approval_status": "approved",
                "decision_id": "family-test-1",
            }
            approval = {
                **approval_payload,
                "approval_sha256": _sha(approval_payload),
            }
            release_payload = {
                "run_id": "run",
                "mode": "base",
                "release_ready": True,
                "gate5_pass": True,
                "gate6_pass": True,
                "han_equal": True,
            }
            release = {
                **release_payload,
                "attestation_sha256": _sha(release_payload),
            }
            result = promote_shadow_to_posting(
                db,
                "run",
                mode="base",
                approved_rule_ids={"test-rule"},
                release_ready=True,
                authorize=True,
                family_approval_attestation=approval,
                release_attestation=release,
                production_account_mapping={
                    "기타비용": "기타비용",
                    CARD_CLEARING_ACCOUNT: CARD_CLEARING_ACCOUNT,
                },
            )
            self.assertTrue(result["passed"])
            self.assertEqual(result["status"], "posted_shadow")
            self.assertEqual(result["posted_payment_count"], 1)
            self.assertEqual(result["external_posting"], False)
            self.assertEqual(
                db.execute(
                    "SELECT posting_status FROM direct_accounting_posting_batches"
                ).fetchone()[0],
                "posted_shadow",
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0],
                0,
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
