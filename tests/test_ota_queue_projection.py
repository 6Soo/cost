"""Synthetic tests for the isolated, non-mutating OTA queue projection."""
from copy import deepcopy

import pytest
import json

from app.ota_queue_projection import classify_event, summarize_queue


READY = {'status': 'ready', 'stale': False, 'refreshing': False,
         'fresh': True, 'enabled': True, 'generation': 7}


def matched(**changes):
    event = {
        'ota_event_id': 'event-001', 'transaction_id': 'card-001',
        'status': 'MATCHED_AUTO', 'reason': 'unique_exact_evidence',
        'payment_status': 'paid', 'evidence_status': 'paid_verified',
        'inferred_link': False, 'individual_payment_evidence': True,
        'allocation_basis': None,
    }
    event.update(changes)
    return event


def test_only_source_backed_exact_and_user_matches_complete_review():
    assert classify_event(matched(), READY)['queue'] == 'completed'
    user = matched(status='MATCHED_USER', reason='pinned_existing_link')
    assert classify_event(user, READY)['queue'] == 'completed'
    assert classify_event(matched(inferred_link=True), READY)['queue'] == 'needs_action'
    assert classify_event(matched(individual_payment_evidence=False,
                                  allocation_basis='auto_stable_order'), READY)['queue'] == 'needs_action'
    assert classify_event(matched(status='MATCHED_AUTO', reason='unknown_success'), READY)['queue'] == 'needs_action'
    assert classify_event(matched(inferred_link='false'), READY)['queue'] == 'needs_action'
    assert classify_event(matched(allocation_basis='unrecognized_group'), READY)['queue'] == 'needs_action'


@pytest.mark.parametrize('change', [
    {'evidence_missing': True}, {'evidence_changed': True},
    {'review_warning': 'raw private warning'},
    {'evidence_changed': 'malformed-flag'},
])
def test_source_warnings_block_completion_and_are_sanitized(change):
    result = classify_event(matched(**change), READY)
    assert result['queue'] == 'needs_action'
    assert result['warning'] is True
    assert 'raw private warning' not in repr(result)


@pytest.mark.parametrize(('event', 'queue'), [
    ({'ota_event_id': 'pending', 'status': 'PENDING_PAYMENT', 'evidence_status': 'scheduled'}, 'waiting_source'),
    ({'ota_event_id': 'date', 'status': 'HOLD_DATE_UNKNOWN', 'evidence_status': 'paid_verified'}, 'waiting_source'),
    ({'ota_event_id': 'card', 'status': 'HOLD_NO_CARD', 'evidence_status': 'paid_verified'}, 'waiting_source'),
    ({'ota_event_id': 'reservation', 'status': 'RESERVATION_ONLY', 'evidence_status': 'unknown'}, 'evidence_missing'),
    ({'ota_event_id': 'forest', 'status': 'RESERVATION_ONLY', 'evidence_status': 'reservation_only'}, 'evidence_missing'),
    ({'ota_event_id': 'amount', 'status': 'HOLD_AMOUNT_UNVERIFIED', 'evidence_status': 'paid_unverified'}, 'evidence_missing'),
    ({'ota_event_id': 'conflict', 'status': 'HOLD_AMOUNT_MISMATCH', 'evidence_status': 'paid_verified'}, 'needs_action'),
    ({'ota_event_id': 'ambiguous', 'status': 'HOLD_AMBIGUOUS', 'evidence_status': 'paid_verified'}, 'needs_action'),
    ({'ota_event_id': 'unknown', 'status': 'FUTURE_STATUS', 'reason': 'raw', 'evidence_status': 'future'}, 'needs_action'),
])
def test_holds_missing_evidence_and_unknown_values_map_conservatively(event, queue):
    assert classify_event(event, READY)['queue'] == queue


@pytest.mark.parametrize('freshness', [
    {'status': 'loading', 'stale': True, 'refreshing': False, 'generation': 0},
    {'status': 'error', 'stale': True, 'refreshing': False, 'generation': 4},
    {'status': 'ready', 'stale': True, 'refreshing': False, 'generation': 4},
    {'status': 'refreshing', 'stale': False, 'refreshing': True, 'generation': 4},
])
def test_global_nonready_envelopes_do_not_hide_events_as_complete(freshness):
    assert classify_event(matched(), freshness)['queue'] == 'auto_recheck'
    summary = summarize_queue([matched()], freshness, coverage='canonical')
    assert summary['counts_by_queue']['auto_recheck']['event_count'] == 1
    assert summary['counts_authoritative'] is False
    assert summary['warning_count'] >= 1


