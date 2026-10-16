"""포털 자동결제 예정일이 카드 이용일과 같을 때만 예약을 결제로 연결하는 규칙을 합성 자료로 검증한다."""
import hashlib
import json
import sqlite3

import pytest

from app import ota_exact, ota_portal
from app.ota_portal import scheduled_card_date_matches
from webapp import ota_payment_review

ROLES = ('identity', 'service_period', 'portal_payment_claim', 'portal_card_observation', 'lifecycle')
PROGRESSION = [{'field': 'status', 'existing': 'upcoming', 'incoming': 'confirmed'}]
SCHEDULED = dict(
    provider='agoda', booking_number='synthetic-scheduled', status='confirmed', reservation_status='확정',
    service_start_on='2026-10-05', service_end_on='2026-10-08', card_last4='8835', card_type='MasterCard',
    collection_model='agoda_collect_card_auto_charge', payment_status='future_due:auto_charge_scheduled_2026-09-30',
    portal_payment_state='none', refund_status='none_displayed',
    price_components=[
        dict(kind='base', currency='KRW', decimal_text='186354', minor_units=186354, scale=0),
        dict(kind='taxes_and_fees', currency='KRW', decimal_text='39144', minor_units=39144, scale=0),
        dict(kind='gross_total', currency='KRW', decimal_text='225498', minor_units=225498, scale=0)])


def portal_database(path, facts):
    """facts: (payload changes, conflicts) 목록. 예약마다 하나의 캡처 기록을 만든다."""
    with sqlite3.connect(path) as conn:
        conn.executescript('''
            CREATE TABLE bookings(id TEXT,provider TEXT,booking_number TEXT,service_start_on TEXT,service_end_on TEXT,status TEXT);
            CREATE TABLE direct_source_records(id TEXT,source_kind TEXT,payload_json TEXT,source_sha256 TEXT);
            CREATE TABLE booking_source_evidence(booking_id TEXT,direct_source_record_id TEXT,evidence_role TEXT,
                evidence_status TEXT,conflict_count INTEGER,conflict_json TEXT);
        ''')
        for index, (changes, conflicts) in enumerate(facts):
            payload = dict(SCHEDULED, **changes)
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            conn.execute('INSERT INTO bookings VALUES (?,?,?,?,?,?)',
                         (str(index), 'agoda', payload['booking_number'], payload['service_start_on'],
                          payload['service_end_on'], 'upcoming'))
            conn.execute('INSERT INTO direct_source_records VALUES (?,?,?,?)',
                         (str(index), 'agoda_portal_detail', raw, hashlib.sha256(raw.encode()).hexdigest()))
            conn.executemany('INSERT INTO booking_source_evidence VALUES (?,?,?,?,?,?)',
                             [(str(index), str(index), role, 'observed', len(conflicts),
                               json.dumps(conflicts, ensure_ascii=False)) for role in ROLES])
    return path


def card(**changes):
    return dict(dict(transaction_id='scheduled-card', source_hash='c' * 64, merchant='AGODA_NICE-Agoda',
                     merchant_normalized='agoda_nice-agoda', card_kind='국내', approval_date='2026-09-30',
                     transaction_direction='purchase', amount_krw=225498, card_tail='8835',
                     foreign_amount=None, foreign_currency='', duplicate_of=None, parse_error=None,
                     conflict_reason=None), **changes)


def gate(matches, rows):
    report = {'matches': list(matches)}
    return ota_exact.apply_gate(report, rows, events=[], rules=[], open_ids={row['transaction_id'] for row in rows})


def test_a_card_row_on_the_scheduled_day_with_the_same_amount_and_card_is_linked(tmp_path):
    path = portal_database(tmp_path / 'portal.sqlite', [({}, [])])
    matches = scheduled_card_date_matches(path, [card()])
    assert len(matches) == 1
    assert matches[0]['booking_ref'] == 'synthetic-scheduled'
    assert matches[0]['period'] == {'starts_on': '2026-10-05', 'ends_on': '2026-10-08'}
    assert matches[0]['evidence_kind'] == ota_portal.SCHEDULED_CARD_DATE_EVIDENCE
    kept = gate(matches, [card()])
    assert kept['exact_matches'] == 1 and kept['evidence_gate']['dropped'] == []


