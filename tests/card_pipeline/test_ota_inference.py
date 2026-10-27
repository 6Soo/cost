import copy

import pytest

from app import ota_exact, ota_inference, ota_payments
from tests.card_pipeline.test_ota_payments import card, event


def fact(**changes):
    return event(paid_on=None, verified_portal_snapshot=True, reservation_status='completed',
                 service_period={'starts_on': '2026-08-01', 'ends_on': '2026-08-03'}, **changes)


def eligible(**changes):
    return card(ota_inference_eligible=True, **changes)


def test_approved_unique_inference_preserves_unknown_date_and_uses_same_rule_in_card_gate():
    observation, row = fact(), eligible()
    original = copy.deepcopy([observation, row])
    result = ota_payments.match_ota_payment_events([observation], [row])[0]
    assert result['status'] == 'MATCHED_AUTO'
    assert result['inferred_link'] is True
    assert result['paid_on'] is None
    assert result['payment_date_verified'] is False
    assert result['ota_event_id'] == observation['ota_event_id']
    report = ota_exact.apply_gate({'matches': []}, [row], events=[observation], rules=[], open_ids={'card-a'})
    assert report['inferred_matches'] == 1
    assert report['exact_matches'] == 0
    assert report['matches'][0]['inferred_link'] is True
    assert '추론 연결' in report['rules'][0]['effects']['description']
    from webapp.ota_payment_review import legacy_exact_bindings
    assert legacy_exact_bindings([observation], [row], report) == {}
    assert ota_payments.pair_check(observation, row) == 'payment_date_unknown'
    assert [observation, row] == original


@pytest.mark.parametrize('changes', [
    {'provider': 'booking'}, {'verified_portal_snapshot': False}, {'card_last4': None},
    {'reservation_status': 'cancelled'}, {'reservation_status': 'unknown'},
    {'refund_status': 'refund_pending'}, {'service_period': None},
    {'service_period': {'starts_on': '2026-08-03', 'ends_on': '2026-08-01'}},
    {'service_period_conflict': True}, {'evidence_status': 'scheduled'},
])
def test_other_providers_incomplete_or_cancelled_evidence_is_not_inferred(changes):
    observation = fact()
    observation.update(changes)
    result = ota_payments.match_ota_payment_events([observation], [eligible()])[0]
    assert result['status'] != 'MATCHED_AUTO'


@pytest.mark.parametrize('changes', [
    {'ota_inference_eligible': False}, {'parse_error': 'unreadable'}, {'duplicate_of': 'other'},
    {'conflict_reason': 'source_changed'}, {'amount_krw': 30001}, {'card_tail': '9999'},
    {'transaction_direction': 'cancellation'},
])
def test_recorded_protected_held_or_changed_card_is_not_inferred(changes):
    row = eligible()
    row.update(changes)
    assert ota_inference.unique_pairs([fact()], [row]) == {}


def test_uniqueness_counts_all_cards_bookings_and_real_duplicate_payments():
    observation = fact()
    row = eligible()
    other_card = eligible(identity='different-card', approval_date='2026-07-01')
    other_card['ota_inference_eligible'] = False
    assert ota_inference.unique_pairs([observation], [row, other_card]) == {}
    other_booking = dict(observation, ota_event_id='another', booking_ref='ANOTHER123')
    assert ota_inference.unique_pairs([observation, other_booking], [row]) == {}
    other_payment = dict(observation, ota_event_id='second-real-payment')
    assert ota_inference.unique_pairs([observation, other_payment], [row]) == {}
    cancelled_notice = dict(observation, ota_event_id='cancel', event_type='reservation', reservation_status='cancelled')
    assert ota_inference.unique_pairs([observation, cancelled_notice], [row]) == {}


def test_existing_links_dated_claims_and_explicit_holds_are_never_displaced():
    observation, row = fact(), eligible()
    assert ota_inference.unique_pairs([observation], [row], occupied={'card-a'}) == {}
    dated = event(identity='dated', provider='agoda')
    assert ota_inference.unique_pairs([observation, dated], [row]) == {}
    report = ota_exact.apply_gate({'matches': []}, [row], events=[observation], rules=[],
                                  open_ids={'card-a'}, inference_excluded_ids={'card-a'})
    assert report['matches'] == []


def test_policy_must_have_explicit_owner_approval(monkeypatch):
    monkeypatch.setattr(ota_inference, 'load_defaults', lambda: {'agoda_undated_unique_match': {'enabled': True}})
    assert ota_inference.unique_pairs([fact()], [eligible()]) == {}


def test_undated_agoda_never_infers_a_trip_merchant_with_same_card_and_amount():
    row = eligible()
    row.update(merchant='Trip.com Tokyo JP', merchant_normalized='trip.com tokyo jp')
    assert ota_inference.unique_pairs([fact()], [row]) == {}
    assert ota_payments.match_ota_payment_events([fact()], [row])[0]['transaction_id'] is None


@pytest.mark.parametrize('flag', ['parse_error', 'conflict_reason'])
def test_broken_competing_original_blocks_inference_in_solver_and_card_gate(flag):
    observation, row = fact(), eligible()
    competitor = eligible(identity='synthetic-competitor', **{flag: 'synthetic-source-error'})
    competitor['ota_inference_eligible'] = False
    original = copy.deepcopy([observation, row, competitor])
    assert ota_inference.unique_pairs([observation], [row, competitor]) == {}
    result = ota_payments.match_ota_payment_events([observation], [row, competitor])[0]
    assert result['transaction_id'] is None and result['status'] == 'HOLD_DATE_UNKNOWN'
    report = ota_exact.apply_gate({'matches': []}, [row, competitor], events=[observation],
                                  rules=[], open_ids={'card-a'})
    assert report['matches'] == [] and report['inferred_matches'] == 0
    assert [observation, row, competitor] == original


def test_proven_duplicate_copy_does_not_count_as_another_original():
    observation, row = fact(), eligible()
    duplicate = eligible(identity='synthetic-copy', duplicate_of=row['transaction_id'])
    assert ota_inference.unique_pairs([observation], [row, duplicate]) == {observation['ota_event_id']: row}
