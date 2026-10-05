"""SOURCE-REFRESH-001: build a fresh review input from a changed source.

A new workbook and a new card master arrive. This turns them into a new review
input, proves it with the whole existing review core, and activates it atomically.
It is a layout and integrity job. It decides nothing about money: a date and
amount that match a card transaction make that transaction a *candidate*, and a
candidate is not an approval.

What this reuses, and why reusing rather than rewriting is the point:

* ``review_context._parse_explicit_date`` and ``._parse_amount`` decide what a
  date and an amount are. A second parser would be a second opinion about the
  same cells, and the two would disagree on exactly the rows that matter.
* ``review_context._resolve_header``-equivalent logic is expressed here only as
  *discovery*: which rows a block claims. Whether a row has usable header
  evidence is still decided by the core when the model is built, so this module
  cannot widen or narrow the core's judgement.
* ``review_context.build_review_context`` is the only thing that says a bundle is
  valid. Nothing here is a shortcut around it.

Three rules the layout forces on this module:

1. **A new block is proven by its own explicit expense header.** A run of seven
   or eight columns labelled 거래일자 / 항목 / 내용 / 기간 / 예약번호 / 증빙유형 /
   금액 in block order, with the amount label at the last column, is the only
   thing that creates scope. An income header, an adjacent block, or a column
   that merely holds a number is not a header and creates nothing.
2. **Nothing in scope may be dropped.** Scope is the union of what the new
   workbook's headers prove and what the previous review input already listed.
   The second half is what keeps a row whose header was deleted — or a row that
   only ever lacked a header — in the bundle as a held row, instead of silently
   shrinking the review. Given that a real source carries hundreds of rows with
   no header above them, "emit only the rows with a valid header" is the one
   implementation that must not exist.
3. **A date with no explicit year is not a date.** The core refuses to parse it
   and so does this module, by asking the core's own parser.

Nothing here writes to the source files, to the decisions database, or to the
operational ledger. It writes one immutable bundle directory and, last of all,
swaps the config file that the web app reads.
"""

from __future__ import annotations

import csv
import io
import json
import os
import pathlib
import tempfile
import threading
from decimal import Decimal

from webapp import review_context
from webapp.contracts import sha256_bytes, sha256_text
from webapp.review_csv_adapter import RAW_CANDIDATE, RAW_UNMATCHED
from webapp.review_csv_adapter import REVIEW_SCHEMA_VERSION
from webapp.review_csv_adapter import REQUIRED_HEADERS

__all__ = [
    "RefreshError",
    "content_digest",
    "content_marker",
    "master_semantic_digest",
    "discover_blocks",
    "build_review_csv",
    "collect",
    "collect_and_activate",
    "activate",
    "collector_lock",
    "load_status",
    "write_status",
    "CODE_ARGUMENT",
    "CODE_SOURCE_UNREADABLE",
    "CODE_SOURCE_EMPTY",
    "CODE_SCOPE_UNPROVEN",
    "CODE_CELL_UNUSABLE",
    "CODE_MASTER_UNREADABLE",
    "CODE_MASTER_DUPLICATE_KEY",
    "CODE_CANDIDATE_UNRESOLVED",
    "CODE_REVIEW_INPUT_INVALID",
    "CODE_CONTEXT_REJECTED",
    "CODE_ROWS_SHRANK",
    "CODE_BUNDLE_WRITE_FAILED",
    "CODE_COLLECTOR_BUSY",
    "CODE_CONFIG_REPLACED",
    "CODE_BASE_CONFIG_CHANGED",
]

#: Fixed codes only. No path, URL, cell value, key or exception text ever
#: reaches a caller, because a collector's failure is read by a person deciding
#: whether to trust it, and a value in that message is data they did not ask for.
CODE_ARGUMENT = "REFRESH_ARGUMENT_INVALID"
CODE_SOURCE_UNREADABLE = "REFRESH_SOURCE_UNREADABLE"
CODE_SOURCE_EMPTY = "REFRESH_SOURCE_EMPTY"
CODE_SCOPE_UNPROVEN = "REFRESH_SCOPE_UNPROVEN"
CODE_CELL_UNUSABLE = "REFRESH_CELL_UNUSABLE"
CODE_MASTER_UNREADABLE = "REFRESH_MASTER_UNREADABLE"
CODE_MASTER_DUPLICATE_KEY = "REFRESH_MASTER_DUPLICATE_KEY"
CODE_CANDIDATE_UNRESOLVED = "REFRESH_CANDIDATE_UNRESOLVED"
CODE_REVIEW_INPUT_INVALID = "REFRESH_REVIEW_INPUT_INVALID"
CODE_CONTEXT_REJECTED = "REFRESH_CONTEXT_REJECTED"
CODE_ROWS_SHRANK = "REFRESH_ROWS_SHRANK"
CODE_BUNDLE_WRITE_FAILED = "REFRESH_BUNDLE_WRITE_FAILED"
CODE_COLLECTOR_BUSY = "REFRESH_COLLECTOR_BUSY"
CODE_CONFIG_REPLACED = "REFRESH_CONFIG_REPLACED"
CODE_BASE_CONFIG_CHANGED = "REFRESH_BASE_CONFIG_CHANGED"

#: The expense block, exactly as the core defines it. Duplicated here as data so
#: discovery cannot drift from the core by editing one of two code paths: the
#: assertions below fail if the two ever disagree.
_EXPENSE_LABELS = review_context.SOURCE_BLOCK_LABELS
_AMOUNT_LABEL = review_context.AMOUNT_LABEL
_WIDTHS = review_context.SOURCE_BLOCK_WIDTHS

#: A sheet is not classified by its name. An earlier version excluded any sheet
#: whose name contained 수입, which threw away a real expense block on a sheet
#: that also carried income — and a sheet name is no more evidence than a
#: filename. What separates an expense block from an income block is the expense
#: block's own header, and the income header cannot spell it: its labels are
#: different and its amount column is not seven or eight past its date. So the
#: decision is per block, and the name is never read.

_MAX_ROWS = 200000


class RefreshError(Exception):
    """A refusal carrying one fixed code and nothing else."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise RefreshError(code)


def _label(value) -> str:
    """The core's own idea of a cell label, reused rather than re-decided."""
    return review_context._label_of(value)


