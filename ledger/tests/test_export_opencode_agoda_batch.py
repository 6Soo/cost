import unittest

from tools.export_opencode_agoda_batch import _date_observed


class DateObservationTests(unittest.TestCase):
    def test_accepts_unpadded_iso_from_browser_evidence(self) -> None:
        self.assertTrue(_date_observed("2026-02-27", '"ci":"2026-2-27"'))
        self.assertTrue(_date_observed("2026-03-01", '"co":"2026-3-1"'))

    def test_rejects_a_different_date(self) -> None:
        self.assertFalse(_date_observed("2026-02-27", '"ci":"2026-2-28"'))


if __name__ == "__main__":
    unittest.main()
