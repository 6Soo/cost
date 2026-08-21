from __future__ import annotations

import unittest
from datetime import date

from ledger.domain.manual_ledger_booking_link import (
    ManualBookingRow,
    link_booking_numbers,
)


def manual_row(**overrides: object) -> ManualBookingRow:
    values: dict[str, object] = {
        "target": "0404_에히메",
        "occurred_on": date(2026, 4, 4),
        "merchant": "AGODA",
        "content": "숙박비",
        "period": "0404_0406",
        "booking_number": "EH-001",
        "evidence": "카드",
        "amount_krw": 120000,
        "sheet_name": "0404_에히메",
        "source_row": 8,
    }
    values.update(overrides)
    return ManualBookingRow(**values)  # type: ignore[arg-type]


def payment(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "payment_id": 1,
        "target": "0404_에히메",
        "amount_krw": 120000,
        "occurred_on": date(2026, 4, 4),
        "merchant": "AGODA TOKYO JP",
        "account": "숙박비",
        "event_start": date(2026, 4, 4),
        "event_end": date(2026, 4, 6),
    }
    values.update(overrides)
    return values


class ManualLedgerBookingLinkTest(unittest.TestCase):
    def test_exact_amount_and_date_links(self) -> None:
        links, diagnostics = link_booking_numbers([payment()], [manual_row()])
        self.assertEqual(links, {1: "EH-001"})
        self.assertEqual(diagnostics["linked"], 1)
        self.assertEqual(diagnostics["reason_exact_date"], 1)

    def test_amount_only_is_rejected(self) -> None:
        links, diagnostics = link_booking_numbers(
            [payment(occurred_on=None, merchant="알 수 없음", account="식비")],
            [manual_row(occurred_on=None, merchant="", content="기타", period="")],
        )
        self.assertEqual(links, {})
        self.assertEqual(diagnostics["rejected_amount_only"], 1)

    def test_provider_match_can_link_when_date_is_missing(self) -> None:
        links, diagnostics = link_booking_numbers(
            [payment(occurred_on=None, merchant="AGODA JP")],
            [manual_row(occurred_on=None, merchant="AGODA")],
        )
        self.assertEqual(links, {1: "EH-001"})
        self.assertEqual(diagnostics["reason_provider"], 1)

    def test_invalid_period_is_not_an_evidence_match(self) -> None:
        links, diagnostics = link_booking_numbers(
            [payment(occurred_on=None, merchant="알 수 없음", account="식비")],
            [manual_row(occurred_on=None, merchant="", content="기타", period="0230")],
        )
        self.assertEqual(links, {})
        self.assertEqual(diagnostics["rejected_amount_only"], 1)

    def test_one_manual_source_row_is_not_reused(self) -> None:
        links, _ = link_booking_numbers(
            [payment(payment_id=1), payment(payment_id=2)], [manual_row()]
        )
        self.assertEqual(len(links), 1)

    def test_tied_booking_candidates_are_left_blank(self) -> None:
        links, diagnostics = link_booking_numbers(
            [payment()],
            [
                manual_row(booking_number="EH-001", source_row=8),
                manual_row(booking_number="EH-002", source_row=9),
            ],
        )
        self.assertEqual(links, {})
        self.assertEqual(diagnostics["rejected_ambiguous_top_candidate"], 1)


if __name__ == "__main__":
    unittest.main()
