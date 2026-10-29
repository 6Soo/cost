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
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote

from app.google_authority import SnapshotError
from . import ledger_board as board
from . import read_scope, ui_icons

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
    """Owner work entry points for the home body, with honest states.

    This lives in the home body only. The sidebar carries the stable primary
    menu (including the single 미배정 지출 entry in the trip region), so this
    menu must not repeat those links. 미배정 지출 is intentionally absent
    here: its one entry point is the sidebar region.
    """
    if board.current_role() != 'owner':
        return ''
    from . import google_ledger_page, receipt_review, ui_icons

    def action(icon, title, note, href=''):
        if not href:
            return ''
        tag = 'a' if href else 'div'
        link = f" href='{board.esc(href)}'" if href else ''
        return (f"<{tag} class='work-action'{link}>{ui_icons.icon(icon)}"
                f"<span><strong>{title}</strong>"
                f"</span></{tag}>")

    actions = action('upload', '지출 정리', '카드 파일 추가 · 미배정 지출 정리 · 오분류 수정 · 전체 카드 검색', '/import')
    actions += action('list', '카드 전체 내역', '연도·월별 전체 카드 거래 조회 · 상세 연결', '/cards/all')
    actions += action('list', 'OTA 내역', '예약 조회 · 여행 미배정 확인 · 검색 · 이용월 조회', '/ota')
    if receipt_review.enabled():
        actions += action('receipt', '영수증 처리', '이미지 업로드 · 수동 입력 · 복사', '/receipts')
    else:
        actions += action('receipt', '영수증 처리 · 설정 필요', '비공개 저장 위치를 연결하면 수동 입력을 사용할 수 있어요')
    return ("<section class='work-menu' id='work-menu' aria-label='지금 할 업무'>"
            f"<h2>지금 할 업무</h2><nav class='work-actions'>{actions}</nav></section>")


def _nav_html(tab_id: str, query: str, kind: str = "", archived: str = "") -> str:
    """The whole trip rail: the brand link, the search box, the region, the footer.

    The search box sits outside the swappable region on purpose. It holds what the
    user typed, and a refresh that replaced it would take the caret and the text
    with it.
    """
    from . import ui_icons as _icons
    if board.current_role() == 'owner':
        from . import flight_passenger_page, receipt_review
        primary = ("<nav class='site-links' aria-label='주요 메뉴'>"
                   f"<a href='/board'>{_icons.icon('book-open', 18)}<span class='nm'>여행 장부</span></a>"
                   f"<a href='/import'>{_icons.icon('upload', 18)}<span class='nm'>지출 정리</span></a>"
                   f"<a href='/cards/all'>{_icons.icon('credit-card', 18)}<span class='nm'>카드 전체 내역</span></a>"
                   f"<a href='/ota'>{_icons.icon('list', 18)}<span class='nm'>OTA 내역</span></a>")
        if receipt_review.enabled():
            primary += (f"<a href='/receipts'>{_icons.icon('receipt', 18)}"
                        "<span class='nm'>영수증 처리</span></a>")
        management = ("</nav><h2 class='nav-sec'>관리</h2>"
                      "<nav class='site-links' aria-label='관리 메뉴'>"
                      f"<a href='/trips'>{_icons.icon('map', 18)}<span class='nm'>여행 관리</span></a>"
                      f"<a href='/reserve-links'>{_icons.icon('link', 18)}<span class='nm'>예약 명단·여행 연결</span></a>")
        if flight_passenger_page.enabled():
            management += (f"<a href='/flight-passengers'>{_icons.icon('users', 18)}"
                           "<span class='nm'>항공권 예약 확인</span></a>")
        primary += (management
                    + f"<a href='/access/admin'>{_icons.icon('users', 18)}<span class='nm'>계정·권한 관리</span></a>"
                    + "</nav>")
    else:
        primary = ("<nav class='site-links' aria-label='주요 메뉴'>"
                   f"<a href='/board'>{_icons.icon('book-open', 18)}<span class='nm'>여행 장부</span></a>")
        primary += '</nav>'
    search = (
        "<form class='nav-q' method='get' action='/board'>"
        f"<input type='hidden' name='tab' value='{board.esc(tab_id)}'>"
        f"{f'<input type=hidden name=kind value={board.esc(kind)}>' if kind else ''}"
        "<label class='sr' for='tripq'>여행 검색</label>"
        f"<input id='tripq' name='q' type='search' placeholder='여행 이름·코드'"
        f" value='{board.esc(query)}' autocomplete='off'></form>")
    return (
        "<aside class='nav' id='nav' aria-label='여행 목록'>"
        "<div class='nav-hd'><a class='brand brand-link' href='/' aria-label='숲길여행 회계 홈으로 이동'><img src='/assets/brand/wallet-favicon-v2.png' alt='' width='20' height='20'>숲길여행 회계</a></div>"
        f"{primary}{search}"
        + nav_region(tab_id, query, kind, archived)
        + ("<footer class='nav-ft' aria-label='여행 메뉴 안내'>"
           "<a class='all-trips-link' href='/trips'>"
           "<span>전체 여행 보기</span>"
           f"{_icons.icon('chevron-right', 16)}</a>"
           "<p class='footer-help'>지난 여행과 진행 중인 여행은 여행 관리에서 확인할 수 있어요.</p>"
           "</footer>")
        + "</aside>"
        "<div class='nav-mask' id='nav-mask' hidden></div>")


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


