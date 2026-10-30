import copy

from playwright.sync_api import sync_playwright

from webapp.insurance_income_match_page import render_page
from webapp.tests.test_insurance_income_match_page import state


def test_candidate_selection_stays_in_its_row_and_narrow_page_does_not_overflow():
    payload = state()
    row = copy.deepcopy(payload['contracts'][0]['rows'][0])
    row['review_row_id'] = 'review-2'
    payload['contracts'][0]['rows'].append(row)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.set_content(render_page(payload))
            rows = page.locator('tbody tr')
            rows.nth(0).locator('select').select_option('1')
            assert rows.nth(0).locator("[data-candidate='1']").is_visible()
            assert rows.nth(0).locator("[data-candidate='0']").is_hidden()
            assert rows.nth(1).locator("[data-candidate='0']").is_visible()
            assert rows.nth(1).locator("[data-candidate='1']").is_hidden()
            for width in (320, 390, 760, 1280):
                page.set_viewport_size({'width': width, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()
