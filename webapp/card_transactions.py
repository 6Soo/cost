"""Read-only projection of stored card transactions for the card-all API.
Uses the real transactions schema from app/db.py (no invented schema).
No write, no OTA re-analysis, no Google call."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional, List

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
    return sqlite3.connect(uri, uri=True, check_same_thread=False)

def _get_available_years(conn: sqlite3.Connection) -> List[int]:
    """Get list of years that have transactions, from approval_date."""
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT substr(approval_date, 1, 4) FROM transactions "
        "WHERE approval_date IS NOT NULL AND approval_date != '' "
        "AND substr(approval_date, 1, 4) GLOB '[0-9][0-9][0-9][0-9]' "
        "ORDER BY 1"
    )
    years = [int(row[0]) for row in cur.fetchall() if row[0].isdigit()]
    return years

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
                "WHERE substr(approval_date, 1, 4) = ? AND substr(approval_date, 6, 2) = ?",
                (str(year), f"{m:02d}"))
            months[m] = cur.fetchone()[0] or 0
        # Undated: only truly null/empty/invalid date values
        # Invalid = not matching YYYY-MM-DD pattern
        cur.execute(
            "SELECT COUNT(DISTINCT transaction_id) FROM transactions "
            "WHERE approval_date IS NULL "
            "   OR approval_date = '' "
            "   OR approval_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'")
        undated = cur.fetchone()[0] or 0
        return {"year": year, "months": months, "undated_count": undated}
    finally:
        conn.close()

def list_for_month(db_path: Optional[str] = None, year: int = 2026, month: int = 1,
                    cursor: Optional[str] = None, per_page: int = 100) -> Dict[str, Any]:
    """List transactions for a specific month with cursor pagination.

    Stable ordering: approval_date ASC, transaction_id ASC.
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
        params = [f"{year}-{month:02d}-%"]
        where = "approval_date LIKE ?"
        if cursor:
            parts = cursor.split("|", 1)
            if len(parts) != 2:
                raise ValueError("invalid cursor format")
            c_date, c_id = parts
            # Validate cursor date format
            if not (c_date and c_date[0:4].isdigit() and len(c_date) >= 10):
                raise ValueError("invalid cursor date")
            where += " AND (approval_date > ? OR (approval_date = ? AND transaction_id > ?))"
            params += [c_date, c_date, c_id]
        sql = (
            "SELECT transaction_id, approval_date, approval_number, amount_krw, "
            "foreign_amount, foreign_currency, merchant, description, classification_state, "
            "classification_source, trip_id, item, description_raw, duplicate_of, conflict_reason, revision "
            "FROM transactions WHERE " + where +
            " ORDER BY approval_date ASC, transaction_id ASC LIMIT ?"
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
        # Only truly null/empty/invalid dates - NOT "NOT LIKE year-%"
        where = (
            "approval_date IS NULL "
            "OR approval_date = '' "
            "OR approval_date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"
        )
        if cursor:
            parts = cursor.split("|", 1)
            if len(parts) != 2:
                raise ValueError("invalid cursor format")
            c_date, c_id = parts
            if not (c_date and c_date[0:4].isdigit() and len(c_date) >= 10):
                raise ValueError("invalid cursor date")
            where += " AND (approval_date > ? OR (approval_date = ? AND transaction_id > ?))"
            params += [c_date, c_date, c_id]
        cur.execute(
            f"SELECT transaction_id, approval_date, approval_number, amount_krw, "
            f"foreign_amount, foreign_currency, merchant, description, classification_state, "
            f"classification_source, trip_id, item, description_raw, duplicate_of, conflict_reason, revision "
            f"FROM transactions WHERE {where} "
            f"ORDER BY approval_date ASC NULLS LAST, transaction_id ASC LIMIT ?",
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
        next_cursor = f"{items[-1]['approval_date']}|{items[-1]['transaction_id']}" if items else None
        return {
            "year": year, "items": items,
            "count": len(items),
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