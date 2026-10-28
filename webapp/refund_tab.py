"""연결이 확인된 환불 묶음의 읽기 전용 표시. 회계 귀속은 변경하지 않는다."""
import sqlite3

from app.partial_refund import refund_links

from . import read_scope, refund_tab_ui
from .history_policy import preserved_periods


def groups(store):
    if store is None:
        return []
    try:
        records = store.conn.execute(
            "SELECT transaction_id, merchant, amount_krw, "
            "COALESCE(NULLIF(approval_date,''),posting_date), item, issuer, card_tail, approval_number, "
            "original_approval_number, transaction_direction, duplicate_of, conflict_reason, parse_error "
            "FROM transactions ORDER BY transaction_id").fetchall()
    except sqlite3.OperationalError as exc:
        if 'no such table: transactions' in str(exc):
            return []
        raise
    sources = {r[0]: dict(transaction_id=r[0], merchant=r[1], amount_krw=r[2],
                          occurred_on=r[3], item=r[4]) for r in records}
    links = refund_links(store.conn, list(sources))
    return refund_tab_ui.assemble_refund_groups(sources, links, is_preserved_fn=preserved_periods)


def member_ids(store):
    return read_scope.remember(("refund_member_ids", id(store)), lambda: _member_ids(store))


def _member_ids(store):
    from . import ledger_board as board
    saved = {r.get('source_event_id'): r for r in board._expense_rows()}
    return {r['transaction_id'] for group in groups(store)
            if not group[0].get('inferred') and all(r['transaction_id'] in saved for r in group)
            and sum(saved[r['transaction_id']]['amount_krw'] for r in group) == 0
            and len({saved[r['transaction_id']].get('display_tab_id') for r in group}) == 1
            for r in group}


def render(store, query='', kind=''):
    from . import ledger_board as board
    all_groups = groups(store)
    saved = {r.get('source_event_id'): r for r in board._expense_rows()}
    names = {t['tab_id']: t['display_key'] for t in board.live_trips(include_archived=True)}
    visible = refund_tab_ui.filter_refund_groups(all_groups, query=query, kind=kind, saved=saved)
    return refund_tab_ui.render_refund_tab(visible, saved=saved, trip_names=names)
