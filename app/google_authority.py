"""Read-only sync of the Google trip ledgers into a standalone snapshot.

Reads the active main workbook and the archive workbook as xlsx exports, finds the
trip tabs in the 매출자료 양식_rev layout and keeps only totals and status codes.
Nothing is written to Google, nothing touches the operating board database, and
row contents (names, reservation numbers, payees) are not kept.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import openpyxl

SPREADSHEET_IDS = {
    "main": "1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU",
    "archive": "1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8",
}
EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
SCHEMA = "google-authority-readonly-v1"
KST = dt.timezone(dt.timedelta(hours=9))
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_BYTES = 64 * 1024 * 1024

INCOME_HEADER = ("거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)")
EXPENSE_HEADER = ("거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)")
TRIP_NAME = re.compile(r"^\d{4}_\S")
COPY_SUFFIX = re.compile(r"\s*의 사본$")
SUM_OF_AMOUNTS = re.compile(r"^=\s*SUM\(\s*H(\d+)(?:\s*:\s*H(\d+))?\s*\)$", re.IGNORECASE)
# A block with any of these cannot be summed safely. Its total is None, never 0.
BLOCKING_FLAGS = {"FORMULA_ERROR", "AMOUNT_INVALID", "AMOUNT_MISSING", "AMOUNT_NOT_CACHED"}


class SourceError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class SnapshotError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _is_date(value) -> bool:
    return isinstance(value, (dt.date, dt.datetime))


def _sum_block(first: int, last: int, ws_f, ws_v, flags: set) -> tuple[int, int, int | None, int | None]:
    total, rows, first_row, last_row = 0, 0, None, None
    for row in range(first, last + 1):
        value = ws_v.cell(row=row, column=8).value
        if value is None or value == "":
            formula = ws_f.cell(row=row, column=8).value
            if isinstance(formula, str) and formula.startswith("="):
                flags.add("AMOUNT_NOT_CACHED")
            elif _is_date(ws_v.cell(row=row, column=2).value):
                flags.add("AMOUNT_MISSING")
            continue
        if isinstance(value, str) and value.startswith("#"):
            flags.add("FORMULA_ERROR")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value).is_integer():
            flags.add("AMOUNT_INVALID")
        else:
            total += int(value)
            rows += 1
            first_row = first_row or row
            last_row = row
    return total, rows, first_row, last_row


def _sum_formulas(ws_f) -> list[tuple[int, int, int, int]]:
    found = []
    for row in ws_f.iter_rows():
        for cell in row:
            match = SUM_OF_AMOUNTS.match(cell.value) if isinstance(cell.value, str) else None
            if match:
                start = int(match.group(1))
                end = int(match.group(2) or match.group(1))
                found.append((cell.row, cell.column, start, end))
    return found


def _check_total(formulas, first, last, ws_v, computed, rows, first_row, last_row, flags: set) -> int | None:
    """Compare the sheet's own total with the rows it should sum. Returns the sheet total."""
    # A total may start on the header row, which holds text and sums to nothing.
    inside = [item for item in formulas if first - 1 <= item[2] and item[3] <= last]
    if len(inside) != 1:
        flags.add("TOTAL_FORMULA_UNCLEAR")
        return None
    row, column, start, end = inside[0]
    if rows and (start > first_row or end < last_row):
        flags.add("TOTAL_RANGE_MISMATCH")
    cached = ws_v.cell(row=row, column=column).value
    if cached is None:
        flags.add("TOTAL_NOT_CACHED")
        return None
    if not isinstance(cached, (int, float)) or isinstance(cached, bool):
        flags.add("FORMULA_ERROR")
        return None
    if abs(cached - computed) > 0.5:
        flags.add("TOTAL_MISMATCH")
    return int(round(cached))


def parse_trip_sheet(ws_f, ws_v) -> dict:
    """One trip tab. Nonstandard layouts are reported, never converted."""
    last_row = ws_v.max_row or 0
    income_rows, expense_rows = [], []
    for row in range(1, last_row + 1):
        labels = tuple(_text(ws_v.cell(row=row, column=column).value) for column in range(2, 9))
        if labels == INCOME_HEADER:
            income_rows.append(row)
        elif labels == EXPENSE_HEADER:
            expense_rows.append(row)
    if len(income_rows) != 1 or len(expense_rows) != 1 or income_rows[0] >= expense_rows[0]:
        return {"layout": "nonstandard", "flags": ["LAYOUT_NOT_STANDARD"], "income_total": None,
                "expense_total": None, "net": None, "income_rows": None, "expense_rows": None}

    income_header, expense_header = income_rows[0], expense_rows[0]
    formulas = _sum_formulas(ws_f)
    # The expense block ends just above its own total, which sits below the rows it sums.
    expense_totals = [item for item in formulas
                      if item[2] in (expense_header, expense_header + 1) and item[0] > expense_header]
    stop = expense_totals[0][0] - 1 if expense_totals else last_row
    blocks = {"income": (income_header + 1, expense_header - 1), "expense": (expense_header + 1, stop)}

    flags: set = set()
    totals, counts = {}, {}
    for name, (first, last) in blocks.items():
        block_flags: set = set()
        row_total, rows, first_row, last_data = _sum_block(first, last, ws_f, ws_v, block_flags)
        # Google's own total is the figure that counts; the row sum only stands in when it is missing.
        sheet_total = _check_total(formulas, first, last, ws_v, row_total, rows, first_row, last_data, block_flags)
        flags |= block_flags
        if block_flags & BLOCKING_FLAGS:
            totals[name] = None
        else:
            totals[name] = sheet_total if sheet_total is not None else row_total
        counts[name] = rows

    income, expense = totals["income"], totals["expense"]
    return {
        "layout": "rev",
        "flags": sorted(flags),
        "income_total": income,
        "expense_total": expense,
        "net": income - expense if income is not None and expense is not None else None,
        "income_rows": counts["income"],
        "expense_rows": counts["expense"],
    }


