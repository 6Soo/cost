"""Synthetic worker, persistence, and read-only summary-route contracts."""
import json
import os
from copy import deepcopy
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlsplit

import pytest

from app import ota_queue_projection
from webapp import ota_payment_review
from webapp.ota_snapshot import OtaSnapshotService


def source(identity, **changes):
    row = {'ota_event_id': identity, 'provider': 'synthetic', 'booking_ref': 'SYN-BOOK',
           'event_type': 'charge', 'payment_status': 'paid',
           'evidence_status': 'paid_verified', 'source_digest': f'digest-{identity}'}
    row.update(changes)
    return row


def result(identity, **changes):
    row = {'ota_event_id': identity, 'status': 'MATCHED_AUTO', 'reason': 'unique_exact_evidence',
           'transaction_id': f'card-{identity}', 'payment_status': 'paid',
           'evidence_status': 'paid_verified', 'individual_payment_evidence': True}
    row.update(changes)
    return row


def counts(summary):
    return summary['counts_by_queue']


def test_canonical_reconcile_summary_uses_full_join_not_public_holds_subset():
    events = [source('hold', status='HOLD_AMBIGUOUS', reason='source-reason'), source('match')]
    results = [result('hold', status='HOLD_AMBIGUOUS', reason='ambiguous'), result('match')]

    class Backend:
        board = object()
        sources = {'mail_directories': []}
        store = SimpleNamespace(active_rules=lambda: [])

        def _data(self):
            return events, [], {}, results

        def _occupied_cards(self, *_args):
            return {}

        def snapshot_from(self, _data, *, include_cards):
            assert include_cards is False
            return {'events': [{'ota_event_id': 'hold'}], 'cards_by_event': {}, 'proposals': []}

    backend = Backend()
    with (mock.patch('webapp.guide_airfare_review.evaluate', return_value={}),
          mock.patch('webapp.guide_airfare_review.authority_summary', return_value={}),
          mock.patch.object(ota_payment_review, '_passenger_index', return_value={}),
          mock.patch.object(ota_payment_review, 'scheduled_card_settlements', return_value=[])):
        payload = ota_payment_review.reconcile_for(backend)
    summary = payload['queue_summary']
    assert counts(summary)['completed']['event_count'] == 1
    assert counts(summary)['needs_action']['event_count'] == 1
    assert len(payload['public']['events']) == 1
    assert payload['public']['events'][0]['ota_event_id'] == 'hold'


def test_verified_portal_reservation_groups_count_events_and_groups_with_worst_member_queue():
    def verified(identity, **changes):
        attestation = {"provider":"agoda", "identity":"opaque-record-group",
                       "identity_status":"verified", "evidence_status":"verified",
                       "source_status":"verified", "source_lineage_id":"stable-lineage",
                       "evidence_link_ids":["link"]}
        row = source(identity, provider="agoda", reservation_identity_attestation=attestation,
                     _portal_reservation_provenance={"provider":"agoda", "identity":"opaque-record-group",
                         "source_digest":"private", "source_lineage_id":"stable-lineage"}, **changes)
        return row
    queue_rows = ota_payment_review._canonical_queue_rows(
        [verified("charge", event_type="charge"), verified("refund", event_type="refund")],
        [result("charge"), result("refund", status="HOLD_EVIDENCE_CONFLICT",
                                  reason="refund_not_verified")], {})
    summary = ota_payment_review._canonical_queue_group_summary(queue_rows)
    assert counts(summary)['needs_action'] == {'event_count': 1, 'group_count': 1}
    assert counts(summary)['completed'] == {'event_count': 1, 'group_count': 0}
    groups = ota_payment_review._canonical_queue_group_rows(queue_rows)
    assert len(groups) == 1
    assert {member['event_type'] for member in groups[0]['event']['group_members']} == {'charge', 'refund'}
    assert groups[0]['queue'] == 'needs_action'
    assert 'private' not in json.dumps(groups)


def test_exact_join_preserves_source_warnings_and_detects_digest_change_without_mutation():
    events = [source('a'), source('b', evidence_missing=True),
              source('c', source_digest='current')]
    results = [result('a'), result('b'), result('c')]
    before_events, before_results = deepcopy(events), deepcopy(results)
    summary = ota_payment_review._canonical_queue_summary(
        events, results, {'c': {'source_digest': 'previous'}})
    assert counts(summary)['completed']['event_count'] == 1
    assert counts(summary)['needs_action']['event_count'] == 2
    assert events == before_events and results == before_results


