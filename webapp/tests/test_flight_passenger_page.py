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


def test_candidate_lookup_uses_existing_host_token_without_exposing_it(tmp_path):
    from types import SimpleNamespace
    board = SimpleNamespace(path=tmp_path/'data'/'board.sqlite')
    secrets = tmp_path/'secrets'
    secrets.mkdir()
    (secrets/'reservation-internal-token.txt').write_text('synthetic-private-token', encoding='utf-8')
    with patch.dict(os.environ, clear=True), \
            patch.object(page, '_passenger_evidence', return_value=EVIDENCE), \
            patch.object(page.reservation_authority, 'fetch_passenger_candidates', return_value=AUTHORITY) as fetch:
        result = page._candidate_result(board, 'SYNTH-500', 'tour-synth')
    fetch.assert_called_once_with('tour-synth', token='synthetic-private-token')
    assert result['passengers'][0]['status'] == 'EXACT_CANDIDATE'
    assert 'synthetic-private-token' not in json.dumps(result)
    assert not (tmp_path/'data'/'flight-passenger.sqlite').exists()


def test_published_index_keeps_verified_evidence_for_lookup_and_rejects_stale_snapshot(tmp_path):
    from types import SimpleNamespace
    from webapp import ota_payment_review
    evidence = dict(EVIDENCE, digest='content-synth', legs=[], cancellation_status='NONE',
                    raw_message='must-not-be-exposed')
    with patch('app.flight_evidence.collect_flight_evidence', return_value={('trip','SYNTH-500'):evidence}):
        index = ota_payment_review._passenger_index([])
    assert index['SYNTH-500']['source_digests'] == EVIDENCE['source_digests']
    assert index['SYNTH-500']['names'] == ['KIM ALPHA']
    assert 'raw_message' not in index['SYNTH-500']
    current = {'data':{'passengers':index}}
    handler = Handler()
    with patch.dict(os.environ, {page.FEATURE_FLAG:'1',page.DB_ENV:str(tmp_path/'flight.sqlite')}), \
            patch.object(ota_payment_review, 'snapshot_service', return_value=SimpleNamespace(held=lambda:(current,True))):
        page.dispatch(handler, urlsplit('/api/flight-passengers/candidates'), is_owner=True,
                      board=object(), query={'booking_ref':['SYNTH-500'],'tour_id':['tour-synth']},
                      candidate_fetch=lambda tour:AUTHORITY)
        assert handler.response[0] == 200
        assert handler.response[1]['passengers'][0]['status'] == 'EXACT_CANDIDATE'
    with patch.dict(os.environ, {page.FEATURE_FLAG:'1',page.DB_ENV:str(tmp_path/'flight.sqlite')}), \
            patch.object(ota_payment_review, 'snapshot_service', return_value=SimpleNamespace(held=lambda:(current,False))), \
            patch.object(page.reservation_authority, 'fetch_passenger_candidates') as fetch:
        page.dispatch(handler, urlsplit('/api/flight-passengers/candidates'), is_owner=True,
                      board=object(), query={'booking_ref':['SYNTH-500'],'tour_id':['tour-synth']})
        assert handler.response[0] == 404
        fetch.assert_not_called()
    assert not (tmp_path/'flight.sqlite').exists()


def test_owner_page_exposes_candidate_search_and_explicit_cost_confirmation_only(tmp_path):
    handler = Handler()
    with patch.dict(os.environ, {page.FEATURE_FLAG: '1', page.DB_ENV: str(tmp_path / 'flight.sqlite')}):
        handled = page.dispatch(handler, urlsplit('/flight-passengers'), is_owner=True,
                                board=object(), csrf='csrf-synth')
    assert handled is True
    assert '연결 후보 찾기' in handler.body
    assert '/api/flight-passengers/candidates' in handler.body
    assert '/api/flight-passengers/assign' in handler.body
    assert '실제 탑승 여부' in handler.body
    assert not (tmp_path / 'flight.sqlite').exists()


