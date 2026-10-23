import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from webapp import flight_passenger_page as page
from app.flight_passenger_matching import match_booking_passengers


EVIDENCE = {'booking_ref': 'SYNTH-500', 'source_digests': ['mail-sha-synth'],
            'passengers': [{'surname': 'KIM', 'given_name': 'ALPHA'}]}
AUTHORITY = {'tour_id': 'tour-synth', 'source_revision': 'roster-synth-v1',
             'candidates': [{'kind': 'lead', 'reference_id': 'opaque-synth',
                             'name_kr': '김알파', 'name_en': 'KIM/ALPHA', 'status': 'active'}]}


class Handler:
    headers = {'X-CSRF-Token': 'csrf-synth'}

    def _send_json(self, body, status=200):
        self.response = (status, body)

    def _send(self, body, status=200):
        self.response = (status, body)
        self.body = body


def test_get_is_owner_only_read_only_and_returns_unconfirmed_candidates(tmp_path):
    handler = Handler()
    board = object()
    calls = []

    def fetch(tour_id):
        calls.append(tour_id)
        return AUTHORITY

    with patch.dict(os.environ, {page.FEATURE_FLAG: '1', page.DB_ENV: str(tmp_path / 'flight.sqlite')}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500': EVIDENCE}):
        handled = page.dispatch(handler, urlsplit('/api/flight-passengers/candidates'),
                                is_owner=True, board=board,
                                query={'booking_ref': ['SYNTH-500'], 'tour_id': ['tour-synth']},
                                candidate_fetch=fetch)
    assert handled is True
    assert handler.response[0] == 200
    passenger = handler.response[1]['passengers'][0]
    assert passenger['status'] == 'EXACT_CANDIDATE'
    assert passenger['confirmed'] is False
    assert passenger['actual_boarding_confirmed'] is False
    assert calls == ['tour-synth']
    assert not (tmp_path / 'flight.sqlite').exists()


def test_owner_page_exposes_candidate_search_and_explicit_cost_confirmation_only(tmp_path):
    handler = Handler()
    with patch.dict(os.environ, {page.FEATURE_FLAG: '1', page.DB_ENV: str(tmp_path / 'flight.sqlite')}):
        handled = page.dispatch(handler, urlsplit('/flight-passengers'), is_owner=True,
                                board=object(), csrf='csrf-synth')
    assert handled is True
    assert '후보 조회' in handler.body
    assert '/api/flight-passengers/candidates' in handler.body
    assert '/api/flight-passengers/assign' in handler.body
    assert '실제 탑승 확인' in handler.body
    assert not (tmp_path / 'flight.sqlite').exists()


def test_browser_owner_selects_candidate_and_confirms_only_cost_assignment():
    from playwright.sync_api import sync_playwright

    proposal = match_booking_passengers(EVIDENCE, AUTHORITY)['passengers'][0]
    proposal['assignment'] = {'stale': True, 'candidate_reference_id': 'opaque-synth',
                              'candidate': {'name_kr': '김알파'}}
    requests = []
    document = page._page('csrf-synth')
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            browser_page = browser.new_page()
            browser_page.route('http://cost.test/flight-passengers', lambda route: route.fulfill(
                status=200, content_type='text/html; charset=utf-8', body=document))
            browser_page.route('**/api/flight-passengers/candidates*', lambda route: route.fulfill(
                status=200, content_type='application/json', body=json.dumps(
                    {'source_revision': AUTHORITY['source_revision'], 'passengers':[proposal]})))

            def assign(route):
                requests.append(json.loads(route.request.post_data))
                route.fulfill(status=200, content_type='application/json', body=json.dumps(
                    {'code':'OK', 'assignment':{'assignment_status':'USER_ASSIGNED',
                     'actual_boarding_confirmed':False}}))

            browser_page.route('**/api/flight-passengers/assign', assign)
            browser_page.goto('http://cost.test/flight-passengers')
            browser_page.locator('input[name=booking_ref]').fill('SYNTH-500')
            browser_page.locator('input[name=tour_id]').fill('tour-synth')
            browser_page.get_by_role('button', name='후보 조회').click()
            browser_page.get_by_text('김알파').wait_for()
            browser_page.get_by_text(
                '저장된 COST 연결이 있지만 예약 참가자 자료가 바뀌어 다시 확인해야 합니다.').wait_for()
            browser_page.locator('input[type=radio]').check()
            browser_page.get_by_role('button', name='선택한 COST 연결 저장').click()
            browser_page.get_by_text('실제 탑승 여부는 확인되지 않았습니다.').wait_for()
            assert requests == [{'booking_ref':'SYNTH-500', 'tour_id':'tour-synth',
                                 'proposal_id':proposal['proposal_id'],
                                 'candidate_reference_id':'opaque-synth'}]
        finally:
            browser.close()


def test_browser_displays_duplicate_passenger_candidates_without_choosing_for_owner():
    from playwright.sync_api import sync_playwright

    ambiguous_authority = {**AUTHORITY, 'candidates': [
        {'kind': 'lead', 'reference_id': 'opaque-lead-a', 'name_kr': '김알파',
         'name_en': 'KIM/ALPHA', 'status': 'confirmed'},
        {'kind': 'lead', 'reference_id': 'opaque-lead-b', 'name_kr': '김알파',
         'name_en': 'KIM/ALPHA', 'status': 'confirmed'},
    ]}
    proposal = match_booking_passengers(EVIDENCE, ambiguous_authority)['passengers'][0]
    document = page._page('csrf-synth')
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            browser_page = browser.new_page()
            browser_page.route('http://cost.test/flight-passengers', lambda route: route.fulfill(
                status=200, content_type='text/html; charset=utf-8', body=document))
            browser_page.route('**/api/flight-passengers/candidates*', lambda route: route.fulfill(
                status=200, content_type='application/json', body=json.dumps(
                    {'passengers': [proposal]})))
            browser_page.goto('http://cost.test/flight-passengers')
            browser_page.locator('input[name=booking_ref]').fill('SYNTH-500')
            browser_page.locator('input[name=tour_id]').fill('tour-synth')
            browser_page.get_by_role('button', name='후보 조회').click()
            browser_page.get_by_text('같은 영문 이름의 예약 참가자가 2명 있습니다.', exact=False).wait_for()
            labels = browser_page.locator('label').all_text_contents()
            assert any('예약자 후보 1 · 김알파' in label for label in labels)
            assert any('예약자 후보 2 · 김알파' in label for label in labels)
            assert browser_page.locator('input[type=radio]:checked').count() == 0
        finally:
            browser.close()


def test_post_persists_only_explicit_cost_assignment_idempotently(tmp_path):
    db_path = tmp_path / 'flight.sqlite'
    handler = Handler()
    proposal = match_booking_passengers(EVIDENCE, AUTHORITY)['passengers'][0]
    body = {'booking_ref': 'SYNTH-500', 'tour_id': 'tour-synth',
            'proposal_id': proposal['proposal_id'],
            'candidate_reference_id': 'opaque-synth'}
    with patch.dict(os.environ, {page.FEATURE_FLAG: '1', page.DB_ENV: str(db_path)}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500': EVIDENCE}):
        for _ in range(2):
            assert page.dispatch(handler, urlsplit('/api/flight-passengers/assign'),
                                 is_owner=True, board=object(), raw=json.dumps(body).encode(),
                                 csrf='csrf-synth', candidate_fetch=lambda _tour: AUTHORITY)
            assert handler.response[0] == 200
    assignment = handler.response[1]['assignment']
    assert assignment['assignment_status'] == 'USER_ASSIGNED'
    assert assignment['confirmed'] is True
    assert assignment['actual_boarding_confirmed'] is False
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute('SELECT COUNT(*) FROM flight_passenger_assignments').fetchone()[0] == 1
    finally:
        conn.close()
    with patch.dict(os.environ, {page.FEATURE_FLAG: '1', page.DB_ENV: str(db_path)}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500': EVIDENCE}):
        current = Handler()
        page.dispatch(current, urlsplit('/api/flight-passengers/candidates'), is_owner=True,
                      board=object(), query={'booking_ref': ['SYNTH-500'], 'tour_id': ['tour-synth']},
                      candidate_fetch=lambda _tour: AUTHORITY)
        saved = current.response[1]['passengers'][0]['assignment']
        assert saved['candidate_reference_id'] == 'opaque-synth'
        assert saved['stale'] is False
        changed = Handler()
        page.dispatch(changed, urlsplit('/api/flight-passengers/candidates'), is_owner=True,
                      board=object(), query={'booking_ref': ['SYNTH-500'], 'tour_id': ['tour-synth']},
                      candidate_fetch=lambda _tour: {**AUTHORITY, 'source_revision': 'roster-synth-v2'})
        assert changed.response[1]['passengers'][0]['assignment'] is None
        assert changed.response[1]['passengers'][0]['stale_assignments'][0]['stale'] is True


def test_assignment_refuses_non_owner_missing_csrf_and_stale_proposal(tmp_path):
    proposal = match_booking_passengers(EVIDENCE, AUTHORITY)['passengers'][0]
    body = json.dumps({'booking_ref': 'SYNTH-500', 'tour_id': 'tour-synth',
                       'proposal_id': proposal['proposal_id'],
                       'candidate_reference_id': 'opaque-synth'}).encode()
    with patch.dict(os.environ, {page.FEATURE_FLAG: '1', page.DB_ENV: str(tmp_path / 'flight.sqlite')}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500': EVIDENCE}):
        forbidden = Handler()
        page.dispatch(forbidden, urlsplit('/api/flight-passengers/candidates'), is_owner=False,
                      board=object(), query={'booking_ref': ['SYNTH-500'], 'tour_id': ['tour-synth']})
        assert forbidden.response[0] == 403
        no_csrf = Handler()
        no_csrf.headers = {'X-CSRF-Token': 'wrong'}
        page.dispatch(no_csrf, urlsplit('/api/flight-passengers/assign'), is_owner=True,
                      board=object(), raw=body, csrf='csrf-synth')
        assert no_csrf.response[0] == 403
        stale = Handler()
        page.dispatch(stale, urlsplit('/api/flight-passengers/assign'), is_owner=True,
                      board=object(), raw=body, csrf='csrf-synth',
                      candidate_fetch=lambda _tour: {**AUTHORITY, 'source_revision': 'roster-new'})
        assert stale.response[0] == 409
        assert stale.response[1]['code'] == 'PASSENGER_CANDIDATE_REQUIRED'
        assert not (tmp_path / 'flight.sqlite').exists()


def test_changed_evidence_keeps_old_assignment_stale_and_rejects_old_proposal(tmp_path):
    db_path = tmp_path / 'flight.sqlite'
    old = {**EVIDENCE, 'digest': 'digest-old'}
    changed = {**EVIDENCE, 'digest': 'digest-new',
               'passengers': [{'surname': 'KIM', 'given_name': 'BETA'}]}
    old_proposal = match_booking_passengers(old, AUTHORITY)['passengers'][0]
    payload = json.dumps({'booking_ref': 'SYNTH-500', 'tour_id': 'tour-synth',
                          'proposal_id': old_proposal['proposal_id'],
                          'candidate_reference_id': 'opaque-synth'}).encode()
    with patch.dict(os.environ, {page.FEATURE_FLAG: '1', page.DB_ENV: str(db_path)}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500': old}):
        saved = Handler()
        page.dispatch(saved, urlsplit('/api/flight-passengers/assign'), is_owner=True,
                      board=object(), raw=payload, csrf='csrf-synth', candidate_fetch=lambda _tour: AUTHORITY)
        assert saved.response[0] == 200
    with patch.dict(os.environ, {page.FEATURE_FLAG: '1', page.DB_ENV: str(db_path)}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500': changed}):
        current = Handler()
        page.dispatch(current, urlsplit('/api/flight-passengers/candidates'), is_owner=True,
                      board=object(), query={'booking_ref': ['SYNTH-500'], 'tour_id': ['tour-synth']},
                      candidate_fetch=lambda _tour: AUTHORITY)
        passenger = current.response[1]['passengers'][0]
        assert passenger['assignment'] is None
        assert len(passenger['stale_assignments']) == 1
        assert passenger['stale_assignments'][0]['evidence_digest'] == 'digest-old'
        assert passenger['confirmed'] is False
        rejected = Handler()
        page.dispatch(rejected, urlsplit('/api/flight-passengers/assign'), is_owner=True,
                      board=object(), raw=payload, csrf='csrf-synth', candidate_fetch=lambda _tour: AUTHORITY)
        assert rejected.response[0] == 409
