"""Synthetic tests for name-only flight lookup. Never access live reservations."""
import json
import os
import pytest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from webapp import flight_passenger_page as page


def _index():
    return {
        "SYNTH-100": {
            "source_digests": ["sha-synthetic"],
            "digest": "flight-synthetic-current",
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
            "legs": [{"label": "가는 편", "origin_city": "서울", "destination_city": "도쿄",
                      "departure_on": "2026-11-10", "segments": [{"departure_airport": "ICN",
                      "arrival_airport": "NRT", "departure_time": "09:10", "arrival_time": "11:30",
                      "flight_number": "SYN123"}]}],
            "cancellation_status": "NONE",
            "conflict": False,
        },
        "SYNTH-200": {
            "source_digests": ["sha-synthetic-b"],
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
            "legs": [],
            "cancellation_status": "CANCELLED",
            "conflict": False,
        },
        "SYNTH-NO-PROOF": {
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
        },
        "SYNTH-DIFFERENT": {
            "source_digests": ["sha-synthetic-c"],
            "passengers": [{"surname": "PARK", "given_name": "BETA"}],
        },
    }


class Handler:
    headers = {"X-CSRF-Token": "synthetic-csrf"}

    def _send_json(self, body, status=200):
        self.response = (status, body)

    def _send(self, body, status=200):
        self.response = (status, body)
        self.body = body


def test_name_search_needs_no_booking_number_or_tour_id():
    with patch("webapp.flight_booking_index.passenger_index_for", return_value=_index()) as lookup:
        found = page._name_search(object(), "  alpha / KIM ")
    assert [row["booking_ref"] for row in found["reservations"]] == ["SYNTH-100", "SYNTH-200"]
    assert found["reservations"][0]["source_verified"] is True
    assert found["reservations"][0]["cancelled"] is False
    assert found["reservations"][1]["cancelled"] is True
    lookup.assert_called_once()


def test_name_search_matches_one_verified_name_component_without_fuzzy_matching():
    responses = {}
    with patch.dict(os.environ, {page.FEATURE_FLAG: "1"}), patch(
        "webapp.flight_booking_index.passenger_index_for", return_value=_index()
    ):
        for query in ("alpha", "alph"):
            handler = Handler()
            page.dispatch(
                handler, urlsplit("/api/flight-passengers/name-search"),
                is_owner=True, board=object(), csrf="synthetic-csrf",
                raw=json.dumps({"name": query}).encode(),
            )
            responses[query] = handler.response
    assert responses["alpha"][0] == 200
    assert [row["booking_ref"] for row in responses["alpha"][1]["reservations"]] == ["SYNTH-100", "SYNTH-200"]
    assert responses["alph"][0] == 200
    assert responses["alph"][1]["reservations"] == []


def test_name_search_does_not_guess_korean_transliteration_or_unverified_records():
    with patch("webapp.flight_booking_index.passenger_index_for", return_value=_index()):
        result = page._name_search(object(), "김알파")
        assert result['reservations'] == [] and result['source_status'] == 'VERIFIED'
        assert not page._name_search(object(), "PARK BETA")["reservations"][0]["cancelled"]


def test_owner_only_post_search_csrf_and_old_assignment_route_stays():
    assert page.owns_route("/api/flight-passengers/assign")
    with patch.dict(os.environ, {page.FEATURE_FLAG: "1"}), patch(
        "webapp.flight_booking_index.passenger_index_for", return_value=_index()
    ):
        handler = Handler()
        assert page.dispatch(
            handler, urlsplit("/api/flight-passengers/name-search"),
            is_owner=True, board=object(), csrf="synthetic-csrf",
            raw=json.dumps({"name": "KIM ALPHA"}).encode(),
        )
        assert handler.response[0] == 200
        assert len(handler.response[1]["reservations"]) == 2
        handler = Handler()
        page.dispatch(handler, urlsplit("/api/flight-passengers/name-search"),
                      is_owner=False, board=object(), csrf="synthetic-csrf",
                      raw=b'{"name":"KIM ALPHA"}')
        assert handler.response[0] == 403
        handler = Handler()
        handler.headers = {}
        page.dispatch(handler, urlsplit("/api/flight-passengers/name-search"),
                      is_owner=True, board=object(), csrf="synthetic-csrf",
                      raw=b'{"name":"KIM ALPHA"}')
        assert handler.response[0] == 403


