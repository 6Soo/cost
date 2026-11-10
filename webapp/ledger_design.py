"""A/Ramp/Pretendard design applied to the real ledger screens.

The screen is server rendered and talks to the existing store, save, upload,
export and rule dialog contracts. Nothing in this module re-implements them,
and no demo data or demo JavaScript is copied in: the demo only supplied the
layout, the colours and the font.

Static fonts and OTA icons are served from explicit allowlists, so a path
cannot escape their asset directories.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
from urllib.parse import urlencode
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote

from app.google_authority import SnapshotError
from . import ledger_board as board
from . import read_scope, ui_icons
from . import ui_components

FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"
OTA_DIR = Path(__file__).resolve().parent / "static" / "ota"
OTA_ASSETS = {"agoda.png": "image/png", "trip.png": "image/png"}


def ota_asset(name):
    if not isinstance(name, str) or name not in OTA_ASSETS:
        return None
    path = OTA_DIR / name
    if not path.is_file() or path.resolve().parent != OTA_DIR.resolve():
        return None
    return path.read_bytes(), OTA_ASSETS[name]


def _category_icon(row):
    category = _row_item(row)
    for terms, name in ((('항공',), 'plane'), (('숙박', '호텔'), 'bed'),
                        (('교통',), 'bus'), (('식비',), 'utensils'),
                        (('현지',), 'map-pin')):
        if any(term in category for term in terms):
            return ui_icons.icon(name, size=14)
    return ui_icons.icon('receipt', size=14)


def _merchant_icon(row):
    # Only the source merchant identifies a brand. Notes and booking IDs do not.
    merchant = str(row.get('source_merchant') or '').upper()
    asset = None
    if re.search(r'(?<![A-Z0-9])AGODA(?![A-Z0-9])', merchant):
        asset = 'agoda.png'
    elif '트립닷컴' in merchant or re.search(r'(?<![A-Z0-9])TRIP\.COM(?![A-Z0-9.])', merchant):
        asset = 'trip.png'
    if asset:
        return (f"<img class='ota-icon' src='/assets/ota/{asset}' width='18' height='18' "
                "alt='' aria-hidden='true' loading='lazy' decoding='async'>")
    return ui_icons.icon('receipt', size=16)

# Explicit allowlist. A name that is not a key here is refused, whatever it
# contains, so traversal, absolute paths and encoded separators cannot resolve.
STATIC_ASSETS = {
    "PretendardVariable.woff2": "font/woff2",
    "OFL.txt": "text/plain; charset=utf-8",
}

FONT_FAMILY = "Pretendard Variable"

# Stored values stay English; the screen shows the Korean the app already uses.
INCOME_KIND_LABELS = {
    "deposit": "예약금",
    "balance": "잔금",
    "additional": "추가금",
}

# Buttons and rows keep the values the existing tests and the export already use.
MONEY = "{:,}원"


def static_asset(name: str):
    """Return (bytes, content_type) for an allowed asset, or None."""
    if not isinstance(name, str) or name not in STATIC_ASSETS:
        return None
    path = FONT_DIR / name
    if path.parent.resolve() != FONT_DIR.resolve():
        return None
    if not path.is_file():
        return None
    return path.read_bytes(), STATIC_ASSETS[name]


from .ledger_design_assets import STYLE, SCRIPT


# ----------------------------------------------------------------- fragments
def _money(value) -> str:
    return MONEY.format(int(value or 0))


def work_menu_html() -> str:
    """The home no longer owns a second navigation menu."""
    return ''


def _nav_html(tab_id: str, query: str, kind: str = "", archived: str = "",
              quick_view: bool = False) -> str:
    """Thin wrapper around the application shell sidebar.

    live_nav is supplied by the same renderer used by nav_region so the
    live fragment and the initial document never disagree.
    """
    from . import site_shell
    # aria-current="page" is assigned by the server shell for one section link.
    return site_shell.sidebar(
        section=site_shell.section_for('/board', {'tab': [tab_id]}),
        tab_id=tab_id,
        role=board.current_role(),
        live_nav=nav_region(tab_id, query, kind, archived),
    )

_CURRENT_YEAR = 2026
_FOCUS_ON_OPEN = ("var d=this.parentNode;setTimeout(function(){if(d.open){"
                  "var t=d.querySelector('.prev-q>summary, a');if(t)t.focus()}},0)")


def _quarter_of(trip):
    try:
        day = date.fromisoformat(trip.get("starts_on") or "")
    except (TypeError, ValueError):
        return None
    return day.year, (day.month - 1) // 3 + 1


def _quarter_groups(trips):
    """The quarters the previous trips fall in, plus the 1st and 2nd quarter of the current year."""
    found = {_quarter_of(t) for t in trips} - {None}
    return sorted(found | {(_CURRENT_YEAR, 1), (_CURRENT_YEAR, 2)})


def _nav_region_inner(tab_id: str, query: str = "", kind: str = "",
                      archived: str = "", quick_view: bool = False) -> str:
    """Return the live navigation region from the shared shell renderer."""
    from . import site_shell
    return site_shell._active_trip_nav(tab_id, role=board.current_role())



def nav_region(tab_id: str, query: str = "", kind: str = "",
               archived: str = "", *, quick_view: bool = False) -> str:
    inner = _nav_region_inner(tab_id, query, kind, archived, quick_view=quick_view)
    if inner.startswith("<div id='live-nav'"):
        return inner
    return "<div id='live-nav'><nav aria-label='진행 중 여행'>" + inner + "</nav></div>"



def nav_part(tab_id: str, query: str = "", kind: str = "",
             archived: str = "") -> str:
    markup = nav_region(tab_id, query, kind, archived)
    if markup.startswith("<div id='live-nav'"):
        opening = markup.find('>') + 1
        return markup[opening:-len("</div>")]
    return markup



def _context_badge() -> str:
    """Only example-data warnings belong beside every page title."""
    mark = board.data_status_mark()
    return f"<span class='synth'>{board.esc(mark)}</span>" if mark == board.SYNTHETIC_MARK else ''


def _head_html(trip) -> str:
    if trip is None:
        title, meta = "여행을 선택해 주세요", ""
        actions = ""
    elif trip.get("is_unclassified"):
        title, meta = "이전 귀속 목록", "여행을 정하지 않은 내역입니다"
        actions = ""
    else:
        title = str(trip.get('display_title') or trip["display_key"])
        if trip.get('owner_id') == 'andre':
            title += ' · 김동언(안드레)'
        from .trip_insurance_policy import is_domestic
        status = '마감' if trip.get('visual_closed') else '미마감'
        region = ui_components.chip('국내여행', 'accent') if is_domestic(trip) else ''
        state = ui_components.chip(status, 'neutral' if trip.get('visual_closed') else 'warn')
        trip_switch = (
            "<button class='btn' id='trip-switch-open' data-no-action-icon type='button' aria-haspopup='dialog' "
            "aria-controls='trip-switch-dialog'>여행 전환</button>"
        )
        from . import trip_management_ui
        more = trip_management_ui.controls(board, trip)
        actions = region + state + trip_switch + more
        meta = (f"{trip.get('starts_on') or ''} – {trip.get('ends_on') or ''} · "
                f"담당자 {trip.get('prepared_by_name') or '-'}")
    header = ui_components.page_header(title, meta=meta, actions=actions, breadcrumb=())
    # Example-data warning stays beside the title (store isolation and synthetic previews rely on it).
    header = header.replace('</h1>', _context_badge() + '</h1>', 1)
    header = header.replace("<header class=\"page-header\">", "<header class=\"page-header trip-header\">")
    if trip and not trip.get('is_unclassified'):
        header += _trip_switch_dialog(trip)
    return header


def _trip_switch_dialog(trip) -> str:
    """Searchable trip switcher; links preserve the existing GET contract."""
    current = str(trip.get('tab_id') or '')
    entries = []
    for item in board.live_trips(include_archived=False):
        if item.get('deleted'):
            continue
        label = str(item.get('display_title') or item.get('display_key') or '')
        entries.append(
            f"<li><a data-trip-switch-item href='/board?{board.esc(state_query(item['tab_id']))}'"
            f"{' aria-current=\"page\"' if item.get('tab_id') == current else ''}>{board.esc(label)}</a></li>")
    try:
        from app import quarter_tab
        for quarter in (1, 2, 3, 4):
            tab = quarter_tab.tab_id_for(2026, quarter)
            label = f"2026년 {quarter}분기 기타비용"
            entries.append(f"<li><a data-trip-switch-item href='/board?{board.esc(state_query(tab))}'>{label}</a></li>")
    except Exception:
        pass
    return (
        "<dialog class='trip-switch-dialog' id='trip-switch-dialog' aria-labelledby='trip-switch-title'>"
        "<div class='trip-switch-head'><h2 id='trip-switch-title'>여행 전환</h2>"
        "<button class='icon-btn' type='button' data-trip-switch-close aria-label='닫기'>×</button></div>"
        "<label for='trip-switch-search'>여행 검색</label>"
        "<input id='trip-switch-search' type='search' autocomplete='off' placeholder='여행 이름 검색'>"
        f"<ul data-trip-switch-list>{''.join(entries) or '<li class=\"muted\">여행이 없습니다.</li>'}</ul>"
        "<a class='btn ghost' href='/trips'>여행 전체 보기</a></dialog>")


def _trip_kpi_html(tab_id: str) -> str:
    """The three ledger figures, using the existing COST/Google read paths."""
    if not tab_id or _STORE_missing():
        return ""
    incomes, expenses, _whole_income, _whole_expense = _selected_rows(tab_id, '', '')
    expense = sum(board._shown_amount(row) for row in expenses)
    income = None
    from .google_ledger_page import get_trip_income_summary
    google_income = get_trip_income_summary(tab_id)
    if google_income and google_income.get('show_rows'):
        income = int(google_income.get('amount') or 0)
    elif incomes:
        income = sum(board._shown_amount(row) for row in incomes)
    balance = income - expense if income is not None else None

    def amount(value):
        if value is None:
            return '—'
        text = _money(value)
        return text.replace('-', '−', 1) if text.startswith('-') else text

    income_note = ("장부 사본 선택 필요"
                   if income is None else f"수입 {len(incomes) or int((google_income or {}).get('count') or 0)}건")
    balance_note = '수입과 지출의 차액' if balance is not None else '수입을 확인하면 계산됩니다'
    income_kpi = ui_components.kpi('수입', amount(income), income_note)
    if income is None:
        income_kpi = income_kpi.replace(
            "<small>장부 사본 선택 필요</small>",
            "<small><a class='kpi-link' href='/google-ledger'>장부 사본 선택 필요</a></small>",
            1)
    return (
        "<dl class='kpi-row' id='sum' aria-label='여행 요약'>"
        + income_kpi
        + f"<div class='kpi'><dt>지출</dt><dd>{board.esc(amount(expense))}</dd>"
          f"<small>{len(expenses)}건</small></div>"
        + f"<div class='kpi'><dt>차액</dt><dd>{board.esc(amount(balance))}</dd>"
        f"<small>{board.esc(balance_note)}</small></div></dl>"
    )


def _expense_toolbar_html(tab_id: str, query: str, kind: str, back: str) -> str:
    """Search, filter, grouping and manual entry controls for the expense tab."""
    if board.current_role() != 'owner':
        return ""
    return (
        "<div class='expense-toolbar' role='toolbar' aria-label='지출 도구'>"
        "<form class='expense-filter' method='get' action='/board' role='search'>"
        f"<input type='hidden' name='tab' value='{board.esc(tab_id)}'>"
        "<label for='q'>검색</label>"
        f"<input id='q' name='q' type='search' value='{board.esc(query)}' "
        "placeholder='거래처·내용·메모 검색' autocomplete='off'>"
        "<label for='kind'>항목</label>"
        "<select id='kind' name='kind'>"
        f"<option value=''{'' if not kind else ''}>전체</option>"
        f"<option value='in'{ ' selected' if kind == 'in' else ''}>수입</option>"
        f"<option value='ex'{ ' selected' if kind == 'ex' else ''}>지출</option></select>"
        "<button class='btn' type='submit' id='q-go'>조회</button>"
        + (f"<a class='btn ghost' id='q-clear' href='/board?{board.esc(state_query(tab_id))}'>초기화</a>" if (query or kind) else '')
        + "</form>"
        "<label class='group-toggle'><input id='group-expenses' type='checkbox' data-group-expenses>항목별 묶기</label>"
        f"<a class='btn' id='add-manual-expense' data-manual-open href='{board.esc(_manual_expense_link(back))}'>"
        f"{ui_icons.icon('pencil')}수기 지출 추가</a>"
        "</div>")


def _trip_tabs_html(tab_id: str, *, query: str, kind: str, selected: str,
                    archived: str, back: str, google_income_html: str,
                    participant_html: str, flight_html: str, reservations_html: str) -> str:
    """Five in-page tabs; the tab script owns hash restoration and APG keys."""
    expense = (_expense_toolbar_html(tab_id, query, kind, back)
               + rows_region(tab_id, query, kind, selected, archived, back))
    income = f"<section id='trip-income' aria-label='여행 수입 · COST 기록'>{google_income_html}</section>"
    participant_content = participant_html
    if not participant_content:
        participant_content = (
            "<section id='participant-trip-panel' class='empty-state' aria-label='참가자·보험'>"
            "<p class='es-title'>참가자·보험</p>"
            "<p>국내 여행은 참가자·보험 연결이 필요하지 않습니다.</p></section>")
    flight_content = flight_html or (
        "<section id='trip-flight-panel' class='empty-state' aria-label='항공권'>"
        "<p class='es-title'>항공권</p><p>이 여행에 연결된 항공권이 없습니다.</p></section>")
    items = [
        {'label': '지출', 'id': 'view-expense', 'content': expense, 'selected': True},
        {'label': '수입', 'id': 'view-income', 'content': income},
    ]
    items.append({'label': '참가자·보험', 'id': 'view-participants', 'content': participant_content})
    items.append({'label': '항공권', 'id': 'view-flights', 'content': flight_content})
    items.append({'label': '예약 연결', 'id': 'view-reservations', 'content': reservations_html})
    return ui_components.view_tabs(items)


def _reserve_link_link_html() -> str:
    """The link to the reservation-event linking screen, for an owner only.

    The screen is reachable from the ledger header so that a feature does not
    need its address typed in. Two conditions decide whether the link is drawn,
    and each exists for a reason:

    * The role. A viewer is refused the route itself, and a link a viewer can
      see but cannot open is worse than no link at all. The route decides the
      role again on every request, so this markup is a convenience and never the
      decision.
    * Not the configuration. This is the one place where the two header links
      differ on purpose. The review link is hidden when no review is configured,
      because opening it would show nothing useful. The linking screen instead
      answers "설정이 필요해요" when the source is not configured, and that answer
      is the reason to show the link: hiding it would leave an installation with
      no configured source unable to find out that one is needed. Hiding it here
      would make the configuration-required state unreachable except by knowing
      the address, which is the same gap this link exists to close.

    Nothing here reads the roster, and nothing searches for one.
    """
    if board.current_role() != "owner":
        return ""
    from . import ui_icons as _icons
    return ("<a class='btn' id='reserve-link' href='#trip-reservations' aria-label='예약·참가자 여행 연결'>"
            f"{_icons.icon('link')}예약·참가자</a>")


def _review_link_html() -> str:
    """The link to the actual-source comparison, when one is configured.

    Rendered only when a review is configured, so an installation without one
    has no dead link. The owner page is the only place it appears: a viewer is
    refused the route itself, and a link they can see but cannot open is worse
    than no link. The route decides the role again on every request, so this
    markup is a convenience and never the decision.
    """
    from . import real_review
    from . import ui_icons as _icons

    if real_review.active_service() is None:
        return ""
    return (f"<a class='btn' id='review-link' href='/review'>{_icons.icon('search')}실제 자료 검토</a>")


def _source_sheet_name(locator: str) -> str:
    """The sheet an explicit source reference names, or "" when it names none.

    A locator looks like `시트명!$A$5|$B$5 (row 5)`. Only the part before the
    first `!` is the sheet, and only a locator that has one is used: matching a
    trip to a sheet by anything else — a prefix, a date, a settlement day, a
    "looks like the same trip" judgement — is a guess, and a guessed trip's
    source rows would sit under the wrong name.
    """
    text = str(locator or "")
    if "!" not in text:
        return ""
    return text.split("!", 1)[0].strip()


def _saved_review_choices(service) -> dict:
    """The review screen's saved decisions, read only, or {} when unavailable.

    Read for display only. Nothing here writes, and no choice is created,
    cleared or changed — a screen that renders state must not be able to move
    it. A read that fails leaves the original per-row decision visible, so the
    screen degrades to what the snapshot itself carried rather than to nothing.
    """
    try:
        state = service.state()
    except Exception:
        return {}
    choices = (state or {}).get("choices")
    return choices if isinstance(choices, dict) else {}


def _source_rows_for_trip(trip) -> list:
    """The source rows whose sheet is exactly this trip's display key.

    An exact string equality, once. Nothing here infers: no dates, no amounts,
    no ordering, no "only one trip could match". A trip with no sheet of its own
    gets nothing, which is the honest answer.
    """
    if not trip:
        return []
    if board.current_role() != "owner":
        return []
    wanted = str(trip.get("display_key") or "")
    if not wanted:
        return []
    try:
        from . import real_review

        service = real_review.active_service()
        if service is None:
            return []
        model = service.model()
        saved = _saved_review_choices(service)
    except Exception:
        # An unbound, unreadable or refused service leaves the ledger exactly as
        # it was. A screen that failed to read the source must not also fail to
        # show the ledger.
        return []
    rows = []
    for row in (model or {}).get("rows") or []:
        if not isinstance(row, dict):
            continue
        source = row.get("source")
        if not isinstance(source, dict):
            continue
        if _source_sheet_name(source.get("sourceLocator")) != wanted:
            continue
        # The snapshot's own decision, and a saved choice when there is one. A
        # blank decision stays blank: it is never promoted to something.
        decision = saved.get(row.get("ref"))
        if not isinstance(decision, str) or not decision.strip():
            decision = str(row.get("decision") or "")
        rows.append({"source": source, "decision": decision})
    return rows


def _source_preview_html(trip) -> str:
    """The trip's actual source rows, shown beside the ledger, read only.

    The reason this exists: a trip with nothing in the ledger shows an empty
    ledger and no way to tell "nothing happened" from "nothing has been entered
    yet". The source is what tells those apart.

    Three things it must not do:

    * **Not be a ledger total.** It is headed as the actual source, before it
      reaches the ledger, and it sits outside `#live-sum`, so the saved totals
      above are untouched and cannot be read as including it.
    * **Not decide anything.** No approval, no selection, no write. The only
      control is a link to the comparison screen, which is where decisions are
      made.
    * **Not guess the trip.** Only a sheet whose name is exactly this trip's
      display key is shown.
    """
    from . import card_flow
    if card_flow.enabled():
        return ""
    rows = _source_rows_for_trip(trip)
    sheet = _source_sheet_name(
        (rows[0]["source"].get("sourceLocator") if rows else "")) or (
            str(trip.get("display_key") or "") if rows else "")
    if not rows:
        return ""
    items = []
    for entry in rows:
        source = entry["source"]
        cells = source.get("fieldcells") or []
        # Built raw and escaped once, at the end. Escaping here and then again
        # in the fallback below would turn a literal `&` into `&amp;amp;` on
        # screen, which is a worse answer than the raw text it replaced.
        labelled = " · ".join(
            f"{cell.get('label') or ''} {cell.get('value') or ''}"
            for cell in cells
            if isinstance(cell, dict) and str(cell.get("label") or "").strip())
        decision = entry["decision"]
        decision_text = ("미검토" if not decision.strip() else decision)
        # Which block this row is. A row from before the kind existed has none,
        # and reads as an expense row so an existing installation is unchanged.
        block_kind = str(source.get("block_kind") or "expense")
        if block_kind not in ("income", "expense", "unknown"):
            block_kind = "expense"
        income = block_kind == "income"
        if income:
            decision_text = "입금 원본 조회"
        badge = {"income": "입금",
                 "expense": "지출"}.get(block_kind, "구분 확인 필요")
        evidence = source.get("evidence_status") == "available"
        content = str(source.get("description") or labelled or "-")
        if income:
            components = source.get("income_components") or {}
            content = " · ".join(
                f"{label} {components[label]}원"
                for label in ("예약금", "잔금", "추가금")
                if str(components.get(label) or "").strip()) or "-"
        items.append(
            f"<li class='src-row' data-block-kind='{board.esc(block_kind)}'>"
            f"<p class='src-line'><span>종류</span>"
            f"<b>{board.esc(badge)}</b></p>"
            + ((f"<p class='src-line'><span>이름</span><b>"
                f"{board.esc(source.get('customer_name') or '-')}</b></p>"
                f"<p class='src-line'><span>닉네임</span><b>"
                f"{board.esc(source.get('nickname') or '-')}</b></p>")
               if income else "")
            + f"<p class='src-line'><span>날짜</span>"
            f"<b>{board.esc(source.get('date') or '-')}</b></p>"
            f"<p class='src-line'><span>금액</span>"
            f"<b class='tnum'>{board.esc(source.get('amount') or '-')}</b></p>"
            + (f"<p class='src-line'><span>내용</span><b>"
               f"{board.esc(content)}</b></p>" if content != "-" else "")
            + "<p class='src-line'><span>원본 위치</span>"
              f"<code>{board.esc(source.get('sourceLocator') or '-')}</code></p>"
            + f"<p class='src-line'><span>검토 상태</span>"
              f"<b>{board.esc(decision_text)}</b>"
            + ("" if evidence else
               " <span class='muted'>· 원본 머리글 확인 필요</span>")
            + "</p></li>")
    # Percent-encoded, not just escaped. A sheet name is free text and can hold
    # `&`, `+`, `#` or a space, all of which mean something else inside a query
    # string; escaping alone would produce a link that opens the wrong search.
    review_href = "/review?q=" + urllib.parse.quote(sheet, safe="")
    # The button sits with the heading rather than after the rows. A trip with
    # dozens of source rows pushes a trailing link far past the fold, and the
    # control a reader wants first becomes the one they have to scroll to.
    return (
        f"<section class='src-preview' id='src-preview'>"
        f"<div class='src-hd'><h2>실제 원천 자료 · 입금과 지출</h2>"
        f"<a class='btn' id='src-review-link' href='{board.esc(review_href)}'>"
        f"{ui_icons.icon('search')}실제 자료 검토</a></div>"
        f"<p class='muted'><code>{board.esc(sheet)}</code> · {len(items)}행</p>"
        f"<ul class='src-list'>{''.join(items)}</ul>"
        f"</section>")


def _bar_html(query: str, kind: str, tab_id: str, archived: str = "") -> str:
    # One GET form owns the search and the filter, so submitting, refreshing and
    # going back all land on the same URL state.
    from . import ui_icons as _icons
    return (
        "<form class='bar' method='get' action='/board' id='q-form'>"
        f"<input type='hidden' name='tab' value='{board.esc(tab_id)}'>"
        f"{f'<input type=hidden name=arch value={board.esc(archived)}>' if archived else ''}"
        "<button class='icon' id='btn-menu' type='button' aria-label='전체 메뉴 열기'"
        f" aria-controls='nav' aria-expanded='false'>{_icons.icon('menu')}</button>"
        "<label class='sr' for='q'>거래 검색</label>"
        "<input id='q' name='q' type='search' placeholder='용도·내용·메모·예약번호 검색'"
        f" value='{board.esc(query)}' autocomplete='off'>"
        "<label class='sr' for='kind'>구분 필터</label>"
        "<select id='kind' name='kind' onchange='this.form.submit()'>"
        f"<option value=''>전체</option><option value='in'{' selected' if kind == 'in' else ''}>수입만</option>"
        f"<option value='ex'{' selected' if kind == 'ex' else ''}>지출만</option></select>"
        f"<button class='btn' type='submit' id='q-go'>{_icons.icon('search')}검색</button>"
        + (f"<a class='btn' id='q-clear' href='/board?{state_query(tab_id)}'>{_icons.icon('rotate-ccw')}지우기</a>"
           if (query or kind) else "")
        + "</form>")


def _net_income_summary(value, prefix=''):
    label = prefix + '수입'
    return (f"<div class='net-income'><i>{ui_icons.icon('arrow-up-down')}{label}</i>"
            f"<b aria-label='{label}, 총수입에서 지출을 뺀 금액'>{_money(value)}</b>"
            "</div>")


def _summary_html(incomes, expenses, *, filtered=None, whole=None, recorded_income_count=None,
                  google_income=None) -> str:
    """The totals bar.

    DETAILED 12.2: with a filter on, the whole total and the result total get
    separate names, and the whole total is never quietly replaced by the result.
    `filtered` is (income, expense, count_income, count_expense) for the rows
    the filter left visible; `whole` is the same for the unfiltered tab.
    """
    expense = sum(board._shown_amount(r) for r in expenses)

    if google_income and not incomes and recorded_income_count in (0, -1):
        if google_income.get('show_rows'):
            income = google_income['amount']
            count_in = google_income['count']
            if filtered is not None and whole is not None:
                return (
                    f"<div class='sum tnum' id='sum'>"
                    f"<div><i>{ui_icons.icon('book-open')}전체 총수입</i><b>{_money(income)}</b></div>"
                    f"<div><i>{ui_icons.icon('credit-card')}전체 지출</i><b>{_money(whole[1])}</b></div>"
                    f"<div class='filtered-total'><i>검색 결과 지출</i><b>{_money(filtered[1])}</b></div>"
                    f"{_net_income_summary(income - whole[1], '전체 ')}"
                    f"<span class='n'>전체 수입 {count_in}건 · 전체 지출 {whole[3]}건 · 검색 결과 지출 {filtered[3]}건</span></div>")
            return (
                f"<div class='sum tnum' id='sum'>"
                f"<div><i>{ui_icons.icon('book-open')}총수입</i><b>{_money(income)}</b></div>"
                f"<div><i>{ui_icons.icon('credit-card')}지출</i><b>{_money(expense)}</b></div>"
                f"{_net_income_summary(income - expense)}"
                f"<span class='n'>수입 {count_in}건 · 지출 {len(expenses)}건</span></div>")
        elif google_income.get('numeric_gap') or not google_income.get('verified'):
            income_status = ("<b class='warn'>합계 차이 있음</b>"
                             if google_income.get('numeric_gap') else "<b>확인 필요</b>")
            income_notice = f"<div><i>{ui_icons.icon('book-open')}수입</i>{income_status}</div>"
            if filtered is not None and whole is not None:
                return (
                    f"<div class='sum tnum' id='sum'>{income_notice}"
                    f"<div><i>{ui_icons.icon('credit-card')}전체 지출</i><b>{_money(whole[1])}</b></div>"
                    f"<div class='filtered-total'><i>검색 결과 지출</i><b>{_money(filtered[1])}</b></div>"
                    f"<span class='n'>전체 지출 {whole[3]}건 · 검색 결과 지출 {filtered[3]}건</span></div>")
            return (
                f"<div class='sum tnum' id='sum'>{income_notice}"
                f"<div><i>{ui_icons.icon('credit-card')}지출</i><b>{_money(expense)}</b></div>"
                f"<span class='n'>지출 {len(expenses)}건</span></div>")

    income = sum(board._shown_amount(r) for r in incomes)
    note = ""
    if not incomes and recorded_income_count in (0, -1):
        if filtered is not None and whole is not None:
            return (f"<div class='sum tnum' id='sum'>"
                    f"<div><i>전체 지출</i><b>{_money(whole[1])}</b></div>"
                    f"<div class='filtered-total'><i>검색 결과 지출</i><b>{_money(filtered[1])}</b></div>"
                    f"<span class='n'>전체 지출 {whole[3]}건 · 검색 결과 지출 {filtered[3]}건</span></div>")
        return (f"<div class='sum tnum' id='sum'>"
                f"<div><i>{ui_icons.icon('credit-card')}지출</i><b>{_money(expense)}</b></div>"
                f"<span class='n'>지출 {len(expenses)}건</span></div>")
    if filtered is None or whole is None:
        return (
            f"<div class='sum tnum' id='sum'><div><i>{ui_icons.icon('book-open')}총수입</i><b>{_money(income)}</b></div>"
            f"<div><i>{ui_icons.icon('credit-card')}지출</i><b>{_money(expense)}</b></div>"
            f"{_net_income_summary(income - expense)}"
            f"<span class='n'>수입 {len(incomes)}건 · 지출 {len(expenses)}건</span></div>" + note)
    fincome, fexpense, finc, fexp = filtered
    wincome, wexpense, winc, wexp = whole
    return (
        f"<div class='sum tnum' id='sum'>"
        f"<div><i>전체 총수입</i><b>{_money(wincome)}</b></div>"
        f"<div><i>전체 지출</i><b>{_money(wexpense)}</b></div>"
        f"<div><i>검색 결과 총수입</i><b>{_money(fincome)}</b></div>"
        f"<div><i>검색 결과 지출</i><b>{_money(fexpense)}</b></div>"
        f"{_net_income_summary(fincome - fexpense, '검색 결과 ')}"
        f"<span class='n'>전체 수입 {winc}건 · 전체 지출 {wexp}건"
        f" · 검색 결과 수입 {finc}건 · 검색 결과 지출 {fexp}건</span></div>" + note)


def _trip_options(current="", blank_label=None) -> str:
    options = []
    if blank_label:
        options.append(f"<option value=''>{board.esc(blank_label)}</option>")
    for trip in board.live_trips():
        options.append(
            f"<option value='{board.esc(trip['tab_id'])}'"
            f"{' selected' if trip['tab_id'] == current else ''}>"
            f"{board.esc(trip['display_key'])} · {board.esc(trip['starts_on'])}~"
            f"{board.esc(trip['ends_on'])}</option>")
    return "".join(options)


def _row_kind_meter(row) -> str:
    if row.get("row_kind") == "income":
        return "수입"
    state = row.get("classification_state")
    if state == "unclassified" or row.get("display_tab_id") is None:
        return "대기"
    if row.get("event_kind") == "cancellation":
        return "취소"
    return "지출"


def _income_kind_label(row) -> str:
    return INCOME_KIND_LABELS.get(row.get("income_kind") or "", row.get("income_kind") or "-")


def _row_amount_class(row) -> str:
    amount = board._shown_amount(row)
    if amount < 0:
        return "a-neg"
    return "a-in" if row.get("row_kind") == "income" else "a-ex"


def _row_party_main(row) -> str:
    """Merchant/description first; reservation second as sub. Income keeps fallback."""
    if row.get("row_kind") == "income":
        for key in ("description", "customer_name"):
            value = str(row.get(key) or "").strip()
            if value:
                return value
        return str(row.get("source_merchant") or "").strip() or "-"
    merchant = str(row.get("source_merchant") or "").strip()
    description = str(row.get("description") or "").strip()
    if merchant:
        return merchant
    if description:
        return description
    return str(row.get("reservation_no") or "").strip() or "-"


def _row_party_sub(row) -> str:
    """Display each known reservation once, without modifying the source row."""
    main = _row_party_main(row)
    if row.get("row_kind") == "income":
        for key in ("source_merchant", "nickname"):
            value = str(row.get(key) or "").strip()
            if value and value != main:
                return value
        return ""
    reservation = str(row.get("reservation_no") or "").strip()
    description = str(row.get("description") or "").strip()
    item = str(row.get("item") or "").strip()
    if item == "숙박비":
        period = _stay_period(row)
        match = _STAY_PATTERN.fullmatch(period)
        if match and _stay_text(row) != "이용일 확인 필요":
            from datetime import date
            start, end = (date.fromisoformat(value) for value in match.groups())
            # Only a whole description segment repeating the displayed period is redundant.
            ranges = {re.sub(r"\s+", "", period), f"{start.month}/{start.day}~{end.month}/{end.day}",
                      f"{start:%m/%d}~{end:%m/%d}"}
            description = " · ".join(part.strip() for part in description.split("·")
                if re.sub(r"\s+", "", part) not in ranges)
    # This legacy clause was emitted by ota_inference's code matcher, not by AI.
    if reservation:
        from app.assignment_status import classification_source_label
        description = " · ".join(classification_source_label('code_inference')
            if part.strip() == "추론 연결" else part.strip() for part in description.split("·"))
    parts = []
    # A lodging or flight row names its stay or its passengers instead of the number;
    # the number itself stays in the row, the search and the source link.
    if item == "\uD56D\uACF5\uB8CC" and reservation:
        parts.append(_passenger_text(row))
    elif reservation and reservation != main:
        parts.append("\uC608\uC57D\uBC88\uD638 " + reservation)
    if reservation:
        description = re.sub(
            r"(?<![\w-])(?:\uC608\uC57D(?:\uBC88\uD638)?\s*)?" + re.escape(reservation)
            + r"(?![\w-])", "", description)
        description = re.sub(r"\s+", " ", description).strip(" \u00b7|,;:-")
    # The typed description is kept verbatim; the bare category name adds nothing.
    if description and description != main and not (item in ("\uC219\uBC15\uBE44", "\uD56D\uACF5\uB8CC") and description == item):
        parts.append(description)
    return " \u00b7 ".join(parts)


_STAY_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")
# A sanity bound only: a long stay with a clear period is real. Reversed or invalid dates are unknown.
_MAX_STAY_DAYS = 366


def _stay_period(row) -> str:
    period = str(row.get("service_period") or "").strip()
    if not period and str(row.get("row_id") or "").startswith("card-"):
        from . import ledger_stay_evidence
        index = read_scope.remember("ledger_stay_evidence", _ledger_stay_index)
        period = ledger_stay_evidence.period_for(row, index)
    return period


def _stay_text(row) -> str:
    """The lodging dates from the source's service period, never from the reservation number.

    A missing, unreadable, reversed or implausibly long period is shown as unknown
    rather than guessed. The card's approval or payment date is a different fact.
    """
    from datetime import date, timedelta
    unknown = "\uC774\uC6A9\uC77C \uD655\uC778 \uD544\uC694"
    period = _stay_period(row)
    match = _STAY_PATTERN.fullmatch(period)
    if not match:
        return unknown
    try:
        start, end = (date.fromisoformat(value) for value in match.groups())
    except ValueError:
        return unknown
    if not start <= end <= start + timedelta(days=_MAX_STAY_DAYS):
        return unknown
    nights = (end - start).days
    stay = f"{nights}박" if nights else "당일"
    text = f"{_day_label(start, start.year != end.year)} ~ {_day_label(end, start.year != end.year)} · {stay}"
    if not str(row.get('service_period') or '').strip() and str(row.get('row_id') or '').startswith('card-'):
        index = read_scope.remember("ledger_stay_evidence", _ledger_stay_index)
        tid = str(row.get('source_event_id') or str(row['row_id'])[5:])
        if ((index.get(tid) or {}).get('ota_evidence') or {}).get('kind') == 'reservation_period_inferred':
            text += ' · 예약 근거 추론'
    return text


def _ledger_stay_index():
    from . import ledger_stay_evidence
    return ledger_stay_evidence.stay_index(board._active_store())


def _day_label(day, with_year: bool) -> str:
    """A calendar day as read on a ledger line: 10월 14일(수), with the year when the stay crosses one."""
    weekday = "월화수목금토일"[day.weekday()]
    prefix = f"{day.year}년 " if with_year else ""
    return f"{prefix}{day.month}월 {day.day}일({weekday})"


def _compact_stay(row) -> str:
    """Compact table label; keep complete dates and inference in the tooltip."""
    full = _stay_text(row)
    match = _STAY_PATTERN.fullmatch(_stay_period(row))
    if full == '이용일 확인 필요' or not match:
        return full
    from datetime import date
    start, end = (date.fromisoformat(value) for value in match.groups())
    fmt = '%y.%m.%d' if start.year != end.year else '%m.%d'
    nights = (end - start).days
    label = f"{start.strftime(fmt)}–{end.strftime(fmt)} · {str(nights) + '박' if nights else '당일'}"
    return label + (' · 추론' if '예약 근거 추론' in full else '')


def _flight_passengers() -> dict:
    """The passenger index the OTA refresh holds in memory, read without computing anything."""
    return read_scope.remember("flight_passengers", _load_flight_passengers)


def _load_flight_passengers() -> dict:
    from . import ota_payment_review
    store = board._active_store()
    if store is None or not ota_payment_review.enabled():
        return {}
    return ota_payment_review.passenger_index_for(store)


def _passenger_text(row) -> str:
    """Who is flying, only when the mail names the passengers of this booking."""
    found = _flight_passengers().get(str(row.get("reservation_no") or "").strip())
    if not found or found.get("conflict") or not found.get("names"):
        return "\uD0D1\uC2B9\uC790 \uD655\uC778 \uD544\uC694"
    names = found["names"]
    if len(names) == 1:
        return f"\uD0D1\uC2B9\uC790: {names[0]}"
    return f"\uD0D1\uC2B9\uC790: {names[0]} \uC678 {len(names) - 1}\uBA85"


def _load_flight_dates():
    """The last complete display evidence and explicit empty overrides; never reconcile on a read."""
    from . import ota_payment_review
    store = board._active_store()
    if store is None or not ota_payment_review.enabled():
        return {}, set()
    with store._lock:
        manual = {str(r[0]) for r in store.conn.execute(
            "SELECT row_id FROM board_manual_overrides WHERE field='service_period'")}
    for attribute in ('_flight_booking_service', '_ota_snapshot_service'):
        service = getattr(store, attribute, None)
        if service is not None:
            current, _state = service.display_context()
            # As for stays: the last complete generation is shown while the next one is computed.
            if current and current.get('data') is not None:
                return (current.get('data') or {}).get('passengers') or {}, manual
    return {}, manual


def _flight_date_labels(row):
    """Departure days of the saved booking, independent of payment and passenger count."""
    from datetime import date
    unknown = ('이용일 미확인', '이용일 미확인')
    stored = _stay_period(row)
    if stored:
        match = _STAY_PATTERN.fullmatch(stored)
        if not match:
            return unknown
        try:
            days = [date.fromisoformat(value) for value in match.groups()]
        except ValueError:
            return unknown
        if days[1] < days[0]:
            return unknown
        days = list(dict.fromkeys(days))
        separator = '–'
    else:
        index, manual = read_scope.remember('flight_service_dates', _load_flight_dates)
        if str(row.get('row_id') or '') in manual:
            return unknown
        # A number mentioned in prose is not a saved reservation relationship.
        ref = str(row.get('reservation_no') or '').strip()
        found = index.get(ref) if ref else None
        if (not found or found.get('conflict') or not found.get('source_digests')
                or found.get('cancellation_status') != 'NONE'
                or any(found.get(flag) for flag in
                       ('evidence_missing', 'evidence_changed', 'period_conflict', 'service_period_conflict'))):
            return unknown
        legs = found.get('legs') or []
        if not legs or any(not leg.get('departure_on') for leg in legs):
            return unknown
        try:
            days = sorted({date.fromisoformat(leg['departure_on']) for leg in legs})
        except (ValueError, TypeError):
            return unknown
        separator = ' · '
    crosses_year = len({day.year for day in days}) > 1
    fmt = '%y.%m.%d' if crosses_year else '%m.%d'
    return (separator.join(day.strftime(fmt) for day in days),
            '항공 이용일: ' + ' · '.join(day.isoformat() for day in days))


# Payment intermediaries and booking sites: a charge through them is a booking, not an on-site stay.
# Rakuten Pay is a wallet used at the property itself, unlike Rakuten Travel.
_BOOKING_CHANNEL = re.compile(
    r'(?i)nice|kcp|inicis|이니시스|토스|카카오페이|네이버페이|페이코|payco|paypal|klook|클룩|booking|agoda|아고다'
    r'|trip\.?com|트립|expedia|hotels\.com|인터넷상거래|결제대행|ksnet|다날|스마트로|나이스|쿠팡|야놀자|여기어때'
    r'|airbnb|에어비앤비|rakuten(?!\s*pay)|라쿠텐(?!\s*페이)|jalan|楽天|skyticket|어드벤처|\bpg\b|\bkg\b'
    r'|호텔스닷컴|인터파크|마이리얼트립|myrealtrip|호텔엔조이|하나투어|모두투어|노랑풍선|참좋은여행|데일리호텔'
    r'|놀유니버스|위메프|티몬|11번가|g마켓|지마켓|옥션|네이버|kkday|hostelworld|hotelscombined|ikyu|一休|jtb|\bars\b|_ars')


def _onsite_payment_label(row, kind):
    """A lodging or rental paid at the property: the card's use date is its use date.

    Only a direct (non-booking-channel) merchant charged inside the row's own trip
    period qualifies; no stay length is inferred from it.
    """
    from app.ota_matching_defaults import provider_for_merchant
    if (not str(row.get('row_id') or '').startswith('card-') or str(row.get('reservation_no') or '').strip()
            or (row.get('amount_krw') or 0) <= 0):
        return None
    merchant = str(row.get('source_merchant') or '')
    if not merchant or provider_for_merchant(merchant) or _BOOKING_CHANNEL.search(merchant):
        return None
    try:
        day = date.fromisoformat(str(row.get('occurred_on') or ''))
    except ValueError:
        return None
    trip = read_scope.remember('trip_periods', _trip_periods).get(str(row.get('display_tab_id') or ''))
    if not trip:
        return None
    starts, ends = trip
    if day < starts or (ends is not None and day > ends):
        return None
    what = '숙박 기간' if kind == 'lodging' else '인수·반납일'
    return (f"{day:%m.%d} 현장 결제",
            f"현장 결제한 카드 이용일 {day.isoformat()} 기준 · {what}은 원문에 없음")


def _trip_periods():
    periods = {}
    for trip in board.live_trips(include_archived=True):
        try:
            starts = date.fromisoformat(str(trip.get('starts_on') or ''))
        except ValueError:
            continue
        try:
            ends = date.fromisoformat(str(trip.get('ends_on') or '')) if trip.get('ends_on') else None
        except ValueError:
            ends = None
        periods[str(trip['tab_id'])] = (starts, ends)
    return periods


_UNKNOWN_SERVICE_DATES = ('이용일 확인 필요', '이용일 미확인')


def _service_date_labels(row):
    labels = _service_date_labels_for(row)
    # A cancellation or refund has no service day of its own; only an unknown date is replaced.
    if labels[0] in _UNKNOWN_SERVICE_DATES and (row.get('display_amount_krw', row.get('amount_krw')) or 0) < 0:
        return '취소·환불', '취소·환불 거래라 별도 이용일이 없음'
    return labels


def _service_date_labels_for(row):
    item = str(row.get('item') or '').strip()
    if item == '숙박비':
        compact, full = _compact_stay(row), _stay_text(row)
        if full == '이용일 확인 필요':
            return _onsite_payment_label(row, 'lodging') or (compact, full)
        return compact, full
    if item in ('항공료', '항공권'):
        return _flight_date_labels(row)
    if item == '렌터카':
        match = _STAY_PATTERN.fullmatch(_stay_period(row))
        try:
            start, end = (date.fromisoformat(value) for value in match.groups()) if match else (None, None)
            valid = start is not None and 0 <= (end - start).days <= _MAX_STAY_DAYS
        except ValueError:
            valid = False
        if not valid:
            return _onsite_payment_label(row, 'rental') or ('이용일 미확인', '렌터카 인수·반납일 미확인')
        fmt = '%y.%m.%d' if start.year != end.year else '%m.%d'
        return (start.strftime(fmt) + '–' + end.strftime(fmt),
                '렌터카 인수 ' + start.isoformat() + ' · 반납 ' + end.isoformat())
    return '', ''


def _row_item(row) -> str:
    """분류: the typed 항목, or the income kind, or "-" when the row has neither.

    Filled from what the row holds, not from the section it sits in: a waiting
    expense has no 여행 and still has a 항목.
    """
    value = str(row.get("item") or "").strip()
    if value:
        return value
    if row.get("row_kind") == "income":
        return _income_kind_label(row)
    return "-"


def _party_cell(row) -> str:
    """거래처·내용: the counterparty and what the transaction was, in one cell.

    One cell rather than two columns, because reading a ledger is a single left
    to right pass: the amount has to sit against the line that explains it.
    """
    main = f"<span class='s-main'>{board.esc(_row_party_main(row))}</span>"
    sub = _row_party_sub(row)
    if sub:
        main += f"<span class='s-sub'>{board.esc(sub)}</span>"
    return (f"<td class='c-party'><span class='party-line'>{_merchant_icon(row)}"
            f"<span class='party-copy'>{main}</span></span></td>")


def _move_form(row, move_back: str) -> str:
    """The travel picker a waiting row carries, in its own action row now."""
    rid = row["row_id"]
    return (
        "<form method='post' action='/api/rows/"
        f"{board.esc(rid)}/save' data-js-move class='row-move'>"
        f"<input type='hidden' name='csrf' value='{board.CSRF_TOKEN}'>"
        f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
        "<input type='hidden' name='client_request_id' value='"
        f"{uuid.uuid4().hex}'>"
        "<input type='hidden' name='change_mode' value='exception'>"
        f"<input type='hidden' name='return_to' value='{board.esc(move_back)}'>"
        "<label class='sr' for='move-" + board.esc(rid) + "'>이동할 여행</label>"
        f"<select class='psel' id='move-{board.esc(rid)}' name='display_tab_id'>"
        f"{_trip_options('', '여행 연결 없음')}</select>"
        f"<button class='btn' type='submit'>{ui_icons.icon('check')}이동</button></form>")


def _match_text(value):
    if value is None:
        return ''
    return ' '.join(unicodedata.normalize('NFC', str(value)).split()).casefold()


def _match_date(value):
    text = str(value or '').strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ''


def _match_amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).strip().replace(',', '').replace('원', '').strip()
        if not re.fullmatch(r'[+-]?\d+', text):
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def _google_expense_matches(google_rows, web_rows):
    """Return display-only web row matches using exact financial and identity fields."""
    edges = {}
    reverse = {}
    web_by_amount = {}
    for web_index, web_row in enumerate(web_rows):
        amount = _match_amount(web_row.get('display_amount_krw', web_row.get('amount_krw')))
        if amount is not None:
            web_by_amount.setdefault(amount, []).append(web_index)
    for g_index, google_row in enumerate(google_rows):
        amount = _match_amount(google_row.get('amount', google_row.get('amount_krw')))
        if amount is None:
            continue
        for web_index in web_by_amount.get(amount, []):
            web_row = web_rows[web_index]
            reasons = []
            g_date, w_date = _match_date(google_row.get('date')), _match_date(
                web_row.get('display_occurred_on') or web_row.get('occurred_on') or web_row.get('ledger_date'))
            if g_date and w_date and g_date == w_date:
                reasons.append('날짜')
            g_merchant, w_merchant = _match_text(google_row.get('payee')), _match_text(
                web_row.get('source_merchant') or web_row.get('merchant'))
            if g_merchant and w_merchant and g_merchant == w_merchant:
                reasons.append('가맹점')
            g_category, w_category = _match_text(google_row.get('category')), _match_text(
                web_row.get('item'))
            if g_category and w_category and g_category == w_category:
                reasons.append('분류')
            g_reservation = _match_text(google_row.get('reservation') or google_row.get('booking_ref'))
            w_reservation = _match_text(web_row.get('reservation_no'))
            placeholders = {'-', '미확정', '미확인', '없음', 'unknown', 'tbd', 'n/a'}
            if (g_reservation and w_reservation and g_reservation not in placeholders
                    and w_reservation not in placeholders and g_reservation == w_reservation):
                reasons.append('예약번호')
            if reasons:
                edges.setdefault(web_index, {})[g_index] = reasons
                reverse.setdefault(g_index, set()).add(web_index)
    result = {}
    for web_index, candidates in edges.items():
        reasons = sorted({reason for values in candidates.values() for reason in values})
        multiple = len(candidates) > 1 or any(len(reverse[g_index]) > 1 for g_index in candidates)
        result[web_index] = {'reasons': reasons, 'multiple': multiple}
    return result


def _expense_copy_preview(tab_id, rows):
    """One read-only comparison shared by row labels and the copy summary."""
    if board.current_role() != 'owner' or not _is_trip_tab(tab_id) or not rows:
        return {}
    from .sheet_expense_reconciliation import preview_for_trip
    return preview_for_trip(board._active_store(), tab_id, cost_rows=rows,
                            include_sheet_rows=True, allow_total_mismatch=True)


def _google_match_annotations(tab_id, rows, preview=None, candidate_rows=None):
    """Read the already selected, fresh Google snapshot for owner-only display hints."""
    if board.current_role() != 'owner' or not tab_id or tab_id == 'unclassified' or not rows:
        return {}
    try:
        result = _expense_copy_preview(tab_id, rows) if preview is None else preview
        if not result.get('source_available'):
            return {}
        comparison_rows = rows if candidate_rows is None else candidate_rows
        candidates = {comparison_rows[index]['row_id']: candidate for index, candidate in
                      _google_expense_matches(result.get('sheet_rows') or [], comparison_rows).items()}
        by_id = {item['transaction_id']: item for item in result.get('results', [])}
        labels = {'MATCHED_MANUAL': '장부에 있음 · 복사 제외',
                  'MATCHED_EXISTING': '장부에 있음 · 복사 제외',
                  'NEW_EXPENSE': '복사 가능',
                  'REVIEW_CONFLICT': '중복 확인 필요 · 복사 제외'}
        annotations = {}
        for row in rows:
            item = by_id.get(str(row.get('transaction_id') or row.get('source_event_id') or row.get('row_id') or ''))
            if item and item.get('status') in labels:
                candidate = candidates.get(row['row_id'])
                annotations[row['row_id']] = {
                    'multiple': bool(candidate and candidate['multiple']) or item['status'] == 'REVIEW_CONFLICT',
                    'reasons': candidate['reasons'] if candidate else item.get('basis') or [],
                    'display_candidate': bool(candidate),
                    'candidate_multiple': bool(candidate and candidate['multiple']),
                    'label': ('복사 제외 · 거래 상세 확인' if item['status'] == 'NEW_EXPENSE'
                              and (row.get('blocked') or row.get('excluded_from_company')) else labels[item['status']]),
                    'status': item['status']}
        return annotations
    except (SnapshotError, AttributeError, KeyError, OSError, TypeError, ValueError):
        return {}


def _table_html(rows, *, kind, selected, unclassified, move_back="/board", match_annotations=None,
                amount_groups=None, date_years=None) -> str:
    if not rows:
        colspan = 6 if amount_groups is not None else 5
        return (f"<tbody><tr class='empty'><td colspan='{colspan}'>"
                f"{'수입 내역이 없어요' if kind == 'income' else '지출 내역이 없어요'}"
                "</td></tr></tbody>")
    body = []
    match_annotations = match_annotations or {}
    for row in rows:
        rid = row["row_id"]
        amount = board._shown_amount(row)
        item = row.get('item') or ''
        service_dates, service_title = _service_date_labels(row)
        service_class = 'c-stay c-flight-dates' if item in ('항공료', '항공권') else 'c-stay'
        # A keyboard reader reaches a row the way a pointer reader does, so the row
        # itself is focusable and Enter or Space opens it. `tabindex` is what
        # makes that possible; the click path is unchanged underneath.
        # Five columns: the memo column is gone from the table. The operator note
        # stays in storage, search and the edit panel; only its table cell is gone.
        match = match_annotations.get(rid) if kind == 'expense' else None
        match_attributes = ''
        match_description = ''
        match_class = ''
        if match:
            label = match.get('label') or ('복수 후보 확인 필요' if match['multiple'] else
                     '금액+' + '+'.join(match['reasons']))
            hint_id = 'google-match-' + str(rid)
            match_class = (' class="google-match-candidate"' if match.get('display_candidate')
                           or match.get('status') != 'NEW_EXPENSE' else '')
            match_attributes = f" aria-describedby='{board.esc(hint_id)}'"
            match_description = (f"<span class='sr' id='{board.esc(hint_id)}'>"
                                 f"{board.esc(label)}</span>")
            if not match.get('status'):
                match_description = (f"<span class='sr' id='{board.esc(hint_id)}'>Google 장부 대조 후보: "
                                     f"{board.esc(label)}</span>")
            if match.get('status') and match.get('status') != 'NEW_EXPENSE':
                match_description = (f"<span class='sr' id='{board.esc(hint_id)}'>"
                                     f"{board.esc(label)}</span>")
            if match.get('display_candidate'):
                candidate_label = ('복수 후보 · 확인 필요' if match['candidate_multiple'] else
                                   '금액+' + '+'.join(match['reasons']))
                match_attributes = f" aria-describedby='{board.esc(hint_id)} {board.esc(hint_id)}-candidate'"
                match_description += (f"<span class='sr' "
                                      f"id='{board.esc(hint_id)}-candidate'>Google 장부 대조 후보: "
                                      f"{board.esc(candidate_label)}</span>")
        category = str(row.get('item') or _row_item(row) or '-')
        body.append(
            f"<tr{match_class} data-id='{board.esc(rid)}' data-kind='{board.esc(kind)}' data-category='{board.esc(category)}' data-revision='{int(row.get('revision') or 1)}' data-amount='{int(amount)}' tabindex='0' aria-expanded='false'"
            f"{match_attributes}"
            f"{' aria-selected="true"' if rid == selected else ''}>"
            f"<td class='c-date tnum' title='{board.esc(board._shown_date(row))}'>{board.esc(_ledger_date_label(row, date_years))}</td>"
            + _party_cell(row).replace('</td>', match_description + '</td>')
            +
            f"<td class='c-item'><span class='category-line'>{_category_icon(row)}{board.esc(_row_item(row))}</span></td>"
            f"<td class='{service_class}' title='{board.esc(service_title)}'>{board.esc(service_dates)}</td>"
            + f"<td class='num tnum c-amt {_row_amount_class(row)}'>{_money(amount)}</td>"
            + (_amount_group_cell(amount_groups, rid) if amount_groups is not None and kind == 'expense'
               else "<td class='gemn-desktop gemn-status-cell'></td>" if amount_groups is not None else '')
            +
            f"</tr>")
        if unclassified:
            # The waiting row's travel picker lives in its own action row below
            # the data row, not in the removed memo cell. Same form contract.
            body.append(
                f"<tr class='move-row' data-move-for='{board.esc(rid)}'>"
                f"<td colspan='{6 if amount_groups is not None else 5}'>{_move_form(row, move_back)}</td></tr>")
    return f"<tbody class='expense-rows' data-kind='{board.esc(kind)}'>{''.join(body)}</tbody>"


def _column_head_row() -> str:
    """Column titles repeated above the expense rows (display only)."""
    return ("<tr><th scope='col'>날짜</th><th scope='col'>거래처·내용</th>"
            "<th scope='col'>분류</th><th scope='col'>이용일</th>"
            "<th scope='col' class='num'>금액</th></tr>")


def _ledger_date_label(row, date_years=None) -> str:
    """Compact date labels while retaining the full source date in ``title``."""
    value = str(board._shown_date(row) or '')
    try:
        day = date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return value
    years = date_years or {day.year}
    return day.strftime('%y-%m-%d' if len(years) > 1 else '%m-%d')


def _amount_group_cell(state, row_id):
    from .expense_amount_group_ui import status_cell
    annotation = (state.get('by_cost_id') or {}).get(row_id)
    return status_cell(annotation or {'status': 'unavailable', 'reason': state.get('reason'),
                                     'last_success_at': state.get('last_success_at')})


def _amount_group_state(tab_id, rows, kind=''):
    if board.current_role() != 'owner' or kind == 'in' or not _is_trip_tab(tab_id):
        return None
    from .expense_amount_group_service import build_state
    return build_state(board._active_store(), tab_id, cost_rows=rows)


def _manual_expense_link(move_back):
    tab = urllib.parse.parse_qs(urllib.parse.urlsplit(move_back).query).get('tab', [''])[0]
    return '/expense/new?' + urlencode({'tab': tab}) if tab else '/expense/new'


def _tables_html(incomes, expenses, *, selected, unclassified, move_back="/board", match_annotations=None,
                 amount_groups=None) -> str:
    from . import expense_amount_group_ui as gemn
    from .expense_amount_group_service import sort_for_display
    if amount_groups is not None and not amount_groups.get('available'):
        amount_groups = None
    # The ledger's default order is the transaction date ascending.  Google
    # comparison keeps its own explicit sort and must not change what the user
    # sees here.
    expenses = sorted(expenses, key=lambda row: (
        not bool(row.get('occurred_on')), row.get('occurred_on') or '',
        _expense_category_rank(row.get('item'))))
    enabled = amount_groups is not None
    extra_col = "<col class='gemn-desktop gemn-column'>" if enabled else ''
    extra_header = gemn.header_cell() if enabled else ''
    extra_blank = "<td class='gemn-desktop gemn-status-cell'></td>" if enabled else ''
    head = (
        "<div class='tw'><table id='tbl' class='data-table'>"
        "<caption class='sr'>거래 내역. 수입은 위, 지출은 아래에 있습니다.</caption>"
        # Five columns, and the widths are given to the fixed ones so the counterparty
        # and content column takes whatever is left. The amount is the last column
        # and stays right-aligned, because a ledger is read by comparing the
        # amount column down, not across.
        "<colgroup><col style='width:108px'><col><col style='width:104px'>"
        "<col style='width:210px'>"
        f"<col style='width:126px'>{extra_col}</colgroup>"
        "<thead><tr><th scope='col'>날짜</th><th scope='col'>거래처·내용</th>"
        "<th scope='col'>분류</th><th scope='col'>이용일</th>"
        f"<th scope='col' class='num'>금액</th>{extra_header}</tr></thead>")
    date_years = set()
    for row in list(incomes) + list(expenses):
        try:
            date_years.add(date.fromisoformat(str(board._shown_date(row) or '')[:10]).year)
        except (TypeError, ValueError):
            pass
    income_total = sum(board._shown_amount(r) for r in incomes)
    expense_total = sum(board._shown_amount(r) for r in expenses)
    income_group = (
        f"<tbody class='grp'><tr><th scope='colgroup' colspan='4'>수입 (COST 기록) "
        f"<a href='#google-trip-income'>수입내역 보기</a></th>"
        f"<th class='num'>{_money(income_total)}</th>{extra_blank}</tr></tbody>"
        + _table_html(incomes, kind="income", selected=selected, unclassified=False,
                      amount_groups=amount_groups, date_years=date_years)
    ) if incomes else ''
    groups = (
        income_group + "<tbody class='grp'><tr><th scope='colgroup'>지출</th>"
        "<td colspan='3'></td>"
        f"<th class='num'>{_money(expense_total)}</th>{extra_blank}</tr></tbody>"
        + "<tbody class='colhead'>" + _column_head_row().replace('</tr>', extra_header + '</tr>') + "</tbody>"
        + _table_html(expenses, kind="expense", selected=selected,
                      unclassified=unclassified, move_back=move_back,
                      match_annotations=match_annotations, amount_groups=amount_groups,
                      date_years=date_years)
        + "</table></div>")
    if amount_groups is None:
        return head + groups
    warning = ("<p class='gemn-total-warning' role='status'>시트 합계 수식 확인 필요 · 개별 지출 행 기준 비교</p>"
               if amount_groups.get('total_warning') else '')
    return gemn.styles() + warning + head + groups + gemn.render_groups(amount_groups)


def _mobile_html(incomes, expenses, *, selected, unclassified,
                  move_back="/board", match_annotations=None) -> str:
    """Mobile list-row projection of the same rows as the desktop table."""
    expenses = sorted(expenses, key=lambda row: (
        not bool(row.get('occurred_on')), row.get('occurred_on') or '',
        _expense_category_rank(row.get('item'))))
    match_annotations = match_annotations or {}

    def item(row, is_expense=False):
        rid = row["row_id"]
        kind = _row_kind_meter(row)
        category = str(row.get("item") or _income_kind_label(row) or "-")
        headline = " · ".join(text for text in (_row_party_main(row), _row_party_sub(row)) if text)
        service_dates, service_title = _service_date_labels(row) if is_expense else ('', '')
        service_label = service_dates if service_dates.startswith('이용일') else ('이용일 ' + service_dates if service_dates else '')
        secondary = " · ".join(part for part in (_ledger_date_label(row), kind, category, service_label) if part)
        match = match_annotations.get(rid) if is_expense else None
        match_hint = ''
        if match:
            reason = match.get('label') or ('복수 후보 확인 필요' if match.get('multiple') else
                      '금액+' + '+'.join(match.get('reasons') or []))
            match_hint = f"<span class='sr'>{board.esc(reason)}</span>"
        move = ''
        if unclassified:
            move = (
                "<form method='post' action='/api/rows/"
                f"{board.esc(rid)}/save' data-js-move>"
                f"<input type='hidden' name='csrf' value='{board.CSRF_TOKEN}'>"
                f"<input type='hidden' name='expected_revision' value='{row.get('revision', 1)}'>"
                "<input type='hidden' name='client_request_id' value='"
                f"{uuid.uuid4().hex}'>"
                "<input type='hidden' name='change_mode' value='exception'>"
                f"<input type='hidden' name='return_to' value='{board.esc(move_back)}'>"
                f"<label class='sr' for='mobile-move-{board.esc(rid)}'>이동할 여행</label>"
                f"<select class='psel' id='mobile-move-{board.esc(rid)}' name='display_tab_id'>"
                f"{_trip_options('', '여행 연결 없음')}</select>"
                f"<button class='btn' type='submit'>{ui_icons.icon('check')}이동</button></form>")
        selected_attr = ' aria-selected="true"' if rid == selected else ''
        return (
            f"<li class='list-row li{' pend' if unclassified else ''}' data-id='{board.esc(rid)}' "
            f"data-kind='{'expense' if is_expense else 'income'}' data-category='{board.esc(category)}' "
            f"data-revision='{int(row.get('revision') or 1)}' data-amount='{int(board._shown_amount(row))}' "
            f"tabindex='0' aria-expanded='false'{selected_attr}>"
            f"<button class='lr-hit' type='button' aria-label='{board.esc(headline)} {board.esc(_money(board._shown_amount(row)))}'>"
            f"<span class='lr-primary'><span class='party-line mobile-party'>{_merchant_icon(row)}"
            f"<span class='t'>{board.esc(headline)}</span></span></span>"
            f"<span class='lr-amount tnum {_row_amount_class(row)}'>{_money(board._shown_amount(row))}</span>"
            f"<span class='lr-secondary'>{board.esc(secondary)}{match_hint}</span></button>{move}</li>")

    income_total = sum(board._shown_amount(r) for r in incomes)
    expense_total = sum(board._shown_amount(r) for r in expenses)
    income_group = (
        f"<li class='list-group lg'><span>기존 수입</span><span class='tnum'>{_money(income_total)}</span></li>"
        + ''.join(item(r) for r in incomes)
    ) if incomes else ''
    rows = ''.join(item(r, True) for r in expenses)
    empty = '<li class="empty-state"><p class="es-title">지출 내역이 없습니다.</p></li>'
    return (
        "<ul class='lst' aria-label='거래 목록'>" + income_group +
        f"<li class='list-group lg'><span>지출</span><span class='tnum'>{_money(expense_total)}</span></li>" +
        (rows or empty) + "</ul>")

# --------------------------------------------------------------- edit panel
def _google_match_detail(row):
    """Read-only evidence on demand; never turn a display candidate into a copy decision."""
    tab_id = row.get('display_tab_id') or ''
    if row.get('row_kind') != 'expense' or board.current_role() != 'owner' or not _is_trip_tab(tab_id):
        return ''
    _, expenses, _, _ = _selected_rows(tab_id)
    preview = _expense_copy_preview(tab_id, expenses)
    match = _google_match_annotations(tab_id, [row], preview, expenses).get(row['row_id'])
    if not match:
        return ''
    lines = [board.esc(match['label'])]
    if match.get('display_candidate'):
        reason = ('복수 후보' if match.get('candidate_multiple') else
                  '금액+' + '+'.join(match.get('reasons') or []))
        lines.append('Google 장부 대조 후보: ' + board.esc(reason))
        lines.append('후보는 비교 단서이며, 같은 거래로 확정된 것은 아닙니다.')
    return ("<details class='p-src google-match-detail'><summary>Google 장부 대조 근거</summary>"
            + ''.join(f"<p class='p-sub'>{line}</p>" for line in lines) + '</details>')


def _panel_html(row, kind, *, csrf, rule_case, error, message, back, draft, google_match_detail='') -> str:
    allowed, fixed = board.editable_fields(kind, row.get("source_kind", ""),
                                           bool(row.get("is_allocation")))
    rev = row.get("revision", 1)
    amount = board._shown_amount(row)
    fields = []
    extra_fields = []
    compact_expense = row.get('row_kind') == 'expense'

    def text_field(name, label, value, *, ro=False, placeholder=""):
        # A locked source field carries no name, so neither a scripted nor a
        # plain form post can send it. The endpoint keeps its own refusal.
        return (f"<div class='f'><label for='f-{name}'>{label}</label>"
                f"<input id='f-{name}'{'' if ro else f" name='{name}'"}"
                f" class='tnum' type='text'"
                f" value='{board.esc(value or '')}'"
                f"{' readonly' if ro else ''} placeholder='{board.esc(placeholder)}'>"
                "</div>")

    def value_of(name, stored):
        if name in draft and draft[name] is not None:
            return draft[name]
        return stored

    # A field the endpoint fixes is a record, not a decision, so it is folded away
    # with the source identifiers. A field the endpoint allows stays in the open
    # form: an income row's date and amount are editable, and a locked input the
    # reader cannot reach is not an edit form.
    locked = []
    editable_source = []
    date_field = text_field("occurred_on",
                            "거래 날짜" if "occurred_on" not in fixed else "거래 날짜 (고정)",
                            board._shown_date(row), ro="occurred_on" in fixed)
    amount_field = text_field(
        "amount_krw", "거래 금액" if "amount_krw" not in fixed else "거래 금액 (고정)",
        f"{amount:,}", ro="amount_krw" in fixed)
    (locked if "occurred_on" in fixed else editable_source).append(date_field)
    (locked if "amount_krw" in fixed else editable_source).append(amount_field)
    locked.append(text_field("reservation_no", "예약번호 (고정)",
                             row.get("reservation_no", ""), ro=True))
    if len(editable_source) == 2:
        fields.append("<div class='grid2'>" + "".join(editable_source) + "</div>")
    else:
        fields.extend(editable_source)

    current_tab = value_of("display_tab_id", row.get("display_tab_id") or "")
    fields.append(
        "<div class='f f-trip-edit'><label for='f-trip-search'>여행 검색</label>"
        "<input id='f-trip-search' type='search' autocomplete='off' placeholder='여행 이름 검색'>"
        "<label for='f-display_tab_id'>여행</label>"
        f"<select id='f-display_tab_id' name='display_tab_id'{' disabled' if 'display_tab_id' not in allowed else ''}>"
        f"{_trip_options(current_tab, '여행 연결 없음')}</select></div>")
    for name, label in (("item", "항목"), ("customer_name", "이름"),
                        ("nickname", "닉네임"), ("customer_id", "고객 ID"),
                        ("income_kind", "입금 종류")):
        if name not in allowed and name not in fixed:
            continue
        if name == "income_kind":
            stored = row.get("income_kind") or ""
        else:
            stored = row.get(name, "")
        fields.append(text_field(name, label, value_of(name, stored),
                                 ro=name in fixed))
    if "description" in allowed or "description" in fixed:
        (extra_fields if compact_expense else fields).append(text_field("description", "용도",
                                 value_of("description", row.get("description", "")),
                                 ro="description" in fixed))
    (extra_fields if compact_expense else fields).append(
        "<div class='f'><label for='f-operator_note'>메모</label>"
        f"<textarea id='f-operator_note' name='operator_note'"
        f"{' disabled' if 'operator_note' not in allowed else ''}>"
        f"{board.esc(value_of('operator_note', row.get('operator_note')) or '')}"
        "</textarea></div>")
    (extra_fields if compact_expense else fields).append(
        "<div class='f'><label for='f-change_mode'>변경 이유</label>"
        "<select id='f-change_mode' name='change_mode'>"
        "<option value='exception'>예외 처리 (이 건만)</option>"
        "<option value='rule_change'>규칙 변경 (반복되는 경우)</option>"
        "</select></div>")
    if error:
        text = board.esc(error) + (f" — {board.esc(message)}" if message else "")
        note = f"<p class='f-msg err' role='alert'>{text}</p>"
    elif message:
        note = f"<p class='f-msg' role='status'>{board.esc(message)}</p>"
    else:
        # The line always exists, so a save result has somewhere to go without
        # rebuilding the panel.
        note = "<p class='f-msg' role='status'></p>"
    rule_link = ""
    if rule_case:
        rule_link = (f"<a id='rule-open' href='/rules?case={board.esc(rule_case)}'>"
                     "규칙 대화 열기</a>")
    links = [f"<a href='/row?id={board.esc(row['row_id'])}'>상세·이력</a>"]
    if row.get("row_kind") == "income":
        links.append(f"<a href='/income/{board.esc(row['row_id'])}/split'>배분</a>")
    links.append(f"<a href='/trips'>여행 관리</a>")
    links.append(f"<a href='/export'>선택 탭 출력</a>")
    links.append(rule_link)
    from . import ui_icons as _panel_icons
    return (
        # `data-row` is which row this panel belongs to. The browser reads it to
        # move to the previous or next row that is actually on screen and to keep
        # exactly one row marked as selected, so the two cannot drift apart.
        "<aside class='panel' id='panel' tabindex='-1'"
        f" data-row='{board.esc(row['row_id'])}' data-edit-kind='{'expense' if compact_expense else 'other'}' aria-label='거래 상세 편집 패널'>"
        "<div class='p-hd'><div>"
        f"<h2>거래 상세</h2><p class='p-amt tnum'>{_money(amount)}</p></div>"
        "<button class='icon' id='p-close' type='button' aria-label='패널 닫기'>×</button>"
        "</div>"
        "<form method='post' action='/api/rows/"
        f"{board.esc(row['row_id'])}/save' data-js-save>"
        f"<input type='hidden' name='csrf' value='{board.esc(csrf)}'>"
        f"<input type='hidden' name='expected_revision' value='{rev}'>"
        f"<input type='hidden' name='client_request_id' value='{uuid.uuid4().hex}'>"
        f"<input type='hidden' name='return_to' value='{board.esc(back)}'>"
        "<div class='p-bd'>"
        # The source identifier, the revision, the source kind and every field the
        # endpoint fixes are what a support answer needs and what a working day
        # does not, so they are folded away here and opened on demand. Nothing is
        # removed and no input loses its selector or its missing name: a locked
        # field is still the same input with no `name`, so no post can send it.
        + ("<div class='p-core-fields'>" + "".join(fields) + "</div>"
           + ("<details class='p-extra'><summary>추가 정보·변경 이유</summary><div class='p-extra-fields'>"
              + "".join(extra_fields) + "</div></details>" if compact_expense else "")
           + note)
        + google_match_detail
        + "<details class='p-src'>"
        "<summary>원본 정보</summary>"
        f"<p class='p-sub'>{board.esc(row.get('source_event_id') or row['row_id'])}"
        f" · {board.esc(row.get('source_kind') or '')}"
        f" · 가맹점 {board.esc(row.get('source_merchant') or '-')}</p>"
        f"{''.join(locked)}"
        "</details>"
        f"<div class='p-links'>{' · '.join(x for x in links if x)}</div>"
        "</div>"
        "<div class='p-ft'>"
        # The two walking buttons start hidden and are shown by the script from
        # the rows that are on screen. A button that cannot go anywhere is not
        # drawn, so nothing here promises a move the ledger cannot make.
        "<button class='btn p-nav' type='button' id='p-prev' hidden"
        f" aria-label='이전 거래'>{_panel_icons.icon('chevron-left')}이전</button>"
        "<button class='btn p-nav' type='button' id='p-next' hidden"
        f" aria-label='다음 거래'>다음{_panel_icons.icon('chevron-right')}</button>"
        "<span class='p-count tnum' id='p-count'></span>"
        + ("<button class='btn' type='button' id='bulk-start'>다른 거래도 함께 변경</button>" if row.get('row_kind') == 'expense' and board.current_role() == 'owner' else '') +
        f"<button class='btn primary' type='submit'>{_panel_icons.icon('save')}저장 "
        "<kbd class='kbd'>Ctrl</kbd>+<kbd class='kbd'>Enter</kbd></button>"
        f"<a class='btn' id='p-cancel' href='{board.esc(back)}'>취소 "
        "<kbd class='kbd'>Esc</kbd></a>"
        "</div></form></aside>")


# -------------------------------------------------------------------- pages
def state_query(tab_id: str, query: str = "", kind: str = "", archived: str = "") -> str:
    """Every in-app link carries the view state, so a trip switch or a refresh
    keeps the search, the filter and the archived drawer as they were."""
    parts = [f"tab={tab_id}"]
    if query:
        parts.append(f"q={quote(query)}")
    if kind:
        parts.append(f"kind={kind}")
    if archived:
        parts.append(f"arch={quote(archived)}")
    return "&".join(parts)


def _last_saved_at(tab_id: str) -> str:
    """When this tab's rows were last saved, for the global header.

    APP_SPEC 4.1 puts `저장되지 않은 변경 1건`과 마지막 저장 시각 in the global
    top area. The time is read from the append-only change ledger, so it is the
    real last save rather than a value the page made up.
    """
    if _STORE_missing():
        return ""
    try:
        if tab_id:
            row = board._STORE.conn.execute(
                "SELECT MAX(r.created_at) FROM board_revisions r"
                " JOIN board_rows b ON b.row_id = r.row_id"
                " WHERE b.display_tab_id=? AND r.kind<>'conflict'",
                (tab_id,)).fetchone()
        else:
            row = board._STORE.conn.execute(
                "SELECT MAX(created_at) FROM board_revisions"
                " WHERE kind<>'conflict'").fetchone()
    except Exception:
        return ""
    if not row or not row[0]:
        return "기록 없음"
    from .google_ledger_page import format_display_time
    return format_display_time(row[0])


def shell(title: str, *, tab_id: str, heading: str, period: str = "",
          meta: str = "", body: str, query: str = "", kind: str = "",
          archived: str = "", aside: str = "", home: bool = False,
          quick_view: bool = False, bare: bool = False) -> str:
    """The shared chrome for every screen, with the view state in the links."""
    state = state_query(tab_id, query, kind, archived)
    back = f"/board?{state}"
    # Reserve the status slot for actual unsaved edits, not routine timestamps.
    role_note = ("읽기 전용" if board.current_role() == "viewer" else "")
    context_badge = "" if quick_view else _context_badge()
    main_class = "main home-main" if home else "main"
    from . import ui_icons as _icons
    global_state = "" if home else (
        f"<p class='meta' id='global-state' data-role='{board.esc(role_note)}'>"
        "<span id='unsaved-count' hidden></span>"
        + (board.esc(role_note) if role_note else "")
        + "</p>")
    # 홈에서는 내보내기 바로가기를 두지 않는다. XLSX 출력은 장부 화면의
    # 내보내기 버튼을 사용한다. /export 기능·권한은 그대로 둔다.
    export_btn = (f"<a class='btn primary' href='/export?{board.esc(urlencode({'tab': tab_id}))}'>{_icons.icon('save')}XLSX 출력</a>"
                  if tab_id and title != '선택 탭 출력' else "")
    # bare: the body renders its own page_header (the 거래 tabs); keep only the
    # live-status slots the cross-screen refresh writes to.
    if bare:
        return (f"<div class='app'>{_nav_html(tab_id, query, kind, archived, quick_view=quick_view)}"
                f"<main class='{main_class}' id='main' tabindex='-1' data-base='{board.esc(back)}'>"
                f"<div class='page-body'>{global_state}"
                "<p class='meta' id='live-status-wrap' aria-live='polite'>"
                "<span class='meta live-ok' id='live-status' hidden></span></p>"
                f"{body}</div></main><div id='panel-slot'>{aside}</div></div>")
    main = (
        f"<main class='{main_class}' id='main' tabindex='-1' data-base='{board.esc(back)}'>"
        "<div class='page-hd'><div>"
        f"<h1>{heading}{context_badge}</h1>"
        + (f"<p class='period'>{period}</p>" if period else "")
        + (f"<p class='meta'>{meta}</p>" if meta else "")
        + global_state
        # The cross-screen refresh reports here. The element always exists, so a
        # deferred change, a lost connection and a revoked permission all have
        # somewhere to say so on any screen that carries the shell.
        + "<p class='meta' id='live-status-wrap' aria-live='polite'>"
        "<span class='meta live-ok' id='live-status' hidden></span></p>"
        "</div><div class='act'>"
        + f"{export_btn}"
        + (f"<a class='btn' href='{board.esc(back)}'>장부</a>" if not home else "")
        + "</div></div>"
        f"<div class='page-body'>{body}</div>"
        "</main>")
    slot = f"<div id='panel-slot'>{aside}</div>" if aside else "<div id='panel-slot'></div>"
    return f"<div class='app'>{_nav_html(tab_id, query, kind, archived, quick_view=quick_view)}{main}{slot}</div>"


def _selected_trip(tab_id: str):
    if tab_id == "unclassified":
        return {"display_key": "이전 귀속 목록", "is_unclassified": True}
    return next((t for t in board.live_trips(include_archived=True)
                 if t["tab_id"] == tab_id), None)


def _expense_category_rank(item: str) -> int:
    """Display-only order: 항공 → 숙박 → 교통 → 식비 → 현지경비, rest last.

    Matches existing item names (항공권/항공비/항공료/항공, 숙박비, 교통비,
    식비, 현지경비/현지). 여비교통비는 기존 분류 의미대로 교통에 둔다.
    Store order, accounting, amounts and TSV order are untouched: this only
    orders the ledger screen lists.
    """
    text = str(item or "")
    if "항공" in text:
        return 0
    if "숙박" in text:
        return 1
    if "교통" in text:
        return 2
    if "식비" in text:
        return 3
    if "현지경비" in text or "현지" in text:
        return 4
    return 5


def _sort_expenses_for_display(rows: list) -> list:
    """화면 날짜 오름차순. 같은 날짜에는 기존 분류 순서를 유지한다."""
    return sorted(rows, key=lambda r: (not bool(r.get('occurred_on')), r.get('occurred_on') or '',
                                      _expense_category_rank(r.get("item"))))


def _group_expenses_for_display(rows: list) -> list:
    """Airfare, lodging by service start, then the rest; never reorder copy data."""
    from datetime import date, timedelta

    def key(row):
        rank = min(_expense_category_rank(row.get('item')), 2)
        start_on = ''
        if rank == 1:
            match = _STAY_PATTERN.fullmatch(_stay_period(row))
            if match:
                try:
                    start, end = (date.fromisoformat(value) for value in match.groups())
                    if start <= end <= start + timedelta(days=_MAX_STAY_DAYS):
                        start_on = start.isoformat()
                except ValueError:
                    pass
        return rank, not bool(start_on), start_on

    return sorted(rows, key=key)


def _quarter_body(tab_id: str, message: str = "", error: str = "") -> str:
    """A quarter's cost tab: rows waiting for confirmation, the booked rows, and the one action that books the waiting rows."""
    from app import quarter_tab
    store = board._active_store()
    pending = quarter_tab.pending_rows(store.conn, tab_id) if store is not None else []
    booked = [r for r in board._expense_rows() if r.get('display_tab_id') == tab_id]
    pending_total = sum(int(r['amount_krw'] or 0) for r in pending)
    booked_total = sum(int(r.get('amount_krw') or 0) for r in booked)
    note = (f"<p class='status err' role='alert'>{board.esc(error)}</p>" if error else
            f"<p class='status' role='status'>{board.esc(message)}</p>" if message else "")

    def line(day, merchant, amount):
        return (f"<tr><td>{board.esc(day or '')}</td><td>{board.esc(merchant or '')}</td>"
                f"<td class='num'>{int(amount or 0):,}원</td></tr>")
    waiting = "".join(line((r.get('approval_date') or r.get('posting_date') or '')[:10], r.get('merchant'),
                           r.get('amount_krw')) for r in pending) or "<tr><td colspan='3'>기록 전 거래가 없습니다.</td></tr>"
    done = "".join(line(str(r.get('occurred_on') or '')[:10], r.get('merchant'), r.get('amount_krw'))
                   for r in booked) or "<tr><td colspan='3'>거래가 없습니다.</td></tr>"
    return ("<div class='body'>" + note +
            f"<h3>거래 {len(booked)}건 · {booked_total:,}원</h3><table><thead><tr><th>날짜</th><th>상호</th><th>금액</th></tr></thead>"
            f"<tbody>{done}</tbody></table>"
            f"<h3>기록 전 기존 거래 {len(pending)}건 · {pending_total:,}원</h3>"
            f"<table><thead><tr><th>날짜</th><th>상호</th><th>금액</th></tr></thead><tbody>{waiting}</tbody></table></div>")


