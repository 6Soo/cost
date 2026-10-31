"""Read-only projection of stored card transactions for the card-all API.
Uses the real transactions schema from app/db.py (no invented schema).
No write, no OTA re-analysis, no Google call."""
from __future__ import annotations
import os
import sqlite3
import re
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from app import request_metrics

# Fixed date-like token for the undated cursor. Undated rows have no real date,
# so their order is transaction_id ASC and the token only carries that position.
# It is deliberately shaped like YYYY-MM-DD so the shared HTTP cursor check accepts it.
_UNDATED_CURSOR_DATE = "0000-00-00"
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_TIME_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$")


def card_identity(issuer, kind, last4):
    """Only an explicit last4 identifies a card; never recover a PAN's suffix."""
    tail = str(last4 or '').strip()
    if not re.fullmatch(r'[0-9]{4}', tail):
        return {'card_key': 'missing', 'card_label': '식별 정보 없음'}
    issuer, kind = str(issuer or '').strip(), str(kind or '').strip()
    key = hashlib.sha256(json.dumps([issuer, kind, tail], ensure_ascii=True).encode()).hexdigest()[:24]
    return {'card_key': key, 'card_label': ' · '.join(filter(None, [issuer, '•••• ' + tail, kind]))}


def _filter_clause(*, unassigned=False, valid_trip_ids=(), card='', search=''):
    clauses, params = [], []
    if unassigned:
        clauses.append('COST_REFUND_TAB_MEMBER(transaction_id)=0')
        trips = sorted(set(valid_trip_ids or ()))
        clauses.append("COST_ASSIGNMENT_STATUS(display_tab_id,trip_id,?)='UNASSIGNED'")
        params.append(json.dumps(trips, ensure_ascii=True))
    if card:
        clauses.append('COST_CARD_KEY(issuer,card_kind,card_tail)=?')
        params.append(card)
    if search:
        # Keep text search case-insensitive and allow the same field to be
        # found by either its displayed amount (9,800) or its stored value
        # (9800).  Amounts are deliberately substring-searchable so a user
        # can enter a partial amount while investigating a transaction.
        numeric_search = str(search).replace(",", "") or str(search)
        clauses.append(
            "(instr(lower(COALESCE(merchant,'')),lower(?))>0 "
            "OR instr(lower(COALESCE(description,'')),lower(?))>0 "
            "OR instr(lower(COALESCE(item,'')),lower(?))>0 "
            "OR instr(lower(COALESCE(approval_number,'')),lower(?))>0 "
            "OR instr(CAST(COALESCE(amount_krw,'') AS TEXT),?)>0 "
            "OR instr(lower(replace(COALESCE(foreign_amount,''),',','')),lower(?))>0)"
        )
        params.extend([search] * 4 + [numeric_search, numeric_search])
    return ''.join(' AND (' + clause + ')' for clause in clauses), params


@request_metrics.card_stage('card_query')
def card_options(db_path=None):
    conn = _connect(_resolve_card_db_path(db_path))
    try:
        options = {identity['card_key']: identity for issuer, kind, tail in conn.execute(
            'SELECT DISTINCT issuer,card_kind,card_tail FROM transactions')
            for identity in [card_identity(issuer, kind, tail)]}
        return sorted(options.values(), key=lambda value: (value['card_key'] == 'missing', value['card_label']))
    finally:
        conn.close()


class DaySourceChanged(ValueError):
    """The explicit date filter must restart after its source rows change."""


