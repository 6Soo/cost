"""OTA booking trip assignments: the review store, classification precedence, the index, and the owner routes."""
import json
import sqlite3
from urllib.parse import urlsplit

import pytest

from app import classify
from app.normalize import normalize_merchant
from app.ota_review import BookingTripError, OtaReviewStore
from webapp import card_flow, ota_catalog, ota_payment_review
from webapp.ledger_store import LedgerStore
from webapp.tests.test_ota_catalog import source_database

VALID_TABS = {'trip-x'}


class FakeHandler:
    def __init__(self):
        self.status = None
        self.headers_sent = {}
        self.payload = None
        self.body = None

    def send_response(self, code):
        self.status = code

    def send_header(self, name, value):
        self.headers_sent[name] = value

    def end_headers(self):
        pass

    def _send_json(self, payload, code=200):
        self.status = code
        self.payload = payload

    def _send(self, body, code=200, content_type=None):
        self.status = code
        self.body = body if isinstance(body, str) else body.decode('utf-8')


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.delenv('WEBLEDGER_REVIEW_CONFIG', raising=False)
    review_db = tmp_path / 'ota-review.sqlite'
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_MODE', 'isolated')
    monkeypatch.setenv('WEBLEDGER_OTA_REVIEW_DB', str(review_db))
    board = LedgerStore(tmp_path / 'board.sqlite', seed_demo=False)
    portal = tmp_path / 'ota.sqlite'
    source_database(portal)
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(portal)
    conn.execute("INSERT INTO bookings VALUES (4,'agoda','BOOK-3','lodging','합성 호텔 셋','2026-10-31','2026-11-02','confirmed')")
    conn.commit()
    conn.close()
    monkeypatch.setenv('WEBLEDGER_OTA_SOURCES_JSON', json.dumps(
        {'portal_databases': [str(portal)], 'mail_directories': [], 'missing': []}))
    board.conn.execute("INSERT INTO trip_tabs(tab_id,display_key,starts_on,ends_on) VALUES "
                       "('trip-x','1101_합성','2026-10-30','2026-11-05')")
    board.conn.execute("INSERT INTO trip_tabs(tab_id,display_key,starts_on,ends_on) VALUES "
                       "('trip-y','1201_합성','2026-12-01','2026-12-05')")
    board.conn.commit()
    monkeypatch.setattr(card_flow.CardFlow, 'trip_valid',
                        lambda self, tab: tab in VALID_TABS)
    sources = {'portal_databases': [portal], 'mail_directories': [], 'missing': []}
    yield board, sources, review_db
    board.close()


def _rule(trip_id, origin='history-recovery-20261003', basis='과거 추론'):
    optional = {'source_hash': 'a' * 64, 'inferred_assignment': {'trip_id': trip_id, 'basis': basis, 'confidence': '낮음'}}
    return {'conditions': {'merchant_normalized': normalize_merchant('TRIP.COM'), 'transaction_direction': 'purchase'},
            'optional': optional, 'effects': {'item': '숙박비'}, 'origin': origin,
            'rule_id': origin + trip_id, 'note': ''}


def _transaction(trip_resolver_tab=None):
    return {'transaction_id': 't1', 'source_hash': 'a' * 64, 'merchant': 'TRIP.COM',
            'merchant_normalized': normalize_merchant('TRIP.COM'), 'transaction_direction': 'purchase',
            'card_kind': '해외', 'approval_date': '2026-11-02', 'posting_date': '2026-11-03',
            'amount_krw': 90000, 'raw_row': {}, 'description_raw': ''}