def _nav_region_inner(tab_id: str, query: str, kind: str = "",
                      archived: str = "") -> str:
    """The trip rail region's contents, without the region's own element.

    One renderer for this markup. The page puts it inside `nav_region`, and a live
    fragment carries the same string, so a refreshed rail and a freshly loaded one
    cannot disagree about the selected trip, the archived drawer, or a total.
    """
    state = state_query(tab_id, query, kind, archived)
    drawer_open = archived in ("1", "open", "true")

    def entry(label, href, count, current, warn=False, archived_row=False, icon=""):
        cls = "nv sel" if current else ("nv nv-arch" if archived_row else "nv")
        badge = (f"<span class='ct{' warn' if warn else ''}'>{count}</span>"
                 if count is not None else "")
        icon_markup = f"<span class='nv-icon'>{icon}</span>" if icon else ""
        return (f"<li><a class='{cls}' href='{href}'"
                f"{' aria-pressed=\"true\"' if current else ''}>"
                f"{icon_markup}<span class='nm'>{label}</span>{badge}</a></li>")

    sections = []
    trips = board.live_trips(include_archived=True)
    # A viewer's rail lists only the trips its allowlist names. The rail is
    # rendered by the shared chrome, so without this the `+ 탭 추가` control was
    # correctly hidden from a viewer while the trip names beside it were not:
    # a trip the viewer may not read was still named, and its total was still
    # shown. The role is decided on the server for this request, so the filter
    # is the server's own answer and not anything the request asked for.
    if board.current_role() == "viewer":
        allowed = board.viewer_visible_tabs(board.current_request_session())
        trips = [t for t in trips if t["tab_id"] in allowed]
    # Display grouping only: never archive or rewrite a trip or its ledger.
    def previous_trip(trip):
        try:
            return date.fromisoformat(trip.get("starts_on") or "") <= date(2026, 6, 25)
        except (TypeError, ValueError):
            return False

    previous_rows = [t for t in trips if not t.get("deleted") and previous_trip(t)]
    active = [t for t in trips if not t.get("archived") and not t.get("deleted")
              and not previous_trip(t)]
    archived_rows = [t for t in trips if t.get("archived") and not t.get("deleted")
                     and not previous_trip(t)]
    def short_date(value):
        parts = str(value or '').split('-')
        if len(parts) == 3 and parts[0].isdigit() and len(parts[0]) == 4:
            return f"{parts[1]}.{parts[2]}"
        return str(value or '')

    def trip_entry(trip):
        # 금액 badge를 표시하지 않는다. 수입 합계는 장부 화면의 합계 영역이
        # 맡고, 목록에는 일정과 이동 상태만 둔다. Google 집계 금액과의 혼동을
        # 막기 위한 표시 변경이며 집계 로직은 그대로 둔다.
        start, end = trip.get("starts_on") or "", trip.get("ends_on") or ""
        if start and end:
            dates = f"{short_date(start)}~{short_date(end)}"
        else:
            dates = short_date(start or end) or None
        return entry(
            board.esc(trip["display_key"]),
            f"/board?{state_query(trip['tab_id'], query, kind, archived)}",
            dates, trip["tab_id"] == tab_id)

    listed = []
    for trip in active:
        if query and query not in (trip["display_key"] + trip["destination"]):
            continue
        listed.append(trip_entry(trip))
    if board.current_role() == "owner":
        from app import quarter_tab
        for quarter in (3, 4):
            tab = quarter_tab.tab_id_for(_CURRENT_YEAR, quarter)
            listed.append(entry(f"{quarter}분기 기타비용", "/board?" + state_query(tab, query, kind, archived),
                                None, tab_id == tab))
    sections.append(("<h2 class='nav-sec'>여행 목록</h2>",
                     f"<ul class='nav-list' id='trips'>{''.join(listed) or '<li class=\"muted\" style=\"padding:6px 8px\">여행이 없어요</li>'}</ul>"))
    # 미배정 지출은 지출 정리(/import) 맨 위에서 처리한다. 여행 레일에는 따로 두지 않는다.
    arch_head = ""
    if board.current_role() == 'owner':
        sections.append(("<h2 class='nav-sec'>환불</h2>", "<ul class='nav-list'>" + entry(
            "환불", f"/board?{state_query('refunds')}",
            None, tab_id == 'refunds', icon=ui_icons.icon('rotate-ccw', 18)) + "</ul>"))
    if archived_rows:
        toggle_state = state_query(tab_id, query, kind, "" if drawer_open else "1")
        arch_head = (
            "<h2 class='nav-sec'>보관 목록</h2>"
            "<a class='nv nav-toggle' id='arch-toggle'"
            f" href='/board?{board.esc(toggle_state)}'"
            f" aria-expanded='{'true' if drawer_open else 'false'}'"
            " aria-controls='archived'>"
            f"<span class='nm'>보관 {len(archived_rows)}개</span>"
            f"<span class='ct'>{'접기' if drawer_open else '펼치기'}</span></a>")
    if archived_rows and drawer_open:
        rows = []
        for trip in archived_rows:
            href = f"/board?{state_query(trip['tab_id'], query, kind, archived)}"
            view = (
                f"<a class='btn arch-view' href='{href}'>보기</a>")
            restore = (
                "<form method='post' class='arch-restore' "
                f"action='/api/trips/{board.esc(trip['tab_id'])}/meta'>"
                f"<input type='hidden' name='csrf' value='{board.CSRF_TOKEN}'>"
                f"<input type='hidden' name='expected_revision' value='{trip.get('revision', 1)}'>"
                "<input type='hidden' name='client_request_id' value='"
                f"{uuid.uuid4().hex}'>"
                "<input type='hidden' name='archived' value='0'>"
                "<input type='hidden' name='return_to' value='"
                f"/board?{board.esc(state_query(tab_id, query, kind, archived))}'>"
                "<button class='btn' type='submit'>복원</button></form>")
            rows.append(
                "<li class='arch-row'>"
                f"<a class='nv nv-arch' href='{href}'>"
                f"<span class='nm'>{board.esc(trip['display_key'])}</span></a>"
                f"{view}{restore}</li>")
        arch_head += f"<ul class='nav-list' id='archived'>{''.join(rows)}</ul>"
    previous = ""
    matching_previous = [t for t in previous_rows
                         if not query or query in (t["display_key"] + t["destination"])]
    from app import quarter_tab
    show_quarters = board.current_role() == "owner"
    if matching_previous or show_quarters:
        # Default collapsed: the server never auto-opens for a selected trip or
        # a search. The user expands with one click (native details/summary).
        # Each quarter opens with the list, and focus moves into a group the
        # user has just opened, only after that user action.
        store = board._active_store()
        quarters = _quarter_groups(matching_previous)
        if show_quarters:
            quarters = sorted(set(quarters) | {(_CURRENT_YEAR, n) for n in (1, 2)})
        groups = []
        for year, quarter in quarters:
            members = [t for t in matching_previous if _quarter_of(t) == (year, quarter)]
            label = f"{quarter}분기" if year == _CURRENT_YEAR else f"{year}년 {quarter}분기"
            cost = ""
            if show_quarters and year == _CURRENT_YEAR and quarter <= 2:
                tab = quarter_tab.tab_id_for(year, quarter)
                count = 0  # nothing waits for a person on a quarter tab
                cost = entry(f"{quarter}분기 기타비용", "/board?" + state_query(tab, query, kind, archived),
                             count or None, tab_id == tab)
            rows = cost + ''.join(trip_entry(t) for t in members)
            body = ('<ul class="nav-list">' + rows + '</ul>' if rows
                    else "<p class='nav-sec'>여행 없음</p>")
            groups.append(
                "<details class='prev-q'>"
                f"<summary class='nv' onclick=\"{_FOCUS_ON_OPEN}\"><span aria-hidden='true'>▸</span>"
                f"<span class='nm'>{label}</span><span class='ct'>{len(members)}개</span></summary>"
                f"{body}</details>")
        previous = (
            '<details id="previous-trips">'
            f"<summary class='nv' onclick=\"{_FOCUS_ON_OPEN}\"><span aria-hidden='true'>▸</span><span class='nm'>이전 여행</span>"
            f'<span class="ct">{len(matching_previous)}개</span></summary>'
            '<p class="nav-sec">2026년 6월 25일까지 여행</p>'
            + ''.join(groups) + '</details>')
    return "".join(head + body for head, body in sections) + arch_head + previous


