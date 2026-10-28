"""Pure read-only HTML assembly helpers for the expense cleanup screen.

Extracted presentation responsibilities from webapp.card_flow:
- Cleanup card row HTML and review details assembly
- Cleanup ledger row HTML assembly
- Trip selection options markup
- Reason breakdown counter chips markup
- Snapshot state status note markup
- Pagination navigation markup
- Container section shell markup with CSS styles and scripts

This module is strictly presentation-only:
- NO database connections or SQL queries
- NO board objects or module globals passed
- NO financial matching, assignment, or classification judgments
- Exact preservation of legacy HTML structure, classes, escaping, and defaults
"""
from __future__ import annotations

from dataclasses import dataclass
import html
from typing import Callable, Mapping, Sequence


def default_esc(value: object) -> str:
    """Escape value for safe HTML insertion."""
    return html.escape("" if value is None else str(value), quote=True)


CLEANUP_STYLE = (
    "<style>#expense-cleanup{background:transparent;border:0;padding:0}"
    "#expense-cleanup .cleanup-breakdown{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 14px;font-size:13px}"
    "#expense-cleanup .cleanup-breakdown span{background:var(--shell-hover);border-radius:999px;padding:5px 10px}"
    "#expense-cleanup .cleanup-list{list-style:none;padding:0;margin:12px 0;display:grid;gap:12px}"
    "#expense-cleanup .cleanup-row{border:1px solid var(--shell-line);background:var(--shell-paper);border-radius:18px;padding:20px;min-width:0}"
    "#expense-cleanup .cleanup-card-head{display:flex;align-items:center;justify-content:space-between;"
    "gap:8px;margin:0 0 12px}"
    "#expense-cleanup .cleanup-card-head h3{margin:0;font-size:17px}"
    "#expense-cleanup .cleanup-info{display:flex;align-items:center;gap:12px;min-width:0}"
    "#expense-cleanup .cleanup-receipt-icon{display:grid;place-items:center;width:46px;height:46px;flex:none;"
    "border-radius:13px;background:var(--shell-hover);color:var(--shell-muted);font-size:27px}"
    "#expense-cleanup .cleanup-title{min-width:0;flex:1;display:flex;flex-direction:column;gap:2px}"
    "#expense-cleanup .cleanup-title strong{font-size:17px;overflow-wrap:anywhere}"
    "#expense-cleanup .cleanup-title small{color:var(--shell-muted)}"
    "#expense-cleanup .cleanup-badge{font-size:12px;font-weight:700;border-radius:999px;padding:5px 9px;"
    "background:var(--shell-hover);color:var(--shell-muted);flex:none}"
    "#expense-cleanup .cleanup-badge-protected{background:var(--shell-warn-bg);color:var(--shell-warn)}"
    "#expense-cleanup .cleanup-amount{font-size:24px;font-weight:800;margin:14px 0 4px;font-variant-numeric:tabular-nums}"
    "#expense-cleanup .cleanup-reason{font-size:13px;color:var(--shell-muted);margin:0 0 10px}"
    "#expense-cleanup .cleanup-form{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}"
    "#expense-cleanup .cleanup-form select{flex:1 1 160px;min-width:0}"
    "#expense-cleanup .cleanup-form input{flex:1 1 120px;min-width:0;height:34px}"
    "#expense-cleanup .cleanup-error{flex:0 0 100%;margin:0;color:var(--shell-danger)}"
    "#expense-cleanup .cleanup-review{margin-top:14px;border-top:1px solid var(--shell-line)}"
    "#expense-cleanup .cleanup-review>summary{cursor:pointer;font-weight:700;min-height:44px}"
    "#expense-cleanup .cleanup-review-note{margin:8px 0 0;color:var(--shell-muted);font-size:13px}"
    "#expense-cleanup .cleanup-protected{margin:8px 0 0;color:var(--shell-muted)}"
    "#expense-cleanup .cleanup-evidence{margin-top:6px;font-size:13px}"
    "#expense-cleanup .cleanup-evidence li{margin:6px 0;overflow-wrap:anywhere}"
    "#expense-cleanup .cleanup-amount{font-size:21px;margin:12px 0 6px;letter-spacing:-.02em}"
    "#expense-cleanup .cleanup-row{border-radius:12px;padding:16px;box-shadow:none}"
    "#expense-cleanup .cleanup-card-head{margin-bottom:10px}"
    "#expense-cleanup .cleanup-card-head h3{font-size:14px;font-weight:700;color:var(--shell-muted)}"
    "#expense-cleanup .cleanup-title strong{font-size:16px;line-height:1.45}"
    "#expense-cleanup .cleanup-receipt-icon{width:36px;height:36px;font-size:20px;border-radius:10px}"
    "#expense-cleanup .cleanup-reason{font-size:12px;line-height:1.6;margin-bottom:6px}"
    "#expense-cleanup .cleanup-review{margin-top:12px}"
    "#expense-cleanup .cleanup-review>summary{display:flex;align-items:center;min-height:44px;color:var(--shell-accent);padding:7px 0}"
    "#expense-cleanup .cleanup-evidence ul{padding-left:16px}"
    "#expense-cleanup .cleanup-merchant-compare{margin-top:12px;padding:8px 12px;border:1px solid var(--shell-line);border-radius:10px;background:var(--shell-hover)}"
    "#expense-cleanup .cleanup-merchant-compare>summary{cursor:pointer;min-height:44px;font-size:13px;font-weight:750;display:flex;align-items:center;gap:8px}"
    "#expense-cleanup .cleanup-mini-count{background:var(--shell-paper);border:1px solid var(--shell-line);border-radius:99px;padding:2px 8px;font-size:12px}"
    "#expense-cleanup .cleanup-evidence-meta{font-size:12px;line-height:1.55;color:var(--shell-muted);margin:7px 0}"
    "#expense-cleanup .cleanup-compare-list{display:grid;gap:8px;margin:12px 0}"
    "#expense-cleanup .cleanup-compare-row{border:1px solid var(--shell-line);background:var(--shell-paper);border-radius:9px;padding:12px;min-width:0}"
    "#expense-cleanup .cleanup-compare-row p{font-size:12px;margin:6px 0;color:var(--shell-muted)}"
    "#expense-cleanup .cleanup-compare-row a{display:inline-flex;align-items:center;min-height:38px}"
    "#expense-cleanup .cleanup-compare-main{display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:8px}"
    "#expense-cleanup .cleanup-compare-main strong{overflow-wrap:anywhere;min-width:0}"
    "#expense-cleanup .cleanup-compare-main b{white-space:nowrap;font-variant-numeric:tabular-nums}"
    "#expense-cleanup .cleanup-pages{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border-top:1px solid var(--shell-line);padding:12px 0}"
    "#expense-cleanup .cleanup-pages a{min-height:44px;display:inline-flex;align-items:center;padding:8px 12px;border:1px solid var(--shell-line);border-radius:9px}"
    "#expense-cleanup .cleanup-evidence-none{font-size:13px;color:var(--shell-muted);margin:6px 0 0}"
    "@media(max-width:550px){#expense-cleanup .cleanup-row{padding:16px}"
    "#expense-cleanup .cleanup-info{flex-wrap:wrap}"
    "}"
    "</style>"
)