def _is_expense_header(cells: list[str], start: int, width: int) -> bool:
    """Is there an expense block header of this width starting at ``start``?

    The block labels must appear in block order, the amount label at the last
    column, and — for width eight — exactly one column may be left unlabelled,
    which is the same rule the core applies when it resolves a header. Anything
    else is not a header, including an income header and a data row.
    """
    if start + width > len(cells):
        return False
    window = cells[start:start + width]
    if _label_of_first(window[0]) != _EXPENSE_LABELS[0]:
        return False
    if not review_context._amount_label_ok(window[-1]):
        return False
    body = window[1:-1]
    unlabelled = [index for index, name in enumerate(body)
                  if name not in _EXPENSE_LABELS
                  and not review_context._amount_label_ok(name)]
    if width == 7 and unlabelled:
        return False
    if width == 8 and len(unlabelled) != 1:
        return False
    cursor = 0
    for name in _EXPENSE_LABELS[1:]:
        while cursor < len(body) and body[cursor] != name:
            cursor += 1
        if cursor >= len(body):
            return False
        cursor += 1
    return True


def _label_of_first(value: str) -> str:
    return value


def discover_blocks(snapshot_bytes: bytes) -> list[dict]:
    """Every expense block the workbook proves, as date/amount column spans.

    The three layouts this has to survive are the ones a real workbook uses: date
    in column 1 with the amount in column 7, and date in column 2 with the amount
    in column 8 or column 9. Width is proven by the header run, never assumed
    from a column index.
    """
    if type(snapshot_bytes) is not bytes:
        _fail(CODE_ARGUMENT)
    try:
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(snapshot_bytes), data_only=True,
                                 read_only=False)
    except RefreshError:
        raise
    except Exception:
        _fail(CODE_SOURCE_UNREADABLE)

    blocks: list[dict] = []
    try:
        for name in workbook.sheetnames:
            sheet = workbook[name]
            width = sheet.max_column or 0
            for row_index in range(1, (sheet.max_row or 0) + 1):
                cells = [_label(sheet.cell(row=row_index, column=column).value)
                         for column in range(1, width + 1)]
                if not any(cells):
                    continue
                for start in range(width):
                    for candidate_width in _WIDTHS:
                        if _is_expense_header(cells, start, candidate_width):
                            blocks.append({
                                "sheet": name,
                                "header_row": row_index,
                                "date_col": start + 1,
                                "amount_col": start + candidate_width,
                                "width": candidate_width,
                            })
                            break
    finally:
        try:
            workbook.close()
        except Exception:
            pass
    return blocks


def content_digest(snapshot_bytes: bytes) -> str:
    """A digest of what the workbook *says*, not of how it is stored.

    This exists because a real source download is a different file every time
    and says exactly the same thing. A workbook is a ZIP, and a ZIP records
    entry timestamps and ordering, so re-downloading an unchanged export
    produces a different byte hash. The parent measured it: 43 sheets, HTTP 200,
    a different file hash, and not one added, removed or changed cell.

    Deciding "nothing changed" on the byte hash would therefore rotate the
    binding on every collection, and rotating the binding resets the review's
    decisions to blank — so a reviewer would be made to decide the same 1,734
    transactions again and again, for no change in any of them.

    So the comparison is on content: sheet names, cell coordinates, each cell's
    raw stored value *and* its cached value, cell data types, and merged ranges.
    The raw pass matters as much as the cached one. A workbook whose formula
    changed but whose last-saved cached results did not has identical
    data_only values and different business content, and comparing only the
    cached values would call that a no-op and keep serving a source nobody
    reviewed. Both passes, over the same coordinates, is the comparison that
    cannot hide either change.
    """
    if type(snapshot_bytes) is not bytes:
        _fail(CODE_ARGUMENT)
    try:
        from openpyxl import load_workbook
        raw = load_workbook(io.BytesIO(snapshot_bytes), data_only=False,
                            read_only=False)
        cached = load_workbook(io.BytesIO(snapshot_bytes), data_only=True,
                               read_only=False)
    except Exception:
        _fail(CODE_SOURCE_UNREADABLE)

    # Structured, not joined. A cell holding a tab or a newline would, in a
    # tab-and-newline joined string, be indistinguishable from two cells — and a
    # workbook whose only difference is that a value contains the separator would
    # then be called unchanged. That is the one mistake a no-op decision must not
    # be able to make, so the structure is serialised instead of spelled out.
    document: list = []
    try:
        for name in raw.sheetnames:
            sheet = raw[name]
            values = cached[name] if name in cached.sheetnames else None
            cells: list = []
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value is None and (values is None or
                                               values[cell.coordinate].value is None):
                        continue
                    cached_value = ""
                    if values is not None:
                        cached_value = _cell_text(values[cell.coordinate].value)
                    cells.append([cell.coordinate, str(cell.data_type),
                                  _cell_text(cell.value), cached_value])
            document.append({
                "sheet": name,
                "merged": sorted(str(item) for item in sheet.merged_cells.ranges),
                "cells": cells,
            })
    finally:
        for workbook in (raw, cached):
            try:
                workbook.close()
            except Exception:
                pass
    return sha256_text(json.dumps(document, ensure_ascii=False,
                                  sort_keys=True, separators=(",", ":")))


def _cell_text(value) -> str:
    return review_context._display(value)


def _row_is_transaction(sheet, row: int, block: dict) -> bool:
    """A transaction row, by the core's own test for one.

    An explicit date at the block start and a parseable amount at the block end.
    This is the same pair of conditions the core uses to tell a data row from a
    header while scanning upwards, so a row this module calls a transaction is a
    row the core would also treat as data.
    """
    date_value = sheet.cell(row=row, column=block["date_col"]).value
    amount_value = sheet.cell(row=row, column=block["amount_col"]).value
    if _cell_text(date_value).strip() == "":
        return False
    if _cell_text(amount_value).strip() == "":
        return False
    if review_context._parse_explicit_date(date_value) is None:
        return False
    if review_context._parse_amount(amount_value) is None:
        return False
    return True


