"""분기 기타비용 탭: 여행 탭처럼 열고, 분기 단위로 한 번에 확정한다.

탭 식별자는 `quarter:<연도>:<분기>`다. 거래는 이 탭에 배정된 뒤 확정하면 장부 기록(ledger_entries)이
되고, 확정 상태는 기존 거래 행의 user_confirmed로 남는다. 확정은 한 트랜잭션에서 처리하고, 이미 기록된
거래는 건너뛴다. 되돌릴 때는 기록을 지우지 않고 역분개 기록을 추가한다.
"""
import re
import sqlite3

from . import quarter_costs
from .db import utc_now
from .ledger import _already_booked

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


def pending_rows(conn, tab: str) -> list[dict]:
    """Assigned to the tab, not yet confirmed, not a duplicate."""
    try:
        rows = conn.execute(
            "SELECT transaction_id, batch_id, source_hash, merchant, approval_date, posting_date, amount_krw, "
            "transaction_direction, card_tail FROM transactions "
            "WHERE item=? AND display_tab_id=? AND user_confirmed=0 AND COALESCE(duplicate_of,'')='' "
            "ORDER BY COALESCE(NULLIF(approval_date,''),posting_date), transaction_id",
            (ITEM, tab)).fetchall()
    except sqlite3.OperationalError:
        return []  # no card tables yet: nothing is waiting on any quarter tab
    keys = ['transaction_id', 'batch_id', 'source_hash', 'merchant', 'approval_date', 'posting_date',
            'amount_krw', 'transaction_direction', 'card_tail']
    return [dict(zip(keys, row)) for row in rows]


def assign_unassigned(conn) -> dict:
    """One-time placement of unconfirmed quarter-cost rows on their quarter tab, by approval date."""
    rows = conn.execute(
        "SELECT transaction_id, COALESCE(NULLIF(approval_date,''),posting_date) FROM transactions "
        "WHERE item=? AND user_confirmed=0 AND COALESCE(duplicate_of,'')='' "
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


def confirm_tab(store, tab: str) -> dict:
    """Books every confirmable row of the tab in one transaction and returns the counts."""
    if parse_tab(tab) is None:
        raise QuarterError('QUARTER_TAB_INVALID')
    booked, skipped = [], []
    now = utc_now()
    with store.lock:
        store.conn.execute('BEGIN IMMEDIATE')
        try:
            for row in pending_rows(store.conn, tab):
                transaction_id = row['transaction_id']
                amount = row['amount_krw']
                undated = not (row['approval_date'] or row['posting_date'])
                if row['transaction_direction'] != 'purchase' or type(amount) is not int or amount <= 0 or undated:
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
                    (transaction_id, row['batch_id'], ITEM, f'{tab} 기타비용', tab, '', amount,
                     row['merchant'] or '', day, 'purchase', row['source_hash'], now))
                store.conn.execute(
                    "UPDATE transactions SET user_confirmed=1, classification_state='confirmed' "
                    "WHERE transaction_id=?", (transaction_id,))
                store.log_change('quarter.booked', transaction_id, {'tab': tab, 'amount_krw': amount})
                booked.append(transaction_id)
            store.conn.execute('COMMIT')
        except Exception:
            store.conn.execute('ROLLBACK')
            raise
    return {'tab': tab, 'booked': len(booked), 'skipped': len(skipped)}
