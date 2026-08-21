from __future__ import annotations

import sqlite3
import unittest

from ledger.domain.direct_2025_cost_accounting import (
    ACCOUNT,
    ALLOCATION_TARGET,
    COST_TYPE,
    RULE_ID,
    TARGET_TYPE,
    _policy_payload,
    validate_2025_cost_accounting,
)
from ledger.domain.direct_2025_payment_terminal import _effective_partition


class Direct2025CostAccountingTest(unittest.TestCase):
    def test_policy_is_accounting_only_and_has_no_travel_fallback(self) -> None:
        policy = _policy_payload()
        self.assertEqual(policy["payment_year"], 2025)
        self.assertEqual(policy["account"], ACCOUNT)
        self.assertEqual(policy["cost_type"], COST_TYPE)
        self.assertEqual(policy["allocation_target"], ALLOCATION_TARGET)
        self.assertEqual(policy["target_type"], TARGET_TYPE)
        self.assertEqual(policy["accounting_period"], "2025")
        self.assertFalse(policy["travel_eligible"])
        self.assertEqual(policy["service_period_source"], "none")
        self.assertEqual(policy["reservation_source"], "none")
        self.assertFalse(policy["reversal_inheritance"])
        self.assertIn("mail_backed_2026_or_2027_travel", policy["exclusions"])
        self.assertIn("settled_cancellation_or_refund", policy["exclusions"])

    def test_effective_partition_moves_only_explicit_cost_ids(self) -> None:
        census = {
            "rows_by_id": {
                1: {"external_key": "payment-a"},
                2: {"external_key": "payment-b"},
                3: {"external_key": "payment-c"},
            },
            "residual_ids": {1, 2},
            "category_keys": {
                "candidate": {"payment-a", "payment-b", "payment-c"},
                "cancellation": set(),
                "mail_travel": {"payment-c"},
                "excluded": set(),
            },
        }
        partition = _effective_partition(census, {1, 3})
        self.assertEqual(partition["cost_ids"], {1})
        self.assertEqual(partition["display_ids"], {2})
        self.assertEqual(
            partition["category_keys"]["cost_accounting"], {"payment-a"}
        )
        self.assertEqual(
            partition["category_keys"]["residual_terminal"], {"payment-b"}
        )

    def test_schema_has_accounting_audit_and_idempotency_columns(self) -> None:
        db = sqlite3.connect(":memory:")
        try:
            from ledger.domain.direct_projection import _apply_schema
            from ledger.domain.ledger_db import initialize

            # The projection schema validator expects the ordinary ledger
            # schema to be present before its extension tables are applied.
            initialize(db)
            _apply_schema(db)
            columns = {
                row[1] for row in db.execute(
                    "PRAGMA table_info(direct_2025_cost_accounting)"
                )
            }
            self.assertTrue({
                "accounting_period",
                "posting_date_source",
                "idempotency_key",
            } <= columns)
            self.assertEqual(
                db.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='direct_2025_cost_accounting'"
                ).fetchone()[0].count("UNIQUE(run_id,idempotency_key)"),
                1,
            )
        finally:
            db.close()

    def test_current_projection_requires_a_cost_manifest(self) -> None:
        db = sqlite3.connect(":memory:")
        try:
            from ledger.domain.direct_projection import _apply_schema
            from ledger.domain.ledger_db import initialize

            initialize(db)
            _apply_schema(db)
            result = validate_2025_cost_accounting(
                db, "missing-run", require_manifest=True
            )
            self.assertFalse(result["passed"])
            self.assertEqual(result["issues"], ["2025_cost_manifest_missing"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
