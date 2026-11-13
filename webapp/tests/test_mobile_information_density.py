"""Observable first-viewport density, roster and owned-control regressions."""
from unittest.mock import patch
from webapp import flight_passenger_page,site_shell
from webapp.flight_booking_projection import project_booking_reservation


def test_browser_round_trip_and_all_passengers_fit_without_nested_field_panels():
    from playwright.sync_api import sync_playwright,expect
    evidence={'passengers':[{'surname':'KIM','given_name':'ALPHA'},{'surname':'LEE','given_name':'BETA'}],
      'legs':[{'label':label,'origin_city':origin,'destination_city':dest,'departure_on':day,
         'segments':[{'departure_airport':a,'arrival_airport':b,'departure_time':start,'arrival_time':end,'flight_number':'SYN123'}]}
       for label,origin,dest,day,a,b,start,end in [('가는편','서울','시즈오카','2026-11-22','ICN','FSZ','07:05','09:00'),
          ('오는편','시즈오카','서울','2026-11-26','FSZ','ICN','10:00','12:00')]]}
    row=project_booking_reservation('SYNTHETIC-ONLY',evidence,'KIM ALPHA')
    with patch('webapp.ledger_design.nav_region',return_value=''):
        doc=site_shell.wrap_document(flight_passenger_page._page('synthetic'),'/flight-passengers')
    with sync_playwright() as api:
        browser=api.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':390,'height':844})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.route('http://synthetic.test/flight-passengers',lambda route:route.fulfill(body=doc,content_type='text/html'))
            page.route('**/api/flight-passengers/name-search',lambda route:route.fulfill(json={
              'reservations':[row,dict(row,booking_ref='SYNTH-2')],'total':2,'source_status':'VERIFIED','revision':'synthetic'}))
            page.goto('http://synthetic.test/flight-passengers')
            page.get_by_label('항공권 검색').fill('시즈오카')
            page.get_by_role('button',name='예약 조회',exact=True).click()
            summary=page.locator('.fb-booking-choice > summary').first
            # Short rosters are named in the summary; only longer rosters show
            # the remaining passenger count there.
            expect(summary).to_contain_text('KIM ALPHA')
            expect(summary).to_contain_text('LEE BETA')
            expect(page.locator('#fb-status')).to_have_text('예약 2건')
            summary.click()
            # Both names already appear in the booking summary; no repeated box.
            expect(page.locator('.fb-passengers')).to_have_count(0)
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':844})
                for theme in ('light','dark'):
                    page.evaluate('(t)=>{document.documentElement.dataset.theme=t;scrollTo(0,0)}',theme)
                    positions=page.locator('.fb-booking-choice').first.evaluate('''node=>({
                      legs:[...node.querySelectorAll('.fb-flight-card')].map(e=>({top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom,height:e.getBoundingClientRect().height})),
                      overflow:document.documentElement.scrollWidth>innerWidth,
                      times:[...node.querySelectorAll('.fb-time')].map(e=>e.textContent),
                      nestedFields:node.querySelectorAll('.fb-flight-facts').length})''')
                    assert not positions['overflow']
                    assert positions['times']==['07:05','09:00','10:00','12:00']
                    assert positions['nestedFields']==0
                    assert max(leg['height'] for leg in positions['legs'])<=140
                    if width==390:
                        assert positions['legs'][0]['top']<360
                        assert positions['legs'][1]['bottom']<740
            # Large party sizes remain fully available on expansion.
            assert not page.locator('.fb-more-details').first.evaluate('(e)=>e.open')
            large=dict(row,passengers=['SYNTHETIC PERSON '+str(i) for i in range(9)])
            page.route('**/api/flight-passengers/name-search',lambda route:route.fulfill(json={
                'reservations':[large,dict(large,booking_ref='SYNTH-2')],'total':2,'source_status':'VERIFIED','revision':'large'}))
            page.get_by_label('항공권 검색').fill('large')
            page.get_by_role('button',name='예약 조회',exact=True).click()
            expect(page.locator('.fb-booking-choice > summary').first).to_contain_text('외 6명')
            page.locator('.fb-booking-choice > summary').first.click()
            for i in range(9):
                expect(page.locator('.fb-passengers').first).to_contain_text('SYNTHETIC PERSON '+str(i))
            assert errors==[]
        finally:
            browser.close()


def test_browser_owned_card_row_and_cleanup_disclosure_are_not_auto_decorated():
    from playwright.sync_api import sync_playwright,expect
    body='''<!doctype html><html><head><meta charset="utf-8"><title>카드 전체 내역</title></head><body><main>
      <h1>카드 전체 내역</h1><button class="card-all-row-toggle" aria-expanded="false">합성 거래<span>합성 카드</span></button>
      <details class="cleanup-review"><summary>근거 보기</summary><p>합성 근거</p></details></main></body></html>'''
    doc=site_shell.wrap_document(body,'/cards/all')
    with sync_playwright() as api:
        browser=api.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':390,'height':844})
            page.route('http://synthetic.test/cards/all',lambda route:route.fulfill(body=doc,content_type='text/html'))
            page.goto('http://synthetic.test/cards/all')
            assert page.locator('.card-all-row-toggle').get_attribute('class')=='card-all-row-toggle'
            assert 'site-action' not in (page.locator('.cleanup-review > summary').get_attribute('class') or '')
            assert not page.locator('h1').evaluate('(e)=>e.classList.contains("site-title-duplicate")')
            page.locator('.cleanup-review > summary').focus()
            page.keyboard.press('Enter')
            expect(page.get_by_text('합성 근거',exact=True)).to_be_visible()
        finally:
            browser.close()
