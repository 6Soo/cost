"""기존 OTA 대사 결과는 코어의 정확 매칭 규칙을 통과해야 새로 자동 배정된다. 기록된 거래는 건드리지 않는다."""
import sqlite3
from decimal import Decimal

from app import ota_exact, ota_payments


def charge(**changes):
    base = dict(ota_event_id='e1', provider='agoda', booking_ref='B1', event_type='charge', evidence_status='paid_verified',
                payment_status='paid', item='숙박비', currency='KRW', amount_krw=48000, amount=Decimal('48000'),
                paid_on='2026-05-01', card_last4='8835')
    base.update(changes)
    return base


def row(tid='t1', **changes):
    base = dict(transaction_id=tid, source_hash=tid * 4, merchant='AGODA_NICE-Agoda', merchant_normalized='agoda',
                transaction_direction='purchase', approval_date='2026-05-01', amount_krw=48000, card_tail='8835',
                foreign_currency='', foreign_amount='', duplicate_of='', parse_error='', conflict_reason='')
    base.update(changes)
    return base


def test_pair_passes_with_card_hint_exact_amount_and_same_day():
    assert ota_payments.pair_check(charge(), row()) is None


def test_portal_style_payment_without_a_payment_date_is_not_paired():
    assert ota_payments.pair_check(charge(paid_on=None), row()) == 'payment_date_unknown'


def test_card_hint_must_equal_the_card_tail():
    assert ota_payments.pair_check(charge(), row(card_tail='3820')) == 'card_identity'


def test_krw_amount_and_day_must_be_exact():
    assert ota_payments.pair_check(charge(), row(amount_krw=48001)) == 'amount'
    assert ota_payments.pair_check(charge(), row(approval_date='2026-05-02')) == 'date'


def test_booking_without_card_hint_needs_an_approved_merchant_alias():
    booking = charge(provider='booking', card_last4=None, booking_ref='B2')
    booking_row = row(merchant='BKG*BOOKING.COM HOTEL', merchant_normalized='booking')
    assert ota_payments.pair_check(booking, booking_row) == 'corroboration'


def test_trip_without_card_hint_pairs_on_exact_amount_day_and_uniqueness_rules():
    trip = charge(provider='trip', card_last4=None)
    assert ota_payments.pair_check(trip, row(merchant='임의 가맹점')) is None


def test_foreign_currency_must_match_exactly_and_allows_only_the_approved_one_day_gap():
    foreign = charge(provider='trip', card_last4=None, currency='JPY', amount=Decimal('34625'), amount_krw=None)
    foreign_row = row(merchant='임의 가맹점', amount_krw=150000, foreign_currency='JPY', foreign_amount='34625')
    assert ota_payments.pair_check(foreign, foreign_row) is None
    assert ota_payments.pair_check(foreign, dict(foreign_row, approval_date='2026-04-30')) is None
    assert ota_payments.pair_check(foreign, dict(foreign_row, approval_date='2026-04-29')) == 'date'
    krw_day = charge(provider='trip', card_last4=None, paid_on='2026-05-01')
    assert ota_payments.pair_check(krw_day, row(merchant='임의 가맹점', approval_date='2026-04-30')) == 'date'


def gate_report(*matches, rules=(), unmatched=(), types=(), diagnoses=()):
    return dict(matches=list(matches), rules=[dict(optional={'source_hash': m['source_hash']}) for m in matches] + list(rules),
                type_only_candidates=list(types), unmatched_transactions=list(unmatched),
                portal_diagnoses=list(diagnoses))


def test_open_row_without_core_proof_loses_its_match_and_rule_and_gets_a_reason():
    match = dict(transaction_id='t1', source_hash='h' * 64, provider='agoda', booking_ref='B1', item='숙박비')
    report = gate_report(match, diagnoses=[dict(source_hash='h' * 64, reason='no_exact_payment_evidence')])
    event = charge(paid_on=None)
    result = ota_exact.apply_gate(report, [row()], events=[event], rules=[], open_ids={'t1'})
    assert result['matches'] == [] and result['rules'] == []
    assert result['unmatched_transactions'][0]['reason'] == 'payment_date_unknown'
    assert result['portal_diagnoses'][0]['reason'] == 'payment_date_unknown'
    assert result['evidence_gate']['checked'] == 1


def test_recorded_or_protected_rows_keep_their_match_even_when_the_core_would_refuse_it():
    match = dict(transaction_id='t2', source_hash='h' * 64, provider='agoda', booking_ref='B1', item='숙박비')
    report = gate_report(match)
    result = ota_exact.apply_gate(report, [row('t2')], events=[charge(paid_on=None)], rules=[], open_ids={'t1'})
    assert result['matches'] == [match]
    assert len(result['rules']) == 1


