"""Synthetic payments only; no configured source inventory or operational DB."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

import pytest

from app import ota_payments as payments
from app.ota_core_projection import project_card_ota_candidate_notes, project_card_ota_statuses
from app.ota_review import OtaReviewStore
from tests.card_pipeline.test_ota_payments import card, event, message, JP_PAID_BODY, JP_PAID_SUBJECT
from webapp import ota_payment_review
from webapp.card_flow import _index_ota_display_candidates
from webapp.ledger_store import LedgerStore


def trip_event(**changes):
    return event(provider='trip', booking_ref='SYNTHETIC-TRIP', amount='9737', currency='JPY',
                 amount_krw=None, **changes)


def trip_card(**changes):
    return card(merchant='TRIP.COM', merchant_normalized='trip.com', **changes)


@pytest.mark.parametrize('rate,fee', [('8.70', 0), ('8.70', 500), ('8.70005', 501)])
def test_original_jpy_matches_despite_fx_fee_and_krw_rounding(rate, fee):
    # Synthetic issuer settlement: total is already inclusive of fees.
    total = int((Decimal('9737') * Decimal(rate)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) + fee
    fact, row = trip_event(), trip_card(amount_krw=total, foreign_amount='9,737.00', foreign_currency='JPY')
    original = deepcopy((fact, row))
    assert payments.compare_payment_amount(fact, row)['status'] == 'MATCH'
    result = payments.match_ota_payment_events([fact], [row])[0]
    assert result['status'] == 'MATCHED_AUTO'
    assert result['transaction_id'] == row['transaction_id']
    assert (fact, row) == original


@pytest.mark.parametrize('foreign_amount', ['9736.999', '9737.001', '9738'])
def test_nearly_equal_foreign_amount_never_uses_rounding_or_krw_coincidence(foreign_amount):
    fact = trip_event()
    row = trip_card(amount_krw=85621, foreign_amount=foreign_amount, foreign_currency='JPY')
    assert payments.compare_payment_amount(fact, row) == {'status': 'MISMATCH', 'reason': 'AMOUNT_MISMATCH'}
    assert not payments.match_ota_payment_events([fact], [row])[0]['transaction_id']


@pytest.mark.parametrize('krw', [85621, 97370, 1, 90000])
def test_plausible_or_implausible_fx_is_unknown_without_same_currency_evidence(krw):
    fact, row = trip_event(), trip_card(amount_krw=krw)
    assert payments.compare_payment_amount(fact, row) == {'status': 'UNKNOWN', 'reason': 'FX_EVIDENCE_REQUIRED'}
    result = payments.match_ota_payment_events([fact], [row])[0]
    assert result['status'] == 'HOLD_AMOUNT_UNVERIFIED'
    assert result['reason'] == 'FX_EVIDENCE_REQUIRED' and result['transaction_id'] is None
    trace = payments.search_card_candidates(fact, [row])
    assert trace['candidates'] == []
    assert trace['rejected'][0]['reason'] == 'FX_EVIDENCE_REQUIRED'
    assert payments.pair_check(fact, row) == 'amount'


@pytest.mark.parametrize('billed,matched', [(85621, True), (85620, False), (85622, False)])
def test_explicit_krw_payment_compares_issuer_total_without_adding_fees(billed, matched):
    fact = event(provider='trip', amount=85621, amount_krw=85621)
    row = trip_card(amount_krw=billed, foreign_amount='9737', foreign_currency='JPY',
                    principal_krw=85121, fee_krw=500, exchange_rate='10')
    original = deepcopy(row)
    assert payments._amount_matches(fact, row, []) is matched
    assert row == original


def test_explicit_different_currency_is_conflict_and_invalid_amount_is_unverified():
    fact = trip_event()
    row = trip_card(foreign_currency='USD', foreign_amount='9737')
    assert payments.compare_payment_amount(fact, row)['reason'] == 'CURRENCY_MISMATCH'
    for value in (None, 'NaN', 'Infinity', '9,,737'):
        row.update(foreign_currency='JPY', foreign_amount=value)
        assert payments.compare_payment_amount(fact, row)['status'] == 'UNKNOWN'
        assert payments.pair_check(fact, row) == 'amount'


def test_same_date_other_purchase_and_two_bookings_are_not_auto_linked():
    fact = event(provider='trip', amount=45000, amount_krw=45000)
    row = trip_card(amount_krw=45000)
    assert payments.match_ota_payment_events([fact], [row])[0]['status'] == 'MATCHED_AUTO'
    other = dict(fact, ota_event_id='other-payment', booking_ref='OTHER-SYNTHETIC', source_ids=['mail:other'])
    results = payments.match_ota_payment_events([fact, other], [row])
    assert all(result['transaction_id'] is None for result in results)
    assert all(result['status'] == 'MATCHED_GROUP' for result in results)
    assert not payments.match_ota_payment_events([fact], [dict(row, amount_krw=45001)])[0]['transaction_id']
    assert not payments.match_ota_payment_events([fact], [dict(row, card_tail='9999')])[0]['transaction_id']
    claim = dict(fact, event_type='reservation', evidence_status='reservation_only', payment_status='unknown')
    assert not payments.match_ota_payment_events([claim], [row])[0]['transaction_id']


def test_signed_mail_through_solver_backend_and_both_public_ui_projections(tmp_path, monkeypatch):
    import json
    directory = tmp_path / 'synthetic-mail'
    directory.mkdir()
    (directory / 'gmail-fixture.json').write_text(json.dumps({'responses': [message(
        JP_PAID_BODY, subject=JP_PAID_SUBJECT, sent='2026-09-25')]}), encoding='utf-8')
    events = payments.build_ota_payment_events({'mail_directories': [directory]})
    assert len(events) == 1 and events[0]['amount_krw'] is None
    row = trip_card(amount_krw=85621, approval_date='2026-09-25')
    board = LedgerStore(tmp_path / 'synthetic-board.sqlite', seed_demo=False)
    backend = ota_payment_review.CoreOtaPaymentBackend(board, str(tmp_path / 'synthetic-review.sqlite'),
        read_only=True, payments=SimpleNamespace(build_ota_payment_events=lambda _: deepcopy(events),
        match_ota_payment_events=payments.match_ota_payment_events,
        search_card_candidates=payments.search_card_candidates, same_date_cards=payments.same_date_cards,
        _event_is_paid=payments._event_is_paid), store_type=OtaReviewStore, sources={})
    monkeypatch.setattr(backend, '_transactions', lambda: [deepcopy(row)])
    try:
        data = backend._data()
        assert data[3][0]['status'] == 'HOLD_AMOUNT_UNVERIFIED'
        assert data[3][0]['candidate_search']['rejected'][0]['reason'] == 'FX_EVIDENCE_REQUIRED'
        full = ota_payment_review.public_snapshot(backend.snapshot_from(data), include_cards=True)
        public_row = full['cards_by_event'][events[0]['ota_event_id']][0]
        assert public_row['selection_disabled']
        assert public_row['candidate_resolution_allowed'] is False
        assert '직접 비교할 수 없습니다' in public_row['selection_disabled_reason']
        assert '다릅니다' not in public_row['selection_disabled_reason']
        snapshot = {'data': dict(zip(('events', 'transactions', 'links', 'results'), data)), 'results': data[3]}
        notes = _index_ota_display_candidates(snapshot)[row['transaction_id']]
        assert any('대조 자료 확인' in note for note in notes)
        assert all('금액이 다릅니다' not in note for note in notes)
        core_notes = project_card_ota_candidate_notes(snapshot, {row['transaction_id']})
        assert '직접 비교할 수 없습니다' in ' '.join(core_notes[row['transaction_id']])
        assert project_card_ota_statuses(snapshot)[0].get(row['transaction_id']) not in ('EXACT', 'INFERRED')
        assert not backend.store.links()
    finally:
        backend.close()
        board.close()


def test_exact_payment_detail_is_not_relabelled_candidate_and_refund_link_is_separate():
    fact = event(provider='trip', amount=45000, amount_krw=45000)
    row = trip_card(amount_krw=45000, refund_status='original_linked', original_transaction_id='synthetic-original')
    result = payments.match_ota_payment_events([fact], [row])[0]
    snapshot = {'results': [result], 'data': {'events': [fact], 'transactions': [row], 'results': [result]}}
    notes = _index_ota_display_candidates(snapshot)[row['transaction_id']]
    assert len(notes) == 1
    assert '확정 연결' in notes[0] and '후보' not in notes[0]
    assert '전역 유일성' in notes[0] and '예약 근거 확인 필요' not in notes[0]
    insufficient = dict(fact, evidence_status='reservation_only', payment_status='unknown')
    assert payments.match_ota_payment_events([insufficient], [row])[0]['transaction_id'] is None
