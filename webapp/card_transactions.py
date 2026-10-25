"""Read-only projection of stored card transactions for the card-all API.
Uses the real transactions schema from app/db.py (no invented schema).
No write, no OTA re-analysis, no Google call."""
from __future__ import annotations
import os
import sqlite3
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

# Fixed date-like token for the undated cursor. Undated rows have no real date,
# so their order is transaction_id ASC and the token only carries that position.
# It is deliberately shaped like YYYY-MM-DD so the shared HTTP cursor check accepts it.
_UNDATED_CURSOR_DATE = "0000-00-00"
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_TIME_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$")

def _valid_use_date(value: Any) -> bool:
    """Accept calendar-valid ISO dates and local date-times without zone suffixes.

    Card-use dates have no timezone conversion rule in the card contract. Keeping
    offset-bearing values undated avoids assigning a potentially different day.
    The stored value itself is still returned unchanged by the read projection.
    """
    if not isinstance(value, str):
        return False
    if _DATE_PREFIX.fullmatch(value):
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    if not _DATE_TIME_PREFIX.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is None

_VALID_DATE_SQL = "COST_VALID_USE_DATE(approval_date) = 1"

def _resolve_card_db_path(db_path: Optional[str] = None) -> str:
    """Resolve the card transactions database path.

    Priority:
    1. Explicitly passed db_path (for tests/integration)
    2. WEBLEDGER_DB environment variable (production card flow database)
    3. Raise error if neither available - pure metadata query impossible

    The card transactions database is separate from the ledger board database.
    """
    if db_path:
        return db_path
    env_path = os.environ.get("WEBLEDGER_DB")
    if env_path:
        return env_path
    # Pure metadata query impossible - no database path configured
    raise RuntimeError(
        "카드 원본 DB 경로가 설정되지 않았습니다. WEBLEDGER_DB 환경 변수를 설정하거나 "
        "명시적으로 db_path를 전달해 주세요. COST_DB 또는 webledger.work.sqlite는 "
        "장부 DB일 수 있으므로 카드 거래 조회용으로 사용하지 않습니다."
    )

def _connect(db_path: str) -> sqlite3.Connection:
    """Open database in read-only mode using SQLite URI.

    Uses mode=ro to prevent accidental file creation on missing path.
    """
    path = Path(db_path).resolve()
    uri = path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.create_function("COST_VALID_USE_DATE", 1, lambda value: int(_valid_use_date(value)), deterministic=True)
    return conn

def _get_available_years(conn: sqlite3.Connection) -> List[int]:
    """Get years only from valid card-use dates."""
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT substr(approval_date, 1, 4) FROM transactions WHERE {_VALID_DATE_SQL} ORDER BY 1")
    return [int(row[0]) for row in cur.fetchall()]
def year_summary(db_path: Optional[str] = None, year: int = 2026) -> Dict[str, Any]:
    """Get monthly transaction counts and undated count for a year.

    Undated count only includes truly null/empty/invalid approval_date values,
    not valid dates from other years.
    """
    resolved_path = _resolve_card_db_path(db_path)
    conn = _connect(resolved_path)
    try:
        cur = conn.cursor()
        months = {}
        for m in range(1, 13):
            cur.execute(
                "SELECT COUNT(DISTINCT transaction_id) FROM transactions "
                f"WHERE {_VALID_DATE_SQL} AND substr(approval_date, 1, 4) = ? AND substr(approval_date, 6, 2) = ?",
                (str(year), f"{m:02d}"))
            months[m] = cur.fetchone()[0] or 0
        cur.execute(f"SELECT COUNT(DISTINCT transaction_id) FROM transactions WHERE NOT ({_VALID_DATE_SQL})")
        undated = cur.fetchone()[0] or 0
        return {"year": year, "months": months, "undated_count": undated}
    finally:
        conn.close()

