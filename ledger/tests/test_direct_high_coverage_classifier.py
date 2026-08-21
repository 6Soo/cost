import unittest
import copy
from collections import Counter, defaultdict
from datetime import date

from ledger.domain.direct_high_coverage_classifier import (
    ACTIVITY_PLACEHOLDER_PATH,
    FEATURE_NAMES,
    GMAIL_EVIDENCE_SNAPSHOT_SHA256,
    INFERRED_EXTERNAL_TARGET_PATH,
    RESERVATION_PLACEHOLDER_PATH,
    TARGET_FEATURE_NAMES,
    TRIP_UNASSIGNED,
    _inherited_reversal_axes,
    _gmail_schedule_target,
    _manual_travel_amount_component_match,
    _manual_travel_match,
    _provisional_reversal_inheritance,
    _reversal_policy_fallback,
    _target_prediction,
    _account_prediction_with_external_evidence,
    _ota_mail_component_groups,
    _ota_mail_date_variants,
    _ota_mail_schedule_targets,
    _build_ota_mail_service_period_targets,
    OTA_AMOUNT_TOLERANCE_POLICY,
    OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH,
    OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH,
    _axis_evidence,
    _axis_evidence_contract_issues,
    _has_row_finality_veto,
    _activity_placeholder_candidate,
    GMAIL_EVIDENCE_SNAPSHOT_SHA256,
    GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH,
    MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
    MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH,
    OWNER_DECISION_CURRENT_SCOPE_PATH,
    REGISTRY_PATH,
    TRIP_CLUSTER_CANONICAL_EXACT_PATH,
)


def _empty_indexes():
    return {
        name: defaultdict(list)
        for name in (*FEATURE_NAMES, *TARGET_FEATURE_NAMES)
    }