def _is_trip_tab(tab_id: str) -> bool:
    """True only for actual trip tabs. False for unclassified, refunds, and quarter tabs."""
    if not tab_id or tab_id in ("unclassified", "refunds"):
        return False
    from app import quarter_tab
    if quarter_tab.parse_tab(tab_id):
        return False
    return _selected_trip(tab_id) is not None


@read_scope.scoped
def tsv_for_trip_expenses(tab_id: str, query: str = "", kind: str = "") -> dict:
    """Builds Google Sheets 7-column TSV (B:H) for the trip's expenses."""
    if not _is_trip_tab(tab_id):
        raise ValueError("INVALID_TRIP_TAB")
    _, expenses, _, _ = _selected_rows(tab_id, query, kind)
    from .sheet_expense_reconciliation import export_for_trip
    return export_for_trip(board._active_store(), expenses, tab_id,
                           allow_total_mismatch=True)


def _trip_expense_tsv(tab_id: str, expenses: list) -> dict:
    from app.google_tsv import expense_tsv
    rows = []
    for row in expenses:
        rows.append({
            "transaction_id": row.get("source_event_id") or row.get("row_id"),
            "status": "blocked" if row.get("blocked") else "ready",
            "date": row.get("occurred_on"),
            "payee": row.get("source_merchant") or row.get("description") or "",
            "category": row.get("item"),
            "period": row.get("service_period"),
            "reservation_no": row.get("reservation_no"),
            "evidence": {"카드": "card", "영수증": "receipt"}.get(row.get("evidence_type")),
            "amount_krw": row.get("display_amount_krw", row.get("amount_krw")),
        })
    return {**expense_tsv(rows, layout="rev"), "tab_id": tab_id}


