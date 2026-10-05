"""REVIEW-UI-001 read-only review context core (Bunny writer scope).

Pure functions only: no filesystem, database, network or clock access. The
two public entry points are

    build_review_context(snapshot_bytes, review_csv_text, master_csv_text,
                         snapshot_sha256, review_sha256, master_sha256)
    build_review_export(model, original_review_csv_text, decisions)

Contract summary
----------------
* Hashes are the existing ``webapp.contracts.sha256_bytes`` /
  ``sha256_text`` (no new hash algorithm). CSV text is hashed by exact UTF-8
  re-encode, so a BOM byte in the text is part of the digest; the parser
  removes a leading BOM only, exactly as the existing adapter does.
* The original review CSV is validated with the existing
  ``normalize_review_csv(text, snapshot_sha256)``. Candidates are never
  fabricated, never moved between rows and a blank decision is never
  promoted.
* Every refusal raises :class:`ReviewContextError` with a fixed code only.
  No raw CSV, no path, no customer value, no exception repr and no
  traceback ever reaches a code or a message.

Source evidence
---------------
``source_ref_snapshot_only`` is ``sheet!dateCell|amountCell (row N)``. The
core requires an existing sheet, existing cells, the same physical row N for
both cells, the date column strictly left of the amount column, and a date
value and a Decimal amount that are exactly equal to the manifest values.
A date string without an explicit four-digit year is refused; no year is
ever inferred.

Only the ``dateCell..amountCell`` column range is read, so an adjacent
income or expense block sitting on the same physical row is never mixed in.
The nearest row above that has any non-blank cell inside that exact column
range is treated as *the* candidate header row. It is accepted only when its
own cells in that range are the expense labels

    거래일자 / 항목 / 내용 / 기간 / 예약번호 / 증빙유형 / 금액

with an optional 원 suffix tolerated on the amount header, because that
suffix is an actual explicit header in this workbook family. Width 7 is the
standard block. Width 8 is accepted only when the same seven labels appear
in that order inside the range and exactly one remaining column is left over:
that column's header text and cell value are preserved raw and are never
given a meaning. Any other header (for example the income block header) is
not allowed to label the expense block, and a missing or ambiguous header
makes the row ``insufficient`` and blocks APPROVE.

Because the source block has no merchant column, ``source.merchant`` is
always the literal ``없음``: the 항목 column is an item label, never a
merchant or a customer, and an extra column is never interpreted. A date and
an amount on their own never establish identity.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .contracts import sha256_bytes, sha256_text
from .migration import build_reviewed_import_plan
from .review_csv_adapter import normalize_review_csv

__all__ = [
    "ReviewContextError",
    "build_review_context",
    "build_review_export",
    "MASTER_HEADERS",
    "SOURCE_BLOCK_LABELS",
]

# --------------------------------------------------------------- fixed codes

CODE_INVALID_ARGUMENT = "INVALID_ARGUMENT"
CODE_INVALID_SHA256 = "INVALID_SHA256"
CODE_SNAPSHOT_HASH_MISMATCH = "SNAPSHOT_HASH_MISMATCH"
CODE_REVIEW_HASH_MISMATCH = "REVIEW_HASH_MISMATCH"
CODE_MASTER_HASH_MISMATCH = "MASTER_HASH_MISMATCH"
CODE_INVALID_SNAPSHOT_WORKBOOK = "INVALID_SNAPSHOT_WORKBOOK"
CODE_REVIEW_CSV_INVALID = "REVIEW_CSV_INVALID"
CODE_INVALID_MASTER_CSV = "INVALID_MASTER_CSV"
CODE_DUPLICATE_MASTER_KEY = "DUPLICATE_MASTER_KEY"
CODE_CANDIDATE_KEY_UNRESOLVED = "CANDIDATE_KEY_UNRESOLVED"
CODE_INVALID_SOURCE_REF = "INVALID_SOURCE_REF"
CODE_SOURCE_SHEET_MISSING = "SOURCE_SHEET_MISSING"
CODE_SOURCE_CELL_MISSING = "SOURCE_CELL_MISSING"
CODE_SOURCE_ROW_MISMATCH = "SOURCE_ROW_MISMATCH"
CODE_SOURCE_COLUMN_ORDER = "SOURCE_COLUMN_ORDER"
CODE_SOURCE_BLOCK_WIDTH_UNSUPPORTED = "SOURCE_BLOCK_WIDTH_UNSUPPORTED"
CODE_SOURCE_DATE_UNPARSABLE = "SOURCE_DATE_UNPARSABLE"
CODE_SOURCE_DATE_MISMATCH = "SOURCE_DATE_MISMATCH"
CODE_SOURCE_AMOUNT_MISMATCH = "SOURCE_AMOUNT_MISMATCH"
CODE_EXPORT_BINDING_MISMATCH = "EXPORT_BINDING_MISMATCH"
CODE_DECISION_SHAPE_INVALID = "DECISION_SHAPE_INVALID"
CODE_DECISION_DUPLICATE_REF = "DECISION_DUPLICATE_REF"
CODE_DECISION_UNKNOWN_REF = "DECISION_UNKNOWN_REF"
CODE_DECISION_VALUE_INVALID = "DECISION_VALUE_INVALID"
CODE_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
CODE_INTERNAL_ERROR = "INTERNAL_ERROR"

# Adapter codes are passed through unchanged: they are already a fixed,
# value-free vocabulary owned by the accepted adapter.
_ADAPTER_CODES = frozenset({
    "MISSING_COLUMN", "INVALID_SCHEMA_VERSION", "INVALID_SHA256",
    "SNAPSHOT_SHA_MISMATCH", "DUPLICATE_SOURCE_REF", "INVALID_CANDIDATE_COUNT",
    "INVALID_CANDIDATE_KEYS_JSON", "CANDIDATE_COUNT_MISMATCH",
    "INVALID_DISPOSITION", "INVALID_REVIEW_DECISION", "APPROVAL_NOT_ALLOWED",
    "APPROVED_KEY_NOT_FOUND", "APPROVED_KEY_DUPLICATED", "DUPLICATE_HEADER",
    "UNEXPECTED_COLUMN", "ROW_LENGTH_MISMATCH", "MALFORMED_CSV",
    "INVALID_SOURCE_REF",
})

_HEX64_RE = re.compile(r"\A[0-9a-fA-F]{64}\Z")
_REF_RE = re.compile(
    r"\A(?P<sheet>[^!\[\]]+)"
    r"!(?P<date>\$?[A-Za-z]{1,3}\$?[0-9]{1,7})"
    r"\|(?P<amount>\$?[A-Za-z]{1,3}\$?[0-9]{1,7})"
    r" \(row (?P<row>[0-9]{1,9})\)\Z"
)
_CELL_RE = re.compile(r"\A\$?(?P<col>[A-Za-z]{1,3})\$?(?P<row>[0-9]{1,9})\Z")

# The expense block header labels, in block order. The amount label is
# checked separately so a real 원 suffix in the actual header is tolerated.
SOURCE_BLOCK_LABELS = (
    "거래일자", "항목", "내용", "기간", "예약번호", "증빙유형",
)
# The income block header, in block order. A separate constant rather than an
# extension of the expense one: the two blocks are not variants of each other,
# and a header that belongs to one must never label the other. Reading an income
# row as an expense row is what turns a deposit into a card charge.
INCOME_BLOCK_LABELS = (
    "거래일자", "이름", "닉네임", "예약금", "잔금", "추가금",
)
AMOUNT_LABEL = "금액"
SOURCE_BLOCK_WIDTHS = (7, 8)

#: What a block turned out to be. `unknown` is a real answer and the safe one:
#: a header matching neither block must not be forced into one.
BLOCK_INCOME = "income"
BLOCK_EXPENSE = "expense"
BLOCK_UNKNOWN = "unknown"

MASTER_HEADERS = (
    "거래키", "카드사", "카드4", "구분", "승인일", "매입일", "가맹점",
    "원화금액", "현지금액", "통화", "승인번호", "취소여부", "출처",
    "적재일", "기록여부", "워크북참조", "비고",
)

MERCHANT_ABSENT = "없음"
EVIDENCE_AVAILABLE = "available"
EVIDENCE_INSUFFICIENT = "insufficient"

_BLANK = " "


class ReviewContextError(Exception):
    """A refusal already reduced to a fixed, value-free code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = code


