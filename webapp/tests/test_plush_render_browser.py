"""Browser acceptance for the opt-in React UI on a synthetic preview.

jsdom unit tests cannot compute layout (truncation, computed font, Tab order,
Esc). These drive a real Chromium against the product server serving the built
React shell at its established URLs (WEBLEDGER_PRIMARY_UI=1), with a synthetic
owner session and fully synthetic seed rows. No operation port, no customer
data: the server binds port 0 and the store is a disposable temp database.
"""
import threading

import pytest

from webapp import access_control, ledger_board


OWNER = "synthetic-render-owner"


@pytest.fixture
def render_ui(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBLEDGER_DB", str(tmp_path / "render.sqlite"))
    monkeypatch.setenv("WEBLEDGER_PRIMARY_UI", "1")
    previous_store, previous_access = ledger_board._STORE, ledger_board._ACCESS
    previous_adapter = access_control.session_adapter()
    server = ledger_board.serve(port=0, with_worker=False, seed_demo=False)
    store = server.card_store
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner(OWNER)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    trip = store.create_trip(
        starts_on="2026-11-10", ends_on="2026-11-20",
        destination="합성 렌더 여행", client_request_id="render-trip-0")["tab_id"]
    for index, (amount, text) in enumerate([
        (12000, "합성 렌더 지출"),
        (-1200, "합성 렌더 환불"),
        (9007199254740993, "합성 렌더 정밀 금액"),
    ]):
        store.create_manual_expense(
            fields={"display_tab_id": trip, "occurred_on": "2026-11-12",
                    "amount_krw": amount, "item": "식비", "pay_method": "현금",
                    "description": text}, client_request_id=f"render-row-{index:04d}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], trip
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        ledger_board.bind_access(previous_access)
        access_control.bind_sessions(previous_adapter)
        ledger_board.bind_store(previous_store)
        store.close()


@pytest.fixture
def render_browser(render_ui):
    from playwright.sync_api import sync_playwright

    port, trip = render_ui
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    contexts = []

    def make_page(width, height=900):
        context = browser.new_context(
            extra_http_headers={access_control.SyntheticSessionAdapter.HEADER: OWNER},
            viewport={"width": width, "height": height})
        page = context.new_page()
        page.on("dialog", lambda d: d.accept() if d.type == "beforeunload" else None)
        contexts.append(context)
        return page

    def open_ledger(page, query=""):
        page.goto(f"http://127.0.0.1:{port}/board?tab={trip}{query}")
        page.wait_for_selector(".cost-app-shell[data-role='owner']")

    try:
        yield port, trip, make_page, open_ledger
    finally:
        for context in contexts:
            context.close()
        browser.close()
        playwright.stop()


class _Cleanups:
    """unittest addCleanup sink so install_canonical_source runs under a pytest fixture."""

    def __init__(self):
        self._stack = []

    def addCleanup(self, fn, *args, **kwargs):
        self._stack.append((fn, args, kwargs))

    def run(self):
        while self._stack:
            fn, args, kwargs = self._stack.pop()
            fn(*args, **kwargs)


@pytest.fixture
def render_copy_browser(render_browser):
    # 사본 복구(#2)는 검증된 Google 원장과 대조해 NEW_EXPENSE 행만 내보낸다. 소스가 없으면
    # 서버가 빈 TSV를 돌려주므로, 합성 canonical 소스를 설치해 실제 복구 경로를 검증한다.
    from webapp.tests.test_trip_expense_copy_button import install_canonical_source

    port, trip, make_page, open_ledger = render_browser
    cleanups = _Cleanups()
    install_canonical_source(cleanups, trip)
    try:
        yield port, trip, make_page, open_ledger
    finally:
        cleanups.run()


# 수락 #3 확인 방법: "scrollWidth > clientWidth인 셀마다 전체 값 접근 수단이 있는지 시험한다."
# 페이지 수준 overflow가 아니라 실제 데이터 셀을 순회한다. 잘린(넘치는) 셀은 줄바꿈·펼침·title 중
# 하나의 전체값 접근 수단이 있어야 한다. display:none 조상(폭별 데스크톱 표↔모바일 목록 전환)은
# rect가 0이라 자동으로 건너뛴다.
_CELL_ACCESS_JS = """() => {
  const selector = '.cost-data-table td, .cost-ledger__row-open strong, .cost-ledger__row-open span, '
    + '.cost-ledger__mobile-row > strong, .cost-ledger__mobile-bottom > span, .cost-ledger__mobile-amount';
  const violations = [];
  let checked = 0;
  for (const cell of document.querySelectorAll(selector)) {
    const rect = cell.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    const style = getComputedStyle(cell);
    if (style.visibility === 'hidden') continue;
    checked += 1;
    if (cell.scrollWidth <= cell.clientWidth) continue;
    const titled = cell.getAttribute('title') || cell.querySelector('[title]');
    const wraps = style.overflowWrap === 'anywhere' || style.overflowWrap === 'break-word'
      || style.wordBreak === 'break-all' || style.wordBreak === 'break-word';
    const expand = cell.querySelector('details, [aria-expanded]');
    if (!titled && !wraps && !expand) {
      violations.push({ text: (cell.textContent || '').trim().slice(0, 40), scrollWidth: cell.scrollWidth, clientWidth: cell.clientWidth });
    }
  }
  return { checked, violations };
}"""


def _cell_access(page):
    return page.evaluate(_CELL_ACCESS_JS)


def test_react_shell_boots_with_synthetic_seed(render_browser):
    port, trip, make_page, open_ledger = render_browser
    page = make_page(1440)
    open_ledger(page)
    assert page.locator(".cost-brand").count() == 1
    assert page.locator(".cost-skip-link").get_attribute("href") == "#cost-main"
    assert page.locator("#cost-main").count() == 1
    assert page.locator(".cost-ledger__row-open, .cost-ledger__mobile-row").count() >= 1
    page.close()


def test_no_horizontal_overflow_at_mobile_widths(render_browser):
    port, trip, make_page, open_ledger = render_browser
    for width in (320, 390, 640, 720):
        page = make_page(width)
        open_ledger(page)
        page.wait_for_selector(".cost-ledger__summary")
        assert page.locator(".cost-ledger__row-open, .cost-ledger__mobile-row").count() >= 1
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 0, f"width {width}: horizontal overflow {overflow}px"
        page.close()


def test_single_pretendard_font_is_loaded(render_browser):
    port, trip, make_page, open_ledger = render_browser
    page = make_page(1440)
    open_ledger(page)
    page.wait_for_selector(".cost-ledger__row-open, .cost-ledger__mobile-row")
    page.evaluate("document.fonts.ready")
    family = page.evaluate("getComputedStyle(document.body).fontFamily")
    assert "Pretendard" in family
    assert page.evaluate("document.fonts.check('14px \"Pretendard Variable\"')")
    page.close()


def test_skip_link_is_first_focus_and_moves_to_main(render_browser):
    port, trip, make_page, open_ledger = render_browser
    page = make_page(1440)
    open_ledger(page)
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.className") == "cost-skip-link"
    page.keyboard.press("Enter")
    page.wait_for_function("document.activeElement.id === 'cost-main'")
    page.close()


def test_row_drawer_closes_on_escape(render_browser):
    port, trip, make_page, open_ledger = render_browser
    page = make_page(1440)
    open_ledger(page)
    page.wait_for_selector(".cost-ledger__row-open")
    page.locator(".cost-ledger__row-open").first.click()
    page.wait_for_selector("dialog[open]")
    page.keyboard.press("Escape")
    page.wait_for_function("!document.querySelector('dialog[open]')")
    page.close()


def test_owner_primary_action_is_single(render_browser):
    port, trip, make_page, open_ledger = render_browser
    page = make_page(1440)
    open_ledger(page)
    page.wait_for_selector(".cost-ledger__toolbar")
    primary = page.locator('.cost-ledger__toolbar button.cost-action-button[data-variant="default"]')
    assert primary.count() == 1
    assert "수기 지출 추가" in primary.first.text_content()
    page.close()


def test_copy_guidance_offers_server_tsv_fallback(render_copy_browser):
    port, trip, make_page, open_ledger = render_copy_browser
    page = make_page(1440)
    open_ledger(page)
    page.wait_for_selector(".cost-ledger__toolbar")
    # clipboard 거부는 실제 흔한 경로다 — 대체 복구 수단(서버 산출 textarea)을 검증한다.
    page.evaluate("() => { navigator.clipboard.writeText = () => Promise.reject(new Error('denied')); }")
    page.get_by_role("button", name="Google 장부용 복사").click()
    page.wait_for_selector("#cost-copy-text")
    notice = page.locator(".cost-ledger__copy-fallback")
    assert notice.locator("label").inner_text() == "서버가 만든 붙여넣기 내용"
    value = page.input_value("#cost-copy-text")
    assert value.strip() != ""
    assert "합성 렌더 지출" in value
    page.close()


def test_input_height_matches_field_token(render_browser):
    port, trip, make_page, open_ledger = render_browser
    page = make_page(1440)
    open_ledger(page)
    page.wait_for_selector("#cost-ledger-search")
    height = page.evaluate("parseFloat(getComputedStyle(document.getElementById('cost-ledger-search')).height)")
    assert height == 48
    page.close()


def test_mobile_input_font_size_at_least_16(render_browser):
    port, trip, make_page, open_ledger = render_browser
    page = make_page(390)
    open_ledger(page)
    page.wait_for_selector("#cost-ledger-search")
    size = page.evaluate("parseFloat(getComputedStyle(document.getElementById('cost-ledger-search')).fontSize)")
    assert size >= 16
    page.close()


def test_amount_input_is_numeric_inputmode(render_browser):
    port, trip, make_page, open_ledger = render_browser
    page = make_page(1440)
    open_ledger(page)
    page.wait_for_selector(".cost-ledger__toolbar")
    page.get_by_role("button", name="수기 지출 추가").click()
    page.wait_for_selector("#entry-amount")
    assert page.get_attribute("#entry-amount", "inputmode") == "numeric"
    assert page.locator("label[for='entry-amount']").inner_text().startswith("금액")
    page.close()


def test_missing_route_shows_not_found_heading(render_browser):
    port, trip, make_page, open_ledger = render_browser
    page = make_page(1440)
    # 임의 경로는 레거시로 떨어지므로, React가 항상 부팅하는 /ui/ 아래 미등록 경로로 검증한다.
    page.goto(f"http://127.0.0.1:{port}/ui/no-such-route")
    page.wait_for_selector(".cost-app-shell")
    assert page.get_by_role("heading", name="화면을 찾을 수 없습니다").count() == 1
    page.close()


def test_ota_page_uses_pagination_not_expand(render_browser):
    port, trip, make_page, open_ledger = render_browser
    page = make_page(1440)
    page.goto(f"http://127.0.0.1:{port}/ota")
    page.wait_for_selector(".cost-app-shell")
    page.wait_for_selector(".e-feature-pagination")
    assert page.locator(".e-feature-pagination nav[aria-label='페이지 이동']").count() == 1
    assert page.locator("form[role='search'], .e-feature-search").count() >= 1
    page.close()


def test_ledger_data_cells_offer_full_value_access(render_browser):
    # 수락 #3: 셀별 잘림·전체값 접근 수단을 모바일 목록(≤767px)과 데스크톱 표(>767px) 모두 검사한다.
    port, trip, make_page, open_ledger = render_browser
    for width in (320, 390, 640, 720, 1440):
        page = make_page(width)
        open_ledger(page)
        page.wait_for_selector(".cost-ledger__summary")
        # 폭별로 실제 보이는 목록을 기다린다(≤767px은 모바일 목록, 초과은 데스크톱 표).
        row_selector = ".cost-ledger__mobile-row" if width <= 767 else ".cost-ledger__desktop-table .cost-ledger__row-open"
        page.wait_for_selector(row_selector)
        report = _cell_access(page)
        assert report["checked"] > 0, f"width {width}: 검사한 데이터 셀이 없음"
        assert report["violations"] == [], f"width {width}: 잘린 셀에 전체값 접근 수단 없음 {report['violations']}"
        if width <= 767:
            assert page.locator(".cost-ledger__mobile-list").is_visible()
            assert not page.locator(".cost-ledger__desktop-table").is_visible()
        else:
            assert page.locator(".cost-ledger__desktop-table").is_visible()
            assert page.locator(".cost-ledger__desktop-table td").count() >= 1
        page.close()


def test_trips_data_cells_offer_full_value_access(render_browser):
    # 수락 #3의 여행 목록(640~720px 포함)도 셀별로 검사한다.
    port, trip, make_page, open_ledger = render_browser
    for width in (320, 390, 640, 720, 1440):
        page = make_page(width)
        page.goto(f"http://127.0.0.1:{port}/ui/trips?state=all")
        page.wait_for_selector(".cost-app-shell")
        page.wait_for_selector(".cost-trips__table td")
        report = _cell_access(page)
        assert report["checked"] > 0, f"width {width}: 검사한 여행 셀이 없음"
        assert report["violations"] == [], f"width {width}: 잘린 여행 셀에 전체값 접근 수단 없음 {report['violations']}"
        page.close()


def test_each_screen_has_unique_page_title(render_browser):
    # 수락 #6: 화면마다 고유한 페이지 <title>. document.title이 화면 h1을 따라 서로 다른지 실측한다.
    port, trip, make_page, open_ledger = render_browser
    page = make_page(1440)
    titles = {}

    page.goto(f"http://127.0.0.1:{port}/ui/")
    page.wait_for_selector(".cost-home h1")
    page.wait_for_function("document.title.includes('정산 현황')")
    titles["home"] = page.title()

    page.goto(f"http://127.0.0.1:{port}/ui/trips?state=all")
    page.wait_for_selector(".cost-trips h1")
    page.wait_for_function("document.title.includes('여행')")
    titles["trips"] = page.title()

    page.goto(f"http://127.0.0.1:{port}/ui/board?tab={trip}")
    page.wait_for_selector(".cost-ledger__title-row h1")
    page.wait_for_function("document.title.includes('합성 렌더 여행')")
    titles["ledger"] = page.title()

    page.goto(f"http://127.0.0.1:{port}/ui/no-such-route")
    page.wait_for_selector(".cost-app-shell h1")
    page.wait_for_function("document.title.includes('화면을 찾을 수 없습니다')")
    titles["missing"] = page.title()

    assert len(set(titles.values())) == len(titles), f"화면별 제목이 고유하지 않음: {titles}"
    assert "정산 현황" in titles["home"]
    assert "여행" in titles["trips"]
    assert "합성 렌더 여행" in titles["ledger"]
    assert "화면을 찾을 수 없습니다" in titles["missing"]
    page.close()