class HighCoverageClassifierPolicyTests(unittest.TestCase):
    def test_missing_row_finality_fails_closed(self):
        self.assertTrue(_has_row_finality_veto({}))
        self.assertTrue(_has_row_finality_veto({"axis_evidence": {}}))
        self.assertTrue(_has_row_finality_veto({
            "axis_evidence": {"row_finality": {"eligible": False}},
        }))
        self.assertFalse(_has_row_finality_veto({
            "axis_evidence": {"row_finality": {"eligible": True}},
        }))

    def test_activity_placeholder_input_contract_is_narrow(self):
        base = {
            "amount_krw": 1000,
            "transaction_type": "purchase",
            "sub": "해외",
            "merchant": "SHOP TOKYO JP",
        }
        self.assertTrue(
            _activity_placeholder_candidate(
                base, "foreign_service_period_pending_review",
            )
        )
        self.assertFalse(
            _activity_placeholder_candidate(
                base, "geographic_context_period_missing",
            )
        )
        for override in (
            {"transaction_type": "refund"},
            {"sub": "국내"},
            {"merchant": "AGODA TOKYO JP"},
            {"merchant": "NICE 결제대행-Trip.com"},
            {"merchant": "SHOP TOKYO JP", "amount_krw": 0},
        ):
            row = {**base, **override}
            self.assertFalse(
                _activity_placeholder_candidate(
                    row, "foreign_service_period_pending_review",
                )
            )

    def test_ota_row_finality_binds_service_amount_and_latest_lifecycle_sources(self):
        row = {
            "source_kind": "card_raw",
            "source_key": "card-source-1",
            "source_sha256": "a" * 64,
            "direct_event_key": "card:" + "1" * 64 + "#single",
            "current_fact_sha256": "b" * 64,
        }
        ota_target = {
            "target_code": "0107_대만",
            "match_kind": "exact",
            "amount_match_method": "exact",
            "amount_difference_ratio": 0.0,
            "card_payment_ids": [1],
            "mail_identities": [["booking-1"]],
            "evidence_records": [{
                "source_kind": "ota_mail",
                "source_key": "service-1",
                "source_sha256": "c" * 64,
                "amount_source_key": "amount-1",
                "amount_source_sha256": "d" * 64,
                "amount_match_method": "exact",
                "amount_difference_ratio": 0.0,
                "lifecycle_latest_source_key": "latest-1",
                "lifecycle_latest_source_sha256": "e" * 64,
                "lifecycle_latest_status": "confirmation",
            }],
        }
        evidence = _axis_evidence(
            row,
            account="숙박비",
            cost_type="여행경비",
            target="0107_대만",
            account_path="test-account",
            target_path="ota_mail_service_period_exact",
            target_evidence_source="ota_mail",
            ota_service_target=ota_target,
        )
        prediction = {
            "account": "숙박비",
            "cost_type": "여행경비",
            "allocation_target": "0107_대만",
            "rule_path": "test|ota_mail_service_period_exact|cost:travel",
        }
        self.assertEqual(
            _axis_evidence_contract_issues(prediction, evidence, row), []
        )
        self.assertTrue(evidence["row_finality"]["eligible"])
        amountless_target = copy.deepcopy(ota_target)
        amountless_target["evidence_records"][0]["amount_source_sha256"] = ""
        amountless = _axis_evidence(
            row,
            account="숙박비",
            cost_type="여행경비",
            target="0107_대만",
            account_path="test-account",
            target_path="ota_mail_service_period_exact",
            target_evidence_source="ota_mail",
            ota_service_target=amountless_target,
        )
        self.assertIn(
            "ota_amount_source_binding_missing",
            amountless["row_finality"]["vetoes"],
        )
        cardinality_target = copy.deepcopy(ota_target)
        cardinality_target["mail_identities"].append(["booking-2"])
        cardinality = _axis_evidence(
            row,
            account="숙박비",
            cost_type="여행경비",
            target="0107_대만",
            account_path="test-account",
            target_path="ota_mail_service_period_exact",
            target_evidence_source="ota_mail",
            ota_service_target=cardinality_target,
        )
        self.assertIn(
            "ota_exact_card_mail_cardinality_invalid",
            cardinality["row_finality"]["vetoes"],
        )
        cancelled_target = copy.deepcopy(ota_target)
        cancelled_target["evidence_records"][0]["lifecycle_latest_status"] = "cancelled"
        cancelled = _axis_evidence(
            row,
            account="숙박비",
            cost_type="여행경비",
            target="0107_대만",
            account_path="test-account",
            target_path="ota_mail_service_period_exact",
            target_evidence_source="ota_mail",
            ota_service_target=cancelled_target,
        )
        self.assertIn(
            "ota_lifecycle_not_closed",
            cancelled["row_finality"]["vetoes"],
        )
        ota_target["evidence_records"][0]["lifecycle_latest_source_sha256"] = ""
        invalid = _axis_evidence(
            row,
            account="숙박비",
            cost_type="여행경비",
            target="0107_대만",
            account_path="test-account",
            target_path="ota_mail_service_period_exact",
            target_evidence_source="ota_mail",
            ota_service_target=ota_target,
        )
        self.assertFalse(invalid["row_finality"]["eligible"])
        self.assertIn(
            "ota_lifecycle_source_binding_missing",
            invalid["row_finality"]["vetoes"],
        )

    def test_2025_structural_placeholder_requires_mail_service_period(self):
        row = {
            "occurred_on": "2025-08-05",
            "source_kind": "card_raw",
            "source_key": "card-source-2025",
            "source_sha256": "a" * 64,
            "direct_event_key": "card:" + "1" * 64 + "#single",
            "current_fact_sha256": "b" * 64,
        }
        evidence = _axis_evidence(
            row,
            account="여비교통비",
            cost_type="여행경비",
            target="임시여행활동_20250805_해외미상",
            account_path="test-account",
            target_path=ACTIVITY_PLACEHOLDER_PATH,
            target_evidence_source=ACTIVITY_PLACEHOLDER_PATH,
            admitted_rule_paths=[ACTIVITY_PLACEHOLDER_PATH],
        )
        self.assertFalse(evidence["row_finality"]["eligible"])
        self.assertIn(
            "2025_mail_service_period_required",
            evidence["row_finality"]["vetoes"],
        )

    def test_2025_pg_mail_service_period_can_be_final(self):
        row = {
            "occurred_on": "2025-11-25",
            "source_kind": "card_raw",
            "source_key": "card-source-pg",
            "source_sha256": "a" * 64,
            "direct_event_key": "card:" + "2" * 64 + "#single",
            "current_fact_sha256": "b" * 64,
        }
        evidence = _axis_evidence(
            row,
            account="항공료",
            cost_type="여행경비",
            target="0404_에히메",
            account_path="test-account",
            target_path=GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH,
            target_evidence_source=GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH,
            gmail_evidence={
                "source_kind": "pg_mail",
                "source_key": "pg-mail-1",
                "source_digest": "c" * 64,
                "classification": "travel",
                "target_hint": "0404_에히메",
                "service_start": "2026-04-04",
                "service_end": "2026-04-10",
            },
        )
        self.assertTrue(evidence["row_finality"]["eligible"])
        self.assertTrue(evidence["row_finality"]["mail_service_period_verified"])
        self.assertEqual(
            evidence["row_finality"]["mail_service_period_source_kinds"],
            ["pg_mail"],
        )
        refs = evidence["target_evidence_refs"]
        self.assertTrue(any(
            item.get("source_kind") == "pg_mail"
            and item.get("source_key") == "pg-mail-1"
            for item in refs
        ))

    def test_ota_month_day_without_explicit_service_year_is_held(self):
        payload = {
            "travel_date_candidates": ["0107"],
            "sent_at": "2025-12-20T10:00:00",
        }
        self.assertEqual(
            _ota_mail_date_variants(payload), [],
        )

    def test_ota_month_day_uses_explicit_service_year(self):
        payload = {
            "travel_date_candidates": ["0107"],
            "service_year_candidates": [2026],
            "sent_at": "2025-12-20T10:00:00",
        }
        self.assertEqual(
            _ota_mail_date_variants(payload), [{date(2026, 1, 7)}],
        )

    def test_ota_mismatch_interpretation_is_held(self):
        payload = {
            "travel_date_candidates": ["0417", "0418"],
            "sent_at": "2026-04-17T10:00:00",
        }
        schedule = {
            "0417_하루": {"tab": "0417_하루", "mm": 4, "dd": 17, "window": 1},
            "0418_하루": {"tab": "0418_하루", "mm": 4, "dd": 18, "window": 1},
        }
        self.assertEqual(_ota_mail_schedule_targets(payload, schedule), set())

    def test_ota_explicit_2025_does_not_match_2026_schedule(self):
        payload = {
            "travel_date_candidates": ["0816"],
            "service_year_candidates": [2025],
            "sent_at": "2025-07-21T10:00:00",
        }
        schedule = {
            "0813_북해도": {
                "tab": "0813_북해도", "mm": 8, "dd": 13,
                "window": 7, "service_year": 2026,
            },
        }
        self.assertEqual(_ota_mail_schedule_targets(payload, schedule), set())

    def test_physical_card_use_requires_schedule_service_year(self):
        row = {
            "merchant": "7ELEVEN TOKYO JP",
            "biz": "편의점",
            "sub": "해외",
            "occurred_on": "2025-08-16",
        }
        schedule = {
            "0813_북해도": {
                "tab": "0813_북해도", "mm": 8, "dd": 13,
                "window": 7, "service_year": 2026,
            },
        }
        target, path, status = _target_prediction(
            row, _empty_indexes(), schedule,
        )
        self.assertEqual(target, TRIP_UNASSIGNED)
        self.assertEqual(path, "foreign_service_period_pending_review")
        self.assertEqual(status, "no_match")

    def test_gmail_service_year_must_match_schedule_year(self):
        evidence = {
            "authority_status": "verified_external",
            "source_digest": GMAIL_EVIDENCE_SNAPSHOT_SHA256,
            "classification": "travel",
            "target_status": "schedule_target",
            "target_hint": "0813_북해도",
            "service_start": "2025-08-16",
            "service_end": "2025-08-16",
        }
        schedule = {
            "0813_북해도": {
                "tab": "0813_북해도", "mm": 8, "dd": 13,
                "window": 7, "service_year": 2026,
            },
        }
        self.assertIsNone(_gmail_schedule_target(evidence, schedule))

    def test_ota_amount_tolerance_is_unique_and_fail_closed(self):
        schedule = {
            "0420_오사카": {
                "tab": "0420_오사카", "mm": 4, "dd": 20, "window": 1,
            },
        }

        def mail(
            source_key: str,
            amount_candidates: list[int],
            *,
            booking_ref: str,
        ) -> dict[str, object]:
            return {
                "source_key": source_key,
                "source_sha256": "a" * 64,
                "payload": {
                    "provider": "trip",
                    "message_id": source_key,
                    "message_status": "confirmation",
                    "booking_ref_candidates": [booking_ref],
                    "travel_date_candidates": ["0420"],
                    "service_year_candidates": [2026],
                    "amount_candidates": amount_candidates,
                    "sent_at": "2026-03-01T10:00:00",
                },
            }

        row = {
            "payment_id": 1,
            "source": "KBD",
            "occurred_on": "2026-03-20",
            "amount_krw": 100000,
            "card4": "1234",
            "transaction_type": "purchase",
            "merchant": "Trip.com",
        }
        result = _build_ota_mail_service_period_targets(
            [row],
            {1: (TRIP_UNASSIGNED, "", "")},
            [mail("m1", [99500], booking_ref="booking-1")],
            schedule,
        )
        self.assertEqual(result[1]["match_kind"], "amount_tolerance_exact")
        self.assertEqual(
            result[1]["amount_match_method"], OTA_AMOUNT_TOLERANCE_POLICY,
        )
        self.assertAlmostEqual(
            result[1]["amount_difference_ratio"], 0.005025126, places=8,
        )
        self.assertEqual(
            _target_prediction(
                row, _empty_indexes(), schedule,
                ota_service_target=result[1],
            )[1],
            OTA_MAIL_SERVICE_PERIOD_TOLERANCE_EXACT_PATH,
        )

        self.assertEqual(
            _build_ota_mail_service_period_targets(
                [row],
                {1: (TRIP_UNASSIGNED, "", "")},
                [mail("m2", [97000], booking_ref="booking-2")],
                schedule,
            ),
            {},
        )
        self.assertEqual(
            _build_ota_mail_service_period_targets(
                [row],
                {1: (TRIP_UNASSIGNED, "", "")},
                [mail("m3", [99500, 100500], booking_ref="booking-3")],
                schedule,
            ),
            {},
        )

    def test_ota_amount_tolerance_mn_keeps_only_common_target(self):
        rows = [
            {
                "payment_id": 1,
                "source": "KBD",
                "occurred_on": "2026-03-20",
                "amount_krw": 100000,
                "card4": "1234",
                "transaction_type": "purchase",
                "merchant": "Trip.com",
            },
            {
                "payment_id": 2,
                "source": "KBD",
                "occurred_on": "2026-03-20",
                "amount_krw": 100000,
                "card4": "1234",
                "transaction_type": "purchase",
                "merchant": "Trip.com",
            },
        ]
        schedule = {
            "0420_오사카": {
                "tab": "0420_오사카", "mm": 4, "dd": 20, "window": 1,
            },
        }
        records = [
            {
                "source_key": "m1",
                "source_sha256": "a" * 64,
                "payload": {
                    "provider": "trip",
                    "message_id": "m1",
                    "message_status": "confirmation",
                    "booking_ref_candidates": ["booking-1"],
                    "travel_date_candidates": ["0420"],
                    "service_year_candidates": [2026],
                    "amount_candidates": [99500],
                    "sent_at": "2026-03-01T10:00:00",
                },
            },
            {
                "source_key": "m2",
                "source_sha256": "b" * 64,
                "payload": {
                    "provider": "trip",
                    "message_id": "m2",
                    "message_status": "confirmation",
                    "booking_ref_candidates": ["booking-2"],
                    "travel_date_candidates": ["0420"],
                    "service_year_candidates": [2026],
                    "amount_candidates": [100500],
                    "sent_at": "2026-03-02T10:00:00",
                },
            },
        ]
        result = _build_ota_mail_service_period_targets(
            rows,
            {
                1: (TRIP_UNASSIGNED, "", ""),
                2: (TRIP_UNASSIGNED, "", ""),
            },
            records,
            schedule,
        )
        self.assertEqual(
            {item["match_kind"] for item in result.values()},
            {"amount_tolerance_target_invariant"},
        )
        self.assertEqual(
            {
                _target_prediction(
                    row, _empty_indexes(), schedule,
                    ota_service_target=result[row["payment_id"]],
                )[1]
                for row in rows
            },
            {OTA_MAIL_SERVICE_PERIOD_TOLERANCE_MN_PATH},
        )

    def test_ota_overlapping_booking_references_share_lifecycle_component(self):
        records = [
            {
                "source_key": "m1",
                "payload": {
                    "provider": "trip",
                    "booking_ref_candidates": ["12345678", "87654321"],
                    "message_id": "one",
                },
            },
            {
                "source_key": "m2",
                "payload": {
                    "provider": "trip",
                    "booking_ref_candidates": ["12345678"],
                    "message_id": "two",
                },
            },
        ]
        groups = _ota_mail_component_groups(records)
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            sorted(item["source_key"] for item in groups[0][1]), ["m1", "m2"],
        )

    def test_verified_gmail_service_period_is_confirmed_path(self):
        row = {
            "source": "KBD",
            "occurred_on": "2026-04-10",
            "amount_krw": 205800,
            "transaction_type": "purchase",
            "merchant": "NICE 결제대행-나이스정보통신(주)",
            "sub": "국내",
            "gmail_payment_evidence": {
                "authority_status": "verified_external",
                "source_digest": GMAIL_EVIDENCE_SNAPSHOT_SHA256,
                "classification": "travel",
                "travel_kind": "airfare",
                "auto_confirmed": True,
                "target_status": "schedule_target",
                "target_hint": "0424_알펜루트",
                "service_start": "2026-04-29",
                "service_end": "2026-04-29",
            },
        }
        target, path, status = _target_prediction(
            row, _empty_indexes(), {
                "0424_알펜루트": {"tab": "0424_알펜루트", "mm": 4, "dd": 24, "window": 7},
            },
        )
        self.assertEqual((target, path, status), (
            "0424_알펜루트", GMAIL_PAYMENT_VERIFIED_SERVICE_PERIOD_PATH,
            "unique_match",
        ))
        self.assertEqual(_account_prediction_with_external_evidence(row, _empty_indexes())[0], "항공료")

    def test_owner_decision_is_overhead_and_non_review_path(self):
        row = {
            "current_owner_decision": {
                "decision_id": "d-1",
                "account": "기타비용",
                "allocation_target": "기타비용",
            },
        }
        self.assertEqual(_target_prediction(row, _empty_indexes(), {}), (
            "기타비용", OWNER_DECISION_CURRENT_SCOPE_PATH, "not_applicable",
        ))
        self.assertEqual(_account_prediction_with_external_evidence(row, _empty_indexes())[0], "기타비용")

    def test_manual_travel_tab_exact_is_checked_before_ota_period_block(self):
        row = {
            "source": "KBD",
            "occurred_on": "2026-06-25",
            "amount_krw": 157652,
            "transaction_type": "purchase",
            "merchant": "Trip.com",
            "sub": "국내",
        }
        manual_index = {
            ("KBD", "2026-06-25", 157652): [{
                "manual_source_key": "0630_오제:120",
                "manual_source_sha256": "a" * 64,
                "manual_tab": "0630_오제",
                "manual_row": "120",
                "manual_date": "2026-06-25",
                "manual_amount_krw": 157652,
                "manual_card": "국민",
            }],
        }
        manual_match = _manual_travel_match(
            row, manual_index, Counter({("KBD", "2026-06-25", 157652): 1}),
        )
        self.assertIsNotNone(manual_match)
        target, path, status = _target_prediction(
            row, _empty_indexes(), {}, manual_match=manual_match,
        )
        self.assertEqual((target, path, status), (
            "0630_오제", "manual_travel_tab_exact", "unique_match",
        ))

    def test_manual_many_to_one_same_target_is_safe_mn_classification(self):
        row = {
            "source": "KBD",
            "occurred_on": "2026-01-10",
            "amount_krw": 100000,
            "transaction_type": "purchase",
            "merchant": "TAIPEI FAMILY MART TW",
            "sub": "해외",
        }
        manual_index = {
            ("KBD", "2026-01-10", 100000): [{
                "manual_source_key": "0107_대만:1",
                "manual_source_sha256": "a" * 64,
                "manual_tab": "0107_대만",
                "manual_row": "1",
                "manual_date": "2026-01-10",
                "manual_amount_krw": 100000,
                "manual_card": "국민",
            }],
        }
        manual_match = _manual_travel_match(
            row, manual_index, Counter({("KBD", "2026-01-10", 100000): 2}),
        )
        target, path, status = _target_prediction(
            row, _empty_indexes(), {}, [{
                "tab": "0107_대만",
                "starts_on": "2026-01-07",
                "ends_on": "2026-01-14",
            }], manual_match=manual_match,
        )
        self.assertEqual((target, path, status), (
            "0107_대만", "manual_travel_tab_mn_target_invariant", "unique_match",
        ))

    def test_manual_amount_component_ignores_service_date_for_prepaid_payment(self):
        row = {
            "source": "KBD",
            "occurred_on": "2026-03-20",
            "amount_krw": 351000,
            "transaction_type": "purchase",
            "merchant": "NICE 결제대행-Trip.com",
            "sub": "국내",
        }
        key = ("KBD", 351000)
        match = _manual_travel_amount_component_match(
            row,
            {
                key: [{
                    "manual_source_key": "1127_야쿠시마:8",
                    "manual_source_sha256": "c" * 64,
                    "manual_tab": "1127_야쿠시마",
                    "manual_date": "2026-11-27",
                    "manual_amount_krw": 351000,
                    "manual_card": "국민",
                }],
            },
            Counter({key: 1}),
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["status"], "amount_component_exact")
        self.assertFalse(match["payment_date_used_as_service_date"])
        self.assertFalse(match["individual_payment_pair_asserted"])
        self.assertEqual(_target_prediction(
            row, _empty_indexes(), {}, manual_match=match,
        ), (
            "1127_야쿠시마", MANUAL_TRAVEL_TAB_AMOUNT_EXACT_PATH,
            "unique_match",
        ))

    def test_manual_amount_component_mn_requires_common_target(self):
        row = {
            "source": "KBD",
            "occurred_on": "2026-03-20",
            "amount_krw": 118800,
            "transaction_type": "purchase",
            "merchant": "NICE 결제대행-Agoda",
            "sub": "국내",
        }
        key = ("KBD", 118800)
        match = _manual_travel_amount_component_match(
            row,
            {
                key: [
                    {
                        "manual_source_key": "1127_야쿠시마:1",
                        "manual_source_sha256": "d" * 64,
                        "manual_tab": "1127_야쿠시마",
                    },
                    {
                        "manual_source_key": "1127_야쿠시마:2",
                        "manual_source_sha256": "e" * 64,
                        "manual_tab": "1127_야쿠시마",
                    },
                ],
            },
            Counter({key: 2}),
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["status"], "amount_component_target_invariant")
        self.assertEqual(_target_prediction(
            row, _empty_indexes(), {}, manual_match=match,
        ), (
            "1127_야쿠시마", MANUAL_TRAVEL_TAB_AMOUNT_MN_PATH,
            "unique_match",
        ))

    def test_canonical_trip_cluster_is_confirmed_but_new_registry_is_provisional(self):
        row = {"merchant": "LAWSON TOKYO", "sub": "해외"}
        canonical = {
            "target_code": "1201_도쿄",
            "target_kind": "canonical_schedule",
        }
        temporary = {
            "target_code": "임시여행_20260320_도쿄_hash",
            "target_kind": "new_registry_target",
        }
        self.assertEqual(
            _target_prediction(row, _empty_indexes(), {}, trip_cluster=canonical)[1],
            TRIP_CLUSTER_CANONICAL_EXACT_PATH,
        )
        self.assertEqual(
            _target_prediction(row, _empty_indexes(), {}, trip_cluster=temporary)[1],
            REGISTRY_PATH,
        )

    def test_manual_item_discriminator_selects_classification_target_only(self):
        row = {
            "source": "KBO",
            "occurred_on": "2026-04-22",
            "amount_krw": 5642,
            "transaction_type": "purchase",
            "merchant": "MOSBURGER",
            "sub": "해외",
        }
        key = ("KBO", "2026-04-22", 5642)
        manual_match = _manual_travel_match(
            row,
            {
                key: [
                    {
                        "manual_source_key": "0417_아오모리:1",
                        "manual_source_sha256": "a" * 64,
                        "manual_tab": "0417_아오모리",
                        "manual_item": "MOSBURGER",
                    },
                    {
                        "manual_source_key": "0420_오사카:1",
                        "manual_source_sha256": "b" * 64,
                        "manual_tab": "0420_오사카",
                        "manual_item": "LAWSON",
                    },
                ],
            },
            Counter({key: 2}),
        )
        self.assertIsNotNone(manual_match)
        assert manual_match is not None
        self.assertEqual(manual_match["target"], "0417_아오모리")
        self.assertEqual(manual_match["status"], "target_invariant")
        self.assertEqual(
            manual_match["merchant_discriminator"]["manual_items"],
            ["MOSBURGER"],
        )

    def test_inferred_external_target_is_a_unique_temporary_target(self):
        target, path, status = _target_prediction(
            {
                "merchant": "TRIP.COM",
                "sub": "국내",
                "occurred_on": "2026-03-20",
            },
            _empty_indexes(),
            {},
            inferred_target={
                "target_code": "임시여행_MN_20260320_KBD_351000_abc123",
                "candidate_targets": ["0408_교토", "0424_알펜루트"],
            },
        )
        self.assertEqual(path, INFERRED_EXTERNAL_TARGET_PATH)
        self.assertEqual(status, "unique_match")
        self.assertEqual(target, "임시여행_MN_20260320_KBD_351000_abc123")

    def test_verified_gmail_schedule_target_breaks_overlapping_windows(self):
        target = _gmail_schedule_target(
            {
                "authority_status": "verified_external",
                "source_digest": GMAIL_EVIDENCE_SNAPSHOT_SHA256,
                "classification": "travel",
                "target_status": "schedule_target",
                "target_hint": "0424_알펜루트",
                "service_start": "2026-04-25",
                "service_end": "2026-04-26",
            },
            {
                "0420_오사카": {"mm": 4, "dd": 20, "window": 7},
                "0424_알펜루트": {"mm": 4, "dd": 24, "window": 7},
            },
        )
        self.assertEqual(target, "0424_알펜루트")

    def test_manual_negative_row_can_classify_a_current_purchase(self):
        row = {
            "source": "KBD",
            "occurred_on": "2026-01-10",
            "amount_krw": 100000,
            "transaction_type": "purchase",
        }
        manual_match = _manual_travel_match(
            row,
            {
                ("KBD", "2026-01-10", 100000): [{
                    "manual_source_key": "0107_대만:1",
                    "manual_source_sha256": "a" * 64,
                    "manual_tab": "0107_대만",
                    "manual_amount_krw": 100000,
                    "manual_amount_sign": "negative",
                    "manual_card": "국민",
                }],
            },
            Counter({("KBD", "2026-01-10", 100000): 1}),
        )
        self.assertIsNotNone(manual_match)
        assert manual_match is not None
        self.assertEqual(manual_match["status"], "exact")
        self.assertEqual(manual_match["target"], "0107_대만")

    def test_provisional_m_to_n_relation_cannot_inherit(self):
        inherited = _provisional_reversal_inheritance(
            {"payment_id": 10},
            {10: [{
                "related_transaction_id": None,
                "match_method": (
                    "kbo_card4_currency_foreign_merchant_unordered_group"
                ),
                "reference_value": "group-1",
                "relation_id": 99,
            }]},
            {20: {
                "account": "숙박비",
                "cost_type": "여행원가",
                "allocation_target": "임시예약_1_행사기간미상",
            }},
            {20: {
                "prediction_id": "prediction-20",
                "prediction_sha256": "b" * 64,
            }},
        )
        self.assertIsNone(inherited)

    def test_taiwan_context_requires_current_marker_and_exact_2026_window(self):
        context = [{
            "tab": "0107_대만",
            "starts_on": "2026-01-07",
            "ends_on": "2026-01-14",
        }]
        target, path, schedule_status = _target_prediction(
            {
                "merchant": "TAIPEI FAMILY MART TW",
                "sub": "국내",
                "occurred_on": "2026-01-10",
            },
            _empty_indexes(),
            {},
            context,
        )
        self.assertEqual(target, "0107_대만")
        self.assertEqual(path, "current_card_geography_context_exact_2026")
        self.assertEqual(schedule_status, "unique_match")

        outside_target, outside_path, outside_status = _target_prediction(
            {
                "merchant": "TRA TAIPEI TW",
                "sub": "해외",
                "occurred_on": "2025-08-18",
            },
            _empty_indexes(),
            {
                "0813_북해도": {
                    "tab": "0813_북해도", "mm": 8, "dd": 13, "window": 7,
                },
            },
            context,
        )
        self.assertEqual(outside_target, TRIP_UNASSIGNED)
        self.assertEqual(outside_path, "foreign_service_period_pending_review")
        self.assertEqual(outside_status, "no_match")

    def test_taiwan_marker_does_not_match_embedded_tw_words(self):
        target, path, schedule_status = _target_prediction(
            {
                "merchant": "TWIN NETWORK SHOP",
                "sub": "국내",
                "occurred_on": "2026-01-10",
            },
            _empty_indexes(),
            {},
            [{
                "tab": "0107_대만",
                "starts_on": "2026-01-07",
                "ends_on": "2026-01-14",
            }],
        )
        self.assertEqual(target, "기타비용")
        self.assertEqual(path, "domestic_nontravel_policy")
        self.assertEqual(schedule_status, "not_applicable")

    def test_ota_does_not_use_payment_date_as_service_date(self):
        row = {
            "merchant": "AGODA.COM YAKUSHIMA",
            "sub": "국내",
            "occurred_on": "2026-04-06",
        }
        target, path, schedule_status = _target_prediction(
            row, _empty_indexes(), {},
        )
        self.assertEqual(target, TRIP_UNASSIGNED)
        self.assertEqual(
            path, "prepaid_travel_service_period_not_in_card_fact",
        )
        self.assertEqual(schedule_status, "not_applicable")

    def test_activity_placeholder_is_review_only_target(self):
        target, path, status = _target_prediction(
            {
                "merchant": "FAMILYMART TOKYO JP",
                "sub": "해외",
                "occurred_on": "2026-02-01",
            },
            _empty_indexes(), {},
            placeholder={
                "target_code": "임시여행활동_20260201_도쿄_hash",
                "classification_path": ACTIVITY_PLACEHOLDER_PATH,
            },
        )
        self.assertEqual(target, "임시여행활동_20260201_도쿄_hash")
        self.assertEqual(path, ACTIVITY_PLACEHOLDER_PATH)
        self.assertEqual(status, "not_applicable")

    def test_reservation_placeholder_does_not_turn_payment_date_into_service_date(self):
        target, path, status = _target_prediction(
            {
                "merchant": "AGODA TOKYO JP",
                "sub": "국내",
                "occurred_on": "2026-02-01",
            },
            _empty_indexes(), {},
            placeholder={
                "target_code": "임시예약_hash_행사기간미상",
                "classification_path": RESERVATION_PLACEHOLDER_PATH,
            },
        )
        self.assertEqual(target, "임시예약_hash_행사기간미상")
        self.assertEqual(path, RESERVATION_PLACEHOLDER_PATH)
        self.assertEqual(status, "not_applicable")

    def test_airfare_does_not_use_payment_date_as_service_date(self):
        row = {
            "merchant": "아시아나항공",
            "biz": "항공",
            "sub": "국내",
            "occurred_on": "2026-04-20",
        }
        schedule = {
            "0417_아오모리": {
                "tab": "0417_아오모리",
                "mm": 4,
                "dd": 17,
                "window": 7,
            },
        }
        target, path, schedule_status = _target_prediction(
            row, _empty_indexes(), schedule,
        )
        self.assertEqual(target, TRIP_UNASSIGNED)
        self.assertEqual(
            path, "prepaid_travel_service_period_not_in_card_fact",
        )
        self.assertEqual(schedule_status, "not_applicable")

    def test_overseas_airline_and_lodging_platform_do_not_use_payment_date(self):
        schedule = {
            "5월_유럽": {
                "tab": "5월_유럽",
                "mm": 5,
                "dd": 1,
                "window": 14,
            },
        }
        for merchant in ("ANAAIR", "Airbnb"):
            with self.subTest(merchant=merchant):
                target, path, schedule_status = _target_prediction(
                    {
                        "merchant": merchant,
                        "biz": "해외",
                        "sub": "해외",
                        "occurred_on": "2026-05-03",
                    },
                    _empty_indexes(),
                    schedule,
                )
                self.assertEqual(target, TRIP_UNASSIGNED)
                self.assertEqual(schedule_status, "not_applicable")
                self.assertIn("prepaid_travel", path)

    def test_unlinked_domestic_ordinary_reversal_uses_overhead_policy(self):
        row = {
            "merchant": "일반식당",
            "biz": "음식점",
            "sub": "국내",
        }
        axes, path = _reversal_policy_fallback(row, _empty_indexes())
        self.assertEqual(axes["cost_type"], "판관비")
        self.assertEqual(axes["allocation_target"], "기타비용")
        self.assertIn("domestic_nontravel", path)

    def test_unlinked_ota_reversal_stays_unassigned(self):
        row = {
            "merchant": "트립닷컴",
            "biz": "전자상거래PG",
            "sub": "국내",
        }
        axes, path = _reversal_policy_fallback(row, _empty_indexes())
        self.assertEqual(axes["cost_type"], "여행원가")
        self.assertEqual(axes["allocation_target"], TRIP_UNASSIGNED)
        self.assertIn("service_period_missing", path)

    def test_unlinked_payment_gateway_reversal_stays_unassigned(self):
        row = {
            "merchant": "나이스정보통신",
            "biz": "전자상거래PG",
            "sub": "국내",
        }
        axes, path = _reversal_policy_fallback(row, _empty_indexes())
        self.assertEqual(axes["cost_type"], "여행원가")
        self.assertEqual(axes["allocation_target"], TRIP_UNASSIGNED)
        self.assertIn("service_period_missing", path)

    def test_explicit_domestic_nontravel_pair_overrides_gateway_hold(self):
        target, path, status = _target_prediction(
            {
                "merchant": "쿠팡(쿠페이)-쿠팡(쿠페이)",
                "biz": "전자상거래PG",
                "sub": "국내",
                "transaction_type": "purchase",
                "amount_krw": 100,
                "occurred_on": "2026-02-01",
            },
            _empty_indexes(), {}, [],
        )
        self.assertEqual(
            (target, path, status),
            ("기타비용", "domestic_nontravel_allowlist", "not_applicable"),
        )

    def test_unique_original_axes_are_inherited(self):
        row = {"payment_id": 10}
        relations = {
            10: [{
                "related_transaction_id": 20,
                "match_method": "issuer_card4_original_approval_exact",
                "reference_value": "123",
            }],
        }
        axes = {
            20: {
                "account": "항공료",
                "cost_type": "여행원가",
                "allocation_target": "5월_유럽",
            },
        }
        inherited = _inherited_reversal_axes(row, relations, {}, axes)
        self.assertIsNotNone(inherited)
        assert inherited is not None
        self.assertEqual(inherited[0]["allocation_target"], "5월_유럽")
        self.assertTrue(inherited[1].endswith(":unique_original"))

    def test_unordered_group_inherits_only_when_axes_are_invariant(self):
        row = {"payment_id": 10}
        relations = {
            10: [{
                "related_transaction_id": None,
                "match_method": (
                    "kbo_card4_currency_foreign_merchant_unordered_group"
                ),
                "reference_value": "group-1",
            }],
        }
        same_axes = {
            "account": "숙박비",
            "cost_type": "여행원가",
            "allocation_target": "1127_야쿠시마",
        }
        inherited = _inherited_reversal_axes(
            row, relations, {"group-1": [20, 21]},
            {20: dict(same_axes), 21: dict(same_axes)},
        )
        self.assertIsNotNone(inherited)
        assert inherited is not None
        self.assertIn("axis_invariant", inherited[1])

        different = _inherited_reversal_axes(
            row, relations, {"group-1": [20, 21]},
            {
                20: dict(same_axes),
                21: {
                    **same_axes,
                    "allocation_target": "0417_아오모리",
                },
            },
        )
        self.assertIsNone(different)


if __name__ == "__main__":
    unittest.main()