def test_store_assigns_revises_revokes_and_keeps_history(world):
    _, _, review_db = world
    store = OtaReviewStore(review_db)
    assert store.booking_trip_rules() == {}
    first = store.save_booking_trip(provider='trip', booking_ref='B1', trip_tab_id='trip-x', trip_code='1101_합성',
                                    basis='이용기간 일치', expected_revision=0, user='owner')
    assert first['revision'] == 1 and first['status'] == 'active'
    second = store.save_booking_trip(provider='trip', booking_ref='B1', trip_tab_id='trip-y', trip_code='1201_합성',
                                     basis='일정 변경', expected_revision=1, user='owner')
    assert second['revision'] == 2
    with pytest.raises(BookingTripError) as stale:
        store.save_booking_trip(provider='trip', booking_ref='B1', trip_tab_id='trip-x', trip_code='x',
                                basis='x', expected_revision=1, user='owner')
    assert stale.value.code == 'REVISION_CONFLICT'
    with pytest.raises(BookingTripError) as empty:
        store.save_booking_trip(provider='trip', booking_ref='B2', trip_tab_id='trip-x', trip_code='x',
                                basis=' ', expected_revision=0, user='owner')
    assert empty.value.code == 'BASIS_REQUIRED'
    revoked = store.revoke_booking_trip(provider='trip', booking_ref='B1', expected_revision=2, user='owner')
    assert revoked['status'] == 'revoked' and revoked['revision'] == 3
    assert store.booking_trip_rules() == {}
    assert store.booking_trip_rule('trip', 'B1')['status'] == 'revoked'
    history = store.booking_trip_history('trip', 'B1')
    assert [(h['revision'], h['status']) for h in history] == [(1, 'active'), (2, 'active'), (3, 'revoked')]
    with pytest.raises(BookingTripError) as nothing:
        store.revoke_booking_trip(provider='trip', booking_ref='B1', expected_revision=3, user='owner')
    assert nothing.value.code == 'NO_ACTIVE_RULE'
    store.close()


def test_owner_assignment_wins_over_an_automatic_suggestion_and_is_a_user_exception():
    owner = _rule('trip-x', origin=classify.OWNER_BOOKING_ORIGIN, basis='예약 배정 r1: 사용자 판단')
    automatic = _rule('trip-y')
    resolver = lambda transaction, country: country['inferred_trip_id'] if isinstance(country, dict) else ''
    verdict = classify.classify_transaction(_transaction(), rules=[automatic, owner], trip_resolver=resolver)
    assert verdict['classification_state'] == classify.STATE_CLASSIFIED
    assert verdict['trip_id'] == 'trip-x' and verdict['display_tab_id'] == 'trip-x'
    assert verdict['classification_source'] == 'owner_booking'
    assert '예약 배정 r1' in verdict['classification_basis']


def test_owner_trip_whose_schedule_cannot_be_verified_says_so():
    owner = _rule('trip-x', origin=classify.OWNER_BOOKING_ORIGIN, basis='예약 배정 r1: 사용자 판단')
    verdict = classify.classify_transaction(_transaction(), rules=[owner], trip_resolver=lambda *a: '')
    assert verdict['classification_state'] == classify.STATE_NEEDS_REVIEW
    assert '사용자가 고른 여행의 일정 원본' in verdict['classification_basis']


def test_index_is_reused_until_an_input_changes(world, monkeypatch):
    board, sources, _ = world
    builds = []
    original = ota_catalog._build_index
    monkeypatch.setattr(ota_catalog, '_build_index', lambda b, s: (builds.append(1), original(b, s))[1])
    ota_catalog._INDEX.update(key=None, value=None)
    ota_catalog.catalog(board, {}, sources=sources)
    ota_catalog.catalog(board, {'page': ['1'], 'q': ['BOOK']}, sources=sources)
    assert len(builds) == 1
    board.conn.execute("INSERT INTO trip_tabs(tab_id,display_key,starts_on,ends_on) VALUES "
                       "('trip-z','0101_합성','2027-01-01','2027-01-03')")
    board.conn.commit()
    ota_catalog.catalog(board, {}, sources=sources)
    assert len(builds) == 2


def test_prewarm_builds_the_index_so_the_first_visit_does_not_rebuild(world, monkeypatch):
    board, sources, _ = world
    builds = []
    original = ota_catalog._build_index
    monkeypatch.setattr(ota_catalog, '_build_index', lambda b, s: (builds.append(1), original(b, s))[1])
    monkeypatch.setattr(ota_catalog, 'configured_sources', lambda b: sources)
    ota_catalog._INDEX.update(key=None, value=None)
    ota_catalog.prewarm(board)
    assert len(builds) == 1
    ota_catalog.catalog(board, {}, sources=sources)
    assert len(builds) == 1