def test_page_renders_usable_name_only_ui_and_unknown_card_status():
    html = page._page('fake-token')
    assert '항공권 예약 확인' in html
    assert 'name="name"' in html
    assert 'name="booking_ref"' not in html
    assert 'name="tour_id"' not in html
    assert '결제 확인' in html
    assert '연결 근거 없음' in html
    assert '/api/flight-passengers/name-search' in html


def test_search_rejects_non_object_json_without_creating_assignment_store(tmp_path):
    with patch.dict(os.environ, {page.FEATURE_FLAG: "1", page.DB_ENV: str(tmp_path / "unused.sqlite")}):
        for payload in ([], None, "KIM ALPHA", {"name": []}):
            handler = Handler()
            page.dispatch(handler, urlsplit('/api/flight-passengers/name-search'),
                          is_owner=True, board=object(), csrf='synthetic-csrf',
                          raw=json.dumps(payload).encode())
            assert handler.response == (422, {'code': 'INVALID_NAME'})
    assert not (tmp_path / 'unused.sqlite').exists()


def test_browser_name_search_renders_verified_itinerary_and_secondary_participant_flow():
    from playwright.sync_api import sync_playwright, expect
    from webapp import site_shell

    with patch('webapp.flight_booking_index.passenger_index_for', return_value=_index()):
        result = page._name_search(object(), 'KIM ALPHA')
    result['reservations'][0]['linked_cards'] = [{'merchant': 'Synthetic Airline', 'amount_krw': 13000,
        'currency': 'KRW', 'amount_status': 'MISMATCH', 'currency_status': 'MATCH',
        'transaction_id': 'synthetic', 'approval_number': 'SYNTH-AUTH'}]
    with patch('webapp.ledger_design.nav_region', return_value=''):
        document = site_shell.wrap_document(page._page('synthetic-csrf'), '/flight-passengers')
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            screen = browser.new_page(viewport={'width': 375, 'height': 812})
            screen.route('http://synthetic.test/flight-passengers', lambda route: route.fulfill(
                content_type='text/html', body=document))
            requests = []
            def respond(route):
                payload = json.loads(route.request.post_data)
                requests.append(payload)
                if len(requests) == 1:
                    route.fulfill(content_type='application/json', body=json.dumps(
                        {'reservations': [], 'source_status': 'LOADING'}))
                    return
                first = payload.get('offset', 0) == 0
                batch = {**result, 'reservations': result['reservations'][:1] if first else result['reservations'][1:],
                         'next_offset': 100 if first else None, 'total': 2}
                route.fulfill(content_type='application/json', body=json.dumps(batch))
            screen.route('**/api/flight-passengers/name-search', respond)
            screen.goto('http://synthetic.test/flight-passengers')
            screen.get_by_label('항공권 검색').fill('KIM ALPHA')
            screen.get_by_label('항공권 검색').press('Enter')
            screen.locator('.fb-booking-choice > summary').first.click()
            ticket = screen.locator('.fb-ticket').first
            expect(ticket.get_by_text('서울', exact=True)).to_be_visible()
            assert ticket.get_by_text('도쿄', exact=True).is_visible()
            assert ticket.locator('.fb-flight-date').filter(has_text='2026-11-10').is_visible()
            assert ticket.get_by_text('SYN123', exact=True).is_visible()
            expect(ticket.locator('.fb-summary-item')).to_have_count(2)
            expect(ticket.locator('.fb-hero')).to_contain_text('KIM ALPHA')
            expect(ticket.locator('.fb-flight-card')).to_have_count(1)
            assert ticket.locator('.fb-route-stop').count() == 2
            assert ticket.get_by_text('Synthetic Airline', exact=True).is_visible()
            assert ticket.get_by_text('카드 원행 상세', exact=True).is_visible()
            assert ticket.get_by_text('결제 근거와 카드 원행의 금액·통화 차이 또는 미확인 항목이 있습니다. 원본을 대조해 주세요.').is_visible()
            assert ticket.get_by_text('참가자 연결 정보', exact=True).count() == 0
            screen.get_by_label('항공권 검색').fill('different input not submitted')
            screen.get_by_role('button', name='예약 더 보기').click()
            expect(screen.locator('.fb-ticket')).to_have_count(2)
            assert requests[-1]['name'] == 'KIM ALPHA'
            assert requests[-1]['revision'] == result['revision']
            for width in (375, 390, 759, 760, 1280):
                screen.set_viewport_size({'width': width, 'height': 812})
                assert screen.evaluate('document.documentElement.scrollWidth <= innerWidth')
            for scheme in ('light', 'dark'):
                screen.emulate_media(color_scheme=scheme)
                assert screen.get_by_role('heading', name='항공권 예약 확인', exact=True).is_visible()
            screen.set_viewport_size({'width': 760, 'height': 812})
            screen.evaluate('document.documentElement.style.zoom="200%"')
            # CSS zoom may round document scrollWidth up by one device pixel.
            assert screen.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert screen.locator(".fb-ticket").evaluate_all('(items)=>items.every(e=>e.getBoundingClientRect().right<=innerWidth)')
            assert ticket.get_by_text('참가자 연결 정보', exact=True).count() == 0
        finally:
            browser.close()


