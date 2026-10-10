# -*- coding: utf-8 -*-
"""Read one uploaded card file.

Nothing here depends on the filename. The same upload can arrive as `F.xlsx`,
`E.xlsx`, `card_2026-04.csv` or a browser-generated name, and the parser is
driven by what the file says about itself: the headers, or the row shape when a
corporate export has no headers at all.

Three formats are supported:

* a domestic card sheet with Korean headers (승인번호, 가맹점, 승인일, ...),
* a foreign card sheet with English headers (Authorization Code, Merchant, ...),
* a headerless corporate export, matched on column count and on a row whose
  date, merchant and amount cells all land where the profile says they should.

Every parse returns the original row and its original cells untouched in
`raw_row_json`. The normalized fields are derived *beside* the original, never
instead of it.

A file is parsed once. `parse_card_file` caches on the exact bytes, so calling
it twice with the same upload returns the same object and does the work once.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field

from openpyxl import load_workbook

from .normalize import (AmountUnreadable, is_cancel_text, normalize_merchant,
                         to_amount_krw, to_currency_text, to_date, to_decimal)

__all__ = ["ParsedFile", "ParsedRow", "ParseError", "parse_card_file", "read_cells"]

# Header aliases. The left side is what this pipeline calls a field; the right
# side is every spelling a card issuer has been observed to use for it. A field
# is only satisfied when one of these is present *as a header*, so a merchant
# that happens to contain the word "일자" cannot become a date.
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "approval_number": ("승인번호", "승인번호(일자)", "거래승인번호", "approvalno",
                        "authorizationcode", "authorizationno", "authcode"),
    "original_approval_number": ("원승인번호", "원거래승인번호", "취소원승인번호",
                                 "originalapprovalno", "originalauthorization"),
    "approval_date": ("승인일", "승인일자", "사용일", "이용일", "거래일", "approvaldate",
                      "transactiondate", "date"),
    "posting_date": ("매입일", "매입일자", "정산일", "posteddate", "postdate",
                     "settlementdate"),
    "merchant": ("가맹점", "가맹점명", "가맹점명(가맹점)", "사용처", "merchant",
                 "merchantname", "description"),
    "merchant_category": ('업종명', '업종', 'merchantcategory'),
    "amount": ("이용금액", "승인금액", "금액", "원화금액", "승인원화금액",
               "amount", "transactionamount", "amountkrw"),
    "foreign_amount": ("외화금액", "현지이용금액", "현지금액", "외화금액(원화제외)", "foreignamount", "localamount"),
    "foreign_currency": ("외화코드", "통화코드", "통화", "currency", "currencycode"),
    "krw_amount": ("원화금액", "원화금액(원)", "krwamount", "amountkrw",
                   "amountinkrw", "총결제금액"),
    "card_company": ("카드사", "카드사명", "카드사코드", "issuer", "cardcompany",
                     "cardissuer"),
    "card_mask": ("카드번호", "카드번호(마스킹)", "카드", "카드뒤4자리",
                  "카드4", "카드번호뒤4자리", "cardno", "cardlast4", "maskedcardno"),
    "card_kind": ("카드종류", "카드구분", "카드유형", "cardtype", "cardkind"),
    "transaction_type": ("구분", "결제방법", "거래유형", "거래구분", "거래종류", "type",
                         "transactiontype", "typeoftransaction"),
    "status": ("상태", "처리상태", "비고", "status"),
}

# Headerless corporate export: (column count, profile name, required index map).
# Two of these profiles are checked in, because the two shapes actually seen in
# the reference sheets (F and E) differ in width. A file that matches neither is
# refused rather than read by guesswork.
FIXED_PROFILES = (
    {"name": "corp-a", "min_columns": 21,
     "required": {"date": 2, "card": 3, "merchant": 5, "type": 0,
                  "amount": 6, "approval_number": 13}},
    {"name": "corp-f", "min_columns": 17,
     "required": {"date": 1, "merchant": 7, "type": 8, "amount": 11,
                  "approval_number": 15}},
    {"name": "corp-e", "min_columns": 17,
     "required": {"date": 0, "card": 4, "merchant": 7, "type": 8,
                  "amount": 10, "approval_number": 15}},
)


class ParseError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass
class ParsedRow:
    """One normalized transaction, with its original row still attached."""
    row_index: int
    source_row: list
    raw: dict
    issuer: str = ""
    card_tail: str = ""
    card_kind: str = ""
    transaction_direction: str = "purchase"
    transaction_kind: str = ""
    approval_number: str = ""
    original_approval_number: str = ""
    approval_date: str = ""
    posting_date: str = ""
    merchant: str = ""
    amount_krw: int | None = None
    foreign_amount: str = ""
    foreign_currency: str = ""
    description_raw: str = ""
    parse_error: str = ""

    @property
    def merchant_normalized(self) -> str:
        return normalize_merchant(self.merchant)

    def as_dict(self) -> dict:
        return {
            "row_index": self.row_index,
            "issuer": self.issuer,
            "card_tail": self.card_tail,
            "card_kind": self.card_kind,
            "transaction_direction": self.transaction_direction,
            "transaction_kind": self.transaction_kind,
            "approval_number": self.approval_number,
            "original_approval_number": self.original_approval_number,
            "approval_date": self.approval_date,
            "posting_date": self.posting_date,
            "merchant": self.merchant,
            "merchant_normalized": self.merchant_normalized,
            "amount_krw": self.amount_krw,
            "foreign_amount": self.foreign_amount,
            "foreign_currency": self.foreign_currency,
            "description_raw": self.description_raw,
            "parse_error": self.parse_error,
            "raw_row": self.source_row,
        }


@dataclass
class ParsedFile:
    filename: str
    parser: str
    headers: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    # approval | domestic_acquired | overseas_acquired | statement
    channel: str = ""

    @property
    def ok_rows(self) -> list:
        return [r for r in self.rows if not r.parse_error]


# --------------------------------------------------------------- reading

def read_cells(content: bytes) -> tuple[str, list[list]]:
    """Return (format, rows-of-cells). The sheet is parsed exactly once."""
    if not content:
        raise ParseError("EMPTY_FILE", "빈 파일이에요")
    if content[:2] == b"PK":
        return "xlsx", _read_xlsx(content)
    if content[:8] == OLE2_MAGIC:
        return "xls", _read_xls(content)
    return "csv", _read_csv(content)


OLE2_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
# 카드사 매입 확정 파일에는 있고 승인(미확정) 파일에는 없는 열. 이 열이 없고 승인방식이 있으면
# 승인내역이다. 승인내역은 거래가 아니라 승인 증거로만 저장한다(`_parse_approval`).
POSTING_HEADERS = ("매입일", "매입일자", "정산일")


def _xls_value(cell):
    """xlrd gives every number as a float. 5400.0 is written 5400, as the same sheet saved as CSV would."""
    if cell == "":
        return None
    if isinstance(cell, float) and cell.is_integer() and abs(cell) < 1e15:
        return int(cell)
    return cell


def _read_xls(content: bytes) -> list[list]:
    """Read the first sheet of a binary .xls (BIFF) card export. Values keep their stored types."""
    try:
        import xlrd
    except ImportError:
        raise ParseError("XLS_READER_UNAVAILABLE",
                         "이 서버에는 XLS 읽기 모듈이 없어 .xls 파일을 열 수 없어요") from None
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
    except Exception:
        raise ParseError("UNREADABLE_FILE", "XLS 파일을 열 수 없어요") from None
    try:
        sheet = book.sheet_by_index(0)
        rows = [[_xls_value(cell) for cell in sheet.row_values(index)]
                for index in range(sheet.nrows)]
    finally:
        book.release_resources()
    return rows


def _read_xlsx(content: bytes) -> list[list]:
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 64 * 1024 * 1024:
                raise ParseError('TOO_LARGE', '엑셀 파일의 내부 자료가 너무 큽니다')
    except zipfile.BadZipFile:
        raise ParseError('UNREADABLE_FILE', '엑셀 파일을 열 수 없습니다') from None
    try:
        workbook = load_workbook(io.BytesIO(content), data_only=True,
                                 read_only=True)
    except Exception:
        raise ParseError("UNREADABLE_FILE", "엑셀 파일을 열 수 없어요") from None
    try:
        sheet = workbook[workbook.sheetnames[0]]
        return [[cell for cell in row]
                for row in sheet.iter_rows(values_only=True)]
    finally:
        try:
            workbook.close()
        except Exception:
            pass


def _read_csv(content: bytes) -> list[list]:
    for encoding in ("utf-8-sig", "cp949", "utf-16"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ParseError("UNREADABLE_ENCODING", "문자 인코딩을 알 수 없어요")
    reader = csv.reader(io.StringIO(text))
    return [list(row) for row in reader]


# ------------------------------------------------------------ header maps

def _norm_header(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _build_header_map(headers: list) -> dict[str, int]:
    """Field name -> column index, from the header row only."""
    lookup: dict[str, int] = {}
    for index, cell in enumerate(headers):
        key = _norm_header(cell)
        if not key:
            continue
        for field_name, aliases in HEADER_ALIASES.items():
            if field_name in lookup:
                continue
            if key in {_norm_header(a) for a in aliases}:
                lookup[field_name] = index
                break
    return lookup


def _detect_profile(cells: list[list]) -> str:
    """Which format this file is, from its content alone."""
    header_map = {}
    for values in cells[:20]:
        candidate = _build_header_map(values)
        if 'merchant' in candidate and 'approval_date' in candidate:
            header_map = candidate
            break
    has_merchant = "merchant" in header_map
    has_amount = "amount" in header_map or "foreign_amount" in header_map
    if has_merchant and (has_amount or "krw_amount" in header_map):
        return "foreign_headered" if "foreign_amount" in header_map else "headered"
    for cell in cells[:6]:
        if len(cell) >= 17 and not _is_header_row([cell]):
            for profile in FIXED_PROFILES:
                if _fixed_row_looks_valid(cell, profile):
                    return f"fixed:{profile['name']}"
    raise ParseError("UNKNOWN_FORMAT",
                     "카드 내역 형식을 알아볼 수 없어요. 헤더나 열 구성을 확인해 주세요")


def _fixed_row_looks_valid(cell: list, profile: dict) -> bool:
    """Does this row's shape match the profile?

    The date, merchant, amount and approval columns must all be readable in the
    places the profile claims. Requiring all four is what keeps a random wide
    sheet from being read as a card file.
    """
    try:
        if len(cell) < profile['min_columns']:
            return False
        if profile['name'] == 'corp-a' and str(cell[0] or '') not in ('매출', '취소또는할인', '승인', '취소'):
            return False
        if not to_date(cell[profile["required"]["date"]]):
            return False
        if not str(cell[profile["required"]["merchant"]] or "").strip():
            return False
        to_amount_krw(cell[profile["required"]["amount"]], "amount")
    except AmountUnreadable:
        return False
    return True


# -------------------------------------------------------------- normalizing

def _approval_parts(value) -> tuple[str, str]:
    """`12345(67890)` -> (`12345`, `67890`).

    The reference sheets pack the original approval into the same cell as
    parentheses. Splitting it here keeps the cancellation link without losing
    the approval the issuer actually used.
    """
    text = str(value or "").strip()
    match = re.match(r"^\s*(\d+)\s*\(\s*(\d+)\s*\)\s*$", text)
    if match:
        return match.group(1), '' if match.group(2) == '0' else match.group(2)
    return re.sub(r"\D", "", text), ""


def _card_tail(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-4:] if digits else ""


def _normalize_row(row: ParsedRow, cells: list, header_map: dict | None,
                  profile: dict | None) -> None:
    def cell(field_name: str):
        if header_map is not None:
            index = header_map.get(field_name)
            return cells[index] if index is not None and index < len(cells) else None
        return None

    if header_map is not None:
        row.issuer = str(cell("card_company") or "").strip()
        row.card_tail = _card_tail(cell("card_mask"))
        row.card_kind = str(cell("card_kind") or "").strip()
        approval, original = _approval_parts(cell("approval_number"))
        row.original_approval_number = (
            re.sub(r"\D", "", str(cell("original_approval_number") or ""))
            or original)
        row.approval_date = to_date(cell("approval_date"))
        row.posting_date = to_date(cell("posting_date")) or row.approval_date
        row.merchant = str(cell("merchant") or "").strip()
        kind_text = str(cell("transaction_type") or "").strip()
        status_text = str(cell("status") or "")
        foreign_amount = cell("foreign_amount")
        row.foreign_currency = to_currency_text(cell("foreign_currency"))
    else:
        need = profile["required"]
        row.approval_date = to_date(cells[need["date"]])
        row.posting_date = row.approval_date
        row.merchant = str(cells[need["merchant"]] or "").strip()
        approval, original = _approval_parts(cells[need["approval_number"]])
        row.original_approval_number = original
        kind_text = str(cells[need["type"]] or "").strip()
        status_text = str(cells[16] or "") if len(cells) > 16 else ""
        card_index = need.get("card")
        row.card_tail = _card_tail(cells[card_index]) if card_index is not None else ""
        row.issuer = '기업' if profile['name'] == 'corp-a' else ''
        if profile['name'] == 'corp-a':
            row.card_kind = '해외' if '해외' in str(cells[1]) else '국내'
            currency_text = str(cells[7] or '')
            currency = re.search(r'\b([A-Z]{3})\b', currency_text)
            row.foreign_currency = currency.group(1) if currency else ''
            if currency:
                row.foreign_amount = currency_text.split()[0]

    row.approval_number = approval
    row.transaction_kind = kind_text or ("취소" if is_cancel_text(status_text) else "")
    row.description_raw = str(cell("status") or "") if header_map is not None else status_text
    if header_map is not None and cell('merchant_category'):
        row.description_raw = 'card-category:' + str(cell('merchant_category')).strip()

    # A cancellation is stated by the transaction kind first and by a cancel
    # marker anywhere in the row second. Neither is inferred from the sign.
    cancelled = ("취소" in row.transaction_kind or is_cancel_text(status_text))
    row.transaction_direction = "cancellation" if cancelled else "purchase"

    # Amount: a won column is preferred over a general amount column, because a
    # foreign sheet's "Amount" holds the foreign figure and a decimal there is
    # not a won amount. First column that reads as an integer won amount wins;
    # if none does, the foreign figure is kept with its currency and the row is
    # marked unreadable rather than priced.
    candidates = []
    if header_map is not None:
        for name in ("krw_amount", "amount"):
            if name in header_map:
                candidates.append(cell(name))
    else:
        candidates.append(cells[profile["required"]["amount"]])
    errors: list[str] = []
    for candidate in candidates:
        if candidate in (None, ""):
            continue
        try:
            row.amount_krw = to_amount_krw(candidate, "amount")
            errors = []
            break
        except AmountUnreadable as exc:
            errors.append(str(exc))
    if header_map is not None and row.foreign_currency:
        try:
            value = to_decimal(cell("foreign_amount"), "foreign_amount")
            row.foreign_amount = format(value, "f")
        except AmountUnreadable:
            row.foreign_amount = ""
    if errors or row.amount_krw is None:
        row.amount_krw = None
        row.parse_error = "|".join(errors) if errors else "amount_missing"
    elif row.transaction_direction == 'cancellation':
        row.amount_krw = -abs(row.amount_krw)


# ------------------------------------------------------------ approvals

_APPROVAL_COLUMNS = {
    "approval_date": ("승인일", "승인일자"),
    "approval_time": ("승인시간",),
    "card": ("카드번호",),
    "merchant": ("가맹점명", "가맹점"),
    "amount": ("승인금액",),
    "scope": ("승인구분",),
    "method": ("승인방식",),
    "approval_number": ("승인번호",),
    "status": ("상태",),
}


def _approval_header_row(cells: list[list]):
    """Index of the header row when this sheet is an approval list, else None.

    An approval list has `승인방식` and `승인번호` and no posting-date column.
    """
    for index, values in enumerate(cells[:20]):
        names = {re.sub(r"\s+", "", str(v or "")) for v in values}
        if ("승인방식" in names and "승인번호" in names and "승인일" in names
                and not names.intersection(POSTING_HEADERS)):
            return index
    return None


def _approval_amount(value) -> tuple[int | None, str, str]:
    """(won, foreign amount, currency). `$12.30` and `-$4.00` are dollars, a plain number is won."""
    if isinstance(value, (int, float)):
        return int(round(value)), "", ""
    text = str(value or "").strip()
    match = re.fullmatch(r"(-?)\$\s*(-?)([\d,]+(?:\.\d+)?)", text)
    if match:
        sign = "-" if (match.group(1) or match.group(2)) else ""
        number = match.group(3).replace(",", "")
        return None, sign + number, "USD"
    return to_amount_krw(text, "amount"), "", ""


def _parse_approval(cells: list[list], header_index: int, fmt: str, filename: str) -> ParsedFile:
    names = [_norm_header(v) for v in cells[header_index]]
    column: dict[str, int] = {}
    for key, aliases in _APPROVAL_COLUMNS.items():
        for alias in aliases:
            if _norm_header(alias) in names:
                column[key] = names.index(_norm_header(alias))
                break
    missing = [k for k in ("approval_date", "card", "merchant", "amount", "approval_number", "status")
               if k not in column]
    if missing:
        raise ParseError("UNKNOWN_FORMAT", "승인내역 열을 알아볼 수 없어요: " + ", ".join(missing))
    rows: list[ParsedRow] = []
    issues: list[dict] = []
    for offset, values in enumerate(cells[header_index + 1:], start=header_index + 1):
        if not any(str(c or "").strip() for c in values):
            continue
        def at(key):
            index = column.get(key)
            return values[index] if index is not None and index < len(values) else None
        row = ParsedRow(row_index=offset + 1, source_row=list(values),
                        raw={f"c{i}": (None if v is None else str(v)) for i, v in enumerate(values)})
        row.issuer = "국민"
        row.card_tail = _card_tail(at("card"))
        row.card_kind = "해외" if str(at("scope") or "").startswith("해외") else "국내"
        row.approval_date = to_date(at("approval_date"))
        row.merchant = str(at("merchant") or "").strip()
        row.approval_number, _ = _approval_parts(at("approval_number"))
        status = str(at("status") or "").strip()
        cancelled = "취소" in status
        row.transaction_direction = "cancellation" if cancelled else "purchase"
        row.transaction_kind = "승인취소" if cancelled else "승인"
        row.description_raw = status
        try:
            won, foreign, currency = _approval_amount(at("amount"))
            row.amount_krw = won
            row.foreign_amount, row.foreign_currency = foreign, currency
            if row.card_kind == "국내" and won is None:
                row.parse_error = "amount_missing"
        except AmountUnreadable as exc:
            row.parse_error = str(exc)
        if not (row.approval_number and row.approval_date and row.card_tail):
            row.parse_error = row.parse_error or "approval_identity_missing"
        if row.parse_error:
            issues.append({"row_index": row.row_index, "error": row.parse_error})
        rows.append(row)
    time_index = column.get("approval_time")
    for row in rows:
        row.raw["_approval_time"] = str(row.source_row[time_index]) if time_index is not None             and time_index < len(row.source_row) and row.source_row[time_index] is not None else ""
        method = column.get("method")
        row.raw["_approval_method"] = str(row.source_row[method]) if method is not None             and method < len(row.source_row) and row.source_row[method] is not None else ""
    return ParsedFile(filename=filename, parser=f"{fmt}:approval", headers=list(cells[header_index]),
                      rows=rows, issues=issues, channel="approval")


# -------------------------------------------------------------- entrypoint

_CACHE: dict[str, ParsedFile] = {}


def parse_card_file(content: bytes, filename: str, *,
                    use_cache: bool = True) -> ParsedFile:
    """Parse one upload once and share the result.

    Cached on the exact bytes, so a second call for the same upload is free and
    returns the identical object. Different bytes never share a cache entry.
    """
    import hashlib

    digest = hashlib.sha256(content).hexdigest()
    if use_cache:
        cached = _CACHE.get(digest)
        if cached is not None:
            return cached
    fmt, cells = read_cells(content)
    approval_header = _approval_header_row(cells)
    if approval_header is not None:
        parsed = _parse_approval(cells, approval_header, fmt, filename)
        if use_cache:
            _CACHE[digest] = parsed
        return parsed
    kind = _detect_profile(cells)
    header_map = None
    profile = None
    start = 1
    if kind.startswith("fixed:"):
        profile = next(p for p in FIXED_PROFILES
                       if p["name"] == kind.split(":", 1)[1])
        start = 0  # no header row in a headerless export
    else:
        start = next(i for i, values in enumerate(cells[:20])
                     if 'merchant' in _build_header_map(values)
                     and 'approval_date' in _build_header_map(values)) + 1
        header_map = _build_header_map(cells[start-1])

    header_names = {_norm_header(v) for v in cells[start-1]} if header_map else set()
    han = '승인취소금액' in header_names and '매입금액' in header_names
    if han:
        from ledger.domain.han_normalizer import validate_han_header, parse_han_amounts, normalize_han_components, is_han_transaction
        han_columns = validate_han_header(cells[start-1])

    rows: list[ParsedRow] = []
    issues: list[dict] = []
    for offset, cells_row in enumerate(cells[start:], start=start):
        if not any(str(c or "").strip() for c in cells_row):
            continue  # a blank spacer row is not a transaction
        row = ParsedRow(row_index=offset + 1, source_row=list(cells_row),
                        raw={f"c{i}": (None if v is None else str(v))
                             for i, v in enumerate(cells_row)})
        _normalize_row(row, cells_row, header_map, profile)
        if header_map and not row.issuer:
            row.issuer = '하나' if han else ('국민' if '부서번호' in header_names else '')
        if not row.card_kind:
            row.card_kind = '해외' if (row.foreign_currency and row.foreign_currency != 'KRW') else '국내'
        if han:
            if not row.card_tail and not row.approval_number:
                continue
            try:
                amounts = parse_han_amounts(cells_row, han_columns)
                is_han_transaction(amounts, identity_present=True)
                components = normalize_han_components(amounts)
                from dataclasses import replace
                for component in components:
                    if not component.signed_amount_krw:
                        continue
                    rows.append(replace(row, amount_krw=component.signed_amount_krw,
                                transaction_direction=component.transaction_type,
                                transaction_kind=component.transaction_type,
                                original_approval_number=row.approval_number if component.role == 'cancellation' else '',
                                parse_error=''))
                continue
            except ValueError as exc:
                row.amount_krw = None
                row.parse_error = str(exc)
        if row.parse_error:
            issues.append({"row_index": row.row_index, "error": row.parse_error})
        rows.append(row)

    channel = ("overseas_acquired" if kind == "foreign_headered"
               else "domestic_acquired" if kind == "headered" else "statement")
    parsed = ParsedFile(filename=filename, parser=f"{fmt}:{kind}",
                        headers=list(cells[0]) if header_map is not None else [],
                        rows=rows, issues=issues, channel=channel)
    if use_cache:
        _CACHE[digest] = parsed
    return parsed


def _is_header_row(cells: list) -> bool:
    """A header row is text only; a data row has a date or an amount in it."""
    if not cells:
        return False
    if to_date(cells[0]) or to_date(cells[1] if len(cells) > 1 else ""):
        return False
    return bool(_build_header_map(cells))


def dump_rows(parsed: ParsedFile) -> str:
    """Stable JSON of the parse, used for the raw preservation check."""
    return json.dumps([r.as_dict() for r in parsed.rows], ensure_ascii=False,
                      sort_keys=True)