def nav_region(tab_id: str, query: str = "", kind: str = "",
               archived: str = "") -> str:
    """The trip rail's own element: the one region a live refresh replaces.

    This is the single renderer for that region, and the full page embeds exactly
    what this returns. The alternative — rendering the whole rail and slicing the
    region back out of the string — is how a fragment ends up carrying the sidebar
    footer and the mask element that sit after it, which then arrive as a second
    `nav-mask` and a stray footer on every refresh.

    It returns the region's *outer* element, so a caller that only wants the inner
    markup has to say so rather than guess where the region ended.
    """
    return (f"<div id='live-nav'>{_nav_region_inner(tab_id, query, kind, archived)}"
            "</div>")


def nav_part(tab_id: str, query: str = "", kind: str = "",
             archived: str = "") -> str:
    """The swappable part of the trip rail, for a live refresh.

    The inner markup only, without the region's own element: the live sync adds
    that wrapper itself, so a bundle written here and a page rendered here cannot
    end up with two elements carrying the same id.
    """
    if _STORE_missing():
        return ""
    return _nav_region_inner(tab_id, query, kind, archived)


def _head_html(trip) -> str:
    from . import ui_icons as _icons
    if trip is None:
        title, period, meta = "여행을 선택해 주세요", "", ""
    elif trip.get("is_unclassified"):
        title = "분류대기"
        period = "여행을 정하지 않은 내역이에요"
        meta = "이 목록을 정리하면 여행 합계가 함께 갱신돼요"
    else:
        title = board.esc(trip["display_key"])
        period = f"{_icons.icon('calendar-days')}<span class='tnum'>{board.esc(trip['starts_on'])}~{board.esc(trip['ends_on'])}</span>"
        meta = (f"<span>작성일 <b>{board.esc(trip.get('prepared_on') or '-')}</b></span>"
                f"<span>{_icons.icon('users')}담당자 <b>{board.esc(trip.get('prepared_by_name') or '-')}</b></span>"
                f""
                f"<span><a class='btn' href='/trips'>{_icons.icon('map')}여행 관리</a></span>")
    return (
        "<div class='page-hd'><div>"
        f"<h1>{title}<span class='synth'>{board.data_status_mark()}</span></h1>"
        f"<p class='period'>{period}</p>"
        f"<p class='meta'>{meta}</p></div>"
        "<div class='act'>"
        + _reserve_link_link_html()
        + _review_link_html()
        + f"<a class='btn' href='/import'>{_icons.icon('upload')}카드 가져오기</a>"
        f"<a class='btn primary' href='/export'>{_icons.icon('save')}XLSX 출력</a>"
        "</div></div>")


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
    return ("<a class='btn' id='reserve-link' href='/reserve-links' aria-label='예약 명단·여행 연결'>"
            f"{_icons.icon('link')}예약 연결</a>")


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
    return (f"<div class='net-income'><i title='총수입 − 지출'>{ui_icons.icon('arrow-up-down')}{label}</i>"
            f"<b aria-label='{label}, 총수입에서 지출을 뺀 금액'>{_money(value)}</b>"
            "<small>총수입 − 지출</small></div>")