def test_handler_wraps_flight_page_with_shared_navigation():
    from io import BytesIO
    from types import SimpleNamespace
    from webapp import ledger_board

    response = SimpleNamespace(path='/flight-passengers', headers={}, wfile=BytesIO())
    response.send_response = lambda code: None
    response.send_header = lambda name, value: None
    response.end_headers = lambda: None
    with patch.object(ledger_board, 'ACCESS_ENFORCEMENT', False):
        ledger_board.Handler._send(response, page._page('csrf-synth'))
    rendered = response.wfile.getvalue().decode('utf-8')
    assert rendered.count("id='nav'") == 1
    assert rendered.count('id="site-content"') == 1
    assert rendered.count('class="site-menu-toggle"') == 1
    assert rendered.count('<main id=\'flight-passenger-page\'>') == 1
    assert '<head>' in rendered and '<body class="site-standalone">' in rendered
    assert '</body></html>' in rendered
    assert '#flight-passenger-page form' in rendered
    assert "id='nav'" in rendered and "class='site-links'" in rendered


def test_browser_wrapped_flight_page_responsive_theme_and_zoom():
    from webapp import site_shell
    from playwright.sync_api import sync_playwright

    with patch('webapp.ledger_design.nav_region', return_value=''):
        document = site_shell.wrap_document(page._page('csrf-synth'), '/flight-passengers')

    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        try:
            browser_page = browser.new_page(viewport={'width': 375, 'height': 812},
                                            color_scheme='dark')
            browser_page.set_content(document)
            for width in (375, 390, 759, 760, 1280):
                browser_page.set_viewport_size({'width': width, 'height': 812})
                assert browser_page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert browser_page.locator('#nav').count() == 1
                assert browser_page.get_by_role('heading', name='항공권 참가자 연결').is_visible()
            dark = browser_page.locator('#nav').evaluate('(el)=>getComputedStyle(el).backgroundColor')
            browser_page.emulate_media(color_scheme='light')
            light = browser_page.locator('#nav').evaluate('(el)=>getComputedStyle(el).backgroundColor')
            assert dark != light

            browser_page.set_viewport_size({'width': 640, 'height': 812})
            browser_page.evaluate('document.documentElement.style.zoom="200%"')
            assert browser_page.locator('#nav').count() == 1
            assert browser_page.get_by_role('heading', name='항공권 참가자 연결').is_visible()
        finally:
            browser.close()


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
            browser_page.get_by_role('button', name='연결 후보 찾기').click()
            browser_page.get_by_text('김알파').wait_for()
            browser_page.get_by_text(
                '이전 연결의 근거가 변경됐습니다. 최신 자료를 확인하고 다시 선택해 주세요.').wait_for()
            browser_page.locator('input[type=radio]').check()
            browser_page.get_by_role('button', name='선택한 참가자를 COST에 연결').click()
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
            browser_page.get_by_role('button', name='연결 후보 찾기').click()
            browser_page.get_by_text('같은 영문 이름의 후보가 2명입니다.', exact=False).wait_for()
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
        assert changed.response[1]['stale_assignments'][0]['stale'] is True


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
        assert len(current.response[1]['stale_assignments']) == 1
        assert current.response[1]['stale_assignments'][0]['evidence_digest'] == 'digest-old'
        assert passenger['confirmed'] is False
        rejected = Handler()
        page.dispatch(rejected, urlsplit('/api/flight-passengers/assign'), is_owner=True,
                      board=object(), raw=payload, csrf='csrf-synth', candidate_fetch=lambda _tour: AUTHORITY)
        assert rejected.response[0] == 409


