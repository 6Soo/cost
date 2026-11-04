"""Core tasks stay visible while secondary actions remain reachable."""
import json
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from webapp import card_flow, ledger_board, ledger_design, receipt_review, site_shell
from webapp.ledger_store import LedgerStore
from webapp.tests.test_receipt_design_contract import SYNTHETIC_CANDIDATE, SYNTHETIC_TRIPS


def test_trip_header_and_management_disclose_secondary_actions(tmp_path):
    store = LedgerStore(tmp_path / 'board.sqlite', seed_demo=True)
    try:
        with patch.object(ledger_board, '_STORE', store), patch.object(ledger_board, 'current_role', return_value='owner'):
            trips = site_shell.wrap_document(ledger_board.trips_page(role='owner'), '/trips')
            head = ledger_design._head_html(store.get_trip('trip-demo-a'))
            document = site_shell.wrap_document(ledger_design.render(
                "<div class='app'><aside id='nav'></aside><main class='main' id='main'>" + head + '</main></div>'), '/board')
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.set_content(document)
                assert page.get_by_role('link', name='XLSX 출력').is_visible()
                assert page.locator('.secondary-actions').count() == 0
                assert not page.locator('.act a[href="/import#newupload"]').is_visible()
                page.set_content(trips)
                row = page.locator('#manage-trip-demo-a')
                assert row.locator('h3 a').is_visible()
                assert not row.locator('.trip-close-form button').is_visible()
                row.locator('.trip-meta > summary').click()
                assert row.locator('.trip-close-form button').is_visible()
                assert row.locator('.trip-close-form input[name=visual_closed]').input_value() == '1'
                page.route('https://ui.test/**', lambda route: route.fulfill(content_type='text/html', body=trips))
                page.goto('https://ui.test/trips?closed=1')
                assert page.locator('.trip-filter-tools').get_attribute('open') is not None
                assert page.locator('#trip-management-closed').input_value() == '1'
            finally:
                browser.close()
    finally:
        store.close()


def test_expense_management_deep_links_and_keyboard_preserve_input():
    document = card_flow.page('synthetic')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route('https://ui.test/**', lambda route: route.fulfill(
                content_type='application/json' if '/api/' in route.request.url else 'text/html',
                body=json.dumps({'batches': [], 'rules': []}) if '/api/' in route.request.url else document))
            page.goto('https://ui.test/import')
            assert page.locator('#expense-tab-upload').is_visible()
            assert not page.locator('#expense-tab-rules').is_visible()
            page.locator('.expense-tools > summary').focus()
            page.keyboard.press('Enter')
            page.locator('#expense-tab-rules').click()
            page.locator('#rule-text').fill('합성 입력 보존')
            page.locator('#expense-tab-cleanup').click()
            page.locator('#expense-tab-rules').click()
            assert page.locator('#rule-text').input_value() == '합성 입력 보존'
            page.goto('https://ui.test/import#rules')
            assert page.locator('#expense-tab-rules').is_visible()
            assert page.locator('#expense-tab-rules').get_attribute('aria-selected') == 'true'
            page.goto('https://ui.test/import#newupload')
            assert page.locator('#file').is_visible()
        finally:
            browser.close()


def test_receipt_empty_stages_disappear_without_hiding_copy_selection():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.set_content(receipt_review.render_html(
                {'candidates': [], 'holds': [], 'images': []}, csrf='synthetic', trips=SYNTHETIC_TRIPS))
            assert not page.locator('#step-review').is_visible()
            assert not page.locator('#step-copy').is_visible()
            assert page.locator('#receipt-holds').count() == 0
            assert not page.locator('#pdf-file').is_visible()
            page.locator('#receipt-pdf > summary').click()
            assert page.locator('#pdf-file').is_visible()
            assert page.locator('#pdf-go').is_disabled()
            page.locator('#receipt-manual-open').click()
            assert page.locator('#r-merchant').is_visible()
            page.set_content(receipt_review.render_html(
                {'candidates': [SYNTHETIC_CANDIDATE], 'holds': [], 'images': []}, csrf='synthetic', trips=SYNTHETIC_TRIPS))
            assert page.locator('#step-review').is_visible()
            assert page.locator('#copy-trip').is_visible()
            page.locator('#copy-trip').select_option('trip-syn')
            assert page.locator('#copy-tsv').is_enabled()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()
