"""Coverage starts with missing periods; source files remain secondary."""
import json

import pytest
from playwright.sync_api import expect, sync_playwright

from webapp.tests.test_card_history_upload_feedback import _document
from webapp.tests.test_cards_all import card_db_path


def coverage_data():
    def file(index, issuer):
        return dict(batch_id='batch-' + f'{index:024x}', issuer_hint=issuer,
                    filename='synthetic-long-card-statement-' + str(index) + '.csv',
                    transaction_start='2026-01-01', transaction_end='2026-06-30',
                    source_rows=20, unique_transactions=20, status='classified',
                    coverage_status='transaction_dates')
    files = [file(i, 'SYNTH A' if i < 7 else 'SYNTH B') for i in range(1, 24)]
    for index, item in enumerate(files[6:]):
        item['transaction_start'] = '2026-01-01' if index % 2 else '2026-05-01'
        item['transaction_end'] = '2026-03-31' if index % 2 else '2026-06-30'
    return dict(available=True, coverage_state='transaction_dates', files=files,
                overview=dict(card_count=2, file_count=23, gap_count=1, files_need_review=0),
                cards=[dict(card_id='a', issuer='SYNTH A', date_basis='거래일자',
                            periods=[dict(start='2026-01-01', end='2026-06-30')],
                            gaps=[], files=files[:6]),
                       dict(card_id='b', issuer='SYNTH B', date_basis='거래일자',
                            periods=[dict(start='2026-01-01', end='2026-03-31'),
                                     dict(start='2026-05-01', end='2026-06-30')],
                            gaps=[dict(start='2026-04-01', end='2026-04-30')], files=files[6:])])


@pytest.mark.parametrize('width', [1440, 390])
def test_missing_period_precedes_files_and_keeps_upload_context(card_db_path, monkeypatch, width):
    document = _document(card_db_path, {'panel': ['coverage']}, monkeypatch)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.route('http://cost.test/cards/all*', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=document))
            page.route('http://cost.test/api/cards/coverage/summary', lambda route: route.fulfill(
                content_type='application/json', body=json.dumps(coverage_data())))
            page.goto('http://cost.test/cards/all?panel=coverage')
            cards = page.locator('.card-coverage-card')
            expect(cards.first).to_contain_text('SYNTH B')
            expect(cards.first).to_contain_text('2026-04-01')
            sources = page.locator('details.card-coverage-sources')
            expect(sources).not_to_have_attribute('open', '')
            expect(sources.locator('.card-coverage-file')).to_have_count(23)
            expect(sources.locator('.card-coverage-file').first).not_to_be_visible()
            assert page.locator('.card-coverage-metrics').count() == 0
            assert not page.locator('#card-coverage-summary').inner_text().count('합집합')
            # Expanding file details cannot move the period summary above them.
            first_top = cards.first.bounding_box()['y']
            sources.locator('summary').click()
            expect(sources.locator('.card-coverage-file').first).to_be_visible()
            assert cards.first.bounding_box()['y'] == pytest.approx(first_top)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            missing = cards.first.locator('.card-coverage-period.is-missing button')
            missing.focus()
            page.keyboard.press('Enter')
            expect(page.locator('#card-upload-panel')).to_be_visible()
            expect(page.locator('#card-gap-context')).to_contain_text('2026-04-01 ~ 2026-04-30')
            expect(page.locator('#card-upload-files')).to_be_focused()
        finally:
            browser.close()