def _trip_copy_html(tab_id: str, expenses: list, preview=None) -> str:
    """Renders the expense copy controls in the trip expense tool area."""
    if not _is_trip_tab(tab_id) or board.current_role() != 'owner':
        return ""
    preview = _expense_copy_preview(tab_id, expenses) if preview is None else preview
    available = bool(preview.get('source_available'))
    matched = preview.get('counts') or {}
    allowed_ids = {item['transaction_id'] for item in preview.get('results', [])
                   if item.get('status') == 'NEW_EXPENSE'} if available else set()
    allowed = [row for row in expenses
               if str(row.get('transaction_id') or row.get('source_event_id') or row.get('row_id') or '') in allowed_ids
               and not row.get('blocked') and not row.get('excluded_from_company')]
    result = _trip_expense_tsv(tab_id, allowed)
    count, total = result['row_count'], result['total_krw']
    held_detail = ("<details class='trip-copy-hold-details' hidden>"
                   "<summary>복사 제외 거래 보기</summary></details>")
    if not expenses:
        description = '복사할 지출이 없습니다.'
    elif not available:
        from .expense_copy_state import source_message
        reason = (preview.get('source_info') or {}).get('reason')
        description = source_message(reason)
    else:
        recorded = matched.get('MATCHED_MANUAL', 0) + matched.get('MATCHED_EXISTING', 0)
        held_results = [item for item in (preview.get('results') or [])
                        if item.get('status') == 'REVIEW_CONFLICT']
        held_reasons = {}
        reason_labels = {
            'MULTIPLE_OR_CONFLICTING_CANDIDATES': 'Google 원장 후보가 여러 개이거나 값이 충돌함',
            'INSUFFICIENT_UNIQUE_EVIDENCE': '금액·날짜·가맹점으로 Google 원장 한 행을 확정할 수 없음',
            'STRONG_ID_CONFLICT_OR_AMBIGUITY': '승인번호·거래 ID 후보가 충돌하거나 모호함',
            'SHEET_ROW_OCCUPIED_BY_EXISTING_LINK': 'Google 원장 행이 다른 COST 거래에 이미 연결됨',
            'EXISTING_LINK_STALE': '저장된 연결의 Google 원본이 바뀜',
            'TRIP_ID_MISMATCH': '다른 여행의 Google 행으로 확인됨',
        }
        for item in held_results:
            reason = str(item.get('reason') or 'REVIEW_CONFLICT')
            held_reasons[reason] = held_reasons.get(reason, 0) + 1
        held_count = len(held_results)
        description = f'복사 가능 {count}건 · {_money(total)} · Google 장부 일치 {recorded}건 제외'
        if held_count:
            description += f' · Google 대조가 끝나지 않은 {held_count}건 제외'
        if (preview.get('source_info') or {}).get('warning') == 'SOURCE_EXPENSE_TOTAL_MISMATCH':
            description += ' · Google 합계 수식은 확인 필요'
        if held_reasons:
            from urllib.parse import quote
            rows_by_id = {str(row.get('transaction_id') or row.get('source_event_id') or row.get('row_id') or ''): row
                          for row in expenses}
            transactions = []
            for item in held_results:
                row = rows_by_id.get(str(item.get('transaction_id') or ''), {})
                label = ' · '.join(str(value) for value in (
                    row.get('occurred_on') or '날짜 없음',
                    row.get('source_merchant') or row.get('description') or '상호 없음',
                    _money(row.get('display_amount_krw', row.get('amount_krw')) or 0)))
                detail_link = (f" <a href='/row?id={quote(str(row['row_id']), safe='')}'>거래 상세 보기</a>"
                               if row.get('row_id') else '')
                transactions.append(f"<li>{board.esc(label)}{detail_link}</li>")
            details = ''.join(
                f"<li>{board.esc(reason_labels.get(reason, 'Google 원장 대조를 확정하지 못함'))} · {count}건</li>"
                for reason, count in sorted(held_reasons.items()))
            held_detail = ("<details class='trip-copy-hold-details'>"
                           "<summary>Google 대조 제외 건의 정체와 사유 보기</summary>"
                           f"<p>이 건들은 Google에 없다고 확정할 수 없어 중복 복사를 막기 위해 제외했습니다.</p>"
                           f"<ul>{details}</ul><ul class='trip-copy-excluded'>{''.join(transactions)}</ul></details>")
    disabled = ' disabled' if not available or not count else ''
    recovery = ''
    if expenses and not available:
        from urllib.parse import quote
        reason = (preview.get('source_info') or {}).get('reason')
        source_href = '/api/google-ledger/source?trip=' + quote(tab_id, safe='')
        source_action = (f"<a class='btn' href='{board.esc(source_href)}' target='_blank' rel='noopener'>Google 원본 확인 ↗</a>"
                         if reason in {'SOURCE_EXPENSE_TOTAL_MISMATCH', 'SOURCE_EXPENSE_UNVERIFIED',
                                       'SOURCE_LAYOUT_UNSUPPORTED'} else
                         "<a class='btn' href='/google-ledger'>장부 연결 설정</a>")
        recovery = ("<div class='trip-copy-recovery'>" + source_action +
                    f"<button type='button' class='btn' data-google-sync data-csrf='{board.esc(board.CSRF_TOKEN)}'>장부 동기화</button>"
                    "<button type='button' class='btn' data-copy-recheck>다시 확인</button></div>")
    return (
        f"<section class='trip-copy-wrap expense-toolbar expense-toolbar-copy' id='trip-expense-copy' aria-label='Google 장부용 복사'>"
        f"<div class='trip-copy-info'><strong class='trip-copy-title'>Google 장부용 복사</strong>"
        f"<p class='trip-copy-desc' id='trip-copy-desc'>{board.esc(description)}</p>{held_detail}</div>"
        f"<div class='trip-copy-box'>"
        f"<button type='button' class='btn primary btn-copy-tsv' id='copy-trip-expenses' aria-describedby='trip-copy-desc' data-tab='{board.esc(tab_id)}' data-csrf='{board.esc(board.CSRF_TOKEN)}'{disabled}>"
        f"{ui_icons.icon('copy', 16)}<span>Google 장부용 복사</span>"
        f"</button>"
        f"{recovery}</div>"
        f"<p class='copy-status' id='copy-status'{(' data-google-sync-status' if recovery else '')} role='status' aria-live='polite' aria-atomic='true'></p>"
        "<div class='trip-copy-manual' hidden>"
        "<label for='trip-copy-text'>Google 시트에 붙여넣을 지출내용</label>"
        "<p id='trip-copy-text-help'>날짜부터 금액까지 7개 열입니다. 선택된 내용을 복사해 Google 시트의 B열부터 붙여넣으세요.</p>"
        "<textarea id='trip-copy-text' rows='7' readonly spellcheck='false' aria-describedby='trip-copy-text-help'></textarea>"
        "<div class='trip-copy-box'><button type='button' class='btn' data-copy-prepared>다시 복사</button>"
        "<button type='button' class='btn' data-copy-text-close>닫기</button></div></div>"
        f"</section>"
    )