def list_for_day(db_path=None, *, day, cursor=None, revision=None, per_page=100):
    """All raw rows for a user-selected use date; never a verified booking date.

    The read transaction keeps the fingerprint, count and page on one SQLite
    snapshot. Fingerprinting streams the allowlisted projection without keeping
    all rows in memory. No financial state is excluded from the date filter.
    """
    if not isinstance(day, str) or not _DATE_PREFIX.fullmatch(day):
        raise ValueError('invalid day: YYYY-MM-DD required')
    parsed = date.fromisoformat(day)
    if not 2000 <= parsed.year <= 2100:
        raise ValueError('invalid day: year out of range')
    if type(per_page) is not int or not 1 <= per_page <= 500:
        raise ValueError('invalid per_page')
    cursor_values = None
    if cursor is not None:
        if not isinstance(cursor, str) or '|' not in cursor:
            raise ValueError('invalid cursor')
        stamp, tid = cursor.split('|', 1)
        if not _valid_use_date(stamp) or stamp[:10] != day or not tid or len(tid) > 256:
            raise ValueError('invalid cursor date')
        if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{64}', revision):
            raise ValueError('cursor revision required')
        cursor_values = (int(len(stamp) == 10), stamp[11:] if len(stamp) > 10 else '', tid)
    fields = ('transaction_id', 'approval_date', 'approval_number', 'amount_krw',
              'foreign_amount', 'foreign_currency', 'merchant', 'transaction_direction',
              'transaction_kind', 'classification_state', 'trip_id', 'display_tab_id', 'item',
              'duplicate_of', 'conflict_reason', 'parse_error', 'revision')
    order = 'CASE WHEN length(approval_date)=10 THEN 1 ELSE 0 END, substr(approval_date,12), transaction_id'
    where = _VALID_DATE_SQL + ' AND substr(approval_date,1,10)=?'
    select = 'SELECT ' + ','.join(fields) + ' FROM transactions WHERE '
    conn = _connect(_resolve_card_db_path(db_path))
    try:
        conn.execute('BEGIN')
        digest = hashlib.sha256(day.encode('ascii'))
        total = 0
        for row in conn.execute(select + where + ' ORDER BY ' + order, (day,)):
            digest.update(json.dumps(row, ensure_ascii=True, separators=(',', ':')).encode('utf-8') + b'\n')
            total += 1
        current_revision = digest.hexdigest()
        if revision is not None and revision != current_revision:
            raise DaySourceChanged('date filter source changed')
        params = [day]
        if cursor_values:
            where += ' AND (CASE WHEN length(approval_date)=10 THEN 1 ELSE 0 END, substr(approval_date,12), transaction_id) > (?,?,?)'
            params.extend(cursor_values)
        rows = conn.execute(select + where + ' ORDER BY ' + order + ' LIMIT ?', params + [per_page + 1]).fetchall()
        items = [dict(zip(fields, row)) for row in rows[:per_page]]
        return {'date': day, 'filter_semantics': 'USER_DATE_FILTER', 'items': items,
                'count': len(items), 'total_count': total, 'has_more': len(rows) > per_page,
                'cursor': f"{items[-1]['approval_date']}|{items[-1]['transaction_id']}" if len(rows) > per_page else None,
                'revision': current_revision}
    finally:
        conn.close()

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

def transaction_detail(transaction_id: str, db_path=None):
    """Read one source row, including cards that have never become ledger rows."""
    if not isinstance(transaction_id, str) or not transaction_id.strip() or len(transaction_id) > 256:
        raise ValueError('invalid transaction id')
    fields = ('transaction_id', 'approval_date', 'approval_number', 'amount_krw',
              'foreign_amount', 'foreign_currency', 'merchant', 'description',
              'classification_state', 'classification_source', 'trip_id', 'display_tab_id',
              'item', 'duplicate_of', 'conflict_reason', 'issuer', 'card_kind', 'card_tail', 'batch_id', 'parse_error')
    conn = _connect(_resolve_card_db_path(db_path))
    try:
        row = conn.execute('SELECT ' + ','.join(fields) + ' FROM transactions WHERE transaction_id=?',
                           (transaction_id,)).fetchone()
        if row is None:
            return None
        result = dict(zip(fields, row))
        result.update(card_identity(result.pop('issuer'), result.pop('card_kind'), result.pop('card_tail')))
        return result
    finally:
        conn.close()