@pytest.mark.parametrize(('change', 'tag'), [
    ({'fresh': False}, 'SNAPSHOT_NOT_FRESH'),
    ({'enabled': False}, 'SNAPSHOT_DISABLED'),
    ({'fresh': 'SENTINEL_FRESH'}, 'INVALID_FRESHNESS_ENVELOPE'),
    ({'enabled': {'secret': 'SENTINEL_ENABLED'}}, 'INVALID_FRESHNESS_ENVELOPE'),
    ({'generation': None}, 'INVALID_FRESHNESS_ENVELOPE'),
])
def test_explicit_stale_disabled_and_malformed_ready_envelopes_are_gated(change, tag):
    freshness = dict(READY, **change)
    result = classify_event(matched(), freshness)
    assert result['queue'] == 'auto_recheck'
    summary = summarize_queue([matched()], freshness, coverage='canonical')
    assert summary['state_tags'] == [tag]
    assert summary['counts_by_queue']['auto_recheck']['event_count'] == 1


@pytest.mark.parametrize('freshness', [
    {'status': 'loading', 'stale': True, 'refreshing': False, 'generation': None},
    {'status': 'error', 'stale': True, 'refreshing': False, 'generation': None},
])
def test_uncreated_snapshot_generation_none_preserves_loading_vs_error(freshness):
    summary = summarize_queue([], freshness, coverage='canonical')
    assert summary['snapshot_status'] == freshness['status']
    assert summary['generation'] is None
    assert summary['counts_authoritative'] is False


@pytest.mark.parametrize('status', ['loading', 'error', 'refreshing'])
def test_empty_ready_and_empty_nonready_snapshots_remain_distinguishable(status):
    empty = summarize_queue([], READY, coverage='canonical')
    gated = summarize_queue([], {'status': status, 'stale': status != 'refreshing',
                                 'refreshing': status == 'refreshing', 'generation': 0},
                            coverage='canonical')
    assert empty['counts_by_queue']['completed']['event_count'] == 0
    assert empty['snapshot_status'] == 'ready' and empty['warning_count'] == 0
    assert gated['snapshot_status'] == status and gated['warning_count'] == 1
    assert gated['state_tags']


def test_coverage_is_required_and_subset_counts_are_not_authoritative():
    with pytest.raises(TypeError):
        summarize_queue([], READY)
    subset = summarize_queue([matched()], READY, coverage='public_subset')
    assert subset['coverage'] == 'public_subset'
    assert subset['counts_authoritative'] is False
    assert 'PUBLIC_SUBSET_NOT_FULL_CANONICAL' in subset['state_tags']
    with pytest.raises(ValueError, match='coverage must'):
        summarize_queue([], READY, coverage='all')


def test_every_event_is_a_singleton_even_with_shared_booking_or_payment_groups():
    events = [
        matched(ota_event_id='one', provider='agoda', booking_ref='same', group_count={'ota': 2}),
        matched(ota_event_id='two', provider='toyoko', booking_ref='same', transaction_id='card-1'),
        matched(ota_event_id='three', provider='agoda', booking_ref='different',
                transaction_id='card-1', ota_group_ids=['one', 'two']),
    ]
    summary = summarize_queue(events, READY, coverage='canonical')
    assert summary['grouping'] == 'singleton_fallback'
    assert summary['counts_by_queue']['completed'] == {'event_count': 3, 'group_count': 3}


def test_duplicate_and_missing_identity_keep_row_count_and_block_completion():
    events = [matched(ota_event_id='duplicate'), matched(ota_event_id='duplicate'),
              matched(ota_event_id=None), {'status': 'MATCHED_AUTO'}]
    summary = summarize_queue(events, READY, coverage='canonical')
    assert sum(v['event_count'] for v in summary['counts_by_queue'].values()) == len(events)
    assert summary['counts_by_queue']['completed']['event_count'] == 0
    assert summary['counts_by_queue']['needs_action']['event_count'] == len(events)
    assert summary['counts_by_queue']['needs_action']['group_count'] == len(events)
    assert summary['warning_count'] == len(events)


def test_duplicates_cannot_overwrite_global_recheck_queue():
    events = [matched(ota_event_id='same'), matched(ota_event_id='same')]
    stale = dict(READY, stale=True, fresh=False)
    summary = summarize_queue(events, stale, coverage='canonical')
    assert summary['counts_by_queue']['auto_recheck']['event_count'] == 2
    assert summary['counts_by_queue']['needs_action']['event_count'] == 0
    assert summary['warning_count'] == 3


@pytest.mark.parametrize('event', [
    matched(status='HOLD_AMOUNT_MISMATCH', evidence_status='scheduled'),
    matched(status='HOLD_EVIDENCE_CONFLICT', evidence_status='scheduled'),
    matched(status='FUTURE_STATUS', evidence_status='scheduled'),
    matched(evidence_status='future', evidence_changed=True),
    matched(evidence_status='scheduled', review_warning='SENTINEL_WARNING'),
])
def test_warnings_unknown_status_and_evidence_precede_waiting_or_missing_queues(event):
    assert classify_event(event, READY)['queue'] == 'needs_action'


