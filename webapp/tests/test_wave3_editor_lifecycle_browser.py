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
