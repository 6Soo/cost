from __future__ import annotations

import unittest

from webapp.review_context import _attach_pipeline_recommendations


class PipelineRecommendationBridgeTests(unittest.TestCase):
    def test_unique_recorded_candidate_is_recommended_without_deciding(self):
        rows = [{
            "decision": "",
            "candidates": [
                {"key": "tx-1", "pipeline_recorded": True},
                {"key": "tx-2", "pipeline_recorded": False},
            ],
        }]

        _attach_pipeline_recommendations(rows)

        self.assertEqual(
            rows[0]["pipeline_recommendation"],
            {"candidate_key": "tx-1", "basis": "existing_reconciliation_unique"},
        )
        self.assertEqual(rows[0]["decision"], "")

    def test_candidate_reused_by_two_source_rows_is_not_recommended(self):
        rows = [
            {"decision": "", "candidates": [{"key": "tx-1", "pipeline_recorded": True}]},
            {"decision": "", "candidates": [{"key": "tx-1", "pipeline_recorded": True}]},
        ]

        _attach_pipeline_recommendations(rows)

        self.assertIsNone(rows[0]["pipeline_recommendation"])
        self.assertIsNone(rows[1]["pipeline_recommendation"])

    def test_unrecorded_candidate_is_not_recommended(self):
        rows = [{
            "decision": "",
            "candidates": [{"key": "tx-1", "pipeline_recorded": False}],
        }]

        _attach_pipeline_recommendations(rows)

        self.assertIsNone(rows[0]["pipeline_recommendation"])


if __name__ == "__main__":
    unittest.main()
