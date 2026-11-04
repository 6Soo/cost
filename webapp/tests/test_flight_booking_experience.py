"""User-visible booking journeys; all records are synthetic."""
from unittest.mock import patch

from webapp import flight_booking_projection as projection, flight_passenger_page as flights


def test_booking_contains_every_documented_passenger_and_revises_on_manifest_change():
    evidence = {'source_digests': ['synthetic'], 'passengers': [
        {'surname': 'KIM', 'given_name': 'ALPHA'}, {'surname': 'PARK', 'given_name': 'BETA'},
        {'surname': 'KIM', 'given_name': 'ALPHA'}], 'cancellation_status': 'CONFLICT'}
    first = projection.query_booking_reservations({'SYNTH-1': evidence}, 'ALPHA')
    row = first['reservations'][0]
    assert row['passengers'] == ['KIM ALPHA', 'PARK BETA']
    assert row['cancellation_status'] == 'CONFLICT'
    evidence['passengers'].append({'surname': 'LEE', 'given_name': 'GAMMA'})
    second = projection.query_booking_reservations({'SYNTH-1': evidence}, 'ALPHA')
    assert first['revision'] != second['revision']


def test_browser_multi_city_booking_and_payment_are_readable_without_internal_fields():
    from playwright.sync_api import sync_playwright, expect
    from webapp import site_shell
    row = projection.project_booking_reservation('SYNTH-1', {
        'passengers': [{'surname': 'KIM', 'given_name': 'ALPHA'}, {'surname': 'PARK', 'given_name': 'BETA'}],
        'booking_date_status': 'FIRST_RECEIVED', 'reserved_on': '2026-10-01',
        'booking_card_day': '2026-10-01', 'booking_date_evidence': [{'timestamp': '2026-10-01T09:00:00+09:00'}],
        'legs': [
            {'origin_city': '서울', 'destination_city': '파리', 'departure_on': '2026-11-10', 'segments': [
                {'departure_airport': 'ICN', 'arrival_airport': 'DXB', 'flight_number': 'SYN1'},
                {'departure_airport': 'DXB', 'arrival_airport': 'CDG', 'flight_number': 'SYN2'}]},
            {'origin_city': '파리', 'destination_city': '로마', 'departure_on': '2026-11-15', 'segments': []}]}, 'KIM ALPHA')
    with patch('webapp.ledger_design.nav_region', return_value=''):
        document = site_shell.wrap_document(flights._page('synthetic'), '/flight-passengers')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.route('http://synthetic.test/flight-passengers', lambda route: route.fulfill(body=document, content_type='text/html'))
            page.route('**/api/flight-passengers/name-search', lambda route: route.fulfill(json={
                'reservations': [row], 'source_status': 'VERIFIED', 'revision': 'synthetic', 'total': 1}))
            page.route('**/api/cards/transactions/day?*', lambda route: route.fulfill(json={
                'date': '2026-10-01', 'filter_semantics': 'USER_DATE_FILTER', 'total_count': 1,
                'items': [{'merchant': 'Synthetic card merchant', 'amount_krw': 1234567,
                           'classification_state': 'PRIVATE-STATE', 'trip_id': 'PRIVATE-TRIP',
                           'display_tab_id': 'PRIVATE-DISPLAY', 'approval_number': 'SYN-AUTH',
                           'transaction_direction': 'refund', 'approval_date': '2026-10-01'}]}))
            page.goto('http://synthetic.test/flight-passengers')
            page.get_by_label('항공권 검색').fill('ALPHA')
            page.get_by_label('항공권 검색').press('Enter')
            expect(page.locator('.fb-hero')).to_contain_text('KIM ALPHA')
            expect(page.locator('.fb-summary')).not_to_contain_text('PARK BETA')
            cards = page.locator('.fb-flight-card')
            expect(cards).to_have_count(3)
            assert cards.nth(0).locator('.fb-route-stop strong').all_text_contents() == ['ICN', 'DXB']
            assert cards.nth(1).locator('.fb-route-stop strong').all_text_contents() == ['DXB', 'CDG']
            expect(cards.nth(2).locator('.fb-flight-title')).to_have_text('여정 2')
            assert page.locator('.fb-return').count() == 0
            expect(page.locator('.fb-date-row')).to_have_count(0)
            page.locator('.fb-more-details > summary').click()
            page.locator('.fb-date-filter > summary').click()
            expect(page.locator('.fb-date-row')).to_have_count(1)
            expect(page.get_by_text('1,234,567원', exact=True)).to_be_visible()
            expect(page.get_by_text('취소·환불', exact=True)).to_be_visible()
            assert not any(value in page.locator('main').inner_text() for value in ('PRIVATE-', '표시 여행 ID', '분류 상태'))
            expect(page.get_by_text('SYN-AUTH', exact=True)).not_to_be_visible()
            page.get_by_text('승인 정보', exact=True).click()
            expect(page.get_by_text('SYN-AUTH', exact=True)).to_be_visible()
            for width in (320, 390, 768, 1440):
                page.set_viewport_size({'width': width, 'height': 844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            for theme in ('light', 'dark'):
                page.evaluate('(t)=>document.documentElement.dataset.theme=t', theme)
                assert page.locator('.fb-hero').is_visible()
        finally:
            browser.close()


def test_browser_source_change_clears_stale_results_and_failed_more_can_retry():
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            page = browser.new_page()
            page.route('http://synthetic.test/flight-passengers', lambda route: route.fulfill(body=flights._page('synthetic'), content_type='text/html'))
            calls = []
            def search(route):
                calls.append(route.request.post_data_json)
                if len(calls) == 1:
                    route.fulfill(json={'source_status': 'VERIFIED', 'reservations': [{'booking_ref': 'SYNTH-OLD'}], 'revision': 'old', 'next_offset': 1, 'total': 2})
                elif len(calls) == 2:
                    route.fulfill(status=503, json={'code': 'TEMPORARY'})
                else:
                    route.fulfill(status=409, json={'code': 'SOURCE_CHANGED'})
            page.route('**/api/flight-passengers/name-search', search)
            page.goto('http://synthetic.test/flight-passengers')
            page.get_by_label('항공권 검색').fill('ALPHA')
            page.get_by_label('항공권 검색').press('Enter')
            expect(page.locator('.fb-ticket')).to_have_count(1)
            page.get_by_role('button', name='예약 더 보기').click()
            expect(page.locator('#fb-status')).to_contain_text('다시 시도')
            expect(page.get_by_role('button', name='예약 더 보기')).to_be_enabled()
            page.get_by_role('button', name='예약 더 보기').click()
            expect(page.locator('.fb-ticket')).to_have_count(0)
            expect(page.locator('#fb-status')).to_contain_text('자료가 변경')
            assert all(c['name'] == 'ALPHA' for c in calls)
        finally:
            browser.close()