@request_metrics.card_stage('db_connect')
def _connect(db_path: str) -> sqlite3.Connection:
    """Open database in read-only mode using SQLite URI.

    Uses mode=ro to prevent accidental file creation on missing path.
    """
    path = Path(db_path).resolve()
    uri = path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.create_function("COST_VALID_USE_DATE", 1, lambda value: int(_valid_use_date(value)), deterministic=True)
    from app.assignment_status import sql_assignment_status
    conn.create_function('COST_ASSIGNMENT_STATUS', 3, sql_assignment_status, deterministic=True)
    conn.create_function('COST_CARD_KEY', 3, lambda issuer, kind, tail: card_identity(issuer, kind, tail)['card_key'], deterministic=True)
    # Resolve the same complete groups as the refund tab once per connection.
    # This stays lazy for endpoints that do not request destination metadata.
    members = None
    def refund_member(transaction_id):
        nonlocal members
        if members is None:
            from types import SimpleNamespace
            from .refund_tab import groups
            members = {row['transaction_id'] for group in groups(SimpleNamespace(conn=conn)) for row in group}
        return int(transaction_id in members)
    conn.create_function('COST_REFUND_TAB_MEMBER', 1, refund_member)
    return conn

def _get_available_years(conn: sqlite3.Connection) -> List[int]:
    """Get years only from valid card-use dates."""
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT substr(approval_date, 1, 4) FROM transactions WHERE {_VALID_DATE_SQL} ORDER BY 1")
    return [int(row[0]) for row in cur.fetchall()]
@request_metrics.card_stage('card_query')
def year_summary(db_path: Optional[str] = None, year: int = 2026, **filters) -> Dict[str, Any]:
    """Get monthly transaction counts and undated count for a year.

    Undated count only includes truly null/empty/invalid approval_date values,
    not valid dates from other years.
    """
    resolved_path = _resolve_card_db_path(db_path)
    conn = _connect(resolved_path)
    try:
        cur = conn.cursor()
        extra, filter_params = _filter_clause(**filters)
        months = {}
        for m in range(1, 13):
            cur.execute(
                "SELECT COUNT(DISTINCT transaction_id) FROM transactions "
                f"WHERE {_VALID_DATE_SQL} AND substr(approval_date, 1, 4) = ? AND substr(approval_date, 6, 2) = ?" + extra,
                [str(year), f"{m:02d}", *filter_params])
            months[m] = cur.fetchone()[0] or 0
        cur.execute(f"SELECT COUNT(DISTINCT transaction_id) FROM transactions WHERE NOT ({_VALID_DATE_SQL})" + extra, filter_params)
        undated = cur.fetchone()[0] or 0
        return {"year": year, "months": months, "undated_count": undated}
    finally:
        conn.close()