@dataclass(frozen=True)
class CleanupCardRow:
    """Presentation DTO for a single card transaction row in expense cleanup."""
    tid: str
    batch: str
    revision: int
    held: bool
    merchant: str
    current_tab: str | None
    protected: bool
    label: str
    day: str | None
    amount: int | float
    reason: str
    review: str


@dataclass(frozen=True)
class CleanupLedgerRow:
    """Presentation DTO for an unassigned ledger expenditure row in expense cleanup."""
    row_id: str
    revision: int
    merchant_or_desc: str
    occurred_on: str | None
    item: str | None
    amount_krw: int | float


def render_cleanup_trip_options(
    trips: Sequence[Mapping[str, object]],
    *,
    esc: Callable[[object], str] = default_esc,
) -> str:
    """Assemble HTML options for trip assignment dropdown."""
    return "<option value=''>여행 선택</option>" + "".join(
        f"<option value='{esc(t['tab_id'])}'>{esc(t.get('display_key') or t['tab_id'])}</option>"
        for t in trips
    )


def render_cleanup_breakdown(
    card_breakdown: Mapping[str, int],
    ledger_total: int,
) -> str:
    """Assemble reason breakdown counter chips markup."""
    return (
        "<div class='cleanup-breakdown' aria-label='지출 정리 사유별 건수'>"
        f"<span>항목 미분류 {card_breakdown.get('no_item', 0):,}건</span>"
        f"<span>여행 미배정 {card_breakdown.get('no_trip', 0) + ledger_total:,}건</span>"
        f"<span>보류·오류 {card_breakdown.get('protected', 0):,}건</span></div>"
    )