def test_cancelled_post_is_rejected_without_database_row_and_stale_history_is_booking_level(tmp_path):
    db_path = tmp_path / 'flight.sqlite'
    cancelled = {**EVIDENCE, 'digest': 'cancel-digest', 'cancellation_status': 'CANCELLED'}
    repeated = {**EVIDENCE, 'passengers': [dict(EVIDENCE['passengers'][0]), dict(EVIDENCE['passengers'][0])]}
    proposals = match_booking_passengers(repeated, AUTHORITY)['passengers']
    old = match_booking_passengers(EVIDENCE, AUTHORITY)['passengers'][0]
    payload = json.dumps({'booking_ref':'SYNTH-500', 'tour_id':'tour-synth',
                          'proposal_id':old['proposal_id'], 'candidate_reference_id':'opaque-synth'}).encode()
    with patch.dict(os.environ, {page.FEATURE_FLAG:'1', page.DB_ENV:str(db_path)}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500':cancelled}):
        rejected = Handler()
        page.dispatch(rejected, urlsplit('/api/flight-passengers/assign'), is_owner=True,
                      board=object(), raw=payload, csrf='csrf-synth', candidate_fetch=lambda _tour:AUTHORITY)
        assert rejected.response[0] == 409
        assert rejected.response[1]['code'] == 'PASSENGER_CANDIDATE_REQUIRED'
    conn = sqlite3.connect(db_path)
    try:
        table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='flight_passenger_assignments'").fetchone()
        assert table is None or conn.execute('SELECT COUNT(*) FROM flight_passenger_assignments').fetchone()[0] == 0
    finally:
        conn.close()
    # Persist an old association, then expose a passenger-less current proposal set.
    with patch.dict(os.environ, {page.FEATURE_FLAG:'1', page.DB_ENV:str(db_path)}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500':EVIDENCE}):
        page.dispatch(Handler(), urlsplit('/api/flight-passengers/assign'), is_owner=True,
                      board=object(), raw=json.dumps({'booking_ref':'SYNTH-500','tour_id':'tour-synth',
                      'proposal_id':old['proposal_id'],'candidate_reference_id':'opaque-synth'}).encode(),
                      csrf='csrf-synth', candidate_fetch=lambda _tour:AUTHORITY)
    empty = {**repeated, 'digest':'now-empty', 'passengers':[]}
    with patch.dict(os.environ, {page.FEATURE_FLAG:'1', page.DB_ENV:str(db_path)}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500':empty}):
        current=Handler()
        page.dispatch(current,urlsplit('/api/flight-passengers/candidates'),is_owner=True,board=object(),
                      query={'booking_ref':['SYNTH-500'],'tour_id':['tour-synth']},candidate_fetch=lambda _tour:AUTHORITY)
        assert len(current.response[1]['stale_assignments']) == 1
        assert current.response[1]['passengers'] == []
        assert current.response[1]['cancellation_status'] == 'NONE'
        assert current.response[1]['evidence_conflict'] is False
    cancelled_empty = {**empty, 'cancellation_status':'CANCELLED'}
    with patch.dict(os.environ, {page.FEATURE_FLAG:'1', page.DB_ENV:str(db_path)}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500':cancelled_empty}):
        current_cancelled=Handler()
        page.dispatch(current_cancelled,urlsplit('/api/flight-passengers/candidates'),is_owner=True,board=object(),
                      query={'booking_ref':['SYNTH-500'],'tour_id':['tour-synth']},candidate_fetch=lambda _tour:AUTHORITY)
        assert current_cancelled.response[1]['cancellation_status'] == 'CANCELLED'
        assert current_cancelled.response[1]['passengers'] == []
    assert proposals[0]['proposal_id'] != proposals[1]['proposal_id']
    duplicate_db = tmp_path / 'duplicate.sqlite'
    paired = {**EVIDENCE, 'passengers': [dict(EVIDENCE['passengers'][0]), dict(EVIDENCE['passengers'][0])]}
    first_proposal = match_booking_passengers(paired, AUTHORITY)['passengers'][0]
    with patch.dict(os.environ, {page.FEATURE_FLAG:'1', page.DB_ENV:str(duplicate_db)}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500':paired}):
        saved = Handler()
        page.dispatch(saved, urlsplit('/api/flight-passengers/assign'), is_owner=True, board=object(),
                      raw=json.dumps({'booking_ref':'SYNTH-500','tour_id':'tour-synth',
                      'proposal_id':first_proposal['proposal_id'],'candidate_reference_id':'opaque-synth'}).encode(),
                      csrf='csrf-synth', candidate_fetch=lambda _tour:AUTHORITY)
        assert saved.response[0] == 200
    with patch.dict(os.environ, {page.FEATURE_FLAG:'1', page.DB_ENV:str(duplicate_db)}), \
            patch('webapp.ota_payment_review.passenger_index_for', return_value={'SYNTH-500':paired}):
        fetched = Handler()
        page.dispatch(fetched, urlsplit('/api/flight-passengers/candidates'), is_owner=True, board=object(),
                      query={'booking_ref':['SYNTH-500'],'tour_id':['tour-synth']}, candidate_fetch=lambda _tour:AUTHORITY)
        assert fetched.response[1]['passengers'][0]['assignment'] is not None
        assert fetched.response[1]['passengers'][1]['assignment'] is None
    conn=sqlite3.connect(duplicate_db)
    try:
        assert conn.execute('SELECT COUNT(*) FROM flight_passenger_assignments').fetchone()[0] == 1
    finally:
        conn.close()
    conn=sqlite3.connect(db_path)
    try:
        assert conn.execute('SELECT COUNT(*) FROM flight_passenger_assignments').fetchone()[0] == 1
    finally:
        conn.close()
