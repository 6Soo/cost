"""분기 기타비용 탭: 여행 탭처럼 열고, 새로 수집된 거래를 분기 단위로 자동 기록한다.

탭 식별자는 `quarter:<연도>:<분기>`다. 거래는 이 탭에 배정되고 장부 기록(ledger_entries)이
되고, 기록 여부는 장부 기록 자체로 판단한다. 한 트랜잭션에서 처리하고, 이미 기록된
거래는 건너뛴다. 되돌릴 때는 기록을 지우지 않고 역분개 기록을 추가한다.
"""
import re
import sqlite3

from . import quarter_costs
from . import auto_record_policy
from .db import decided_sql, utc_now
from .ledger import _already_booked, _recording_guard

ITEM = '분기 기타비용'
TAB_RE = re.compile(r'quarter:(20\d{2}):([1-4])')


class QuarterError(Exception):
    pass


def tab_id_for(year: int, quarter: int) -> str:
    return f'quarter:{year}:{quarter}'


def parse_tab(tab: str):
    match = TAB_RE.fullmatch(tab or '')
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def pending_rows(conn, tab: str, batch_id: str | None = None) -> list[dict]:
    """Assigned to the tab, not yet recorded, not a duplicate. With a batch, only that batch's rows."""
    scope = " AND transaction_id IN (SELECT transaction_id FROM import_batch_rows WHERE batch_id=?)" if batch_id else ""
    args = (ITEM, tab, batch_id) if batch_id else (ITEM, tab)
    try:
        rows = conn.execute(
            "SELECT transaction_id, batch_id, source_hash, merchant, approval_date, posting_date, amount_krw, "
            "transaction_direction, card_tail, classification_state, conflict_reason, parse_error FROM transactions "
            "WHERE item=? AND display_tab_id=? AND COALESCE(duplicate_of,'')=''"
            " AND NOT EXISTS (SELECT 1 FROM ledger_entries l WHERE l.transaction_id=transactions.transaction_id)" + scope +
            " ORDER BY COALESCE(NULLIF(approval_date,''),posting_date), transaction_id", args).fetchall()
    except sqlite3.OperationalError:
        return []  # no card tables yet: nothing is waiting on any quarter tab
    keys = ['transaction_id', 'batch_id', 'source_hash', 'merchant', 'approval_date', 'posting_date',
            'amount_krw', 'transaction_direction', 'card_tail', 'classification_state', 'conflict_reason', 'parse_error']
    return [dict(zip(keys, row)) for row in rows]


def assign_unassigned(conn) -> dict:
    """One-time placement of undecided quarter-cost rows on their quarter tab, by approval date."""
    rows = conn.execute(
        "SELECT transaction_id, COALESCE(NULLIF(approval_date,''),posting_date) FROM transactions "
        "WHERE item=? AND NOT " + decided_sql() + " AND COALESCE(duplicate_of,'')='' "
        "AND COALESCE(display_tab_id,'') IN ('','unclassified')", (ITEM,)).fetchall()
    placed = {}
    for transaction_id, day in rows:
        target = quarter_costs.destination({'item': ITEM, 'display_tab_id': 'unclassified',
                                            'transaction_direction': 'purchase', 'amount_krw': 1,
                                            'approval_date': day})
        if target is None:
            continue
        conn.execute("UPDATE transactions SET display_tab_id=?, trip_id='' WHERE transaction_id=?",
                     (target['id'], transaction_id))
        placed[target['id']] = placed.get(target['id'], 0) + 1
    return placed


def book_batch(store, batch_id: str, projection=None) -> int:
    """Records the quarter-cost rows of one newly collected batch. Older batches are never touched."""
    if not auto_record_policy.batch_is_new(store.conn, batch_id):
        return 0
    tabs = [r[0] for r in store.conn.execute(
        "SELECT DISTINCT display_tab_id FROM transactions WHERE item=? "
        "AND display_tab_id LIKE 'quarter:%' AND transaction_id IN "
        "(SELECT transaction_id FROM import_batch_rows WHERE batch_id=?)", (ITEM, batch_id)).fetchall()]
    return sum(confirm_tab(store, tab, batch_id=batch_id, projection=projection)['booked']
               for tab in tabs if parse_tab(tab))


def confirm_tab(store, tab: str, batch_id: str | None = None, projection=None) -> dict:
    """Records the tab's rows in one transaction and returns the counts. Already recorded rows are skipped.

    `projection`, when given, is called for each booked row inside the same transaction, so the
    board row and the ledger entry are written together or not at all."""
    if parse_tab(tab) is None:
        raise QuarterError('QUARTER_TAB_INVALID')
    year, quarter = parse_tab(tab)
    description = f'{year}년 {quarter}분기 기타비용'
    booked, skipped = [], []
    now = utc_now()
    with store.lock:
        store.conn.execute('BEGIN IMMEDIATE')
        try:
            from .company_expenses import states as company_expense_states
            from .review_holds import active_holds
            exclusions = company_expense_states(store.conn)
            holds = active_holds(store.conn)
            for row in pending_rows(store.conn, tab, batch_id):
                transaction_id = row['transaction_id']
                amount = row['amount_krw']
                undated = not (row['approval_date'] or row['posting_date'])
                if row['transaction_direction'] != 'purchase' or type(amount) is not int or amount <= 0 or undated:
                    skipped.append(transaction_id)
                    continue
                if _recording_guard(source_hash=row['source_hash'], state=row['classification_state'],
                                    conflict_reason=row['conflict_reason'], parse_error=row['parse_error'],
                                    exclusion=exclusions.get(transaction_id), hold=holds.get(transaction_id)):
                    skipped.append(transaction_id)
                    continue
                if _already_booked(store, transaction_id):
                    skipped.append(transaction_id)
                    continue
                day = (row['approval_date'] or row['posting_date'] or '')[:10]
                store.conn.execute(
                    "INSERT INTO ledger_entries(transaction_id, batch_id, item, description, display_tab_id, "
                    "trip_id, amount_krw, merchant, occurred_on, transaction_direction, source_hash, committed_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (transaction_id, row['batch_id'], ITEM, description, tab, '', amount,
                     row['merchant'] or '', day, 'purchase', row['source_hash'], now))
                store.log_change('quarter.booked', transaction_id, {'tab': tab, 'amount_krw': amount})
                booked.append(transaction_id)
                if projection is not None:
                    projection({'transaction_id': transaction_id, 'batch_id': row['batch_id'], 'item': ITEM,
                                'description': description, 'display_tab_id': tab, 'trip_id': '',
                                'amount_krw': amount, 'merchant': row['merchant'] or '', 'occurred_on': day,
                                'transaction_direction': 'purchase', 'source_hash': row['source_hash'],
                                'classification_state': 'classified', 'now': now})
            store.conn.execute('COMMIT')
        except Exception:
            store.conn.execute('ROLLBACK')
            raise
    return {'tab': tab, 'booked': len(booked), 'skipped': len(skipped)}
