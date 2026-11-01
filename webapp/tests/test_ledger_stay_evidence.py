"""Synthetic OTA-to-ledger display coverage; no operating data is used."""
from copy import deepcopy
from types import SimpleNamespace
from threading import RLock
import sqlite3

import pytest

from webapp import ledger_design as design, ledger_stay_evidence as stays
from webapp.read_scope import scoped


@pytest.fixture
def context(monkeypatch):
    data = {
        'events': [dict(ota_event_id='e1', provider='agoda', booking_ref='B1',
                        item='숙박비', reservation_status='completed', source_digest='digest',
                        service_period={'starts_on': '2026-07-05', 'ends_on': '2026-07-07'})],
        'transactions': [dict(transaction_id='t1', source_hash='s1',
                              transaction_direction='purchase', amount_krw=1000)],
        'results': [dict(ota_event_id='e1', transaction_id='t1', status='MATCHED_AUTO')],
    }
    state = {'fresh': True}
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE board_manual_overrides(row_id TEXT, field TEXT)')
    calls = []
    def display_context():
        calls.append(1)
        return {'data': data}, state
    store = SimpleNamespace(conn=conn, _lock=RLock(),
                            _ota_snapshot_service=SimpleNamespace(display_context=display_context))
    monkeypatch.setattr(design.board, '_active_store', lambda: store)
    from webapp import ota_payment_review
    monkeypatch.setattr(ota_payment_review, 'enabled', lambda: True)
    yield store, data, state, calls
    conn.close()


def card(**values):
    return dict(row_id='card-t1', source_event_id='t1', item='숙박비', **values)


def test_existing_card_reads_linked_stay_without_writes_or_card_date_guess(context):
    store, data, _, calls = context
    before = deepcopy(data)
    row = card(occurred_on='2026-06-22', service_period='')
    changes = store.conn.total_changes
    @scoped
    def render():
        return design._stay_text(row), design._stay_text(row)
    assert render() == ('7월 5일(일) ~ 7월 7일(화) · 2박',) * 2
    assert calls == [1]
    assert store.conn.total_changes == changes
    assert data == before and row['service_period'] == ''


@pytest.mark.parametrize('override', ['2026-08-01~2026-08-02', 'invalid'])
def test_stored_dates_and_invalid_explicit_values_are_preserved(context, override):
    assert stays.period_for(card(service_period=override), stays.stay_index(context[0])) == override


def test_manual_empty_period_and_different_reservation_are_preserved(context):
    store = context[0]
    assert stays.period_for(card(reservation_no='OTHER'), stays.stay_index(store)) == ''
    store.conn.execute("INSERT INTO board_manual_overrides VALUES ('card-t1','service_period')")
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('flag', ['evidence_missing', 'evidence_changed', 'service_period_conflict'])
def test_changed_missing_and_conflicting_evidence_is_not_used(context, flag):
    store, data, _, _ = context
    data['events'][0][flag] = True
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('status', ['cancelled', 'refunded', 'refund_pending', 'evidence_pending'])
def test_cancelled_and_pending_reservations_are_not_used(context, status):
    store, data, _, _ = context
    data['events'][0]['reservation_status'] = status
    assert stays.stay_index(store) == {}


def test_stale_or_unstarted_service_is_not_used(context):
    store, _, state, _ = context
    state['fresh'] = False
    assert stays.stay_index(store) == {}
    del store._ota_snapshot_service
    assert stays.stay_index(store) == {}


def test_group_order_is_not_individual_booking_evidence(context):
    store, data, _, _ = context
    data['results'][0].update(allocation_basis='auto_stable_order', individual_payment_evidence=False)
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('flag', ['duplicate_of', 'parse_error', 'conflict_reason'])
def test_financial_source_protections_remain(context, flag):
    store, data, _, _ = context
    data['transactions'][0][flag] = 'blocked'
    assert stays.stay_index(store) == {}


def test_multiple_claims_and_refund_card_are_not_used(context):
    store, data, _, _ = context
    data['transactions'][0]['transaction_direction'] = 'refund'
    assert stays.stay_index(store) == {}
    data['transactions'][0]['transaction_direction'] = 'purchase'
    data['results'].append(dict(data['results'][0], ota_event_id='e2'))
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('period', [None, {}, {'starts_on': '2026-07-05'},
                                    {'starts_on': '2026-07-05', 'ends_on': None}])
def test_incomplete_stay_is_not_guessed_or_crashed(context, period):
    store, data, _, _ = context
    data['events'][0]['service_period'] = period
    assert stays.stay_index(store) == {}


@pytest.mark.parametrize('where', ['events', 'results'])
def test_alternate_period_conflict_is_protected(context, where):
    store, data, _, _ = context
    data[where][0]['period_conflict'] = True
    assert stays.stay_index(store) == {}
