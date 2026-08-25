import unittest
from datetime import date
import sqlite3

from ledger.domain.manual_ledger_booking_link import ManualBookingRow
from ledger.domain.manual_tab_overlap_resolution import (
    AOMORI_TARGET,
    OSAKA_TARGET,
    OVERLAP_TARGETS,
    RULE_ID,
    resolve_overlap_target,
)
from ledger.domain.direct_trip_schedule_authority import ScheduleRecord
from tools.build_agoda_accounting_draft_v3 import build_rows


class ManualTabOverlapResolutionTests(unittest.TestCase):
    def row(self, *, amount=123200):
        return ManualBookingRow(
            target=OSAKA_TARGET,
            occurred_on=date(2026, 4, 16),
            merchant="Y&Y NAMBA HOTEL OSAKA",
            content="숙박",
            period="0420_0423",
            booking_number="",
            evidence="아고다",
            amount_krw=amount,
            sheet_name=OSAKA_TARGET,
            source_row=13,
        )

    def kwargs(
        self,
        *,
        amount=123200,
        merchant="AGODA.COM Y&Y NAMBA HOTEL",
        manual_rows=None,
    ):
        return dict(
            candidate_targets=OVERLAP_TARGETS,
            occurred_on="2026-04-16",
            amount_krw=amount,
            merchant=merchant,
            service_start_on="2026-04-20",
            service_end_on="2026-04-23",
            manual_rows=[self.row(amount=amount)] if manual_rows is None else manual_rows,
            resolution_sha256="r" * 64,
        )

    def test_unique_manual_row_selects_osaka(self):
        decision = resolve_overlap_target(**self.kwargs())
        self.assertEqual(decision.selected_target, OSAKA_TARGET)
        self.assertEqual(decision.reason, "unique_google_manual_agoda_lodging_row")
        self.assertEqual(len(decision.manual_evidence_digest), 64)

    def test_every_other_overlap_row_defaults_to_aomori(self):
        decision = resolve_overlap_target(**self.kwargs(manual_rows=[]))
        self.assertEqual(decision.selected_target, AOMORI_TARGET)
        self.assertEqual(decision.reason, "overlap_default_no_unique_manual_row")
        self.assertIsNone(decision.manual_evidence_digest)

    def test_non_agoda_overlap_row_defaults_to_aomori(self):
        decision = resolve_overlap_target(**self.kwargs(merchant="FAMILYMART"))
        self.assertEqual(decision.selected_target, AOMORI_TARGET)
        self.assertEqual(decision.reason, "overlap_default_non_agoda_source")

    def test_other_overlap_is_untouched(self):
        decision = resolve_overlap_target(
            **{**self.kwargs(), "candidate_targets": ("0404_에히메", "0420_오사카")}
        )
        self.assertIsNone(decision)
        self.assertEqual(RULE_ID, "manual-ledger-osaka-reconnaissance-overlap-v1")

    def test_draft_boundary_uses_manual_osaka_then_aomori_fallback(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE payment_transactions(id INTEGER PRIMARY KEY, occurred_on TEXT, merchant TEXT)"
        )
        db.executemany(
            "INSERT INTO payment_transactions(id,occurred_on,merchant) VALUES (?,?,?)",
            [(1, "2026-04-16", "AGODA.COM Y&Y NAMBA HOTEL"),
             (2, "2026-04-04", "AGODA.COM OTHER HOTEL")],
        )
        authority = [
            ScheduleRecord(
                AOMORI_TARGET, 2026, date(2026, 4, 17), date(2026, 4, 22), "아오모리",
                "explicit_trip_registry", "evidence://aomori", "a" * 64, "authoritative",
            ),
            ScheduleRecord(
                OSAKA_TARGET, 2026, date(2026, 4, 20), date(2026, 4, 22), "오사카",
                "explicit_trip_registry", "evidence://osaka", "b" * 64, "authoritative",
            ),
        ]
        source = lambda payment_id, amount, start, end: {
            "link_authority_id": f"{payment_id:064d}"[-64:],
            "payment_id": payment_id,
            "booking_id": payment_id + 100,
            "booking_number": str(1700000000 + payment_id),
            "external_key": f"KBO-{payment_id}",
            "amount_krw": amount,
            "service_start_on": start,
            "service_end_on": end,
            "booking_evidence_set_sha256": "e" * 64,
        }
        rows = build_rows(
            db,
            [source(1, 123200, "2026-04-20", "2026-04-23")],
            authority,
            input_database_sha256="a" * 64,
            input_audit_sha256="b" * 64,
            authority_document_sha256="c" * 64,
            overlap_manual_rows=[self.row()],
            overlap_resolution_sha256="r" * 64,
        )
        self.assertEqual(rows[0]["allocation_target"], OSAKA_TARGET)
        self.assertEqual(
            rows[0]["overlap_resolution"]["reason"],
            "unique_google_manual_agoda_lodging_row",
        )
        rows = build_rows(
            db,
            [source(1, 999999, "2026-04-20", "2026-04-23")],
            authority,
            input_database_sha256="a" * 64,
            input_audit_sha256="b" * 64,
            authority_document_sha256="c" * 64,
            overlap_manual_rows=[self.row()],
            overlap_resolution_sha256="r" * 64,
        )
        self.assertEqual(rows[0]["allocation_target"], AOMORI_TARGET)
        self.assertEqual(
            rows[0]["overlap_resolution"]["reason"],
            "overlap_default_no_unique_manual_row",
        )
        db.close()


if __name__ == "__main__":
    unittest.main()