def test_detail_page_shows_the_judgment_and_refuses_bad_assignments(world, monkeypatch):
    board, sources, _ = world
    monkeypatch.setenv('WEBLEDGER_OTA_SOURCES_JSON', json.dumps(
        {'portal_databases': [str(sources['portal_databases'][0])], 'mail_directories': [], 'missing': []}))
    handler = FakeHandler()
    ota_catalog.dispatch(handler, urlsplit('/ota/booking?provider=agoda&ref=BOOK-1'), board=board,
                         is_owner=True, query={'provider': ['agoda'], 'ref': ['BOOK-1']}, csrf='tok')
    assert handler.status == 200 and 'BOOK-1' in handler.body and '판단' in handler.body
    assert 'name="expected_revision" value=\'0\'' in handler.body or "value='0'" in handler.body

    refused = FakeHandler()
    ota_catalog.dispatch(refused, urlsplit('/ota/booking'), board=board, is_owner=False,
                         query={'provider': ['agoda'], 'ref': ['BOOK-1']})
    assert refused.status == 404

    def post(form, owner=True, token='tok'):
        handler = FakeHandler()
        body = '&'.join(f'{k}={v}' for k, v in {**form, 'csrf': token}.items()).encode('utf-8')
        ota_catalog.dispatch_post(handler, urlsplit('/ota/booking/trip'), raw=body, csrf='tok',
                                  board=board, is_owner=owner)
        return handler

    not_csrf = post({'provider': 'agoda', 'booking_ref': 'BOOK-1', 'trip_tab_id': 'trip-x', 'basis': 'x',
                     'expected_revision': 0}, token='wrong')
    assert not_csrf.status == 303 and 'error=CSRF_REQUIRED' in not_csrf.headers_sent['Location']
    viewer = post({'provider': 'agoda', 'booking_ref': 'BOOK-1', 'trip_tab_id': 'trip-x', 'basis': 'x',
                   'expected_revision': 0}, owner=False)
    assert viewer.status == 404
    cancelled = post({'provider': 'agoda', 'booking_ref': 'BOOK-2', 'trip_tab_id': 'trip-x', 'basis': 'x',
                      'expected_revision': 0})
    assert 'error=BOOKING_CANCELLED' in cancelled.headers_sent['Location']
    linked_elsewhere = post({'provider': 'trip', 'booking_ref': 'BOOK-1', 'trip_tab_id': 'trip-x', 'basis': 'x',
                             'expected_revision': 0})
    assert 'error=NO_PERIOD' in linked_elsewhere.headers_sent['Location']


def test_saved_revised_and_revoked_assignment_round_trip(world, monkeypatch):
    board, sources, review_db = world
    ota_catalog._INDEX.update(key=None, value=None)

    def post(path, form):
        handler = FakeHandler()
        body = '&'.join(f'{k}={v}' for k, v in {**form, 'csrf': 'tok'}.items()).encode('utf-8')
        ota_catalog.dispatch_post(handler, urlsplit(path), raw=body, csrf='tok', board=board, is_owner=True)
        return handler

    saved = post('/ota/booking/trip', {'provider': 'agoda', 'booking_ref': 'BOOK-3', 'trip_tab_id': 'trip-x',
                                       'basis': '이용기간 일치', 'expected_revision': 0})
    assert 'notice=saved' in saved.headers_sent['Location']
    store = OtaReviewStore(review_db)
    assert store.booking_trip_rule('agoda', 'BOOK-3')['trip_tab_id'] == 'trip-x'
    store.close()
    assigned = ota_catalog.catalog(board, {'q': ['BOOK-3']}, sources=sources)['rows'][0]
    assert assigned['trips'][0]['source'] == 'rule' and assigned['rule']['revision'] == 1
    stale = post('/ota/booking/trip', {'provider': 'agoda', 'booking_ref': 'BOOK-3', 'trip_tab_id': 'trip-x',
                                       'basis': '다시', 'expected_revision': 0})
    assert 'error=REVISION_CONFLICT' in stale.headers_sent['Location']
    revoked = post('/ota/booking/revoke', {'provider': 'agoda', 'booking_ref': 'BOOK-3', 'expected_revision': 1})
    assert 'notice=revoked' in revoked.headers_sent['Location']
    store = OtaReviewStore(review_db)
    assert store.booking_trip_rule('agoda', 'BOOK-3')['status'] == 'revoked'
    store.close()
    listing = ota_catalog.catalog(board, {'state': ['unassigned']}, sources=sources)
    assert any(r['booking_ref'] == 'BOOK-3' for r in listing['rows'])


