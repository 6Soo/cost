import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from ledger.domain.direct_trip_schedule_authority import validate_document
from ledger.domain.manual_tab_schedule_authority import (
    MANUAL_TAB_CANDIDATE_SCHEMA_VERSION,
    build_manual_tab_documents,
    inspect_manual_ledger,
)


def make_workbook(path: Path, *, conflict: bool = False) -> None:
    workbook = Workbook()
    first = workbook.active
    first.title = "0404_에히메"
    first["A1"] = "㈜숲길여행"
    first["A2"] = "2026년 4월 매출 확인자료_에히메_0404_0407"
    first["A8"] = "거래일자"
    duplicate = workbook.create_sheet("0404_에히메 (1)")
    duplicate["A1"] = "㈜숲길여행"
    duplicate["A2"] = (
        "2026년 4월 매출 확인자료_에히메_0404_0410"
        if conflict
        else "2026년 4월 매출 확인자료_에히메_0404_0407"
    )
    incomplete = workbook.create_sheet("0801_노리쿠라")
    incomplete["A1"] = "㈜숲길여행"
    incomplete["A2"] = "2026년 8월 매출 확인자료_노리쿠라_0801"
    year_only = workbook.create_sheet("0206_오쿠타다미")
    year_only["A1"] = "㈜숲길여행"
    year_only["A2"] = "2027년 2월 매출 확인자료_오쿠타다미"
    workbook.create_sheet("2분기_기타비용")["A1"] = "비여행 탭"
    workbook.save(path)


class ManualTabScheduleAuthorityTests(unittest.TestCase):
    def test_complete_tab_is_authoritative_and_duplicate_collapses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.xlsx"
            make_workbook(path)
            authority, candidates = build_manual_tab_documents(path)
            records = validate_document(authority)
        self.assertEqual([record.trip_code for record in records], ["0404_에히메"])
        self.assertEqual(records[0].event_year, 2026)
        self.assertEqual(records[0].starts_on.isoformat(), "2026-04-04")
        self.assertEqual(records[0].ends_on.isoformat(), "2026-04-06")
        self.assertEqual(candidates["schema_version"], MANUAL_TAB_CANDIDATE_SCHEMA_VERSION)
        self.assertEqual(candidates["duplicate_group_count"], 1)
        self.assertEqual(candidates["authoritative_count"], 1)
        self.assertEqual(
            candidates["records"][0]["source_end_semantics"],
            "exclusive_checkout_date",
        )

    def test_missing_end_is_candidate_only_and_tab_prefix_does_not_infer_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.xlsx"
            make_workbook(path)
            _, candidates = build_manual_tab_documents(path)
        row = next(item for item in candidates["records"] if item["trip_code"] == "0801_노리쿠라")
        self.assertEqual(row["authority_status"], "candidate_only")
        self.assertIsNone(row["ends_on"])
        self.assertEqual(row["reason"], "explicit_period_missing")

    def test_year_is_taken_from_title_not_current_date_or_tab_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.xlsx"
            make_workbook(path)
            _, candidates = build_manual_tab_documents(path)
        row = next(item for item in candidates["records"] if item["trip_code"] == "0206_오쿠타다미")
        self.assertEqual(row["event_year"], 2027)
        self.assertIsNone(row["starts_on"])
        self.assertEqual(row["reason"], "explicit_period_missing")

    def test_conflicting_duplicate_schedule_is_held(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.xlsx"
            make_workbook(path, conflict=True)
            authority, candidates = build_manual_tab_documents(path)
        self.assertEqual(authority["records"], [])
        row = next(item for item in candidates["records"] if item["trip_code"] == "0404_에히메")
        self.assertEqual(row["authority_status"], "candidate_only")
        self.assertEqual(row["reason"], "duplicate_schedule_conflict")
        self.assertEqual(candidates["duplicate_conflict_count"], 1)

    def test_source_digest_is_content_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.xlsx"
            make_workbook(path)
            first, _ = inspect_manual_ledger(path)
            workbook = __import__("openpyxl").load_workbook(path)
            workbook["0404_에히메"]["A3"] = "changed"
            workbook.save(path)
            second, _ = inspect_manual_ledger(path)
        first_row = next(item for item in first if item.canonical_tab == "0404_에히메")
        second_row = next(item for item in second if item.canonical_tab == "0404_에히메")
        self.assertNotEqual(first_row.source_sha256, second_row.source_sha256)
        self.assertEqual(len(first_row.source_sha256), 64)


if __name__ == "__main__":
    unittest.main()