def _selected_rows(tab_id: str, query: str = "", kind: str = ""):
    """The rows this tab and filter show, and the unfiltered totals beside them.

    DETAILED 12.2: the whole totals are kept beside the filtered ones, so a filter
    never quietly replaces the whole total with the result total. The live refresh
    calls this too, so a refreshed row list and a freshly loaded one are the same
    rows for the same tab and filter. Expenses are display-sorted by category;
    totals and store order are unchanged.
    """
    if tab_id == "unclassified":
        incomes = [r for r in board._income_rows() if r.get("display_tab_id") is None]
        expenses = board._unclassified_rows()
    else:
        incomes = [r for r in board._income_rows() if r.get("display_tab_id") == tab_id]
        expenses = [r for r in board._expense_rows() if r.get("display_tab_id") == tab_id]
    if kind == "in":
        expenses = []
    elif kind == "ex":
        incomes = []
    whole_income, whole_expense = list(incomes), list(expenses)
    if board.current_role() == 'owner':
        from .refund_tab import member_ids
        paired = member_ids(board._active_store())
        expenses = [r for r in expenses if r.get('source_event_id') not in paired]
        whole_expense = [r for r in whole_expense if r.get('source_event_id') not in paired]
    if query:
        def keep(row):
            blob = " ".join(str(row.get(key) or "") for key in (
                "item", "description", "operator_note", "reservation_no",
                "source_merchant", "customer_name"))
            return query in blob
        incomes = [r for r in incomes if keep(r)]
        expenses = [r for r in expenses if keep(r)]
    expenses = _sort_expenses_for_display(expenses)
    incomes = sorted(incomes, key=lambda r: (not bool(r.get('occurred_on')), r.get('occurred_on') or ''))
    return incomes, expenses, whole_income, whole_expense


