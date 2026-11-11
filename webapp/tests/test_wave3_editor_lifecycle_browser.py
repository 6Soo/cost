"""Synthetic browser checks for the drawer's existing edit protections."""
import pytest

from webapp.tests import test_ledger_design as _screens


@pytest.fixture
def screen():
    case = _screens.DesignScreenTests(methodName='runTest')
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()
        case.doCleanups()


@pytest.mark.parametrize('width', [390, 1440])
def test_expense_grouping_changes_visible_rows_and_restores_date_order(screen, width):
    status, result = screen._api('/api/rows/expense-demo-c4/save', {
        'csrf': _screens.board_mod.CSRF_TOKEN,
        'expected_revision': screen.store.get_row('expense-demo-c4')['revision'],
        'client_request_id': f'grouping-{width}', 'change_mode': 'exception', 'item': '식비',
    }, method='POST')
    assert status == 200, result
    page = screen._page(width)
    screen._board(page, '?tab=trip-demo-a')
    scope = '.lst' if width == 390 else '#tbl tbody.expense-rows[data-kind=expense]'
    row_selector = ':scope > li[data-kind=expense]' if width == 390 else ':scope > tr[data-id]'
    head_selector = '.expense-category-group' if width == 390 else '.group-row'
    rows = page.locator(scope).locator(row_selector)
    original = rows.evaluate_all('(rows)=>rows.map(r=>({id:r.dataset.id,category:r.dataset.category,amount:Number(r.dataset.amount)}))')
    expected = {}
    for row in original:
        expected.setdefault(row['category'], []).append(row)
    assert original and len(expected) > 1
    page.locator('[data-group-expenses]').check()
    heads = page.locator(scope).locator(head_selector)
    assert heads.count() == len(expected)
    for index, (category, items) in enumerate(expected.items()):
        assert f'{category} · {len(items)}건' in heads.nth(index).inner_text()
        assert f"{sum(item['amount'] for item in items):,}원" in heads.nth(index).inner_text()
    grouped_ids = [row['id'] for items in expected.values() for row in items]
    assert rows.evaluate_all('(rows)=>rows.map(r=>r.dataset.id)') == grouped_ids
    page.reload()
    assert page.locator('[data-group-expenses]').is_checked()
    assert page.locator(scope).locator(head_selector).count() == len(expected)
    page.locator('[data-group-expenses]').uncheck()
    assert page.locator(scope).locator(head_selector).count() == 0
    assert page.locator(scope).locator(row_selector).evaluate_all('(rows)=>rows.map(r=>r.dataset.id)') == [row['id'] for row in original]
    assert page.locator('#global-state').get_attribute('data-role') == ''
    assert page.locator('#global-state #unsaved-count').count() == 1
    assert page.locator('#live-status-wrap #live-status').count() == 1
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_another_row_cannot_discard_a_dismissed_unsaved_draft(screen):
    page = screen._page(1440)
    screen._open_panel(page, 'expense-demo-c1')
    before = screen.store.get_row('expense-demo-c1')
    page.fill('#f-description', 'Synthetic unsaved draft')
    asked = []
    page.on('dialog', lambda dialog: (asked.append(dialog.message), dialog.dismiss()))
    # Exercise the delegated row-click path while the current editor is open.
    page.locator('.tw tr[data-id="expense-demo-c4"]').evaluate('row => row.click()')
    assert len(asked) == 1
    assert page.locator('#panel').get_attribute('data-row') == 'expense-demo-c1'
    assert page.input_value('#f-description') == 'Synthetic unsaved draft'
    assert screen.store.get_row('expense-demo-c1') == before


@pytest.mark.parametrize('action', ['close', 'escape', 'next', 'bulk', 'another-row'])
def test_saving_blocks_every_drawer_exit_without_mutating_the_source(screen, action):
    page = screen._page(1440)
    screen._open_panel(page, 'expense-demo-c1')
    before = screen.store.get_row('expense-demo-c1')
    pending = []
    page.route('**/api/rows/expense-demo-c1/save', lambda route: pending.append(route))
    page.click('#panel button[type=submit]')
    page.wait_for_selector('#panel form[data-saving="1"]')
    try:
        if action == 'close':
            page.click('#drawer-close')
        elif action == 'escape':
            page.keyboard.press('Escape')
        elif action == 'next':
            page.click('#p-next')
        elif action == 'bulk':
            page.click('#bulk-start')
        else:
            page.locator('.tw tr[data-id="expense-demo-c4"]').evaluate('row => row.click()')
        assert page.locator('#ledger-drawer').evaluate('dialog => dialog.open')
        assert page.locator('#ledger-drawer #panel').get_attribute('data-row') == 'expense-demo-c1'
        assert page.locator('#panel form').get_attribute('data-saving') == '1'
        assert page.locator('.bulk-bar').count() == 0
        assert screen.store.get_row('expense-demo-c1') == before
    finally:
        for route in pending:
            route.abort()


