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
from typing import Any, Callable, Mapping, Sequence


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
    "background:var(--shell-hover);color:var(--shell-muted);flex:0 1 auto;min-width:0;"
    "max-width:100%;white-space:normal;overflow-wrap:anywhere;box-sizing:border-box}"
    "#expense-cleanup .cleanup-badge-protected{background:var(--shell-warn-bg);color:var(--shell-warn)}"
    "#expense-cleanup .cleanup-amount{font-size:24px;font-weight:800;margin:14px 0 4px;font-variant-numeric:tabular-nums}"
    "#expense-cleanup .cleanup-reason{font-size:13px;color:var(--shell-muted);margin:0 0 10px}"
    "#expense-cleanup .cleanup-assignment{font-size:13px;line-height:1.6;margin:0 0 6px;overflow-wrap:anywhere}"
    "#expense-cleanup .cleanup-form{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr) auto;gap:8px;align-items:end;margin:12px 0 0}"
    "#expense-cleanup .cleanup-form label{display:grid;gap:4px;min-width:0;font-size:12px;color:var(--shell-muted)}"
    "#expense-cleanup .cleanup-form select,#expense-cleanup .cleanup-form input{width:100%;min-width:0;min-height:44px;box-sizing:border-box;font-size:14px}"
    "#expense-cleanup .cleanup-form button{min-height:44px;margin:0;white-space:nowrap}"
    "#expense-cleanup .cleanup-editor-title{font-size:13px;font-weight:700;margin:12px 0 0}"
    "#expense-cleanup .cleanup-save-note{font-size:12px;color:var(--shell-muted);margin:6px 0 0}"
    "#expense-cleanup .cleanup-form .cleanup-error{grid-column:1/-1}"
    "#expense-cleanup .cleanup-error:empty{display:none}"
    "#expense-cleanup .cleanup-error{flex:0 0 100%;margin:0;color:var(--shell-danger)}"
    "#expense-cleanup .cleanup-review{margin-top:14px;border-top:1px solid var(--shell-line)}"
    "#expense-cleanup .cleanup-review>summary{cursor:pointer;font-weight:700;min-height:44px}"
    "#expense-cleanup .cleanup-review>summary{display:flex;align-items:center;gap:8px;list-style:none;font-size:13px}"
    "#expense-cleanup .cleanup-review>summary::-webkit-details-marker{display:none}"
    "#expense-cleanup .cleanup-review>summary::after{content:'';width:7px;height:7px;margin-left:auto;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:rotate(45deg);flex:0 0 7px}"
    "#expense-cleanup .cleanup-review[open]>summary::after{transform:rotate(225deg)}"
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
    "#expense-cleanup .action-queue-summary{display:grid;gap:4px;border:1px solid var(--shell-line);"
    "border-radius:12px;padding:14px;margin:12px 0;background:var(--shell-paper)}"
    "#expense-cleanup .action-queue-summary h2,#expense-cleanup .action-queue-summary p{margin:0}"
    "#expense-cleanup .action-queue-summary a{display:inline-flex;align-items:center;min-height:44px;overflow-wrap:anywhere}"
    "#expense-cleanup .action-queue-summary h2 a{color:var(--shell-accent);text-underline-offset:3px}"
    "#expense-cleanup .cleanup-review a{display:inline-flex;align-items:center;min-height:44px}"
    "#expense-cleanup .cleanup-diagnostics{border-top:1px solid var(--shell-line);margin-top:16px;padding-top:8px}"
    "#expense-cleanup .cleanup-diagnostics>summary{min-height:44px;font-weight:700}"
    "#expense-cleanup .cleanup-diagnostic-note{color:var(--shell-muted);font-size:13px}"
    "@media(max-width:550px){#expense-cleanup .cleanup-list{gap:0}#expense-cleanup .cleanup-row{padding:12px 0;border:0;border-bottom:1px solid var(--shell-line);border-radius:0}"
    "#expense-cleanup .cleanup-info{flex-wrap:wrap}#expense-cleanup .cleanup-receipt-icon{display:none}"
    "#expense-cleanup .cleanup-card-head{margin-bottom:5px}#expense-cleanup .cleanup-amount{font-size:19px;margin:4px 0}"
    "#expense-cleanup .cleanup-assignment{line-height:1.4;margin-bottom:3px}"
    "#expense-cleanup .cleanup-form{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}"
    "#expense-cleanup .cleanup-form button{grid-column:1/-1;justify-self:end;padding:8px 16px}"
    "}"
    "</style>"
)


