"""Google 매출자료 양식_rev 지출 7열(B:H)을 붙여넣을 TSV로 만든다.

Builds text only. Nothing is written to Google, nothing is booked, and the operating
database is not read. Each input row is one actual card or receipt payment. Rows that
are not ready, or that cannot be placed safely, are held with a reason instead of
being pasted.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter

COLUMNS = ("거래일자", "항목", "내용", "기간", "예약번호", "증빙유형", "금액(원)")
EVIDENCE_TYPES = {"card": "카드", "receipt": "영수증"}
FORMULA_START = ("=", "+", "-", "@")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(value) -> str:
    """A cell that cannot turn into a formula or break the paste row."""
    text = "" if value is None else str(value)
    text = re.sub(r"[\t\r\n]+", " ", text).strip()
    return "'" + text if text.startswith(FORMULA_START) else text


def _hold_reason(row: dict) -> str | None:
    if row.get("status") != "ready":
        return "NOT_READY"
    if not isinstance(row.get("amount_krw"), int) or isinstance(row.get("amount_krw"), bool):
        return "AMOUNT_INVALID"
    if not isinstance(row.get('evidence'), str) or row['evidence'] not in EVIDENCE_TYPES:
        return "EVIDENCE_UNKNOWN"
    if not isinstance(row.get('date'), str) or not DATE.fullmatch(row['date']):
        return "DATE_INVALID"
    try:
        dt.date.fromisoformat(row["date"])
    except ValueError:
        return "DATE_INVALID"
    if not _text(row.get("payee")) or not _text(row.get("category")):
        return "FIELD_MISSING"
    identity = row.get('transaction_id')
    if identity is None or (isinstance(identity, str) and not identity.strip()):
        return 'ID_MISSING'
    if not isinstance(identity, str):
        return 'ID_INVALID'
    return None


def expense_tsv(rows: list[dict], *, layout: str) -> dict:
    """Returns the paste text for ready rows plus the held rows with reasons.

    layout must be the standard 매출자료 양식_rev. Any other layout is refused, never converted.
    """
    if layout != "rev":
        raise ValueError("TARGET_LAYOUT_NOT_STANDARD")
    reasons = [(row, _hold_reason(row)) for row in rows]
    counts = Counter(row.get("transaction_id") for row, reason in reasons if reason is None)
    held, ready = [], []
    for row, reason in reasons:
        transaction_id = row.get("transaction_id")
        # The same transaction twice is never pasted twice; both copies wait for a person.
        if reason is None and counts[transaction_id] > 1:
            reason = "DUPLICATE_ID"
        if reason is None:
            ready.append(row)
        else:
            held.append({"transaction_id": transaction_id, "reason": reason})
    ordered = sorted(ready, key=lambda r: (r["date"], str(r["transaction_id"])))
    lines = ["\t".join([
        row["date"],
        _text(row["payee"]),
        _text(row["category"]),
        _text(row.get("period")),
        _text(row.get("reservation_no")),
        EVIDENCE_TYPES[row["evidence"]],
        str(row["amount_krw"]),
    ]) for row in ordered]
    return {
        "tsv": "\n".join(lines) + ("\n" if lines else ""),
        "row_count": len(lines),
        "total_krw": sum(row["amount_krw"] for row in ordered),
        "held": held,
    }
