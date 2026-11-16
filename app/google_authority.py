"""Read-only sync of the Google trip ledgers into a standalone snapshot.

Reads the active main workbook and the archive workbook as xlsx exports, finds the
trip tabs in the 매출자료 양식_rev layout and keeps only totals, check results and
status codes. Nothing is written to Google, nothing touches the operating board
database, and row contents (names, reservation numbers, payees) are not kept.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import openpyxl

SPREADSHEET_IDS = {
    "main": "1fhqNkhfiWTYr_U8QnFxlunijAIFPH3r8rPRR0DTPlKU",
    "archive": "1scMHyDERFWZp82gwZMxnz9Hzgy0CJm3TdvqD1sw_9C8",
    "andre_main": "1giIJZDYIL-RBwVy_-yDhElAmsV0pUgkCxBcEa3Wr87Y",
}
SOURCE_REGISTRY = {
    "main": {"owner_id": "aslan", "role": "main", "owner_name": "아슬란", "owner_alias": "아슬란"},
    "archive": {"owner_id": "aslan", "role": "archive", "owner_name": "아슬란", "owner_alias": "아슬란"},
    "andre_main": {"owner_id": "andre", "role": "main", "owner_name": "김동언", "owner_alias": "안드레"},
}


def source_owner_id(source: str) -> str:
    return SOURCE_REGISTRY[source]["owner_id"]


def source_role(source: str) -> str:
    return SOURCE_REGISTRY[source]["role"]


def source_label(source: str) -> str:
    metadata = SOURCE_REGISTRY[source]
    role = "메인 장부" if metadata["role"] == "main" else "보관 장부"
    return f"{metadata['owner_alias']} {role}"


def trip_sheet(key: str) -> str:
    if key.startswith("andre::"):
        match = re.fullmatch(r"andre::(\d{4})::(.+)", key)
        if match is None:
            raise ValueError("INVALID_QUALIFIED_TRIP_KEY")
        return match[2]
    return key


def trip_owner_id(key: str) -> str:
    if key.startswith("andre::"):
        trip_sheet(key)  # Reject malformed qualified keys instead of treating them as legacy Aslan keys.
        return "andre"
    return "aslan"
EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
SCHEMA = "google-authority-readonly-v2"
ROWS_SCHEMA = "google-authority-rows-private-v1"
KST = dt.timezone(dt.timedelta(hours=9))
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_BYTES = 64 * 1024 * 1024

#: 파서 세대. 이름 인덱스를 만들기 전 세대(`quarter-expense-v1`)는 같은 workbook
#: 해시여도 다시 읽어야 이름 인덱스가 생긴다.
PARSER_VERSION = 'quarter-expense-v5'

INCOME_HEADER = ("거래일자", "이름", "닉네임", "예약금", "잔금", "추가금", "금액(원)")
EXPENSE_HEADER = ("거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)")
TRIP_NAME = re.compile(r"^\d{4}_\S")
QUARTER_NAME = re.compile(r"^([1-4])분기_기타비용(?:\s*의 사본)?$")
COPY_SUFFIX = re.compile(r"\s*의 사본$")
SUM_OF_AMOUNTS = re.compile(r"^=\s*SUM\(\s*H(\d+)(?:\s*:\s*H(\d+))?\s*\)$", re.IGNORECASE)
# A block with any of these cannot be summed safely. Its total is None, never 0.
BLOCKING_FLAGS = {"FORMULA_ERROR", "AMOUNT_INVALID", "AMOUNT_MISSING", "AMOUNT_NOT_CACHED",
                  "INCOME_COMPONENT_AMOUNT_MISSING", "INCOME_COMPONENT_TOTAL_MISMATCH",
                  "INCOME_COMPONENT_INVALID"}
# A block with any of these has a total Google shows but COST cannot verify.
TOTAL_FLAGS = {"TOTAL_MISMATCH", "TOTAL_RANGE_MISMATCH", "TOTAL_FORMULA_UNCLEAR", "TOTAL_NOT_CACHED"}


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


def _candidate_key(title: str) -> str:
    """Only for flagging a possible duplicate. Never used to merge two tabs."""
    return COPY_SUFFIX.sub("", title)


def _cell_value(value):
    if _is_date(value):
        return value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
    return value


def _sum_block(first: int, last: int, ws_f, ws_v, flags: set,
               out_rows: list | None = None, out_names: list | None = None) -> tuple[int, int, int | None, int | None]:
    total, rows, first_row, last_row = 0, 0, None, None
    for row in range(first, last + 1):
        value = ws_v.cell(row=row, column=8).value
        if out_names is not None:
            # A blank transaction date does not make a deposit/balance vanish.
            # Validate the source's arithmetic, without inventing received cash
            # or replacing Google's own amount/formula with our calculation.
            components = [ws_v.cell(row=row, column=col).value for col in (5, 6, 7)]
            populated = [v for v in components if v is not None and v != '']
            if populated:
                if any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) or not float(v).is_integer() for v in populated):
                    flags.add('INCOME_COMPONENT_INVALID')
                elif value is None or value == '':
                    flags.add('INCOME_COMPONENT_AMOUNT_MISSING')
                elif (isinstance(value, (int, float)) and not isinstance(value, bool)
                      and math.isfinite(value) and value != sum(populated)):
                    flags.add('INCOME_COMPONENT_TOTAL_MISMATCH')
            # 이름 인덱스는 금액 집계와 무관하다. 금액이 없는 이름 행도 여기만 남는다.
            _collect_name_row(ws_f, ws_v, row, value, out_names)
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
            if out_rows is not None:
                cells = {column: _cell_value(ws_v.cell(row=row, column=index).value)
                         for index, column in enumerate("BCDEFG", start=2)}
                out_rows.append({"row": row, "cells": cells, "amount": int(value)})
    return total, rows, first_row, last_row


def _collect_name_row(ws_f, ws_v, row: int, value, out_names: list) -> None:
    """이름 또는 닉네임이 있는 수입 행. 회계 집계에는 들어가지 않는다."""
    name = _text(ws_v.cell(row=row, column=3).value)
    nickname = _text(ws_v.cell(row=row, column=4).value)
    if not name and not nickname:
        return
    if value is None or value == "":
        formula = ws_f.cell(row=row, column=8).value
        state = "not_cached" if isinstance(formula, str) and formula.startswith("=") else "blank"
        amount = None
    elif isinstance(value, str) and value.startswith("#"):
        state = "formula_error"
        amount = None
    elif isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value).is_integer():
        state = "invalid"
        amount = None
    else:
        state = "amounted"
        amount = int(value)
    cells = {column: _cell_value(ws_v.cell(row=row, column=index).value)
             for index, column in enumerate("BCDEFG", start=2)}
    out_names.append({"row": row, "cells": cells, "name": name, "nickname": nickname,
                      "amount": amount, "amount_state": state})


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
    """Find the sheet's own total for a block and report how it compares with the rows."""
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