def test_browser_name_search_opens_real_synthetic_card_and_trip_flight_then_returns():
    """Exercise search, original card row, trip flight list/detail and browser return on real routes."""
    from types import SimpleNamespace
    from playwright.sync_api import sync_playwright, expect
    from webapp import flight_booking_index
    from webapp.card_flow import CardFlow
    from webapp.google_oidc import COOKIE_NAME
    from webapp.tests.test_signed_session_http import OWNER, SignedSessionHttpTests
    from tests.card_pipeline.fixtures import domestic_row, make_xlsx

    service = SignedSessionHttpTests()
    service.setUp()
    try:
        store = service.server.card_store
        trip = store.create_trip(starts_on='2026-11-07', ends_on='2026-11-10',
            destination='Synthetic flight trip', display_key='Synthetic flight trip',
            client_request_id='synthetic-flight-search-trip')
        flow = CardFlow(store)
        batch = flow.pipeline.receive(make_xlsx([domestic_row(
            merchant='SYNTHETIC AIRLINE', amount=13000, approval='SYN-FLIGHT-001',
            issuer='SYNTHETIC ISSUER', card='****3820', kind='매입')]),
            'synthetic-flight-card.xlsx')['batch_id']
        source_row = flow.pipeline.get_batch(batch)['rows'][0]
        transaction_id = source_row['transaction_id']
        flow.trip_valid = lambda candidate: candidate == trip['tab_id']
        decision = flow.pipeline.save_decision(
            transaction_id, source_row['revision'], item='항공료',
            description='Synthetic airline fare', display_tab_id=trip['tab_id'],
            trip_id=trip['tab_id'], request_id='synthetic-flight-trip-assignment',
            trip_validator=flow.trip_valid, tab_validator=flow.tab_valid)
        assert decision['trip_id'] == trip['tab_id']
        assert flow.record_decision(batch, transaction_id) == 1

        index = _index()
        evidence = index['SYNTH-100']
        card = {
            'transaction_id': transaction_id, 'source_hash': source_row['source_hash'],
            'issuer': 'SYNTHETIC ISSUER', 'merchant': 'SYNTHETIC AIRLINE',
            'merchant_normalized': 'synthetic airline', 'card_tail': '3820',
            'approval_date': '2026-11-10', 'approval_number': 'SYN-FLIGHT-001',
            'transaction_direction': 'purchase', 'amount_krw': 13000,
            'foreign_currency': '', 'foreign_amount': None,
        }
        event = {
            'ota_event_id': 'synthetic-flight-paid-event', 'provider': 'trip',
            'booking_ref': 'SYNTH-100', 'event_type': 'charge',
            'evidence_status': 'paid_verified', 'payment_status': 'paid',
            'source_digest': 'synthetic-flight-payment-proof',
            'amount_krw': 13000, 'currency': 'KRW',
        }
        snapshot = {
            'passengers': {'SYNTH-100': evidence}, 'events': [event],
            'transactions': [card],
            'links': {event['ota_event_id']: {
                'transaction_id': transaction_id, 'status': 'MATCHED_USER',
                'source_digest': event['source_digest']}},
            'results': [{'ota_event_id': event['ota_event_id'],
                'transaction_id': transaction_id, 'status': 'MATCHED_USER'}],
        }
        store._ota_snapshot_service = SimpleNamespace(
            held=lambda: ({'data': snapshot}, True))
        store._flight_booking_service = SimpleNamespace(display_context=lambda: (
            {'data': snapshot}, {'fresh': True, 'generation': 'synthetic-flight-generation'}))

        with patch.dict(os.environ, {
                page.FEATURE_FLAG: '1', 'WEBLEDGER_OTA_REVIEW_DB': ''}), \
             patch('webapp.flight_booking_index.passenger_index_for', return_value=index), \
             patch.object(flight_booking_index, 'prewarm', return_value=None):
            with sync_playwright() as api:
                browser = api.chromium.launch(headless=True)
                try:
                    context = browser.new_context(viewport={'width': 1280, 'height': 900})
                    context.add_cookies([{
                        'name': COOKIE_NAME, 'value': service.cookie(OWNER),
                        'url': f'http://127.0.0.1:{service.port}',
                    }])
                    screen = context.new_page()
                    search_requests = []
                    screen.on('request', lambda request: search_requests.append(request.post_data)
                              if request.url.endswith('/api/flight-passengers/name-search') else None)
                    base = f'http://127.0.0.1:{service.port}'
                    screen.goto(base + '/flight-passengers')
                    expect(screen.locator('h1').first).to_be_visible()
                    screen.locator('input[name="name"]').fill('KIM ALPHA')
                    screen.locator('form button[type="submit"]').click()
                    tickets = screen.locator('.fb-ticket')
                    screen.locator('.fb-booking-choice').filter(has_text='SYNTH-100').locator('summary').first.click()
                    expect(tickets.filter(has_text='SYNTH-100')).to_be_visible()
                    expect(tickets.filter(has_text='SYNTH-100').get_by_text('SYN123', exact=True)).to_be_visible()

                    detail = tickets.filter(has_text='SYNTH-100').locator('.fb-card-detail')
                    detail.locator('summary').click()
                    expect(detail).to_contain_text('SYNTHETIC AIRLINE')
                    expect(detail).to_contain_text('13,000')
                    assert detail.locator('a,button,form').count() == 0
                    detail.locator('summary').click()

                    # The originating tab keeps both reservations and needs no repeat search.
                    expect(screen).to_have_url(base + '/flight-passengers')
                    expect(screen.locator('input[name="name"]')).to_have_value('KIM ALPHA')
                    expect(tickets.filter(has_text='SYNTH-100')).to_be_visible()
                    assert len(search_requests) == 1
                    assert 'KIM ALPHA' not in screen.url and 'SYNTH-100' not in screen.url
                    storage = screen.evaluate("JSON.stringify([localStorage, sessionStorage])")
                    assert 'KIM ALPHA' not in storage and 'SYNTH-100' not in storage
                    # Verify the second synthetic reservation directly from the preserved results.
                    screen.locator('.fb-booking-choice').filter(has_text='SYNTH-200').locator('summary').first.click()
                    second = tickets.filter(has_text='SYNTH-200')
                    expect(second).to_contain_text('SYNTH-200')
                    expect(second).to_contain_text('KIM ALPHA')
                    assert len(search_requests) == 1
                finally:
                    browser.close()
    finally:
        service.tearDown()


