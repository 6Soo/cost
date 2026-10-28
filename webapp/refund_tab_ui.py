"""Pure read projection and HTML assembly helpers for the refund tab.

Extracted responsibilities from webapp.refund_tab:
- assemble_refund_groups: Project raw transaction records and refund links into sorted, complete refund groups
- filter_refund_groups: Filter visible refund groups by query and kind
- render_refund_line: Assemble single line markup for original purchase or refund
- render_refund_card: Assemble section card markup for a refund group
- render_refund_summary: Assemble summary bar with gross, refund, and net amounts
- render_refund_tab: Assemble full tab HTML with styles, summary, and cards

This module is strictly presentation-only:
- NO database connections or SQL queries
- NO store or board objects passed
- NO mutation of input records or links
- Exact preservation of legacy HTML structure, classes, escaping, and formatting
"""
from __future__ import annotations

import html
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote


def default_esc(value: object) -> str:
    """Escape value for safe HTML insertion."""
    return html.escape("" if value is None else str(value))


def format_money(amount: int | float | None) -> str:
    """Format numeric currency value with thousands separator and 원 suffix."""
    val = int(amount or 0)
    return f"{val:,}원"


REFUND_TAB_STYLE = (
    "<style>.refund-card{border:1px solid var(--line,#d7ded8);border-radius:10px;padding:12px;margin:12px 0}"
    ".refund-card h2{font-size:16px}.refund-line{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;padding:10px 0;border-top:1px solid var(--line,#d7ded8)}"
    ".refund-line span{overflow-wrap:anywhere}.refund-line strong{white-space:nowrap}"
    "@media(max-width:480px){.refund-line{grid-template-columns:minmax(0,1fr)}.refund-line strong{font-size:18px}}</style>"
)


