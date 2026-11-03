"""Additional synthetic acceptance: expanded long content and member-error recovery.

CSS zoom and viewport emulation only; these tests do not claim physical-device QA.
"""
from urllib.parse import parse_qs, urlsplit
from datetime import datetime, timezone

import pytest
from playwright.sync_api import expect, sync_playwright

from webapp import ota_payment_review, site_shell

LONG_REF = 'SYNTHETIC-BOOKING-20261028-' + 'LONG-REFERENCE-' * 8
LONG_MERCHANT = '합성 숙소 카드 가맹점 ' * 12
EVENT = {'ota_event_id': 'synthetic-long', 'provider': 'agoda', 'booking_ref': LONG_REF,
         'event_type': 'charge', 'paid_on': '2026-10-28', 'item': '합성 숙박 객실 ' * 8,
         'amount': 1250000, 'currency': 'KRW', 'status': 'HOLD_AMBIGUOUS'}


def document():
    html = ("<!doctype html><html><head><meta charset='utf-8'><base href='http://localhost/'>"
            '</head><body>' + ota_payment_review.render_import_section('synthetic-csrf') + '</body></html>')
    return site_shell.wrap_document(html, '/import')


def summary(generation=1):
    return {'status': 'ready', 'fresh': True, 'stale': False, 'refreshing': False,
            'generation': generation, 'counts_authoritative': True, 'counts_by_queue': {
                'needs_action': {'event_count': 1, 'group_count': 1}}}


def row(group_id=None):
    return {'queue': 'needs_action', 'reason_codes': [], 'event': {
        **EVENT, 'group_id': group_id, 'group_total_count': 1,
        'group_members': [{**EVENT, 'detail_available': True}]}}


def test_expanded_long_detail_and_cards_reflow_in_each_theme_viewport_and_zoom():
    requests = []

    def route(request):
        path = urlsplit(request.request.url).path
        requests.append((path, request.request.method))
        if path.endswith('/summary'):
            body = summary()
        elif path.endswith('/groups'):
            body = {'generation': 1, 'items': [row()], 'next_cursor': None}
        elif '/events/' in path:
            body = {'generation': 1, 'event': {**EVENT, 'card_candidate_count': 1}}
        elif '/cards/' in path:
            body = {'cards': [{'transaction_id': 'synthetic-card', 'merchant': LONG_MERCHANT,
                              'issuer': '합성카드', 'amount_krw': 1250000,
                              'approval_date': '2026-10-28', 'selection_disabled': False}]}
        else:
            request.fulfill(status=404, json={'code': 'NOT_FOUND'})
            return
        request.fulfill(json=body)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.set_default_timeout(4000)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/imports/ota/**', route)
            page.set_content(document())
            theme = page.locator('#site-theme-toggle')
            theme.focus()
            page.keyboard.press('Tab')
            page.keyboard.press('Shift+Tab')
            assert theme.evaluate('e => e === document.activeElement')
            assert theme.evaluate('e => getComputedStyle(e).outlineStyle') != 'none'
            page.locator('#ota-review > summary').click()
            page.locator('[data-queue-detail] > summary').click()
            page.locator('[data-load-detail]').click()
            event = page.locator('[data-event="synthetic-long"]')
            expect(event).to_contain_text(LONG_REF)
            assert not any('/cards/' in path for path, _ in requests)
            event.locator('h4[role=button]').click()
            card = event.locator('.ota-card-row')
            expect(card).to_contain_text(LONG_MERCHANT.strip())
            radio = card.locator('input[type=radio]')
            radio.focus()
            page.keyboard.press('Space')
            expect(radio).to_be_checked()
            assert radio.evaluate('e => e === document.activeElement')
            for width in (375, 1280):
                page.set_viewport_size({'width': width, 'height': 900})
                for color in ('light', 'dark'):
                    if page.locator('html').get_attribute('data-theme') != color:
                        theme.click()
                    expect(page.locator('html')).to_have_attribute('data-theme', color)
                    for zoom in ('100%', '200%'):
                        page.evaluate('(zoom) => document.documentElement.style.zoom = zoom', zoom)
                        dimensions = page.evaluate('''() => ({scroll: document.documentElement.scrollWidth,
                            client: document.documentElement.clientWidth})''')
                        assert dimensions['scroll'] <= dimensions['client'] + 2, (width, color, zoom, dimensions)
                        expect(event).to_contain_text('1,250,000')
                        expect(card).to_be_visible()
                        expect(radio).to_be_checked()
                        assert theme.count() == 1
            assert errors == []
            assert requests.count(('/api/imports/ota/cards/synthetic-long', 'GET')) == 1
            assert all(method == 'GET' and path != '/api/imports/ota' for path, method in requests)
        finally:
            browser.close()


@pytest.mark.parametrize('status,code', [(409, 'SNAPSHOT_CHANGED'), (400, 'BAD_CURSOR')])
def test_member_failure_clears_stale_rows_or_displays_cursor_error(status, code):
    reads = {'summary': 0, 'members': 0}
    group_id = 'a' * 64

    def route(request):
        path = urlsplit(request.request.url).path
        if path.endswith('/summary'):
            reads['summary'] += 1
            body = summary(reads['summary'])
        elif path.endswith('/groups'):
            body = {'generation': reads['summary'], 'next_cursor': None,
                    'items': [row(group_id)] if reads['summary'] == 1 else []}
        elif path.endswith('/members'):
            reads['members'] += 1
            request.fulfill(status=status, json={'code': code})
            return
        else:
            request.fulfill(status=404, json={'code': 'NOT_FOUND'})
            return
        request.fulfill(json=body)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 375, 'height': 812})
            page.set_default_timeout(4000)
            page.clock.install(time=datetime(2026, 10, 28, tzinfo=timezone.utc))
            page.clock.pause_at(datetime(2026, 10, 28, 0, 0, 1, tzinfo=timezone.utc))
            page.route('**/api/imports/ota/**', route)
            page.set_content(document())
            page.locator('#ota-review > summary').click()
            page.locator('[data-queue-detail] > summary').click()
            if status == 409:
                expect(page.locator('#ota-events')).to_have_text('자료가 갱신되었습니다. 최신 목록을 다시 확인하세요.')
                assert page.locator('[data-queue-detail]').count() == 0
                with page.expect_request('**/api/imports/ota/summary'):
                    page.clock.run_for(1100)
                expect(page.locator('#ota-events')).to_have_text('이 페이지에 표시할 거래가 없습니다.')
                assert reads['summary'] == 2
            else:
                expect(page.locator('[data-group-error]')).to_have_text('페이지 정보가 만료되었습니다.')
                assert page.locator('[data-queue-detail]').count() == 1
                assert reads['summary'] == 1
            assert reads['members'] == 1
            if status == 400:
                retry = page.get_by_role('button', name='구성원 다시 불러오기')
                expect(retry).to_be_enabled()
                with page.expect_request('**/api/imports/ota/groups/*/members*'):
                    retry.click()
                expect(page.locator('[data-group-error]')).to_have_text('페이지 정보가 만료되었습니다.')
                assert reads['members'] == 2
                assert reads['summary'] == 1
        finally:
            browser.close()