def test_unverified_trip_cannot_be_chosen(world, monkeypatch):
    board, sources, _ = world
    handler = FakeHandler()
    body = b'provider=agoda&booking_ref=BOOK-1&trip_tab_id=trip-y&basis=x&expected_revision=0&csrf=tok'
    ota_catalog.dispatch_post(handler, urlsplit('/ota/booking/trip'), raw=body, csrf='tok', board=board, is_owner=True)
    assert 'error=TRIP_NOT_CANDIDATE' in handler.headers_sent['Location'] or 'error=TRIP_NOT_VERIFIED' in handler.headers_sent['Location']


def test_checkout_on_the_trip_start_day_is_not_an_overlap_and_reasons_are_plain():
    trip = {'starts_on': '2026-08-27', 'ends_on': '2026-08-30'}
    assert ota_catalog._relation(('2026-08-26', '2026-08-27'), trip) == 'none'
    assert ota_catalog._relation(('2026-08-26', '2026-08-28'), trip) == 'overlaps'
    stay = {'trips': [], 'status_codes': ['observed'], 'stay': ('2026-08-27', '2026-08-28'), 'candidates': []}
    assert ota_catalog._unassigned_reason(stay, False) == 'not_confirmed'
    assert ota_catalog._unassigned_reason({**stay, 'status_codes': ['confirmed']}, False) == 'no_trip'


def test_revoking_a_stay_assignment_without_a_rule_is_recorded(tmp_path):
    store = OtaReviewStore(tmp_path / 'review.sqlite')
    result = store.revoke_booking_trip(provider='trip', booking_ref='B7', expected_revision=0, user='owner')
    assert result['status'] == 'revoked' and result['revision'] == 1
    assert store.booking_trip_states()[('trip', 'B7')]['status'] == 'revoked'
    store.close()


def test_a_confirmation_with_unknown_provider_joins_the_payment_with_the_same_number():
    rows = {
        ('unknown', 'R1'): {'labels': {'항공'}, 'periods': {('2026-08-01', '2026-08-06')}, 'statuses': {'confirmed'},
                            'portal_trips': set(), 'ledger_trips': set()},
        ('trip', 'R1'): {'labels': {'항공료'}, 'periods': set(), 'statuses': {'observed'},
                         'portal_trips': set(), 'ledger_trips': set()},
    }
    ota_catalog._join_by_booking_number(rows)
    assert list(rows) == [('trip', 'R1')]
    assert rows[('trip', 'R1')]['periods'] == {('2026-08-01', '2026-08-06')}
    assert rows[('trip', 'R1')]['statuses'] == {'confirmed', 'observed'}


def test_a_saved_index_made_by_other_logic_is_not_reused(world, monkeypatch):
    board, sources, _ = world
    before = ota_catalog._signature(board, sources)
    monkeypatch.setattr(ota_catalog, '_code_stamp', lambda: 'other-logic')
    assert ota_catalog._signature(board, sources) != before


def test_an_unverified_trip_covering_the_stay_does_not_block_the_one_verified_trip():
    candidates = [{'tab_id': 'a', 'name': 'A', 'relation': 'covers', 'valid': False},
                  {'tab_id': 'b', 'name': 'B', 'relation': 'covers', 'valid': True},
                  {'tab_id': 'c', 'name': 'C', 'relation': 'overlaps', 'valid': True}]
    assert ota_catalog._period_trip(candidates) == {'id': 'b', 'name': 'B', 'source': 'period'}
    assert ota_catalog._period_trip(candidates + [{'tab_id': 'd', 'name': 'D', 'relation': 'covers', 'valid': True}]) is None