def list_for_month(db_path: Optional[str] = None, year: int = 2026, month: int = 1,
                    cursor: Optional[str] = None, per_page: int = 100) -> Dict[str, Any]:
    """List transactions for a specific month with cursor pagination.

    Stable ordering: date ASC, time-bearing rows first, time ASC, ID ASC.
    Preserves all financial states: different IDs with same amount, duplicates, cancellations, etc.
    """
    if not isinstance(month, int) or month < 1 or month > 12:
        raise ValueError("invalid month: must be 1-12")
    if not isinstance(year, int) or year < 2000 or year > 2100:
        raise ValueError("invalid year: must be 2000-2100")
    if not isinstance(per_page, int) or per_page < 1 or per_page > 500:
        raise ValueError("invalid per_page: must be 1-500")

    resolved_path = _resolve_card_db_path(db_path)
    conn = _connect(resolved_path)
    try:
        cur = conn.cursor()
        params = [str(year), f"{month:02d}"]
        where = f"{_VALID_DATE_SQL} AND substr(approval_date, 1, 4) = ? AND substr(approval_date, 6, 2) = ?"
        if cursor:
            parts = cursor.split("|", 1)
            if len(parts) != 2:
                raise ValueError("invalid cursor format")
            c_date, c_id = parts
            if not _valid_use_date(c_date) or not c_id:
                raise ValueError("invalid cursor date")
            c_date_only = int(len(c_date) == 10)
            c_time = c_date[11:] if not c_date_only else ""
            where += (
                " AND (substr(approval_date, 1, 10), "
                "CASE WHEN length(approval_date) = 10 THEN 1 ELSE 0 END, "
                "substr(approval_date, 12), transaction_id) > (?, ?, ?, ?)"
            )
            params += [c_date[:10], c_date_only, c_time, c_id]
        sql = (
            "SELECT transaction_id, approval_date, approval_number, amount_krw, "
            "foreign_amount, foreign_currency, merchant, description, classification_state, "
            "classification_source, trip_id, item, description_raw, duplicate_of, conflict_reason, revision "
            "FROM transactions WHERE " + where +
            " ORDER BY substr(approval_date, 1, 10) ASC, "
            "CASE WHEN length(approval_date) = 10 THEN 1 ELSE 0 END ASC, "
            "substr(approval_date, 12) ASC, transaction_id ASC LIMIT ?"
        )
        cur.execute(sql, params + [per_page + 1])
        rows = cur.fetchall()
        has_more = len(rows) > per_page
        rows = rows[:per_page]
        items = []
        for r in rows:
            tid, adate, anumber, amt, famt, fcurr, merchant, desc, state, src, trip, item, raw, dup, conflict, rev = r
            items.append({
                "transaction_id": tid,
                "use_date": adate or "",
                "approval_date": adate,
                "approval_number": anumber,
                "amount_krw": amt,
                "foreign_amount": famt,
                "foreign_currency": fcurr,
                "merchant": merchant,
                "description": desc,
                "classification_state": state,
                "classification_source": src,
                "trip_id": trip,
                "item": item,
                "description_raw": raw,
                "duplicate_of": dup,
                "conflict_reason": conflict,
                "revision": rev
            })
        next_cursor = f"{items[-1]['approval_date']}|{items[-1]['transaction_id']}" if items else None
        return {
            "year": year, "month": month,
            "items": items,
            "count": len(items),
            "has_more": has_more,
            "cursor": next_cursor,
            "undated": []
        }
    finally:
        conn.close()

def undated_list(db_path: Optional[str] = None, year: int = 2026, cursor: Optional[str] = None, per_page: int = 100) -> Dict[str, Any]:
    """List undated transactions (null/empty/invalid approval_date only).

    Does NOT include transactions from other years with valid dates.
    """
    if not isinstance(year, int) or year < 2000 or year > 2100:
        raise ValueError("invalid year: must be 2000-2100")
    if not isinstance(per_page, int) or per_page < 1 or per_page > 500:
        raise ValueError("invalid per_page: must be 1-500")

    resolved_path = _resolve_card_db_path(db_path)
    conn = _connect(resolved_path)
    try:
        cur = conn.cursor()
        params = []
        # Only truly null/empty/invalid dates - NOT "NOT LIKE year-%".
        # The OR group must be parenthesized so a cursor filter cannot reopen it.
        where = f"NOT ({_VALID_DATE_SQL})"
        cur.execute(f"SELECT COUNT(DISTINCT transaction_id) FROM transactions WHERE NOT ({_VALID_DATE_SQL})")
        undated_total = cur.fetchone()[0] or 0
        if cursor:
            parts = cursor.split("|", 1)
            if len(parts) != 2:
                raise ValueError("invalid cursor format")
            c_date, c_id = parts
            # Undated rows have no usable date, so they are ordered by transaction_id
            # alone. The cursor keeps a fixed date-like token so the HTTP layer's
            # shared cursor validation accepts it.
            if c_date != _UNDATED_CURSOR_DATE or not c_id:
                raise ValueError("invalid cursor date")
            where += " AND transaction_id > ?"
            params.append(c_id)
        cur.execute(
            f"SELECT transaction_id, approval_date, approval_number, amount_krw, "
            f"foreign_amount, foreign_currency, merchant, description, classification_state, "
            f"classification_source, trip_id, item, description_raw, duplicate_of, conflict_reason, revision "
            f"FROM transactions WHERE {where} "
            f"ORDER BY transaction_id ASC LIMIT ?",
            params + [per_page + 1])
        rows = cur.fetchall()
        has_more = len(rows) > per_page
        rows = rows[:per_page]
        items = []
        for r in rows:
            tid, adate, anumber, amt, famt, fcurr, merchant, desc, state, src, trip, item, raw, dup, conflict, rev = r
            items.append({
                "transaction_id": tid,
                "approval_date": adate or "",
                "approval_number": anumber,
                "amount_krw": amt,
                "foreign_amount": famt,
                "foreign_currency": fcurr,
                "merchant": merchant,
                "description": desc,
                "classification_state": state,
                "classification_source": src,
                "trip_id": trip,
                "item": item,
                "description_raw": raw,
                "duplicate_of": dup,
                "conflict_reason": conflict,
                "revision": rev
            })
        next_cursor = f"{_UNDATED_CURSOR_DATE}|{items[-1]['transaction_id']}" if items else None
        return {
            "year": year, "items": items,
            "count": len(items), "total_count": undated_total,
            "has_more": has_more,
            "cursor": next_cursor
        }
    finally:
        conn.close()

def available_years(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Get list of available years from transactions, with 2026 as default if empty."""
    resolved_path = _resolve_card_db_path(db_path)
    conn = _connect(resolved_path)
    try:
        years = _get_available_years(conn)
        if not years:
            years = [2026]
        return {"years": years, "default": 2026}
    finally:
        conn.close()
