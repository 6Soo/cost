from __future__ import annotations

import unittest

from tools.agoda_amount_candidate_graph import (
    PaymentAmount,
    ReservationAmount,
    resolve_candidate_graph,
)


class AgodaAmountCandidateGraphTests(unittest.TestCase):
    def test_universe_unique_exact_amount_promotes_singleton(self) -> None:
        result = resolve_candidate_graph(
            [ReservationAmount("r1", "KRW", 86411)],
            [PaymentAmount("p1", "KRW", 86411)],
            universe_sealed=True,
        )
        self.assertEqual(len(result["amount_candidates"]), 1)
        self.assertEqual(len(result["confirmed_individuals"]), 1)
        self.assertEqual(result["confirmed_individuals"][0]["tier"], "universe_unique_exact_amount")

    def test_foreign_currency_card4_forces_two_individuals(self) -> None:
        result = resolve_candidate_graph(
            [
                ReservationAmount("r1", "JPY", 22000, card4="1111"),
                ReservationAmount("r2", "JPY", 22000, card4="2222"),
            ],
            [
                PaymentAmount("p1", "JPY", 22000, card4="2222"),
                PaymentAmount("p2", "JPY", 22000, card4="1111"),
            ],
            universe_sealed=True,
        )
        self.assertEqual(len(result["confirmed_individuals"]), 2)
        self.assertEqual(len(result["confirmed_groups"]), 0)
        self.assertTrue(
            all(
                item["tier"] == "foreign_amount_card4_forced"
                for item in result["confirmed_individuals"]
            )
        )

    def test_known_card4_forces_edge_and_unknown_residual_is_singleton(self) -> None:
        result = resolve_candidate_graph(
            [
                ReservationAmount("r1", "JPY", 22000, card4="1111"),
                ReservationAmount("r2", "JPY", 22000),
            ],
            [
                PaymentAmount("p1", "JPY", 22000, card4="1111"),
                PaymentAmount("p2", "JPY", 22000, card4="2222"),
            ],
            universe_sealed=True,
        )
        pairs = {
            (item["reservation_key"], item["payment_key"], item["tier"])
            for item in result["confirmed_individuals"]
        }
        self.assertEqual(
            pairs,
            {
                ("r1", "p1", "foreign_amount_card4_forced"),
                ("r2", "p2", "universe_unique_exact_amount"),
            },
        )

    def test_equal_four_by_four_becomes_one_unordered_group(self) -> None:
        result = resolve_candidate_graph(
            [ReservationAmount(f"r{i}", "KRW", 86411) for i in range(4)],
            [PaymentAmount(f"p{i}", "KRW", 86411) for i in range(4)],
            universe_sealed=True,
        )
        self.assertEqual(len(result["confirmed_individuals"]), 0)
        self.assertEqual(len(result["confirmed_groups"]), 1)
        group = result["confirmed_groups"][0]
        self.assertEqual(group["member_count_each_side"], 4)
        self.assertFalse(group["individual_pair_asserted"])

    def test_unbalanced_cluster_is_held_without_partial_pair(self) -> None:
        result = resolve_candidate_graph(
            [
                ReservationAmount("r1", "KRW", 50000, card4="1111"),
                ReservationAmount("r2", "KRW", 50000),
            ],
            [PaymentAmount("p1", "KRW", 50000, card4="1111")],
            universe_sealed=True,
        )
        self.assertEqual(result["confirmed_individuals"], ())
        self.assertEqual(result["confirmed_groups"], ())
        self.assertEqual(result["held"][0]["reason"], "unbalanced_amount_candidate_cluster")

    def test_explicit_card4_conflict_is_held(self) -> None:
        result = resolve_candidate_graph(
            [ReservationAmount("r1", "JPY", 10000, card4="1111")],
            [PaymentAmount("p1", "JPY", 10000, card4="2222")],
            universe_sealed=True,
        )
        self.assertEqual(result["amount_candidates"], ())
        self.assertEqual(result["confirmed_individuals"], ())
        self.assertEqual(result["held"][0]["reason"], "card4_or_graph_conflict")

    def test_refund_never_matches_charge(self) -> None:
        result = resolve_candidate_graph(
            [ReservationAmount("r1", "KRW", 120000, event_kind="refund")],
            [PaymentAmount("p1", "KRW", 120000, event_kind="charge")],
            universe_sealed=True,
        )
        self.assertEqual(result["amount_candidates"], ())
        self.assertEqual(result["confirmed_individuals"], ())

    def test_charge_and_refund_cycles_resolve_in_separate_partitions(self) -> None:
        result = resolve_candidate_graph(
            [
                ReservationAmount("r-charge", "KRW", 120000, event_kind="charge"),
                ReservationAmount("r-refund", "KRW", 120000, event_kind="refund"),
            ],
            [
                PaymentAmount("p-refund", "KRW", 120000, event_kind="refund"),
                PaymentAmount("p-charge", "KRW", 120000, event_kind="charge"),
            ],
            universe_sealed=True,
        )
        self.assertEqual(
            {
                (item["reservation_key"], item["payment_key"])
                for item in result["confirmed_individuals"]
            },
            {("r-charge", "p-charge"), ("r-refund", "p-refund")},
        )

    def test_property_collect_is_noncompeting(self) -> None:
        result = resolve_candidate_graph(
            [
                ReservationAmount(
                    "r1",
                    "JPY",
                    10000,
                    competes_for_payment=False,
                    promotion_eligible=False,
                    hold_reason="property_collect_without_charge_event",
                )
            ],
            [PaymentAmount("p1", "JPY", 10000)],
            universe_sealed=True,
        )
        self.assertEqual(result["confirmed_individuals"], ())
        reasons = {item["reason"] for item in result["held"]}
        self.assertIn("property_collect_without_charge_event", reasons)

    def test_lifecycle_conflict_blocks_otherwise_unique_amount(self) -> None:
        result = resolve_candidate_graph(
            [ReservationAmount("r1", "KRW", 120000)],
            [
                PaymentAmount(
                    "p1",
                    "KRW",
                    120000,
                    promotion_eligible=False,
                    hold_reason="cancellation_settlement_member",
                )
            ],
            universe_sealed=True,
        )
        self.assertEqual(result["confirmed_individuals"], ())
        self.assertEqual(
            result["held"][0]["reason"],
            "nonpromotable_competitor_in_closed_cluster",
        )

    def test_unsealed_universe_never_promotes_and_order_is_deterministic(self) -> None:
        reservations = [
            ReservationAmount("r2", "KRW", 100),
            ReservationAmount("r1", "KRW", 100),
        ]
        payments = [PaymentAmount("p2", "KRW", 100), PaymentAmount("p1", "KRW", 100)]
        first = resolve_candidate_graph(reservations, payments, universe_sealed=False)
        second = resolve_candidate_graph(
            reversed(reservations), reversed(payments), universe_sealed=False
        )
        self.assertEqual(first, second)
        self.assertEqual(first["confirmed_individuals"], ())
        self.assertEqual(first["confirmed_groups"], ())
        self.assertEqual(first["held"][0]["reason"], "unsealed_universe")


if __name__ == "__main__":
    unittest.main()
