import datetime as dt
import io
import json
from pathlib import Path

import openpyxl
import pytest

from app import google_authority as ga

INCOME = ["거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)"]
EXPENSE = ["거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)"]
NOW = dt.datetime(2026, 10, 11, 9, 0, tzinfo=ga.KST)


def rev_sheet(wb, title, income_amounts, expense_amounts):
    ws = wb.create_sheet(title)
    ws["B4"] = "수입 내용"
    for col, label in zip("BCDEFGH", INCOME):
        ws[f"{col}5"] = label
    for index, amount in enumerate(income_amounts):
        row = 6 + index
        ws[f"B{row}"] = dt.date(2027, 2, 6)
        ws[f"H{row}"] = amount
    income_sum_row = 6 + len(income_amounts) + 1
    ws[f"C{income_sum_row}"] = f"=sum(H6:H{5 + len(income_amounts)})"
    expense_title = income_sum_row + 2
    ws[f"B{expense_title}"] = "지출 내용"
    header = expense_title + 1
    for col, label in zip("BCDEFGH", EXPENSE):
        ws[f"{col}{header}"] = label
    first = header + 1
    for index, amount in enumerate(expense_amounts):
        row = first + index
        ws[f"B{row}"] = dt.date(2027, 2, 7)
        ws[f"H{row}"] = amount
    last = first + len(expense_amounts) - 1
    ws[f"C{last + 1}"] = f"=SUM(H{first}:H{last})"
    ws[f"B{last + 3}"] = "합계 및 회사수익인식"
    return ws


def workbook_bytes(build) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    build(wb)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class _Cell:
    def __init__(self, value):
        self.value = value


class _Sheet:
    def __init__(self, values):
        self._values = values

    def cell(self, row, column):
        return _Cell(self._values.get((row, column)))


def test_rev_trip_tab_row_sums_and_formula_recognition():
    def build(wb):
        rev_sheet(wb, "0206_하쿠산", [100000, 50000], [30000, 20000, 5000])

    (trip,) = ga.parse_workbook(workbook_bytes(build))
    assert trip["sheet"] == "0206_하쿠산" and trip["copy_name"] is False
    assert trip["layout"] == "rev"
    assert trip["income"]["row_sum"] == 150000 and trip["expense"]["row_sum"] == 55000
    assert (trip["income_rows"], trip["expense_rows"]) == (2, 3)
    # Plain values have no cached formula result, so Google's total is missing and nothing
    # is substituted from the row sum.
    assert trip["income"]["total"] is None and trip["expense"]["total"] is None and trip["net"] is None
    assert trip["verified"] is False
    assert set(trip["flags"]) == {"TOTAL_NOT_CACHED"}


def test_non_trip_sheets_are_ignored():
    def build(wb):
        rev_sheet(wb, "매출자료 양식_rev", [], [])
        wb.create_sheet("3분기_기타비용")
        wb.create_sheet("프리랜서 지급대장")
        rev_sheet(wb, "0630_오제", [10], [4])

    tabs = ga.parse_workbook(workbook_bytes(build))
    assert [t["sheet"] for t in tabs] == ["3분기_기타비용", "0630_오제"]
    assert tabs[0]['kind'] == 'quarter' and tabs[0]['layout'] == 'nonstandard'


def test_legacy_layout_is_reported_not_converted():
    def build(wb):
        ws = wb.create_sheet("0909_제주")
        ws["B25"], ws["D25"], ws["F25"], ws["H25"], ws["I25"] = "거래일자", "항목", "내용", "증빙유형", "금액(원)"
        ws["B26"] = dt.date(2026, 9, 9)
        ws["I26"] = 30000

    trip = ga.parse_workbook(workbook_bytes(build))[0]
    assert trip["layout"] == "nonstandard"
    assert trip["flags"] == ["LAYOUT_NOT_STANDARD"]
    assert trip["income"] is None and trip["expense"] is None and trip["net"] is None


def test_error_value_blocks_block_total_instead_of_zeroing_it():
    def build(wb):
        rev_sheet(wb, "0630_오제", [100000], [30000])
        ws = wb["0630_오제"]
        expense_data_row = next(r for r in range(1, ws.max_row + 1) if ws[f"H{r}"].value == 30000)
        ws[f"H{expense_data_row}"] = "#REF!"

    trip = ga.parse_workbook(workbook_bytes(build))[0]
    assert "FORMULA_ERROR" in trip["flags"]
    assert trip["expense"]["total"] is None and trip["expense"]["row_sum"] is None
    assert trip["net"] is None and trip["verified"] is False


def test_copy_name_keeps_its_own_title_and_is_flagged():
    def build(wb):
        rev_sheet(wb, "0404_에히메의 사본", [1], [1])

    trip = ga.parse_workbook(workbook_bytes(build))[0]
    assert trip["sheet"] == "0404_에히메의 사본" and trip["copy_name"] is True


@pytest.mark.parametrize("cached, expected, flags", [
    (1050, 1050, set()),
    (1200, 1200, {"TOTAL_MISMATCH"}),
    (None, None, {"TOTAL_NOT_CACHED"}),
    ("#REF!", None, {"FORMULA_ERROR"}),
])
def test_sheet_total_is_the_figure_and_disagreement_is_flagged(cached, expected, flags):
    sheet = _Sheet({(18, 3): cached})
    block_flags: set = set()
    total = ga._check_total({(18, 3, 6, 17)}, 6, 19, sheet, 1050, 12, 6, 17, block_flags)
    assert total == expected and block_flags == flags


def test_total_range_that_misses_data_is_flagged():
    block_flags: set = set()
    ga._check_total({(33, 3, 22, 30)}, 22, 32, _Sheet({(33, 3): 1050}), 1050, 12, 22, 32, block_flags)
    assert block_flags == {"TOTAL_RANGE_MISMATCH"}


