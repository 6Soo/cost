"""Synthetic browser coverage for lazy trip booking list and selected detail."""
from playwright.sync_api import sync_playwright
from pathlib import Path

import pytest

from webapp.trip_flight_ui import render_trip_flights


@pytest.mark.parametrize('width', [1363, 680, 390, 320])
def test_booking_rows_fit_global_button_styles_and_selected_detail_is_accessible(width):
    css = (Path(__file__).parents[1] / 'static/css/ledger_design.css').read_text(encoding='utf-8')
    html = ("<!doctype html><html lang='ko'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<style>{css}</style><body style='height:auto;overflow:auto'>"
            "<main class='page-body' style='padding:16px'>" + render_trip_flights('trip-A') + '</main>')
    calls = []

    def respond(route):
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(route.request.url).query)
        if 'booking_key' in query:
            _respond(route, calls)
        else:
            route.fulfill(json={'items': [
                {'booking_key': f'key-{i}', 'booking_ref': f'LONG-RESERVATION-{i}-1234567890',
                 'outbound_departure_on': '2026-11-07', 'route_summary': 'ICN → FUK',
                 'passenger_count': 2, 'assignment_status': 'AUTO_INFERRED'} for i in range(3)],
                'source_generation': 'g', 'total_bookings': 3, 'next_cursor': None})

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 900})
            page.route('http://test.local/', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=html))
            page.route('http://test.local/api/trips/trip-A/flight-bookings**', respond)
            page.route('**/assets/fonts/**', lambda route: route.abort())
            page.goto('http://test.local')
            page.locator('summary').focus()
            page.keyboard.press('Enter')
            rows = page.locator('.trip-flight-items button')
            rows.first.wait_for()
            rows.nth(1).focus()
            page.keyboard.press('Enter')
            page.get_by_role('region', name='선택한 예약 상세').wait_for()
            assert rows.nth(1).get_attribute('aria-pressed') == 'true'
            assert rows.nth(1).get_by_text('선택됨').count() == 1
            assert rows.nth(0).get_attribute('aria-pressed') == 'false'
            assert page.locator('.trip-flight-detail').evaluate('(e) => e === document.activeElement')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert rows.evaluate_all('''buttons => buttons.every(button => {
                const box = button.getBoundingClientRect();
                return box.height >= 44 && [...button.children].every(child => {
                    const rect = child.getBoundingClientRect();
                    return rect.top >= box.top && rect.bottom <= box.bottom + 1;
                });
            })''')
            rects = page.evaluate('''() => ['.trip-flight-list','.trip-flight-detail'].map(
                selector => document.querySelector(selector).getBoundingClientRect().toJSON())''')
            if width == 1363:
                assert abs(rects[0]['top'] - rects[1]['top']) < 1
                assert rects[1]['left'] >= rects[0]['right']
            else:
                assert rects[1]['top'] >= rects[0]['bottom']
        finally:
            browser.close()


def test_unavailable_source_remains_visible_and_retry_recovers_to_visible_empty_state():
    html = "<!doctype html><meta charset='utf-8'>" + render_trip_flights('trip-A')
    attempts = []

    def respond(route):
        attempts.append(True)
        route.fulfill(json={'items': [], 'source_generation': 'g', 'next_cursor': None,
                            'total_bookings': 0,
                            'evidence_status': 'UNAVAILABLE' if len(attempts) == 1 else 'FRESH'})

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route('http://test.local/', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=html))
            page.route('http://test.local/api/trips/trip-A/flight-bookings**', respond)
            page.goto('http://test.local')
            page.locator('summary').click()
            retry = page.get_by_role('button', name='다시 불러오기')
            retry.wait_for()
            assert page.locator('.trip-flight').get_attribute('data-state') == 'error'
            assert '잠시 후 다시 불러와 주세요.' in page.get_by_role('status').inner_text()
            assert page.get_by_role('status').bounding_box()['height'] > 1
            retry.click()
            page.get_by_text('이 여행에 연결된 항공권 예약이 없습니다.').wait_for()
            assert page.locator('.trip-flight').get_attribute('data-state') == 'empty'
            assert page.get_by_role('status').bounding_box()['height'] > 1
        finally:
            browser.close()


def test_source_change_clears_stale_rows_and_reopening_fetches_a_new_list():
    from urllib.parse import urlparse, parse_qs
    html = "<!doctype html><meta charset='utf-8'><body>" + render_trip_flights("trip-A")
    calls = []
    def respond(route):
        query = parse_qs(urlparse(route.request.url).query)
        if "booking_key" in query:
            calls.append(query)
            route.fulfill(status=409, content_type="application/json", body='{"code":"SOURCE_CHANGED"}')
        else:
            _respond(route, calls)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route("http://test.local/", lambda route: route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=html))
            page.route("http://test.local/api/trips/trip-A/flight-bookings**", respond)
            page.goto("http://test.local")
            page.locator("summary").click()
            page.get_by_role("button", name="2026-11-07 · SYNTH-PNR").click()
            page.get_by_text("예약 자료가 갱신됐습니다. 목록을 새로 열어 주세요.").wait_for()
            assert page.locator(".trip-flight-items li").count() == 0
            page.locator("summary").click()
            page.locator("summary").click()
            page.get_by_role("button", name="2026-11-07 · SYNTH-PNR").wait_for()
            assert len(calls) == 3
            assert "cursor" not in calls[-1]
        finally:
            browser.close()


