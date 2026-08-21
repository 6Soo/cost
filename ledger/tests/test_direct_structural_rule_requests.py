from __future__ import annotations

import json
import unittest

from ledger.domain.direct_structural_rule_requests import (
    build_structural_rule_request_report,
    simulate_structural_rule_admission,
)


class StructuralRuleRequestTest(unittest.TestCase):
    @staticmethod
    def _prediction(payment_id: int, vetoes: list[str], path: str) -> dict[str, object]:
        return {
            "payment_id": payment_id,
            "rule_path": f"card_taxonomy|{path}|cost:travel",
            "axis_evidence_json": json.dumps({
                "row_finality": {
                    "eligible": not vetoes,
                    "status": "final_eligible" if not vetoes else "nonfinal_veto",
                    "vetoes": vetoes,
                },
            }),
        }

    def test_groups_structural_vetoes_without_item_approval(self) -> None:
        report = build_structural_rule_request_report(
            [
                self._prediction(1, ["ota_lifecycle_not_closed"], "reservation_placeholder"),
                self._prediction(
                    2,
                    ["ota_lifecycle_not_closed", "ota_service_period_evidence_missing"],
                    "reservation_placeholder",
                ),
                self._prediction(3, ["review_or_provisional_target_path"], "activity_placeholder"),
            ],
            [1, 2, 3, 4],
        )
        self.assertEqual(report["nonfinal_payment_count"], 4)
        self.assertEqual(report["affected_payment_count"], 4)
        self.assertTrue(report["coverage_invariant"])
        self.assertEqual(report["item_level_approval"], "forbidden")
        self.assertFalse(report["rule_auto_authorization"])
        self.assertEqual(report["overlap_payment_count"], 1)
        families = {
            group["structural_failure_family"] for group in report["groups"]
        }
        self.assertIn("lifecycle_not_closed", families)
        self.assertIn("service_period_evidence_missing", families)
        self.assertIn("review_or_provisional_target", families)
        self.assertIn("classifier_prediction_missing", families)
        lifecycle_groups = [
            group for group in report["groups"]
            if group["structural_failure_family"] == "lifecycle_not_closed"
        ]
        self.assertEqual(
            sorted(group["veto_only_release_candidate_count"] for group in lifecycle_groups),
            [1],
        )
        for group in report["groups"]:
            self.assertNotIn("payment_id", group)
            self.assertNotIn("event_key", group)
            self.assertEqual(group["user_decision"]["item_level_approval"], "not_requested")

    def test_valid_payload_without_veto_is_not_silently_omitted(self) -> None:
        report = build_structural_rule_request_report(
            [self._prediction(1, [], "manual_exact")],
            [1],
        )
        self.assertEqual(report["rule_request_group_count"], 1)
        self.assertEqual(
            report["groups"][0]["structural_failure_family"],
            "unclassified_nonfinal",
        )
        self.assertTrue(report["coverage_invariant"])

    def test_request_exposes_aggregate_evidence_composition_only(self) -> None:
        prediction = self._prediction(1, ["review_or_provisional_target_path"], "external")
        payload = json.loads(str(prediction["axis_evidence_json"]))
        payload["target_evidence_refs"] = [
            {"source_kind": "card_raw", "evidence_role": "current_card_transaction_fact"},
            {"source_kind": "ota_mail", "evidence_role": "ota_service_period"},
            {"source_kind": "classifier_training", "evidence_role": "historical_context_only"},
        ]
        prediction["axis_evidence_json"] = json.dumps(payload)
        report = build_structural_rule_request_report([prediction], [1])
        group = report["groups"][0]
        self.assertEqual(group["evidence_composition_counts"], {"independent_plus_weak": 1})
        self.assertEqual(group["strict_evidence_role_counts"], {"service_period_role": 1})
        self.assertEqual(group["evidence_source_kind_counts"]["ota_mail"], 1)
        self.assertNotIn("payment_id", group)

    def test_empty_nonfinal_scope_has_no_request(self) -> None:
        report = build_structural_rule_request_report([], [])
        self.assertEqual(report["rule_request_group_count"], 0)
        self.assertEqual(report["affected_payment_count"], 0)
        self.assertTrue(report["coverage_invariant"])

    def test_package_simulation_is_staged_and_side_effect_free(self) -> None:
        predictions = [
            self._prediction(1, ["review_or_provisional_target_path"], "registry"),
            self._prediction(2, ["review_or_provisional_target_path"], "activity"),
            self._prediction(3, ["review_or_provisional_target_path"], "reservation"),
            self._prediction(4, ["review_or_provisional_target_path"], "external"),
        ]
        report = build_structural_rule_request_report(predictions, [1, 2, 3, 4])
        by_path = {
            group["classification_path"]: group["request_id"]
            for group in report["groups"]
        }
        result = simulate_structural_rule_admission(
            predictions,
            [1, 2, 3, 4],
            [
                by_path["registry"],
                by_path["activity"],
                by_path["reservation"],
                by_path["external"],
            ],
        )
        self.assertEqual(result["candidate_remaining_nonfinal_count"], 0)
        self.assertEqual(result["candidate_reduced_count"], 4)
        self.assertTrue(result["simulation_only"])
        self.assertFalse(result["side_effects_created"])
        self.assertEqual(
            [stage["newly_reduced_candidate_count"] for stage in result["stages"]],
            [1, 1, 1, 1],
        )


if __name__ == "__main__":
    unittest.main()