@dataclass(frozen=True)
class CleanupCardRow:
    """Presentation DTO for a single card transaction row in expense cleanup."""
    tid: Any
    batch: Any
    revision: Any
    held: Any
    merchant: Any
    current_tab: Any
    protected: bool
    label: Any
    day: Any
    amount: Any
    reason: Any
    review: Any
    refund_group_original: str = ""
    assignment_text: str = ""


@dataclass(frozen=True)
class CleanupLedgerRow:
    """Presentation DTO for an unassigned ledger expenditure row in expense cleanup."""
    row_id: Any
    revision: Any
    merchant_or_desc: Any
    occurred_on: Any
    item: Any
    amount_krw: Any


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
    """Assemble non-protective cleanup counters without exposing safety holds."""
    return (
        "<div class='cleanup-breakdown' aria-label='지출 정리 사유별 건수'>"
        f"<span>항목 미분류 {card_breakdown.get('no_item', 0):,}건</span>"
        f"<span>여행 미배정 {card_breakdown.get('no_trip', 0) + ledger_total:,}건</span></div>"
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
    }.get(snapshot_context.get("status"), "")
    if not snapshot_message:
        return ""
    return "<p class='cleanup-protected' role='status'>" + esc(snapshot_message) + "</p>"


def render_cleanup_card_review(
    *,
    detail: object,
    is_cancellation: bool,
    evidence: object,
    conflict_reason: object = None,
    parse_error: object = None,
    held: bool = False,
    finance_related: bool = False,
    reason: object = None,
    item: object = None,
    finance_label: object = None,
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
            f"<details class='cleanup-review'><summary>거래 근거 자세히 보기</summary>{evidence}"
            "<p class='cleanup-protected'>거래 근거를 확인하고 있습니다.</p>"
            f"<p><a href='{esc(detail)}'>원본 자료 보기</a></p></details>"
        )
    elif finance_related:
        review = (
            "<p class='cleanup-review-note'>금융 관계와 원본 증빙을 읽기 전용으로 표시합니다. "
            "실제 카드 환급 여부나 내부 기록 완료를 대신 확정하지 않습니다.</p>"
            f"<details class='cleanup-review'><summary>거래 근거 자세히 보기</summary>{evidence}"
            f"<p><a href='{esc(detail)}'>카드 자료 전체 검토</a></p></details>"
        )
    else:
        review = (
            "<p class='cleanup-editor-title'>여행·항목 수정</p>"
            "<form class='cleanup-form'><label>여행<select name='display_tab_id' aria-label='여행 선택'><option value=''>여행 선택</option></select></label>"
            f"<label>비용 항목<input name='item' aria-label='비용 항목' value='{esc(item or '')}' placeholder='예: 식비' required></label>"
            "<button type='submit'>변경 저장</button><p class='cleanup-error' role='alert'></p></form>"
            "<p class='cleanup-save-note'>COST의 여행·항목에 저장됩니다.</p>"
            f"<details class='cleanup-review'><summary>예약·분류 근거 보기</summary>{evidence}"
            f"<p><a href='{esc(detail)}'>카드 자료 전체 검토</a></p></details>"
        )
    if not is_cancellation and finance_label and finance_label != reason:
        review += "<p class='cleanup-finance-status'>" + esc(finance_label) + "</p>"
    return review