@request_metrics.card_stage('card_query')
def list_for_month(db_path: Optional[str] = None, year: int = 2026, month: int = 1,
                    cursor: Optional[str] = None, per_page: int = 100, **filters) -> Dict[str, Any]:
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
        extra, filter_params = _filter_clause(**filters)
        where += extra
        params.extend(filter_params)
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
            "classification_source, trip_id, item, description_raw, duplicate_of, conflict_reason, revision, issuer,card_kind,card_tail,display_tab_id, COST_REFUND_TAB_MEMBER(transaction_id), batch_id "
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
            tid, adate, anumber, amt, famt, fcurr, merchant, desc, state, src, trip, item, raw, dup, conflict, rev, issuer,kind,tail,display_tab,refund_member,batch = r
            items.append({
                "transaction_id": tid, "batch_id": batch,
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
                "display_tab_id": display_tab, "refund_tab_member": bool(refund_member),
                **card_identity(issuer, kind, tail),
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

@request_metrics.card_stage('card_query')
def undated_list(db_path: Optional[str] = None, year: int = 2026, cursor: Optional[str] = None, per_page: int = 100, **filters) -> Dict[str, Any]:
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
        extra, params = _filter_clause(**filters)
        where += extra
        cur.execute('SELECT COUNT(DISTINCT transaction_id) FROM transactions WHERE ' + where, params)
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
            f"classification_source, trip_id, item, description_raw, duplicate_of, conflict_reason, revision, issuer,card_kind,card_tail,display_tab_id, COST_REFUND_TAB_MEMBER(transaction_id), batch_id "
            f"FROM transactions WHERE {where} "
            f"ORDER BY transaction_id ASC LIMIT ?",
            params + [per_page + 1])
        rows = cur.fetchall()
        has_more = len(rows) > per_page
        rows = rows[:per_page]
        items = []
        for r in rows:
            tid, adate, anumber, amt, famt, fcurr, merchant, desc, state, src, trip, item, raw, dup, conflict, rev, issuer,kind,tail,display_tab,refund_member,batch = r
            items.append({
                "transaction_id": tid, "batch_id": batch,
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
                "display_tab_id": display_tab, "refund_tab_member": bool(refund_member),
                **card_identity(issuer, kind, tail),
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


@request_metrics.card_stage('card_query')
def search_for_year(db_path: Optional[str] = None, year: int = 2026,
                    cursor: Optional[str] = None, per_page: int = 100,
                    **filters) -> Dict[str, Any]:
    """Search valid dated transactions across every month in ``year``.

    The month view remains the canonical paged view.  This projection exists
    so a search submitted before choosing a month has an immediate result
    area, including an explicit zero-result state.
    """
    if not isinstance(year, int) or year < 2000 or year > 2100:
        raise ValueError("invalid year: must be 2000-2100")
    if not isinstance(per_page, int) or per_page < 1 or per_page > 500:
        raise ValueError("invalid per_page: must be 1-500")

    conn = _connect(_resolve_card_db_path(db_path))
    try:
        params = [str(year)]
        where = f"{_VALID_DATE_SQL} AND substr(approval_date, 1, 4) = ?"
        extra, filter_params = _filter_clause(**filters)
        where += extra
        params.extend(filter_params)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(DISTINCT transaction_id) FROM transactions WHERE " + where, params)
        total = cur.fetchone()[0] or 0
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
            params.extend([c_date[:10], c_date_only, c_time, c_id])
        sql = (
            "SELECT transaction_id, approval_date, approval_number, amount_krw, "
            "foreign_amount, foreign_currency, merchant, description, classification_state, "
            "classification_source, trip_id, item, description_raw, duplicate_of, conflict_reason, revision, issuer,card_kind,card_tail,display_tab_id, COST_REFUND_TAB_MEMBER(transaction_id), batch_id "
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
            tid, adate, anumber, amt, famt, fcurr, merchant, desc, state, src, trip, item, raw, dup, conflict, rev, issuer, kind, tail, display_tab, refund_member, batch = r
            items.append({
                "transaction_id": tid, "batch_id": batch, "use_date": adate or "", "approval_date": adate,
                "approval_number": anumber, "amount_krw": amt, "foreign_amount": famt,
                "foreign_currency": fcurr, "merchant": merchant, "description": desc,
                "classification_state": state, "classification_source": src,
                "trip_id": trip, "display_tab_id": display_tab, "refund_tab_member": bool(refund_member),
                **card_identity(issuer, kind, tail), "item": item,
                "description_raw": raw, "duplicate_of": dup,
                "conflict_reason": conflict, "revision": rev
            })
        next_cursor = f"{items[-1]['approval_date']}|{items[-1]['transaction_id']}" if items and has_more else None
        return {"year": year, "items": items, "count": len(items),
                "total_count": total, "has_more": has_more, "cursor": next_cursor}
    finally:
        conn.close()

@request_metrics.card_stage('card_query')
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