@pytest.mark.parametrize('status,code,expected_retry', [
    (400, 'BAD_CURSOR', None), (503, 'SERVICE_ERROR', 'expired'),
])
def test_member_cursor_retry_resets_only_expired_cursor(status, code, expected_retry):
    group_id = 'b' * 64
    cursors = []

    def route(request):
        url = urlsplit(request.request.url)
        if url.path.endswith('/summary'):
            request.fulfill(json=summary())
        elif url.path.endswith('/groups'):
            request.fulfill(json={'generation': 1, 'next_cursor': None, 'items': [row(group_id)]})
        elif url.path.endswith('/members'):
            cursor = parse_qs(url.query).get('cursor', [None])[0]
            cursors.append(cursor)
            if cursor and cursors.count(cursor) == 1:
                request.fulfill(status=status, json={'code': code})
            else:
                request.fulfill(json={'generation': 1, 'items': [{'event': EVENT}],
                                      'total_count': 21, 'next_cursor': 'expired'})
        else:
            request.fulfill(status=404, json={'code': 'NOT_FOUND'})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route('**/api/imports/ota/**', route)
            page.set_content(document())
            page.locator('#ota-review > summary').click()
            page.locator('[data-queue-detail] > summary').click()
            page.get_by_role('button', name='다음 사건').click()
            expect(page.locator('[data-group-error]')).to_be_visible()
            if code == 'BAD_CURSOR':
                page.locator('[data-group-members]').evaluate(
                    "e => e.insertAdjacentHTML('beforeend', \"<div class='ota-card-row'><input type='radio' checked></div>\")")
                page.get_by_role('button', name='구성원 다시 불러오기').click()
                expect(page.locator('#ota-freshness')).to_contain_text('저장하지 않은 선택')
                assert cursors == [None, 'expired']
                page.locator('.ota-card-row input').evaluate('e => e.checked = false')
            page.get_by_role('button', name='구성원 다시 불러오기').click()
            expect(page.locator('[data-group-error]')).to_have_count(0)
            expect(page.get_by_role('button', name='다음 사건')).to_be_visible()
            assert cursors == [None, 'expired', expected_retry]
        finally:
            browser.close()
