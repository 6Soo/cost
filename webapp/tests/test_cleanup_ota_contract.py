"""중앙 대사와 지출 정리의 사용자 표시 계약. 모든 자료는 합성이다."""
import copy
from types import SimpleNamespace

import pytest

from webapp import card_flow, ledger_board, ota_catalog, ota_payment_review
from webapp.ledger_store import LedgerStore
from webapp.tests.test_expense_cleanup import card_rows


@pytest.fixture
def context(tmp_path, monkeypatch):
    board = LedgerStore(tmp_path / 'synthetic.sqlite', seed_demo=False)
    ledger_board.bind_store(board)
    flow, batch, rows = card_rows(board, 1)
    tid = rows[0]['transaction_id']
    board.conn.execute("UPDATE transactions SET merchant='Trip.com',merchant_normalized='TRIP.COM',"
                       "amount_krw=230191,classification_source='inference',item='숙박비' WHERE transaction_id=?", (tid,))
    board.conn.commit()
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
    monkeypatch.setattr(ota_catalog, '_index', lambda *a, **k: pytest.fail('예약 캐시를 결제 판단에 사용하면 안 된다'))
    monkeypatch.setattr(
        ota_payment_review.CoreOtaPaymentBackend, 'from_host',
        lambda *_args, **_kwargs: SimpleNamespace(
            store=SimpleNamespace(group_pins=lambda: []), close=lambda: None),
    )
    holder = {'current': {'generation': 17, 'results': [], 'data': {'events': [], 'results': []}},
              'state': {'enabled': True, 'status': 'ready', 'fresh': True, 'generation': 17}, 'reads': 0}

    def display_context():
        holder['reads'] += 1
        return holder['current'], holder['state']

    service = SimpleNamespace(display_context=display_context)
    monkeypatch.setattr(ota_payment_review, 'snapshot_service', lambda _board: service)
    try:
        yield board, flow, tid, holder
    finally:
        ledger_board.bind_store(None)
        board.close()


def candidates(holder, tid, count=1, *, group=False):
    events, results = [], []
    for i in range(count):
        event = {'ota_event_id': f'synthetic-{i}', 'provider': 'trip', 'booking_ref': f'SYNTHETIC-BOOKING-{i}',
                 'item': '숙박비', 'event_type': 'charge', 'paid_on': None}
        result = {'ota_event_id': event['ota_event_id'], 'status': 'HOLD_DATE_UNKNOWN',
                  'reason': 'payment_date_unknown', 'candidates': [tid],
                  'candidate_search': {'status': 'CANDIDATES_FOUND', 'date_status': 'UNKNOWN',
                                       'candidates': [{'transaction_id': tid, 'date_status': 'UNKNOWN'}]}}
        if group:
            result.update(status='MATCHED_AUTO', transaction_id=tid,
                          allocation_basis='auto_stable_order', individual_payment_evidence=False)
        events.append(event)
        results.append(result)
    holder['current'] = {'generation': 17, 'results': results,
                         'data': {'events': events, 'results': results}}


def test_candidate_in_central_result_is_visible_on_cleanup(context):
    board, flow, tid, holder = context
    candidates(holder, tid)
    markup = card_flow.render_expense_cleanup(board, 'csrf')
    assert 'SYNTHETIC-BOOKING-0' in markup
    assert '후보' in markup and ('결제일' in markup or '날짜' in markup)
    assert holder['reads'] == 1


def test_multiple_candidates_are_not_overwritten_or_silently_limited_to_two(context):
    board, flow, tid, holder = context
    candidates(holder, tid, 3)
    before = copy.deepcopy(holder['current'])
    markup = card_flow.render_expense_cleanup(board, 'csrf')
    for i in range(3):
        assert f'SYNTHETIC-BOOKING-{i}' in markup
    assert holder['current'] == before


def test_missing_payment_event_differs_from_multiple_candidates(context):
    board, flow, tid, holder = context
    board.conn.execute('UPDATE transactions SET amount_krw=690318 WHERE transaction_id=?', (tid,))
    missing = card_flow.render_expense_cleanup(board, 'csrf')
    candidates(holder, tid, 2)
    ambiguous = card_flow.render_expense_cleanup(board, 'csrf')
    assert 'SYNTHETIC-BOOKING' not in missing
    assert 'SYNTHETIC-BOOKING-0' in ambiguous and 'SYNTHETIC-BOOKING-1' in ambiguous
    assert missing != ambiguous


@pytest.mark.parametrize('state', ['refreshing', 'error'])
def test_unavailable_snapshot_does_not_claim_no_reservation(context, state):
    board, flow, tid, holder = context
    holder['current'] = None
    holder['state'] = {'enabled': True, 'fresh': False, 'status': state, 'generation': None}
    markup = card_flow.render_expense_cleanup(board, 'csrf')
    assert ('갱신' in markup if state == 'refreshing' else ('오류' in markup or '실패' in markup))
    assert '이 결제와 연결된 예약 자료가 현재 검토 목록에 없습니다.' not in markup


def test_stale_then_fresh_never_labels_old_exact_as_current(context):
    board, flow, tid, holder = context
    candidates(holder, tid)
    result = holder['current']['results'][0]
    result.update(status='MATCHED_AUTO', transaction_id=tid, candidate_search={})
    holder['state'].update(fresh=False, status='refreshing')
    stale = card_flow.render_expense_cleanup(board, 'csrf')
    assert '갱신' in stale and 'OTA 결제 확정 연결' not in stale
    holder['state'].update(fresh=True, status='ready')
    fresh = card_flow.render_expense_cleanup(board, 'csrf')
    assert '확정' in fresh