def render_cleanup_card_row(
    row: CleanupCardRow,
    *,
    esc: Callable[[object], str] = default_esc,
) -> str:
    """Assemble <li> HTML for a single card transaction row."""
    badge_class = " cleanup-badge-protected" if row.protected else ""
    return (
        f"<li class='cleanup-row' data-kind='card' data-transaction='{esc(row.tid)}' data-batch='{esc(row.batch)}'"
        f" data-revision='{int(row.revision)}' data-held='{1 if row.held else 0}' data-merchant='{esc(row.merchant)}'"
        f" data-current-tab='{esc(row.current_tab or '')}'>"
        f"<div class='cleanup-card-head'>"
        f"<span class='cleanup-badge{badge_class}'>{row.label}</span></div>"
        f"<div class='cleanup-info'><span class='cleanup-receipt-icon' aria-hidden='true'>▤</span>"
        f"<div class='cleanup-title'><strong>{esc(row.merchant)}</strong><small>{esc(row.day or '')} · 카드 결제</small></div></div>"
        f"<div class='cleanup-amount'>{int(row.amount or 0):,}원</div>"
        + (f"<p class='cleanup-assignment'>{esc(row.assignment_text)}</p>"
           if row.assignment_text else "")
        + f"<p class='cleanup-reason'>{esc(row.reason)}</p>{row.review}"
        + "</li>"
    )


def render_cleanup_ledger_row(
    row: CleanupLedgerRow,
    *,
    esc: Callable[[object], str] = default_esc,
) -> str:
    """Assemble <li> HTML for an unassigned ledger expenditure row."""
    return (
        f"<li class='cleanup-row' data-kind='ledger' data-row-id='{esc(row.row_id)}' data-revision='{int(row.revision)}'>"
        "<div class='cleanup-card-head'><h3>여행 지정</h3>"
        "<span class='cleanup-badge'>장부 배정 상태</span></div>"
        f"<div class='cleanup-info'><span class='cleanup-receipt-icon' aria-hidden='true'>▤</span>"
        f"<div class='cleanup-title'><strong>{esc(row.merchant_or_desc)}</strong>"
        f"<small>{esc(row.occurred_on or '')} · {esc(row.item or '항목 없음')}</small></div></div>"
        f"<div class='cleanup-amount'>{int(row.amount_krw or 0):,}원</div>"
        f"<form class='cleanup-form'><select name='display_tab_id' aria-label='여행 선택'><option value=''>여행 선택</option></select>"
        "<button type='submit'>여행 지정</button><p class='cleanup-error' role='alert'></p></form></li>"
    )


def render_cleanup_empty() -> str:
    """Fallback <li> markup when there are no cleanup items."""
    return '<li class="muted">조회 조건에 맞는 거래·장부 행이 없습니다.</li>'


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
    action_summary_html: str,
    diagnostics_open: bool,
    breakdown_html: str,
    note_html: str,
    options_html: str,
    body_html: str,
    nav_html: str,
    script_html: str,
    style_html: str = CLEANUP_STYLE,
) -> str:
    """Assemble the top-level <section id='expense-cleanup'> container."""
    open_attr = " open" if diagnostics_open else ""
    return (
        style_html
        + "<section id='expense-cleanup' aria-label='지출 처리 현황'>"
        + action_summary_html
        + f"<details class='cleanup-diagnostics'{open_attr}>"
        f"<summary>거래·장부 상태 상세 · {total:,}건 · 사용자 요청 아님</summary>"
        "<p class='cleanup-diagnostic-note'>아래 건수는 거래·장부 행 수입니다. 내 확인 필요 작업 수와 다를 수 있습니다.</p>"
        f"{breakdown_html}{note_html}"
        f"<template id='cleanup-trip-options'>{options_html}</template>"
        f"<ul class='cleanup-list'>{body_html}</ul>{nav_html}"
        f"<script>{script_html}</script></details>"
        "<script>(()=>{if(location.hash==='#expense-cleanup'){"
        "const d=document.querySelector('#expense-cleanup .cleanup-diagnostics');if(d)d.open=true"
        "}})();</script></section>"
    )
