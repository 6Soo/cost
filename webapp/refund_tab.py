"""연결이 확인된 환불 묶음의 읽기 전용 표시. 회계 귀속은 변경하지 않는다."""
import sqlite3

from app.partial_refund import refund_links

from . import read_scope, refund_tab_ui


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
    # Preserved history is excluded from new cleanup work, not from this
    # read-only history tab. Keep every source amount and accounting decision.
    return refund_tab_ui.assemble_refund_groups(sources, links, is_preserved_fn=lambda periods: False)


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
    completed = {r['transaction_id'] for group in all_groups for r in group}
    return (refund_tab_ui.render_refund_tab(visible, saved=saved, trip_names=names)
            + render_settlement_review(store, completed, query=query, kind=kind))


def render_settlement_review(store, completed=(), *, query='', kind=''):
    """Keep reviewed nonzero/unlinked cancellations visible without booking them.

    A refund-tab classification is a review disposition, not proof of a refund.
    Financial holds and the original source remain unchanged by this read path.
    """
    if store is None or kind == 'in':
        return ''
    if not store.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='transactions'").fetchone():
        return ''
    import html
    from urllib.parse import urlencode
    rows = store.conn.execute(
        "SELECT t.transaction_id,t.merchant,t.amount_krw,"
        "COALESCE(NULLIF(t.approval_date,''),t.posting_date),d.description,d.note,"
        "EXISTS(SELECT 1 FROM ledger_entries l WHERE l.transaction_id=t.transaction_id),"
        "COALESCE(h.reason,'') FROM transactions t "
        "JOIN review_decisions d ON d.transaction_id=t.transaction_id "
        "AND d.revision=(SELECT MAX(d2.revision) FROM review_decisions d2 WHERE d2.transaction_id=t.transaction_id) "
        "LEFT JOIN transaction_review_holds h ON h.transaction_id=t.transaction_id "
        "WHERE d.display_tab_id='refunds' AND t.classification_state!='preserved' "
        "ORDER BY COALESCE(NULLIF(t.approval_date,''),t.posting_date) DESC,t.transaction_id").fetchall()
    esc = html.escape
    cards = []
    for tid, merchant, amount, day, description, note, booked, hold in rows:
        if tid in completed or (query and query not in ' '.join(str(v or '') for v in (merchant,day,description,note))):
            continue
        href = '/board?' + urlencode({'row': 'card-' + tid})
        status = '내부 장부 기록 있음' if booked else '내부 장부 미기록'
        cards.append("<section class='ui-card refund-card'><h3>" + esc(merchant or '') + '</h3>'
                     + '<p>' + esc(day or '날짜 확인 필요') + f' · {amount:,}원</p>'
                     + '<p>' + esc(description or '취소 정산 근거 확인 중') + '</p>'
                     + '<p>' + esc(status) + ' · 실제 환급 완료를 뜻하지 않습니다.</p>'
                     + ('<p>' + esc(hold) + '</p>' if hold else '')
                     + '<details><summary>검토 근거</summary><p>' + esc(note or '') + '</p></details>'
                     + "<a href='" + esc(href, quote=True) + "'>카드 근거 보기</a></section>")
    if not cards:
        return ''
    return ("<section id='refund-settlement-review'><h2>취소 정산 확인 중 · " + str(len(cards))
            + '건</h2><p>분류가 끝난 취소 내역입니다. 원결제 연결·내부 기록·실제 환급은 각각 확인합니다.</p>'
            + ''.join(cards) + '</section>')