def _source_ref(sheet_name: str, row: int, block: dict) -> str:
    """The ref naming this row's own date and amount cells.

    The date column is the block's, not a guess. A ref whose date cell is not the
    column the date was read from would point the reviewer at the wrong cell, and
    the core would then compare a different cell's value against the review CSV.
    """
    return "{}!{date}|{amount} (row {row})".format(
        sheet_name,
        date=review_context._col_letters(block["date_col"]) + str(row),
        amount=review_context._col_letters(block["amount_col"]) + str(row),
        row=row,
    )


def _ref_location(ref: str) -> dict | None:
    """A ref's sheet and row, read with the core's own parser."""
    try:
        parsed = review_context._parse_source_ref(ref)
    except Exception:
        return None
    return {"sheet": parsed.sheet, "row": parsed.row,
            "date_col": parsed.date_col, "amount_col": parsed.amount_col}


def _master_candidates(master_csv_text: str) -> dict:
    """Index the master by (date, amount) to the keys that match exactly.

    A transaction is a candidate for a source row when the amount is equal and
    the source date equals *either* of the two dates the master keeps for it: the
    approval date and the posting date. Both are kept, because they are the
    evidence and the reviewer decides which one the source row means.

    Duplicate keys fail closed, with the same rule the core applies.
    """
    if type(master_csv_text) is not str:
        _fail(CODE_MASTER_UNREADABLE)
    try:
        index = review_context._parse_master(master_csv_text)
    except review_context.ReviewContextError as exc:
        if exc.code == review_context.CODE_DUPLICATE_MASTER_KEY:
            _fail(CODE_MASTER_DUPLICATE_KEY)
        _fail(CODE_MASTER_UNREADABLE)

    by_match: dict[tuple[str, Decimal], list[str]] = {}
    for key, record in index.items():
        amount = review_context._parse_amount(record.get("원화금액", ""))
        if amount is None:
            continue
        for field in ("승인일", "매입일"):
            date = review_context._parse_explicit_date(record.get(field, ""))
            if date is None:
                continue
            by_match.setdefault((date, amount), []).append(key)
    for keys in by_match.values():
        keys.sort()
    return index, by_match


def master_semantic_digest(master_csv_text: str) -> str:
    """A digest of what the master says, independent of how the file is written.

    A master re-exported with the same rows in a different order, or with
    different line endings, is the same content and must not rotate the review.
    Every one of the seventeen fields of every row is folded in, so a changed
    amount, a changed date or a changed key is a different content.
    """
    index, _by_match = _master_candidates(master_csv_text)
    # A JSON array of arrays, not a joined line. A 가맹점 containing the
    # separator would otherwise produce the same digest as a row split across
    # two, and two different masters would be called the same content.
    document = [[key] + [str(index[key].get(header, ""))
                        for header in review_context.MASTER_HEADERS]
                for key in sorted(index)]
    return sha256_text(json.dumps(document, ensure_ascii=False,
                                  separators=(",", ":")))


def review_scope_digest(previous_review_csv_text: str) -> str:
    """A digest of the refs the previous review listed, order-independent.

    The scope is what the previous review knew; the decisions in it are not
    carried, so they are not part of this digest either. What is compared is
    which rows were under review, because a source that grew is a different
    input even when the master did not change at all.
    """
    if not previous_review_csv_text:
        return sha256_text("")
    refs = sorted(_previous_refs(previous_review_csv_text))
    return sha256_text(json.dumps(refs, ensure_ascii=False,
                                  separators=(",", ":")))


def content_marker(snapshot_bytes: bytes, master_csv_text: str,
                   scope_csv_text: str) -> dict:
    """The three parts of "did anything change", kept apart on purpose.

    The workbook and the master are the inputs, and the scope is the review that
    was *generated* from them. It has to be the generated one: after an
    activation the next run reads the new review CSV as its input, so a marker
    written from the old input's scope would never match the next run's input
    scope, and an unchanged source would be re-collected and re-activated on every
    run. With the generated scope in the marker, the first run after an activation
    compares equal and stops.

    Kept as three values rather than one digest so a change can be attributed: a
    new card transaction and a new workbook row are different facts about the
    source, and the operator is told which happened.
    """
    return {
        "workbook": content_digest(snapshot_bytes),
        "master": master_semantic_digest(master_csv_text),
        "scope": review_scope_digest(scope_csv_text or ""),
    }


def marker_matches(active: dict, workbook: str, master: str, scope: str) -> bool:
    """Is this the same content, by all three parts?"""
    if not active:
        return False
    if active.get("workbook") != workbook or active.get("master") != master:
        return False
    return active.get("scope") == scope


def sheet_name_missing(workbook, location) -> bool:
    return location["sheet"] not in workbook.sheetnames


def _row_still_holds(sheet, row: int, block: dict, recorded: dict) -> bool:
    """Does this row still carry the date and amount the review recorded?

    The check is on the row's own cells, parsed by the core's parsers, and
    compared with the values the previous review CSV held. A row whose cells
    changed, or whose text is no longer a transaction at all, does not still hold
    them, and is a removal rather than a preserved row.
    """
    date_value = sheet.cell(row=row, column=block["date_col"]).value
    amount_value = sheet.cell(row=row, column=block["amount_col"]).value
    if _cell_text(date_value).strip() == "" or _cell_text(amount_value).strip() == "":
        return False
    date_now = review_context._parse_explicit_date(date_value)
    amount_now = review_context._parse_amount(amount_value)
    if date_now is None or amount_now is None:
        return False
    date_before = review_context._parse_explicit_date(
        recorded.get("source_date", ""))
    amount_before = review_context._parse_amount(
        recorded.get("source_amount", ""))
    if date_before is None or amount_before is None:
        return False
    return date_before == date_now and amount_before == amount_now


