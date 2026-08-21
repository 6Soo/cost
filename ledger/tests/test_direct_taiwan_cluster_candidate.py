import unittest

from ledger.domain.direct_taiwan_cluster_candidate import (
    build_taiwan_cluster_candidate,
    validate_taiwan_cluster_candidate,
)


class TaiwanClusterCandidateTest(unittest.TestCase):
    def _row(self, key, merchant, *, currency="KRW", transaction_type="purchase", day="2026-01-08"):
        return {
            "direct_event_key": key,
            "payment_id": int(key.rsplit(":", 1)[-1]),
            "current_evidence_id": f"evidence:{key}",
            "source_kind": "card_raw",
            "source_key": f"source:{key}",
            "source_sha256": "a" * 64,
            "current_fact_sha256": "b" * 64,
            "occurred_on": day,
            "amount_krw": 1000,
            "merchant": merchant,
            "currency": currency,
            "transaction_type": transaction_type,
        }

    def test_taiwan_marker_is_candidate_but_twd_only_is_corroboration(self):
        result = build_taiwan_cluster_candidate(
            [
                self._row("card:1", "HOTEL TAIPEI TW"),
                self._row("card:2", "CHUN SHUI TANG", currency="TWD"),
                self._row("card:3", "HOTEL TAIPEI TW", transaction_type="cancellation"),
                self._row("card:4", "HOTEL TAIPEI TW", day="2026-02-01"),
            ],
            [{"message_hash": "mail-hash", "provider": "agoda"}],
        )

        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(len(result["corroboration_only"]), 1)
        self.assertEqual(len(result["excluded_reversals"]), 1)
        self.assertEqual(result["manifest"]["gate5_credit"], 0)
        self.assertFalse(result["manifest"]["applied"])
        self.assertTrue(validate_taiwan_cluster_candidate(result)["passed"])

    def test_current_agoda_date_anchor_can_add_named_current_merchant(self):
        result = build_taiwan_cluster_candidate(
            [self._row("card:10", "AGODA.COM CHERNG YUA")],
            [{"message_hash": "mail-hash", "provider": "agoda"}],
        )
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(
            result["candidates"][0]["match_basis"],
            "current_card_plus_current_agoda_date_anchor",
        )


if __name__ == "__main__":
    unittest.main()
