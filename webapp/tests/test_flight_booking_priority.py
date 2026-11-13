"""Content priority and disclosure geometry regressions, with synthetic mail only."""
from unittest.mock import patch
from webapp import flight_booking_projection as projection, flight_passenger_page as flights, site_shell


def reservation():
    return projection.project_booking_reservation('SYNTH-LONG-BOOKING-0001', {
        'conflict': True,
        'legs': [{'origin_city': '59 (서울 시간, GMT +9)환불 현황을 확인하려면 아래 버튼을 선택하세요.',
                  'destination_city': '시즈오카', 'departure_on': '2026-11-21',
                  'segments': [{'departure_airport': 'ICN', 'arrival_airport': 'FSZ',
                                'departure_time': '09:00', 'arrival_time': '11:00', 'flight_number': 'SYN123'}]}],
        'booking_date_status': 'FIRST_RECEIVED', 'reserved_on': '2026-10-01',
        'booking_card_day': '2026-10-01'}, 'SYNTHETIC LONG PASSENGER ALPHA')


def test_projection_removes_mail_prose_without_changing_conflict_or_source():
    row = reservation()
    assert row['legs'][0]['origin_city'] == ''
    assert row['legs'][0]['departure_on'] == '2026-11-21'
    assert row['conflict'] is True
    assert projection.project_itinerary_leg({'departure_on': '2026-11-21 long mail footer'})['departure_on'] == ''


def test_browser_passenger_heading_and_conflict_recovery_lead_to_real_readonly_actions():
    from playwright.sync_api import sync_playwright, expect
    from copy import deepcopy
    row = dict(reservation(), provider='jeju', passengers=['KIM ALPHA'],
               passenger_name='KIM ALPHA', reserved_on='2026-10-01', booking_card_day='',
               booking_date_status='EXPLICIT_LABEL')
    before = deepcopy(row)
    with patch('webapp.ledger_design.nav_region', return_value=''):
        document = site_shell.wrap_document(flights._page('synthetic'), '/flight-passengers')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 1000})
            requests = []
            page.route('http://synthetic.test/flight-passengers', lambda route: route.fulfill(body=document, content_type='text/html'))
            page.route('**/api/flight-passengers/name-search', lambda route: route.fulfill(json={
                'reservations': [row, dict(row, booking_ref='SYNTH-2')], 'total': 2,
                'revision': 'synthetic', 'source_status': 'VERIFIED'}))
            def day(route):
                requests.append((route.request.method, route.request.url))
                route.fulfill(json={'filter_semantics': 'USER_DATE_FILTER', 'date': '2026-10-01',
                                    'items': [], 'total_count': 0, 'has_more': False})
            page.route('**/api/cards/transactions/day?*', day)
            page.goto('http://synthetic.test/flight-passengers')
            page.get_by_label('항공권 검색').fill('ALPHA')
            page.get_by_role('button', name='예약 조회', exact=True).click()
            summary = page.locator('.fb-booking-choice > summary').first
            expect(summary.locator('strong')).to_have_text('KIM ALPHA')
            summary.click()
            ticket = page.locator('.fb-ticket').first
            warning = ticket.locator('.fb-reservation-warning')
            expect(warning).to_contain_text('예약 자료가 서로 일치하지 않습니다')
            expect(warning.get_by_role('link', name='제주항공에서 예약 확인')).to_have_attribute('href', 'https://www.jejuair.net/')
            expect(warning.get_by_role('button', name='예약번호 복사')).to_be_visible()
            # No timestamp/zone is available: the field stays manual, no automatic query.
            date = ticket.get_by_label('조회 날짜', exact=True)
            expect(date).to_be_visible()
            expect(date).to_have_value('')
            assert requests == []
            date.fill('2026-10-01')
            ticket.get_by_role('button', name='카드 내역 조회', exact=True).click()
            expect(ticket.locator('.fb-date-status')).to_contain_text('카드 내역이 없습니다')
            assert len(requests) == 1 and requests[0][0] == 'GET'
            expect(ticket.locator('.fb-date-filter')).to_contain_text('다른 날짜')
            # Copy failure has an in-place fallback; success never confirms a booking/payment.
            page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async () => { throw Error('blocked'); }}})")
            warning.get_by_role('button', name='예약번호 복사').click()
            expect(warning.locator('[role=status]')).to_contain_text('직접 선택해 복사')
            for width in (320, 390, 1440):
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert row == before
        finally:
            browser.close()