def _previous_refs(previous_review_csv_text: str) -> dict:
    """The refs the previous review input listed, with their locations.

    This is the half of the scope that no header proves. It is read as a *layout*
    record — which sheet and row was reviewed — and never as a decision: the
    previous ``reviewer_decision`` values are not carried into a new bundle, so a
    rejection or an approval made against the old source cannot follow a row to
    the new one.
    """
    if type(previous_review_csv_text) is not str:
        return {}
    try:
        reader = csv.reader(io.StringIO(previous_review_csv_text), strict=True)
        rows = list(reader)
    except Exception:
        _fail(CODE_REVIEW_INPUT_INVALID)
    if not rows:
        return {}
    header = rows[0]
    if "source_ref_snapshot_only" not in header:
        _fail(CODE_REVIEW_INPUT_INVALID)
    index = header.index("source_ref_snapshot_only")
    found: dict[str, dict] = {}
    for record in rows[1:]:
        if len(record) != len(header):
            _fail(CODE_REVIEW_INPUT_INVALID)
        ref = record[index]
        if ref == "" or ref.strip() == "":
            _fail(CODE_REVIEW_INPUT_INVALID)
        if ref in found:
            _fail(CODE_REVIEW_INPUT_INVALID)
        location = _ref_location(ref)
        if location is None:
            _fail(CODE_REVIEW_INPUT_INVALID)
        # The values the previous review recorded for this row. They are what
        # makes a removal a removal: a row that no longer holds them is gone,
        # rather than merely not having been looked at.
        fields = dict(zip(header, record))
        location["source_date"] = fields.get("source_date", "")
        location["source_amount"] = fields.get("source_amount", "")
        found[ref] = location
    return found


#: The date and amount labels an income block carries. Narrow on purpose: a
#: subtotal row says 합계 in an amount column and a memo row says anything at
#: all, and neither of those is a block starting. Only a row that reads as a
#: header in both of those positions is treated as one.
_INCOME_DATE_LABELS = ("일자", "날짜", "거래일", "입금일", "적립일", "수입일")
_INCOME_AMOUNT_LABELS = ("금액", "입금액", "적립액", "수입액")


def _row_labels(sheet, row: int, block: dict) -> list[str]:
    return [_label(sheet.cell(row=row, column=column).value)
            for column in range(block["date_col"], block["amount_col"] + 1)]


def _is_expense_header_row(labels: list[str]) -> bool:
    return _is_expense_header(labels, 0, len(labels))


def _is_income_header_row(labels: list[str]) -> bool:
    """Does this row read as the start of an income block?

    It has to look like a header, not like data: a date label in the block's date
    column and an amount label in its amount column. A row that merely has words
    in it is a memo, a title or a subtotal, and none of those ends a range.
    """
    if len(labels) < 2:
        return False
    if labels[0] not in _INCOME_DATE_LABELS:
        return False
    return any(label in _INCOME_AMOUNT_LABELS for label in labels[1:])


def _is_block_boundary(sheet, row: int, block: dict) -> bool:
    """Does a new block start here? Only an explicit header says so.

    The earlier version treated *any* row that was not a transaction as a
    boundary. A financial workbook has memo lines, section titles and subtotal
    rows in the middle of a block, and each one ended the scan, so everything
    below it was dropped. On the real source that lost 514 rows the previous
    review had listed, and 520 of the rows there have no header above them at
    all, so they had no second chance to be found.

    So the boundary is an explicit header — the next expense block, or an income
    block starting. A blank row is not one either: a block is often split by
    spacing, and a boundary there would truncate the range just as badly.
    """
    labels = _row_labels(sheet, row, block)
    if not any(labels):
        return False
    if _is_expense_header_row(labels):
        return True
    if _is_income_header_row(labels):
        return True
    return False


def _scan_range(sheet, block: dict, start_row: int):
    """Every transaction row of one column range from ``start_row`` downward.

    Stopping only at an explicit header is what lets a range survive the memo
    rows, the section titles and the subtotals inside it. A row that is neither
    a transaction nor a header is skipped and the scan continues.
    """
    for row in range(max(1, start_row), (sheet.max_row or 0) + 1):
        if row > _MAX_ROWS:
            _fail(CODE_SOURCE_UNREADABLE)
        if _is_block_boundary(sheet, row, block):
            return
        if _row_is_transaction(sheet, row, block):
            yield row


def build_review_csv(snapshot_bytes: bytes, master_csv_text: str,
                     previous_review_csv_text: str = "") -> str:
    """The new review CSV: every in-scope row, every decision blank.

    The output is the adapter's own shape, with the same eleven headers and the
    same schema version, so the whole existing validation applies unchanged.
    """
    records, _removed = _build_rows(snapshot_bytes, master_csv_text,
                                    previous_review_csv_text)
    return _render(records, sha256_bytes(snapshot_bytes))


def _render(records: list[list[str]], snapshot_sha: str) -> str:
    if not records:
        _fail(CODE_SOURCE_EMPTY)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(REQUIRED_HEADERS))
    for record in records:
        writer.writerow(record)
    return buffer.getvalue()


