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


def rev_sheet(wb, title, income_amounts, expense_amounts, *, income_total=None, expense_total=None):
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


def test_rev_trip_tab_totals_and_formula_recognition():
    def build(wb):
        rev_sheet(wb, "0206_하쿠산", [100000, 50000], [30000, 20000, 5000])

    trips = ga.parse_workbook(workbook_bytes(build))
    assert len(trips) == 1
    trip = trips[0]
    assert trip["key"] == "0206_하쿠산" and trip["copy_name"] is False
    assert trip["layout"] == "rev"
    assert (trip["income_total"], trip["expense_total"], trip["net"]) == (150000, 55000, 95000)
    assert (trip["income_rows"], trip["expense_rows"]) == (2, 3)
    # Plain values cannot carry a cached formula result, so the total is reported as not cached.
    assert trip["flags"] == ["TOTAL_NOT_CACHED"]


class _Cell:
    def __init__(self, value):
        self.value = value


class _Sheet:
    def __init__(self, values):
        self._values = values

    def cell(self, row, column):
        return _Cell(self._values.get((row, column)))


@pytest.mark.parametrize("cached, expected, flags", [
    (1050, 1050, set()),
    (1200, 1200, {"TOTAL_MISMATCH"}),
    (None, None, {"TOTAL_NOT_CACHED"}),
    ("#REF!", None, {"FORMULA_ERROR"}),
])
def test_sheet_total_is_the_figure_and_disagreement_is_flagged(cached, expected, flags):
    sheet = _Sheet({(18, 3): cached})
    found = {(18, 3, 6, 17)}
    block_flags: set = set()
    total = ga._check_total(found, 6, 19, sheet, 1050, 12, 6, 17, block_flags)
    assert total == expected and block_flags == flags


def test_total_range_that_misses_data_is_flagged():
    sheet = _Sheet({(33, 3): 1050})
    block_flags: set = set()
    ga._check_total({(33, 3, 22, 30)}, 22, 32, sheet, 1050, 12, 22, 32, block_flags)
    assert block_flags == {"TOTAL_RANGE_MISMATCH"}


def test_non_trip_sheets_are_ignored():
    def build(wb):
        rev_sheet(wb, "매출자료 양식_rev", [], [])
        wb.create_sheet("3분기_기타비용")
        wb.create_sheet("프리랜서 지급대장")
        rev_sheet(wb, "0630_오제", [10], [4])

    assert [t["key"] for t in ga.parse_workbook(workbook_bytes(build))] == ["0630_오제"]


def test_legacy_layout_is_reported_not_converted():
    def build(wb):
        ws = wb.create_sheet("0909_제주")
        ws["B25"], ws["D25"], ws["F25"], ws["H25"], ws["I25"] = "거래일자", "항목", "내용", "증빙유형", "금액(원)"
        ws["B26"] = dt.date(2026, 9, 9)
        ws["I26"] = 30000

    trip = ga.parse_workbook(workbook_bytes(build))[0]
    assert trip["layout"] == "nonstandard"
    assert trip["flags"] == ["LAYOUT_NOT_STANDARD"]
    assert trip["income_total"] is None and trip["expense_total"] is None and trip["net"] is None


def test_error_value_blocks_block_total_instead_of_zeroing_it():
    def build(wb):
        rev_sheet(wb, "0630_오제", [100000], [30000])
        ws = wb["0630_오제"]
        expense_data_row = next(r for r in range(1, ws.max_row + 1) if ws[f"H{r}"].value == 30000)
        ws[f"H{expense_data_row}"] = "#REF!"

    trip = ga.parse_workbook(workbook_bytes(build))[0]
    assert "FORMULA_ERROR" in trip["flags"]
    assert trip["expense_total"] is None and trip["net"] is None
    assert trip["income_total"] == 100000


def test_copy_name_is_normalized_and_flagged():
    def build(wb):
        rev_sheet(wb, "0404_에히메의 사본", [1], [1])

    trip = ga.parse_workbook(workbook_bytes(build))[0]
    assert trip["key"] == "0404_에히메" and trip["copy_name"] is True


def _source(trips, *, status="ok", last_ok="2026-10-11T09:00:00+09:00", stale=False):
    return {"status": status, "trips": trips, "last_ok_at": last_ok, "stale": stale}


