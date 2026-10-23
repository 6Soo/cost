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
