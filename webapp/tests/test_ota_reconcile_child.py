import os
import tempfile
import unittest
from pathlib import Path

from webapp import ota_payment_review


class ReconcileChildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("WEBLEDGER_OTA_REVIEW_DB")
        os.environ["WEBLEDGER_OTA_REVIEW_DB"] = str(Path(self.tmp) / "ota-review.sqlite")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("WEBLEDGER_OTA_REVIEW_DB", None)
        else:
            os.environ["WEBLEDGER_OTA_REVIEW_DB"] = self._prev

    def test_a_failing_reconciliation_in_the_child_is_reported_with_its_cause(self):
        """A board with no sources cannot reconcile; the parent must see why, not a silent success."""
        class Board:
            path = Path(self.tmp) / "board.sqlite"
            _reservation_authority = None

        with self.assertRaises(ota_payment_review.OtaReconcileChildError) as raised:
            ota_payment_review.reconcile_in_child(Board())
        self.assertIn(":", str(raised.exception))
        self.assertEqual(list(Path(self.tmp).glob("ota-reconcile-*")), [])


if __name__ == "__main__":
    unittest.main()