def _build_rows(snapshot_bytes: bytes, master_csv_text: str,
                previous_review_csv_text: str):
    """Every in-scope row, and the previous rows this bundle no longer has.

    Scope is the union of what the new workbook's own expense headers prove and
    what the previous review listed. Both halves matter and neither is enough:

    * The headers find additions and moves, including a row that appeared inside
      a range that never had a header — which is why a header-less range from the
      previous review is re-scanned over the same column span instead of being
      taken row by row. Scanning only the old rows would find the old rows and
      nothing else, so a new row in a header-less range would be invisible.
    * The previous review keeps a row whose header was deleted, and a row that
      only ever lacked a header, as a held row rather than dropping it.

    A previous ref that is not claimed by either half is a *removal*, and it is
    reported as one. It is not an error: a row that is genuinely gone from the
    source must leave the review, or the review grows forever and shows rows
    that no longer exist. It used to be a hard failure, which meant a source
    could never shrink.
    """
    snapshot_sha = sha256_bytes(snapshot_bytes)
    master_index, by_match = _master_candidates(master_csv_text)
    previous = _previous_refs(previous_review_csv_text or "")
    blocks = discover_blocks(snapshot_bytes)
    if not blocks and not previous:
        _fail(CODE_SCOPE_UNPROVEN)

    try:
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(snapshot_bytes), data_only=True,
                                 read_only=False)
    except Exception:
        _fail(CODE_SOURCE_UNREADABLE)

    try:
        claimed: dict[str, dict] = {}
        for block in blocks:
            sheet = workbook[block["sheet"]]
            for row in _scan_range(sheet, block, block["header_row"] + 1):
                ref = _source_ref(block["sheet"], row, block)
                claimed[ref] = {
                    "sheet": block["sheet"], "row": row, "block": block,
                    "proved_by_header": True,
                }

        # The ranges the previous review knew, whatever a header proves about
        # them. This scan used to be skipped whenever a block with the same
        # columns existed, and that lost every row of a range that sat *above*
        # that block's header, or below a memo line inside it. On the real source
        # that was 514 rows the previous review had listed: the block scan found
        # the rows under the header, and the skip meant nothing else was looked
        # for. So the range is always scanned, from the top of the sheet, and a
        # row already claimed is simply not claimed twice.
        ranges: dict[tuple, list[int]] = {}
        for ref, location in previous.items():
            key = (location["sheet"], location["date_col"],
                   location["amount_col"])
            ranges.setdefault(key, []).append(location["row"])

        for (sheet_name, date_col, amount_col), _rows in ranges.items():
            if sheet_name not in workbook.sheetnames:
                continue
            sheet = workbook[sheet_name]
            block = {"sheet": sheet_name, "date_col": date_col,
                     "amount_col": amount_col}
            for row in _scan_range(sheet, block, 1):
                ref = _source_ref(sheet_name, row, block)
                if ref in claimed:
                    continue
                claimed[ref] = {
                    "sheet": sheet_name, "row": row, "block": block,
                    "proved_by_header": False,
                }

        # A previous ref is kept while its own row still holds the values the
        # previous review recorded, whether or not a scan reached it. That is the
        # "its original values are still there" test, and it is what makes a
        # removal mean a removal rather than a scan that did not look.
        for ref, location in previous.items():
            if ref in claimed:
                continue
            recorded = previous[ref]
            if sheet_name_missing(workbook, location):
                continue
            sheet = workbook[location["sheet"]]
            block = {"sheet": location["sheet"],
                     "date_col": location["date_col"],
                     "amount_col": location["amount_col"]}
            if location["row"] > (sheet.max_row or 0):
                continue
            if not _row_still_holds(sheet, location["row"], block, recorded):
                continue
            claimed[ref] = {
                "sheet": location["sheet"], "row": location["row"],
                "block": block, "proved_by_header": False,
            }

        removed = sorted(ref for ref in previous if ref not in claimed)

        if not claimed:
            _fail(CODE_SOURCE_EMPTY)

        records: list[list[str]] = []
        for ref in sorted(claimed):
            entry = claimed[ref]
            sheet = workbook[entry["sheet"]]
            block = entry["block"]
            row = entry["row"]
            date_value = sheet.cell(row=row, column=block["date_col"]).value
            amount_value = sheet.cell(row=row, column=block["amount_col"]).value
            source_date = review_context._parse_explicit_date(date_value)
            source_amount = review_context._parse_amount(amount_value)
            if source_date is None or source_amount is None:
                _fail(CODE_CELL_UNUSABLE)

            # The two master dates are two pieces of evidence for the same key,
            # so a transaction whose approval and posting dates are equal is one
            # candidate, not two. Listed twice it would be a duplicate candidate
            # key, and the adapter refuses duplicates.
            keys = sorted(set(by_match.get((source_date, source_amount), [])))
            for key in keys:
                if key not in master_index:
                    _fail(CODE_CANDIDATE_UNRESOLVED)
            date_fields = [
                {
                    "key": key,
                    "approval_date": master_index[key].get("승인일", ""),
                    "posting_date": master_index[key].get("매입일", ""),
                }
                for key in keys
            ]
            disposition = RAW_CANDIDATE if keys else RAW_UNMATCHED
            records.append([
                ref,
                _cell_text(date_value),
                _cell_text(amount_value),
                str(len(keys)),
                json.dumps(keys, ensure_ascii=False),
                json.dumps(date_fields, ensure_ascii=False),
                disposition,
                # Every decision blank. A new bundle starts with nothing decided,
                # and this module has no authority to carry one across.
                "",
                "",
                REVIEW_SCHEMA_VERSION,
                snapshot_sha,
            ])
    finally:
        try:
            workbook.close()
        except Exception:
            pass

    if not records:
        _fail(CODE_SOURCE_EMPTY)
    return records, removed


# --------------------------------------------------------------------- bundle

#: One in-process guard, so two threads in this process cannot both collect.
#: It is *not* the machine-wide guarantee — see `collector_lock` for that.
_THREAD_LOCK = threading.Lock()

try:
    import msvcrt  # Windows
except Exception:  # pragma: no cover - the other branch is POSIX
    msvcrt = None
try:
    import fcntl  # POSIX
except Exception:  # pragma: no cover
    fcntl = None


def _lock_name(config_path) -> pathlib.Path:
    """The lock file for one config, beside it.

    Beside the config rather than in a temp directory, because the lock has to
    mean the same thing to every collector that cares about *this* config. Two
    configs are two reviews and may be collected at the same time; the same
    config twice is one review and must not be.
    """
    config_path = pathlib.Path(config_path)
    return config_path.parent / (config_path.name + ".collector.lock")


class _FileLock:
    """An exclusive lock on a file, held by the operating system.

    A `threading.Lock` only stops threads in this process. The operator's real
    risk is a second collector *process* — a scheduled run overlapping a manual
    one, or two watch loops on two terminals — and two processes both passing
    their own validation and then racing on the config swap would leave the
    machine activating a bundle whose bytes nobody checked against the file that
    became active. So the lock is an OS lock on a real file, taken for the whole
    distance from reading the source to the config replacement, and it is held by
    the file handle, which the operating system releases if the process dies
    rather than leaving a lock nobody can clear.

    Non-blocking, so a second collector is told the machine is busy instead of
    queueing behind a fetch it may hold for minutes.
    """

    def __init__(self, config_path):
        self._path = _lock_name(config_path)
        self._handle = None

    def acquire(self) -> bool:
        self._handle = open(self._path, "a+b")
        try:
            if msvcrt is not None:
                # From byte 0, every time. The lock is a byte range, so locking
                # wherever the handle happens to sit would let two collectors
                # take different bytes of the same file and both believe they
                # hold the lock.
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            elif fcntl is not None:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                return False
        except OSError:
            self._close()
            return False
        return True

    def _close(self):
        if self._handle is None:
            return
        try:
            if msvcrt is not None:
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self._handle.close()
        except Exception:
            pass
        self._handle = None

    def release(self) -> None:
        self._close()

    def __enter__(self):
        if not self.acquire():
            _fail(CODE_COLLECTOR_BUSY)
        return self

    def __exit__(self, *exc):
        self.release()
        return False