def test_group_correspondence_never_becomes_individual_exact(context):
    board, flow, tid, holder = context
    candidates(holder, tid, group=True)
    markup = card_flow.render_expense_cleanup(board, 'csrf')
    assert '그룹' in markup and '개별' in markup
    assert 'OTA 결제 확정 연결' not in markup


def test_cleanup_reads_change_no_card_decision_or_ledger_state(context):
    board, flow, tid, holder = context
    candidates(holder, tid, 2)
    holder['current']['links'] = {'synthetic-pin': tid}
    holder['current']['data']['links'] = {'synthetic-pin': {'transaction_id': tid, 'source_digest': 'original'}}
    original_snapshot = copy.deepcopy(holder['current'])
    tables = [r[0] for r in board.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    before = {t: board.conn.execute(f'SELECT * FROM "{t}"').fetchall() for t in tables}
    changes = board.conn.total_changes
    card_flow.render_expense_cleanup(board, 'csrf')
    assert board.conn.total_changes == changes
    assert holder['current'] == original_snapshot
    assert {t: board.conn.execute(f'SELECT * FROM "{t}"').fetchall() for t in tables} == before


def test_invalid_trip_is_explained_even_when_ota_is_exact(context, monkeypatch):
    board, flow, tid, holder = context
    trip = board.create_trip(starts_on='2026-09-20', ends_on='2026-09-27', destination='합성',
                             client_request_id='invalid-trip')
    board.conn.execute('UPDATE transactions SET display_tab_id=?,trip_id=? WHERE transaction_id=?',
                       (trip['tab_id'], trip['tab_id'], tid))
    board.conn.commit()
    monkeypatch.setattr(card_flow.CardFlow, 'trip_valid', lambda self, _trip: False)
    candidates(holder, tid)
    holder['current']['results'][0].update(status='MATCHED_AUTO', transaction_id=tid)
    markup = card_flow.render_expense_cleanup(board, 'csrf')
    assert '여행' in markup and ('권위' in markup or '유효하지' in markup or '일정 근거' in markup)
    assert '확정' in markup  # OTA 연결과 여행 검증은 서로 다른 축이다.


def test_valid_card_without_ota_can_still_prepare(context, monkeypatch):
    board, flow, tid, holder = context
    trip = board.create_trip(starts_on='2026-09-20', ends_on='2026-09-27', destination='합성',
                             client_request_id='valid-trip')
    board.conn.execute('UPDATE transactions SET display_tab_id=?,trip_id=? WHERE transaction_id=?',
                       (trip['tab_id'], trip['tab_id'], tid))
    board.conn.commit()
    monkeypatch.setattr(card_flow.CardFlow, 'trip_valid', lambda self, target: target == trip['tab_id'])
    markup = card_flow.render_expense_cleanup(board, 'csrf')
    assert '준비 가능' in markup
    assert board.conn.execute('SELECT COUNT(*) FROM ledger_entries').fetchone()[0] == 0


def test_snapshot_read_exception_is_input_error_not_no_booking(context, monkeypatch):
    board, flow, tid, holder = context
    def fail(_board):
        raise ValueError('private source text')
    monkeypatch.setattr(ota_payment_review, 'snapshot_service', fail)
    markup = card_flow.render_expense_cleanup(board, 'csrf')
    assert '오류' in markup and 'private source text' not in markup
    assert '예약 자료가 현재 검토 목록에 없습니다' not in markup


def test_cleanup_filters_legacy_other_provider_rejects_and_shows_actual_amounts(context):
    board, flow, tid, holder = context
    candidates(holder, tid)
    data = holder['current']['data']
    data['transactions'] = [{'transaction_id': tid, 'merchant': 'Trip.com Tokyo JP', 'amount_krw': 85621}]
    data['events'][0].update(amount='9737', currency='JPY', amount_krw=None)
    data['events'].append(dict(data['events'][0], ota_event_id='other', provider='agoda', booking_ref='UNRELATED-AGODA'))
    data['results'].append({'ota_event_id': 'other', 'status': 'HOLD_NO_CARD',
                            'candidate_search': {'rejected': [{'transaction_id': tid, 'reason': 'AMOUNT_MISMATCH'}]}})
    before = copy.deepcopy(holder['current'])
    changes = board.conn.total_changes
    markup = card_flow.render_expense_cleanup(board, 'csrf')
    assert 'UNRELATED-AGODA' not in markup
    assert '85,621원' in markup and '9,737 JPY' in markup
    assert holder['current'] == before and board.conn.total_changes == changes


def test_amount_mismatch_comparison_does_not_become_a_payment_candidate(context):
    board, flow, tid, holder = context
    candidates(holder, tid)
    data = holder['current']['data']
    data['events'][0].update(amount='100000', currency='KRW', amount_krw=100000)
    data['transactions'] = [{'transaction_id': tid, 'merchant': 'Trip.com', 'amount_krw': 85621}]
    data['results'][0].update(status='HOLD_AMOUNT_MISMATCH', reason='amount_differs',
                              candidate_search={'rejected': [{'transaction_id': tid, 'reason': 'AMOUNT_MISMATCH'}]})
    entries = card_flow._ota_entries_by_card(board)
    assert entries[tid]['ota_status'] == 'UNLINKED'
    assert all(' · 후보' not in note for note in entries[tid]['ota_notes'])
    assert all('100,000원' in note and '85,621원' in note for note in entries[tid]['ota_notes'])
