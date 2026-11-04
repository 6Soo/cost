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
            expect(card.get_by_text('예약일 근거',exact=True)).not_to_be_visible()
            expect(card.get_by_text('결제 확인',exact=True)).not_to_be_visible()
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