def _block(sheet_total: int | None, row_sum: int | None, block_flags: set) -> dict:
    if block_flags & BLOCKING_FLAGS:
        return {"sheet_total": None, "row_sum": None, "total": None, "verified": False}
    verified = sheet_total is not None and sheet_total == row_sum and not (block_flags & TOTAL_FLAGS)
    return {"sheet_total": sheet_total, "row_sum": row_sum, "total": sheet_total, "verified": verified}


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
        from .google_expense_rows import read
        original = read(ws_f, ws_v)
        return {"layout": "nonstandard", "flags": ["LAYOUT_NOT_STANDARD"], "income": None, "expense": None,
                "net": None, "verified": False, "income_rows": None, "expense_rows": None,
                "expense_source_status": original['status'],
                "rows": {"income": [], "expense": original['rows']},
                "name_index": {"income": [], "available": False}}

    income_header, expense_header = income_rows[0], expense_rows[0]
    formulas = _sum_formulas(ws_f)
    # The expense block ends just above its own total, which sits below the rows it sums.
    expense_totals = [item for item in formulas
                      if item[2] in (expense_header, expense_header + 1) and item[0] > expense_header]
    stop = expense_totals[0][0] - 1 if expense_totals else last_row
    blocks = {"income": (income_header + 1, expense_header - 1), "expense": (expense_header + 1, stop)}

    flags: set = set()
    result, counts, entries = {}, {}, {}
    name_rows: list = []
    for name, (first, last) in blocks.items():
        block_flags: set = set()
        entries[name] = []
        row_sum, rows, first_row, last_data = _sum_block(first, last, ws_f, ws_v, block_flags, entries[name],
                                                        name_rows if name == "income" else None)
        sheet_total = _check_total(formulas, first, last, ws_v, row_sum, rows, first_row, last_data, block_flags)
        flags |= block_flags
        result[name] = _block(sheet_total, None if block_flags & BLOCKING_FLAGS else row_sum, block_flags)
        counts[name] = rows

    income, expense = result["income"], result["expense"]
    net = income["total"] - expense["total"] if income["total"] is not None and expense["total"] is not None else None
    return {
        "layout": "rev",
        "flags": sorted(flags),
        "income": income,
        "expense": expense,
        "net": net,
        "verified": income["verified"] and expense["verified"],
        "income_rows": counts["income"],
        "expense_rows": counts["expense"],
        "rows": entries,
        # 이름 인덱스는 비공개 자료에만 둔다. 공개 스냅샷에는 이름이 남지 않는다.
        "name_index": {"income": name_rows, "available": True},
    }


