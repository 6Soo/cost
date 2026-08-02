import unittest

from ledger.domain import direct_all_period_source_coverage_census as census


class AllPeriodSourceCoverageCensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = census.build_all_period_source_coverage_census()

    def test_all_available_rows_are_included_without_period_filter(self):
        result = self.result
        self.assertEqual(result["raw_card_row_count"], 5237)
        self.assertEqual(result["normalized_event_count"], 5328)
        self.assertEqual(result["han_component_expansion_count"], 91)
        self.assertFalse(result["period_filter_applied"])
        self.assertEqual(result["available_input_rows_excluded"], 0)

    def test_source_date_ranges_are_explicit(self):
        self.assertEqual(self.result["source_coverage"], census.EXPECTED_SOURCES)
        self.assertEqual(self.result["earliest_available_date"], "2025-05-06")
        self.assertEqual(self.result["latest_available_date"], "2026-07-20")

    def test_does_not_claim_data_before_available_sources(self):
        self.assertFalse(self.result["pre_source_range_data_claimed"])
        self.assertFalse(self.result["database_applied"])


if __name__ == "__main__":
    unittest.main()