def test_zero_total_is_a_real_zero_and_missing_is_none():
    assert ga._block(0, 0, set())["total"] == 0
    assert ga._block(0, 0, set())["verified"] is True
    assert ga._block(None, 0, set())["total"] is None
    assert ga._block(None, 0, set())["verified"] is False


def _source(trips, *, status="ok", last_ok="2026-10-11T09:00:00+09:00", stale=False):
    return {"status": status, "trips": trips, "last_ok_at": last_ok, "stale": stale}


def _trip(sheet, *, income=1000, expense=400, flags=(), layout="rev", copy=False):
    def block(value):
        return {"sheet_total": value, "row_sum": value, "total": value, "verified": True}
    if layout != "rev":
        return {"sheet": sheet, "copy_name": copy, "layout": layout, "flags": ["LAYOUT_NOT_STANDARD"],
                "income": None, "expense": None, "net": None, "verified": False}
    return {"sheet": sheet, "copy_name": copy, "layout": "rev", "flags": list(flags),
            "income": block(income), "expense": block(expense), "net": income - expense,
            "verified": not flags}


def _view(sources):
    return {t["key"]: t for t in ga.build_trip_view(sources)}


def test_view_main_only_is_open_and_archive_only_is_closed():
    sources = {"main": _source([_trip("0630_오제")]),
               "archive": _source([_trip("0107_대만의 사본", copy=True)])}
    view = _view(sources)
    assert view["0630_오제"]["closure"] == "open"
    assert view["0107_대만의 사본"]["closure"] == "closed"
    assert {"ARCHIVE_ONLY", "COPY_NAME"} <= set(view["0107_대만의 사본"]["review"])
    assert view["0107_대만의 사본"]["canonical_source"] == "archive"


def test_same_title_in_both_books_is_one_trip_read_from_main():
    sources = {"main": _source([_trip("0630_오제", income=900, expense=100)]),
               "archive": _source([_trip("0630_오제", income=1000, expense=400)])}
    view = ga.build_trip_view(sources)
    assert len(view) == 1
    trip = view[0]
    assert trip["canonical_source"] == "main" and trip["closure"] == "closed"
    assert trip["income_total"] == 900 and trip["net"] == 800
    assert "DUPLICATE_IN_BOTH" in trip["review"]
    assert trip["copies"]["archive"]["income"]["total"] == 1000


def test_copy_name_with_different_title_is_not_merged_with_main():
    sources = {"main": _source([_trip("0404_에히메")]),
               "archive": _source([_trip("0404_에히메의 사본", copy=True)])}
    view = _view(sources)
    assert set(view) == {"0404_에히메", "0404_에히메의 사본"}
    for trip in view.values():
        assert "POSSIBLE_DUPLICATE" in trip["review"]
        assert trip["income_total"] is None and trip["net"] is None
        assert "DUPLICATE_IN_BOTH" not in trip["review"]


def test_different_year_title_is_not_merged():
    sources = {"main": _source([_trip("0206_하쿠산")]),
               "archive": _source([_trip("0206_하쿠산 2026", copy=False)])}
    view = _view(sources)
    assert "DUPLICATE_IN_BOTH" not in view["0206_하쿠산"]["review"]
    assert view["0206_하쿠산"]["closure"] == "open"
    assert view["0206_하쿠산 2026"]["closure"] == "closed"


def test_total_mismatch_shows_google_figure_but_is_not_verified():
    mismatched = _trip("0630_오제", flags=["TOTAL_MISMATCH", "TOTAL_RANGE_MISMATCH"])
    mismatched["expense"]["verified"] = False
    mismatched["verified"] = False
    (trip,) = ga.build_trip_view({"main": _source([mismatched]), "archive": _source([], last_ok=None, status="error")})
    assert trip["expense_total"] is None and trip["reported"]["expense_total"] == 400
    assert trip["verified"] is False
    assert {"TOTAL_MISMATCH", "TOTAL_RANGE_MISMATCH"} <= set(trip["review"])


def test_view_unknown_closure_until_archive_has_synced_once():
    sources = {"main": _source([_trip("0630_오제")]), "archive": _source([], last_ok=None, status="error")}
    (trip,) = ga.build_trip_view(sources)
    assert trip["closure"] == "unknown" and trip["closure_current"] is False


def _fetcher(payloads):
    def fetch(url):
        for role, sheet_id in ga.SPREADSHEET_IDS.items():
            if sheet_id in url:
                outcome = payloads[role]
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(url)
    return fetch


def _sync(path, **kwargs):
    return ga.sync(path, path.with_name("rows-private.json"), **kwargs)


def _good_books():
    main = workbook_bytes(lambda wb: rev_sheet(wb, "0630_오제", [100], [40]))
    archive = workbook_bytes(lambda wb: rev_sheet(wb, "0107_대만의 사본", [70], [10]))
    return main, archive


def test_sync_writes_snapshot_and_skips_parse_when_unchanged(tmp_path: Path):
    snapshot_path = tmp_path / "google-authority" / "snapshot.json"
    main, archive = _good_books()
    snapshot = _sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)
    assert snapshot["sources"]["main"]["status"] == "ok"
    assert {t["key"]: t["canonical_source"] for t in snapshot["trips"]} == {
        "0107_대만의 사본": "archive", "0630_오제": "main"}

    again = _sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)
    assert again["sources"]["main"]["unchanged"] is True
    assert json.loads(snapshot_path.read_text(encoding="utf-8"))["schema"] == ga.SCHEMA