def parse_workbook(data: bytes) -> list[dict]:
    formulas = openpyxl.load_workbook(io.BytesIO(data))
    values = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    trips = []
    for name in values.sheetnames:
        title = name.strip()
        key = COPY_SUFFIX.sub("", title)
        if not TRIP_NAME.match(key):
            continue
        trip = parse_trip_sheet(formulas[name], values[name])
        trips.append({"sheet": title, "key": key, "copy_name": key != title, **trip})
    return trips


def _download(url: str, *, timeout: float, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise SourceError("SOURCE_NOT_FOUND") from None
        if error.code in (401, 403):
            raise SourceError("SOURCE_ACCESS_DENIED") from None
        raise SourceError("SOURCE_UNREACHABLE") from None
    except Exception:
        raise SourceError("SOURCE_UNREACHABLE") from None
    if content_type == "text/html":
        raise SourceError("SOURCE_WRONG_TYPE")
    if len(data) > max_bytes:
        raise SourceError("SOURCE_TOO_LARGE")
    if not data:
        raise SourceError("SOURCE_UNREACHABLE")
    return data


def load_snapshot(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SnapshotError("SNAPSHOT_UNREADABLE") from error
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise SnapshotError("SNAPSHOT_SCHEMA_MISMATCH")
    return data


def _retained(previous: dict, *, code: str, checked_at: str) -> dict:
    """A failed read keeps the last good trips and says so. It never empties them."""
    return {**previous, "status": "error", "error_code": code, "checked_at": checked_at,
            "stale": True, "unchanged": False, "trips": previous.get("trips", []),
            "last_ok_at": previous.get("last_ok_at")}


def _sync_source(role: str, previous: dict, now: str, fetcher) -> dict:
    try:
        data = fetcher(EXPORT_URL.format(sheet_id=SPREADSHEET_IDS[role]))
    except SourceError as error:
        return _retained(previous, code=error.code, checked_at=now)
    digest = hashlib.sha256(data).hexdigest()
    if previous.get("status") == "ok" and previous.get("content_sha256") == digest:
        return {**previous, "checked_at": now, "last_ok_at": now, "unchanged": True}
    try:
        trips = parse_workbook(data)
    except Exception:
        return _retained(previous, code="SOURCE_PARSE_FAILED", checked_at=now)
    if not trips and previous.get("trips"):
        return _retained(previous, code="SOURCE_NO_TRIP_SHEETS", checked_at=now)
    return {"status": "ok", "error_code": None, "stale": False, "checked_at": now, "last_ok_at": now,
            "content_sha256": digest, "unchanged": False, "trips": trips}


def _closure(archive_trips: list[dict], archive_source: dict) -> str:
    if archive_trips:
        return "closed"
    return "unknown" if archive_source.get("last_ok_at") is None else "open"


def build_trip_view(sources: dict) -> list[dict]:
    keys = sorted({trip["key"] for source in sources.values() for trip in source.get("trips", [])})
    view = []
    for key in keys:
        main = [t for t in sources["main"].get("trips", []) if t["key"] == key]
        archive = [t for t in sources["archive"].get("trips", []) if t["key"] == key]
        flags: set = set()
        if len(main) > 1 or len(archive) > 1:
            flags.add("DUPLICATE_IN_SOURCE")
        if any(t["copy_name"] for t in archive):
            flags.add("COPY_NAME")
        if main and archive:
            flags.add("DUPLICATE_IN_BOTH")
        if archive and not main:
            flags.add("ARCHIVE_ONLY")
        source_name, canonical = ("main", main[0]) if main else ("archive", archive[0])
        if sources[source_name].get("stale"):
            flags.add("SOURCE_STALE")
        usable = canonical["layout"] == "rev" and "DUPLICATE_IN_SOURCE" not in flags
        view.append({
            "key": key,
            "closure": _closure(archive, sources["archive"]),
            "canonical_source": source_name,
            "sheets": {"main": main[0]["sheet"] if main else None,
                       "archive": archive[0]["sheet"] if archive else None},
            "income_total": canonical["income_total"] if usable else None,
            "expense_total": canonical["expense_total"] if usable else None,
            "net": canonical["net"] if usable else None,
            "review": sorted(flags | set(canonical["flags"])),
        })
    return view


def _write_atomic(path: Path, snapshot: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def sync(snapshot_path: Path, *, timeout: float = DEFAULT_TIMEOUT, max_bytes: int = DEFAULT_MAX_BYTES,
         fetcher=None, now: dt.datetime | None = None) -> dict:
    """One read of both workbooks. Writes only the snapshot file, never Google."""
    previous = load_snapshot(snapshot_path)
    if fetcher is None:
        def fetcher(url):
            return _download(url, timeout=timeout, max_bytes=max_bytes)
    checked_at = (now or dt.datetime.now(KST)).isoformat()
    sources = {}
    for role in SPREADSHEET_IDS:
        sources[role] = _sync_source(role, previous.get("sources", {}).get(role, {}), checked_at, fetcher)
    snapshot = {"schema": SCHEMA, "synced_at": checked_at, "sources": sources,
                "trips": build_trip_view(sources)}
    _write_atomic(snapshot_path, snapshot)
    return snapshot