TRIP_HEADER_DATES_FIRST = re.compile(r"(?:확인자료|수기장부형 자료)_(\d{4})_(\d{4})_(.+?)\s*$")
TRIP_HEADER_DATES_LAST = re.compile(r"(?:확인자료|수기장부형 자료)_(.+?)_(\d{4})_(\d{4})\s*$")


#: Trips without a year in their title are in this year. Tabs after the December tabs of the main workbook are next year's.
BASE_YEAR = 2026
ITEM_PERIOD = re.compile(r"(\d{4})_(\d{4})")


def _item_end(ws_v, starts: dt.date):
    """Latest end of a 기간 range in the expense rows that starts on or after the trip start, or None."""
    last_row = ws_v.max_row or 0
    header = next((row for row in range(1, last_row + 1)
                   if tuple(_text(ws_v.cell(row=row, column=c).value) for c in range(2, 9)) == EXPENSE_HEADER), None)
    if header is None:
        return None
    ends = []
    for row in range(header + 1, last_row + 1):
        match = ITEM_PERIOD.fullmatch(_text(ws_v.cell(row=row, column=5).value))
        if not match:
            continue
        try:
            first = dt.date(starts.year, int(match[1][:2]), int(match[1][2:]))
            last = dt.date(starts.year, int(match[2][:2]), int(match[2][2:]))
        except ValueError:
            continue
        if starts <= first <= last:
            ends.append(last)
    return max(ends, default=None)


def parse_trip_period(ws_v, sheet: str, year_offset: int = 0) -> dict:
    """Year, start and end of a trip tab.

    The start is the tab name's MMDD. The year is the title's year, else BASE_YEAR, plus year_offset. The end
    comes from the top title, else from the expense rows' 기간 ranges. A title whose dates disagree with the
    tab name is held. An open end is closed later from the next trip.
    """
    title = ""
    for row in range(1, 5):
        for column in range(1, 13):
            text = _text(ws_v.cell(row=row, column=column).value)
            if "확인자료" in text or "수기장부형 자료" in text:
                title = text
                break
        if title:
            break
    flags = []
    year_text = re.search(r"(20\d{2})년", title)
    year = int(year_text[1]) if year_text else BASE_YEAR
    if year_offset and year == BASE_YEAR:
        year += year_offset
    first = TRIP_HEADER_DATES_FIRST.search(title)
    last = TRIP_HEADER_DATES_LAST.search(title)
    if first:
        header_start, header_end, destination = first[1], first[2], first[3]
    elif last:
        header_start, header_end, destination = last[2], last[3], last[1]
    else:
        header_start = header_end = destination = None
    start = re.match(r"(\d{4})_", sheet)
    period = {"year": year, "starts_on": None, "ends_on": None,
              "destination": destination or "", "flags": flags}
    if not start:
        flags.append("PERIOD_START_MISSING")
        return period
    if header_start is not None and header_start != start[1]:
        flags.append("PERIOD_START_MISMATCH")
        return period
    try:
        starts = dt.date(year, int(start[1][:2]), int(start[1][2:]))
        ends = None
        if header_end is not None:
            ends = dt.date(year, int(header_end[:2]), int(header_end[2:]))
    except ValueError:
        flags.append("PERIOD_DATE_INVALID")
        return period
    if ends is not None and ends < starts:
        flags.append("PERIOD_ORDER")
        return period
    if ends is None:
        ends = _item_end(ws_v, starts)
        flags.append("PERIOD_END_FROM_ITEMS" if ends else "PERIOD_END_MISSING")
    period["starts_on"] = starts.isoformat()
    period["ends_on"] = ends.isoformat() if ends else None
    return period