def _summary_html(incomes, expenses, *, filtered=None, whole=None, recorded_income_count=None,
                  google_income=None) -> str:
    """The totals bar.

    DETAILED 12.2: with a filter on, the whole total and the result total get
    separate names, and the whole total is never quietly replaced by the result.
    `filtered` is (income, expense, count_income, count_expense) for the rows
    the filter left visible; `whole` is the same for the unfiltered tab.
    """
    expense = sum(board._shown_amount(r) for r in expenses)
    scope = "<span class='scope'>기록된 거래</span>"

    if google_income and not incomes and recorded_income_count in (0, -1):
        if google_income.get('show_rows'):
            income = google_income['amount']
            count_in = google_income['count']
            if filtered is not None and whole is not None:
                return (
                    f"<div class='sum tnum' id='sum'>{scope}"
                    f"<div><i>{ui_icons.icon('book-open')}전체 총수입</i><b>{_money(income)}</b></div>"
                    f"<div><i>{ui_icons.icon('credit-card')}전체 지출</i><b>{_money(whole[1])}</b></div>"
                    f"<div class='filtered-total'><i>검색 결과 지출</i><b>{_money(filtered[1])}</b></div>"
                    f"{_net_income_summary(income - whole[1], '전체 ')}"
                    f"<span class='n'>전체 수입 {count_in}건 · 전체 지출 {whole[3]}건 · 검색 결과 지출 {filtered[3]}건</span></div>")
            return (
                f"<div class='sum tnum' id='sum'>{scope}"
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
                    f"<div class='sum tnum' id='sum'>{scope}{income_notice}"
                    f"<div><i>{ui_icons.icon('credit-card')}전체 지출</i><b>{_money(whole[1])}</b></div>"
                    f"<div class='filtered-total'><i>검색 결과 지출</i><b>{_money(filtered[1])}</b></div>"
                    f"<span class='n'>전체 지출 {whole[3]}건 · 검색 결과 지출 {filtered[3]}건</span></div>")
            return (
                f"<div class='sum tnum' id='sum'>{scope}{income_notice}"
                f"<div><i>{ui_icons.icon('credit-card')}지출</i><b>{_money(expense)}</b></div>"
                f"<span class='n'>지출 {len(expenses)}건</span></div>")

    income = sum(board._shown_amount(r) for r in incomes)
    note = ""
    if not incomes and recorded_income_count in (0, -1):
        if filtered is not None and whole is not None:
            return (f"<div class='sum tnum' id='sum'>{scope}"
                    f"<div><i>전체 지출</i><b>{_money(whole[1])}</b></div>"
                    f"<div class='filtered-total'><i>검색 결과 지출</i><b>{_money(filtered[1])}</b></div>"
                    f"<span class='n'>전체 지출 {whole[3]}건 · 검색 결과 지출 {filtered[3]}건</span></div>")
        return (f"<div class='sum tnum' id='sum'>{scope}"
                f"<div><i>{ui_icons.icon('credit-card')}지출</i><b>{_money(expense)}</b></div>"
                f"<span class='n'>지출 {len(expenses)}건</span></div>")
    if filtered is None or whole is None:
        return (
            f"<div class='sum tnum' id='sum'>{scope}<div><i>{ui_icons.icon('book-open')}총수입</i><b>{_money(income)}</b></div>"
            f"<div><i>{ui_icons.icon('credit-card')}지출</i><b>{_money(expense)}</b></div>"
            f"{_net_income_summary(income - expense)}"
            f"<span class='n'>수입 {len(incomes)}건 · 지출 {len(expenses)}건</span></div>" + note)
    fincome, fexpense, finc, fexp = filtered
    wincome, wexpense, winc, wexp = whole
    return (
        f"<div class='sum tnum' id='sum'>{scope}"
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


def _stay_text(row) -> str:
    """The lodging dates from the source's service period, never from the reservation number.

    A missing, unreadable, reversed or implausibly long period is shown as unknown
    rather than guessed. The card's approval or payment date is a different fact.
    """
    from datetime import date, timedelta
    unknown = "\uC774\uC6A9\uC77C \uD655\uC778 \uD544\uC694"
    match = _STAY_PATTERN.fullmatch(str(row.get("service_period") or "").strip())
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
    return f"{_day_label(start, start.year != end.year)} ~ {_day_label(end, start.year != end.year)} · {stay}"


def _day_label(day, with_year: bool) -> str:
    """A calendar day as read on a ledger line: 10월 14일(수), with the year when the stay crosses one."""
    weekday = "월화수목금토일"[day.weekday()]
    prefix = f"{day.year}년 " if with_year else ""
    return f"{prefix}{day.month}월 {day.day}일({weekday})"


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
        f"{_trip_options('', '분류대기(여행 미정)')}</select>"
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
        amount = _match_amount(web_row.get('amount_krw'))
        if amount is not None:
            web_by_amount.setdefault(amount, []).append(web_index)
    for g_index, google_row in enumerate(google_rows):
        amount = _match_amount(google_row.get('amount'))
        if amount is None:
            continue
        for web_index in web_by_amount.get(amount, []):
            web_row = web_rows[web_index]
            reasons = []
            g_date, w_date = _match_date(google_row.get('date')), _match_date(
                web_row.get('occurred_on') or web_row.get('ledger_date'))
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
            g_reservation = _match_text(google_row.get('reservation'))
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


def _google_match_annotations(tab_id, rows):
    """Read the already selected, fresh Google snapshot for owner-only display hints."""
    if board.current_role() != 'owner' or not tab_id or tab_id == 'unclassified' or not rows:
        return {}
    try:
        from . import google_ledger_page as google
        if not google.enabled():
            return {}
        path = google.snapshot_path()
        mapping = google.load_mapping(path)
        keys = [key for key, linked in mapping.items() if linked == tab_id]
        if len(keys) != 1:
            return {}
        snapshot, private_rows = google.google_authority.load_consistent(path, google.rows_path())
        payload = google.owner_payload(google.snapshot_for_display(snapshot), google.load_choices(path))
        trips = [trip for trip in payload.get('trips', []) if trip.get('key') == keys[0]]
        if len(trips) != 1:
            return {}
        trip = trips[0]
        source = trip.get('chosen_source')
        source_state = (payload.get('sources') or {}).get(source) or {}
        copy = (trip.get('copies') or {}).get(source) or {}
        if (source not in ('main', 'archive') or source_state.get('status') != 'ok'
                or source_state.get('stale') or copy.get('layout') != 'rev'
                or not (copy.get('expense') or {}).get('verified')
                or set(trip.get('review') or []) & google.OWNER_CHOICE_BLOCKERS):
            return {}
        detail = google.owner_rows(private_rows, keys[0], source)
        if detail is None:
            return {}
        matches = _google_expense_matches(detail.get('expense') or [], rows)
        return {rows[index].get('row_id'): value for index, value in matches.items()
                if rows[index].get('row_id')}
    except (SnapshotError, AttributeError, KeyError, OSError, TypeError, ValueError):
        return {}


def _table_html(rows, *, kind, selected, unclassified, move_back="/board", match_annotations=None) -> str:
    if not rows:
        return ("<tbody><tr class='empty'><td colspan='5'>"
                f"{'수입 내역이 없어요' if kind == 'income' else '지출 내역이 없어요'}"
                "</td></tr></tbody>")
    body = []
    match_annotations = match_annotations or {}
    for row in rows:
        rid = row["row_id"]
        amount = board._shown_amount(row)
        item = row.get('item') or ''
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
            label = ('복수 후보 확인 필요' if match['multiple'] else
                     '금액+' + '+'.join(match['reasons']))
            hint_id = 'google-match-' + str(rid)
            match_class = ' class="google-match-candidate"'
            match_attributes = f" aria-describedby='{board.esc(hint_id)}'"
            match_description = (f"<span class='sr' id='{board.esc(hint_id)}'>Google 장부 대조 후보: "
                                 f"{board.esc(label)}</span>")
        body.append(
            f"<tr{match_class} data-id='{board.esc(rid)}' tabindex='0'"
            f"{match_attributes}"
            f"{' aria-selected="true"' if rid == selected else ''}>"
            f"<td class='c-date tnum'>{match_description}{board.esc(board._shown_date(row))}</td>"
            f"{_party_cell(row)}"
            f"<td class='c-item'><span class='category-line'>{_category_icon(row)}{board.esc(_row_item(row))}</span></td>"
            f"<td class='c-stay'>{board.esc(_stay_text(row)) if item == '숙박비' else ''}</td>"
            + f"<td class='num tnum c-amt {_row_amount_class(row)}'>{_money(amount)}</td>"
            f"</tr>")
        if unclassified:
            # The waiting row's travel picker lives in its own action row below
            # the data row, not in the removed memo cell. Same form contract.
            body.append(
                f"<tr class='move-row' data-move-for='{board.esc(rid)}'>"
                f"<td colspan='5'>{_move_form(row, move_back)}</td></tr>")
    return f"<tbody>{''.join(body)}</tbody>"


def _column_head_row() -> str:
    """Column titles repeated above the expense rows (display only)."""
    return ("<tr><th scope='col'>날짜</th><th scope='col'>거래처·내용</th>"
            "<th scope='col'>분류</th><th scope='col'>이용일</th>"
            "<th scope='col' class='num'>금액</th></tr>")


def _tables_html(incomes, expenses, *, selected, unclassified, move_back="/board", match_annotations=None) -> str:
    head = (
        "<div class='tw'><table id='tbl'>"
        "<caption class='sr'>거래 내역. 수입은 위, 지출은 아래에 있습니다.</caption>"
        # Five columns, and the widths are given to the fixed ones so the counterparty
        # and content column takes whatever is left. The amount is the last column
        # and stays right-aligned, because a ledger is read by comparing the
        # amount column down, not across.
        "<colgroup><col style='width:108px'><col style='width:28%'><col style='width:104px'>"
        "<col style='width:280px'>"
        "<col style='width:126px'></colgroup>"
        "<thead><tr><th scope='col'>날짜</th><th scope='col'>거래처·내용</th>"
        "<th scope='col'>분류</th><th scope='col'>이용일</th>"
        "<th scope='col' class='num'>금액</th></tr></thead>")
    income_total = sum(board._shown_amount(r) for r in incomes)
    expense_total = sum(board._shown_amount(r) for r in expenses)
    income_group = (
        f"<tbody class='grp'><tr><th scope='colgroup' colspan='4'>수입 (COST 기록) "
        f"<a href='#google-trip-income'>수입내역 보기</a></th>"
        f"<th class='num'>{_money(income_total)}</th></tr></tbody>"
        + _table_html(incomes, kind="income", selected=selected, unclassified=False)
    ) if incomes else ''
    groups = (
        income_group + "<tbody class='grp'><tr><th scope='colgroup'>지출</th>"
        "<td colspan='3'><a class='btn' id='add-manual-expense' href='/expense/new'>"
        f"{ui_icons.icon('pencil')}수기 지출 추가</a></td>"
        f"<th class='num'>{_money(expense_total)}</th></tr></tbody>"
        + "<tbody class='colhead'>" + _column_head_row() + "</tbody>"
        + _table_html(expenses, kind="expense", selected=selected,
                      unclassified=unclassified, move_back=move_back,
                      match_annotations=match_annotations)
        + "</table></div>")
    return head + groups


def _mobile_html(incomes, expenses, *, selected, unclassified,
                  move_back="/board", match_annotations=None) -> str:
    match_annotations = match_annotations or {}
    def item(row, is_expense=False):
        rid = row["row_id"]
        move = ""
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
                f"{_trip_options('', '분류대기(여행 미정)')}</select>"
                f"<button class='btn' type='submit'>{ui_icons.icon('check')}이동</button></form>")
        kind = _row_kind_meter(row)
        cls = "li pend" if unclassified else "li"
        match = match_annotations.get(rid) if is_expense else None
        if match:
            cls += ' google-match-candidate'
        match_hint = ''
        if match:
            reason = ('복수 후보 확인 필요' if match['multiple'] else
                      '금액+' + '+'.join(match['reasons']))
            match_hint = (f"<span class='sr'>Google 장부 대조 후보: "
                          f"{board.esc(reason)}</span>")
        # Two-line business summary only: date, kind tag, category, vendor,
        # purpose, amount. The origin detail lives in the edit panel, so no
        # per-row details element here (density first).
        cat = row.get("item") or _income_kind_label(row) or "-"
        main_text = _row_party_main(row)
        sub_text = _row_party_sub(row)
        headline = " \u00b7 ".join(text for text in (main_text, sub_text) if text)
        tag_cls = "tag in" if kind == "수입" else "tag"
        return (
            f"<button class='{cls}' type='button' data-id='{board.esc(rid)}'"
            f"{' aria-selected="true"' if rid == selected else ''}>"
            f"<span class='m-row'><span class='d tnum'>"
            f"{board.esc(board._shown_date(row))}</span>"
            f"<span class='{tag_cls}'>{board.esc(kind)}</span>"
            f"<span class='m-cat category-line'>{_category_icon(row)}{board.esc(cat)}</span>"
            f"<span class='a tnum {_row_amount_class(row)}'>"
            f"{_money(board._shown_amount(row))}</span>{match_hint}</span>"
            f"<span class='party-line mobile-party'>{_merchant_icon(row)}<span class='t'>{board.esc(headline)}</span></span></button>{move}")

    income_total = sum(board._shown_amount(r) for r in incomes)
    expense_total = sum(board._shown_amount(r) for r in expenses)
    income_group = (
        f"<p class='lg'><span>기존 수입</span><span class='tnum'>{_money(income_total)}</span></p>"
        + ''.join(item(r) for r in incomes)
    ) if incomes else ''
    return (
        "<div class='lst'>"
        + income_group +
        f"<p class='lg'><span>지출</span><span class='tnum'>{_money(expense_total)}</span>"
        "<a class='btn' id='add-manual-expense-mobile' href='/expense/new'>"
        f"{ui_icons.icon('pencil')}수기 지출 추가</a></p>"
        f"{''.join(item(r, True) for r in expenses) or '<p class=\"muted\" style=\"padding:12px 16px\">지출 내역이 없어요</p>'}"
        "</div>")