def test_two_fast_row_clicks_cannot_race_panel_responses(screen):
    page = screen._page(1440)
    screen._board(page, '?tab=trip-demo-a')
    pending = []
    requested = []
    def panel_route(route):
        from urllib.parse import parse_qs, urlsplit
        if route.request.headers.get('x-part') != 'panel':
            route.continue_()
            return
        requested.append(parse_qs(urlsplit(route.request.url).query)['row'][0])
        pending.append(route)
    page.route('**/board?*', panel_route)
    page.locator('.tw tr[data-id="expense-demo-c1"]').click()
    page.wait_for_selector('#panel-slot[aria-busy=true]', state='attached')
    page.locator('.tw tr[data-id="expense-demo-c4"]').click()
    try:
        assert requested == ['expense-demo-c1']
        first = pending.pop(0)
        first.fulfill(response=first.fetch())
        page.wait_for_selector('#ledger-drawer #panel[data-row="expense-demo-c1"]')
        page.locator('#panel .p-extra > summary').click()
        page.fill('#f-description', 'Synthetic draft after first response')
        assert page.input_value('#f-description') == 'Synthetic draft after first response'
        assert requested == ['expense-demo-c1']
    finally:
        for route in pending:
            route.abort()


def test_next_and_previous_keep_the_editor_inside_the_native_drawer(screen):
    page = screen._page(1440)
    screen._open_panel(page, 'expense-demo-c1')
    page.click('#p-next')
    page.wait_for_selector('#ledger-drawer #panel:not([data-row="expense-demo-c1"])')
    assert page.locator('#ledger-drawer').evaluate('dialog => dialog.open')
    assert page.locator('.inline-editor-row,.inline-editor-mobile').count() == 0
    page.click('#p-prev')
    page.wait_for_selector('#ledger-drawer #panel[data-row="expense-demo-c1"]')


def test_bulk_edit_closes_the_drawer_and_exposes_interactive_controls(screen):
    page = screen._page(1440)
    screen._open_panel(page, 'expense-demo-c1')
    page.click('#bulk-start')
    page.wait_for_selector('.bulk-bar')
    assert not page.locator('#ledger-drawer').evaluate('dialog => dialog.open')
    assert page.locator('#bulk-trip').evaluate('element => document.activeElement === element')
    assert page.locator('#ledger-drawer #panel-slot').count() == 1
    page.click('[data-bulk-end]')
    assert page.locator('.bulk-bar').count() == 0

@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('width', [390, 1440])
def test_drawer_header_and_footer_stay_on_screen_and_close_by_real_click(screen, width, theme):
    page = screen._page(width)
    screen._board(page, '?tab=trip-demo-a')
    page.evaluate('(theme) => localStorage.setItem("cost-theme", theme)', theme)
    page.reload()
    page.wait_for_function('(theme) => document.documentElement.dataset.theme === theme', arg=theme)
    page.click('[role=tab][aria-controls="view-expense"]')
    selector = ('.lst .list-row' if width < 760 else '.tw tr') + '[data-id="expense-demo-c1"]'
    page.click(selector)
    page.wait_for_selector('#ledger-drawer[open] #panel[data-row="expense-demo-c1"]')
    page.evaluate('() => Promise.all(document.getAnimations().map(a => a.finished.catch(() => {})))')
    box = page.evaluate('''() => {
        const rect = s => { const r = document.querySelector(s).getBoundingClientRect();
            return {top: r.top, left: r.left, right: r.right, bottom: r.bottom}; };
        const close = document.querySelector('#drawer-close').getBoundingClientRect();
        const hit = document.elementFromPoint(close.left + close.width / 2, close.top + close.height / 2);
        return {title: rect('#ledger-drawer-title'), close: rect('#drawer-close'),
                count: rect('#panel .p-count'), drawer: rect('#ledger-drawer'),
                hitsClose: !!hit && !!hit.closest('#drawer-close')};
    }''')
    assert box['title']['top'] >= box['drawer']['top'] >= 0, box
    assert box['close']['top'] >= box['drawer']['top'] and box['close']['right'] <= width, box
    assert box['count']['right'] <= box['drawer']['right'] <= width, box
    assert box['count']['bottom'] <= 900, box
    assert box['hitsClose'], box
    page.click('#drawer-close')
    assert not page.locator('#ledger-drawer').evaluate('dialog => dialog.open')