def parse_workbook(data: bytes, *, rollover: bool = False) -> list[dict]:
    """With rollover, the tabs that follow the December tabs in the workbook are next year's."""
    formulas = openpyxl.load_workbook(io.BytesIO(data))
    values = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    trips = []
    after_december = False
    for name in values.sheetnames:
        title = name.strip()
        quarter = QUARTER_NAME.fullmatch(title)
        if not TRIP_NAME.match(title) and not quarter:
            continue
        trip = (parse_quarter_sheet(formulas[name], values[name], int(quarter[1]))
                if quarter else parse_trip_sheet(formulas[name], values[name]))
        # A quarter tab kept only as a copy is the quarter's tab, so it groups under the plain title.
        sheet = COPY_SUFFIX.sub("", title) if quarter else title
        if not quarter:
            month = int(title[:2])
            offset = 1 if rollover and after_december and month < 12 else 0
            trip["period"] = parse_trip_period(values[name], title, offset)
            after_december = after_december or (rollover and month == 12)
        trips.append({"sheet": sheet, "copy_name": bool(COPY_SUFFIX.search(title)), **trip})
    return trips


def parse_quarter_sheet(ws_f, ws_v, quarter: int) -> dict:
    """분기 지출 전용 탭을 여행이나 수입 탭으로 추정하지 않는다."""
    headers = [r for r in range(1, (ws_v.max_row or 0) + 1)
               if tuple(_text(ws_v.cell(r, c).value) for c in range(2, 9)) == EXPENSE_HEADER]
    year_match = re.search(r'\b(20\d{2})년', _text(ws_v.cell(2, 3).value))
    base = {'kind': 'quarter', 'quarter': quarter,
            'ledger_year': int(year_match[1]) if year_match else None}
    if len(headers) != 1:
        from .google_expense_rows import read
        original = read(ws_f, ws_v)
        return {**base, 'layout': 'nonstandard', 'flags': ['LAYOUT_NOT_STANDARD'],
                'income': None, 'expense': None, 'net': None, 'verified': False,
                'expense_source_status': original['status'],
                'rows': {'income': [], 'expense': original['rows']},
                'name_index': {'income': [], 'available': False}}
    first = headers[0] + 1
    formulas = _sum_formulas(ws_f)
    totals = [f for f in formulas if f[2] in (first - 1, first) and f[0] >= first]
    last = totals[0][0] - 1 if len(totals) == 1 else ws_v.max_row
    flags, entries = set(), []
    computed, count, start, end = _sum_block(first, last, ws_f, ws_v, flags, entries)
    total = _check_total(formulas, first, last, ws_v, computed, count, start, end, flags)
    expense = _block(total, None if flags & BLOCKING_FLAGS else computed, flags)
    # No income block exists. The kind marker hides income/net in presentation.
    return {**base, 'layout': 'rev', 'flags': sorted(flags),
            'income': {'sheet_total': 0, 'row_sum': 0, 'total': 0, 'verified': True},
            'expense': expense, 'net': None, 'verified': expense['verified'],
            'income_rows': 0, 'expense_rows': count, 'rows': {'income': [], 'expense': entries},
            'name_index': {'income': [], 'available': False}}


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


def _row_key(sheet: str, block: str, row: dict) -> tuple:
    return (sheet, block, row["row"])


def _row_changes(previous: dict, current: dict) -> dict:
    """Counts only. Compares rows by sheet, block and row position."""
    old = {_row_key(s, b, r): r for s, blocks in previous.items() for b, rows in blocks.items() for r in rows}
    new = {_row_key(s, b, r): r for s, blocks in current.items() for b, rows in blocks.items() for r in rows}
    return {"added": len(new.keys() - old.keys()), "removed": len(old.keys() - new.keys()),
            "changed": sum(1 for k in new.keys() & old.keys() if new[k] != old[k])}


def _public_trips(trips: list[dict]) -> list[dict]:
    """공개 스냅샷에는 행 내용과 이름 인덱스를 남기지 않는다."""
    return [{k: v for k, v in trip.items() if k not in ("rows", "name_index")} for trip in trips]