# --------------------------------------------------------------- edit panel
def _panel_html(row, kind, *, csrf, rule_case, error, message, back, draft) -> str:
    allowed, fixed = board.editable_fields(kind, row.get("source_kind", ""),
                                           bool(row.get("is_allocation")))
    rev = row.get("revision", 1)
    amount = board._shown_amount(row)
    fields = []

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
        "<div class='f'><label for='f-display_tab_id'>여행</label>"
        f"<select id='f-display_tab_id' name='display_tab_id'{' disabled' if 'display_tab_id' not in allowed else ''}>"
        f"{_trip_options(current_tab, '분류대기(여행 미정)')}</select></div>")
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
        fields.append(text_field("description", "용도",
                                 value_of("description", row.get("description", "")),
                                 ro="description" in fixed))
    fields.append(
        "<div class='f'><label for='f-operator_note'>메모</label>"
        f"<textarea id='f-operator_note' name='operator_note'"
        f"{' disabled' if 'operator_note' not in allowed else ''}>"
        f"{board.esc(value_of('operator_note', row.get('operator_note')) or '')}"
        "</textarea></div>")
    fields.append(
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
        f" data-row='{board.esc(row['row_id'])}' aria-label='거래 상세 편집 패널'>"
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
        f"{''.join(fields)}{note}"
        "<details class='p-src'>"
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
          archived: str = "", aside: str = "", home: bool = False) -> str:
    """The shared chrome for every screen, with the view state in the links."""
    state = state_query(tab_id, query, kind, archived)
    back = f"/board?{state}"
    # APP_SPEC 4.1: the global top area carries the unsaved row count and the
    # last saved time. The count is filled in by the script as edits become
    # dirty; the time is the ledger's own last save for this tab.
    role_note = ("읽기 전용" if board.current_role() == "viewer" else "")
    main_class = "main home-main" if home else "main"
    from . import ui_icons as _icons
    global_state = "" if home else (
        f"<p class='meta' id='global-state' data-role='{board.esc(role_note)}'>"
        "<span id='unsaved-count'>저장되지 않은 변경 없음</span>"
        f"<span>{ui_icons.icon('save')}최근 저장 {_last_saved_at(tab_id)}</span>"
        + (f" · {board.esc(role_note)}" if role_note else "")
        + "</p>")
    # 홈에서는 내보내기 바로가기를 두지 않는다. XLSX 출력은 장부 화면의
    # 내보내기 버튼을 사용한다. /export 기능·권한은 그대로 둔다.
    export_btn = ("" if home
                  else f"<a class='btn primary' href='/export'>{_icons.icon('save')}XLSX 출력</a>")
    main = (
        f"<main class='{main_class}' id='main' tabindex='-1' data-base='{board.esc(back)}'>"
        "<div class='page-hd'><div>"
        f"<h1>{heading}<span class='synth'>{board.data_status_mark()}</span></h1>"
        + (f"<p class='period'>{period}</p>" if period else "")
        + (f"<p class='meta'>{meta}</p>" if meta else "")
        + global_state
        # The cross-screen refresh reports here. The element always exists, so a
        # deferred change, a lost connection and a revoked permission all have
        # somewhere to say so on any screen that carries the shell.
        + "<p class='meta' id='live-status-wrap' aria-live='polite'>"
        "<span class='meta live-ok' id='live-status' hidden></span></p>"
        "</div><div class='act'>"
        f"<a class='btn' href='/import'>{_icons.icon('upload')}카드 가져오기</a>"
        f"{export_btn}"
        f"<a class='btn' href='{board.esc(back)}'>장부</a>"
        "</div></div>"
        f"<div class='page-body'>{body}</div>"
        "</main>")
    slot = f"<div id='panel-slot'>{aside}</div>" if aside else "<div id='panel-slot'></div>"
    return f"<div class='app'>{_nav_html(tab_id, query, kind, archived)}{main}{slot}</div>"