def test_browser_manual_date_filter_keeps_explicit_date_and_refuses_mixed_revisions():
    from playwright.sync_api import sync_playwright, expect
    from webapp import site_shell
    with patch('webapp.flight_booking_index.passenger_index_for', return_value=_index()):
        result = page._name_search(object(), 'KIM ALPHA')
    result['reservations'] = result['reservations'][:1]
    with patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"></aside>'):
        document = site_shell.wrap_document(page._page('synthetic-csrf'), '/flight-passengers')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        screen = browser.new_page(viewport={'width': 375, 'height': 812})
        screen.route('http://synthetic.test/flight-passengers', lambda route: route.fulfill(content_type='text/html', body=document))
        screen.route('**/api/flight-passengers/name-search', lambda route: route.fulfill(json=result))
        requests = []
        def respond(route):
            requests.append((route.request.method, route.request.url))
            if len(requests) == 3:
                route.fulfill(status=409, json={'code': 'SOURCE_CHANGED'})
                return
            first = len(requests) == 1
            route.fulfill(json={'filter_semantics': 'USER_DATE_FILTER', 'date': '2026-03-07',
                'items': [{'transaction_id': 'SYNTH-1' if first else 'SYNTH-2', 'approval_date': '2026-03-07',
                           'merchant': 'Synthetic same-amount merchant', 'amount_krw': -100,
                           'transaction_direction': 'credit', 'duplicate_of': 'other', 'parse_error': 'synthetic',
                           'display_tab_id': 'SYNTH-MANUAL-TRIP'}],
                'total_count': 3, 'has_more': True, 'cursor': '2026-03-07|SYNTH-' + ('1' if first else '2'),
                'revision': 'a' * 64})
        screen.route('**/api/cards/transactions/day?*', respond)
        screen.goto('http://synthetic.test/flight-passengers')
        screen.get_by_label('항공권 검색').fill('KIM ALPHA')
        screen.get_by_role('button', name='예약 조회', exact=True).click()
        expect(screen.locator('.fb-ticket')).to_have_count(1)
        if screen.locator('.fb-booking-choice > summary').count():
            screen.locator('.fb-booking-choice > summary').first.click()
        screen.get_by_text('카드 거래 보기', exact=True).click()
        screen.get_by_label('조회 날짜 (직접 지정 필터)').fill('2026-03-07')
        screen.get_by_role('button', name='지정 날짜 원행 조회', exact=True).click()
        expect(screen.locator('.fb-date-row')).to_have_count(1)
        assert screen.get_by_text('예약일이나 결제 연결이 확정된 것은 아닙니다.', exact=True).is_visible()
        assert screen.locator('.fb-date-row').get_by_text('중복 원행 · 원본 오류', exact=True).is_visible()
        assert 'SYNTH-MANUAL-TRIP' not in screen.locator('.fb-date-row').inner_text()
        assert '기존 분류 상태' not in screen.locator('.fb-date-row').inner_text()
        assert screen.locator('.fb-date-row').get_by_text('-100원', exact=True).is_visible()
        screen.get_by_label('조회 날짜 (직접 지정 필터)').fill('2026-04-01')
        screen.get_by_role('button', name='카드 원행 더 보기', exact=True).click()
        expect(screen.locator('.fb-date-row')).to_have_count(2)
        assert 'date=2026-03-07' in requests[-1][1]
        assert 'revision=' + 'a' * 64 in requests[-1][1]
        assert all(method == 'GET' for method, _ in requests)
        screen.get_by_role('button', name='카드 원행 더 보기', exact=True).click()
        expect(screen.locator('.fb-date-row')).to_have_count(0)
        assert screen.get_by_text('카드 자료가 변경됐습니다. 지정 날짜로 다시 조회해 주세요.', exact=True).is_visible()
        assert screen.evaluate('document.documentElement.scrollWidth<=innerWidth')
        browser.close()