def test_duplicate_missing_and_orphan_rows_are_unresolved_and_counted_individually():
    events = [source('duplicate'), source('duplicate'),
              source(None, status='MATCHED_AUTO', reason='unique_exact_evidence',
                     transaction_id='source-must-not-complete'),
              source('source-only', status='MATCHED_AUTO', reason='unique_exact_evidence',
                     transaction_id='source-must-not-complete')]
    results = [result('duplicate'), result('orphan'),
               result(None, transaction_id='orphan-card'),
               result('result-duplicate'), result('result-duplicate')]
    summary = ota_payment_review._canonical_queue_summary(events, results, {})
    total = sum(bucket['event_count'] for bucket in counts(summary).values())
    # Every source row plus each result not joined by a unique exact ID remains a unit.
    assert total == len(events) + len(results) - 0
    assert counts(summary)['completed']['event_count'] == 0
    assert counts(summary)['needs_action']['event_count'] == total
    assert counts(summary)['needs_action']['group_count'] == total


def test_unique_join_missing_result_does_not_use_source_match_fields_as_result():
    event = source('missing-result', status='MATCHED_AUTO', reason='unique_exact_evidence',
                   transaction_id='source-card')
    summary = ota_payment_review._canonical_queue_summary([event], [], {})
    assert counts(summary)['completed']['event_count'] == 0
    assert counts(summary)['needs_action']['event_count'] == 1


@pytest.mark.parametrize('missing_key', ['status', 'reason', 'transaction_id'])
def test_source_match_fields_cannot_fill_missing_solver_authority(missing_key):
    event = source('x', status='MATCHED_AUTO', reason='unique_exact_evidence', transaction_id='source-card')
    solver = result('x')
    solver.pop(missing_key)
    summary = ota_payment_review._canonical_queue_summary([event], [solver], {})
    assert counts(summary)['completed']['event_count'] == 0


@pytest.mark.parametrize('evidence', ['conflict', 'evidence_conflict', 'refund_conflict'])
def test_source_evidence_conflict_cannot_be_overwritten_by_result(evidence):
    summary = ota_payment_review._canonical_queue_summary(
        [source('x', evidence_status=evidence)], [result('x')], {})
    assert counts(summary)['needs_action']['event_count'] == 1
    assert counts(summary)['completed']['event_count'] == 0


def test_result_duplicate_with_source_is_not_joined_cartesian_or_last_wins():
    summary = ota_payment_review._canonical_queue_summary(
        [source('x')], [result('x'), result('x')], {})
    assert sum(bucket['event_count'] for bucket in counts(summary).values()) == 3
    assert counts(summary)['completed']['event_count'] == 0
    assert counts(summary)['needs_action']['event_count'] == 3


def test_unknown_result_status_or_evidence_never_completes_canonical_summary():
    summary = ota_payment_review._canonical_queue_summary(
        [source('unknown-status'), source('unknown-evidence')],
        [result('unknown-status', status='FUTURE_STATUS'),
         result('unknown-evidence', evidence_status='future-evidence')], {})
    assert counts(summary)['completed']['event_count'] == 0
    assert counts(summary)['needs_action']['event_count'] == 2


def test_refund_and_cancellation_rows_keep_source_values_unmodified():
    events = [source('refund', event_type='refund', refund_status='refund_pending',
                     amount='12.30', currency='JPY', source_digest='refund-proof'),
              source('cancel', event_type='cancellation', refund_status='none_displayed',
                     amount='-4.20', currency='USD')]
    results = [result('refund', status='HOLD_EVIDENCE_CONFLICT', reason='refund_not_verified'),
               result('cancel', status='HOLD_EVIDENCE_CONFLICT', reason='cancel_review')]
    before = deepcopy(events)
    ota_payment_review._canonical_queue_summary(events, results, {})
    assert events == before
    assert events[0]['refund_status'] == 'refund_pending'
    assert events[0]['currency'] == 'JPY' and events[1]['currency'] == 'USD'


class Handler:
    def __init__(self, user='synthetic-owner'):
        self.user = user
        self.headers = {}
        self.response = None

    def current_user_id(self):
        return self.user

    def _send_json(self, payload, status=200):
        self.response = (status, payload)


