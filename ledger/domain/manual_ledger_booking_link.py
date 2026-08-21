"""Conservative linkage from manual-ledger reservation numbers to card rows."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from openpyxl import load_workbook

from ledger.domain.result_selection_rules import normalize_merchant_name


@dataclass(frozen=True)
class ManualBookingRow:
    target: str
    occurred_on: date | None
    merchant: str
    content: str
    period: str
    booking_number: str
    evidence: str
    amount_krw: int | None
    sheet_name: str
    source_row: int


def _parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%y-%m-%d", "%y.%m.%d", "%Y/%m/%d", "%y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _parse_amount(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    text = str(value).replace(",", "").strip()
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def canonical_target(sheet_name: str) -> str:
    return re.sub(r"\s+\([12]\)$", "", str(sheet_name).strip())


def load_manual_expense_rows(path: Path) -> list[ManualBookingRow]:
    """Load all user-facing expense rows, including rows without bookings.

    The row type keeps its historical name for compatibility with the booking
    linker.  Rows without a reservation number are intentionally retained here
    because display-only hints (for example an airline passenger name) may
    exist without an OTA booking number.
    """

    workbook = load_workbook(path, read_only=False, data_only=True)
    result: list[ManualBookingRow] = []
    try:
        for sheet in workbook.worksheets:
            expense_row = None
            for row in sheet.iter_rows():
                if any(cell.value == "지출 내용" for cell in row):
                    expense_row = row[0].row
                    break
            if expense_row is None:
                continue
            headers = tuple(sheet.cell(expense_row + 1, column).value for column in range(2, 9))
            if headers != ("거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)"):
                continue
            target = canonical_target(sheet.title)
            for row_number in range(expense_row + 2, sheet.max_row + 1):
                if sheet.cell(row_number, 2).value == "총 금액 (B)":
                    break
                booking_number = str(sheet.cell(row_number, 6).value or "").strip()
                result.append(
                    ManualBookingRow(
                        target=target,
                        occurred_on=_parse_date(sheet.cell(row_number, 2).value),
                        merchant=str(sheet.cell(row_number, 3).value or "").strip(),
                        content=str(sheet.cell(row_number, 4).value or "").strip(),
                        period=str(sheet.cell(row_number, 5).value or "").strip(),
                        booking_number=booking_number,
                        evidence=str(sheet.cell(row_number, 7).value or "").strip(),
                        amount_krw=_parse_amount(sheet.cell(row_number, 8).value),
                        sheet_name=sheet.title,
                        source_row=row_number,
                    )
                )
    finally:
        workbook.close()
    return result


def load_manual_booking_rows(path: Path) -> list[ManualBookingRow]:
    """Load only manual-ledger rows that contain a reservation number."""

    return [
        row for row in load_manual_expense_rows(path)
        if row.booking_number
    ]


def _provider(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    if any(token in text for token in ("AGODA", "아고다")):
        return "agoda"
    if any(token in text for token in ("TRIP.COM", "TRIPCOM", "트립닷컴")):
        return "trip"
    if any(token in text for token in ("BOOKING.COM", "BOOKING", "부킹")):
        return "booking"
    if "AIRBNB" in text:
        return "airbnb"
    if any(token in text for token in ("JEJU AIR", "제주항공")):
        return "jeju_air"
    if any(token in text for token in ("ANA", "ALL NIPPON")):
        return "ana"
    return ""


def _content_group(value: object) -> str:
    text = str(value or "").strip()
    return {
        "숙박비": "숙박",
        "숙박": "숙박",
        "항공료": "항공",
        "항공": "항공",
        "렌터카": "렌트",
        "렌트": "렌트",
    }.get(text, text)


def _period_matches(manual_period: str, event_start: date | None, event_end: date | None) -> bool:
    if not manual_period or event_start is None or event_end is None:
        return False
    numbers = re.findall(r"(?<!\d)(\d{4})(?!\d)", manual_period)
    if not numbers:
        return False
    candidates: list[tuple[int, int]] = []
    for item in numbers:
        candidates.append((int(item[:2]), int(item[2:])))
    resolved: list[date] = []
    for month, day in candidates:
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            return False
        candidate_dates: list[date] = []
        for year in range(event_start.year, event_end.year + 1):
            try:
                candidate_dates.append(date(year, month, day))
            except ValueError:
                continue
        in_window = [item for item in candidate_dates if event_start <= item <= event_end]
        if not in_window:
            return False
        resolved.append(in_window[0])
    return bool(resolved)


def _date_distance(left: date | None, right: date | None) -> int | None:
    if left is None or right is None:
        return None
    return abs((left - right).days)


def _score(payment: Mapping[str, object], manual: ManualBookingRow) -> tuple[int, set[str]]:
    score = 100  # exact amount is mandatory for a candidate edge
    reasons: set[str] = {"exact_amount"}
    payment_date = _parse_date(payment.get("occurred_on"))
    distance = _date_distance(payment_date, manual.occurred_on)
    if distance == 0:
        score += 40
        reasons.add("exact_date")
    elif distance is not None and distance <= 7:
        score += 18
        reasons.add("date_within_7_days")
    provider_payment = _provider(payment.get("merchant"))
    provider_manual = _provider(manual.merchant)
    if provider_payment and provider_manual and provider_payment == provider_manual:
        score += 30
        reasons.add("provider_match")
    elif provider_payment and provider_manual and provider_payment != provider_manual:
        score -= 30
        reasons.add("provider_conflict")
    if _content_group(payment.get("account")) == _content_group(manual.content):
        score += 8
        reasons.add("content_match")
    if _period_matches(
        manual.period,
        _parse_date(payment.get("event_start")),
        _parse_date(payment.get("event_end")),
    ):
        score += 8
        reasons.add("manual_period_in_event_window")
    if normalize_merchant_name(payment.get("merchant")) == normalize_merchant_name(manual.merchant):
        score += 12
        reasons.add("merchant_match")
    return score, reasons


def link_booking_numbers(
    payments: Sequence[Mapping[str, object]],
    manual_rows: Iterable[ManualBookingRow],
) -> tuple[dict[int, str], dict[str, int]]:
    """Return only high-confidence one-to-one payment→reservation links.

    Exact amount and the same canonical travel tab are required.  A second
    independent binding (date, provider, merchant, content, or period) is
    required before a reservation number is emitted.
    """

    manual_rows = list(manual_rows)
    manual_by_key: dict[tuple[str, int], list[ManualBookingRow]] = defaultdict(list)
    for manual in manual_rows:
        if manual.amount_krw is not None and manual.booking_number:
            manual_by_key[(manual.target, manual.amount_krw)].append(manual)

    edges: list[tuple[int, int, str, int, set[str]]] = []
    diagnostics: Counter[str] = Counter()
    for payment in payments:
        payment_id = int(payment["payment_id"])
        target = str(payment.get("target") or "")
        amount = _parse_amount(payment.get("amount_krw"))
        if not target or amount is None:
            continue
        candidates = manual_by_key.get((target, amount), [])
        if not candidates:
            continue
        diagnostics["exact_amount_target_candidates"] += len(candidates)
        for manual in candidates:
            score, reasons = _score(payment, manual)
            independent = len(reasons - {"exact_amount"})
            if independent < 1:
                diagnostics["rejected_amount_only"] += 1
                continue
            edges.append((score, payment_id, manual.booking_number, manual.source_row, reasons))

    # Resolve each payment only after checking its top-score cardinality.
    # A tie between different booking rows is not safe to break by sort order.
    by_payment: dict[int, list[tuple[int, int, str, int, set[str]]]] = defaultdict(list)
    for edge in edges:
        by_payment[edge[1]].append(edge)
    unambiguous_edges: list[tuple[int, int, str, int, set[str]]] = []
    for payment_id, candidates in by_payment.items():
        top_score = max(item[0] for item in candidates)
        top = [item for item in candidates if item[0] == top_score]
        candidate_rows = {(item[2], item[3]) for item in top}
        if len(candidate_rows) != 1:
            diagnostics["rejected_ambiguous_top_candidate"] += 1
            continue
        if any("provider_conflict" in item[4] for item in top):
            diagnostics["rejected_provider_conflict"] += 1
            continue
        unambiguous_edges.append(top[0])

    unambiguous_edges.sort(key=lambda item: (-item[0], item[1], item[3], item[2]))
    assigned_payments: set[int] = set()
    assigned_manual_rows: set[tuple[str, int]] = set()
    links: dict[int, str] = {}
    for score, payment_id, booking_number, source_row, reasons in unambiguous_edges:
        if payment_id in assigned_payments or (booking_number, source_row) in assigned_manual_rows:
            continue
        if score < 118:
            diagnostics["rejected_low_score"] += 1
            continue
        links[payment_id] = booking_number
        assigned_payments.add(payment_id)
        assigned_manual_rows.add((booking_number, source_row))
        diagnostics["linked"] += 1
        diagnostics["reason_exact_date"] += "exact_date" in reasons
        diagnostics["reason_provider"] += "provider_match" in reasons
        diagnostics["reason_period"] += "manual_period_in_event_window" in reasons

    diagnostics["manual_rows_with_booking_number"] = len(manual_rows)
    diagnostics["payments_with_link"] = len(links)
    return links, dict(diagnostics)