def test_confirmed_cards_require_fresh_matching_manual_payment_evidence():
    evidence = _index()
    data = {'passengers': evidence, 'events': [{'ota_event_id': 'event-1', 'provider': 'trip',
            'booking_ref': 'SYNTH-100', 'source_digest': 'payment-proof', 'event_type': 'charge',
            'evidence_status': 'paid_verified', 'payment_status': 'paid', 'amount_krw': 12000,
            'currency': 'KRW'}],
            'links': {'event-1': {'transaction_id': 'card-1', 'status': 'MATCHED_USER',
                                 'source_digest': 'payment-proof'}},
            'results': [{'ota_event_id': 'event-1', 'transaction_id': 'card-1', 'status': 'MATCHED_USER'}],
            'transactions': [{'transaction_id': 'card-1', 'approval_date': '2026-10-20',
                              'merchant': 'Synthetic Airline', 'amount_krw': 13000, 'currency': 'KRW',
                              'approval_number': 'SYNTH-AUTH', 'raw_row_json': 'private-not-returned'}]}

    def search(snapshot, fresh=True):
        board = SimpleNamespace(_ota_snapshot_service=SimpleNamespace(held=lambda: ({'data': snapshot}, fresh)))
        with patch('webapp.flight_booking_index.passenger_index_for', return_value=evidence):
            return page._name_search(board, 'KIM ALPHA')['reservations'][0]

    booking = search(data)
    assert booking['linked_cards'][0]['transaction_id'] == 'card-1'
    assert booking['linked_cards'][0]['amount_status'] == 'MISMATCH'
    assert 'raw_row_json' not in booking['linked_cards'][0]
    assert not search(data, fresh=False)['linked_cards']
    for mutate in (
        lambda d: d['links']['event-1'].update(evidence_changed=True),
        lambda d: d['links']['event-1'].update(source_digest='old-proof'),
        lambda d: d['events'][0].update(provider='other-provider'),
        lambda d: d['events'][0].update(evidence_missing=True),
        lambda d: d['events'][0].update(event_type='scheduled_charge'),
        lambda d: d['events'][0].update(payment_status='unknown'),
        lambda d: d['results'][0].update(status='MATCHED_AUTO'),
        lambda d: d['results'][0].update(evidence_changed=True),
        lambda d: d['transactions'].clear(),
        lambda d: d['transactions'][0].update(duplicate_of='other-card'),
        lambda d: d['transactions'][0].update(parse_error='invalid amount'),
        lambda d: d['transactions'][0].update(conflict_reason='different source'),
        lambda d: d['passengers']['SYNTH-100'].update(conflict=True),
        lambda d: d['links'].update({'other-event': {'transaction_id': 'card-1'}}),
        lambda d: d['passengers']['SYNTH-100'].update(digest='changed-flight-proof'),
    ):
        snapshot = deepcopy(data)
        mutate(snapshot)
        assert not search(snapshot)['linked_cards']