def _selected_trip(tab_id: str):
    if tab_id == "unclassified":
        return {"display_key": "분류대기", "is_unclassified": True}
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
                   for r in booked) or "<tr><td colspan='3'>기록된 거래가 없습니다.</td></tr>"
    return ("<div class='body'>" + note +
            "<p class='hint'>새로 수집된 정상 거래는 자동으로 기록됩니다. 잘못 옮겨진 거래만 여행이나 항목을 바꾸세요.</p>"
            f"<h3>기록된 거래 {len(booked)}건 · {booked_total:,}원</h3><table><thead><tr><th>날짜</th><th>상호</th><th>금액</th></tr></thead>"
            f"<tbody>{done}</tbody></table>"
            f"<h3>기록 전 기존 거래 {len(pending)}건 · {pending_total:,}원</h3>"
            "<p class='hint'>자동 기록 시작 이전에 분류된 거래입니다. 확정 단계는 없고, 새로 수집되는 거래는 분류되는 즉시 기록됩니다.</p>"
            f"<table><thead><tr><th>날짜</th><th>상호</th><th>금액</th></tr></thead><tbody>{waiting}</tbody></table></div>")


def _is_trip_tab(tab_id: str) -> bool:
    """True only for actual trip tabs. False for unclassified, refunds, and quarter tabs."""
    if not tab_id or tab_id in ("unclassified", "refunds"):
        return False
    from app import quarter_tab
    if quarter_tab.parse_tab(tab_id):
        return False
    return _selected_trip(tab_id) is not None