def _trip(key, *, layout="rev", income=1000, expense=400, copy=False, sheet=None):
    return {"sheet": sheet or key, "key": key, "copy_name": copy, "layout": layout,
            "income_total": income if layout == "rev" else None,
            "expense_total": expense if layout == "rev" else None,
            "net": income - expense if layout == "rev" else None, "flags": []}


def test_view_main_only_is_open_and_archive_only_is_closed():
    sources = {"main": _source([_trip("0630_오제")]),
               "archive": _source([_trip("0107_대만", copy=True, sheet="0107_대만의 사본")])}
    view = {t["key"]: t for t in ga.build_trip_view(sources)}
    assert view["0630_오제"]["closure"] == "open"
    assert view["0107_대만"]["closure"] == "closed"
    assert "ARCHIVE_ONLY" in view["0107_대만"]["review"] and "COPY_NAME" in view["0107_대만"]["review"]
    assert view["0107_대만"]["canonical_source"] == "archive"


def test_view_same_trip_in_both_books_prefers_main_and_flags_it():
    sources = {"main": _source([_trip("0630_오제", income=900, expense=100)]),
               "archive": _source([_trip("0630_오제", income=1000, expense=400)])}
    (trip,) = ga.build_trip_view(sources)
    assert trip["canonical_source"] == "main"
    assert trip["closure"] == "closed"
    assert trip["income_total"] == 900 and trip["net"] == 800
    assert "DUPLICATE_IN_BOTH" in trip["review"]


def test_view_unknown_closure_until_archive_has_synced_once():
    sources = {"main": _source([_trip("0630_오제")]), "archive": _source([], last_ok=None, status="error")}
    (trip,) = ga.build_trip_view(sources)
    assert trip["closure"] == "unknown"


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


def _good_books():
    main = workbook_bytes(lambda wb: rev_sheet(wb, "0630_오제", [100], [40]))
    archive = workbook_bytes(lambda wb: rev_sheet(wb, "0107_대만의 사본", [70], [10]))
    return main, archive


def test_sync_writes_snapshot_and_skips_parse_when_unchanged(tmp_path: Path):
    snapshot_path = tmp_path / "google-authority" / "snapshot.json"
    main, archive = _good_books()
    snapshot = ga.sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)
    assert snapshot["sources"]["main"]["status"] == "ok"
    assert {t["key"]: t["canonical_source"] for t in snapshot["trips"]} == {
        "0107_대만": "archive", "0630_오제": "main"}

    again = ga.sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)
    assert again["sources"]["main"]["unchanged"] is True
    assert json.loads(snapshot_path.read_text(encoding="utf-8"))["schema"] == ga.SCHEMA


def test_failed_read_keeps_last_good_trips(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    main, archive = _good_books()
    ga.sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)

    later = NOW + dt.timedelta(hours=1)
    snapshot = ga.sync(snapshot_path,
                       fetcher=_fetcher({"main": ga.SourceError("SOURCE_NOT_FOUND"), "archive": archive}),
                       now=later)
    main_source = snapshot["sources"]["main"]
    assert main_source["status"] == "error" and main_source["error_code"] == "SOURCE_NOT_FOUND"
    assert main_source["stale"] is True
    assert main_source["last_ok_at"] == NOW.isoformat()
    assert [t["key"] for t in main_source["trips"]] == ["0630_오제"]
    assert "SOURCE_STALE" in next(t for t in snapshot["trips"] if t["key"] == "0630_오제")["review"]


def test_empty_workbook_never_replaces_known_trips(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    main, archive = _good_books()
    ga.sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)
    empty = workbook_bytes(lambda wb: wb.create_sheet("매출자료 양식_rev"))
    snapshot = ga.sync(snapshot_path, fetcher=_fetcher({"main": empty, "archive": archive}), now=NOW)
    assert snapshot["sources"]["main"]["error_code"] == "SOURCE_NO_TRIP_SHEETS"
    assert [t["key"] for t in snapshot["sources"]["main"]["trips"]] == ["0630_오제"]


def test_corrupt_snapshot_is_not_overwritten(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text("{not json", encoding="utf-8")
    main, archive = _good_books()
    with pytest.raises(ga.SnapshotError) as raised:
        ga.sync(snapshot_path, fetcher=_fetcher({"main": main, "archive": archive}), now=NOW)
    assert raised.value.code == "SNAPSHOT_UNREADABLE"
    assert snapshot_path.read_text(encoding="utf-8") == "{not json"


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