def _sync_source(role: str, previous: dict, previous_rows: dict, now: str, fetcher,
                 previous_index: bool = True) -> tuple[dict, dict | None]:
    """Returns the public source record and the private rows to store, or None to keep the old rows."""
    try:
        data = fetcher(EXPORT_URL.format(sheet_id=SPREADSHEET_IDS[role]))
    except SourceError as error:
        return _retained(previous, code=error.code, checked_at=now), None
    digest = hashlib.sha256(data).hexdigest()
    if (previous.get("status") == "ok" and previous.get("content_sha256") == digest
            and previous.get('parser_version') == PARSER_VERSION and previous_index):
        # 같은 workbook라도 이름 인덱스가 없는 세대면 다시 읽어야 인덱스가 생긴다.
        return {**previous, "checked_at": now, "last_ok_at": now, "unchanged": True,
                "row_changes": {"added": 0, "removed": 0, "changed": 0}}, None
    try:
        trips = parse_workbook(data, rollover=role in ("main", "andre_main"))
    except Exception:
        return _retained(previous, code="SOURCE_PARSE_FAILED", checked_at=now), None
    if not trips and previous.get("trips"):
        return _retained(previous, code="SOURCE_NO_TRIP_SHEETS", checked_at=now), None
    current_rows = {t["sheet"]: t.get("rows", {}) for t in trips}
    # 이름 인덱스는 금액 행과 별개로 저장한다. 금액이 없는 이름 행도 여기만 남는다.
    current_names = {t["sheet"]: t.get("name_index", {"income": [], "available": False}) for t in trips}
    record = {"status": "ok", "error_code": None, "stale": False, "checked_at": now, "last_ok_at": now,
              'parser_version': PARSER_VERSION,
              "content_sha256": digest, "unchanged": False, "trips": _public_trips(trips),
              "row_changes": _row_changes(previous_rows, current_rows)}
    return record, {"content_sha256": digest, "trips": current_rows, "income_names": current_names}


def _copy(trip: dict | None) -> dict | None:
    if trip is None:
        return None
    return {"sheet": trip["sheet"], "layout": trip["layout"], "income": trip["income"],
            "expense": trip["expense"], "flags": trip["flags"],
            **{k: trip[k] for k in ('kind', 'quarter', 'ledger_year') if k in trip}}


