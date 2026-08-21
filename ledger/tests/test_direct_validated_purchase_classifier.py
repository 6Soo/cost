from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from ledger.domain import direct_validated_purchase_classifier as classifier
from ledger.domain.direct_validated_purchase_classifier import (
    EXPECTED_TRAINING_ROWS,
    _peer_model,
    _schedule_status,
    _training_rows,
)


class ValidatedPurchaseClassifierTest(unittest.TestCase):
    def test_target_historical_row_is_excluded_from_every_peer_model(self) -> None:
        target = {
            "excluded_row_sha256": "t" * 64,
            "historical_row_sha256": "t" * 64,
            "model_key": ("merchant",), "truth_account": "식비",
        }
        peers = [
            {
                "historical_row_sha256": str(index) * 64,
                "model_key": ("merchant",), "truth_account": "식비",
            }
            for index in range(1, 4)
        ]
        result = _peer_model(
            {("merchant",): [target, *peers]}, target, "model_key",
            ("truth_account",),
        )
        self.assertEqual(result["support"], 3)
        self.assertEqual(result["output"], ("식비",))
        self.assertNotIn("t" * 64, result["peer_hashes"])

    def test_peer_conflict_withholds_prediction(self) -> None:
        target = {
            "excluded_row_sha256": "t" * 64,
            "historical_row_sha256": "t" * 64,
            "model_key": ("merchant",), "truth_account": "식비",
        }
        peers = [
            {
                "historical_row_sha256": str(index) * 64,
                "model_key": ("merchant",),
                "truth_account": "식비" if index < 3 else "교통비",
            }
            for index in range(1, 4)
        ]
        result = _peer_model(
            {("merchant",): [target, *peers]}, target, "model_key",
            ("truth_account",),
        )
        self.assertEqual(result["support"], 3)
        self.assertIsNone(result["output"])
        self.assertFalse(result["unanimous"])

    def test_target_uid_content_and_label_changes_only_affect_scoring(self) -> None:
        peers = [
            {
                "historical_row_sha256": str(index) * 64,
                "model_key": ("merchant",), "truth_account": "식비",
            }
            for index in range(1, 4)
        ]

        def predict(
            target_hash: str, target_uid: str, target_label: str,
        ) -> tuple[str, ...] | None:
            target_seed = {
                "historical_row_sha256": target_hash,
                "historical_uid": target_uid,
                "model_key": ("merchant",),
                "truth_account": target_label,
            }
            target = {
                "excluded_row_sha256": target_hash,
                "model_key": ("merchant",),
            }
            return _peer_model(
                {("merchant",): [target_seed, *peers]}, target, "model_key",
                ("truth_account",),
            )["output"]

        before = predict("a" * 64, "old-uid", "교통비")
        after = predict("b" * 64, "changed-uid", "숙박비")
        self.assertEqual(before, ("식비",))
        self.assertEqual(after, before)
        self.assertTrue(before == ("식비",))
        self.assertFalse(after == ("숙박비",))

    def test_full_build_keeps_target_prediction_and_model_fingerprint_invariant(self) -> None:
        training = []
        current = []
        for index in range(4):
            uid = f"old-{index}"
            payload = {
                "uid": uid, "src": "KBD", "use_date": "2026-04-01",
                "post_date": "2026-04-01", "card4": f"10{index:02d}",
                "merchant": "동일상점", "biz": "음식", "currency": "KRW",
                "krw": str(100 + index), "bucket": "trip-a",
                "account": "식비", "cancel": "false",
                "cost_type": "여행원가", "appr": str(9000 + index),
                "confidence": "high", "tax_conf": "ignored",
            }
            training.append({
                "uid": uid, "row_sha256": classifier._sha(payload),
                "payload": payload,
            })
            current.append({
                "direct_event_key": f"event-{index}", "payment_id": index + 1,
                "amount_krw": 100 + index, "source": "KBD",
                "occurred_on": "2026-04-01", "posted_on": "2026-04-01",
                "merchant": "동일상점", "approval": str(9000 + index),
                "transaction_type": "purchase" if index == 0 else "refund",
                "card4": f"10{index:02d}", "biz": "음식", "currency": "KRW",
                "current_evidence_id": f"evidence-{index}",
                "current_fact_sha256": classifier._sha({"event": index}),
            })

        class Result:
            def fetchone(self) -> tuple[str, int]:
                return classifier.TRAINING_SOURCE_SHA256, classifier.EXPECTED_TRAINING_ROWS

        class Database:
            def execute(self, sql: str, params: object = ()) -> Result:
                self.last = (sql, params)
                return Result()

        trips = {
            "trip-a": {"starts_on": "2026-04-01", "ends_on": "2026-04-01"},
        }

        def build(rows: list[dict[str, object]]) -> dict[str, object]:
            with (
                patch.object(classifier, "_load_training", return_value=rows),
                patch.object(classifier, "_load_current", return_value=current),
                patch.object(classifier, "load_trip_schedule", return_value=trips),
                patch.object(classifier, "_existing_nonclassifier_decisions", return_value=0),
            ):
                return classifier._build_expected(Database(), "run")

        baseline = build(training)
        changed = copy.deepcopy(training)
        changed_payload = changed[0]["payload"]
        assert isinstance(changed_payload, dict)
        changed_payload.update({
            "uid": "changed-uid", "account": "숙박비",
            "confidence": "changed", "tax_conf": "changed",
        })
        changed[0]["uid"] = "changed-uid"
        changed[0]["row_sha256"] = classifier._sha(changed_payload)
        changed_result = build(changed)

        adverse = copy.deepcopy(training)
        adverse_payload = adverse[0]["payload"]
        assert isinstance(adverse_payload, dict)
        adverse_payload.update({"uid": "adverse-uid", "account": "검토필요"})
        adverse[0]["uid"] = "adverse-uid"
        adverse[0]["row_sha256"] = classifier._sha(adverse_payload)
        adverse_result = build(adverse)

        def target_prediction(result: dict[str, object]) -> dict[str, object]:
            predictions = result["predictions"]
            assert isinstance(predictions, list)
            return next(row for row in predictions if row["direct_event_key"] == "event-0")

        invariant_fields = (
            "model_id", "loo_model_sha256", "prediction_id",
            "prediction_sha256", "account", "cost_type", "allocation_target",
        )
        expected_prediction = target_prediction(baseline)
        for result in (changed_result, adverse_result):
            actual_prediction = target_prediction(result)
            self.assertEqual(
                {name: expected_prediction[name] for name in invariant_fields},
                {name: actual_prediction[name] for name in invariant_fields},
            )
            self.assertEqual(
                baseline["model"]["model_id"], result["model"]["model_id"],
            )
            self.assertNotEqual(
                baseline["model"]["run_state_sha256"],
                result["model"]["run_state_sha256"],
            )

        self.assertTrue(baseline["validations"][0]["agrees"])
        self.assertFalse(changed_result["validations"][0]["agrees"])
        self.assertEqual(
            adverse_result["validations"][0]["validation_status"],
            "adverse_truth",
        )

    def test_unique_schedule_contradiction_blocks_but_ambiguity_does_not_support(self) -> None:
        trips = {
            "trip-a": {"starts_on": "2026-04-01", "ends_on": "2026-04-03"},
            "trip-b": {"starts_on": "2026-04-02", "ends_on": "2026-04-04"},
        }
        self.assertEqual(
            _schedule_status("2026-04-01", "trip-b", trips),
            (None, ["trip-a"]),
        )
        self.assertEqual(
            _schedule_status("2026-04-02", "trip-a", trips),
            ("ambiguous_match", ["trip-a", "trip-b"]),
        )

    def test_frozen_learning_snapshot_has_expected_census(self) -> None:
        raw = Path("ledger/data/classified_v14.csv").read_bytes()
        self.assertEqual(len(_training_rows(raw)), EXPECTED_TRAINING_ROWS)


if __name__ == "__main__":
    unittest.main()