@read_scope.scoped
def page(tab_id: str, query: str = "", kind: str = "", selected: str = "",
         error: str = "", message: str = "", archived: str = "",
         draft: dict = None, back: str = "", participant_query: dict = None) -> str:
    """The main ledger screen in the new design."""
    if _STORE_missing():
        return board.layout("웹 장부", "<div class='body'><p>저장소가 연결되지 않았어요.</p></div>")
    from app import quarter_tab
    if quarter_tab.parse_tab(tab_id):
        year, quarter = quarter_tab.parse_tab(tab_id)
        title = f"{year}년 {quarter}분기 기타비용"
        return _quarter_page(tab_id, title, query=query, kind=kind, message=message, error=error)
    if tab_id == 'refunds':
        from .refund_tab import render as refund_body
        return shell('환불', tab_id='refunds', heading='환불', query=query, bare=True,
                     body=                     "<div id='live-sum'></div><div id='live-rows'>" +
                     refund_body(board._active_store(), query, kind) + '</div>')
    trip = _selected_trip(tab_id)
    from .google_ledger_page import trip_income_html
    status = (f"<p class='status err' id='status' role='alert'>{board.esc(error)}</p>" if error else
              f"<p class='status' id='status' role='status'>{board.esc(message)}</p>" if message else
              "<p class='status hint' id='status' role='status' aria-live='polite'></p>")
    back = back or ("/board?" + state_query(tab_id, query, kind, archived))
    from . import participant_trip_panel as participant_panel
    participant_controls = (participant_panel.controls_from_query(participant_query or {})
                            if board.current_role() == "owner" else {})
    google_income_html = trip_income_html(
        tab_id, income_offset=participant_controls.get("income_offset", 0),
        participant_search=participant_controls.get("search", ""))
    from .trip_flight_ui import render_trip_flights
    flight_html = render_trip_flights(tab_id) if _is_trip_tab(tab_id) else ""
    from . import trip_management_ui
    participant_html = _participant_trip_panel(tab_id, participant_controls)
    reservations_html = trip_management_ui.reservations(board, trip)
    selected_panel = (panel_part(selected, back=back, error=error, message=message,
                                 draft=draft or {}) if selected else '')
    drawer_html = (
        "<dialog class='drawer' id='ledger-drawer' aria-labelledby='ledger-drawer-title'>"
        "<div class='drawer-header'><h2 id='ledger-drawer-title'>거래 상세</h2>"
        "<button class='icon-btn' type='button' id='drawer-close' data-drawer-close aria-label='닫기'>×</button></div>"
        f"<div class='drawer-body' id='panel-slot'>{selected_panel}</div></dialog>")
    whole_expenses = _selected_rows(tab_id, '', '')[3] if _is_trip_tab(tab_id) else []
    amount_groups = _amount_group_state(tab_id, whole_expenses, kind)
    workflow = ''
    if board.current_role() == 'owner' and _is_trip_tab(tab_id):
        from .trip_workflow import render as workflow_render
        workflow = workflow_render(board._active_store(), tab_id, whole_expenses, amount_groups)
    tabs = _trip_tabs_html(tab_id, query=query, kind=kind, selected=selected,
                           archived=archived, back=back, google_income_html=google_income_html,
                           participant_html=participant_html, flight_html=flight_html,
                           reservations_html=reservations_html)
    main = (
        f"<main class='main ledger-workspace' id='main' tabindex='-1' data-base='{board.esc(back)}'>"
        f"{_head_html(trip)}{status}"
        f"<div id='live-sum'>{_trip_kpi_html(tab_id) if _is_trip_tab(tab_id) else summary_part(tab_id, kind, query)}</div>"
        f"{workflow}"
        f"{tabs}"
        "<p class='meta' id='global-state' data-role='"
        f"{board.esc('읽기 전용' if board.current_role() == 'viewer' else '')}>"
        "<span id='unsaved-count' hidden></span></p>"
        "<p class='meta' id='live-status-wrap' aria-live='polite'>"
        "<span class='meta live-ok' id='live-status' hidden></span></p>"
        "</main>")
    return (f"<style>{trip_management_ui.STYLE}</style><div class='app'>"
            f"{_nav_html(tab_id, query, kind, archived)}{main}{drawer_html}"
            + (f"{board.MANUAL_EXPENSE_STYLE}<dialog id='manual-expense-dialog' aria-labelledby='mx-title'>"
               f"{board.manual_expense_form(tab_id, modal=True)}</dialog>" if board.current_role() == 'owner' else '')
            + f"</div><script>{trip_management_ui.SCRIPT}</script>")