class SnapshotBackend:
    def __init__(self, view):
        self.view = view
        self.view_calls = 0
        self.other_calls = []

    def snapshot_view(self):
        self.view_calls += 1
        return self.view

    def _data(self):
        self.other_calls.append('_data')
        raise AssertionError('request path must not read backend data')

    def snapshot(self):
        self.other_calls.append('snapshot')
        raise AssertionError('request path must not reconcile')

    def cards_for_event(self, _event_id):
        self.other_calls.append('cards_for_event')
        raise AssertionError('summary must not materialize cards')


def ready_view(summary, *, generation=5, generated_at='2026-10-28T00:00:00+00:00'):
    saved = {**summary, 'generation': generation, 'generated_at': generated_at}
    return {'status': 'ready', 'fresh': True, 'stale': False, 'refreshing': False,
            'generation': generation, 'generated_at': generated_at,
            'current': {'queue_summary': saved, 'public': {'events': []}}}


def call_summary(backend, *, user='synthetic-owner'):
    handler = Handler(user)
    handled = ota_payment_review.dispatch(
        handler, urlsplit('/api/imports/ota/summary'), backend=backend)
    assert handled
    return handler.response


def test_authenticated_summary_get_reads_saved_counts_only_repeatedly():
    saved = ota_payment_review._canonical_queue_summary([source('a')], [result('a')], {})
    backend = SnapshotBackend(ready_view(saved))
    with mock.patch.dict(os.environ, {
        ota_payment_review.REVIEW_MODE_ENV: 'isolated',
        ota_payment_review.REVIEW_DB_ENV: 'C:/synthetic/summary.sqlite',
    }), mock.patch.object(ota_payment_review, 'summarize_queue', side_effect=AssertionError), \
         mock.patch.object(ota_payment_review, '_canonical_queue_summary', side_effect=AssertionError):
        first = call_summary(backend)
        second = call_summary(backend)
    assert first[0] == second[0] == 200
    assert first[1]['counts_authoritative'] is True
    assert first[1]['counts_by_queue']['completed']['event_count'] == 1
    assert first[1]['generation'] == 5
    assert first[1]['generated_at'] == '2026-10-28T00:00:00+00:00'
    assert backend.view_calls == 2 and backend.other_calls == []


def test_summary_auth_denial_and_missing_snapshot_service_are_safe():
    with mock.patch.dict(os.environ, {
        ota_payment_review.REVIEW_MODE_ENV: 'isolated',
        ota_payment_review.REVIEW_DB_ENV: 'C:/synthetic/summary.sqlite',
    }):
        denied_backend = SnapshotBackend({})
        denied = call_summary(denied_backend, user='')
        assert denied[0] == 403 and denied_backend.view_calls == 0
        no_service = call_summary(SimpleNamespace(), user='synthetic-owner')
        assert no_service[0] == 503


def test_disabled_mode_keeps_existing_404_gate_for_summary_path():
    backend = SnapshotBackend({})
    handler = Handler()
    with mock.patch.dict(os.environ, {}, clear=True):
        handled = ota_payment_review.dispatch(
            handler, urlsplit('/api/imports/ota/summary'), backend=backend)
    assert handled and handler.response[0] == 404
    assert backend.view_calls == 0


@pytest.mark.parametrize('status', ['loading', 'error', 'refreshing'])
def test_nonready_summary_downgrades_saved_counts_to_auto_recheck(status):
    saved = ota_payment_review._canonical_queue_summary(
        [source('a'), source('b')], [result('a'), result('b')], {})
    view = ready_view(saved)
    view.update(status=status, fresh=False, stale=True, refreshing=status == 'refreshing')
    response = ota_payment_review._stored_queue_summary_response(view)
    assert response['counts_authoritative'] is False
    assert response['counts_by_queue']['completed']['event_count'] == 0
    assert response['counts_by_queue']['auto_recheck'] == {'event_count': 2, 'group_count': 2}
    assert response['state_tags']


def test_unavailable_current_or_old_persisted_snapshot_never_looks_like_zero_ready():
    for view in ({'status': 'loading', 'current': None, 'generation': 0},
                 {'status': 'refreshing', 'current': {'public': {}}, 'generation': 2}):
        response = ota_payment_review._stored_queue_summary_response(view)
        assert response['summary_status'] == 'unavailable'
        assert response['counts_available'] is False
        assert response['counts_by_queue'] is None
        assert response['counts_authoritative'] is False