def test_browser_flight_priority_and_disclosures_do_not_stack_icons_above_text():
    from playwright.sync_api import sync_playwright, expect
    with patch('webapp.ledger_design.nav_region', return_value=''):
        document=site_shell.wrap_document(flights._page('synthetic'), '/flight-passengers')
    row=reservation()
    with sync_playwright() as api:
        browser=api.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':390,'height':844})
            page.route('http://synthetic.test/flight-passengers',lambda route:route.fulfill(body=document,content_type='text/html'))
            page.route('**/api/flight-passengers/name-search',lambda route:route.fulfill(json={
                'reservations':[row,dict(row,booking_ref='SYNTH-2')],'total':2,'revision':'synthetic','source_status':'VERIFIED'}))
            page.goto('http://synthetic.test/flight-passengers')
            page.get_by_label('항공권 검색').fill('시즈오카')
            page.get_by_role('button',name='예약 조회',exact=True).click()
            summary=page.locator('.fb-booking-choice > summary').first
            expect(summary).to_contain_text('ICN → 시즈오카')
            expect(summary).to_contain_text('2026-11-21')
            expect(summary).not_to_contain_text('SYNTH-LONG-BOOKING')
            summary.click()
            card=page.locator('.fb-ticket').first
            expect(card.locator('.fb-itinerary')).to_be_visible()
            expect(card.locator('.fb-hero')).to_contain_text('SYNTHETIC LONG PASSENGER')
            expect(card.locator('.fb-note').first).to_be_visible()
            expect(card.get_by_text('예약일 근거',exact=True)).to_be_visible()
            expect(card.get_by_text('카드 결제',exact=True)).to_be_visible()
            expect(card.get_by_label('조회 날짜', exact=True)).to_be_visible()
            assert '환불 현황을 확인하려면' not in page.locator('main').inner_text()
            details=card.locator('.fb-more-details')
            assert not details.evaluate('(node)=>node.open')
            itinerary_top=card.locator('.fb-itinerary').bounding_box()['y']
            details_top=details.bounding_box()['y']
            assert itinerary_top < details_top
            details.locator(':scope > summary').click()
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':1000})
                for theme in ('light','dark'):
                    page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                    result=page.evaluate('''()=>({overflow:document.documentElement.scrollWidth>innerWidth,
                      summaries:[...document.querySelectorAll('#flight-booking-page summary')].filter(e=>e.checkVisibility()).map(e=>({
                        display:getComputedStyle(e).display,icon:e.classList.contains('site-action-icon'),height:e.getBoundingClientRect().height,
                        arrow:getComputedStyle(e,'::after').width})),
                      submit:document.querySelector('#fb-submit').getBoundingClientRect().height})''')
                    assert not result['overflow']
                    assert result['submit'] >= 44
                    assert all(s['display']=='flex' and not s['icon'] and s['height']>=44 and s['arrow']=='7px' for s in result['summaries'])
            # Keyboard toggling remains native and focus is visible.
            detail_summary=details.locator(':scope > summary')
            detail_summary.focus()
            detail_summary.press('Enter')
            assert not details.evaluate('(node)=>node.open')
        finally:
            browser.close()


def test_browser_trip_groups_merge_next_page_and_keep_passenger_titles_and_unassigned():
    from playwright.sync_api import sync_playwright, expect
    first = dict(reservation(), passengers=['KIM ALPHA'], passenger_name='KIM ALPHA',
                 assigned_trip_tab_id='trip-a', assigned_trip_title='11월 시즈오카',
                 assigned_trip_starts_on='2026-11-21', trip_assignment_available=True)
    second = dict(first, booking_ref='SYNTH-B', passengers=['PARK BETA'],
                  assigned_trip_tab_id='trip-b', assigned_trip_title='12월 도쿄',
                  assigned_trip_starts_on='2026-12-01')
    unassigned = dict(first, booking_ref='SYNTH-UNASSIGNED', passengers=['LEE GAMMA'],
                      assigned_trip_tab_id='', assignment_status='UNRESOLVED')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            page = browser.new_page()
            page.route('http://synthetic.test/flight-passengers', lambda route: route.fulfill(
                body=flights._page('synthetic'), content_type='text/html'))
            def search(route):
                more = bool(route.request.post_data_json.get('offset'))
                route.fulfill(json={'reservations': [dict(first, booking_ref='SYNTH-NEXT', passengers=['CHOI DELTA'])]
                                    if more else [first, second, unassigned],
                                    'revision': 'synthetic', 'total': 4, 'next_offset': None if more else 3})
            page.route('**/api/flight-passengers/name-search', search)
            page.goto('http://synthetic.test/flight-passengers')
            page.get_by_label('항공권 검색').fill('시즈오카')
            page.get_by_role('button', name='예약 조회', exact=True).click()
            groups = page.locator('.fb-trip-group')
            expect(groups).to_have_count(3)
            expect(groups.nth(0).locator('header h2')).to_have_text('12월 도쿄')
            expect(groups.nth(2).locator('header h2')).to_have_text('여행 귀속 없음')
            a = page.locator('.fb-trip-group[data-trip-id="trip-a"]')
            expect(a.locator('.fb-choice-copy strong')).to_have_text('KIM ALPHA')
            expect(a.get_by_role('link', name='여행별 비용')).to_have_attribute('href', '/board?tab=trip-a')
            page.get_by_role('button', name='예약 더 보기').click()
            expect(groups).to_have_count(3)
            expect(a.locator('.fb-choice-copy strong')).to_have_text(['KIM ALPHA', 'CHOI DELTA'])
            expect(a.locator('.fb-group-count')).to_have_text('2건 표시')
            expect(groups.nth(2).locator('.fb-choice-copy strong')).to_have_text('LEE GAMMA')
        finally:
            browser.close()