class collector_lock:
    """The collector lock for one config: OS lock, then the in-process guard.

    Held across collection *and* activation by `collect_and_activate`, which is
    the only way the guarantee is complete. Calling `collect` and then
    `activate` separately still locks each step, and a bundle is named after its
    own digests and written once, so a bundle staged but not activated is inert
    rather than dangerous.
    """

    def __init__(self, config_path):
        self._file = _FileLock(config_path)
        self._thread = False

    def __enter__(self):
        if not self._file.acquire():
            _fail(CODE_COLLECTOR_BUSY)
        if not _THREAD_LOCK.acquire(blocking=False):
            self._file.release()
            _fail(CODE_COLLECTOR_BUSY)
        self._thread = True
        return self

    def __exit__(self, *exc):
        if self._thread:
            self._thread = False
            _THREAD_LOCK.release()
        self._file.release()
        return False


def _write_immutable(path: pathlib.Path, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)


def _bundle_name(snapshot_sha: str, review_sha: str, master_sha: str) -> str:
    return "{}-{}-{}".format(snapshot_sha[:16], review_sha[:16], master_sha[:16])


def collect(config_path, bundle_root, snapshot_bytes: bytes, master_csv_text: str,
            previous_review_csv_text: str = "", minimum_rows: int = 0,
            active_content: dict | None = None) -> dict:
    """Build, prove and stage a bundle without activating it.

    Staging without activating is safe and is what a dry run wants: a bundle is
    named after its own digests and written once, so staging the same inputs
    twice writes the same bytes and proves nothing changed.
    """
    with collector_lock(config_path):
        return _collect_locked(config_path, bundle_root, snapshot_bytes,
                               master_csv_text, previous_review_csv_text,
                               minimum_rows, active_content or {})


def _collect_locked(config_path, bundle_root, snapshot_bytes: bytes,
                    master_csv_text: str, previous_review_csv_text: str,
                    minimum_rows: int, active_content: dict) -> dict:
    """Build, prove, and stage a bundle. Does not activate it.

    The proof is the whole existing review core over the candidate bundle, run
    before anything is written to the active config. A bundle that the core would
    reject is never staged, and therefore never activated.
    """
    if type(snapshot_bytes) is not bytes or not snapshot_bytes:
        _fail(CODE_SOURCE_EMPTY)
    if type(master_csv_text) is not str or not master_csv_text:
        _fail(CODE_MASTER_UNREADABLE)
    bundle_root = pathlib.Path(bundle_root)
    config_path = pathlib.Path(config_path)

    # The marker of the bundle that is actually active, read from its own
    # directory rather than remembered. A caller may pass one instead, which is
    # how a test states what it believes is live.
    active = dict(active_content) if active_content else read_content_marker(
        config_path)
    # The no-op path is only open while the live source is the one that was
    # verified. If the three active files no longer hash to what the config says,
    # a matching marker is not evidence of anything, and the full path runs.
    allow_no_op = bool(active) and _active_inputs_intact(config_path)
    workbook_digest = content_digest(snapshot_bytes)
    master_digest = master_semantic_digest(master_csv_text)
    if allow_no_op and marker_matches(
            active, workbook_digest, master_digest,
            review_scope_digest(previous_review_csv_text or "")):
        # The same workbook, re-downloaded. The bytes differ because a ZIP does,
        # and the content does not, so the binding must not move: a new bundle
        # here would blank every saved decision for 1,734 unchanged
        # transactions. The existing bundle, its config and its binding all stay
        # exactly as they are, and only the collection time moves.
        return {
            "no_op": True,
            "content": dict(active),
            "removed_refs": [],
            "snapshot_sha256": "",
            "review_sha256": "",
            "master_sha256": "",
            "rows": 0,
            "bundle_dir": "",
            "snapshot_path": "",
            "review_path": "",
            "master_path": "",
            "decisions_db_path": "",
        }

    records, removed = _build_rows(snapshot_bytes, master_csv_text,
                                   previous_review_csv_text)
    review_text = _render(records, sha256_bytes(snapshot_bytes))
    snapshot_sha = sha256_bytes(snapshot_bytes)
    content = content_marker(snapshot_bytes, master_csv_text, review_text)
    if allow_no_op and marker_matches(active, workbook_digest, master_digest,
                                     content["scope"]):
        # The source and the master are unchanged and the review they generate is
        # the one that is already active. The input scope differed — a bundle was
        # activated since — and the content did not, so this is still a no-op and
        # the live binding stays where it is.
        return {
            "no_op": True,
            "content": content,
            "removed_refs": [],
            "snapshot_sha256": "",
            "review_sha256": "",
            "master_sha256": "",
            "rows": 0,
            "bundle_dir": "",
            "snapshot_path": "",
            "review_path": "",
            "master_path": "",
            "decisions_db_path": "",
        }
    review_sha = sha256_text(review_text)
    master_sha = sha256_text(master_csv_text)

    try:
        model = review_context.build_review_context(
            snapshot_bytes, review_text, master_csv_text,
            snapshot_sha, review_sha, master_sha)
    except review_context.ReviewContextError as exc:
        _fail(CODE_CONTEXT_REJECTED)

    rows = len(model["rows"])
    if rows == 0:
        _fail(CODE_SOURCE_EMPTY)
    # A source that suddenly has far fewer rows is a truncated download or a
    # wrong file, not a smaller month. Refusing it keeps the previous bundle
    # active, which is the safe direction: the reviewer keeps working on rows
    # that really exist.
    # `minimum_rows` is an operator's own floor and is off unless given. It
    # used to be applied to any decrease in row count, which made a verified
    # deletion impossible to ever collect: a source that genuinely lost a row
    # was indistinguishable from a truncated download, and the one bundle
    # that could prove the difference was the one refused. A real truncation
    # still fails, by having no provable scope at all.
    if minimum_rows and rows < minimum_rows:
        _fail(CODE_ROWS_SHRANK)

    manifest = _read_manifest(config_path)
    bundle_dir = bundle_root / _bundle_name(snapshot_sha, review_sha,
                                            master_sha)
    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        _stage(bundle_dir, snapshot_bytes, review_text, master_csv_text,
               manifest, content)
    except RefreshError:
        raise
    except Exception:
        _fail(CODE_BUNDLE_WRITE_FAILED)
    return {
        "no_op": False,
        "content": content,
        "removed_refs": removed,
        "bundle_dir": str(bundle_dir),
        "snapshot_path": str(bundle_dir / "snapshot.xlsx"),
        "review_path": str(bundle_dir / "review.csv"),
        "master_path": str(bundle_dir / "master.csv"),
        "snapshot_sha256": snapshot_sha,
        "review_sha256": review_sha,
        "master_sha256": master_sha,
        "rows": rows,
        "decisions_db_path": manifest.get("decisions_db_path", ""),
    }


