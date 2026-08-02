import unittest
from unittest import mock

from ledger.domain import direct_all_period_corp_void_admission as voids


class AllPeriodCorpVoidAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = voids.build_all_period_corp_void_admission()

    def test_four_voids_resolve_without_cost_posting(self):
        manifest = self.result["manifest"]
        rows = self.result["resolutions"]
        self.assertEqual((manifest["resolved_event_delta"], manifest["full_classification_delta"],
                          manifest["accepted_union"], manifest["global_residual"]),
                         (4, 0, 1551, 3777))
        self.assertEqual((len(rows), {row["disposition"] for row in rows},
                          sum(row["posting_amount_krw"] for row in rows)),
                         (4, {"void_no_posting"}, 0))

    def test_authority_boundary(self):
        manifest = self.result["manifest"]
        self.assertEqual((manifest["authority_status"], manifest["posting_status"],
                          manifest["database_applied"]), ("unattested", "blocked", False))

    def test_historical_nonzero_rejected(self):
        real = voids.csv.DictReader
        class Rows:
            def __iter__(self):
                return iter([{"src": "CORP", "appr": key, "status": "승인취소",
                              "krw": "1" if index == 0 else "0"}
                             for index, key in enumerate(voids.TARGETS)])
        with mock.patch.object(voids.csv, "DictReader", return_value=Rows()), \
             self.assertRaisesRegex(ValueError, "historical_disposition"):
            voids._historical(voids.Path("ledger"))


if __name__ == "__main__":
    unittest.main()