def render_cleanup_snapshot_note(
    snapshot_context: Mapping[str, object] | None,
    *,
    esc: Callable[[object], str] = default_esc,
) -> str:
    """Assemble status note for OTA booking snapshot state."""
    if not snapshot_context:
        return ""
    snapshot_message = {
        "loading": "예약 근거를 불러오고 있습니다.",
        "refreshing": "예약 근거 갱신 중 · 최신 근거 확인이 필요합니다.",
        "error": "예약 근거 입력 오류 · 자료를 읽지 못했습니다. 잠시 뒤 다시 확인해 주세요.",
    }.get(str(snapshot_context.get("status") or ""), "")
    if not snapshot_message:
        return ""
    return "<p class='cleanup-protected' role='status'>" + esc(snapshot_message) + "</p>"


def render_cleanup_card_review(
    *,
    tid: str,
    detail: str,
    is_cancellation: bool,
    evidence: str,
    conflict_reason: str = "",
    parse_error: str = "",
    held: bool = False,
    reason: str = "",
    item: str = "",
    finance_label: str = "",
    esc: Callable[[object], str] = default_esc,
) -> str:
    """Assemble the <details class='cleanup-review'> section for a card transaction."""
    if is_cancellation:
        review = (
            f"<details class='cleanup-review'><summary>원결제·취소 근거 자세히 보기</summary>{evidence}"
            f"<p><a href='{esc(detail)}'>원결제 연결 자료 보기</a></p></details>"
        )
    elif conflict_reason or parse_error:
        review = (
            f"<details class='cleanup-review'><summary>상세 검토</summary>"
            f"<p class='cleanup-protected'>{'원본 충돌' if conflict_reason else '파싱 오류'} · "
            f"{esc(conflict_reason or parse_error)}</p>"
            f"<p><a href='{esc(detail)}'>카드 자료 전체 검토</a></p></details>"
        )
    elif held:
        review = (
            f"<details class='cleanup-review'><summary>상세 검토</summary>{evidence}"
            "<p class='cleanup-protected'>보류 중 · 여행 변경과 보류 해제는 카드 자료 전체 검토에서 "
            "명시적으로 확인해 주세요.</p>"
            f"<p><a href='{esc(detail)}'>카드 자료 전체 검토</a></p></details>"
        )
    else:
        review = (
            f"<details class='cleanup-review'><summary>상세 검토</summary>{evidence}"
            f"<p class='cleanup-review-note'>분류 근거 · {esc(reason)}</p>"
            f"<form class='cleanup-form'><select name='display_tab_id' aria-label='여행 선택'><option value=''>여행 선택</option></select>"
            f"<input name='item' aria-label='비용 항목' value='{esc(item or '')}' placeholder='비용 항목'>"
            "<button type='submit'>여행 수정</button><p class='cleanup-error' role='alert'></p></form></details>"
        )
    if not is_cancellation and finance_label:
        review += "<p class='cleanup-finance-status'>" + esc(finance_label) + "</p>"
    return review


def render_cleanup_card_row(
    row: CleanupCardRow | Mapping[str, object],
    *,
    esc: Callable[[object], str] = default_esc,
) -> str:
    """Assemble <li> HTML for a single card transaction row."""
    if isinstance(row, Mapping):
        tid = row["tid"]
        batch = row["batch"]
        revision = row["revision"]
        held = row["held"]
        merchant = row["merchant"]
        current_tab = row.get("current_tab")
        protected = row["protected"]
        label = row["label"]
        day = row.get("day")
        amount = row["amount"]
        reason = row["reason"]
        review = row["review"]
    else:
        tid = row.tid
        batch = row.batch
        revision = row.revision
        held = row.held
        merchant = row.merchant
        current_tab = row.current_tab
        protected = row.protected
        label = row.label
        day = row.day
        amount = row.amount
        reason = row.reason
        review = row.review

    badge_class = " cleanup-badge-protected" if protected else ""
    return (
        f"<li class='cleanup-row' data-kind='card' data-transaction='{esc(tid)}' data-batch='{esc(batch)}'"
        f" data-revision='{int(revision)}' data-held='{1 if held else 0}' data-merchant='{esc(merchant)}'"
        f" data-current-tab='{esc(current_tab or '')}'>"
        f"<div class='cleanup-card-head'><h3>카드 거래</h3>"
        f"<span class='cleanup-badge{badge_class}'>{label}</span></div>"
        f"<div class='cleanup-info'><span class='cleanup-receipt-icon' aria-hidden='true'>▤</span>"
        f"<div class='cleanup-title'><strong>{esc(merchant)}</strong><small>{esc(day or '')} · 카드 결제</small></div></div>"
        f"<div class='cleanup-amount'>{int(amount or 0):,}원</div>"
        f"<p class='cleanup-reason'>{esc(reason)}</p>{review}</li>"
    )