def tsv_for_trip_expenses(tab_id: str, query: str = "", kind: str = "") -> dict:
    """Builds Google Sheets 7-column TSV (B:H) for the trip's expenses."""
    if not _is_trip_tab(tab_id):
        raise ValueError("INVALID_TRIP_TAB")
    _, expenses, _, _ = _selected_rows(tab_id, query, kind)
    return _trip_expense_tsv(tab_id, expenses)


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


def _trip_copy_html(tab_id: str, expenses: list) -> str:
    """Renders the expense copy controls at the bottom of the trip tab only."""
    if not _is_trip_tab(tab_id):
        return ""
    result = _trip_expense_tsv(tab_id, expenses)
    count, total = result["row_count"], result["total_krw"]
    held = f" · 확인 필요 {len(result['held'])}건 제외" if result["held"] else ""
    return (
        f"<section class='trip-copy-wrap' aria-label='지출내용 복사'>"
        f"<div class='trip-copy-box'>"
        f"<button type='button' class='btn btn-copy-tsv' id='copy-trip-expenses' data-tab='{board.esc(tab_id)}'>"
        f"{ui_icons.icon('copy', 16)}<span>지출내용 복사</span>"
        f"</button>"
        f"<span class='trip-copy-desc'>현재 표시된 지출을 Google 7열(B:H)로 복사합니다 ({count}건 · {_money(total)}{held})</span>"
        f"<span class='copy-status' id='copy-status' role='status' aria-live='polite'></span>"
        f"</div>"
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
        return shell(title, tab_id=tab_id, heading=title, query=query,
                     body=_quarter_body(tab_id, message, error))
    if tab_id == 'refunds':
        from .refund_tab import render as refund_body
        return shell('환불', tab_id='refunds', heading='환불', query=query,
                     body=_bar_html(query, kind, 'refunds', archived) +
                     "<div id='live-sum'></div><div id='live-rows'>" +
                     refund_body(board._active_store(), query, kind) + '</div>')
    trip = _selected_trip(tab_id)
    from .google_ledger_page import trip_income_html
    incomes, expenses, whole_income, whole_expense = _selected_rows(tab_id, query, kind)
    unclassified = tab_id == "unclassified"
    status = ""
    if error:
        status = f"<p class='status err' id='status' role='alert'>{board.esc(error)}</p>"
    elif message:
        status = (f"<p class='status' id='status' role='status'>"
                  f"{board.esc(message)}</p>")
    else:
        status = ("<p class='status hint' id='status' role='status' aria-live='polite'></p>")
    back = back or ("/board?" + state_query(tab_id, query, kind, archived))
    participant_state = None
    from . import participant_trip_panel as participant_panel
    participant_controls = (participant_panel.controls_from_query(participant_query or {})
                            if board.current_role() == "owner" else {})
    google_income_html = trip_income_html(
        tab_id, income_offset=participant_controls.get("income_offset", 0),
        participant_search=participant_controls.get("search", ""))
    from .trip_flight_ui import render_trip_flights
    flight_html = render_trip_flights(tab_id) if _is_trip_tab(tab_id) else ""
    panel = ""
    if selected:
        panel = panel_part(selected, back=back, error=error, message=message,
                           draft=draft or {})
    main = (
        f"<main class='main' id='main' tabindex='-1' data-base='{board.esc(back)}'><div class='main-wrap'>"
        f"{_head_html(trip)}"
        f"{_bar_html(query, kind, tab_id, archived)}{status}"
        # APP_SPEC 4.1: the same global state line the shared shell carries.
        f"<p class='meta' id='global-state' data-role='"
        f"{board.esc('읽기 전용' if board.current_role() == 'viewer' else '')}'>"
        "<span id='unsaved-count'>저장되지 않은 변경 없음</span>"
        f"<span>{ui_icons.icon('save')}최근 저장 {_last_saved_at(tab_id)}</span></p>"
        # APP_SPEC 4.1: ledger-note removed per review
        # The live refresh replaces the totals and the two row lists as one block,
        # and the edit panel sits outside it so an open panel is never rewritten.
        f"<div id='live-sum'>"
        f"{summary_part(tab_id, kind, query)}"
        f"</div>"
        f"<section id='trip-income' aria-label='여행 수입 · COST 기록'>"
        f"{google_income_html}"
        f"</section>"
        f"{_participant_trip_panel(tab_id, participant_controls)}"
        f"{_source_preview_html(trip)}"
        f"{rows_region(tab_id, query, kind, selected, archived, back)}"
        f"{flight_html}"
        "<p class='meta' id='live-status-wrap' aria-live='polite'>"
        "<span class='meta live-ok' id='live-status' hidden></span></p>"
        "</div></main>")
    return (f"<div class='app'>"
            f"{_nav_html(tab_id, query, kind, archived)}{main}"
            f"<div id='panel-slot'>{panel}</div></div>")


def _participant_trip_panel(tab_id: str, controls: dict) -> str:
    """Owner-only projection. Viewer HTML never receives participant names."""
    if board.current_role() != "owner" or not _selected_trip(tab_id):
        return ""
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
                       error=error, message=message, back=back, draft=draft or {})