def test_search_pages_all_matches_and_refuses_changed_source_revision():
    evidence = {f'SYNTH-{i:04d}': deepcopy(_index()['SYNTH-100']) for i in range(1001)}
    with patch('webapp.flight_booking_index.passenger_index_for', return_value=evidence):
        first = page._name_search(object(), 'KIM ALPHA')
        rows = list(first['reservations'])
        offset = first['next_offset']
        while offset is not None:
            batch = page._name_search(object(), 'KIM ALPHA', offset=offset, revision=first['revision'])
            rows.extend(batch['reservations'])
            offset = batch['next_offset']
        assert len(rows) == len({r['booking_ref'] for r in rows}) == 1001
        evidence['SYNTH-0000']['digest'] = 'changed-proof'
        try:
            page._name_search(object(), 'KIM ALPHA', offset=100, revision=first['revision'])
        except LookupError as exc:
            assert str(exc) == 'SOURCE_CHANGED'
        else:
            raise AssertionError('changed evidence must require a new search')


def test_no_current_evidence_and_secondary_participant_view_have_explicit_states():
    with patch('webapp.flight_booking_index.passenger_index_for', return_value={}):
        assert page._name_search(object(), 'KIM ALPHA')['source_status'] == 'UNAVAILABLE'
    with patch.dict(os.environ, {page.FEATURE_FLAG: '1'}):
        handler = Handler()
        page.dispatch(handler, urlsplit('/flight-passengers?view=participants'),
                      is_owner=True, board=object(), csrf='synthetic-csrf')
        assert '예약 시스템 여행 ID' in handler.body
        handler = Handler()
        page.dispatch(handler, urlsplit('/flight-passengers?view=participants'),
                      is_owner=False, board=object(), csrf='synthetic-csrf')
        assert handler.response[0] == 403