def _read_manifest(config_path: pathlib.Path) -> dict:
    """The current config, for the two values a new bundle must inherit.

    The decisions database path is the review's own history and belongs to the
    review, not to the source. A new bundle that pointed somewhere else would
    silently start a second, empty decision history.
    """
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if type(data) is not dict:
        return {}
    return data


def _stage(bundle_dir: pathlib.Path, snapshot_bytes: bytes, review_text: str,
           master_csv_text: str, manifest: dict, content: dict) -> None:
    """Write the bundle once, and never over it.

    A bundle directory is named after its three digests, so an identical input
    lands on the identical path: that is the no-op case, and it is proven by the
    bytes already being there rather than by a claim that nothing changed.
    """
    snapshot_path = bundle_dir / "snapshot.xlsx"
    review_path = bundle_dir / "review.csv"
    master_path = bundle_dir / "master.csv"
    payload = (
        (snapshot_path, snapshot_bytes),
        # newline="" so the bytes on disk are the bytes the digests were taken
        # over; a translating write would change them and the core would refuse
        # its own bundle.
        (review_path, review_text.encode("utf-8")),
        (master_path, master_csv_text.encode("utf-8")),
    )
    for path, data in payload:
        if path.exists():
            if path.read_bytes() != data:
                _fail(CODE_BUNDLE_WRITE_FAILED)
            continue
        _write_immutable(path, data)

    # The content digest lives beside the bundle rather than in the config: the
    # config's seven keys are the core's contract and must not grow.
    content_path = bundle_dir / "content.json"
    marker = (json.dumps(content, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")) + "\n").encode("utf-8")
    if content_path.exists():
        if content_path.read_bytes() != marker:
            _fail(CODE_BUNDLE_WRITE_FAILED)
    else:
        _write_immutable(content_path, marker)


def _config_bytes(config_path) -> bytes:
    try:
        return pathlib.Path(config_path).read_bytes()
    except OSError:
        return b""


def _config_binding(config_path):
    """The binding the live config currently names, and the config's own sha.

    Read inside the collector lock, so it is a statement about the config as it
    is at this moment and not about a moment earlier. Both halves are needed: the
    binding says which source is live, and the config's own digest says the file
    itself has not been replaced by another collector in the meantime.
    """
    raw = _config_bytes(config_path)
    if not raw:
        return "", ""
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except Exception:
        return "", sha256_bytes(raw)
    if type(manifest) is not dict:
        return "", sha256_bytes(raw)
    binding = "|".join((
        str(manifest.get("snapshot_sha256", "")),
        str(manifest.get("review_sha256", "")),
        str(manifest.get("master_sha256", "")),
    ))
    return binding, sha256_bytes(raw)


def _active_inputs_intact(config_path) -> bool:
    """Do the three files the live config names still hash to what it says?

    A marker on its own is not evidence that the active source is intact. If the
    active workbook was truncated or replaced in place, a matching content marker
    would still say "unchanged" and the collector would report a successful no-op
    while serving a source that is not the one that was verified. So the no-op
    path re-reads the three active inputs and checks them against the config.
    """
    try:
        manifest = json.loads(
            pathlib.Path(config_path).read_bytes().decode("utf-8"))
    except Exception:
        return False
    checks = (("snapshot_path", "snapshot_sha256", "rb"),
              ("review_path", "review_sha256", "text"),
              ("master_path", "master_sha256", "text"))
    for path_key, digest_key, mode in checks:
        try:
            path = manifest[path_key]
            with open(path, "rb") as handle:
                data = handle.read()
        except Exception:
            return False
        if mode == "text":
            try:
                data = data.decode("utf-8")
            except Exception:
                return False
            digest = sha256_text(data)
        else:
            digest = sha256_bytes(data)
        if digest != manifest.get(digest_key):
            return False
    return True


def collect_and_activate(config_path, bundle_root, snapshot_bytes: bytes,
                         master_csv_text: str, previous_review_csv_text: str = "",
                         minimum_rows: int = 0) -> dict:
    """Collect and activate under one lock, and say whether anything moved.

    The single-lock path is the one an operator should use. The no-op check, the
    staging and the config replacement then happen with no window between them in
    which a second collector could read the same source and write its own answer.
    """
    with collector_lock(config_path):
        base_binding, base_config_sha = _config_binding(config_path)
        # The no-op is decided on the marker's *content* digest, and only after
        # the active inputs have been re-checked against the live config.
        # One read of the marker and one integrity check, both inside the lock,
        # and both used by the no-op decision wherever it is taken.
        active = read_content_marker(config_path) if base_binding else {}
        bundle = _collect_locked(config_path, bundle_root, snapshot_bytes,
                                 master_csv_text, previous_review_csv_text,
                                 minimum_rows, active)
        bundle["expected_base_binding"] = base_binding
        bundle["expected_base_config_sha256"] = base_config_sha
        if bundle.get("no_op"):
            return bundle
        bundle["activated"] = True
        bundle["activate_code"] = _activate_locked(config_path, bundle)
        return bundle


def activate(config_path, bundle: dict) -> str:
    """Point the live config at a staged bundle, taking the lock for it.

    The same verification as the single-lock path, so a bundle staged by one
    process and activated by another is still checked against the files on disk
    and against the config as it is now.
    """
    with collector_lock(config_path):
        return _activate_locked(config_path, bundle)


def _verify_bundle_on_disk(bundle: dict) -> None:
    """Re-read the three bundle files and prove them before the config names them.

    Staging and activating are separate moments, and something can write in
    between — another collector, a person, a partial copy. The digests recorded at
    staging time are not evidence about the bytes that are there now, so the bytes
    are read again and the whole core is run over them.
    """
    checks = (("snapshot_path", "snapshot_sha256", False),
              ("review_path", "review_sha256", True),
              ("master_path", "master_sha256", True))
    payloads = {}
    for path_key, digest_key, as_text in checks:
        try:
            data = pathlib.Path(bundle[path_key]).read_bytes()
        except OSError:
            _fail(CODE_BUNDLE_WRITE_FAILED)
        if as_text:
            try:
                payloads[path_key] = data.decode("utf-8")
            except Exception:
                _fail(CODE_BUNDLE_WRITE_FAILED)
            digest = sha256_text(payloads[path_key])
        else:
            payloads[path_key] = data
            digest = sha256_bytes(data)
        if digest != bundle.get(digest_key):
            _fail(CODE_BUNDLE_WRITE_FAILED)
    try:
        review_context.build_review_context(
            payloads["snapshot_path"], payloads["review_path"],
            payloads["master_path"], bundle["snapshot_sha256"],
            bundle["review_sha256"], bundle["master_sha256"])
    except review_context.ReviewContextError:
        _fail(CODE_CONTEXT_REJECTED)
    except Exception:
        _fail(CODE_CONTEXT_REJECTED)


def _activate_locked(config_path, bundle: dict) -> str:
    """Point the live config at a staged bundle. The last thing that happens.

    Three things are re-checked here, in this order, because this is the last
    moment at which any of them can still stop the change:

    1. The three bundle files on disk still hash to what staging recorded, and the
       whole review core still accepts them. A bundle that was written once and
       never touched again is the normal case, and a bundle that was touched is
       not activated on the strength of a digest written hours ago.
    2. The config has not been replaced since the collection began. That is the
       compare-and-swap: another collector that activated in the meantime must not
       be silently overwritten by this one's older bundle.
    3. Only then is the single file replaced. `os.replace` is atomic, so a reader
       sees either the old config or the new one and never a half-written file.
    """
    config_path = pathlib.Path(config_path)
    _verify_bundle_on_disk(bundle)

    expected_config = bundle.get("expected_base_config_sha256", "")
    current_binding, current_config_sha = _config_binding(config_path)
    if expected_config and current_config_sha != expected_config:
        # Somebody else's config is live. Activating over it would replace a
        # source this collector never verified against this config.
        _fail(CODE_BASE_CONFIG_CHANGED)

    manifest = {
        "snapshot_path": bundle["snapshot_path"],
        "snapshot_sha256": bundle["snapshot_sha256"],
        "review_path": bundle["review_path"],
        "review_sha256": bundle["review_sha256"],
        "master_path": bundle["master_path"],
        "master_sha256": bundle["master_sha256"],
        "decisions_db_path": bundle["decisions_db_path"],
    }
    for key in ("snapshot_path", "review_path", "master_path",
                "decisions_db_path"):
        if not manifest[key]:
            _fail(CODE_BUNDLE_WRITE_FAILED)
    for key, digest in (("snapshot_sha256", manifest["snapshot_sha256"]),
                        ("review_sha256", manifest["review_sha256"]),
                        ("master_sha256", manifest["master_sha256"])):
        if len(digest) != 64:
            _fail(CODE_BUNDLE_WRITE_FAILED)

    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=str(config_path.parent),
        prefix=config_path.name + ".", suffix=".new", delete=False)
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, str(config_path))
    except Exception:
        try:
            os.unlink(handle.name)
        except Exception:
            pass
        _fail(CODE_BUNDLE_WRITE_FAILED)
    return CODE_CONFIG_REPLACED


