"""Synthetic tests for name-only flight lookup. Never access live reservations."""
import json
import os
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
    with patch("webapp.ota_payment_review.passenger_index_for", return_value=_index()) as lookup:
        found = page._name_search(object(), "  alpha / KIM ")
    assert [row["booking_ref"] for row in found["reservations"]] == ["SYNTH-100", "SYNTH-200"]
    assert found["reservations"][0]["source_verified"] is True
    assert found["reservations"][0]["cancelled"] is False
    assert found["reservations"][1]["cancelled"] is True
    lookup.assert_called_once()


def test_name_search_does_not_guess_korean_transliteration_or_unverified_records():
    with patch("webapp.ota_payment_review.passenger_index_for", return_value=_index()):
        result = page._name_search(object(), "김알파")
        assert result['reservations'] == [] and result['source_status'] == 'VERIFIED'
        assert not page._name_search(object(), "PARK BETA")["reservations"][0]["cancelled"]


def test_owner_only_post_search_csrf_and_old_assignment_route_stays():
    assert page.owns_route("/api/flight-passengers/assign")
    with patch.dict(os.environ, {page.FEATURE_FLAG: "1"}), patch(
        "webapp.ota_payment_review.passenger_index_for", return_value=_index()
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
    assert '예약일의 카드 거래 후보' in html
    assert '확정된 카드 연결 근거를 아직 검증할 수 없습니다' in html
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
    from playwright.sync_api import sync_playwright
    from webapp import site_shell

    with patch('webapp.ota_payment_review.passenger_index_for', return_value=_index()):
        result = page._name_search(object(), 'KIM ALPHA')
    result['reservations'][0]['linked_cards'] = [{'merchant': 'Synthetic Airline', 'amount_krw': 13000,
        'currency': 'KRW', 'amount_status': 'MISMATCH', 'currency_status': 'MATCH',
        'detail_href': '/board?row=card-synthetic', 'approval_number': 'SYNTH-AUTH'}]
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
                first = payload.get('offset', 0) == 0
                batch = {**result, 'reservations': result['reservations'][:1] if first else result['reservations'][1:],
                         'next_offset': 100 if first else None, 'total': 2}
                route.fulfill(content_type='application/json', body=json.dumps(batch))
            screen.route('**/api/flight-passengers/name-search', respond)
            screen.goto('http://synthetic.test/flight-passengers')
            screen.get_by_label('탑승객 이름').fill('KIM ALPHA')
            screen.get_by_label('탑승객 이름').press('Enter')
            ticket = screen.locator('.fb-ticket').first
            assert ticket.get_by_text('서울', exact=True).is_visible()
            assert ticket.get_by_text('도쿄', exact=True).is_visible()
            assert ticket.get_by_text('2026-11-10', exact=True).is_visible()
            assert ticket.get_by_text('SYN123', exact=True).is_visible()
            assert ticket.get_by_text('Synthetic Airline', exact=True).is_visible()
            assert ticket.get_by_role('link', name='카드 원행 상세 보기').get_attribute('href') == '/board?row=card-synthetic'
            assert ticket.get_by_text('결제 근거와 카드 원행의 금액·통화 차이 또는 미확인 항목이 있습니다. 원본을 대조해 주세요.').is_visible()
            ticket.get_by_text('참가자 연결 정보', exact=True).click()
            assert ticket.get_by_role('link', name='참가자 연결 정보 열기').get_attribute('href') == '/flight-passengers?view=participants'
            screen.get_by_label('탑승객 이름').fill('different input not submitted')
            screen.get_by_role('button', name='예약 더 보기').click()
            assert screen.locator('.fb-ticket').count() == 2
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
            assert screen.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert ticket.get_by_role('link', name='참가자 연결 정보 열기').is_visible()
        finally:
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
        with patch('webapp.ota_payment_review.passenger_index_for', return_value=evidence):
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
        lambda d: d['links'].update({'other-event': {'transaction_id': 'card-1'}}),
        lambda d: d['passengers']['SYNTH-100'].update(digest='changed-flight-proof'),
    ):
        snapshot = deepcopy(data)
        mutate(snapshot)
        assert not search(snapshot)['linked_cards']


def test_search_pages_all_matches_and_refuses_changed_source_revision():
    evidence = {f'SYNTH-{i:04d}': deepcopy(_index()['SYNTH-100']) for i in range(1001)}
    with patch('webapp.ota_payment_review.passenger_index_for', return_value=evidence):
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
    with patch('webapp.ota_payment_review.passenger_index_for', return_value={}):
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