def _quarter_page(tab_id: str, title: str, *, query: str = '', kind: str = '',
                  message: str = '', error: str = '') -> str:
    """Quarter cost tabs use the same header, steps and tab surface as trips."""
    store = board._active_store()
    from app import quarter_tab
    pending = quarter_tab.pending_rows(store.conn, tab_id) if store is not None else []
    booked = [row for row in board._expense_rows() if row.get('display_tab_id') == tab_id]
    total = sum(int(row.get('amount_krw') or 0) for row in booked)
    status = (f"<p class='status err' id='status' role='alert'>{board.esc(error)}</p>" if error else
              f"<p class='status' id='status' role='status'>{board.esc(message)}</p>" if message else '')
    header = ui_components.page_header(title, meta='여행에 속하지 않는 비용', breadcrumb=())
    step_markup = ui_components.steps([
        {'label': '지출', 'note': f'{len(booked)}건 · {total:,}원', 'href': '#quarter-expenses', 'state': 'done' if not pending else 'todo'},
        {'label': 'Google 복사', 'note': '비교 불가', 'href': '#quarter-expenses', 'state': 'todo'},
    ])
    body = _quarter_body(tab_id, message, error)
    main = (f"<main class='main ledger-workspace' id='main' tabindex='-1'>{header}{status}"
            f"<section class='settlement-steps' aria-label='정산 단계'>{step_markup}</section>"
            f"<section id='quarter-expenses' class='view-tabs'><div role='tablist'><button role='tab' aria-selected='true' aria-controls='quarter-panel'>지출</button></div>"
            f"<section id='quarter-panel' role='tabpanel'>{body}</section></section></main>")
    return f"<div class='app'>{_nav_html(tab_id, query, kind, '')}{main}</div>"


