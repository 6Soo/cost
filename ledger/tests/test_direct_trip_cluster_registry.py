import json
import unittest

from ledger.domain.direct_trip_cluster_registry import (
    ACTIVITY_PLACEHOLDER_TARGET_KIND,
    RESERVATION_PLACEHOLDER_TARGET_KIND,
    UNKNOWN_MIXED_ACTIVITY_PLACEHOLDER_RULE_ID,
    build_trip_cluster_registry,
    build_reservation_placeholder_registry,
    build_split_travel_activity_placeholder_registry,
    build_split_reversal_activity_placeholder_registry,
    build_travel_activity_placeholder_registry,
)


def _row(
    number, day, merchant, *, card4="1234", currency="JPY", foreign="",
):
    return {
        "payment_id": number,
        "direct_event_key": f"event-{number}",
        "current_fact_sha256": f"{number:064x}",
        "current_evidence_id": f"current-card:{number:064x}",
        "source": "HAN",
        "card4": card4,
        "occurred_on": day,
        "amount_krw": 1000 + number,
        "transaction_type": "purchase",
        "sub": "해외",
        "merchant": merchant,
        "biz": "일반",
        "currency": currency,
        "foreign": foreign,
    }


class TripClusterRegistryTest(unittest.TestCase):
    def test_requires_card_specific_multi_merchant_region_anchor(self):
        result = build_trip_cluster_registry([
            _row(1, "2026-02-01", "FAMILYMART TOKYO JP"),
            _row(2, "2026-02-02", "LAWSON TOKYO JP"),
            _row(3, "2026-02-03", "SUSHIRO TOKYO JP"),
        ], {}, [])
        self.assertEqual(len(result["registries"]), 1)
        registry = result["registries"][0]
        self.assertEqual(registry["region"], "도쿄")
        self.assertEqual(registry["target_kind"], "new_registry_target")
        self.assertTrue(registry["target_code"].startswith("임시여행_"))
        self.assertEqual(
            {row["payment_id"] for row in registry["members"]}, {1, 2, 3}
        )

    def test_one_city_marker_or_one_merchant_never_anchors(self):
        result = build_trip_cluster_registry([
            _row(1, "2026-02-01", "FAMILYMART TOKYO JP"),
            _row(2, "2026-02-02", "FAMILYMART TOKYO JP"),
            _row(3, "2026-02-03", "FAMILYMART TOKYO JP"),
        ], {}, [])
        self.assertEqual(result["registries"], [])

    def test_branch_suffixes_of_one_chain_do_not_count_as_two_merchants(self):
        result = build_trip_cluster_registry([
            _row(1, "2026-02-01", "FAMILYMART SHIBUYA TOKYO JP"),
            _row(2, "2026-02-02", "FAMILYMART SHINJUKU TOKYO JP"),
            _row(3, "2026-02-03", "FAMILYMART UENO TOKYO JP"),
        ], {}, [])
        self.assertEqual(result["registries"], [])

    def test_existing_period_with_wrong_region_is_a_conflict(self):
        result = build_trip_cluster_registry([
            _row(1, "2026-02-01", "FAMILYMART TOKYO JP"),
            _row(2, "2026-02-02", "LAWSON TOKYO JP"),
            _row(3, "2026-02-03", "SUSHIRO TOKYO JP"),
        ], {
            "wrong-region": {
                "tab": "wrong-region", "mm": 2, "dd": 1,
                "region": "오사카", "window": 3,
            },
        }, [])
        self.assertEqual(result["registries"], [])

    def test_partially_overlapping_wrong_region_is_also_a_conflict(self):
        result = build_trip_cluster_registry([
            _row(1, "2026-02-01", "FAMILYMART TOKYO JP"),
            _row(2, "2026-02-02", "LAWSON TOKYO JP"),
            _row(3, "2026-02-03", "SUSHIRO TOKYO JP"),
        ], {
            "wrong-region": {
                "tab": "wrong-region", "mm": 1, "dd": 31,
                "region": "오사카", "window": 2,
            },
        }, [])
        self.assertEqual(result["registries"], [])

    def test_context_schedule_is_not_recorded_as_canonical(self):
        result = build_trip_cluster_registry([
            _row(1, "2026-01-08", "7-ELEVEN TAIPEI TW", currency="TWD"),
            _row(2, "2026-01-09", "FAMILY MART TAICHUNG TW", currency="TWD"),
            _row(3, "2026-01-10", "SUSHIRO TAINAN TW", currency="TWD"),
        ], {}, [{
            "tab": "0107_대만", "mm": 1, "dd": 7, "region": "대만",
            "window": 8, "source_kind": "geographic_trip_context",
        }])
        self.assertEqual(len(result["registries"]), 1)
        self.assertEqual(result["registries"][0]["target_kind"], "context_schedule")

    def test_different_cards_are_not_mixed(self):
        result = build_trip_cluster_registry([
            _row(1, "2026-02-01", "FAMILYMART TOKYO JP", card4="1234"),
            _row(2, "2026-02-02", "LAWSON TOKYO JP", card4="5678"),
            _row(3, "2026-02-03", "SUSHIRO TOKYO JP", card4="1234"),
        ], {}, [])
        self.assertEqual(result["registries"], [])

    def test_currency_only_rows_attach_but_do_not_anchor(self):
        result = build_trip_cluster_registry([
            _row(1, "2026-02-01", "FAMILYMART TOKYO JP"),
            _row(2, "2026-02-02", "LAWSON TOKYO JP"),
            _row(3, "2026-02-03", "SUSHIRO TOKYO JP"),
            _row(4, "2026-02-03", "SUSHIRO", currency="JPY"),
        ], {}, [])
        self.assertEqual(len(result["registries"]), 1)
        self.assertEqual(
            {row["payment_id"] for row in result["registries"][0]["members"]},
            {1, 2, 3, 4},
        )

    def test_two_overlapping_countries_on_one_card_are_rejected(self):
        result = build_trip_cluster_registry([
            _row(1, "2026-02-01", "FAMILYMART TOKYO JP"),
            _row(2, "2026-02-02", "LAWSON TOKYO JP"),
            _row(3, "2026-02-03", "SUSHIRO TOKYO JP"),
            _row(4, "2026-02-02", "NIGHT MARKET BANGKOK TH"),
            _row(5, "2026-02-03", "MALL BANGKOK TH"),
            _row(6, "2026-02-04", "CAFE BANGKOK TH"),
        ], {}, [])
        self.assertEqual(result["registries"], [])

    def test_activity_placeholder_is_use_window_only_and_not_currency_country(self):
        result = build_travel_activity_placeholder_registry([
            _row(1, "2026-02-01", "FAMILYMART TOKYO JP", currency="USD"),
            _row(2, "2026-02-02", "LAWSON TOKYO JP", currency="USD"),
        ], {}, [])
        self.assertEqual(len(result["registries"]), 1)
        registry = result["registries"][0]
        self.assertEqual(registry["target_kind"], ACTIVITY_PLACEHOLDER_TARGET_KIND)
        self.assertEqual(registry["country"], "JP")
        self.assertEqual(registry["region"], "도쿄")
        payload = json.loads(registry["payload_json"])
        self.assertEqual(payload["audit"]["target_completeness"], "activity_only")
        self.assertTrue(payload["audit"]["payment_window_is_not_service_period"])
        self.assertFalse(payload["audit"]["currency_used_to_create_country"])

    def test_activity_placeholder_rejects_cross_country_run(self):
        result = build_travel_activity_placeholder_registry([
            _row(1, "2026-02-01", "FAMILYMART TOKYO JP"),
            _row(2, "2026-02-02", "LAWSON BANGKOK TH"),
        ], {}, [])
        self.assertEqual(result["registries"], [])

    def test_split_activity_does_not_regroup_small_or_unmarked_unknown_rows(self):
        result = build_split_travel_activity_placeholder_registry([
            _row(1, "2026-02-01", "SHOP TOKYO JP"),
            _row(2, "2026-02-01", "SHOP"),
            _row(3, "2026-02-02", "SHOP"),
            _row(4, "2026-02-02", "SHOP BANGKOK TH"),
        ], {}, [])
        unknown = [
            registry for registry in result["registries"]
            if registry["country"] == "UNKNOWN"
        ]
        self.assertEqual(unknown, [])
        self.assertEqual(set(result["by_payment"]), {1, 4})

    def test_split_activity_accepts_exactly_seven_positive_unknown_members(self):
        rows = [
            _row(100 + index, "2026-02-01", "SHOP")
            for index in range(7)
        ]
        rows.extend([
            _row(200, "2026-02-01", "SHOP TORONTO CA"),
            _row(201, "2026-02-02", "SHOP PARIS FR"),
        ])
        for row in rows[:7]:
            row["currency"] = "SGD"
            row["foreign"] = "1"

        result = build_split_travel_activity_placeholder_registry(
            rows, {}, [],
        )
        unknown = [
            registry for registry in result["registries"]
            if registry["country"] == "UNKNOWN"
        ]
        self.assertEqual(len(unknown), 7)
        self.assertEqual(
            {row["payment_id"] for registry in unknown
             for row in registry["members"]},
            set(range(100, 107)),
        )
        self.assertTrue(all(len(registry["members"]) == 1 for registry in unknown))
        self.assertTrue(all(
            json.loads(registry["payload_json"])["registry_core"]["rule_id"]
            == UNKNOWN_MIXED_ACTIVITY_PLACEHOLDER_RULE_ID
            for registry in unknown
        ))
        self.assertEqual(
            set(result["by_payment"]), set(range(100, 107)) | {200, 201},
        )

    def test_split_activity_excludes_krw_markerless_row_from_mixed_parent(self):
        rows = [
            _row(300, "2026-03-01", "SHOP", currency="SGD", foreign="1"),
            _row(301, "2026-03-01", "SHOP", currency="KRW", foreign=""),
            _row(302, "2026-03-02", "SHOP", currency="SGD", foreign="1"),
            _row(303, "2026-03-02", "SHOP TORONTO CA"),
            _row(304, "2026-03-03", "SHOP PARIS FR"),
        ]
        result = build_split_travel_activity_placeholder_registry(
            rows, {}, [],
        )
        self.assertEqual(
            {payment_id for payment_id in result["by_payment"]},
            {303, 304},
        )

    def test_unknown_mixed_activity_hash_is_stable_under_input_order(self):
        rows = [
            _row(400 + index, "2026-04-01", "SHOP", currency="SGD", foreign="1")
            for index in range(7)
        ]
        rows.extend([
            _row(500, "2026-04-01", "SHOP TORONTO CA"),
            _row(501, "2026-04-02", "SHOP PARIS FR"),
        ])
        first = build_split_travel_activity_placeholder_registry(rows, {}, [])
        second = build_split_travel_activity_placeholder_registry(
            list(reversed(rows)), {}, [],
        )
        def unknown_signature(result):
            return sorted(
                (
                    registry["target_code"],
                    registry["registry_sha256"],
                    registry["payload_json"],
                )
                for registry in result["registries"]
                if registry["country"] == "UNKNOWN"
            )
        self.assertEqual(unknown_signature(first), unknown_signature(second))

    def test_reservation_placeholder_keeps_service_period_unknown(self):
        row = _row(1, "2026-02-01", "AGODA TOKYO JP")
        row["sub"] = "국내"
        result = build_reservation_placeholder_registry([row], {}, [])
        self.assertEqual(len(result["registries"]), 1)
        registry = result["registries"][0]
        self.assertEqual(
            registry["target_kind"], RESERVATION_PLACEHOLDER_TARGET_KIND,
        )
        payload = json.loads(registry["payload_json"])
        self.assertEqual(
            payload["audit"]["service_period_status"],
            "unknown_not_payment_date",
        )

    def test_split_reversal_activity_keeps_explicit_countries_only(self):
        japan = _row(1, "2026-02-01", "SHOP TOKYO JP")
        japan["transaction_type"] = "refund"
        japan["amount_krw"] = -1001
        thailand = _row(2, "2026-02-02", "SHOP BANGKOK TH")
        thailand["transaction_type"] = "cancellation"
        thailand["amount_krw"] = -1002
        unknown = _row(3, "2026-02-02", "SHOP")
        unknown["transaction_type"] = "refund"
        unknown["amount_krw"] = -1003
        result = build_split_reversal_activity_placeholder_registry(
            [japan, thailand, unknown], {}, [],
        )
        self.assertEqual(
            {str(row["country"]) for row in result["registries"]},
            {"JP", "TH"},
        )
        self.assertEqual(set(result["by_payment"]), {1, 2})


if __name__ == "__main__":
    unittest.main()
