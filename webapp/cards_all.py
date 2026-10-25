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
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})")


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
    cursor = _first(query_params, "cursor")
    undated_cursor = _first(query_params, "undated_cursor")
    if cursor and not _CURSOR_RE.match(cursor):
        cursor = None
    if undated_cursor and not _CURSOR_RE.match(undated_cursor):
        undated_cursor = None
    show_undated = str(_first(query_params, "undated", "0")).strip() in ("1", "true", "on")
    # 월 상세와 날짜 미확인 상세는 별도 페이지 상태다.
    if month is not None and cursor:
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
    minute = time_match.group(2)
    if hour > 23:
        return (date_part, "")
    if hour == 0 and minute == "00":
        return (date_part, "")
    return (date_part, f"{hour:02d}:{minute}")


def _is_truly_undated(value) -> bool:
    """유효한 YYYY-MM-DD 이용일이 없는 값만 날짜 확인 필요로 본다."""
    return _DATE_RE.match(str(value or "").strip()) is None


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


def _render_month_rows(items: list[dict], include_detail_link: bool = True) -> str:
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
            trip = _get_trip_display(item.get("trip_id"),
                                     item.get("classification_source"))
            link = ""
            href = _detail_href(tid) if include_detail_link else ""
            if href:
                link = (f"<a class='card-all-link' href='{_esc(href)}'>상세 보기</a>")
            rows.append(
                f"<tr data-tx-id='{_esc(tid)}'>"
                f"<td class='use-datetime'>{_esc(date_text)}</td>"
                f"<td class='merchant' title='{_esc(merchant)}'>{_esc(merchant)}</td>"
                f"<td class='amount'>{_esc(amount)}</td>"
                f"<td class='trip'>{_esc(trip)} {_status_badges(item)} {link}</td>"
                f"</tr>")
    return "".join(rows)


def _transactions_table(items: list[dict], label: str) -> str:
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
        f"<tbody>{_render_month_rows(items)}</tbody>"
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
                     expanded: bool, cursor: str | None, has_more: bool) -> str:
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
            f"{_transactions_table(items, '날짜 확인 필요 거래')}{more}"
            "</section>")


def _month_detail(year: int, month: int, items: list[dict], cursor, has_more: bool,
                  total: int) -> str:
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
            f"{_transactions_table(items, f'{year}년 {month}월 거래')}"
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
            undated_items = [item for item in (undated_result.get("items") or [])
                             if _is_truly_undated(item.get("approval_date"))]
            # 실제 미확인 건수는 날짜 미확인 API의 total만 신뢰한다.
            # 기존 API는 total을 제공하지 않으므로 페이지 행 수를 전체로 가장하지 않는다.
            if "total" in undated_result:
                undated_count = int(undated_result.get("total") or 0)
            undated_has_more = bool(undated_result.get("has_more"))
            undated_next_cursor = undated_result.get("cursor")
    except RuntimeError:
        return _error_page("카드 원본 DB 경로를 확인할 수 없어요.")
    except sqlite3.OperationalError:
        return _error_page("카드 원본 DB에서 거래 표를 읽을 수 없어요.")
    except (ValueError, TypeError):
        return _error_page("조회 조건을 확인하지 못했어요.")

    if selected_month is not None:
        detail = _month_detail(year, selected_month, items, next_cursor,
                               has_more, month_total)
    else:
        detail = ("<p class='card-all-prompt' role='status'>확인할 월을 선택해 줘.</p>")

    body = (
        "<div class='card-all-page'>"
        "<div class='card-all-toolbar'>"
        f"{_year_form(year, years)}"
        "</div>"
        f"{_month_grid(year, months, selected_month)}"
        f"{detail}"
        f"{_undated_section(year, undated_items, undated_count, expanded=show_undated, cursor=undated_next_cursor, has_more=undated_has_more)}"
        "</div>")
    fragment = _design.shell(
        "카드 전체 내역", tab_id="", heading="카드 전체 내역",
        meta="저장된 카드 거래를 연도와 월로 확인해요. 카드사 원본 대조는 별도 단계예요.",
        body=body, home=True)
    return _design.render(fragment, title="카드 전체 내역")