def _trip_actions(tab_id: str, back: str) -> str:
    """Compatibility hook retained for callers of the former action strip."""
    return ''


def _participant_trip_panel(tab_id: str, controls: dict) -> str:
    """Owner-only projection. Viewer HTML never receives participant names."""
    if board.current_role() != "owner" or not _selected_trip(tab_id):
        return ""
    from . import trip_insurance_policy
    if trip_insurance_policy.domestic_trip(tab_id):
        return ''
    from . import participant_trip_panel
    return participant_trip_panel.shell(trip_id=tab_id)


def _participant_trip_state(tab_id: str):
    return None


def panel_part(row_id: str, *, back: str = "/board", error: str = "",
               message: str = "", draft: dict = None) -> str:
    """Just the edit panel, for a row click without a full page load."""
    if _STORE_missing() or not row_id:
        return ""
    kind, row = board.find_row(row_id)
    if row is None:
        if row_id.startswith('card-') and board.current_role() == 'owner':
            from . import card_transactions, cards_all
            import sqlite3
            path = board._get_card_db_path()
            try:
                source = card_transactions.transaction_detail(row_id[5:], db_path=path) if path else None
            except sqlite3.OperationalError:
                source = None
            if source is not None:
                return ("<aside class='panel'><div class='p-bd'><h2>카드 거래 상세</h2>"
                        f"{cards_all.card_detail_html(source)}"
                        "<p><a href='/cards/all'>카드 내역으로 돌아가기</a></p></div></aside>")
        return ("<aside class='panel'><div class='p-bd'>"
                "<p class='muted'>없는 거래예요</p></div></aside>")
    return _panel_html(row, kind, csrf=board.CSRF_TOKEN,
                       rule_case=board.learning_case_id(row_id),
                       error=error, message=message, back=back, draft=draft or {},
                       google_match_detail=_google_match_detail(row))