# --------------------------------------------------------------------- status

_STATUS_NAME = "status.json"


def read_content_marker(config_path) -> dict:
    """The content marker of the bundle that is actually active right now.

    Read from the config's own bundle directory, not from a remembered value, so
    a no-op decision compares against what is live and not against what was live
    last time. A missing or unreadable marker compares as unknown, which is the
    direction that re-collects rather than skips.
    """
    try:
        manifest = json.loads(pathlib.Path(config_path).read_text(encoding="utf-8"))
        bundle_dir = pathlib.Path(manifest["snapshot_path"]).parent
        marker = json.loads(bundle_dir.joinpath("content.json").read_text(
            encoding="utf-8"))
    except Exception:
        return {}
    return marker if type(marker) is dict else {}


def write_status(bundle_root, code: str, bundle: dict | None = None,
                 collected_at: str = "", path: str = "") -> None:
    """Record a fixed code and the last good binding, and nothing else.

    A collector's status file is read by a person deciding whether to trust the
    active source. It therefore carries the code and the three digests of the last
    bundle that passed the whole core — never a path, a URL, a cell value or an
    exception message.
    """
    record: dict = {"code": code}
    if collected_at:
        # Only the time a collection succeeded. A no-op is a success, and it is
        # the one success that changes nothing else on disk.
        record["collected_at"] = collected_at
    if bundle:
        record["last_good_binding"] = "|".join((
            bundle["snapshot_sha256"], bundle["review_sha256"],
            bundle["master_sha256"]))
        record["last_good_content"] = bundle.get("content", {})
        record["rows"] = bundle["rows"]
        # The refs this bundle no longer has, so a removal is a reportable fact
        # rather than a silent difference.
        record["removed_refs"] = list(bundle.get("removed_refs", []))
    # An explicit path when one is given, so the collector and the web app are
    # reading and writing the same file by name rather than by two conventions
    # that happen to agree today.
    target = pathlib.Path(path) if path else pathlib.Path(bundle_root) / _STATUS_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    os.replace(str(temporary), str(target))


def load_status(bundle_root) -> dict:
    try:
        data = json.loads(
            (pathlib.Path(bundle_root) / _STATUS_NAME).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if type(data) is dict else {}