@pytest.mark.parametrize('changes', [
    {'approval_date': '2026-09-29'}, {'approval_date': '2026-10-01'}, {'amount_krw': 225497},
    {'card_tail': '9999'}, {'merchant': 'BOOKING.COM HOTEL', 'merchant_normalized': 'booking.com hotel'},
    {'transaction_direction': 'refund'}, {'duplicate_of': 'other'},
])
def test_a_card_row_that_does_not_match_the_scheduled_day_amount_or_card_is_not_linked(tmp_path, changes):
    path = portal_database(tmp_path / 'portal.sqlite', [({}, [])])
    assert scheduled_card_date_matches(path, [card(**changes)]) == []


@pytest.mark.parametrize('changes', [
    {'reservation_status': 'cancelled'}, {'refund_status': 'refund_completed'},
    {'price_components': [dict(kind='gross_total', currency='KRW', decimal_text='225498', minor_units=225498, scale=0)],
     'payment_status': 'paid'},
    {'collection_model': 'agoda_collect'}, {'card_last4': '12'},
    {'service_start_on': '2026-10-09'},
])
def test_cancelled_paid_or_unclear_bookings_are_not_linked_by_the_scheduled_rule(tmp_path, changes):
    path = portal_database(tmp_path / 'portal.sqlite', [(changes, [])])
    assert scheduled_card_date_matches(path, [card()]) == []


def test_the_upcoming_to_confirmed_status_step_is_the_only_conflict_allowed(tmp_path):
    progressed = portal_database(tmp_path / 'progressed.sqlite', [({}, PROGRESSION)])
    assert len(scheduled_card_date_matches(progressed, [card()])) == 1
    other = [{'field': 'amount', 'existing': '225498', 'incoming': '226000'}]
    blocked = portal_database(tmp_path / 'blocked.sqlite', [({}, other)])
    assert scheduled_card_date_matches(blocked, [card()]) == []
    mixed = portal_database(tmp_path / 'mixed.sqlite', [({}, PROGRESSION + other)])
    assert scheduled_card_date_matches(mixed, [card()]) == []


def test_a_price_breakdown_that_does_not_add_up_is_not_linked(tmp_path):
    broken = [dict(kind='base', currency='KRW', decimal_text='186000', minor_units=186000, scale=0),
              dict(kind='taxes_and_fees', currency='KRW', decimal_text='39144', minor_units=39144, scale=0),
              dict(kind='gross_total', currency='KRW', decimal_text='225498', minor_units=225498, scale=0)]
    path = portal_database(tmp_path / 'portal.sqlite', [({'price_components': broken}, [])])
    assert scheduled_card_date_matches(path, [card()]) == []


def test_two_identical_card_rows_on_the_same_day_are_not_guessed(tmp_path):
    path = portal_database(tmp_path / 'portal.sqlite', [({}, [])])
    rows = [card(transaction_id='first', source_hash='d' * 64), card(transaction_id='second', source_hash='e' * 64)]
    assert scheduled_card_date_matches(path, rows) == []


def test_the_gate_drops_the_link_when_the_card_row_moves_to_another_day(tmp_path):
    path = portal_database(tmp_path / 'portal.sqlite', [({}, [])])
    matches = scheduled_card_date_matches(path, [card()])
    moved = card(approval_date='2026-09-29')
    kept = gate(matches, [moved])
    assert kept['matches'] == []
    assert kept['unmatched_transactions'][0]['reason'] == 'date'


def test_the_rule_can_be_switched_off(tmp_path, monkeypatch):
    path = portal_database(tmp_path / 'portal.sqlite', [({}, [])])
    monkeypatch.setattr(ota_portal, 'scheduled_card_date_enabled', lambda: False)
    assert scheduled_card_date_matches(path, [card()]) == []


def test_the_shipped_defaults_turn_the_rule_on():
    from app.ota_matching_defaults import load_defaults
    assert load_defaults()['portal_scheduled_card_date_enabled'] is True
    assert ota_portal.scheduled_card_date_enabled() is True


def test_the_worker_settles_the_scheduled_row_unless_another_result_already_holds_it(tmp_path):
    sources = {'portal_databases': [str(portal_database(tmp_path / 'portal.sqlite', [({}, [])]))]}
    assert ota_payment_review.scheduled_card_settlements(sources, [card()], occupied=set()) == ['scheduled-card']
    assert ota_payment_review.scheduled_card_settlements(sources, [card()], occupied={'scheduled-card'}) == []