def summary_part(tab_id: str, kind: str = "", query: str = "") -> str:
    if tab_id == 'refunds':
        return ''
    if _STORE_missing():
        return ""
    if _is_trip_tab(tab_id):
        return _trip_kpi_html(tab_id)
    _, _, whole_income, whole_expense = _selected_rows(tab_id, '', kind)
    recorded_income_count = len(whole_income)
    if kind == "in":
        whole_expense = []
    elif kind == "ex":
        whole_income = []

    from .google_ledger_page import get_trip_income_summary
    google_income = get_trip_income_summary(tab_id)

    if not query:
        return _summary_html(whole_income, whole_expense, recorded_income_count=recorded_income_count,
                             google_income=google_income)
    # DETAILED 12.2: a filter separates the names; the whole total stays whole.
    needle = query.strip()
    shown_in = [r for r in whole_income if _matches(r, needle)]
    shown_ex = [r for r in whole_expense if _matches(r, needle)]
    return _summary_html(
        shown_in, shown_ex,
        recorded_income_count=recorded_income_count,
        filtered=_summary_totals(shown_in, shown_ex),
        whole=_summary_totals(whole_income, whole_expense),
        google_income=google_income)


def rows_region(tab_id: str, query: str = "", kind: str = "", selected: str = "",
                archived: str = "", back: str = "") -> str:
    """The two row lists inside the one element a live refresh replaces.

    One renderer, embedded by the full page and re-rendered for a fragment, so the
    two cannot disagree about which rows exist, which one is selected, or which
    move form a row carries.
    """
    if _STORE_missing():
        return ""
    incomes, expenses, _whole_income, _whole_expense = _selected_rows(
        tab_id, query, kind)
    unclassified = tab_id == "unclassified"
    back = back or ("/board?" + state_query(tab_id, query, kind, archived))
    copy_preview = _expense_copy_preview(tab_id, expenses)
    matches = _google_match_annotations(tab_id, expenses, copy_preview, _whole_expense)
    amount_groups = _amount_group_state(tab_id, _whole_expense, kind)
    return (f"<div id='live-rows'>"
            f"{_trip_copy_html(tab_id, expenses, copy_preview)}"
            f"{_tables_html(incomes, expenses, selected=selected, unclassified=unclassified,
                            move_back=back, match_annotations=matches, amount_groups=amount_groups)}"
            f"{_mobile_html(incomes, expenses, selected=selected, unclassified=unclassified,
                            move_back=back, match_annotations=matches)}"
            f"</div>")


def rows_part(tab_id: str, query: str = "", kind: str = "", selected: str = "",
              archived: str = "") -> str:
    """The row lists' contents for a live fragment, without the region's element.

    The live sync adds that wrapper, so a bundle written here and a page rendered
    here cannot both carry `id='live-rows'` and end up with the id twice on screen.

    No "is this a real trip" test here. `분류대기` is not a trip in `trip_tabs`, so
    a guard that asked `_selected_trip` would return an empty fragment for the
    unassigned bucket, and the rows waiting there would never appear however often
    something was added to it or moved into it.
    """
    if _STORE_missing():
        return ""
    if tab_id == 'refunds':
        from .refund_tab import render as refund_body
        return refund_body(board._active_store(), query, kind)
    incomes, expenses, _whole_income, _whole_expense = _selected_rows(
        tab_id, query, kind)
    unclassified = tab_id == "unclassified"
    back = "/board?" + state_query(tab_id, query, kind, archived)
    copy_preview = _expense_copy_preview(tab_id, expenses)
    matches = _google_match_annotations(tab_id, expenses, copy_preview, _whole_expense)
    amount_groups = _amount_group_state(tab_id, _whole_expense, kind)
    return (f"{_trip_copy_html(tab_id, expenses, copy_preview)}"
            f"{_tables_html(incomes, expenses, selected=selected, unclassified=unclassified,
                            move_back=back, match_annotations=matches, amount_groups=amount_groups)}"
            f"{_mobile_html(incomes, expenses, selected=selected, unclassified=unclassified,
                            move_back=back, match_annotations=matches)}")


def viewer_trips_html(trips) -> str:
    """A viewer's own trips with their totals, for the viewer board and its
    live refresh alike.

    The caller passes trips that have already been filtered by the access store.
    This function only renders them, so there is no path here that could name a
    trip the viewer was not given.
    """
    if not trips:
        return ("<div class='sect'><h2>담당 여행</h2>"
                "<p>현재 배정된 여행이 없습니다</p></div>")
    items = "".join(
        f"<li><a href='/board?tab={board.esc(t['tab_id'])}'>{board.esc(t['display_key'])}</a>"
        f" — {board.esc(t['starts_on'])}~{board.esc(t['ends_on'])}"
        f" · 수입 {t['income_krw']:,}원 · 지출 {t['expense_krw']:,}원"
        f" · 차액 {t['balance_krw']:,}원</li>"
        for t in trips)
    return f"<div class='sect'><h2>담당 여행</h2><ul>{items}</ul></div>"


def _matches(row: dict, needle: str) -> bool:
    """Does this row contain the search text, over the fields the screen shows."""
    if not needle:
        return True
    hay = " ".join(str(row.get(f) or "") for f in (
        "occurred_on", "item", "description", "customer_name", "nickname",
        "reservation_no", "service_period", "source_merchant", "operator_note",
        "display_tab_id", "income_kind", "evidence_type"))
    return needle in hay


def _summary_totals(rows_in, rows_ex):
    """Compute displayed amounts through the board's current amount hook."""
    return (sum(board._shown_amount(r) for r in rows_in),
            sum(board._shown_amount(r) for r in rows_ex),
            len(rows_in), len(rows_ex))


def _totals_kw(query, shown_in, shown_ex, whole_in, whole_ex) -> dict:
    """The summary's keyword arguments, split only when a filter is on."""
    if not query:
        return {}

    return {"filtered": _summary_totals(shown_in, shown_ex),
            "whole": _summary_totals(whole_in, whole_ex)}


def _STORE_missing() -> bool:
    return getattr(board, "_STORE", None) is None


def render(page_html: str, title: str = "웹 장부", live_config: str = "") -> str:
    """Wrap a design fragment in the document with the design stylesheet.

    `live_config` is the JSON the cross-screen refresh script reads. It is
    optional so a screen that has nothing to poll (a login page, a rule dialog)
    simply carries no script rather than an empty one that asks for nothing.
    """
    from . import live_sync

    live = (f"{live_config}<script>{live_sync.SCRIPT}</script>"
            if live_config else "")
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{board.esc(title)}</title><style>{STYLE}</style></head>"
        f"<body>{page_html}<script>{SCRIPT}</script>{live}</body></html>")