def test_a_passing_open_row_keeps_its_match():
    match = dict(transaction_id='t1', source_hash='h' * 64, provider='agoda', booking_ref='B1', item='숙박비')
    result = ota_exact.apply_gate(gate_report(match), [row()], events=[charge()], rules=[], open_ids={'t1'})
    assert result['matches'] == [match]


def test_unreadable_ota_evidence_refuses_open_rows_instead_of_passing_them():
    match = dict(transaction_id='t1', source_hash='h' * 64, provider='agoda', booking_ref='B1', item='숙박비')
    result = ota_exact.apply_gate(gate_report(match), [row()], events=None, rules=[], open_ids={'t1'})
    assert result['matches'] == []
    assert result['unmatched_transactions'][0]['reason'] == 'evidence_unavailable'


def test_shared_period_group_without_an_alias_does_not_assign_a_trip_for_agoda_or_booking():
    agoda_group = dict(transaction_id='t1', source_hash='a' * 64, provider='agoda', item='숙박비',
                       shared_period=dict(starts_on='2026-07-22', ends_on='2026-07-25'))
    trip_group = dict(transaction_id='t2', source_hash='b' * 64, item='숙박비',
                      shared_period=dict(starts_on='2026-07-22', ends_on='2026-07-25'))
    report = gate_report(types=[agoda_group, trip_group])
    other = dict(merchant='임의 가맹점', merchant_normalized='임의 가맹점')
    result = ota_exact.apply_gate(report, [row(**other), row('t2', **other)], events=[charge()],
                                  rules=[], open_ids={'t1', 't2'})
    assert [item['transaction_id'] for item in result['type_only_candidates']] == ['t2']
    assert all(rule['optional']['source_hash'] != 'a' * 64 for rule in result['rules'])


def test_gate_can_be_switched_off_for_rollback(monkeypatch):
    monkeypatch.setenv(ota_exact.ENV, '0')
    match = dict(transaction_id='t1', source_hash='h' * 64, provider='agoda', booking_ref='B1', item='숙박비')
    result = ota_exact.apply_gate(gate_report(match), [row()], events=[charge(paid_on=None)], rules=[], open_ids={'t1'})
    assert result['matches'] == [match]


def test_open_ids_exclude_recorded_preserved_and_user_decided_rows():
    conn = sqlite3.connect(':memory:')
    conn.executescript("""
        CREATE TABLE transactions(transaction_id TEXT, classification_state TEXT, classification_source TEXT);
        CREATE TABLE board_rows(row_id TEXT, row_kind TEXT);
        INSERT INTO transactions VALUES ('t1','classified','rule');
        INSERT INTO transactions VALUES ('t2','classified','rule');
        INSERT INTO transactions VALUES ('t3','preserved','user_completed_period');
        INSERT INTO transactions VALUES ('t4','classified','user_decision');
        INSERT INTO transactions VALUES ('t5','needs_review','booking_evidence_needed');
        INSERT INTO board_rows VALUES ('card-t2','expense');
    """)
    assert ota_exact.open_transaction_ids(conn) == {'t1', 't5'}


def test_portal_payment_without_a_date_is_refused_by_default_and_allowed_only_when_the_rule_is_off(monkeypatch):
    portal = charge(paid_on=None)
    assert ota_payments.pair_check(portal, row()) == 'payment_date_unknown'
    monkeypatch.setattr(ota_payments, 'portal_payment_date_required', lambda: False)
    assert ota_payments.pair_check(portal, row()) is None
    assert ota_payments.pair_check(portal, row(card_tail='3820')) == 'card_identity'


def test_refused_match_with_a_known_stay_blocks_inference_but_one_without_a_stay_does_not():
    stay = dict(starts_on='2026-08-06', ends_on='2026-08-12')
    with_stay = dict(transaction_id='t1', source_hash='a' * 64, provider='agoda', booking_ref='B1', item='숙박비', period=stay)
    without_stay = dict(transaction_id='t2', source_hash='b' * 64, provider='agoda', booking_ref='B2', item='숙박비')
    report = gate_report(with_stay, without_stay)
    events = [charge(paid_on=None), charge(booking_ref='B2', paid_on=None)]
    result = ota_exact.apply_gate(report, [row('t1'), row('t2')], events=events, rules=[], open_ids={'t1', 't2'})
    assert result['matches'] == []
    assert result['evidence_gate']['blocked_inference_sources'] == ['a' * 64]