def render_cleanup_ledger_row(
    row: CleanupLedgerRow | Mapping[str, object],
    *,
    esc: Callable[[object], str] = default_esc,
) -> str:
    """Assemble <li> HTML for an unassigned ledger expenditure row."""
    if isinstance(row, Mapping):
        row_id = row["row_id"]
        revision = row["revision"]
        merchant_or_desc = row["merchant_or_desc"]
        occurred_on = row.get("occurred_on")
        item = row.get("item")
        amount_krw = row["amount_krw"]
    else:
        row_id = row.row_id
        revision = row.revision
        merchant_or_desc = row.merchant_or_desc
        occurred_on = row.occurred_on
        item = row.item
        amount_krw = row.amount_krw

    return (
        f"<li class='cleanup-row' data-kind='ledger' data-row-id='{esc(row_id)}' data-revision='{int(revision)}'>"
        "<div class='cleanup-card-head'><h3>여행 지정</h3>"
        "<span class='cleanup-badge'>여행 미배정</span></div>"
        f"<div class='cleanup-info'><span class='cleanup-receipt-icon' aria-hidden='true'>▤</span>"
        f"<div class='cleanup-title'><strong>{esc(merchant_or_desc)}</strong>"
        f"<small>{esc(occurred_on or '')} · {esc(item or '항목 없음')}</small></div></div>"
        f"<div class='cleanup-amount'>{int(amount_krw or 0):,}원</div>"
        f"<form class='cleanup-form'><select name='display_tab_id' aria-label='여행 선택'><option value=''>여행 선택</option></select>"
        "<button type='submit'>여행 지정</button><p class='cleanup-error' role='alert'></p></form></li>"
    )


def render_cleanup_empty() -> str:
    """Fallback <li> markup when there are no cleanup items."""
    return '<li class="muted">정리할 지출이 없습니다.</li>'


def render_cleanup_pagination(
    page: int,
    pages: int,
    total: int,
) -> str:
    """Assemble navigation markup when total items span multiple pages."""
    if pages <= 1:
        return ""
    previous = (
        f"<a href='/import?cleanup_page={page - 1}'>이전 20건</a>"
        if page > 1 else "<span>이전 20건</span>"
    )
    following = (
        f"<a href='/import?cleanup_page={page + 1}'>다음 20건</a>"
        if page < pages else "<span>다음 20건</span>"
    )
    return (
        f"<nav class='cleanup-pages'><p class='muted'>{total}건을 20건씩 봅니다 · {page}/{pages}페이지</p>"
        f"{previous} · {following}</nav>"
    )


def render_cleanup_section(
    *,
    total: int,
    breakdown_html: str,
    note_html: str,
    options_html: str,
    body_html: str,
    nav_html: str,
    script_html: str,
    style_html: str = CLEANUP_STYLE,
) -> str:
    """Assemble the top-level <section id='expense-cleanup'> container."""
    return (
        style_html
        + "<section id='expense-cleanup' aria-label='정리할 지출'>"
        f"<h2>근거 확인이 필요한 거래 <span id='cleanup-count' data-total='{total}'>{total}건</span></h2>"
        f"{breakdown_html}{note_html}"
        "<p class='muted'>아래 거래의 예약 연결, 여행 배정, 금융 보호 사유를 확인해 주세요. 이 화면을 조회하는 동안 장부를 변경하지 않습니다.</p>"
        f"<template id='cleanup-trip-options'>{options_html}</template>"
        f"<ul class='cleanup-list'>{body_html}</ul>{nav_html}"
        f"<script>{script_html}</script></section>"
    )