def _fail(code: str) -> "ReviewContextError":
    return ReviewContextError(code)


# ------------------------------------------------------------ small helpers

def _is_hex64(value: object) -> bool:
    return type(value) is str and _HEX64_RE.match(value) is not None


def _is_str(value: object) -> bool:
    return type(value) is str


def _display(value: object) -> str:
    """Render a cell as a display string, preserving the original text.

    No leading-formula escape is applied: source notes and values reach the
    operator exactly as the workbook holds them, and the browser renders
    every dynamic string through ``textContent``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.date().isoformat()
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        text = repr(value)
        if text.endswith(".0"):
            return text[:-2]
        return text
    return str(value)


def _label_of(value: object) -> str:
    """Header cell text, whitespace-trimmed only, otherwise byte-for-byte."""
    return _display(value).strip()


def _col_index(letters: str) -> int:
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - 64)
    return index


def _amount_label_ok(label: str) -> bool:
    """True for the real amount header, tolerating an explicit 원 suffix."""
    if not label.startswith(AMOUNT_LABEL):
        return False
    rest = label[len(AMOUNT_LABEL):].strip().strip("()（）").strip()
    return rest in ("", "원")


_DATE_PATTERNS = (
    re.compile(r"\A(?P<y>\d{4})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})\Z"),
    re.compile(r"\A(?P<y>\d{4})년\s*(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일?\Z"),
    re.compile(r"\A(?P<y>\d{4})\s*(?P<m>\d{1,2})\s*(?P<d>\d{1,2})\Z"),
    re.compile(r"\A(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})\Z"),
)


def _parse_explicit_date(value: object) -> str | None:
    """ISO date from a value that carries an explicit four-digit year.

    Returns None when no explicit year is present. There is deliberately no
    year inference: a bare ``4/1`` is never turned into a date.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if type(value) is not str:
        return None
    text = value.strip()
    if text == "":
        return None
    for pattern in _DATE_PATTERNS:
        found = pattern.match(text)
        if found is None:
            continue
        year = int(found.group("y"), 10)
        month = int(found.group("m"), 10)
        day = int(found.group("d"), 10)
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            return None
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    return None