def build_trip_view(sources: dict) -> list[dict]:
    """Groups tabs by exact title. Only an exact title match is treated as the same trip."""
    view = []
    groups = {}
    for role in SPREADSHEET_IDS:
        owner = source_owner_id(role)
        for trip in sources.get(role, {}).get("trips", []):
            raw = trip["sheet"]
            year = trip.get('ledger_year') or (trip.get('period') or {}).get('year')
            qualified_year = f"{int(year):04d}" if year else "0000"
            key = raw if owner == "aslan" else f"andre::{qualified_year}::{raw}"
            group_key = (owner, year, raw) if owner == "andre" else (owner, None, raw)
            groups.setdefault(group_key, []).append((role, trip, key, year))
    for (owner, year, title), members in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1] or 0, item[0][2])):
        main = [t for role, t, _, _ in members if role in ("main", "andre_main")]
        archive = [t for role, t, _, _ in members if role == "archive"]
        main_role = "andre_main" if owner == "andre" else "main"
        archive_role = "archive"
        main_source = sources.get(main_role, {})
        archive_source = sources.get(archive_role, {}) if owner == "aslan" else {}
        archive_ok = archive_source.get("status") == "ok"
        other = [t for role in ("main", "archive", "andre_main")
                 if source_owner_id(role) == owner and role != (main_role if main else archive_role)
                 for t in sources.get(role, {}).get("trips", [])]
        flags: set = set()
        years = {member_year for _, _, _, member_year in members if member_year is not None}
        if owner == "aslan" and len(years) > 1:
            flags.add("PERIOD_YEAR_CONFLICT")
        if owner == "andre" and any(member_year is None for _, _, _, member_year in members):
            flags.add("PERIOD_YEAR_MISSING")
        if len(main) > 1 or len(archive) > 1:
            flags.add("DUPLICATE_IN_SOURCE")
        if main and archive:
            flags.add("DUPLICATE_IN_BOTH")
        if archive and not main:
            flags.add("ARCHIVE_ONLY")
        if archive and any(t["copy_name"] for t in archive):
            flags.add("COPY_NAME")
        if any(t["sheet"] != title and _candidate_key(t["sheet"]) == _candidate_key(title) for t in other):
            flags.add("POSSIBLE_DUPLICATE")
        canonical_source, canonical = (main_role, main[0]) if main else (archive_role, archive[0])
        if sources[canonical_source].get("stale"):
            flags.add("SOURCE_STALE")
        usable = (canonical["layout"] == "rev"
                  and not flags & {"DUPLICATE_IN_SOURCE", "POSSIBLE_DUPLICATE", "PERIOD_YEAR_CONFLICT", "PERIOD_YEAR_MISSING"})
        closure = "closed" if archive else ("unknown" if owner == "andre" or archive_source.get("last_ok_at") is None else "open")
        verified = usable and canonical["verified"] and not flags & {"SOURCE_STALE"}
        reported = {
            "income_total": canonical["income"]["total"] if usable else None,
            "expense_total": canonical["expense"]["total"] if usable else None,
            "net": canonical["net"] if usable else None,
        }
        # Only verified figures count as totals. What Google displays but COST cannot verify stays in reported.
        figures = reported if verified else dict.fromkeys(reported)
        view.append({
            "key": title if owner == "aslan" else members[0][2],
            "owner_id": owner,
            "owner_name": "김동언" if owner == "andre" else "아슬란",
            "owner_alias": "안드레" if owner == "andre" else "아슬란",
            "sheet": title,
            **{k: canonical[k] for k in ('kind', 'quarter', 'ledger_year', 'period') if k in canonical},
            "closure": closure,
            "closure_current": archive_ok and closure != "unknown",
            "canonical_source": canonical_source,
            **figures,
            "reported": reported,
            "verified": verified,
            "copies": ({main_role: _copy(main[0] if main else None)} if owner == "andre" else
                       {"main": _copy(main[0] if main else None), "archive": _copy(archive[0] if archive else None)}),
            "review": sorted(flags | set(canonical["flags"])),
        })
    for owner in ("aslan", "andre"):
        owned = [t for t in view if t["owner_id"] == owner]
        _close_open_ends(owned)
    return view


def _close_open_ends(view: list[dict]) -> None:
    """A trip with no end date ends the day before the next trip starts."""
    dated = sorted((t for t in view if (t.get("period") or {}).get("starts_on")),
                   key=lambda t: t["period"]["starts_on"])
    for index, trip in enumerate(dated):
        period = trip["period"]
        if period.get("ends_on"):
            continue
        from .reconciliation import open_trip_end
        following = next((t["period"]["starts_on"] for t in dated[index + 1:]
                          if t["period"]["starts_on"] > period["starts_on"]
                          and (t["period"].get("year") or int(t["period"]["starts_on"][:4]))
                          == (period.get("year") or int(period["starts_on"][:4]))), None)
        ends = open_trip_end(period["starts_on"], following)
        if ends is None:
            continue
        period["ends_on"] = ends
        period["flags"] = [f for f in period["flags"] if f != "PERIOD_END_MISSING"] + ["PERIOD_END_FROM_NEXT_TRIP"]


def _write_atomic(path: Path, snapshot: dict) -> None:
    """Writes a temporary file and swaps it in. On Windows a reader holding the old file can block the swap briefly."""
    import time
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02 * (attempt + 1))


def _rows_file(rows_path: Path, generation: str) -> Path:
    return rows_path.with_name(f"{rows_path.stem}.{generation}{rows_path.suffix}")