@pytest.mark.parametrize('width', [390, 1440])
def test_bulk_row_clicks_and_shift_range_then_normal_edit(screen, width):
    page = screen._page(width)
    screen._board(page, '?tab=trip-demo-a')
    selector = '.lst .li[data-kind="expense"]' if width < 760 else '.tw tr[data-kind="expense"]'
    rows = page.locator(selector).filter(visible=True)
    assert rows.count() >= 3
    ids = [rows.nth(i).get_attribute('data-id') for i in range(3)]
    amounts = [int(rows.nth(i).get_attribute('data-amount')) for i in range(3)]
    rows.nth(0).click()
    page.wait_for_selector('#ledger-drawer #panel')
    page.click('#bulk-start')
    def check(selected):
        expected = sum(amounts[i] for i in selected)
        assert page.locator('[data-bulk-count]').inner_text() == f'선택 {len(selected)}건 · 합계 {expected:,}원'
        assert not page.locator('#ledger-drawer').evaluate('dialog => dialog.open')
        for i in range(3):
            assert (rows.nth(i).get_attribute('data-bulk-selected') == 'true') == (i in selected)
    check({0})
    rows.nth(1).click()
    check({0, 1})
    rows.nth(1).click()
    check({0})
    rows.nth(2).evaluate("row => row.scrollIntoView({block: 'center'})")
    assert rows.nth(2).evaluate("el => el.getBoundingClientRect().bottom") <= page.locator('.bulk-bar').evaluate("el => el.getBoundingClientRect().top")
    rows.nth(2).click(modifiers=['Shift'])
    check({0, 1, 2})
    page.click('[data-bulk-end]')
    rows.nth(1).click()
    page.wait_for_selector(f'#ledger-drawer #panel[data-row="{ids[1]}"]')
    page.locator('#panel .p-extra > summary').click()
    page.fill('#f-description', 'Synthetic bulk follow-up edit')
    page.click('#panel button[type=submit]')
    page.wait_for_function("document.querySelector('#panel form')?.getAttribute('data-saving') !== '1'")
    assert screen.store.get_row(ids[1])['description'] == 'Synthetic bulk follow-up edit'

@pytest.mark.parametrize('width', [320, 390])
def test_home_trip_identity_and_period_are_readable(screen, width):
    from webapp.card_flow import home_page
    from webapp.tests.test_card_flow import CardFlowTests
    case = CardFlowTests(methodName='runTest')
    case.setUp()
    screen.addCleanup(case.tearDown)
    case.board.create_trip(starts_on='2099-08-03', ends_on='2099-08-31',
                           destination='합성 여행 이름이 길어도 전부 읽혀야 합니다 1234567890',
                           client_request_id='synthetic-home-trip')
    page = screen._page(width)
    page.goto(f'http://127.0.0.1:{screen.port}/')
    page.set_content(home_page(case.board))
    row = page.locator('.home-trips tbody tr').first
    assert row.count() == 1
    name = row.locator('th a')
    period = row.locator('td').first
    for cell in (name.locator('..'), period):
        assert cell.evaluate("el => { const s=getComputedStyle(el); return s.textOverflow !== 'ellipsis' && s.whiteSpace !== 'nowrap' && el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight; }")
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

def test_sidebar_long_trip_label_and_period_do_not_overflow(screen):
    page = screen._page(1440)
    screen._board(page, '?tab=trip-demo-a')
    link = page.locator('#nav .nav-list .nv').first
    link.locator('.nm').evaluate("el => el.textContent = '합성 여행의 매우 긴 이름 1234567890ABCDEFGHIJKLMN'")
    link.evaluate("el => { if (!el.querySelector('.ct')) el.insertAdjacentHTML('beforeend', '<span class=ct></span>'); }")
    link.locator('.ct').evaluate("el => el.textContent = '08.03~08.31'")
    assert page.locator('#nav').evaluate('el => el.scrollWidth <= el.clientWidth')
    assert link.locator('.ct').inner_text() == '08.03~08.31'
