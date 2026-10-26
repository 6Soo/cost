"""카드 전체 내역 화면: 저장된 카드 원행을 연도/월 단위로 조회한다.

읽기 전용 화면이다. 원본/장부/OTA/Google 자료를 쓰지 않으며, 카드사 원본 대비
누락을 자동 판정하지 않는다. 표시 필드는 `card_transactions` 읽기 투영이 실제로
돌려주는 값만 사용한다.
"""
from __future__ import annotations

import html
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from . import card_transactions as _ct
from . import ledger_design as _design

DEFAULT_YEAR = 2026
MIN_YEAR = 2000
MAX_YEAR = 2100
PAGE_SIZE = 100
UNDATED_PAGE_SIZE = 100

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_CURSOR_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}(?:[T ].*)?)?\|.+$")
_TIME_RE = re.compile(r"^(\d{2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?$")


CARD_ALL_STYLE = """
<style id="card-all-design">
/* This visual layer scopes every rule to the read-only card history screen. */
.card-all-page{--ca-border:var(--line,#e2e8f0);--ca-muted:var(--mut,#64748b);--ca-ink:var(--ink,#0f172a);--ca-paper:var(--paper,#fff);--ca-soft:var(--hover,#f1f5f9);--ca-accent:var(--grn,#1c7a52);color:var(--ca-ink);max-width:1260px;margin:0 auto;padding:24px 24px 64px;font:inherit}
.card-all-page *{box-sizing:border-box}
.card-all-page .card-all-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;padding:22px 24px;border:1px solid var(--ca-border);border-radius:16px;background:var(--ca-paper);margin-bottom:18px}
.card-all-page .card-all-eyebrow{font-size:12px;font-weight:750;letter-spacing:.045em;color:var(--ca-accent);margin:0 0 5px}
.card-all-page .card-all-lead{font-size:15px;font-weight:700;margin:0}
.card-all-page .card-all-description{font-size:12px;color:var(--ca-muted);margin:5px 0 0;max-width:52ch;line-height:1.55}
.card-all-page .card-all-summary{display:grid;grid-template-columns:repeat(2,minmax(110px,1fr));gap:10px}
.card-all-page .card-all-stat{display:grid;gap:3px;min-width:115px;padding:12px 15px;border:1px solid var(--ca-border);background:var(--ca-soft);border-radius:11px}
.card-all-page .card-all-stat-label{font-size:11px;color:var(--ca-muted);font-weight:650}
.card-all-page .card-all-stat-value{font-size:19px;font-variant-numeric:tabular-nums;font-weight:800}
.card-all-page .card-all-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 12px;flex-wrap:wrap}
.card-all-page .card-all-toolbar-title{font-size:16px;font-weight:750;margin:0}
.card-all-page .card-all-year{display:flex;align-items:center;gap:9px;margin:0;font-size:13px}
.card-all-page .card-all-year label{font-size:12px;color:var(--ca-muted)}
.card-all-page .card-all-year select{color:var(--ca-ink);background:var(--ca-paper);font:inherit;font-weight:700;min-height:42px;padding:8px 32px 8px 12px;border:1px solid var(--ca-border);border-radius:9px}
.card-all-page .card-all-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:18px}
.card-all-page .card-month-form{margin:0;min-width:0}
.card-all-page .card-all-tile{display:flex;flex-direction:column;align-items:flex-start;justify-content:space-between;gap:13px;width:100%;min-height:94px;text-align:left;padding:15px 16px;border:1px solid var(--ca-border);border-radius:12px;background:var(--ca-paper);color:var(--ca-ink);font:inherit;cursor:pointer;transition:background .15s,border-color .15s,box-shadow .15s}
.card-all-page .card-all-tile .month-name{font-size:16px;font-weight:800}
.card-all-page .card-all-tile .month-count{font-size:12px;font-weight:650;color:var(--ca-muted);font-variant-numeric:tabular-nums}
.card-all-page .card-all-tile:hover{background:var(--ca-soft);border-color:var(--ca-accent)}
.card-all-page .card-all-tile[aria-pressed=true]{background:var(--sel,var(--ca-soft));border:2px solid var(--ca-accent);padding:14px 15px;box-shadow:0 0 0 1px var(--ca-accent)}
.card-all-page .card-all-tile[aria-pressed=true] .month-count{color:var(--ca-ink)}
.card-all-page :is(button,a,select):focus-visible{outline:2px solid var(--focus,#2563eb);outline-offset:3px}
.card-all-page :is(.card-all-detail,.card-all-undated,.card-all-prompt){border:1px solid var(--ca-border);border-radius:14px;background:var(--ca-paper);padding:19px 20px;margin:0 0 16px}
.card-all-page :is(.card-all-detail,.card-all-undated) h2{margin:0 0 14px;font-size:16px;font-weight:750;line-height:1.5}
.card-all-page .card-all-prompt{color:var(--ca-muted);font-size:13px}
.card-all-page .card-all-muted{font-size:12px;line-height:1.6;color:var(--ca-muted)}
.card-all-page .card-all-table-wrap{width:100%;overflow-x:auto;overscroll-behavior-inline:contain;border-radius:10px;border:1px solid var(--ca-border)}
.card-all-page .card-all-table{border-collapse:separate;border-spacing:0;width:100%;min-width:650px;background:var(--ca-paper);font-size:13px;line-height:1.5}
.card-all-page .card-all-table th,.card-all-page .card-all-table td{padding:12px 14px;text-align:left;vertical-align:middle;border-bottom:1px solid var(--ca-border)}
.card-all-page .card-all-table thead th{position:sticky;top:0;background:var(--ca-soft);color:var(--ca-muted);font-size:12px;font-weight:700;z-index:1}
.card-all-page .card-all-table .date-group th{padding:9px 14px;background:var(--ca-soft);color:var(--ca-ink);font-size:12px;font-weight:750}
.card-all-page .card-all-table tbody tr:not(.date-group):hover{background:var(--ca-soft)}
.card-all-page .card-all-table tbody tr:last-child td{border-bottom:0}
.card-all-page .card-all-table .amount{text-align:right;font-weight:750;font-variant-numeric:tabular-nums;white-space:nowrap}
.card-all-page .card-all-table .use-datetime{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--ca-muted)}
.card-all-page .card-all-table .merchant{font-weight:700;overflow-wrap:anywhere}
.card-all-page .card-all-table .trip{min-width:170px;overflow-wrap:anywhere}
.card-all-page .card-all-trip-name{display:block;font-weight:700;line-height:1.4}
.card-all-page .card-all-trip-name.unassigned{color:var(--ca-muted);font-weight:500}
.card-all-page .card-all-trip-source{display:inline-flex;margin-top:4px;font-size:11px;line-height:1.5;color:var(--ca-muted)}
.card-all-page .card-all-badge{display:inline-flex;margin:5px 4px 0 0;padding:2px 7px;border-radius:6px;border:1px solid var(--ca-border);background:var(--ca-soft);font-size:11px;color:var(--ca-ink)}
.card-all-page .card-all-link{color:var(--ca-accent);font-weight:750;font-size:12px;text-decoration:underline;text-underline-offset:3px}
.card-all-page .card-all-table .card-all-link{display:inline-flex;white-space:nowrap;margin-top:6px}
.card-all-page .card-all-pagination{margin-top:15px;display:flex;justify-content:center}
.card-all-page .card-all-pagination a{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:10px 16px;border:1px solid var(--ca-border);border-radius:9px;background:var(--ca-soft);text-decoration:none}
@media(width < 760px){.card-all-page{padding:14px 12px 42px}.card-all-page .card-all-hero{padding:16px}.card-all-page .card-all-summary{width:100%;grid-template-columns:repeat(2,minmax(0,1fr))}.card-all-page .card-all-stat{min-width:0}.card-all-page .card-all-grid{grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.card-all-page .card-all-tile{min-height:78px;padding:11px}.card-all-page .card-all-tile[aria-pressed=true]{padding:10px}.card-all-page :is(.card-all-detail,.card-all-undated){padding:13px}.card-all-page .card-all-table th,.card-all-page .card-all-table td{padding:10px}}
@media(max-width:390px){.card-all-page .card-all-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.card-all-page .card-all-hero{gap:14px}}
@media(prefers-reduced-motion:reduce){.card-all-page .card-all-tile{transition:none}}
</style>
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _first(query_params: dict | None, key: str, default=None):
    if not query_params:
        return default
    values = query_params.get(key)
    if not values:
        return default
    return values[0]


def _safe_int(raw, default, minimum: int, maximum: int):
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if value < minimum or value > maximum:
        return default
    return value


def _request_params(query_params: dict | None) -> tuple[int, int | None, str | None, str | None, bool]:
    """연도/월/커서를 검증한다. 잘못된 값은 안전한 기본값으로 되돌린다."""
    year = _safe_int(_first(query_params, "year", DEFAULT_YEAR), DEFAULT_YEAR,
                     MIN_YEAR, MAX_YEAR)
    month_raw = _first(query_params, "month")
    month = None
    if month_raw is not None:
        month = _safe_int(month_raw, None, 1, 12)
        if month is None:
            # A malformed month must not fall through into another requested view.
            return year, None, None, None, False
    cursor = _first(query_params, "cursor")
    undated_cursor = _first(query_params, "undated_cursor")
    if cursor and not _CURSOR_RE.match(cursor):
        cursor = None
    if undated_cursor and not _CURSOR_RE.match(undated_cursor):
        undated_cursor = None
    show_undated = str(_first(query_params, "undated", "0")).strip() in ("1", "true", "on")
    # 월 상세와 날짜 미확인 상세는 함께 열지 않고, 명시한 날짜 미확인 모드를 우선한다.
    if show_undated:
        month = None
        cursor = None
    elif month is not None and cursor:
        undated_cursor = None
    elif undated_cursor:
        cursor = None
    return year, month, cursor, undated_cursor, show_undated


def _split_datetime(value) -> tuple[str, str]:
    """승인일 문자열을 (날짜, 시간)으로 나눈다.

    시간이 없거나 00:00이면 빈 문자열을 돌려준다. 없는 시간을 합성하지 않는다.
    """
    text = str(value or "").strip()
    if not text:
        return ("", "")
    match = _DATE_RE.match(text)
    if not match:
        return ("", "")
    date_part = match.group(0)
    rest = text[len(date_part):].strip()
    if rest[:1] in ("T", " "):
        rest = rest[1:].strip()
    time_match = _TIME_RE.match(rest)
    if not time_match:
        return (date_part, "")
    hour = int(time_match.group(1))
    minute = int(time_match.group(2))
    seconds = time_match.group(3)
    if hour > 23 or minute > 59:
        return (date_part, "")
    if seconds is not None and float(seconds) >= 60:
        return (date_part, "")
    return (date_part, time_match.group(0))


def _format_use_date(value) -> str:
    date_part, time_part = _split_datetime(value)
    if not date_part:
        return ""
    return f"{date_part} {time_part}" if time_part else date_part


def _format_number(value):
    """부호를 보존한 천 단위 구분 숫자. 숫자가 아니면 None."""
    text = str(value).replace(",", "").strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    negative = number < 0
    number = abs(number)
    body = format(number, "f")
    if "." in body:
        whole, fraction = body.split(".", 1)
        fraction = fraction.rstrip("0")
    else:
        whole, fraction = body, ""
    whole = f"{int(whole):,}"
    result = f"{whole}.{fraction}" if fraction else whole
    return f"-{result}" if negative else result


def _format_amount(amount_krw, foreign_amount="", foreign_currency="") -> str:
    """원본 부호와 통화를 유지한다. 환산액으로 원본을 대체하지 않는다."""
    currency = str(foreign_currency or "").strip().upper()
    if currency and currency != "KRW":
        original = _format_number(foreign_amount)
        if original is not None:
            return f"{original} {currency}"
    krw = _format_number(amount_krw) if amount_krw is not None else None
    if krw is not None:
        return f"{krw}원"
    original = _format_number(foreign_amount)
    if original is not None and currency:
        return f"{original} {currency}"
    return "금액 미확인"


def _get_trip_display(trip_id, classification_source) -> str:
    """현재 유효한 배정과 출처만 표시한다. 확정/추정을 섞지 않는다."""
    trip = str(trip_id or "").strip()
    if not trip:
        return "미배정"
    source = str(classification_source or "").strip()
    if source == "manual":
        return f"{trip} · 사용자 확정"
    if source == "auto_inferred":
        return f"{trip} · 추정"
    return trip


def _status_badges(item: dict) -> str:
    """읽기 투영이 실제로 돌려주는 상태만 배지로 표시한다."""
    badges: list[str] = []
    if str(item.get("duplicate_of") or "").strip():
        badges.append("<span class='card-all-badge duplicate'>중복 출처</span>")
    if str(item.get("conflict_reason") or "").strip():
        badges.append("<span class='card-all-badge conflict'>원본 충돌</span>")
    state = str(item.get("classification_state") or "").strip()
    if state == "needs_review":
        badges.append("<span class='card-all-badge review'>검토 필요</span>")
    elif state == "preserved":
        badges.append("<span class='card-all-badge preserved'>원본 보존</span>")
    return "".join(badges)


def _detail_href(transaction_id) -> str:
    tid = str(transaction_id or "").strip()
    if not tid:
        return ""
    return "/board?" + urlencode({"row": f"card-{tid}"})


def _group_by_date(items: list[dict]) -> list[tuple[str, list[tuple[str, str, dict]]]]:
    """날짜 오름차순, 같은 날짜는 시간 있는 거래 먼저, 그다음 안정 ID 순."""
    grouped: dict[str, list[tuple[str, str, dict]]] = {}
    for item in items:
        date_part, time_part = _split_datetime(
            item.get("use_date") or item.get("approval_date"))
        key = date_part or "날짜 확인 필요"
        grouped.setdefault(key, []).append((date_part, time_part, item))
    ordered: list[tuple[str, list[tuple[str, str, dict]]]] = []
    for key in sorted(k for k in grouped if k != "날짜 확인 필요"):
        rows = grouped[key]
        rows.sort(key=lambda row: (row[1] == "", row[1],
                                   str(row[2].get("transaction_id") or "")))
        ordered.append((key, rows))
    if "날짜 확인 필요" in grouped:
        rows = sorted(grouped["날짜 확인 필요"],
                      key=lambda row: str(row[2].get("transaction_id") or ""))
        ordered.append(("날짜 확인 필요", rows))
    return ordered


def _render_month_rows(items: list[dict], include_detail_link: bool = True, *,
                       trip_names: dict[str, str] | None = None) -> str:
    rows: list[str] = []
    for date_key, entries in _group_by_date(items):
        rows.append(
            f"<tr class='date-group'><th scope='colgroup' colspan='4'>"
            f"{_esc(date_key)} · {len(entries)}건</th></tr>")
        for date_part, time_part, item in entries:
            tid = str(item.get("transaction_id") or "")
            approved = item.get("use_date") or item.get("approval_date")
            date_text = _format_use_date(approved)
            if not date_text:
                date_text = "날짜 확인 필요"
            merchant = str(item.get("merchant") or "").strip() or "가맹점 미상"
            amount = _format_amount(item.get("amount_krw"),
                                    item.get("foreign_amount"),
                                    item.get("foreign_currency"))
            trip_id = str(item.get("trip_id") or "").strip()
            trip_name = (trip_names or {}).get(trip_id, trip_id)
            source = str(item.get("classification_source") or "").strip()
            if not trip_id:
                trip_markup = "<span class='card-all-trip-name unassigned'>미배정</span>"
            else:
                trip_markup = (f"<span class='card-all-trip-name' title='{_esc(trip_id)}'>"
                               f"{_esc(trip_name)}</span>")
                if source in ("manual", "auto_inferred"):
                    label = "사용자 확정" if source == "manual" else "추정 배정"
                    trip_markup += f"<span class='card-all-trip-source'>{label}</span>"
            link = ""
            href = _detail_href(tid) if include_detail_link else ""
            if href:
                link = (f"<a class='card-all-link' href='{_esc(href)}'>상세 보기</a>")
            rows.append(
                f"<tr data-tx-id='{_esc(tid)}'>"
                f"<td class='use-datetime'>{_esc(date_text)}</td>"
                f"<td class='merchant' title='{_esc(merchant)}'>{_esc(merchant)}</td>"
                f"<td class='amount'>{_esc(amount)}</td>"
                f"<td class='trip'>{trip_markup} {_status_badges(item)} {link}</td>"
                f"</tr>")
    return "".join(rows)


def _transactions_table(items: list[dict], label: str, *,
                        trip_names: dict[str, str] | None = None) -> str:
    return (
        "<div class='card-all-table-wrap'>"
        f"<table class='card-all-table' aria-label='{_esc(label)}'>"
        "<caption class='sr'>저장된 카드 거래 내역</caption>"
        "<thead><tr>"
        "<th scope='col'>이용일시</th>"
        "<th scope='col'>가맹점명</th>"
        "<th scope='col' class='amount'>금액</th>"
        "<th scope='col'>배정된 여행</th>"
        "</tr></thead>"
        f"<tbody>{_render_month_rows(items, trip_names=trip_names)}</tbody>"
        "</table></div>")


def _month_grid(year: int, months: dict, selected_month: int | None) -> str:
    tiles: list[str] = []
    for month in range(1, 13):
        try:
            count = int(months.get(month, 0) or 0)
        except (TypeError, ValueError):
            count = 0
        pressed = selected_month == month
        hidden = f"<input type='hidden' name='year' value='{year}'>"
        if not pressed:
            hidden += f"<input type='hidden' name='month' value='{month}'>"
        label = f"{month}월 거래 {count}건"
        if pressed:
            label += " (다시 누르면 닫힘)"
        tiles.append(
            "<form method='get' action='/cards/all' class='card-month-form'>"
            f"{hidden}"
            f"<button type='submit' class='card-all-tile' data-month='{month}' "
            f"aria-pressed='{'true' if pressed else 'false'}' "
            f"aria-label='{_esc(label)}'>"
            f"<span class='month-name'>{month}월</span>"
            f"<span class='month-count'>{count:,}건</span>"
            "</button></form>")
    return (
        "<div class='card-all-grid' role='group' aria-label='월별 거래 건수'>"
        + "".join(tiles)
        + "</div>")


def _undated_section(year: int, items: list[dict], count: int, *,
                     expanded: bool, cursor: str | None, has_more: bool,
                     trip_names: dict[str, str] | None = None) -> str:
    heading = f"<h2>날짜 확인 필요 · {count:,}건</h2>"
    note = ("<p class='card-all-muted'>유효한 이용일이 없는 저장 원행이에요. "
            "연도 필터와 상관없이 확인할 수 있어요.</p>")
    if count == 0:
        return (f"<section class='card-all-undated' aria-labelledby='undated-heading'>"
                f"<div id='undated-heading'>{heading}</div>"
                "<p class='card-all-muted'>날짜 확인이 필요한 거래가 없어.</p>"
                "</section>")
    if not expanded:
        href = "/cards/all?" + urlencode({"year": year, "undated": "1"})
        return (f"<section class='card-all-undated' aria-labelledby='undated-heading'>"
                f"<div id='undated-heading'>{heading}</div>{note}"
                f"<a class='card-all-link' href='{_esc(href)}'>날짜 확인 필요 목록 보기</a>"
                "</section>")
    more = ""
    if has_more and cursor:
        href = "/cards/all?" + urlencode({"year": year, "undated": "1",
                                         "undated_cursor": cursor})
        more = ("<div class='card-all-pagination'>"
                f"<a class='card-all-link' href='{_esc(href)}'>다음 날짜 확인 필요 거래 100건 보기</a>"
                "</div>")
    return (f"<section class='card-all-undated' aria-labelledby='undated-heading'>"
            f"<div id='undated-heading'>{heading}</div>{note}"
            f"{_transactions_table(items, '날짜 확인 필요 거래', trip_names=trip_names)}{more}"
            "</section>")


def _month_detail(year: int, month: int, items: list[dict], cursor, has_more: bool,
                  total: int, *, trip_names: dict[str, str] | None = None) -> str:
    if not items:
        if total:
            start = "/cards/all?" + urlencode({"year": year, "month": month})
            return ("<section class='card-all-detail'>"
                    f"<h2>{year}년 {month}월 · 전체 {total:,}건</h2>"
                    "<p class='card-all-muted'>이 위치에는 표시할 거래가 더 없어. "
                    f"<a class='card-all-link' href='{_esc(start)}'>처음부터 보기</a></p>"
                    "</section>")
        return ("<section class='card-all-detail card-all-empty'>"
                f"<h2>{year}년 {month}월</h2>"
                "<p>이 달에 저장된 카드 거래가 없어.</p>"
                "<p class='card-all-muted'>카드사 원본에도 없다는 뜻은 아니에요.</p>"
                "</section>")
    more = ""
    if has_more and cursor:
        href = "/cards/all?" + urlencode({"year": year, "month": month,
                                         "cursor": cursor})
        more = (f"<div class='card-all-pagination'>"
                f"<a class='card-all-link' href='{_esc(href)}'>다음 100건 더 보기</a>"
                "</div>")
    return (f"<section class='card-all-detail' aria-labelledby='month-heading'>"
            f"<h2 id='month-heading'>{year}년 {month}월 · 전체 {total:,}건</h2>"
            f"{_transactions_table(items, f'{year}년 {month}월 거래', trip_names=trip_names)}"
            f"{more}</section>")


def _year_form(year: int, years: list[int]) -> str:
    options = "".join(
        f"<option value='{value}'{' selected' if value == year else ''}>"
        f"{value}년</option>" for value in years)
    return (
        "<form method='get' action='/cards/all' class='card-all-year'>"
        "<label for='card-all-year'>연도</label>"
        "<select id='card-all-year' name='year' onchange='this.form.submit()'>"
        f"{options}</select>"
        "<noscript><button type='submit' class='card-all-link'>보기</button></noscript>"
        "</form>")


def _available_years(db_path: str | None) -> list[int]:
    result = _ct.available_years(db_path=db_path)
    years = {int(value) for value in result.get("years", []) if str(value).isdigit()}
    years.add(DEFAULT_YEAR)
    return sorted(years, reverse=True)


def _default_db_path():
    from .ledger_board import _get_card_db_path as _board_card_db_path
    return _board_card_db_path()


def _error_page(message: str) -> str:
    body = ("<section class='card-all-empty' role='alert'>"
            "<h2>카드를 불러오지 못했어요</h2>"
            f"<p>{_esc(message)}</p></section>")
    fragment = _design.shell("카드 전체 내역", tab_id="", heading="카드 전체 내역",
                             meta="저장된 카드 거래를 연도와 월로 확인해요.",
                             body=body, home=True)
    return _design.render(fragment, title="카드 전체 내역")


def cards_all_page(query_params: dict, *, db_path: str | None = None) -> str:
    """카드 전체 내역 페이지를 그린다. 읽기만 수행한다."""
    year, selected_month, cursor, undated_cursor, show_undated = _request_params(query_params)
    card_db_path = db_path or _default_db_path()
    if not card_db_path:
        return _error_page("카드 원본 DB가 연결되지 않았어요. 운영 설정을 확인해 주세요.")
    try:
        years = _available_years(card_db_path)
        summary = _ct.year_summary(db_path=card_db_path, year=year)
        months = summary.get("months") or {}

        items: list[dict] = []
        next_cursor = None
        has_more = False
        month_total = 0
        if selected_month is not None:
            try:
                month_total = int(months.get(selected_month, 0) or 0)
            except (TypeError, ValueError):
                month_total = 0
            result = _ct.list_for_month(db_path=card_db_path, year=year,
                                        month=selected_month, cursor=cursor,
                                        per_page=PAGE_SIZE)
            items = result.get("items") or []
            next_cursor = result.get("cursor")
            has_more = bool(result.get("has_more"))

        undated_count = int(summary.get("undated_count", 0) or 0)
        undated_items: list[dict] = []
        undated_has_more = False
        undated_next_cursor = None
        if show_undated:
            undated_result = _ct.undated_list(
                db_path=card_db_path, year=year, cursor=undated_cursor,
                per_page=UNDATED_PAGE_SIZE)
            # 날짜 유효성의 권위는 API에 둔다. 무효한 달력 날짜도 API가
            # 날짜 확인 필요 목록으로 돌려줬다면 화면에서 제외하지 않는다.
            undated_items = undated_result.get("items") or []
            # 실제 미확인 건수는 날짜 미확인 API의 total만 신뢰한다.
            # 기존 API는 total을 제공하지 않으므로 페이지 행 수를 전체로 가장하지 않는다.
            if "total_count" in undated_result or "total" in undated_result:
                undated_count = int(undated_result.get("total_count", undated_result.get("total", 0)) or 0)
            undated_has_more = bool(undated_result.get("has_more"))
            undated_next_cursor = undated_result.get("cursor")
    except RuntimeError:
        return _error_page("카드 원본 DB 경로를 확인할 수 없어요.")
    except sqlite3.OperationalError:
        return _error_page("카드 원본 DB에서 거래 표를 읽을 수 없어요.")
    except (ValueError, TypeError):
        return _error_page("조회 조건을 확인하지 못했어요.")

    # Only an already-authorized owner page resolves ledger display labels.
    # This never changes the stored trip_id, the card's classification, or access policy.
    trip_names: dict[str, str] = {}
    try:
        from . import ledger_board as _board
        if (items or undated_items) and _board.current_role() == "owner":
            trip_names = {
                str(t.get("tab_id") or ""): str(t.get("display_key") or t.get("tab_id") or "")
                for t in _board.live_trips(include_archived=True)
                if isinstance(t, dict) and t.get("tab_id")
            }
    except (RuntimeError, AttributeError, TypeError):
        trip_names = {}

    if selected_month is not None:
        detail = _month_detail(year, selected_month, items, next_cursor,
                               has_more, month_total, trip_names=trip_names)
    else:
        detail = ("<p class='card-all-prompt' role='status'>확인할 월을 선택해 줘.</p>")

    body = (
        CARD_ALL_STYLE
        + "<div class='card-all-page'>"
        "<header class='card-all-hero'>"
        "<div><p class='card-all-eyebrow'>CARD TRANSACTION HISTORY</p>"
        "<p class='card-all-lead'>월별 카드 거래 확인</p>"
        "<p class='card-all-description'>저장된 원행을 날짜순으로 확인합니다. 원본 카드사 자료와의 완전성 대조는 별도입니다.</p></div>"
        "<div class='card-all-summary' aria-label='저장 거래 요약'>"
        f"<div class='card-all-stat'><span class='card-all-stat-label'>{year}년 날짜 확인 거래</span><strong class='card-all-stat-value'>{sum(int(v or 0) for v in months.values()):,}건</strong></div>"
        f"<div class='card-all-stat'><span class='card-all-stat-label'>날짜 확인 필요</span><strong class='card-all-stat-value'>{undated_count:,}건</strong></div>"
        "</div></header>"
        "<div class='card-all-toolbar'><h2 class='card-all-toolbar-title'>조회할 월 선택</h2>"
        f"{_year_form(year, years)}"
        "</div>"
        f"{_month_grid(year, months, selected_month)}"
        f"{detail}"
        f"{_undated_section(year, undated_items, undated_count, expanded=show_undated, cursor=undated_next_cursor, has_more=undated_has_more, trip_names=trip_names)}"
        "</div>")
    fragment = _design.shell(
        "카드 전체 내역", tab_id="", heading="카드 전체 내역",
        meta="저장된 카드 거래를 연도와 월로 확인해요. 카드사 원본 대조는 별도 단계예요.",
        body=body, home=True)
    return _design.render(fragment, title="카드 전체 내역")
