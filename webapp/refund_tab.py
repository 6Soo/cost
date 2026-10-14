"""연결이 확인된 환불 묶음의 읽기 전용 표시. 회계 귀속은 변경하지 않는다."""
import html
import sqlite3
from urllib.parse import quote

from app.partial_refund import refund_links

from . import read_scope


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
    grouped = {}
    for refund_id, link in links.items():
        original = link['original_id']
        grouped.setdefault(original, [sources[original]]).append(sources[refund_id])
    purchases = {}
    for r in records:
        if r[9] == 'purchase' and r[2] > 0 and r[10] is None and not r[11] and not r[12] and r[7]:
            purchases.setdefault((r[5], r[6], r[7]), []).append(r[0])
    for r in records:
        if r[9] != 'cancellation' or r[2] >= 0 or r[8] or r[10] is not None or r[11] or r[12]:
            continue
        matches = purchases.get((r[5], r[6], r[7]), [])
        if len(matches) == 1:
            grouped.setdefault(matches[0], [sources[matches[0]]]).append(sources[r[0]])
    from .history_policy import preserved_periods
    complete = [rows for rows in grouped.values()
                if sum(r['amount_krw'] for r in rows) == 0
                and not preserved_periods([(r['occurred_on'], r['occurred_on']) for r in rows])]
    return sorted(complete, key=lambda rows: (
        not bool(rows[0]['occurred_on']), rows[0]['occurred_on'], rows[0]['transaction_id']))


def member_ids(store):
    return read_scope.remember(("refund_member_ids", id(store)), lambda: _member_ids(store))


def _member_ids(store):
    from . import ledger_board as board
    saved = {r.get('source_event_id'): r for r in board._expense_rows()}
    return {r['transaction_id'] for group in groups(store)
            if all(r['transaction_id'] in saved for r in group)
            and sum(saved[r['transaction_id']]['amount_krw'] for r in group) == 0
            and len({saved[r['transaction_id']].get('display_tab_id') for r in group}) == 1
            for r in group}


def render(store, query='', kind=''):
    from . import ledger_board as board
    all_groups = groups(store)
    saved = {r.get('source_event_id'): r for r in board._expense_rows()}
    names = {t['tab_id']: t['display_key'] for t in board.live_trips(include_archived=True)}
    visible = [g for g in all_groups if not query or any(
        query in ' '.join(str(r.get(k) or '') for k in ('merchant', 'item', 'occurred_on'))
        or query in str(saved.get(r['transaction_id'], {}).get('description') or '')
        for r in g)]
    if kind == 'in':
        visible = []
    esc = html.escape
    money = lambda amount: f'{amount:,}원'
    gross = sum(g[0]['amount_krw'] for g in visible)
    refund = sum(r['amount_krw'] for g in visible for r in g[1:])
    cards = []
    for group in visible:
        net = sum(r['amount_krw'] for r in group)
        title = '전액 환불' if net == 0 else '초과 환불 확인 필요' if net < 0 else '부분 환불'
        rows = []
        for index, source in enumerate([group[0]] + sorted(group[1:], key=lambda r: (
                not bool(r['occurred_on']), r['occurred_on'], r['transaction_id']))):
            row = saved.get(source['transaction_id'])
            state = '장부 기록됨' if row else '미기록'
            trip = names.get(row.get('display_tab_id'), '미배정') if row else ''
            detail = (f"<a href='/row?id={quote(row['row_id'])}&amp;back={quote('/board?tab=refunds', safe='')}'>자료 검토</a>"
                      if row else "<a href='/import'>지출 정리</a>")
            rows.append(f"<div class='refund-line'><span>{'원결제' if index == 0 else '환불'} · "
                        f"{esc(source['occurred_on'] or '날짜 확인 필요')}</span>"
                        f"<strong>{money(source['amount_krw'])}</strong>"
                        f"<span>{esc(source['merchant'])} · {esc(row.get('item') or source['item']) if row else esc(source['item'])}</span>"
                        f"<span>{esc(state)}{' · ' + esc(trip) if trip else ''} · {detail}</span></div>")
        cards.append(f"<section class='refund-card'><h2>{title} · 순액 {money(net)}</h2>{''.join(rows)}</section>")
    return ("<style>.refund-card{border:1px solid var(--line,#d7ded8);border-radius:10px;padding:12px;margin:12px 0}"
            ".refund-card h2{font-size:16px}.refund-line{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;padding:10px 0;border-top:1px solid var(--line,#d7ded8)}"
            ".refund-line span{overflow-wrap:anywhere}.refund-line strong{white-space:nowrap}"
            "@media(max-width:480px){.refund-line{grid-template-columns:minmax(0,1fr)}.refund-line strong{font-size:18px}}</style>"
            f"<div class='sum tnum'><span>카드 환불 {len(visible)}쌍</span><div>원결제 <b>{money(gross)}</b></div>"
            f"<div>환불 <b>{money(refund)}</b></div><div>순액 <b>{money(gross + refund)}</b></div></div>"
            + (''.join(cards) or '<p>환불 쌍이 없습니다.</p>'))
