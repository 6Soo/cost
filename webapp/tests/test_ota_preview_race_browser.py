import json

from playwright.sync_api import sync_playwright

from webapp.ota_payment_review import render_import_section


def test_late_preview_cannot_replace_the_current_card_selection():
    event = {'ota_event_id': 'event-syn', 'booking_ref': 'BOOK-SYN', 'provider': 'Synthetic', 'status': 'HOLD_AMBIGUOUS'}
    cards = [{'transaction_id': identity, 'merchant': identity, 'amount_krw': 1000}
             for identity in ('card-a-syn', 'card-b-syn')]
    snapshot = {'events': [event], 'cards_by_event': {'event-syn': cards}, 'proposals': []}
    pending = []
    confirms = []
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 844})

        def respond(route):
            request = route.request
            if request.method == 'GET':
                route.fulfill(json=snapshot)
            elif request.url.endswith('/preview'):
                body = request.post_data_json
                if body['transaction_id'] == 'card-a-syn':
                    pending.append(route)
                else:
                    route.fulfill(json={'preview_digest': 'digest-b-syn', 'difference_krw': 22,
                                        'event_amount_krw': 1022, 'card_amount_krw': 1000})
            elif request.url.endswith('/confirm'):
                confirms.append(request.post_data_json)
                route.fulfill(json={'status': 'MATCHED_USER'})

        page.route('http://localhost/', lambda route: route.fulfill(
            content_type='text/html; charset=utf-8', body=render_import_section('csrf-syn')))
        page.route('http://localhost/api/imports/ota**', respond)
        page.add_init_script("""window.previewResponses=0;const realFetch=window.fetch;
            window.fetch=async(...args)=>{const response=await realFetch(...args);
              if(String(args[0]).endsWith('/preview')){const realJson=response.json.bind(response);
                response.json=async()=>{const data=await realJson();
                  setTimeout(()=>window.previewResponses++,0);return data}}
              return response};""")
        try:
            page.goto('http://localhost/')
            page.locator("#ota-review > summary").click()
            page.get_by_text('BOOK-SYN', exact=True).wait_for()
            page.locator('input[value="card-a-syn"]').check()
            with page.expect_request('**/preview'):
                page.get_by_role('button', name='차이 미리 보기', exact=True).click()
            page.locator('input[value="card-b-syn"]').check()
            assert len(pending) == 1
            page.get_by_role('button', name='차이 미리 보기', exact=True).click()
            page.get_by_text('차이 22원', exact=True).wait_for()
            pending.pop().fulfill(json={'preview_digest': 'digest-a-syn', 'difference_krw': 11,
                                        'event_amount_krw': 1011, 'card_amount_krw': 1000})
            page.wait_for_function('window.previewResponses === 2')
            assert page.get_by_text('차이 22원', exact=True).count() == 1
            assert page.get_by_text('차이 11원', exact=True).count() == 0
            page.get_by_role('button', name='이 거래로 결제 연결 확정', exact=True).click()
            page.get_by_text('사용자 확인 연결', exact=True).wait_for()
            assert len(confirms) == 1
            assert confirms[0]['transaction_id'] == 'card-b-syn'
            assert confirms[0]['preview_digest'] == 'digest-b-syn'
        finally:
            browser.close()