def _parse_amount(value: object) -> Decimal | None:
    """Exact Decimal for a numeric or plainly numeric cell, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, Decimal)):
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return None
    if isinstance(value, float):
        try:
            return Decimal(repr(value))
        except (InvalidOperation, ValueError):
            return None
    if type(value) is not str:
        return None
    text = value.strip().replace(",", "").replace("₩", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1].strip()
    if text == "":
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


# ------------------------------------------------------------- CSV read side

def _read_csv_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """Header and data rows with a leading BOM removed, values untouched."""
    if text.startswith("\ufeff"):
        text = text[1:]
    if text == "":
        raise _fail(CODE_INVALID_MASTER_CSV)
    try:
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except Exception:
        raise _fail(CODE_INVALID_MASTER_CSV) from None
    if not rows:
        raise _fail(CODE_INVALID_MASTER_CSV)
    return rows[0], rows[1:]


def _manifest_index(review_csv_text: str) -> dict[str, dict[str, str]]:
    """Per-ref manifest context, read without touching any other field.

    This is a read-only companion to the adapter: the adapter owns validity,
    this index only carries the ``source_date`` / ``source_amount`` /
    ``reviewer_decision`` strings the adapter deliberately does not return.
    """
    header, data = _read_csv_rows(review_csv_text)
    index: dict[str, dict[str, str]] = {}
    for row in data:
        if len(row) != len(header):
            raise _fail(CODE_REVIEW_CSV_INVALID)
        record = dict(zip(header, row))
        ref = record.get("source_ref_snapshot_only", "")
        if ref in index:
            raise _fail(CODE_REVIEW_CSV_INVALID)
        index[ref] = record
    return index


def _parse_master(master_csv_text: str) -> dict[str, dict]:
    """Exact 거래키 index over the master CSV. Duplicate keys fail closed."""
    header, data = _read_csv_rows(master_csv_text)
    if len(set(header)) != len(header):
        raise _fail(CODE_INVALID_MASTER_CSV)
    if sorted(header) != sorted(MASTER_HEADERS):
        raise _fail(CODE_INVALID_MASTER_CSV)
    index: dict[str, dict] = {}
    for position, row in enumerate(data, start=2):
        if len(row) != len(header):
            raise _fail(CODE_INVALID_MASTER_CSV)
        if all(cell.strip() == "" for cell in row):
            continue
        record = dict(zip(header, row))
        key = record["거래키"]
        if key.strip() == "":
            raise _fail(CODE_INVALID_MASTER_CSV)
        if key in index:
            raise _fail(CODE_DUPLICATE_MASTER_KEY)
        record["_row"] = position
        index[key] = record
    return index


# ------------------------------------------------------------- source blocks

class _SourceRef:
    __slots__ = ("sheet", "date_col", "date_row", "amount_col", "amount_row",
                 "row", "text")

    def __init__(self, sheet, date_col, date_row, amount_col, amount_row, row,
                 text):
        self.sheet = sheet
        self.date_col = date_col
        self.date_row = date_row
        self.amount_col = amount_col
        self.amount_row = amount_row
        self.row = row
        self.text = text


def _parse_source_ref(ref: str) -> _SourceRef:
    found = _REF_RE.match(ref)
    if found is None:
        raise _fail(CODE_INVALID_SOURCE_REF)
    date_cell = _CELL_RE.match(found.group("date"))
    amount_cell = _CELL_RE.match(found.group("amount"))
    if date_cell is None or amount_cell is None:
        raise _fail(CODE_INVALID_SOURCE_REF)
    date_col = _col_index(date_cell.group("col"))
    amount_col = _col_index(amount_cell.group("col"))
    date_row = int(date_cell.group("row"), 10)
    amount_row = int(amount_cell.group("row"), 10)
    row = int(found.group("row"), 10)
    if date_row != amount_row or date_row != row or row < 1:
        raise _fail(CODE_SOURCE_ROW_MISMATCH)
    if date_col >= amount_col:
        raise _fail(CODE_SOURCE_COLUMN_ORDER)
    return _SourceRef(found.group("sheet"), date_col, date_row, amount_col,
                      amount_row, row, ref)


def _block_labels_match(labels: dict[int, str], block: tuple, amount_col: int,
                        date_col: int) -> bool:
    """Whether `labels` is exactly `block` in block order, at this width.

    The amount label is checked by the caller. Every remaining column must be one
    of the block's own labels in order, and exactly one column may be left over
    at width 8 — the same rule both blocks have always had.
    """
    expected = list(block[1:])
    cursor = date_col + 1
    for name in expected:
        while cursor < amount_col and labels[cursor] != name:
            cursor += 1
        if cursor >= amount_col:
            return False
        cursor += 1
    unlabelled = [
        column for column in range(date_col, amount_col + 1)
        if labels[column] not in block and not _amount_label_ok(labels[column])
    ]
    if (amount_col - date_col + 1) == 7:
        return not unlabelled
    return len(unlabelled) == 1


def _resolve_header(sheet, source: _SourceRef) -> tuple[dict[int, str] | None, str]:
    """The nearest valid header row, and which block it turned out to be.

    Returns ``(None, BLOCK_UNKNOWN)`` when no valid header exists above the source
    row, when the nearest header-like row is not a valid header for this block
    width, or when more than one column is left unlabelled. Transaction rows are
    never treated as headers and are skipped while searching upward for the
    nearest valid header in the same exact column range. Neither block's header
    ever labels the other, and the scan never walks past an invalid header-like
    row to an older header.

    The kind is decided by which header actually matched, inside the same exact
    column range the expense path always used. Nothing is inferred from the sheet
    name, the amount's sign or where the row sits — a header that matches neither
    block is `unknown`, which is the answer that keeps it out of card matching
    rather than the one that forces it into a block.
    """
    width = source.amount_col - source.date_col + 1
    if width not in SOURCE_BLOCK_WIDTHS:
        raise _fail(CODE_SOURCE_BLOCK_WIDTH_UNSUPPORTED)

    for header_row in range(source.row - 1, 0, -1):
        labels = {
            column: _label_of(sheet.cell(row=header_row, column=column).value)
            for column in range(source.date_col, source.amount_col + 1)
        }
        if not any(labels.values()):
            continue

        # A transaction row carries an explicit date at the block start and
        # an exact amount at the block end. Such rows are data, never header
        # candidates, so the scan continues upward to the block header.
        date_raw = sheet.cell(row=header_row, column=source.date_col).value
        amount_raw = sheet.cell(row=header_row, column=source.amount_col).value
        if _parse_explicit_date(date_raw) is not None \
                and _parse_amount(amount_raw) is not None:
            continue

        if labels[source.date_col] not in (SOURCE_BLOCK_LABELS[0],
                                           INCOME_BLOCK_LABELS[0]):
            return None, BLOCK_UNKNOWN
        if not _amount_label_ok(labels[source.amount_col]):
            return None, BLOCK_UNKNOWN

        for block, kind in ((SOURCE_BLOCK_LABELS, BLOCK_EXPENSE),
                            (INCOME_BLOCK_LABELS, BLOCK_INCOME)):
            if _block_labels_match(labels, block, source.amount_col,
                                   source.date_col):
                return labels, kind
        return None, BLOCK_UNKNOWN
    return None, BLOCK_UNKNOWN


def _field_cells(sheet, source: _SourceRef, labels: dict[int, str] | None
                 ) -> list[dict]:
    """Every column of the block, in block order, with its address.

    With a valid header each cell carries that header's own label. Without
    one, the address and the raw value are still shown with an empty label
    and the row is reported insufficient. An extra width-8 column keeps its
    raw header text and is never named.
    """
    cells: list[dict] = []
    for column in range(source.date_col, source.amount_col + 1):
        label = labels.get(column, "") if labels else ""
        cells.append({
            "address": f"{_col_letters(column)}{source.row}",
            "label": label,
            "value": _display(sheet.cell(row=source.row, column=column).value),
        })
    return cells


def _col_letters(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _labelled(cells: list[dict], name: str) -> str:
    for cell in cells:
        if cell["label"] == name:
            return cell["value"]
    return ""


def _build_source(workbook, ref: str, manifest: dict[str, str]) -> dict:
    source = _parse_source_ref(ref)
    if source.sheet not in workbook.sheetnames:
        raise _fail(CODE_SOURCE_SHEET_MISSING)
    target = workbook[source.sheet]

    date_value = target.cell(row=source.date_row, column=source.date_col).value
    amount_value = target.cell(row=source.amount_row,
                               column=source.amount_col).value
    if _display(date_value).strip() == "" or _display(amount_value).strip() == "":
        raise _fail(CODE_SOURCE_CELL_MISSING)

    parsed_date = _parse_explicit_date(date_value)
    if parsed_date is None:
        raise _fail(CODE_SOURCE_DATE_UNPARSABLE)
    manifest_date = _parse_explicit_date(manifest.get("source_date", ""))
    if manifest_date is None or manifest_date != parsed_date:
        raise _fail(CODE_SOURCE_DATE_MISMATCH)

    parsed_amount = _parse_amount(amount_value)
    if parsed_amount is None:
        raise _fail(CODE_SOURCE_AMOUNT_MISMATCH)
    manifest_amount = _parse_amount(manifest.get("source_amount", ""))
    if manifest_amount is None or manifest_amount != parsed_amount:
        raise _fail(CODE_SOURCE_AMOUNT_MISMATCH)

    labels, block_kind = _resolve_header(target, source)
    cells = _field_cells(target, source, labels)
    source_out = {
        "date": manifest.get("source_date", ""),
        "amount": manifest.get("source_amount", ""),
        "block_kind": block_kind,
        "fieldcells": cells,
        # The expense block carries no merchant column. 항목 is an item label
        # and an uninterpreted extra column stays uninterpreted, so there is
        # never a source merchant to show.
        "merchant": MERCHANT_ABSENT,
        "description": _labelled(cells, "내용") if labels else "",
        "sourceLocator": ref,
        "evidence_status": EVIDENCE_AVAILABLE if labels else EVIDENCE_INSUFFICIENT,
    }
    if block_kind == BLOCK_INCOME:
        # The income block names a person and splits a deposit into components.
        # Those are read out here, once, so every screen shows the same values
        # rather than re-reading the cells and getting a different answer.
        source_out["customer_name"] = _labelled(cells, "이름")
        source_out["nickname"] = _labelled(cells, "닉네임")
        source_out["income_components"] = {
            name: _labelled(cells, name)
            for name in ("예약금", "잔금", "추가금")
        }
    return source_out


# ----------------------------------------------------------- candidate rows

def _build_candidate(key: str, master: dict[str, dict]) -> dict:
    record = master.get(key)
    if record is None:
        raise _fail(CODE_CANDIDATE_KEY_UNRESOLVED)
    origin = record.get("출처", "").strip()
    locator = f"(row {record['_row']})"
    if origin:
        locator = f"{origin} {locator}"
    return {
        "key": key,
        "datefields": {
            "approval_date": record.get("승인일", ""),
            "posting_date": record.get("매입일", ""),
        },
        "amount": record.get("원화금액", ""),
        "merchant": record.get("가맹점", ""),
        # The master has no description column and 비고 is a remark, not a
        # description, so nothing is invented here.
        "description": "",
        "approval_number": record.get("승인번호", ""),
        "sourceLocator": locator,
        "pipeline_recorded": bool(
            record.get("\uae30\ub85d\uc5ec\ubd80", "").strip().upper() == "Y"
            and record.get("\uc6cc\ud06c\ubd81\ucc38\uc870", "").strip()
        ),
    }


def _attach_pipeline_recommendations(rows: list[dict]) -> None:
    """Attach conservative historical reconciliation recommendations only."""
    occurrences: dict[str, int] = {}
    eligible_by_row: list[list[str]] = []
    for row in rows:
        # A recommendation is a card to match against, so it only exists for a
        # card expense. Suggesting one for a deposit is the error this whole
        # change is about, and suggesting one for a row whose block could not be
        # identified is guessing. Both receive a null recommendation while their
        # original candidate keys remain unchanged.
        kind = (row.get("source") or {}).get("block_kind") or BLOCK_EXPENSE
        if kind != BLOCK_EXPENSE:
            eligible_by_row.append([])
            continue
        eligible = [
            candidate.get("key")
            for candidate in row.get("candidates", [])
            if candidate.get("pipeline_recorded") is True
            and type(candidate.get("key")) is str
            and candidate.get("key")
        ]
        eligible_by_row.append(eligible)
        for candidate_key in set(eligible):
            occurrences[candidate_key] = occurrences.get(candidate_key, 0) + 1

    for row, eligible in zip(rows, eligible_by_row):
        unique = [key for key in eligible if occurrences.get(key) == 1]
        row["pipeline_recommendation"] = (
            {"candidate_key": unique[0],
             "basis": "existing_reconciliation_unique"}
            if len(unique) == 1 else None
        )


# ------------------------------------------------------------------- public

def build_review_context(snapshot_bytes, review_csv_text, master_csv_text,
                         snapshot_sha256, review_sha256, master_sha256) -> dict:
    """Build the read-only review model for one sealed snapshot.

    Every failure raises :class:`ReviewContextError` with a fixed code.
    """
    if not _is_hex64(snapshot_sha256) or not _is_hex64(review_sha256) \
            or not _is_hex64(master_sha256):
        raise _fail(CODE_INVALID_SHA256)
    if not _is_str(review_csv_text) or not _is_str(master_csv_text):
        raise _fail(CODE_INVALID_ARGUMENT)
    if type(snapshot_bytes) is not bytes:
        raise _fail(CODE_INVALID_ARGUMENT)

    if sha256_bytes(snapshot_bytes) != snapshot_sha256:
        raise _fail(CODE_SNAPSHOT_HASH_MISMATCH)
    if sha256_text(review_csv_text) != review_sha256:
        raise _fail(CODE_REVIEW_HASH_MISMATCH)
    if sha256_text(master_csv_text) != master_sha256:
        raise _fail(CODE_MASTER_HASH_MISMATCH)

    try:
        normalized = normalize_review_csv(review_csv_text, snapshot_sha256)
    except Exception as exc:
        code = getattr(exc, "code", None)
        if _is_str(code) and code in _ADAPTER_CODES:
            raise _fail(code) from None
        raise _fail(CODE_INTERNAL_ERROR) from None

    manifest = _manifest_index(review_csv_text)
    master = _parse_master(master_csv_text)

    try:
        from openpyxl import load_workbook
    except Exception:
        raise _fail(CODE_INVALID_SNAPSHOT_WORKBOOK) from None
    try:
        workbook = load_workbook(io.BytesIO(snapshot_bytes), data_only=True,
                                 read_only=False)
    except Exception:
        raise _fail(CODE_INVALID_SNAPSHOT_WORKBOOK) from None

    rows: list[dict] = []
    try:
        for review_row in normalized["review_rows"]:
            ref = review_row["source_ref_snapshot_only"]
            record = manifest.get(ref)
            if record is None:
                raise _fail(CODE_REVIEW_CSV_INVALID)
            candidates = [
                _build_candidate(key, master)
                for key in review_row["candidate_transaction_keys"]
            ]
            rows.append({
                "ref": ref,
                "source": _build_source(workbook, ref, record),
                "candidates": candidates,
                # The original decision is carried through untouched. A blank
                # decision stays blank and is never promoted here.
                "decision": record.get("reviewer_decision", ""),
            })
    finally:
        try:
            workbook.close()
        except Exception:
            pass

    _attach_pipeline_recommendations(rows)

    return {
        "snapshotsha": snapshot_sha256,
        "reviewsha": review_sha256,
        "mastersha": master_sha256,
        "rows": rows,
    }


# ------------------------------------------------------------------- export

# The plan view below mirrors the allowlist the existing CLI
# tools/build_reviewed_import_plan_from_csv.py already publishes. It adds no
# planner semantics; the test suite pins the two shapes together.
_ELIGIBLE_FIELDS = (
    "source_ref_snapshot_only",
    "review_snapshot_sha256",
    "chosen_candidate_key",
    "candidate_transaction_keys",
    "plan_id",
)
_REFUSED_FIELDS = (
    "source_ref_snapshot_only",
    "disposition",
    "reason_code",
    "review_snapshot_sha256",
    "approved",
    "chosen_candidate_key",
    "candidate_fingerprint",
    "candidate_count",
)
_PLAN_COUNT_FIELDS = ("eligible", "refused", "total")
_EXPORT_COUNT_FIELDS = ("approved", "rejected", "incomplete")
_DECISION_FIELDS = frozenset({"ref", "value"})


def _reviewed_plan_view(plan: dict) -> dict:
    eligible = [
        {name: entry.get(name) for name in _ELIGIBLE_FIELDS}
        for entry in plan.get("eligible") or []
    ]
    refused = [
        {name: entry.get(name) for name in _REFUSED_FIELDS}
        for entry in plan.get("refused") or []
    ]
    counts = {name: (plan.get("counts") or {}).get(name)
              for name in _PLAN_COUNT_FIELDS}
    return {"eligible": eligible, "refused": refused, "counts": counts}


def _verify_model_binding(model: dict, original_review_csv_text: str) -> None:
    """The model must still describe exactly this text, refs and candidates."""
    if type(model) is not dict or type(original_review_csv_text) is not str:
        raise _fail(CODE_INVALID_ARGUMENT)
    snapshot_sha256 = model.get("snapshotsha")
    if not _is_hex64(snapshot_sha256):
        raise _fail(CODE_EXPORT_BINDING_MISMATCH)
    if model.get("reviewsha") != sha256_text(original_review_csv_text):
        raise _fail(CODE_EXPORT_BINDING_MISMATCH)
    if _is_str(model.get("mastersha")) and \
            not _is_hex64(model["mastersha"]):
        raise _fail(CODE_EXPORT_BINDING_MISMATCH)

    try:
        normalized = normalize_review_csv(original_review_csv_text,
                                          snapshot_sha256)
    except Exception:
        raise _fail(CODE_EXPORT_BINDING_MISMATCH) from None
    manifest = _manifest_index(original_review_csv_text)

    rows = model.get("rows")
    if type(rows) is not list or len(rows) != len(normalized["review_rows"]):
        raise _fail(CODE_EXPORT_BINDING_MISMATCH)

    expected = {row["source_ref_snapshot_only"]: row
                for row in normalized["review_rows"]}
    if len(expected) != len(rows):
        raise _fail(CODE_EXPORT_BINDING_MISMATCH)
    for row in rows:
        if type(row) is not dict:
            raise _fail(CODE_EXPORT_BINDING_MISMATCH)
        ref = row.get("ref")
        if ref not in expected:
            raise _fail(CODE_EXPORT_BINDING_MISMATCH)
        source = row.get("source")
        candidates = row.get("candidates")
        if type(source) is not dict or type(candidates) is not list:
            raise _fail(CODE_EXPORT_BINDING_MISMATCH)
        record = manifest[ref]
        if source.get("sourceLocator") != ref:
            raise _fail(CODE_EXPORT_BINDING_MISMATCH)
        if source.get("date") != record.get("source_date", "") or \
                source.get("amount") != record.get("source_amount", ""):
            raise _fail(CODE_EXPORT_BINDING_MISMATCH)
        if [item.get("key") for item in candidates] != \
                list(expected[ref]["candidate_transaction_keys"]):
            raise _fail(CODE_EXPORT_BINDING_MISMATCH)


def _normalize_decisions(decisions, rows: list[dict]) -> dict[str, str]:
    """Validate the submitted decisions; omitted rows keep the original value."""
    by_ref = {row["ref"]: row for row in rows}
    if decisions is None:
        decisions = []
    if type(decisions) is not list:
        raise _fail(CODE_DECISION_SHAPE_INVALID)

    resolved: dict[str, str] = {}
    for entry in decisions:
        if type(entry) is not dict or set(entry) != _DECISION_FIELDS:
            raise _fail(CODE_DECISION_SHAPE_INVALID)
        ref = entry["ref"]
        value = entry["value"]
        if not _is_str(ref) or not _is_str(value):
            raise _fail(CODE_DECISION_SHAPE_INVALID)
        if ref not in by_ref:
            raise _fail(CODE_DECISION_UNKNOWN_REF)
        if ref in resolved:
            raise _fail(CODE_DECISION_DUPLICATE_REF)
        if value == "" or value == "REJECT":
            resolved[ref] = value
            continue
        if not value.startswith("APPROVE:") or value[len("APPROVE:"):] == "":
            raise _fail(CODE_DECISION_VALUE_INVALID)
        key = value[len("APPROVE:"):]
        row = by_ref[ref]
        # An income row is refused an approval outright, before evidence or
        # candidates are consulted. The card hides these controls, but a hidden
        # control is a convenience and this is the decision: a deposit approved
        # as a card charge is the exact harm this refuses to record. `REJECT` and
        # a blank stay allowed above, so a row from before the block kind existed
        # is unaffected.
        if (row["source"].get("block_kind") or BLOCK_EXPENSE) == BLOCK_INCOME:
            raise _fail(CODE_DECISION_VALUE_INVALID)
        if row["source"].get("evidence_status") != EVIDENCE_AVAILABLE:
            raise _fail(CODE_INSUFFICIENT_EVIDENCE)
        if not row["candidates"]:
            raise _fail(CODE_INSUFFICIENT_EVIDENCE)
        if key not in [item["key"] for item in row["candidates"]]:
            raise _fail(CODE_DECISION_VALUE_INVALID)
        resolved[ref] = value
    return resolved


def _render_decision_csv(original_review_csv_text: str,
                         decisions: dict[str, str]) -> str:
    """Copy the original CSV, changing only reviewer_decision.

    Every other field is written back exactly as parsed, with QUOTE_ALL and
    LF record terminators. A CR, CRLF or LF inside a quoted field stays
    field data, and a leading BOM in the original is kept so the copy is
    byte-comparable with its input.
    """
    had_bom = original_review_csv_text.startswith("\ufeff")
    body = original_review_csv_text[1:] if had_bom else original_review_csv_text
    try:
        rows = list(csv.reader(io.StringIO(body), strict=True))
    except Exception:
        raise _fail(CODE_EXPORT_BINDING_MISMATCH) from None
    if not rows:
        raise _fail(CODE_EXPORT_BINDING_MISMATCH)
    header = rows[0]
    if "reviewer_decision" not in header or "source_ref_snapshot_only" not in header:
        raise _fail(CODE_EXPORT_BINDING_MISMATCH)
    ref_column = header.index("source_ref_snapshot_only")
    decision_column = header.index("reviewer_decision")

    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(header)
    for row in rows[1:]:
        if len(row) != len(header):
            raise _fail(CODE_EXPORT_BINDING_MISMATCH)
        if row[ref_column] in decisions:
            row[decision_column] = decisions[row[ref_column]]
        writer.writerow(row)
    text = buffer.getvalue()
    if had_bom:
        text = "\ufeff" + text
    return text


def build_review_export(model, original_review_csv_text, decisions) -> dict:
    """Apply decisions to a copy of the original CSV and build the plan.

    The adapter and the pure planner own every rule: this function only
    re-emits the CSV with the chosen decisions, then runs the accepted
    normalize-then-plan flow unchanged. Nothing is written to disk.
    """
    _verify_model_binding(model, original_review_csv_text)
    rows = model["rows"]
    submitted = _normalize_decisions(decisions, rows)
    decision_csv = _render_decision_csv(original_review_csv_text, submitted)

    snapshot_sha256 = model["snapshotsha"]
    try:
        normalized = normalize_review_csv(decision_csv, snapshot_sha256)
    except Exception as exc:
        code = getattr(exc, "code", None)
        if _is_str(code) and code in _ADAPTER_CODES:
            raise _fail(code) from None
        raise _fail(CODE_INTERNAL_ERROR) from None

    plan = build_reviewed_import_plan(snapshot_sha256,
                                      list(normalized["review_rows"]))
    if type(plan) is not dict:
        raise _fail(CODE_INTERNAL_ERROR)

    counts = normalized["counts"]
    return {
        "decision_csv": decision_csv,
        "plan_json": {
            "counts": {name: counts.get(name, 0) for name in _EXPORT_COUNT_FIELDS},
            "plan_digest": plan.get("plan_digest"),
            "reviewed_plan": _reviewed_plan_view(plan),
            "snapshot_sha256": plan.get("snapshot_sha256"),
        },
        "counts": {name: counts.get(name, 0) for name in _EXPORT_COUNT_FIELDS},
        "plan_digest": plan.get("plan_digest"),
    }
