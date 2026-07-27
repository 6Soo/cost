from __future__ import annotations

import unittest

from ledger.domain.card_group_matching import (
    balanced_exact_card_groups,
    balanced_exact_card_keys,
    balanced_blank_merchant_card_groups,
    classify_unresolved_card_lineage,
    enrich_unique_card_identifiers,
    lifecycle_event_set_gate,
    unique_exact_structural_card_links,
    unique_approval_card_links,
)


class CardGroupMatchingTest(unittest.TestCase):
    def test_two_same_amount_lifecycles_require_all_four_distinct_raw_events(self) -> None:
        # KBD raw F:426/F:31 and F:427/F:32 are not duplicate ingestion.
        # The cancellation approvals and their distinct original approvals
        # identify two independent full-cancellation lifecycles.
        raw = [
            {
                "src": "KBD", "raw_record_id": raw_id, "c4": "8835",
                "use": "2026-04-22", "amt": 337406, "cx": cancelled,
                "appr": approval, "orig": original,
            }
            for raw_id, cancelled, approval, original in (
                ("F:426", False, "30100002", ""),
                ("F:31", True, "40138659", "30100002"),
                ("F:427", False, "30100024", ""),
                ("F:32", True, "40138660", "30100024"),
            )
        ]
        projected = [
            {
                "uid": uid, "src": "KBD", "card4": "8835",
                "use_date": "2026-04-22", "krw": amount,
                "appr": approval, "orig_appr": original,
            }
            for uid, amount, approval, original in (
                ("KBD-0818", "337406", "30100002", ""),
                ("KBD-0368", "-337406", "40138659", "30100002"),
                ("KBD-0819", "337406", "30100024", ""),
                ("KBD-0369", "-337406", "40138660", "30100024"),
            )
        ]
        self.assertTrue(lifecycle_event_set_gate(projected, raw)["passed"])

        # A legacy projection that retains only the first pair has lost the
        # second independent lifecycle; it cannot be dismissed as dedupe.
        loss = lifecycle_event_set_gate(projected[:2], raw)
        self.assertFalse(loss["passed"])
        self.assertEqual(loss["raw_event_count"], 4)
        self.assertEqual(loss["projected_event_count"], 2)
        self.assertEqual(
            {locator for item in loss["missing_raw_events"] for locator in item["raw_locators"]},
            {"KBD:F:32", "KBD:F:427"},
        )

    def test_lifecycle_gate_rejects_duplicate_consumption_of_one_raw_event(self) -> None:
        raw = [{
            "src": "KBD", "raw_record_id": "F:426", "c4": "8835",
            "use": "2026-04-22", "amt": 337406, "cx": False,
            "appr": "30100002", "orig": "",
        }]
        projected = [{
            "uid": uid, "src": "KBD", "card4": "8835",
            "use_date": "2026-04-22", "krw": "337406",
            "appr": "30100002", "orig_appr": "",
        } for uid in ("KBD-0818", "KBD-DUPLICATE")]
        report = lifecycle_event_set_gate(projected, raw)
        self.assertFalse(report["passed"])
        self.assertEqual(report["overconsumed_raw_events"][0]["count"], 1)

    def test_same_amount_raw_refunds_need_distinct_original_approvals(self) -> None:
        raw = [
            {
                "src": "KBD", "raw_record_id": raw_id, "c4": "8835",
                "use": "2026-04-14", "amt": 125398, "cx": cancelled,
                "appr": approval, "orig": original,
            }
            for raw_id, cancelled, approval, original in (
                ("F:465", True, "47662906", "30099256"),
                ("F:482", False, "30099256", ""),
                ("F:466", True, "47662917", "30099278"),
                ("F:484", False, "30099278", ""),
            )
        ]
        projection = [
            {
                "uid": uid, "src": "KBD", "card4": "8835",
                "use_date": "2026-04-14", "krw": amount,
                "appr": approval, "orig_appr": original,
            }
            for uid, amount, approval, original in (
                ("KBD-0778", "-125398", "47662906", "30099256"),
                ("KBD-0779", "125398", "30099256", ""),
                ("KBD-0780", "-125398", "47662917", "30099278"),
                ("KBD-0781", "125398", "30099278", ""),
            )
        ]
        self.assertTrue(lifecycle_event_set_gate(projection, raw)["passed"])
        # Losing the second positive must leave the second lifecycle open;
        # it cannot be absorbed by the equal amount of the first pair.
        loss = lifecycle_event_set_gate(projection[:-1], raw)
        self.assertFalse(loss["passed"])
        self.assertEqual(loss["missing_raw_events"][0]["raw_locators"], ["KBD:F:484"])

    def test_approval_less_overseas_refunds_are_covered_as_a_group_not_linked_to_travel(self) -> None:
        # KBO E:1217/E:1218 are distinct Trip.com cancellation RAW events.
        # The overseas feed has no approval/original-approval fields, so the
        # only safe conclusion is two-event source coverage, not a guessed
        # original transaction or booking link.
        base = [
            {
                "uid": uid, "src": "KBO", "use_date": "2026-04-07",
                "krw": "-893170", "merchant": "TRIP.COM",
            }
            for uid in ("KBO-0346", "KBO-0347")
        ]
        raw = [
            {
                "src": "KBO", "raw_record_id": raw_id, "co": "ISSUER",
                "use": "2026-04-07", "amt": 893170, "cx": True,
                "mer": "TRIP.COM", "appr": "",
            }
            for raw_id in ("E:1217", "E:1218")
        ]
        groups = balanced_exact_card_groups(base, raw, {"KBO": "ISSUER"})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["raw_ids"], ["KBO:E:1217", "KBO:E:1218"])
        self.assertEqual(groups[0]["match_scope"], "multiset_exact")
        self.assertFalse(groups[0]["individual_identity_confirmed"])

    def test_original_approval_selects_one_of_two_same_amount_charges(self) -> None:
        raw = [
            {
                "src": "KBD", "raw_record_id": raw_id, "c4": "9800",
                "use": "2026-05-04", "amt": amount, "cx": cancelled,
                "appr": approval, "orig": original,
            }
            for raw_id, amount, cancelled, approval, original in (
                ("F:361", 395506, False, "30101205", ""),
                ("F:370", 395506, False, "30101283", ""),
                ("F:328", 324912, True, "46499378", "30101283"),
            )
        ]
        projection = [
            {
                "uid": uid, "src": "KBD", "card4": "9800",
                "use_date": "2026-05-04", "krw": amount,
                "appr": approval, "orig_appr": original,
            }
            for uid, amount, approval, original in (
                ("KBD-0867", "395506", "30101205", ""),
                ("KBD-0874", "395506", "30101283", ""),
                ("KBD-0873", "-324912", "46499378", "30101283"),
            )
        ]
        self.assertTrue(lifecycle_event_set_gate(projection, raw)["passed"])

    def test_raw_discovered_cancel_requires_its_own_source_event(self) -> None:
        raw = [
            {
                "src": "KBD", "raw_record_id": raw_id, "c4": "8835",
                "use": "2026-05-27", "amt": 68720, "cx": cancelled,
                "appr": approval, "orig": original,
            }
            for raw_id, cancelled, approval, original in (
                ("F:277", False, "30102701", ""),
                ("F:255", True, "43940664", "30102701"),
            )
        ]
        projection = [
            {
                "uid": uid, "src": "KBD", "card4": "8835",
                "use_date": "2026-05-27", "krw": amount,
                "appr": approval, "orig_appr": original,
            }
            for uid, amount, approval, original in (
                ("KBD-0963", "68720", "30102701", ""),
                ("KBD-1106", "-68720", "43940664", "30102701"),
            )
        ]
        self.assertTrue(lifecycle_event_set_gate(projection, raw)["passed"])
        self.assertFalse(lifecycle_event_set_gate(projection[:1], raw)["passed"])

    def test_lifecycle_gate_distinguishes_five_refund_shapes(self) -> None:
        def raw(
            raw_id: str,
            amount: int,
            approval: str,
            *,
            cancelled: bool = False,
            original: str = "",
            **extra: object,
        ) -> dict[str, object]:
            return {
                "src": extra.pop("src", "KBD"),
                "raw_record_id": raw_id,
                "c4": "8835",
                "use": "2026-05-01",
                "amt": amount,
                "cx": cancelled,
                "appr": approval,
                "orig": original,
                **extra,
            }

        def projected(card: dict[str, object], uid: str) -> dict[str, object]:
            amount = int(card["amt"])
            cancelled = bool(card["cx"])
            return {
                "uid": uid,
                "src": card["src"],
                "card4": card["c4"],
                "use_date": card["use"],
                "krw": -amount if cancelled else amount,
                "cancel": cancelled,
                "appr": card["appr"],
                "orig_appr": card["orig"],
            }

        # 1:N is valid when cumulative refunds stay within the original.
        # Observed KBD-0861..0865: one 3,893,400 approval has four refund
        # legs. The four legs exactly exhaust, rather than over-refund, gross.
        one_to_many_raw = [
            raw("classified:KBD-0861", 3893400, "30101185"),
            raw(
                "classified:KBD-0862", 1730400, "43032904",
                cancelled=True, original="30101185",
            ),
            raw(
                "classified:KBD-0863", 216300, "43032881",
                cancelled=True, original="30101185",
            ),
            raw(
                "classified:KBD-0864", 216300, "43032870",
                cancelled=True, original="30101185",
            ),
            raw(
                "classified:KBD-0865", 1730400, "43032892",
                cancelled=True, original="30101185",
            ),
        ]
        one_to_many = lifecycle_event_set_gate(
            [projected(card, f"LEG-{index}")
             for index, card in enumerate(one_to_many_raw)],
            one_to_many_raw,
        )
        self.assertTrue(one_to_many["passed"])
        self.assertEqual(
            one_to_many["one_to_many_refund_groups"][0]["residual_krw"],
            0,
        )

        # The same 1:N shape becomes a blocker when refunds exceed gross.
        over_raw = [
            raw("F:10", 100000, "30000010"),
            raw("F:11", 70000, "40000010", cancelled=True, original="30000010"),
            raw("F:12", 40000, "40000011", cancelled=True, original="30000010"),
        ]
        over = lifecycle_event_set_gate(
            [projected(card, f"OVER-{index}")
             for index, card in enumerate(over_raw)],
            over_raw,
        )
        self.assertFalse(over["passed"])
        self.assertEqual(over["over_refunded_groups"][0]["residual_krw"], -10000)

        # A cancellation projected with a positive sign cannot pass merely
        # because its amount and approval match RAW.
        sign_raw = [
            raw(
                "F:20", 50000, "40000020",
                cancelled=True, original="30000020",
                outside_source_window=True,
            )
        ]
        sign_projection = [projected(sign_raw[0], "SIGN-1")]
        sign_projection[0]["krw"] = 50000
        sign = lifecycle_event_set_gate(sign_projection, sign_raw)
        self.assertFalse(sign["passed"])
        self.assertEqual(
            sign["sign_errors"][0]["reason"],
            "cancelled_projection_not_negative",
        )

        # A disclosed outside-window original is an exception, not a false
        # over-refund or a fabricated in-window purchase.
        outside_raw = [
            raw(
                "classified:KBO-0346", 893170, "",
                cancelled=True, original="",
                outside_source_window=True, src="KBO",
                sub="해외", cur="JPY",
            )
        ]
        outside = lifecycle_event_set_gate(
            [projected(outside_raw[0], "OUTSIDE-1")],
            outside_raw,
        )
        self.assertTrue(outside["passed"])
        self.assertEqual(
            outside["lifecycle_exceptions"][0]["reason"],
            "original_outside_source_window",
        )

        # KB overseas files may lack orig_appr. Keep the raw refund event and
        # label the issuer-specific exception; never invent an original.
        overseas_raw = [
            raw(
                "classified:KBO-2833", 421101, "", cancelled=True,
                src="KBO", sub="해외", cur="USD",
            )
        ]
        overseas = lifecycle_event_set_gate(
            [projected(overseas_raw[0], "KBO-2833")],
            overseas_raw,
        )
        self.assertTrue(overseas["passed"])
        self.assertEqual(
            overseas["lifecycle_exceptions"][0]["reason"],
            "kbo_overseas_original_approval_unavailable",
        )

    def test_two_equal_charges_are_preserved_and_consumed_as_two_events(self) -> None:
        base = [
            {
                "uid": f"KBO-{index}",
                "src": "KBO",
                "use_date": "2026-06-26",
                "krw": "116935",
                "merchant": "AGODA.COM",
            }
            for index in (1, 2)
        ]
        cards = [
            {
                "src": "KBO",
                "raw_record_id": f"E:{row}",
                "co": "국민",
                "use": "2026-06-26",
                "amt": 116935,
                "cx": False,
                "mer": "AGODA.COM",
            }
            for row in (879, 880)
        ]
        self.assertEqual(
            balanced_exact_card_keys(base, cards, {"KBO": "국민"}),
            {"KBO:E:879", "KBO:E:880"},
        )

    def test_cardinality_mismatch_remains_for_review(self) -> None:
        base = [
            {
                "uid": "KBO-1",
                "src": "KBO",
                "use_date": "2026-06-26",
                "krw": "116935",
                "merchant": "AGODA.COM",
            }
        ]
        cards = [
            {
                "src": "KBO",
                "raw_record_id": f"E:{row}",
                "co": "국민",
                "use": "2026-06-26",
                "amt": 116935,
                "cx": False,
                "mer": "AGODA.COM",
            }
            for row in (879, 880)
        ]
        self.assertFalse(balanced_exact_card_keys(base, cards, {"KBO": "국민"}))

    def test_approval_less_repeated_rows_are_group_only_not_individual_links(self) -> None:
        base = [
            {
                "uid": f"KBO-{index}",
                "src": "KBO",
                "use_date": "2026-04-29",
                "krw": "1423",
                "merchant": "KATAYAMAZUONSEN NAGAYA",
            }
            for index in range(5)
        ]
        cards = [
            {
                "src": "KBO",
                "raw_record_id": f"E:{row}",
                "co": "국민",
                "use": "2026-04-29",
                "amt": 1423,
                "cx": False,
                "mer": "KATAYAMAZUONSEN NAGAYA",
                "appr": "",
            }
            for row in range(1081, 1086)
        ]
        groups = balanced_exact_card_groups(base, cards, {"KBO": "국민"})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["match_scope"], "multiset_exact")
        self.assertFalse(groups[0]["individual_identity_confirmed"])
        self.assertEqual(len(groups[0]["base_ids"]), 5)
        self.assertEqual(len(groups[0]["raw_ids"]), 5)

    def test_unique_refund_restores_cancel_and_original_approval(self) -> None:
        classified = [
            {
                "uid": "KBD-1106",
                "src": "KBD",
                "use_date": "2026-05-27",
                "merchant": "트립닷컴(구)_NICE",
                "krw": "-68720",
                "appr": "",
                "orig_appr": "",
            }
        ]
        cards = [
            {
                "src": "KBD",
                "raw_record_id": "F:93",
                "use": "2026-05-27",
                "mer": "트립닷컴(구)_NICE",
                "amt": 68720,
                "cx": True,
                "appr": "cancel-approval",
                "orig": "original-approval",
            }
        ]
        updates = enrich_unique_card_identifiers(classified, cards)
        self.assertEqual(classified[0]["appr"], "cancel-approval")
        self.assertEqual(classified[0]["orig_appr"], "original-approval")
        self.assertEqual(len(updates), 1)

    def test_blank_raw_merchant_does_not_hide_unique_cancel_approvals(self) -> None:
        classified = [
            {
                "uid": uid,
                "src": "KBD",
                "card4": "8835",
                "use_date": "2026-05-04",
                "merchant": "트립닷컴",
                "krw": amount,
                "appr": approval,
            }
            for uid, amount, approval in (
                ("KBD-0862", "-1730400", "43032904"),
                ("KBD-0865", "-1730400", "43032892"),
            )
        ]
        cards = [
            {
                "src": "KBD",
                "raw_record_id": raw_id,
                "co": "국민",
                "c4": "8835",
                "use": "2026-05-04",
                "amt": 1730400,
                "cx": True,
                "mer": "",
                "appr": approval,
            }
            for raw_id, approval in (
                ("F:359", "43032904"),
                ("F:372", "43032892"),
            )
        ]
        links = unique_approval_card_links(
            classified,
            cards,
            {"KBD": "국민"},
        )
        self.assertEqual(
            {(link["uid"], link["raw_id"]) for link in links},
            {("KBD-0862", "KBD:F:359"), ("KBD-0865", "KBD:F:372")},
        )

    def test_one_raw_event_cannot_be_direct_linked_to_two_base_rows(self) -> None:
        classified = [
            {
                "uid": uid,
                "src": "KBD",
                "card4": "9800",
                "use_date": "2026-05-04",
                "merchant": "트립닷컴",
                "krw": "-216300",
                "appr": "43032881",
            }
            for uid in ("KBD-DUP-1", "KBD-DUP-2")
        ]
        cards = [
            {
                "src": "KBD",
                "raw_record_id": "F:360",
                "co": "국민",
                "c4": "9800",
                "use": "2026-05-04",
                "amt": 216300,
                "cx": True,
                "mer": "",
                "appr": "43032881",
            }
        ]
        self.assertFalse(
            unique_approval_card_links(
                classified,
                cards,
                {"KBD": "국민"},
            )
        )

    def test_approval_amount_cannot_override_known_date_or_merchant_conflict(self) -> None:
        base = [
            {
                "uid": "KBD-CONFLICT",
                "src": "KBD",
                "card4": "8835",
                "use_date": "2026-05-20",
                "merchant": "HERTZ INTERNATIONAL",
                "krw": "543947",
                "appr": "00305072",
            }
        ]
        cards = [
            {
                "src": "KBD",
                "raw_record_id": "F:331",
                "co": "ISSUER",
                "c4": "8835",
                "use": "2026-05-22",
                "amt": 543947,
                "cx": False,
                "mer": "AVIS BUDGET",
                "appr": "00305072",
            }
        ]
        issuer = {"KBD": "ISSUER"}
        self.assertFalse(unique_approval_card_links(base, cards, issuer))
        self.assertFalse(unique_exact_structural_card_links(base, cards, issuer))
        self.assertEqual(
            classify_unresolved_card_lineage(base, cards, issuer),
            {"approval_only_blocked": 1},
        )

    def test_unique_exact_structural_link_allows_blank_raw_merchant(self) -> None:
        base = [{
            "uid": "KBD-1", "src": "KBD", "card4": "8835",
            "use_date": "2026-05-20", "merchant": "HERTZ INTERNATIONAL",
            "krw": "543947", "appr": "",
        }]
        cards = [{
            "src": "KBD", "raw_record_id": "F:201", "co": "국민",
            "c4": "8835", "use": "2026-05-20", "amt": 543947,
            "cx": False, "mer": "", "appr": "not-used",
        }]
        self.assertEqual(
            unique_exact_structural_card_links(base, cards, {"KBD": "국민"}),
            [{"uid": "KBD-1", "raw_id": "KBD:F:201", "source_identity": "structural_exact"}],
        )

    def test_structural_link_repairs_exact_posting_date_copied_as_use_date(self) -> None:
        base = [{
            "uid": "KBO-1", "src": "KBO", "card4": "8835",
            "use_date": "2026-04-13", "post_date": "2026-04-13",
            "merchant": "AGODA.COM HOTEL PEAR", "currency": "JPY",
            "foreign": "10816", "krw": "102732", "appr": "",
        }]
        cards = [{
            "src": "KBO", "raw_record_id": "E:1222", "co": "국민",
            "c4": "8835", "use": "2026-04-06", "bill": "2026-04-13",
            "amt": 102732, "cx": False, "mer": "AGODA.COM HOTEL PEAR",
            "cur": "JPY", "fx": "10816", "appr": "",
        }]
        self.assertEqual(
            unique_exact_structural_card_links(
                base, cards, {"KBO": "국민"}
            ),
            [{
                "uid": "KBO-1",
                "raw_id": "KBO:E:1222",
                "source_identity": "structural_exact_post_date_repair",
            }],
        )

    def test_posting_date_repair_requires_both_legacy_dates_to_equal_posting_date(self) -> None:
        base = [{
            "uid": "KBO-1", "src": "KBO", "card4": "8835",
            "use_date": "2026-04-13", "post_date": "2026-04-14",
            "merchant": "AGODA.COM HOTEL PEAR", "krw": "102732",
        }]
        cards = [{
            "src": "KBO", "raw_record_id": "E:1222", "co": "국민",
            "c4": "8835", "use": "2026-04-06", "bill": "2026-04-13",
            "amt": 102732, "cx": False, "mer": "AGODA.COM HOTEL PEAR",
        }]
        self.assertFalse(
            unique_exact_structural_card_links(
                base, cards, {"KBO": "국민"}
            )
        )

    def test_structural_link_does_not_use_approval_by_itself(self) -> None:
        base = [{
            "uid": "KBD-1", "src": "KBD", "card4": "8835",
            "use_date": "", "merchant": "HERTZ INTERNATIONAL",
            "krw": "543947", "appr": "00226223",
        }]
        cards = [{
            "src": "KBD", "raw_record_id": "F:201", "co": "국민",
            "c4": "8835", "use": "2026-05-20", "amt": 543947,
            "cx": False, "mer": "HERTZ INTERNATIONAL", "appr": "00226223",
        }]
        self.assertFalse(unique_exact_structural_card_links(base, cards, {"KBD": "국민"}))
        self.assertEqual(
            classify_unresolved_card_lineage(base, cards, {"KBD": "국민"}),
            {"missing_date": 1},
        )

    def test_structural_link_treats_conflicting_approval_as_a_blocker(self) -> None:
        base = [{
            "uid": "KBD-1", "src": "KBD", "card4": "8835",
            "use_date": "2026-05-20", "merchant": "HERTZ INTERNATIONAL",
            "krw": "543947", "appr": "00226223",
        }]
        cards = [{
            "src": "KBD", "raw_record_id": "F:201", "co": "국민",
            "c4": "8835", "use": "2026-05-20", "amt": 543947,
            "cx": False, "mer": "HERTZ INTERNATIONAL", "appr": "99999999",
        }]
        self.assertFalse(unique_exact_structural_card_links(base, cards, {"KBD": "국민"}))

    def test_blank_merchant_group_preserves_explicit_n_to_m_coverage(self) -> None:
        base = [
            {
                "uid": f"KBO-{index}", "src": "KBO", "card4": "8835",
                "use_date": "2026-05-20", "merchant": f"HOTEL-{index}", "krw": "543947",
            }
            for index in (1, 2)
        ]
        cards = [
            {
                "src": "KBO", "raw_record_id": f"E:{row}", "co": "국민",
                "c4": "8835", "use": "2026-05-20", "amt": 543947,
                "cx": False, "mer": "", "appr": "",
            }
            for row in (201, 202)
        ]
        groups = balanced_blank_merchant_card_groups(base, cards, {"KBO": "국민"})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["match_scope"], "multiset_blank_merchant")
        self.assertFalse(groups[0]["individual_identity_confirmed"])

    def test_zero_amount_is_an_adjustment_disposition_not_a_card_link(self) -> None:
        base = [{
            "uid": "KBD-ZERO", "src": "KBD", "card4": "8835",
            "use_date": "2026-05-20", "merchant": "HERTZ INTERNATIONAL",
            "krw": "0", "appr": "00226223",
        }]
        cards = [{
            "src": "KBD", "raw_record_id": "F:201", "co": "국민",
            "c4": "8835", "use": "2026-05-20", "amt": 543947,
            "cx": False, "mer": "HERTZ INTERNATIONAL", "appr": "00226223",
        }]
        self.assertFalse(unique_exact_structural_card_links(base, cards, {"KBD": "국민"}))
        self.assertEqual(
            classify_unresolved_card_lineage(base, cards, {"KBD": "국민"}),
            {"zero_amount_adjustment": 1},
        )


if __name__ == "__main__":
    unittest.main()