def summary_part(tab_id: str, kind: str = "", query: str = "") -> str:
    if tab_id == 'refunds':
        return ''
    if _STORE_missing():
        return ""
    _, _, whole_income, whole_expense = _selected_rows(tab_id, '', kind)
    recorded_income_count = len(whole_income)
    if kind == "in":
        whole_expense = []
    elif kind == "ex":
        whole_income = []

    def totals(rows_in, rows_ex):
        return (sum(board._shown_amount(r) for r in rows_in),
                sum(board._shown_amount(r) for r in rows_ex),
                len(rows_in), len(rows_ex))

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
        filtered=totals(shown_in, shown_ex),
        whole=totals(whole_income, whole_expense),
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
    matches = _google_match_annotations(tab_id, expenses)
    return (f"<div id='live-rows'>"
            f"{_tables_html(incomes, expenses, selected=selected, unclassified=unclassified,
                            move_back=back, match_annotations=matches)}"
            f"{_mobile_html(incomes, expenses, selected=selected, unclassified=unclassified,
                            move_back=back, match_annotations=matches)}"
            f"{_trip_copy_html(tab_id, expenses)}"
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
    matches = _google_match_annotations(tab_id, expenses)
    return (f"{_tables_html(incomes, expenses, selected=selected, unclassified=unclassified,
                            move_back=back, match_annotations=matches)}"
            f"{_mobile_html(incomes, expenses, selected=selected, unclassified=unclassified,
                            move_back=back, match_annotations=matches)}"
            f"{_trip_copy_html(tab_id, expenses)}")


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


def _totals_kw(query, shown_in, shown_ex, whole_in, whole_ex) -> dict:
    """The summary's keyword arguments, split only when a filter is on."""
    if not query:
        return {}

    def totals(rows_in, rows_ex):
        return (sum(board._shown_amount(r) for r in rows_in),
                sum(board._shown_amount(r) for r in rows_ex),
                len(rows_in), len(rows_ex))

    return {"filtered": totals(shown_in, shown_ex),
            "whole": totals(whole_in, whole_ex)}


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
