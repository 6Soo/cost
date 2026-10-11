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
}
EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
SCHEMA = "google-authority-readonly-v2"
ROWS_SCHEMA = "google-authority-rows-private-v1"
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
               out_rows: list | None = None) -> tuple[int, int, int | None, int | None]:
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
            if out_rows is not None:
                cells = {column: _cell_value(ws_v.cell(row=row, column=index).value)
                         for index, column in enumerate("BCDEFG", start=2)}
                out_rows.append({"row": row, "cells": cells, "amount": int(value)})
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
        return {"layout": "nonstandard", "flags": ["LAYOUT_NOT_STANDARD"], "income": None, "expense": None,
                "net": None, "verified": False, "income_rows": None, "expense_rows": None}

    income_header, expense_header = income_rows[0], expense_rows[0]
    formulas = _sum_formulas(ws_f)
    # The expense block ends just above its own total, which sits below the rows it sums.
    expense_totals = [item for item in formulas
                      if item[2] in (expense_header, expense_header + 1) and item[0] > expense_header]
    stop = expense_totals[0][0] - 1 if expense_totals else last_row
    blocks = {"income": (income_header + 1, expense_header - 1), "expense": (expense_header + 1, stop)}

    flags: set = set()
    result, counts, entries = {}, {}, {}
    for name, (first, last) in blocks.items():
        block_flags: set = set()
        entries[name] = []
        row_sum, rows, first_row, last_data = _sum_block(first, last, ws_f, ws_v, block_flags, entries[name])
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
    }


def parse_workbook(data: bytes) -> list[dict]:
    formulas = openpyxl.load_workbook(io.BytesIO(data))
    values = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    trips = []
    for name in values.sheetnames:
        title = name.strip()
        if not TRIP_NAME.match(title):
            continue
        trip = parse_trip_sheet(formulas[name], values[name])
        trips.append({"sheet": title, "copy_name": bool(COPY_SUFFIX.search(title)), **trip})
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


def _row_key(sheet: str, block: str, row: dict) -> tuple:
    return (sheet, block, row["row"])


def _row_changes(previous: dict, current: dict) -> dict:
    """Counts only. Compares rows by sheet, block and row position."""
    old = {_row_key(s, b, r): r for s, blocks in previous.items() for b, rows in blocks.items() for r in rows}
    new = {_row_key(s, b, r): r for s, blocks in current.items() for b, rows in blocks.items() for r in rows}
    return {"added": len(new.keys() - old.keys()), "removed": len(old.keys() - new.keys()),
            "changed": sum(1 for k in new.keys() & old.keys() if new[k] != old[k])}


def _public_trips(trips: list[dict]) -> list[dict]:
    return [{k: v for k, v in trip.items() if k != "rows"} for trip in trips]


def _sync_source(role: str, previous: dict, previous_rows: dict, now: str, fetcher) -> tuple[dict, dict | None]:
    """Returns the public source record and the private rows to store, or None to keep the old rows."""
    try:
        data = fetcher(EXPORT_URL.format(sheet_id=SPREADSHEET_IDS[role]))
    except SourceError as error:
        return _retained(previous, code=error.code, checked_at=now), None
    digest = hashlib.sha256(data).hexdigest()
    if previous.get("status") == "ok" and previous.get("content_sha256") == digest:
        return {**previous, "checked_at": now, "last_ok_at": now, "unchanged": True,
                "row_changes": {"added": 0, "removed": 0, "changed": 0}}, None
    try:
        trips = parse_workbook(data)
    except Exception:
        return _retained(previous, code="SOURCE_PARSE_FAILED", checked_at=now), None
    if not trips and previous.get("trips"):
        return _retained(previous, code="SOURCE_NO_TRIP_SHEETS", checked_at=now), None
    current_rows = {t["sheet"]: t.get("rows", {}) for t in trips}
    record = {"status": "ok", "error_code": None, "stale": False, "checked_at": now, "last_ok_at": now,
              "content_sha256": digest, "unchanged": False, "trips": _public_trips(trips),
              "row_changes": _row_changes(previous_rows, current_rows)}
    return record, {"content_sha256": digest, "trips": current_rows}


def _copy(trip: dict | None) -> dict | None:
    if trip is None:
        return None
    return {"sheet": trip["sheet"], "layout": trip["layout"], "income": trip["income"],
            "expense": trip["expense"], "flags": trip["flags"]}


def build_trip_view(sources: dict) -> list[dict]:
    """Groups tabs by exact title. Only an exact title match is treated as the same trip."""
    main_trips = sources["main"].get("trips", [])
    archive_trips = sources["archive"].get("trips", [])
    archive_ok = sources["archive"].get("status") == "ok"
    view = []
    for title in sorted({trip["sheet"] for trip in main_trips + archive_trips}):
        main = [t for t in main_trips if t["sheet"] == title]
        archive = [t for t in archive_trips if t["sheet"] == title]
        other = archive_trips if main else main_trips
        flags: set = set()
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
        canonical_source, canonical = ("main", main[0]) if main else ("archive", archive[0])
        if sources[canonical_source].get("stale"):
            flags.add("SOURCE_STALE")
        usable = (canonical["layout"] == "rev"
                  and not flags & {"DUPLICATE_IN_SOURCE", "POSSIBLE_DUPLICATE"})
        closure = "closed" if archive else ("unknown" if sources["archive"].get("last_ok_at") is None else "open")
        verified = usable and canonical["verified"] and not flags & {"SOURCE_STALE"}
        reported = {
            "income_total": canonical["income"]["total"] if usable else None,
            "expense_total": canonical["expense"]["total"] if usable else None,
            "net": canonical["net"] if usable else None,
        }
        # Only verified figures count as totals. What Google displays but COST cannot verify stays in reported.
        figures = reported if verified else dict.fromkeys(reported)
        view.append({
            "key": title,
            "closure": closure,
            "closure_current": archive_ok and closure != "unknown",
            "canonical_source": canonical_source,
            **figures,
            "reported": reported,
            "verified": verified,
            "copies": {"main": _copy(main[0] if main else None), "archive": _copy(archive[0] if archive else None)},
            "review": sorted(flags | set(canonical["flags"])),
        })
    return view


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
        record, rows = _sync_source(role, previous.get("sources", {}).get(role, {}),
                                    previous_rows.get(role, {}).get("trips", {}), checked_at, fetcher)
        sources[role] = record
        if rows is not None:
            private[role] = rows
    generation = uuid.uuid4().hex
    _write_atomic(_rows_file(rows_path, generation),
                  {"schema": ROWS_SCHEMA, "generation": generation, "synced_at": checked_at, "sources": private})
    snapshot = {"schema": SCHEMA, "synced_at": checked_at, "sources": sources,
                "trips": build_trip_view(sources), "rows_generation": generation,
                "rows_generation_previous": previous.get("rows_generation")}
    _write_atomic(snapshot_path, snapshot)
    # A reader that loaded the previous snapshot may still open its rows, so the previous generation stays.
    _remove_other_generations(rows_path, keep={generation, previous.get("rows_generation")})
    return snapshot