def load_rows(rows_path: Path, generation: str | None) -> dict:
    """Rows of the generation the current snapshot names. Never a newer or older file."""
    if not generation:
        return {}
    try:
        data = json.loads(_rows_file(rows_path, generation).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SnapshotError("ROWS_MISSING") from error
    except (OSError, ValueError) as error:
        raise SnapshotError("ROWS_UNREADABLE") from error
    if not isinstance(data, dict) or data.get("schema") != ROWS_SCHEMA:
        raise SnapshotError("ROWS_SCHEMA_MISMATCH")
    if data.get("generation") != generation:
        raise SnapshotError("ROWS_GENERATION_MISMATCH")
    return data.get("sources", {})


READ_ATTEMPTS = 4
READ_RETRY_SECONDS = 0.05


def load_consistent(snapshot_path: Path, rows_path: Path) -> tuple[dict, dict]:
    """Reads the public snapshot and the private rows together and refuses a pair from different runs.

    The rows must be the generation the snapshot names, and for every source the content
    fingerprint must match. A sync may replace the pair between the two reads; that is retried a few
    times, so a reader sees one whole run or a clear error, never a mix.
    """
    import time
    last = None
    for attempt in range(READ_ATTEMPTS):
        try:
            snapshot = load_snapshot(snapshot_path)
            if not snapshot:
                raise SnapshotError("SNAPSHOT_MISSING")
            rows = load_rows(rows_path, snapshot.get("rows_generation"))
            for role, record in snapshot.get("sources", {}).items():
                if record.get("content_sha256") != rows.get(role, {}).get("content_sha256"):
                    raise SnapshotError("GENERATION_MISMATCH")
            return snapshot, rows
        except SnapshotError as error:
            last = error
            transient = ("ROWS_MISSING", "GENERATION_MISMATCH", "SNAPSHOT_UNREADABLE", "ROWS_UNREADABLE")
            if error.code not in transient or attempt + 1 == READ_ATTEMPTS:
                break
            time.sleep(READ_RETRY_SECONDS)
    raise last


def _remove_other_generations(rows_path: Path, *, keep: set) -> None:
    """Removes orphaned or two-runs-old rows files, which a crash between the two writes can leave behind."""
    keep_names = {_rows_file(rows_path, g).name for g in keep if g}
    generated = re.compile(re.escape(rows_path.stem) + r'\.([0-9a-f]{32})' + re.escape(rows_path.suffix))
    for candidate in rows_path.parent.iterdir():
        match = generated.fullmatch(candidate.name)
        if not match or candidate.name in keep_names or candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            metadata = json.loads(candidate.read_text(encoding='utf-8'))
            if (isinstance(metadata, dict) and metadata.get('schema') == ROWS_SCHEMA
                    and metadata.get('generation') == match.group(1)):
                candidate.unlink()
        except (OSError, ValueError):
            pass  # Unknown or damaged files are recovery evidence, not disposable generations.


def sync(snapshot_path: Path, rows_path: Path, *, timeout: float = DEFAULT_TIMEOUT,
         max_bytes: int = DEFAULT_MAX_BYTES, fetcher=None, now: dt.datetime | None = None) -> dict:
    """One read of both workbooks. Writes the public snapshot and a private rows file, never Google.

    Rows are written to a new generation file first, then the snapshot names that generation in
    one atomic replace. A crash before the replace leaves the old snapshot and its old rows
    intact, so the two never describe different generations.
    """
    previous = load_snapshot(snapshot_path)
    previous_rows = load_rows(rows_path, previous.get("rows_generation"))
    if fetcher is None:
        def fetcher(url):
            return _download(url, timeout=timeout, max_bytes=max_bytes)
    checked_at = (now or dt.datetime.now(KST)).isoformat()
    sources, private = {}, dict(previous_rows)
    for role in SPREADSHEET_IDS:
        previous_role_rows = previous_rows.get(role, {})
        has_index = isinstance(previous_role_rows.get("income_names"), dict)
        record, rows = _sync_source(role, previous.get("sources", {}).get(role, {}),
                                    previous_role_rows.get("trips", {}), checked_at, fetcher,
                                    has_index)
        sources[role] = record
        if rows is not None:
            private[role] = rows
    private_unchanged = (private == previous_rows)
    previous_gen = previous.get("rows_generation")
    reuse_gen = private_unchanged and bool(previous_gen)
    if reuse_gen:
        generation = previous_gen
        retained_previous_gen = previous.get("rows_generation_previous")
    else:
        generation = uuid.uuid4().hex
        retained_previous_gen = previous_gen
        _write_atomic(_rows_file(rows_path, generation),
                      {"schema": ROWS_SCHEMA, "generation": generation, "synced_at": checked_at, "sources": private})
    snapshot = {"schema": SCHEMA, "synced_at": checked_at, "sources": sources,
                "trips": build_trip_view(sources), "rows_generation": generation,
                "rows_generation_previous": retained_previous_gen}
    _write_atomic(snapshot_path, snapshot)
    # A reader that loaded the previous snapshot may still open its rows, so the previous generation stays.
    _remove_other_generations(rows_path, keep={generation, retained_previous_gen})
    return snapshot