def test_failed_read_keeps_last_good_trips_and_marks_stale(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    main, archive = _good_books()
    _sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)

    later = NOW + dt.timedelta(hours=1)
    snapshot = _sync(snapshot_path,
                       fetcher=_fetcher({"main": ga.SourceError("SOURCE_NOT_FOUND"), "archive": archive}),
                       now=later)
    main_source = snapshot["sources"]["main"]
    assert main_source["status"] == "error" and main_source["error_code"] == "SOURCE_NOT_FOUND"
    assert main_source["stale"] is True
    assert main_source["last_ok_at"] == NOW.isoformat()
    assert [t["sheet"] for t in main_source["trips"]] == ["0630_오제"]
    assert snapshot["sources"]["archive"]["status"] == "ok"
    trip = next(t for t in snapshot["trips"] if t["key"] == "0630_오제")
    assert "SOURCE_STALE" in trip["review"] and trip["verified"] is False


def test_archive_failure_is_not_reported_as_current_closure(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    main, archive = _good_books()
    _sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)
    snapshot = _sync(snapshot_path,
                       fetcher=_fetcher({"main": main, "archive": ga.SourceError("SOURCE_UNREACHABLE")}),
                       now=NOW + dt.timedelta(hours=1))
    closed = next(t for t in snapshot["trips"] if t["key"] == "0107_대만의 사본")
    assert closed["closure"] == "closed" and closed["closure_current"] is False
    assert snapshot["sources"]["main"]["status"] == "ok"


def test_empty_workbook_never_replaces_known_trips(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    main, archive = _good_books()
    _sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)
    empty = workbook_bytes(lambda wb: wb.create_sheet("매출자료 양식_rev"))
    snapshot = _sync(snapshot_path, fetcher=_fetcher({"main": empty, "archive": archive}), now=NOW)
    assert snapshot["sources"]["main"]["error_code"] == "SOURCE_NO_TRIP_SHEETS"
    assert [t["sheet"] for t in snapshot["sources"]["main"]["trips"]] == ["0630_오제"]


def test_corrupt_snapshot_is_not_overwritten(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text("{not json", encoding="utf-8")
    main, archive = _good_books()
    with pytest.raises(ga.SnapshotError) as raised:
        _sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)
    assert raised.value.code == "SNAPSHOT_UNREADABLE"
    assert snapshot_path.read_text(encoding="utf-8") == "{not json"


def test_previous_schema_snapshot_is_refused_not_mixed(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps({"schema": "google-authority-readonly-v1"}), encoding="utf-8")
    main, archive = _good_books()
    with pytest.raises(ga.SnapshotError) as raised:
        _sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)
    assert raised.value.code == "SNAPSHOT_SCHEMA_MISMATCH"


def test_html_login_page_is_refused_as_wrong_type(monkeypatch):
    class Response:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, limit):
            return b"<html>login</html>"

    monkeypatch.setattr(ga.urllib.request, "urlopen", lambda request, timeout: Response())
    with pytest.raises(ga.SourceError) as raised:
        ga._download("https://example.invalid/export", timeout=1, max_bytes=1024)
    assert raised.value.code == "SOURCE_WRONG_TYPE"


def _row_book(expense_rows, income_amount=100000):
    def build(wb):
        ws = wb.create_sheet("0801_노리쿠라")
        for col, label in zip("BCDEFGH", INCOME):
            ws[f"{col}5"] = label
        ws["B6"], ws["C6"], ws["D6"], ws["H6"] = dt.date(2027, 8, 1), "INCOME-NAME", "INCOME-NICK", income_amount
        ws["C7"] = "=sum(H6:H6)"
        for col, label in zip("BCDEFGH", EXPENSE):
            ws[f"{col}10"] = label
        for index, (payee, category, amount) in enumerate(expense_rows):
            row = 11 + index
            ws[f"B{row}"], ws[f"C{row}"], ws[f"D{row}"] = dt.date(2027, 8, 2), payee, category
            ws[f"F{row}"], ws[f"G{row}"], ws[f"H{row}"] = "RESV-SECRET", "카드", amount
        last = 10 + len(expense_rows)
        ws[f"C{last + 1}"] = f"=SUM(H11:H{last})"
        ws[f"B{last + 3}"] = "합계 및 회사수익인식"
    return workbook_bytes(build)


def test_rows_keep_position_fields_and_negative_refund():
    data = _row_book([("PAYEE-A", "숙박비", 30000), ("PAYEE-B", "식비", -5000)])
    (trip,) = ga.parse_workbook(data)
    expense = trip["rows"]["expense"]
    assert [(r["row"], r["amount"]) for r in expense] == [(11, 30000), (12, -5000)]
    assert expense[0]["cells"]["C"] == "PAYEE-A" and expense[0]["cells"]["D"] == "숙박비"
    assert expense[1]["cells"]["B"] == "2027-08-02"
    assert trip["income"]["row_sum"] == 100000