def test_ready_empty_is_known_zero_but_loading_empty_is_rechecking_zero():
    empty = ota_payment_review._canonical_queue_summary([], [], {})
    ready = ota_payment_review._stored_queue_summary_response(ready_view(empty))
    stale_view = ready_view(empty)
    stale_view.update(status='loading', fresh=False, stale=True, refreshing=False)
    loading = ota_payment_review._stored_queue_summary_response(stale_view)
    assert ready['counts_available'] is True and ready['counts_authoritative'] is True
    assert ready['counts_by_queue']['auto_recheck']['event_count'] == 0
    assert loading['counts_available'] is True and loading['counts_authoritative'] is False
    assert loading['counts_by_queue']['auto_recheck']['event_count'] == 0
    assert loading['summary_status'] == 'rechecking'


def test_summary_generation_mismatch_is_explicitly_rechecking_and_sanitized():
    summary = ota_payment_review._canonical_queue_summary(
        [source('SENTINEL_ID', source_digest='SENTINEL_DIGEST', amount='SENTINEL_AMOUNT')],
        [result('SENTINEL_ID', reason='SENTINEL_REASON')], {})
    view = ready_view(summary)
    view['current']['queue_summary']['generation'] = 4
    response = ota_payment_review._stored_queue_summary_response(view)
    assert response['summary_status'] == 'rechecking'
    assert response['state_tags'] == ['QUEUE_SUMMARY_NOT_CURRENT']
    assert response['counts_authoritative'] is False
    assert 'SENTINEL' not in json.dumps(response)


def test_malformed_generation_timestamp_never_echoes_or_marks_counts_authoritative():
    summary = ota_payment_review._canonical_queue_summary([source('a')], [result('a')], {})
    view = ready_view(summary)
    view['generated_at'] = 'SENTINEL_GENERATED_AT'
    response = ota_payment_review._stored_queue_summary_response(view)
    assert response['generated_at'] is None
    assert response['counts_authoritative'] is False
    assert 'SENTINEL' not in json.dumps(response)


def test_worker_publication_persistence_restore_and_failed_refresh_keep_same_generation_summary(tmp_path):
    initial = ota_payment_review._canonical_queue_summary([source('a')], [result('a')], {})
    key = {'value': 'one'}
    attempts = {'n': 0}

    def reconcile():
        attempts['n'] += 1
        if attempts['n'] == 2:
            raise RuntimeError('synthetic failure')
        return {'public': {'events': []}, 'results': [], 'links': {}, 'data': {},
                'queue_summary': initial}

    path = tmp_path / 'snapshot.json'
    service = OtaSnapshotService(key_fn=lambda: key['value'], reconcile_fn=reconcile,
                                 persist_path=path, start=False)
    service.check_now()
    current = service._current
    assert current['queue_summary']['generation'] == current['generation'] == 1
    assert current['queue_summary']['generated_at'] == current['generated_at']
    document = json.loads(path.read_text(encoding='utf-8'))
    assert document['queue_summary']['generation'] == 1

    restored = OtaSnapshotService(key_fn=lambda: key['value'], reconcile_fn=reconcile,
                                  persist_path=path, start=False)
    restored_view = restored.view()
    assert restored_view['status'] == 'refreshing'
    downgraded = ota_payment_review._stored_queue_summary_response(restored_view)
    assert downgraded['counts_by_queue']['auto_recheck']['event_count'] == 1

    key['value'] = 'two'
    service.check_now()
    assert service.view()['status'] == 'error'
    assert service._current['generation'] == 1
    failed = ota_payment_review._stored_queue_summary_response(service.view())
    assert failed['counts_by_queue']['auto_recheck']['event_count'] == 1
    assert failed['counts_by_queue']['completed']['event_count'] == 0

    document.pop('queue_summary')
    path.write_text(json.dumps(document), encoding='utf-8')
    old_restore = OtaSnapshotService(key_fn=lambda: 'one', reconcile_fn=lambda: {},
                                     persist_path=path, start=False)
    unavailable = ota_payment_review._stored_queue_summary_response(old_restore.view())
    assert unavailable['summary_status'] == 'unavailable'
    assert unavailable['counts_by_queue'] is None