@pytest.mark.parametrize('identity', ['   ', '', None])
def test_blank_event_identity_blocks_completion(identity):
    assert classify_event(matched(ota_event_id=identity), READY)['queue'] == 'needs_action'


@pytest.mark.parametrize('transaction_id', ['   ', '', None])
def test_blank_transaction_identity_blocks_completion(transaction_id):
    assert classify_event(matched(transaction_id=transaction_id), READY)['queue'] == 'needs_action'


def test_refund_cancellation_money_currency_and_private_sentinels_are_not_exposed_or_mutated():
    events = [
        {'ota_event_id': 'refund', 'event_type': 'refund', 'status': 'HOLD_EVIDENCE_CONFLICT',
         'reason': 'SENTINEL_REASON_TEXT', 'refund_status': 'refund_pending',
         'payment_status': 'paid', 'evidence_status': 'refund_verified',
         'amount': 'SENTINEL_AMOUNT', 'currency': 'JPY', 'source_digest': 'SENTINEL_DIGEST'},
        {'ota_event_id': 'cancel', 'event_type': 'cancellation', 'status': 'HOLD_EVIDENCE_CONFLICT',
         'reason': 'SENTINEL_REASON_TEXT', 'refund_status': 'none_displayed',
         'amount': '-10.25', 'currency': 'USD', 'source_ids': ['SENTINEL_ID']},
    ]
    before = deepcopy(events)
    summary = summarize_queue(events, READY, coverage='canonical')
    assert events == before
    assert summary['counts_by_queue']['needs_action']['event_count'] == 2
    serialized = repr(summary)
    for secret in ('SENTINEL', '10.25', 'JPY', 'USD', 'refund_pending'):
        assert secret not in serialized


def test_candidates_are_not_materialized_and_nested_inputs_are_read_only():
    candidate = {'transaction_id': 'SENTINEL_CARD'}
    event = matched(candidate_search={'candidates': [candidate]}, source_ids=['SENTINEL_SOURCE'])
    before = deepcopy(event)
    classify_event(event, READY)
    summarize_queue([event], READY, coverage='canonical')
    assert event == before


@pytest.mark.parametrize('event', [None, [], 'not-an-event', {'status': [], 'evidence_status': {}}])
def test_malformed_events_return_safe_finite_classification(event):
    result = classify_event(event, READY)
    assert result['queue'] == 'needs_action'
    assert result['warning'] is True
    assert all(code.isupper() and code.replace('_', '').isalnum() for code in result['reason_codes'])


def test_invalid_freshness_is_safe_and_never_authoritative():
    summary = summarize_queue([matched()], {'status': ['secret'], 'generation': object()},
                              coverage='canonical')
    assert summary['counts_by_queue']['auto_recheck']['event_count'] == 1
    assert summary['counts_authoritative'] is False
    assert summary['state_tags'] == ['INVALID_FRESHNESS_ENVELOPE']
    serialized = json.dumps(summary)
    assert 'secret' not in serialized and 'object at' not in serialized


def test_untrusted_freshness_metadata_is_sanitized_to_json_safe_primitives():
    class Secret:
        def __repr__(self):
            return 'SENTINEL_OBJECT_REPR'

    freshness = {'status': 'SENTINEL_STATUS', 'stale': {'s': 1},
                 'refreshing': 'SENTINEL_REFRESH', 'fresh': Secret(),
                 'enabled': Secret(), 'generation': {'secret': 'SENTINEL_GENERATION'}}
    summary = summarize_queue([matched()], freshness, coverage='public_subset')
    encoded = json.dumps(summary)
    for secret in ('SENTINEL', 'secret', 'object at'):
        assert secret not in encoded
    assert summary['snapshot_status'] == 'unknown'
    assert summary['generation'] is None
    assert summary['stale'] is None and summary['refreshing'] is None


@pytest.mark.parametrize('status', ['PENDING_PAYMENT', 'HOLD_NO_CARD', 'RESERVATION_ONLY'])
@pytest.mark.parametrize('evidence', ['conflict', 'evidence_conflict', 'refund_conflict'])
def test_conflicting_evidence_precedes_waiting_and_missing_buckets(status, evidence):
    result = classify_event(matched(status=status, evidence_status=evidence), READY)
    assert result['queue'] == 'needs_action'
    assert result['warning'] is True


def test_hostile_malformed_values_are_not_compared_or_echoed():
    class Hostile:
        def __eq__(self, other):
            raise RuntimeError('SENTINEL_EXCEPTION_TEXT')

    result = classify_event(matched(reason=Hostile(), evidence_status=Hostile(),
                                    evidence_changed=Hostile()), READY)
    assert result['queue'] == 'needs_action'
    assert 'SENTINEL_EXCEPTION_TEXT' not in repr(result)