def test_public_snapshot_has_no_row_contents_but_private_file_does(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    rows_path = tmp_path / "rows-private.json"
    data = _row_book([("PAYEE-SECRET", "식비", 1000)])
    ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    public = snapshot_path.read_text(encoding="utf-8")
    assert "PAYEE-SECRET" not in public and "RESV-SECRET" not in public and "INCOME-NAME" not in public
    assert "PAYEE-SECRET" in _rows_text(snapshot_path, rows_path)


def test_row_changes_are_counted_by_position(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    rows_path = tmp_path / "rows-private.json"
    first = _row_book([("A", "식비", 1000), ("B", "식비", 2000)])
    ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": first, "archive": first}), now=NOW)
    edited = _row_book([("A", "식비", 1500), ("B", "식비", 2000), ("C", "식비", 300)])
    snapshot = ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": edited, "archive": first}), now=NOW)
    assert snapshot["sources"]["main"]["row_changes"] == {"added": 1, "removed": 0, "changed": 1}
    assert snapshot["sources"]["archive"]["row_changes"] == {"added": 0, "removed": 0, "changed": 0}
    removed = _row_book([("A", "식비", 1500)])
    snapshot = ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": removed, "archive": first}), now=NOW)
    assert snapshot["sources"]["main"]["row_changes"] == {"added": 0, "removed": 2, "changed": 0}


def test_failed_read_keeps_private_rows(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    rows_path = tmp_path / "rows-private.json"
    data = _row_book([("KEEP-ME", "식비", 1000)])
    ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    ga.sync(snapshot_path, rows_path,
            fetcher=_fetcher({"main": ga.SourceError("SOURCE_UNREACHABLE"), "archive": data}), now=NOW)
    assert "KEEP-ME" in _rows_text(snapshot_path, rows_path)


def test_nonstandard_tab_in_a_real_sync_does_not_break_row_storage(tmp_path: Path):
    def build(wb):
        ws = wb.create_sheet("0909_제주")
        ws["B25"], ws["D25"], ws["H25"], ws["I25"] = "거래일자", "항목", "증빙유형", "금액(원)"
        ws["I26"] = 30000
        rev_sheet(wb, "0630_오제", [100], [40])

    data = workbook_bytes(build)
    snapshot = _sync(tmp_path / "snapshot.json", fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    assert {t["key"] for t in snapshot["trips"]} == {"0630_오제", "0909_제주"}
    assert snapshot["sources"]["main"]["status"] == "ok"


def _rows_text(snapshot_path: Path, rows_path: Path) -> str:
    generation = json.loads(snapshot_path.read_text(encoding="utf-8"))["rows_generation"]
    return ga._rows_file(rows_path, generation).read_text(encoding="utf-8")


# --------------------------------------------------------------- participant name index

def _name_row_book():
    """수입에 금액이 있는 행 하나, 이름만 있고 날짜·금액이 비어 있는 행 하나."""
    def build(wb):
        ws = wb.create_sheet("0404_에히메")
        ws["B4"] = "수입 내용"
        for col, label in zip("BCDEFGH", INCOME):
            ws[f"{col}5"] = label
        ws["B6"], ws["C6"], ws["H6"] = dt.date(2027, 4, 4), "김가람", 100000
        ws["C7"] = "박다온"
        ws["C9"] = "=sum(H6:H7)"
        ws["B10"] = "지출 내용"
        for col, label in zip("BCDEFGH", EXPENSE):
            ws[f"{col}11"] = label
        ws["B12"], ws["C12"], ws["H12"] = dt.date(2027, 4, 5), "지출처", 30000
        ws["C13"] = "=SUM(H12:H12)"
    return workbook_bytes(build)


def test_participant_name_index_keeps_the_amount_rows_and_totals_unchanged():
    (trip,) = ga.parse_workbook(_name_row_book())
    assert trip["income_rows"] == 1
    assert trip["income"]["row_sum"] == 100000
    assert [row["amount"] for row in trip["rows"]["income"]] == [100000]
    names = trip["name_index"]["income"]
    assert [(row["name"], row["amount"], row["amount_state"]) for row in names] == [
        ("김가람", 100000, "amounted"), ("박다온", None, "blank")]
    assert trip["name_index"]["available"] is True


def test_participant_name_index_does_not_make_a_zero_income_row():
    (trip,) = ga.parse_workbook(_name_row_book())
    assert all(row["amount"] != 0 for row in trip["rows"]["income"])
    assert trip["income"]["row_sum"] == 100000


def test_participant_name_index_keeps_an_amount_error_out_of_the_amount():
    def build(wb):
        ws = wb.create_sheet("0404_에히메")
        for col, label in zip("BCDEFGH", INCOME):
            ws[f"{col}5"] = label
        ws["B6"], ws["C6"], ws["H6"] = dt.date(2027, 4, 4), "김가람", 100000
        ws["C7"], ws["H7"] = "이나래", "#REF!"
        ws["C9"] = "=sum(H6:H7)"
        ws["B10"] = "지출 내용"
        for col, label in zip("BCDEFGH", EXPENSE):
            ws[f"{col}11"] = label
        ws["B12"], ws["C12"], ws["H12"] = dt.date(2027, 4, 5), "지출처", 30000
        ws["C13"] = "=SUM(H12:H12)"
    (trip,) = ga.parse_workbook(workbook_bytes(build))
    assert "FORMULA_ERROR" in trip["flags"]
    assert trip["income"]["total"] is None
    states = {row["name"]: row["amount_state"] for row in trip["name_index"]["income"]}
    assert states["김가람"] == "amounted" and states["이나래"] == "formula_error"


def test_participant_name_index_is_private_and_the_public_snapshot_stays_clean(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    rows_path = tmp_path / "rows-private.json"
    data = _name_row_book()
    ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    public = snapshot_path.read_text(encoding="utf-8")
    assert "김가람" not in public and "박다온" not in public
    private = json.loads(_rows_text(snapshot_path, rows_path))
    names = private["sources"]["main"]["income_names"]["0404_에히메"]
    assert names["available"] is True
    assert [row["name"] for row in names["income"]] == ["김가람", "박다온"]


def test_participant_name_index_is_unavailable_for_a_nonstandard_tab():
    def build(wb):
        ws = wb.create_sheet("0909_제주")
        ws["B25"], ws["D25"], ws["F25"], ws["H25"], ws["I25"] = "거래일자", "항목", "내용", "증빙유형", "금액(원)"
        ws["B26"], ws["I26"] = dt.date(2026, 9, 9), 30000
    (trip,) = ga.parse_workbook(workbook_bytes(build))
    assert trip["name_index"]["available"] is False
    assert trip["name_index"]["income"] == []


def test_participant_name_index_is_missing_in_an_older_generation(tmp_path: Path):
    from webapp import google_ledger_page as page
    rows = {"main": {"trips": {"0404_에히메": {"income": [], "expense": []}}}}
    assert page.owner_income_names(rows, "0404_에히메", "main") is None
    rows["main"]["income_names"] = {"0404_에히메": {"available": True, "income": [
        {"row": 6, "cells": {"B": "", "C": "김가람", "D": "", "E": "", "F": "", "G": ""},
         "name": "김가람", "nickname": "", "amount": None, "amount_state": "blank"}]}}
    index = page.owner_income_names(rows, "0404_에히메", "main")
    assert index["available"] is True and index["rows"][0]["name"] == "김가람"


def test_participant_name_index_is_created_for_an_older_snapshot_of_the_same_workbook(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    rows_path = tmp_path / "rows-private.json"
    data = _name_row_book()
    ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    # 구버전 스냅샷: 이전 파서 세대이고 이름 인덱스가 없다.
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    for record in snapshot["sources"].values():
        record["parser_version"] = "quarter-expense-v1"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    rows_file = ga._rows_file(rows_path, snapshot["rows_generation"])
    rows_doc = json.loads(rows_file.read_text(encoding="utf-8"))
    for source in rows_doc["sources"].values():
        source.pop("income_names", None)
    rows_file.write_text(json.dumps(rows_doc, ensure_ascii=False), encoding="utf-8")

    again = ga.sync(snapshot_path, rows_path,
                    fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    # 같은 workbook 해시여도 이름 인덱스가 없으면 다시 읽는다.
    assert again["sources"]["main"]["unchanged"] is False
    assert again["sources"]["main"]["parser_version"] == ga.PARSER_VERSION == "quarter-expense-v2"
    private = json.loads(_rows_text(snapshot_path, rows_path))
    index = private["sources"]["main"]["income_names"]["0404_에히메"]
    assert index["available"] is True
    assert [row["name"] for row in index["income"]] == ["김가람", "박다온"]


def test_adc_setup_failure_marks_last_good_stale_without_public_fallback(tmp_path, monkeypatch, capsys):
    from app import google_adc_export, sync_schedule
    from tools import google_authority_sync as cli

    snapshot_path, rows_path = tmp_path / 'snapshot.json', tmp_path / 'rows.json'
    now = dt.datetime.now(ga.KST)
    data = _row_book([('SYNTHETIC-PRIVATE-PAYEE', '식비', 1234)])
    good = ga.sync(snapshot_path, rows_path,
                   fetcher=_fetcher({'main': data, 'archive': data}), now=now)
    private_before = json.loads(_rows_text(snapshot_path, rows_path))['sources']
    sync_schedule.record_result(tmp_path / 'sync-state.json', ok=True, now=now)

    def unavailable(**kwargs):
        raise RuntimeError('synthetic-secret-token')

    monkeypatch.setattr(google_adc_export, 'authorized_export_fetcher', unavailable)
    monkeypatch.setattr(ga, '_download', lambda *args, **kwargs: pytest.fail('public fallback'))
    assert cli.main(['--snapshot', str(snapshot_path), '--rows', str(rows_path),
                     '--google-auth', 'adc']) == 5
    output = capsys.readouterr()
    assert 'synthetic-secret-token' not in output.out + output.err
    assert 'SYNTHETIC-PRIVATE-PAYEE' not in output.out + output.err
    failed = ga.load_snapshot(snapshot_path)
    for role, source in failed['sources'].items():
        assert source['status'] == 'error' and source['stale'] is True
        assert source['error_code'] == 'GOOGLE_AUTH_UNAVAILABLE'
        assert source['last_ok_at'] == good['sources'][role]['last_ok_at']
        assert source['trips'] == good['sources'][role]['trips']
    assert json.loads(_rows_text(snapshot_path, rows_path))['sources'] == private_before
    state = sync_schedule.read_state(tmp_path / 'sync-state.json')
    assert state['last_ok_at'] == now.isoformat()
    assert state['last_error'] == 'GOOGLE_AUTH_UNAVAILABLE'
    assert state['consecutive_failures'] == 1


def test_adc_partial_outage_and_recovery_preserve_private_last_good(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import google_adc_export, sync_schedule
    from tools import google_authority_sync as cli

    snapshot_path, rows_path = tmp_path / 'snapshot.json', tmp_path / 'rows.json'
    original = _row_book([('ORIGINAL-PAYEE', '식비', 1000)])
    updated = _row_book([('UPDATED-PAYEE', '식비', 2000)])
    ga.sync(snapshot_path, rows_path,
            fetcher=_fetcher({'main': original, 'archive': original}), now=NOW)
    before = json.loads(_rows_text(snapshot_path, rows_path))['sources']

    class Clock:
        current = NOW + dt.timedelta(minutes=1)

        @classmethod
        def now(cls, tz):
            return cls.current

    monkeypatch.setattr(cli, 'dt', SimpleNamespace(datetime=Clock))
    monkeypatch.setattr(ga, '_download', lambda *args, **kwargs: pytest.fail('public fallback'))
    monkeypatch.setattr(google_adc_export, 'authorized_export_fetcher', lambda **kwargs:
                        _fetcher({'main': ga.SourceError('SOURCE_UNREACHABLE'), 'archive': updated}))
    args = ['--snapshot', str(snapshot_path), '--rows', str(rows_path), '--google-auth', 'adc']
    assert cli.main(args) == 1
    partial = ga.load_snapshot(snapshot_path)
    private = json.loads(_rows_text(snapshot_path, rows_path))['sources']
    assert partial['sources']['main']['stale'] is True
    assert partial['sources']['main']['last_ok_at'] == NOW.isoformat()
    assert private['main'] == before['main']
    assert partial['sources']['archive']['status'] == 'ok'
    assert private['archive'] != before['archive']
    Clock.current += dt.timedelta(minutes=6)
    monkeypatch.setattr(google_adc_export, 'authorized_export_fetcher', lambda **kwargs:
                        _fetcher({'main': updated, 'archive': updated}))
    assert cli.main(args) == 0
    recovered = ga.load_snapshot(snapshot_path)
    for source in recovered['sources'].values():
        assert source['status'] == 'ok' and source['stale'] is False
        assert source['last_ok_at'] == Clock.current.isoformat()
    private = json.loads(_rows_text(snapshot_path, rows_path))['sources']
    assert private['main'] != before['main']
    assert sync_schedule.read_state(tmp_path / 'sync-state.json')['consecutive_failures'] == 0


def test_adc_corrupt_xlsx_keeps_last_good_and_recovers_through_real_adapter(tmp_path, monkeypatch, capsys):
    import google.auth
    from google.auth.transport import requests
    from types import SimpleNamespace
    from tools import google_authority_sync as cli
    from tests.card_pipeline.test_google_adc_export import FakeResponse

    snapshot_path, rows_path = tmp_path / 'snapshot.json', tmp_path / 'rows.json'
    original = _row_book([('ORIGINAL-PAYEE', '식비', 1000)])
    updated = _row_book([('UPDATED-PAYEE', '식비', 2000)])
    ga.sync(snapshot_path, rows_path, fetcher=_fetcher({'main': original, 'archive': original}), now=NOW)
    before = json.loads(_rows_text(snapshot_path, rows_path))['sources']
    scopes, responses, calls = [], [], []
    payloads = {'main': b'SYNTHETIC-PRIVATE-BROKEN-XLSX', 'archive': updated}

    class Session:
        def get(self, url, **kwargs):
            role = next(role for role, identity in ga.SPREADSHEET_IDS.items() if f'/{identity}/export' in url)
            calls.append((role, kwargs))
            response = FakeResponse(payload=payloads[role])
            responses.append(response)
            return response

    class Clock:
        current = NOW + dt.timedelta(minutes=1)

        @classmethod
        def now(cls, tz):
            return cls.current

    monkeypatch.setattr(cli, 'dt', SimpleNamespace(datetime=Clock))
    monkeypatch.setattr(google.auth, 'default', lambda **kwargs: (scopes.append(kwargs['scopes']), None))
    monkeypatch.setattr(requests, 'AuthorizedSession', lambda credentials: Session())
    monkeypatch.setattr(ga, '_download', lambda *args, **kwargs: pytest.fail('anonymous fallback'))
    args = ['--snapshot', str(snapshot_path), '--rows', str(rows_path), '--google-auth', 'adc']
    assert cli.main(args) == 1
    partial = ga.load_snapshot(snapshot_path)
    private = json.loads(_rows_text(snapshot_path, rows_path))['sources']
    assert partial['sources']['main']['error_code'] == 'SOURCE_PARSE_FAILED'
    assert partial['sources']['main']['stale'] is True
    assert partial['sources']['main']['last_ok_at'] == NOW.isoformat()
    assert private['main'] == before['main']
    assert private['archive'] != before['archive']
    payloads['main'] = updated
    Clock.current += dt.timedelta(minutes=6)
    assert cli.main(args) == 0
    recovered = ga.load_snapshot(snapshot_path)
    assert all(source['status'] == 'ok' and not source['stale'] for source in recovered['sources'].values())
    assert all(scope == ['https://www.googleapis.com/auth/drive.readonly'] for scope in scopes)
    assert all(not kwargs['allow_redirects'] for _, kwargs in calls)
    assert all(response.closed for response in responses)
    output = capsys.readouterr()
    assert all(secret not in output.out + output.err for secret in
               ('SYNTHETIC-PRIVATE-BROKEN-XLSX', 'ORIGINAL-PAYEE', 'UPDATED-PAYEE'))


def test_crash_before_snapshot_replace_keeps_old_snapshot_and_rows_consistent(tmp_path: Path, monkeypatch):
    snapshot_path = tmp_path / "snapshot.json"
    rows_path = tmp_path / "rows-private.json"
    first = _row_book([("OLD-PAYEE", "식비", 1000)])
    ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": first, "archive": first}), now=NOW)
    before = snapshot_path.read_text(encoding="utf-8")

    real_write = ga._write_atomic
    def crash_on_snapshot(path, obj):
        if path == snapshot_path:
            raise OSError("disk full")
        real_write(path, obj)
    monkeypatch.setattr(ga, "_write_atomic", crash_on_snapshot)
    changed = _row_book([("NEW-PAYEE", "식비", 9000)])
    with pytest.raises(OSError):
        ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": changed, "archive": first}), now=NOW)
    monkeypatch.setattr(ga, "_write_atomic", real_write)

    assert snapshot_path.read_text(encoding="utf-8") == before
    assert "OLD-PAYEE" in _rows_text(snapshot_path, rows_path)
    # The next good run works from the old generation and replaces it cleanly.
    ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": changed, "archive": first}), now=NOW)
    assert "NEW-PAYEE" in _rows_text(snapshot_path, rows_path)


def test_snapshot_naming_a_missing_rows_generation_is_refused(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    rows_path = tmp_path / "rows-private.json"
    data = _row_book([("A", "식비", 1)])
    ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    generation = json.loads(snapshot_path.read_text(encoding="utf-8"))["rows_generation"]
    ga._rows_file(rows_path, generation).unlink()
    with pytest.raises(ga.SnapshotError) as raised:
        ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    assert raised.value.code == "ROWS_MISSING"


def test_rows_file_from_another_generation_is_refused(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    rows_path = tmp_path / "rows-private.json"
    data = _row_book([("A", "식비", 1)])
    ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    generation = json.loads(snapshot_path.read_text(encoding="utf-8"))["rows_generation"]
    other = json.loads(ga._rows_file(rows_path, generation).read_text(encoding="utf-8"))
    other["generation"] = "someone-else"
    ga._rows_file(rows_path, generation).write_text(json.dumps(other), encoding="utf-8")
    with pytest.raises(ga.SnapshotError) as raised:
        ga.sync(snapshot_path, rows_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    assert raised.value.code == "ROWS_GENERATION_MISMATCH"


def test_previous_generation_is_kept_for_readers_and_the_oldest_is_removed(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    rows_path = tmp_path / "rows-private.json"
    gens = []
    for minute in range(3):
        data = _row_book([("A", "식비", minute + 1)])
        _sync(snapshot_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW + dt.timedelta(minutes=minute))
        gens.append(json.loads(snapshot_path.read_text(encoding="utf-8"))["rows_generation"])
    assert len(set(gens)) == 3
    assert not ga._rows_file(rows_path, gens[0]).exists()  # two runs old: removed
    assert ga._rows_file(rows_path, gens[1]).exists()      # previous: kept for a reader in flight
    assert ga._rows_file(rows_path, gens[2]).exists()      # current


def test_generation_cleanup_preserves_backups_and_unrecognized_files(tmp_path):
    rows_path = tmp_path / 'rows-private.json'
    protected = {
        'rows-private.backup.json': b'synthetic original backup',
        'rows-private.original.json': b'synthetic original',
        'rows-private.' + 'a' * 32 + '.json': b'{broken recovery evidence',
        'rows-private.' + 'b' * 32 + '.json': json.dumps({'schema': 'other', 'generation': 'b' * 32}).encode(),
    }
    for name, body in protected.items():
        (tmp_path / name).write_bytes(body)
    orphan = ga._rows_file(rows_path, 'c' * 32)
    orphan.write_text(json.dumps({'schema': ga.ROWS_SCHEMA, 'generation': 'c' * 32, 'sources': {}}))
    ga._remove_other_generations(rows_path, keep=set())
    assert not orphan.exists()
    for name, body in protected.items():
        assert (tmp_path / name).read_bytes() == body

def test_unverified_figures_are_reported_separately_from_totals():
    mismatched = _trip("0630_오제", flags=["TOTAL_MISMATCH"])
    mismatched["verified"] = False
    (trip,) = ga.build_trip_view({"main": _source([mismatched]), "archive": _source([], last_ok=None, status="error")})
    assert trip["net"] is None and trip["income_total"] is None
    assert trip["reported"]["net"] == 600


def test_reader_gets_a_consistent_pair(tmp_path: Path):
    snapshot_path, rows_path = tmp_path / "snapshot.json", tmp_path / "rows-private.json"
    data = _row_book([("A", "식비", 1)])
    _sync(snapshot_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    snapshot, rows = ga.load_consistent(snapshot_path, rows_path)
    assert snapshot["schema"] == ga.SCHEMA and "main" in rows


def test_reader_refuses_rows_whose_fingerprint_belongs_to_another_run(tmp_path: Path):
    snapshot_path, rows_path = tmp_path / "snapshot.json", tmp_path / "rows-private.json"
    data = _row_book([("A", "식비", 1)])
    _sync(snapshot_path, fetcher=_fetcher({"main": data, "archive": data}), now=NOW)
    generation = json.loads(snapshot_path.read_text(encoding="utf-8"))["rows_generation"]
    rows_file = ga._rows_file(rows_path, generation)
    doc = json.loads(rows_file.read_text(encoding="utf-8"))
    doc["sources"]["main"]["content_sha256"] = "0" * 64
    rows_file.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ga.SnapshotError) as raised:
        ga.load_consistent(snapshot_path, rows_path)
    assert raised.value.code == "GENERATION_MISMATCH"


def test_reader_refuses_a_missing_snapshot(tmp_path: Path):
    with pytest.raises(ga.SnapshotError) as raised:
        ga.load_consistent(tmp_path / "none.json", tmp_path / "rows.json")
    assert raised.value.code == "SNAPSHOT_MISSING"


def test_readers_never_see_a_mixed_pair_while_the_writer_swaps_generations(tmp_path: Path):
    import threading
    snapshot_path, rows_path = tmp_path / "snapshot.json", tmp_path / "rows-private.json"
    books = [_row_book([("A%d" % i, "식비", 1000 + i)]) for i in range(2)]
    _sync(snapshot_path, fetcher=_fetcher({"main": books[0], "archive": books[1]}), now=NOW)
    failures, reads, stop = [], [0], threading.Event()

    def writer():
        try:
            for i in range(12):
                data = books[i % 2]
                _sync(snapshot_path, fetcher=_fetcher({"main": data, "archive": books[(i + 1) % 2]}),
                      now=NOW + dt.timedelta(minutes=i))
        except Exception as error:  # a dead writer must still stop the readers
            failures.append("writer: " + repr(error))
        finally:
            stop.set()

    def reader():
        import time
        while not stop.is_set():
            time.sleep(0.002)
            try:
                snapshot, rows = ga.load_consistent(snapshot_path, rows_path)
                for role, record in snapshot["sources"].items():
                    if record.get("content_sha256") != rows.get(role, {}).get("content_sha256"):
                        failures.append("mixed pair")
                reads[0] += 1
            except ga.SnapshotError as error:
                failures.append(error.code)

    threads = [threading.Thread(target=reader) for _ in range(3)] + [threading.Thread(target=writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert failures == [], failures[:5]
    assert reads[0] > 0
    generations = list(tmp_path.glob("rows-private.*.json"))
    assert len(generations) <= 2  # current and previous only


def test_a_crash_between_the_two_writes_leaves_a_readable_pair_and_the_next_run_cleans_up(tmp_path: Path,
                                                                                       monkeypatch):
    snapshot_path, rows_path = tmp_path / "snapshot.json", tmp_path / "rows-private.json"
    first = _row_book([("OLD", "식비", 1)])
    _sync(snapshot_path, fetcher=_fetcher({"main": first, "archive": first}), now=NOW)
    before = snapshot_path.read_text(encoding="utf-8")
    real = ga._write_atomic

    def crash_on_snapshot(path, obj):
        if path == snapshot_path:
            raise OSError("power loss")
        real(path, obj)

    newer = _row_book([("NEW", "식비", 2)])
    monkeypatch.setattr(ga, "_write_atomic", crash_on_snapshot)
    with pytest.raises(OSError):
        _sync(snapshot_path, fetcher=_fetcher({"main": newer, "archive": newer}), now=NOW)
    monkeypatch.setattr(ga, "_write_atomic", real)
    assert snapshot_path.read_text(encoding="utf-8") == before
    snapshot, rows = ga.load_consistent(snapshot_path, rows_path)
    assert "OLD" in json.dumps(rows)
    orphans = list(tmp_path.glob("rows-private.*.json"))
    assert len(orphans) == 2  # the old generation and the orphan from the crash
    _sync(snapshot_path, fetcher=_fetcher({"main": newer, "archive": newer}), now=NOW + dt.timedelta(minutes=5))
    assert len(list(tmp_path.glob("rows-private.*.json"))) == 2
    snapshot, rows = ga.load_consistent(snapshot_path, rows_path)
    assert "NEW" in json.dumps(rows)


def test_a_quarter_tab_kept_only_as_a_copy_groups_under_the_quarter_title():
    def build(wb):
        wb.create_sheet("2분기_기타비용의 사본")
    (tab,) = ga.parse_workbook(workbook_bytes(build))
    assert tab["sheet"] == "2분기_기타비용" and tab["copy_name"] is True
    assert tab["kind"] == "quarter" and tab["quarter"] == 2
    assert tab["verified"] is False and "LAYOUT_NOT_STANDARD" in tab["flags"]


@pytest.mark.parametrize('title,sheet,expected', [
    ('2026년 월 매출 확인자료_오제_0630_0704', '0630_오제', ('2026-06-30', '2026-07-04', '오제')),
    ('2026년 1월 매출 확인자료_1201_1205_도쿄', '1201_도쿄', ('2026-12-01', '2026-12-05', '도쿄')),
    ('2026년 월 매출 확인자료_', '0712_몽골', ('2026-07-12', None, '')),
    ('2026년 2분기 수기장부형 자료_0506_0610_유럽', '0506_0610_유럽', ('2026-05-06', '2026-06-10', '유럽')),
])
def test_trip_period_takes_year_and_end_from_the_top_title(title, sheet, expected):
    def build(wb):
        ws = wb.create_sheet(sheet)
        ws['C2'] = title
    ws = openpyxl.load_workbook(io.BytesIO(workbook_bytes(build)))[sheet]
    period = ga.parse_trip_period(ws, sheet)
    assert (period['starts_on'], period['ends_on'], period['destination']) == expected


def test_trip_period_without_a_year_uses_the_base_year_and_another_start_is_held():
    def build(wb):
        wb.create_sheet('0506_0610_유럽')['C2'] = '매출 확인자료_유럽_0506_0610'
        wb.create_sheet('0107_대만')['C2'] = '2026년 매출 확인자료_대만_0108_0114'
    wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes(build)))
    europe = ga.parse_trip_period(wb['0506_0610_유럽'], '0506_0610_유럽')
    assert (europe['starts_on'], europe['ends_on'], europe['flags']) == ('2026-05-06', '2026-06-10', [])
    assert 'PERIOD_START_MISMATCH' in ga.parse_trip_period(wb['0107_대만'], '0107_대만')['flags']


def test_tabs_after_the_december_tabs_of_the_main_workbook_are_next_year():
    def build(wb):
        for name in ('1205_도쿄', '0206_하쿠산', '0302_야쿠시마'):
            wb.create_sheet(name)['C2'] = '2026년 월 매출 확인자료_'
    trips = {t['sheet']: t['period'] for t in ga.parse_workbook(workbook_bytes(build), rollover=True)}
    assert trips['1205_도쿄']['starts_on'] == '2026-12-05'
    assert trips['0206_하쿠산']['starts_on'] == '2027-02-06'
    assert trips['0302_야쿠시마']['starts_on'] == '2027-03-02'
    unchanged = {t['sheet']: t['period'] for t in ga.parse_workbook(workbook_bytes(build))}
    assert unchanged['0206_하쿠산']['starts_on'] == '2026-02-06'


def test_end_comes_from_the_expense_period_range_when_the_title_has_none():
    def build(wb):
        ws = wb.create_sheet('0823_화순')
        ws['C2'] = '2026년 월 매출 확인자료_'
        for col, label in zip('BCDEFGH', EXPENSE):
            ws[f'{col}10'] = label
        ws['B11'] = dt.date(2026, 8, 20)
        ws['E11'] = '0823_0826'
        ws['B12'] = dt.date(2026, 7, 1)
        ws['E12'] = '0701_0709'
        ws['E13'] = 1005.0
    ws = openpyxl.load_workbook(io.BytesIO(workbook_bytes(build)))['0823_화순']
    period = ga.parse_trip_period(ws, '0823_화순')
    assert period['ends_on'] == '2026-08-26' and period['flags'] == ['PERIOD_END_FROM_ITEMS']


def test_a_trip_without_an_end_ends_the_day_before_the_next_trip_starts():
    def trip(key, start, end=None):
        return {'key': key, 'sheet': key, 'copy_name': False, 'kind': 'trip', 'layout': 'nonstandard', 'verified': False,
                'flags': [], 'income': None, 'expense': None, 'net': None,
                'period': {'year': 2026, 'starts_on': start, 'ends_on': end, 'destination': '',
                           'flags': [] if end else ['PERIOD_END_MISSING']}}
    main = {'status': 'ok', 'trips': [trip('0712_몽골', '2026-07-12'), trip('0721_황금해안', '2026-07-21', '2026-07-23')]}
    archive = {'status': 'ok', 'trips': [trip('0630_오제', '2026-06-30', '2026-07-04')]}
    view = {t['key']: t['period'] for t in ga.build_trip_view({'main': main, 'archive': archive})}
    assert view['0712_몽골']['ends_on'] == '2026-07-20'
    assert 'PERIOD_END_FROM_NEXT_TRIP' in view['0712_몽골']['flags']
    assert view['0721_황금해안']['ends_on'] == '2026-07-23'
