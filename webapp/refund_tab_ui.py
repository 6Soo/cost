"""Pure read projection and HTML assembly helpers for the refund tab.

Extracted responsibilities from webapp.refund_tab:
- assemble_refund_groups: Project raw transaction records and refund links into sorted, complete refund groups
- filter_refund_groups: Filter visible refund groups by query and kind
- render_refund_line: Assemble single line markup for original purchase or refund
- render_refund_card: Assemble section card markup for a refund group
- render_refund_tab: Assemble full tab HTML with styles, summary, and cards

Strictly presentation/projection only:
- No database connections or SQL queries
- Preserves exact legacy HTML structure, classes, escaping, and formatting semantics
"""
import html
from urllib.parse import quote


def assemble_refund_groups(sources, links, *, is_preserved_fn=None):
    """Assemble complete, sorted refund groups outside preserved history periods."""
    grouped = {}
    for refund_id, link in links.items():
        original = link['original_id']
        grouped.setdefault(original, [dict(sources[original], inferred=bool(link.get('inferred')),
                                          refund_basis=link.get('basis') or 'original_approval_number')]
                           ).append(sources[refund_id])
    if is_preserved_fn is None:
        from .history_policy import preserved_periods
        is_preserved_fn = preserved_periods
    complete = [rows for rows in grouped.values()
                if sum(r['amount_krw'] for r in rows) == 0
                and not is_preserved_fn([(r['occurred_on'], r['occurred_on']) for r in rows])]
    return sorted(complete, key=lambda rows: (
        not bool(rows[0]['occurred_on']), rows[0]['occurred_on'], rows[0]['transaction_id']))


def filter_refund_groups(all_groups, *, query='', kind='', saved=None):
    """Filter visible refund groups by query string and direction kind."""
    saved = saved or {}
    visible = [g for g in all_groups if not query or any(
        query in ' '.join(str(r.get(k) or '') for k in ('merchant', 'item', 'occurred_on'))
        or query in str(saved.get(r['transaction_id'], {}).get('description') or '')
        for r in g)]
    if kind == 'in':
        visible = []
    return visible


def render_refund_line(source, index, row=None, trip=''):
    """Assemble single line HTML for an original purchase or refund."""
    esc = html.escape
    money = lambda amount: f'{amount:,}원'
    state = '장부 기록됨' if row else '미기록'
    detail = (f"<a href='/row?id={quote(row['row_id'])}&amp;back={quote('/board?tab=refunds', safe='')}'>자료 검토</a>"
              if row else "<a href='/import'>지출 정리</a>")
    return (f"<div class='refund-line'><span>{'원결제' if index == 0 else '환불'} · "
            f"{esc(source['occurred_on'] or '날짜 확인 필요')}</span>"
            f"<strong>{money(source['amount_krw'])}</strong>"
            f"<span>{esc(source['merchant'])} · {esc(row.get('item') or source['item']) if row else esc(source['item'])}</span>"
            f"<span>{esc(state)}{' · ' + esc(trip) if trip else ''} · {detail}</span></div>")


def render_refund_card(group, saved=None, trip_names=None):
    """Assemble section card HTML for one refund group."""
    saved = saved or {}
    names = trip_names or {}
    money = lambda amount: f'{amount:,}원'
    net = sum(r['amount_krw'] for r in group)
    title = '전액 환불' if net == 0 else '초과 환불 확인 필요' if net < 0 else '부분 환불'
    if group[0].get('inferred'):
        title = '원결제 추론 연결 · 기록 준비 · 환급 완료 여부 별도'
    rows = []
    for index, source in enumerate([group[0]] + sorted(group[1:], key=lambda r: (
            not bool(r['occurred_on']), r['occurred_on'], r['transaction_id']))):
        row = saved.get(source['transaction_id'])
        trip = names.get(row.get('display_tab_id'), '미배정') if row else ''
        rows.append(render_refund_line(source, index, row=row, trip=trip))
    return (f"<section class='ui-card refund-card'><h2 class='ui-card__heading'>{title} · 순액 {money(net)}</h2>"
            f"{''.join(rows)}</section>")


def render_refund_tab(visible, saved=None, trip_names=None):
    """Assemble full refunds tab HTML with summary and cards."""
    saved = saved or {}
    trip_names = trip_names or {}
    money = lambda amount: f'{amount:,}원'
    gross = sum(g[0]['amount_krw'] for g in visible)
    refund = sum(r['amount_krw'] for g in visible for r in g[1:])
    cards = [render_refund_card(group, saved=saved, trip_names=trip_names) for group in visible]
    return (f"<div class='sum tnum'><span>카드 환불 {len(visible)}쌍</span><div>원결제 <b>{money(gross)}</b></div>"
            f"<div>환불 <b>{money(refund)}</b></div><div>순액 <b>{money(gross + refund)}</b></div></div>"
            + (''.join(cards) or "<p class='ui-state'>환불 쌍이 없습니다.</p>"))