def test_trip_flight_list_is_lazy_and_detail_uses_text_content():
    html = "<!doctype html><meta charset='utf-8'><body>" + render_trip_flights("trip-A")
    calls = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route("http://test.local/", lambda route: route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=html))
            page.route("http://test.local/api/trips/trip-A/flight-bookings**", lambda route: _respond(route, calls))
            page.goto("http://test.local")
            assert calls == []
            page.locator("summary").click()
            page.get_by_role("button", name="2026-11-07 · SYNTH-PNR").wait_for()
            assert len(calls) == 1
            page.get_by_role("button", name="2026-11-07 · SYNTH-PNR").click()
            page.get_by_text("SYNTH-PNR · 1명").wait_for()
            assert len(calls) == 2 and calls[1]["generation"]
            assert page.locator(".trip-flight-detail img").count() == 0
            assert page.locator(".trip-flight-detail").inner_text().count("<img") == 1
            assert "최초 메일 수신일 기준 2026-05-04" in page.locator(".trip-flight-detail").inner_text()
        finally:
            browser.close()


def test_history_filter_exposes_cancelled_booking_and_returns_to_current():
    from urllib.parse import parse_qs, urlparse
    html = "<!doctype html><meta charset='utf-8'><body>" + render_trip_flights("trip-A")
    calls = []

    def respond(route):
        query = parse_qs(urlparse(route.request.url).query)
        calls.append(query)
        if 'booking_key' in query:
            route.fulfill(json={'item': {'booking_ref': 'CANCELLED', 'passengers': ['SYNTHETIC'],
                                        'legs': [], 'booking_status': 'CANCELLED',
                                        'assignment_status': 'AUTO_INFERRED'}})
            return
        items = [{'booking_key': 'trip:CURRENT', 'booking_ref': 'CURRENT',
                  'outbound_departure_on': '2026-11-07', 'passenger_count': 1,
                  'assignment_status': 'AUTO_INFERRED', 'booking_status': 'ACTIVE'}]
        if query.get('status') == ['all']:
            items.append({'booking_key': 'trip:CANCELLED', 'booking_ref': 'CANCELLED',
                          'outbound_departure_on': '2026-11-07', 'passenger_count': 1,
                          'assignment_status': 'AUTO_INFERRED', 'booking_status': 'CANCELLED'})
        route.fulfill(json={'items': items, 'source_generation': 'g', 'next_cursor': None,
                            'total_bookings': len(items), 'verified_passenger_count': 1,
                            'evidence_status': 'FRESH'})

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.route('http://test.local/', lambda route: route.fulfill(
                content_type='text/html; charset=utf-8', body=html))
            page.route('http://test.local/api/trips/trip-A/flight-bookings**', respond)
            page.goto('http://test.local')
            page.locator('summary').click()
            page.get_by_role('button', name='2026-11-07 · CURRENT').wait_for()
            page.get_by_label('예약 상태').select_option('all')
            page.get_by_role('button', name='2026-11-07 · CANCELLED').wait_for()
            assert '취소' in page.locator('.trip-flight-items li').last.inner_text()
            assert '현재 예약 탑승객 1명' in page.locator('summary').inner_text()
            page.get_by_role('button', name='2026-11-07 · CANCELLED').click()
            page.get_by_role('heading', name='CANCELLED · 1명').wait_for()
            assert '취소' in page.locator('.trip-flight-detail').inner_text()
            page.get_by_label('예약 상태').select_option('active')
            page.get_by_role('button', name='2026-11-07 · CURRENT').wait_for()
            assert page.get_by_role('button', name='2026-11-07 · CANCELLED').count() == 0
            assert calls[-3].get('status') == ['all'] and calls[-1].get('status') == ['active']
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()


def _respond(route, calls):
    from urllib.parse import urlparse, parse_qs
    query = parse_qs(urlparse(route.request.url).query)
    calls.append(query)
    if "booking_key" in query:
        route.fulfill(status=200, content_type="application/json", body=(
            '{"item":{"booking_ref":"SYNTH-PNR","passengers":["<img src=x onerror=alert(1)>"] ,'
            '"legs":[{"label":"가는편","departure_on":"2026-11-07","segments":[]}],'
            '"booking_date_label":"최초 메일 수신일 기준 2026-05-04"}}'))
    else:
        route.fulfill(status=200, content_type="application/json", body=(
            '{"items":[{"booking_key":"trip:SYNTHPNR","booking_ref":"SYNTH-PNR",'
            '"outbound_departure_on":"2026-11-07","route_summary":"ICN → FUK",'
            '"passenger_count":1,"assignment_status":"AUTO_INFERRED"}],"source_generation":"synthetic-g",'
            '"next_cursor":null,"total_bookings":1,"evidence_status":"FRESH"}'))
