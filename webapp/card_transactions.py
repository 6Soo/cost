"""Read-only projection of stored card transactions for the card-all API.
Uses the real transactions schema from app/db.py (no invented schema).
No write, no OTA re-analysis, no Google call."""
from __future__ import annotations
import sqlite3, os
from typing import Dict, Any, Optional

DB_DEFAULT = os.environ.get("COST_DB", "webledger.work.sqlite")

def _connect(db_path: str = DB_DEFAULT):
    return sqlite3.connect(db_path, check_same_thread=False)

def year_summary(db_path: str = DB_DEFAULT, year: int = 2026) -> Dict[str, Any]:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        months = {}
        for m in range(1, 13):
            cur.execute(
                "SELECT COUNT(DISTINCT transaction_id) FROM transactions WHERE substr(approval_date,1,4)=? AND substr(approval_date,6,2)=?",
                (str(year), f"{m:02d}"))
            months[m] = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(DISTINCT transaction_id) FROM transactions WHERE approval_date IS NULL OR approval_date='' OR approval_date NOT LIKE ?",
                    (f"{year}-%",))
        undated = cur.fetchone()[0] or 0
        return {"year": year, "months": months, "undated_count": undated}
    finally:
        conn.close()

def list_for_month(db_path: str = DB_DEFAULT, year: int = 2026, month: int = 1,
                    cursor: Optional[str] = None, per_page: int = 100) -> Dict[str, Any]:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        params = [f"{year}-{month:02d}-%"]
        where = "approval_date LIKE ?"
        if cursor:
            parts = cursor.split("|", 1)
            if len(parts) == 2:
                c_date, c_id = parts
                where += " AND (approval_date > ? OR (approval_date = ? AND transaction_id > ?))"
                params += [c_date, c_date, c_id]
        sql = f"SELECT transaction_id, approval_date, approval_number, amount_krw, "\
            f"foreign_amount, foreign_currency, merchant, description, classification_state, "\
            f"classification_source, trip_id, item, description_raw, duplicate_of, conflict_reason, revision "\
            f"FROM transactions WHERE {where} ORDER BY approval_date ASC, transaction_id ASC LIMIT ?"
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

def undated_list(db_path: str = DB_DEFAULT, year: int = 2026, cursor: Optional[str] = None, per_page: int = 100) -> Dict[str, Any]:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        params = []
        where = "(approval_date IS NULL OR approval_date='' OR approval_date NOT LIKE ?)"
        params.append(f"{year}-%")
        if cursor:
            parts = cursor.split("|", 1)
            if len(parts) == 2:
                c_date, c_id = parts
                where += " AND (approval_date > ? OR (approval_date = ? AND transaction_id > ?))"
                params += [c_date, c_date, c_id]
        cur.execute(
            f"SELECT transaction_id, approval_date, approval_number, amount_krw, "
            f"foreign_amount, foreign_currency, merchant, description, classification_state, "
            f"classification_source, trip_id, item, description_raw, duplicate_of, conflict_reason, revision "
            f"FROM transactions WHERE {where} ORDER BY approval_date ASC NULLS LAST, transaction_id ASC LIMIT ?",
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
        return {
            "year": year, "items": items,
            "count": len(items),
            "has_more": has_more,
            "cursor": f"{items[-1]['approval_date']}|{items[-1]['transaction_id']}" if items else None
        }
    finally:
        conn.close()
