from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from ledger.domain.manual_ledger_booking_link import ManualBookingRow
from tools.export_event_year_manual_ledger import _evidence_label
from tools.export_clean_manual_ledger import (
    _airfare_passenger_content,
    _display_sort_key,
    _is_airfare_content,
    _single_active_trip_for_activity,
    _single_active_trip_local_target,
    _output_lane,
    _output_period,
    human_content,
    manual_period,
)


def manual_row(**overrides: object) -> ManualBookingRow:
    values: dict[str, object] = {
        "target": "0404_에히메",
        "occurred_on": date(2026, 4, 4),
        "merchant": "제주항공",
        "content": "항공_김효정",
        "period": "0404_0410",
        "booking_number": "",
        "evidence": "수기장부",
        "amount_krw": 232300,
        "sheet_name": "0404_에히메",
        "source_row": 8,
    }
    values.update(overrides)
    return ManualBookingRow(**values)  # type: ignore[arg-type]


class CleanManualLedgerExportTest(unittest.TestCase):
    def test_airfare_uses_one_exact_passenger_label(self) -> None:
        row = {
            "account": "항공료",
            "occurred_on": date(2026, 4, 4),
            "amount_krw": 232300,
        }
        passenger = _airfare_passenger_content(
            row, "0404_에히메", [manual_row()]
        )
        self.assertEqual(passenger, "항공_김효정")
        self.assertEqual(human_content("항공료", passenger), "항공_김효정")

    def test_airfare_joins_multiple_passenger_names(self) -> None:
        row = {
            "account": "항공료",
            "occurred_on": date(2026, 4, 4),
            "amount_krw": 232300,
        }
        self.assertEqual(
            _airfare_passenger_content(row, "0404_에히메", []), ""
        )
        self.assertEqual(
            _airfare_passenger_content(
                row,
                "0404_에히메",
                [
                    manual_row(content="항공_김효정"),
                    manual_row(content="항공_김의영", source_row=9),
                ],
            ),
            "항공_김효정 김의영",
        )
        self.assertEqual(
            _airfare_passenger_content(
                row,
                "0404_에히메",
                [
                    manual_row(content="전용진"),
                    manual_row(content="김의영", source_row=9),
                ],
            ),
            "항공_전용진 김의영",
        )
        self.assertEqual(
            _airfare_passenger_content(
                row,
                "0404_에히메",
                [manual_row(content="항공_김효정_0404_0407")],
            ),
            "항공_김효정",
        )
        self.assertEqual(
            _airfare_passenger_content(
                row, "0404_에히메", [manual_row(content="항공_")]
            ),
            "",
        )
        self.assertEqual(human_content("항공료", ""), "항공")
        self.assertFalse(_is_airfare_content("항공_"))
        self.assertFalse(_is_airfare_content("항공_   "))

    def test_bare_airline_name_is_not_taken_from_a_lodging_row(self) -> None:
        lodging = {
            "account": "숙박비",
            "occurred_on": date(2026, 4, 4),
            "amount_krw": 232300,
        }
        self.assertEqual(
            _airfare_passenger_content(
                lodging, "0404_에히메", [manual_row(content="전용진")]
            ),
            "",
        )

    def test_card_source_labels_are_user_facing(self) -> None:
        self.assertEqual(_evidence_label("KBD"), "국민")
        self.assertEqual(_evidence_label("KBO"), "국민")
        self.assertEqual(_evidence_label("KBO_OVS"), "국민")
        self.assertEqual(_evidence_label("HAN"), "하나")
        self.assertEqual(_evidence_label("MAN"), "영수증")

    def test_period_is_shown_only_for_service_accounts(self) -> None:
        period = SimpleNamespace(
            starts_on=date(2026, 4, 4),
            ends_on=date(2026, 4, 10),
        )
        for account in (
            "항공료",
            "항공",
            "숙박비",
            "숙박",
            "렌터카",
            "렌트",
            "여행자보험",
        ):
            self.assertEqual(manual_period(period, account), "0404_0410")
        for account in ("식비", "통행료", "주유비", "기타비용"):
            self.assertEqual(manual_period(period, account), "")

    def test_lodging_uses_exact_manual_period_and_not_event_window(self) -> None:
        row = {
            "account": "숙박비",
            "occurred_on": date(2025, 11, 22),
            "amount_krw": 369246,
        }
        event_period = SimpleNamespace(
            starts_on=date(2026, 4, 4),
            ends_on=date(2026, 4, 10),
        )
        self.assertEqual(
            _output_period(
                row,
                event_period,
                "0404_에히메",
                "1400821831501966",
                [
                    manual_row(
                        occurred_on=date(2025, 11, 22),
                        content="숙박",
                        period="0406_0407",
                        amount_krw=369246,
                        booking_number="1400821831501966",
                    )
                ],
            ),
            "0406_0407",
        )
        self.assertEqual(
            _output_period(
                row,
                event_period,
                "0404_에히메",
                "",
                [manual_row(occurred_on=date(2025, 11, 22), content="숙박", period="")],
            ),
            "",
        )

    def test_insurance_prefers_explicit_period_and_falls_back_to_event_window(self) -> None:
        row = {
            "account": "여행자보험",
            "occurred_on": date(2026, 3, 22),
            "amount_krw": 66710,
        }
        event_period = SimpleNamespace(
            starts_on=date(2026, 4, 13),
            ends_on=date(2026, 4, 16),
        )
        self.assertEqual(
            _output_period(
                row,
                event_period,
                "0413_나가센도",
                "",
                [
                    manual_row(
                        target="0413_나가센도",
                        occurred_on=date(2026, 3, 22),
                        content="여행자보험",
                        period="0413_0416",
                        amount_krw=66710,
                    )
                ],
            ),
            "0413_0416",
        )
        self.assertEqual(
            _output_period(
                row,
                event_period,
                "0413_나가센도",
                "",
                [
                    manual_row(
                        target="0413_나가센도",
                        occurred_on=date(2026, 3, 22),
                        content="여행자보험",
                        period="",
                        amount_krw=66710,
                    )
                ],
            ),
            "0413_0416",
        )
        self.assertEqual(
            _output_period(
                row,
                event_period,
                "0613_북해도",
                "",
                [
                    manual_row(
                        target="0613_북해도",
                        occurred_on=date(2026, 3, 22),
                        content="여행자보험_0613_0619",
                        period="",
                        amount_krw=66710,
                    )
                ],
            ),
            "0613_0619",
        )

    def test_output_lane_applies_2025_payment_rule_without_promoting_unknown_period(self) -> None:
        event_period = SimpleNamespace(
            event_years=frozenset({2026}),
            target="0404_에히메",
            source="trip_schedule",
        )
        row_2025_confirmed = {
            "occurred_on": date(2025, 11, 25),
            "allocation_target": "0404_에히메",
        }
        self.assertEqual(
            _output_lane(row_2025_confirmed, event_period),
            ("2025_payment", "2025년 결제"),
        )
        mail_confirmed = {
            "axes": {
                "allocation_target": {"value": "0404_에히메"},
            },
            "row_finality": {
                "payment_year": 2025,
                "mail_service_period_verified": True,
                "mail_service_period_source_kinds": ["ota_mail"],
                "eligible": True,
            },
            "service_start": "2026-04-04",
            "service_end": "2026-04-10",
        }
        self.assertEqual(
            _output_lane(
                row_2025_confirmed,
                SimpleNamespace(
                    event_years=frozenset({2026}),
                    target="0404_에히메",
                    source="service_evidence",
                ),
                [mail_confirmed],
            ),
            ("travel", "0404_에히메"),
        )
        row_2025_unknown = {
            "occurred_on": date(2025, 11, 25),
            "allocation_target": "임시여행_20251125_해외미상",
        }
        self.assertEqual(
            _output_lane(row_2025_unknown, SimpleNamespace(event_years=frozenset())),
            ("2025_payment", "2025년 결제"),
        )
        self.assertEqual(
            _output_lane(
                {
                    "occurred_on": date(2025, 7, 21),
                    "allocation_target": "임시여행활동_20250721_해외미상",
                    "transaction_type": "purchase",
                    "conflict_count": 0,
                },
                SimpleNamespace(event_years=frozenset()),
            ),
            ("2025_payment", "2025년 결제"),
        )
        row_2026_unknown = {
            "occurred_on": date(2026, 1, 10),
            "allocation_target": "임시여행_20260110_해외미상",
        }
        self.assertEqual(
            _output_lane(
                row_2026_unknown,
                SimpleNamespace(
                    event_years=frozenset(),
                    eligible=False,
                    target="",
                    source="none",
                ),
            ),
            ("review", "검토필요"),
        )

    def test_explicit_2025_terminal_overrides_target_inference(self) -> None:
        row = {
            "occurred_on": date(2025, 8, 21),
            "allocation_target": "0404_에히메",
            "terminal_disposition": "2025년 결제",
        }
        self.assertEqual(
            _output_lane(
                row,
                SimpleNamespace(
                    event_years=frozenset({2026}),
                    target="0404_에히메",
                    source="service_evidence",
                ),
            ),
            ("2025_payment", "2025년 결제"),
        )

    def test_output_lane_rejects_event_period_outside_allowed_years(self) -> None:
        row = {
            "occurred_on": date(2026, 1, 10),
            "allocation_target": "0404_에히메",
            "conflict_count": 0,
        }
        outside_period = SimpleNamespace(
            event_years=frozenset({2025}),
            target="0404_에히메",
            source="trip_schedule",
        )
        self.assertEqual(
            _output_lane(row, outside_period),
            ("review", "검토필요"),
        )

    def test_zero_net_cancellation_refund_uses_separate_lane(self) -> None:
        row = {
            "occurred_on": date(2026, 6, 19),
            "allocation_target": "취소환불",
            "cost_type": "비용제외",
            "transaction_type": "refund",
        }
        self.assertEqual(
            _output_lane(row, SimpleNamespace(event_years=frozenset())),
            ("cancellation_refund", "취소환불"),
        )

    def test_local_activity_purchase_uses_payment_date_as_event_date(self) -> None:
        row = {
            "occurred_on": date(2026, 7, 19),
            "allocation_target": "임시여행활동_20260712_해외미상_test",
            "account": "식비",
            "merchant": "LOCAL NIGHT MARKET",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
        }
        self.assertEqual(
            _output_lane(
                row,
                SimpleNamespace(
                    event_years=frozenset(),
                    target="",
                    source="none",
                ),
            ),
            ("review", "검토필요"),
        )
        trips = {"0719_의왕": ("2026-07-19", "2026-07-19")}
        self.assertEqual(_single_active_trip_for_activity(row, trips), "0719_의왕")
        self.assertEqual(
            _output_lane(
                row,
                SimpleNamespace(
                    event_years=frozenset(),
                    target="",
                    source="none",
                ),
                trip_ranges=trips,
            ),
            ("travel", "0719_의왕"),
        )
        period = SimpleNamespace(
            starts_on=date(2026, 7, 19),
            ends_on=date(2026, 7, 19),
            source="payment_date_local_activity",
        )
        self.assertEqual(
            _output_period(row | {"account": "숙박비"}, period, "0719_의왕", "", []),
            "0719",
        )

    def test_local_activity_rejects_nonphysical_service_account(self) -> None:
        row = {
            "occurred_on": date(2026, 7, 13),
            "allocation_target": "임시여행활동_20260712_해외미상_test",
            "account": "숙박비",
            "merchant": "LOCAL HOTEL",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
            "rule_path": "current_card_travel_activity_placeholder|cost:travel",
        }
        self.assertEqual(
            _output_lane(
                row,
                SimpleNamespace(
                    event_years=frozenset({2026}),
                    target="임시여행활동_20260712_해외미상_test",
                    source="trip_schedule",
                ),
            ),
            ("review", "검토필요"),
        )

    def test_2026_online_purchase_needs_mail_even_when_schedule_matches(self) -> None:
        row = {
            "occurred_on": date(2026, 7, 13),
            "allocation_target": "0719_의왕",
            "account": "숙박비",
            "merchant": "AGODA_NICE",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
            "rule_path": "current_card_reservation_placeholder|cost:travel",
        }
        period = SimpleNamespace(
            event_years=frozenset({2026}),
            target="0719_의왕",
            source="trip_schedule",
        )
        self.assertEqual(_output_lane(row, period), ("review", "검토필요"))
        mail = {
            "axes": {"allocation_target": {"value": "0719_의왕"}},
            "row_finality": {
                "payment_year": 2026,
                "mail_service_period_verified": True,
                "mail_service_period_source_kinds": ["pg_mail"],
                "eligible": True,
            },
        }
        self.assertEqual(
            _output_lane(row, period, [mail]),
            ("travel", "0719_의왕"),
        )

    def test_weak_geography_needs_local_use_or_mail(self) -> None:
        row = {
            "occurred_on": date(2026, 7, 19),
            "allocation_target": "0719_의왕",
            "account": "숙박비",
            "merchant": "LOCAL HOTEL",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
            "rule_path": "current_card_inferred_external_target|cost:travel",
        }
        period = SimpleNamespace(
            event_years=frozenset({2026}),
            target="0719_의왕",
            source="trip_schedule",
        )
        trips = {"0719_의왕": ("2026-07-19", "2026-07-19")}
        self.assertEqual(
            _output_lane(row, period, trip_ranges=trips),
            ("review", "검토필요"),
        )
        local = dict(row, account="식비", merchant="LOCAL CAFE")
        self.assertEqual(
            _output_lane(local, period, trip_ranges=trips),
            ("travel", "0719_의왕"),
        )

    def test_3820_domestic_outside_domestic_trip_is_other(self) -> None:
        row = {
            "occurred_on": date(2026, 7, 13),
            "allocation_target": "0719_의왕",
            "account": "식비",
            "merchant": "LOCAL CAFE",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
        }
        self.assertEqual(
            _output_lane(
                row,
                SimpleNamespace(
                    event_years=frozenset({2026}),
                    target="0719_의왕",
                    source="trip_schedule",
                ),
                card_fact={"card4": "3820", "sub": "국내"},
                trip_ranges={"0501_부산": ("2026-05-01", "2026-05-07")},
                trip_regions={"0501_부산": "부산"},
            ),
            ("other", "기타비용"),
        )

    def test_3820_domestic_during_domestic_trip_is_not_forced_other(self) -> None:
        row = {
            "occurred_on": date(2026, 5, 3),
            "allocation_target": "0501_부산",
            "account": "식비",
            "merchant": "LOCAL CAFE",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
        }
        self.assertEqual(
            _output_lane(
                row,
                SimpleNamespace(
                    event_years=frozenset({2026}),
                    target="0501_부산",
                    source="trip_schedule",
                ),
                card_fact={"card4": "3820", "sub": "국내"},
                trip_ranges={"0501_부산": ("2026-05-01", "2026-05-07")},
                trip_regions={"0501_부산": "부산"},
            ),
            ("travel", "0501_부산"),
        )

    def test_3820_mail_present_outside_domestic_trip_is_not_forced_other(self) -> None:
        row = {
            "occurred_on": date(2026, 7, 13),
            "allocation_target": "0719_의왕",
            "account": "식비",
            "merchant": "LOCAL CAFE",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
        }
        mail = {
            "row_finality": {
                "mail_service_period_verified": False,
                "mail_service_period_source_kinds": ["pg_mail"],
            }
        }
        lane, _target = _output_lane(
            row,
            SimpleNamespace(
                event_years=frozenset({2026}),
                target="0719_의왕",
                source="trip_schedule",
            ),
            [mail],
            card_fact={"card4": "3820", "sub": "국내"},
            trip_ranges={"0501_부산": ("2026-05-01", "2026-05-07")},
            trip_regions={"0501_부산": "부산"},
        )
        self.assertNotEqual(lane, "other")

    def test_3820_conflict_is_not_forced_other(self) -> None:
        row = {
            "occurred_on": date(2026, 7, 13),
            "allocation_target": "0719_의왕",
            "account": "식비",
            "merchant": "LOCAL CAFE",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 1,
        }
        lane, _target = _output_lane(
            row,
            SimpleNamespace(
                event_years=frozenset({2026}),
                target="0719_의왕",
                source="trip_schedule",
            ),
            card_fact={"card4": "3820", "sub": "국내"},
            trip_ranges={"0501_부산": ("2026-05-01", "2026-05-07")},
            trip_regions={"0501_부산": "부산"},
        )
        self.assertNotEqual(lane, "other")

    def test_unknown_source_kind_does_not_satisfy_mail_gate(self) -> None:
        row = {
            "occurred_on": date(2026, 7, 13),
            "allocation_target": "0719_의왕",
            "account": "숙박비",
            "merchant": "AGODA_NICE",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
            "rule_path": "current_card_reservation_placeholder|cost:travel",
        }
        period = SimpleNamespace(
            event_years=frozenset({2026}),
            target="0719_의왕",
            source="trip_schedule",
        )
        unknown_mail = {
            "axes": {"allocation_target": {"value": "0719_의왕"}},
            "row_finality": {
                "payment_year": 2026,
                "mail_service_period_verified": True,
                "mail_service_period_source_kinds": ["card_raw"],
                "eligible": True,
            },
        }
        self.assertEqual(
            _output_lane(row, period, [unknown_mail]),
            ("review", "검토필요"),
        )

    def test_local_activity_reversal_does_not_enter_travel_lane(self) -> None:
        row = {
            "occurred_on": date(2026, 7, 13),
            "allocation_target": "임시여행활동환불_20260712_해외미상_test",
            "transaction_type": "cancellation",
            "conflict_count": 0,
        }
        self.assertEqual(
            _output_lane(
                row,
                SimpleNamespace(
                    event_years=frozenset(),
                    target="",
                    source="none",
                ),
            ),
            ("review", "검토필요"),
        )

    def test_weak_local_candidate_requires_one_active_canonical_trip(self) -> None:
        row = {
            "occurred_on": date(2026, 1, 9),
            "allocation_target": "0107_대만",
            "account": "식비",
            "merchant": "PRESIDENT TAIPEI TW",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
        }
        trips = {
            "0107_대만": ("2026-01-07", "2026-01-12"),
            "5월_유럽": ("2026-05-01", "2026-05-10"),
        }
        self.assertEqual(_single_active_trip_local_target(row, trips), "0107_대만")
        self.assertEqual(
            _output_lane(
                row,
                SimpleNamespace(event_years=frozenset(), target="", source="none"),
                trip_ranges=trips,
            ),
            ("travel", "0107_대만"),
        )

    def test_weak_local_candidate_rejects_online_or_overlapping_trip(self) -> None:
        online = {
            "occurred_on": date(2026, 1, 9),
            "allocation_target": "0107_대만",
            "account": "식비",
            "merchant": "트립닷컴(구)_NICE",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
        }
        trips = {
            "0107_대만": ("2026-01-07", "2026-01-12"),
            "중첩_여행": ("2026-01-09", "2026-01-10"),
        }
        self.assertEqual(_single_active_trip_local_target(online, trips), "")
        physical = dict(online, merchant="PRESIDENT TAIPEI TW")
        self.assertEqual(_single_active_trip_local_target(physical, trips), "")

    def test_weak_local_candidate_does_not_override_2025_mail_only_rule(self) -> None:
        row = {
            "occurred_on": date(2025, 1, 9),
            "allocation_target": "0107_대만",
            "account": "식비",
            "merchant": "PRESIDENT TAIPEI TW",
            "transaction_type": "purchase",
            "amount_krw": 12000,
            "conflict_count": 0,
        }
        self.assertEqual(
            _output_lane(
                row,
                SimpleNamespace(event_years=frozenset({2026}), target="0107_대만", source="trip_schedule"),
                trip_ranges={"0107_대만": ("2025-01-07", "2025-01-12")},
            ),
            ("2025_payment", "2025년 결제"),
        )

    def test_carpisa_within_europe_schedule_uses_europe_trip(self) -> None:
        row = {
            "occurred_on": date(2026, 5, 29),
            "merchant": "CARPISA VERONA VRIT",
            "allocation_target": "여행_미배정",
            "transaction_type": "purchase",
            "conflict_count": 0,
        }
        self.assertEqual(
            _output_lane(
                row,
                SimpleNamespace(event_years=frozenset(), target="", source="none"),
                trip_ranges={"5월_유럽": ("2026-05-01", "2026-06-10")},
            ),
            ("travel", "5월_유럽"),
        )

    def test_nonzero_reversal_sort_key_follows_original(self) -> None:
        parents = {17: 12}
        ranks = {17: 1}
        dates = {17: "2026-05-29"}
        original = {"payment_id": 12, "occurred_on": "2026-05-29"}
        reversal = {"payment_id": 17, "occurred_on": "2026-05-29"}
        following = {"payment_id": 18, "occurred_on": "2026-05-29"}
        self.assertLess(
            _display_sort_key(original, parents, ranks, dates),
            _display_sort_key(reversal, parents, ranks, dates),
        )
        self.assertLess(
            _display_sort_key(reversal, parents, ranks, dates),
            _display_sort_key(following, parents, ranks, dates),
        )


if __name__ == "__main__":
    unittest.main()