def assemble_refund_groups(
    sources: Mapping[str, Mapping[str, Any]],
    links: Mapping[str, Mapping[str, Any]],
    *,
    is_preserved_fn: Callable[[list[tuple[Any, Any]]], bool] | None = None,
) -> list[list[dict[str, Any]]]:
    """Group refund transactions with their corresponding original purchases.

    Filters for complete groups (net amount == 0) outside preserved periods,
    and sorts groups stably by original payment date and transaction ID.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for refund_id, link in links.items():
        original = link["original_id"]
        orig_src = sources.get(original)
        if orig_src is None:
            continue
        grouped.setdefault(
            original,
            [
                dict(
                    orig_src,
                    inferred=bool(link.get("inferred")),
                    refund_basis=link.get("basis") or "original_approval_number",
                )
            ],
        ).append(dict(sources[refund_id]))

    complete: list[list[dict[str, Any]]] = []
    for rows in grouped.values():
        if sum(r.get("amount_krw") or 0 for r in rows) != 0:
            continue
        if is_preserved_fn is not None:
            periods = [(r.get("occurred_on"), r.get("occurred_on")) for r in rows]
            if is_preserved_fn(periods):
                continue
        complete.append(rows)

    return sorted(
        complete,
        key=lambda rows: (
            not bool(rows[0].get("occurred_on")),
            rows[0].get("occurred_on") or "",
            rows[0].get("transaction_id") or "",
        ),
    )


def filter_refund_groups(
    all_groups: Sequence[Sequence[Mapping[str, Any]]],
    *,
    query: str = "",
    kind: str = "",
    saved: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Sequence[Mapping[str, Any]]]:
    """Filter refund groups matching query and kind criteria."""
    if kind == "in":
        return []
    if not query:
        return list(all_groups)
    saved_rows = saved or {}
    return [
        g
        for g in all_groups
        if any(
            query in " ".join(str(r.get(k) or "") for k in ("merchant", "item", "occurred_on"))
            or query in str(saved_rows.get(r.get("transaction_id"), {}).get("description") or "")
            for r in g
        )
    ]


def render_refund_line(
    source: Mapping[str, Any],
    index: int,
    row: Mapping[str, Any] | None = None,
    trip_name: str = "",
    *,
    esc: Callable[[object], str] = default_esc,
    money: Callable[[int | float | None], str] = format_money,
) -> str:
    """Assemble single line HTML for either an original purchase or a refund."""
    role_label = "원결제" if index == 0 else "환불"
    date_str = esc(source.get("occurred_on") or "날짜 확인 필요")
    amount_str = money(source.get("amount_krw"))
    merchant_str = esc(source.get("merchant"))
    item_str = esc(row.get("item") or source.get("item")) if row else esc(source.get("item"))
    state = "장부 기록됨" if row else "미기록"
    trip_str = f" · {esc(trip_name)}" if trip_name else ""
    if row:
        row_id = quote(str(row.get("row_id") or ""))
        back_url = quote("/board?tab=refunds", safe="")
        detail = f"<a href='/row?id={row_id}&amp;back={back_url}'>자료 검토</a>"
    else:
        detail = "<a href='/import'>지출 정리</a>"

    return (
        f"<div class='refund-line'><span>{role_label} · {date_str}</span>"
        f"<strong>{amount_str}</strong>"
        f"<span>{merchant_str} · {item_str}</span>"
        f"<span>{esc(state)}{trip_str} · {detail}</span></div>"
    )


def render_refund_card(
    group: Sequence[Mapping[str, Any]],
    saved: Mapping[str, Mapping[str, Any]] | None = None,
    trip_names: Mapping[str, str] | None = None,
    *,
    esc: Callable[[object], str] = default_esc,
    money: Callable[[int | float | None], str] = format_money,
) -> str:
    """Assemble section card HTML for one refund group."""
    saved_rows = saved or {}
    names = trip_names or {}
    net = sum(r.get("amount_krw") or 0 for r in group)
    title = "전액 환불" if net == 0 else "초과 환불 확인 필요" if net < 0 else "부분 환불"
    if group and group[0].get("inferred"):
        title = "원결제 추론 연결 · 기록 보류 · 환급 완료 아님"

    sorted_refunds = sorted(
        group[1:],
        key=lambda r: (
            not bool(r.get("occurred_on")),
            r.get("occurred_on") or "",
            r.get("transaction_id") or "",
        ),
    )
    ordered_items = [group[0]] + sorted_refunds
    lines = []
    for index, source in enumerate(ordered_items):
        tid = source.get("transaction_id")
        row = saved_rows.get(tid)
        trip = names.get(row.get("display_tab_id"), "미배정") if row else ""
        lines.append(render_refund_line(source, index, row=row, trip_name=trip, esc=esc, money=money))

    return (
        f"<section class='refund-card'><h2>{title} · 순액 {money(net)}</h2>"
        f"{''.join(lines)}</section>"
    )


def render_refund_summary(
    visible: Sequence[Sequence[Mapping[str, Any]]],
    *,
    money: Callable[[int | float | None], str] = format_money,
) -> str:
    """Assemble summary bar with count, gross purchase, refund total, and net amount."""
    gross = sum(g[0].get("amount_krw") or 0 for g in visible if g)
    refund = sum(r.get("amount_krw") or 0 for g in visible for r in g[1:])
    net = gross + refund
    return (
        f"<div class='sum tnum'><span>카드 환불 {len(visible)}쌍</span>"
        f"<div>원결제 <b>{money(gross)}</b></div>"
        f"<div>환불 <b>{money(refund)}</b></div>"
        f"<div>순액 <b>{money(net)}</b></div></div>"
    )


def render_refund_tab(
    visible: Sequence[Sequence[Mapping[str, Any]]],
    saved: Mapping[str, Mapping[str, Any]] | None = None,
    trip_names: Mapping[str, str] | None = None,
    *,
    esc: Callable[[object], str] = default_esc,
    money: Callable[[int | float | None], str] = format_money,
    style_html: str = REFUND_TAB_STYLE,
) -> str:
    """Assemble complete HTML presentation for the refunds tab."""
    summary_html = render_refund_summary(visible, money=money)
    cards = [
        render_refund_card(group, saved=saved, trip_names=trip_names, esc=esc, money=money)
        for group in visible
    ]
    cards_html = "".join(cards) or "<p>환불 쌍이 없습니다.</p>"
    return style_html + summary_html + cards_html
