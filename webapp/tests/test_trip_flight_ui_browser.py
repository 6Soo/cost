"""Synthetic browser coverage for lazy trip booking list and selected detail."""
from playwright.sync_api import sync_playwright

from webapp.trip_flight_ui import render_trip_flights


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