@pytest.mark.parametrize('outcome', ['VERIFIED', 'UNAVAILABLE', 'TIMEOUT'])
def test_browser_refresh_wait_stays_busy_and_announces_once_until_ready(outcome):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            screen = browser.new_page()
            screen.route('http://synthetic.test/flight-passengers', lambda route: route.fulfill(
                content_type='text/html', body=page._page('synthetic-csrf')))
            calls = []
            def respond(route):
                calls.append(route.request.post_data)
                route.fulfill(content_type='application/json', body=json.dumps({
                    'source_status': 'LOADING' if len(calls) < 3 or outcome == 'TIMEOUT' else outcome,
                    'reservations': [], 'total': 0}))
            screen.route('**/api/flight-passengers/name-search', respond)
            screen.clock.install()
            screen.goto('http://synthetic.test/flight-passengers')
            screen.evaluate("""() => {
                window.notices=[];
                new MutationObserver(() => window.notices.push(document.querySelector('[role=status]').textContent))
                    .observe(document.querySelector('[role=status]'), {childList:true});
            }""")
            screen.locator('input[name=name]').fill('SYNTH')
            screen.locator('form button[type=submit]').click()
            status = screen.locator('[role=status]')
            expect(status).to_contain_text('자동으로 조회')
            expect(screen.locator('form button[type=submit]')).to_be_disabled()
            expect(screen.locator('#fb-results')).to_have_attribute('aria-busy', 'true')
            first_notice = status.inner_text()
            with screen.expect_response('**/api/flight-passengers/name-search'):
                screen.clock.fast_forward(2000)
            expect(status).to_have_text(first_notice)
            expect(screen.locator('form button[type=submit]')).to_be_disabled()
            assert screen.evaluate('window.notices.filter(t=>t.includes("자동으로 조회")).length') == 1
            with screen.expect_response('**/api/flight-passengers/name-search'):
                screen.clock.fast_forward(120000 if outcome == 'TIMEOUT' else 2000)
            expected = {'VERIFIED': '예약이 없습니다', 'UNAVAILABLE': '최신 수집 상태', 'TIMEOUT': '다시 시도'}
            expect(status).to_contain_text(expected[outcome])
            expect(screen.locator('form button[type=submit]')).to_be_enabled()
            expect(screen.locator('#fb-results')).to_have_attribute('aria-busy', 'false')
            assert len(calls) == 3
            screen.clock.fast_forward(10000)
            assert len(calls) == 3
        finally:
            browser.close()


def test_browser_stalled_search_request_releases_controls_with_retry_message():
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            screen = browser.new_page()
            screen.route('http://synthetic.test/flight-passengers', lambda route: route.fulfill(
                content_type='text/html', body=page._page('synthetic-csrf')))
            screen.route('**/api/flight-passengers/name-search', lambda route: None)
            screen.clock.install()
            screen.goto('http://synthetic.test/flight-passengers')
            screen.locator('input[name=name]').fill('SYNTH')
            with screen.expect_request('**/api/flight-passengers/name-search'):
                screen.locator('form button[type=submit]').click()
            screen.clock.fast_forward(15000)
            expect(screen.locator('[role=status]')).to_contain_text('응답이 지연')
            expect(screen.locator('form button[type=submit]')).to_be_enabled()
            expect(screen.locator('#fb-results')).to_have_attribute('aria-busy', 'false')
        finally:
            browser.close()
