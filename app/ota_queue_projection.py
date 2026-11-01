"""Pure, conservative queue projection for OTA review events.

Source basis: ``docs/specs/ota-review-queue-performance-20261027.md`` sections
3, 4 and 10; payment result/status/reason production in
``app/ota_payments.py`` (notably 1597-1603, 1633-1688 and 1777-1781); and
snapshot freshness metadata in ``webapp/ota_snapshot.py``:213-236. This is only
a matching-review queue: it cannot establish booking, ledger, travel, or bank
refund completion. The freshness envelope follows ``webapp/ota_snapshot.py``
view/action-context fields (including ``fresh``, ``enabled``, ``stale``,
``refreshing`` and ``generation``). Completion requires a caller-supplied ready, fresh envelope,
a known matched status and finite known success reason/evidence, a usable unique
event identity, and no warning. Unknown values remain unresolved. Reservation
groups have no validated input contract yet, so each input event is a singleton
group; provider, booking/payment references, dates, names and amounts never
merge events. ``historical`` remains empty absent an explicit source contract.

The API is ``classify_event(event, freshness, *, duplicate_identity=False)``
and ``summarize_queue(events, freshness, *, coverage)`` where coverage is
required and is exactly ``canonical`` or ``public_subset``. Summary counts for
public subsets are not full-canonical or authoritative. Functions read but do
not mutate inputs, materialize card candidates, copy nested mappings, perform
I/O, or expose source IDs, text, amounts, digests, or arbitrary raw reason data.
"""
from collections.abc import Mapping


QUEUES = ('needs_action', 'waiting_source', 'evidence_missing', 'auto_recheck',
          'completed', 'historical')
_FRESHNESS_STATES = ('ready', 'loading', 'refreshing', 'error')
_MATCHED_STATUSES = ('MATCHED_AUTO', 'MATCHED_USER')
_KNOWN_STATUSES = _MATCHED_STATUSES + (
    'PENDING_PAYMENT', 'HOLD_DATE_UNKNOWN', 'HOLD_NO_CARD',
    'RESERVATION_ONLY', 'HOLD_AMOUNT_UNVERIFIED', 'HOLD_AMOUNT_MISMATCH',
    'HOLD_AMBIGUOUS', 'HOLD_EVIDENCE_CONFLICT', 'HOLD_GROUP_CHANGED',
    'HOLD_PARTIAL_GROUP', 'NOT_CARD_CHARGE', 'MATCHED_GROUP',
)
_SUCCESS_REASONS = ('unique_exact_evidence', 'approved_delta_rule',
                    'approved_trip_flight_delta', 'pinned_existing_link',
                    'merchant_amount_card_tail_without_payment_date')
_VERIFIED_EVIDENCE = ('paid_verified', 'refund_verified')
_KNOWN_EVIDENCE = _VERIFIED_EVIDENCE + (
    'scheduled', 'unknown', 'not_card_charge', 'conflict', 'evidence_conflict',
    'refund_conflict', 'paid_unverified', 'refund_unverified', 'reservation_only',
)
_WAITING_STATUSES = ('PENDING_PAYMENT', 'HOLD_DATE_UNKNOWN', 'HOLD_NO_CARD')
_MISSING_STATUSES = ('RESERVATION_ONLY', 'HOLD_AMOUNT_UNVERIFIED')


def _envelope(freshness):
    if type(freshness) is not dict:
        return False, 'INVALID_ENVELOPE', 'INVALID_FRESHNESS_ENVELOPE'
    status = freshness.get('status')
    stale = freshness.get('stale')
    refreshing = freshness.get('refreshing')
    generation = freshness.get('generation')
    fresh = freshness.get('fresh')
    enabled = freshness.get('enabled')
    if (type(status) is not str or status not in _FRESHNESS_STATES or
            type(stale) is not bool or type(refreshing) is not bool or
            (fresh is not None and type(fresh) is not bool) or
            ('fresh' in freshness and fresh is None) or
            (enabled is not None and type(enabled) is not bool) or
            ('enabled' in freshness and enabled is None) or
            (generation is None and status not in ('loading', 'error')) or
            (generation is not None and
             (type(generation) is not int or generation < 0))):
        return False, 'INVALID_ENVELOPE', 'INVALID_FRESHNESS_ENVELOPE'
    if status == 'error':
        return False, status, 'SNAPSHOT_ERROR'
    if status == 'loading':
        return False, status, 'SNAPSHOT_LOADING'
    if refreshing or status == 'refreshing':
        return False, 'refreshing', 'SNAPSHOT_REFRESHING'
    if enabled is False:
        return False, status, 'SNAPSHOT_DISABLED'
    if enabled is None and 'enabled' in freshness:
        return False, status, 'SNAPSHOT_ENABLEMENT_UNKNOWN'
    if fresh is False:
        return False, status, 'SNAPSHOT_NOT_FRESH'
    if 'fresh' in freshness and fresh is not True:
        return False, status, 'SNAPSHOT_FRESHNESS_UNKNOWN'
    if stale:
        return False, status, 'SNAPSHOT_STALE'
    if status != 'ready':
        return False, status, 'SNAPSHOT_NOT_READY'
    return True, status, None


def _result(queue, *codes, warning=False):
    return {'queue': queue, 'reason_codes': list(codes), 'warning': warning}


def _classify_ready_event(event, *, duplicate_identity=False):
    if type(event) is not dict:
        return _result('needs_action', 'MALFORMED_EVENT', warning=True)

    identity = event.get('ota_event_id')
    if type(identity) is not str or not identity.strip():
        return _result('needs_action', 'EVENT_ID_MISSING', warning=True)
    if duplicate_identity:
        return _result('needs_action', 'EVENT_ID_DUPLICATE', warning=True)

    codes = []
    warning = False
    for key, code in (('evidence_changed', 'EVIDENCE_CHANGED'),
                      ('evidence_missing', 'EVIDENCE_MISSING'),
                      ('review_warning', 'REVIEW_WARNING')):
        value = event.get(key)
        empty_warning = type(value) is str and value == ''
        if value is True or (value is not None and value is not False and not empty_warning):
            codes.append(code)
            warning = True

    status = event.get('status')
    reason = event.get('reason')
    evidence = event.get('evidence_status')
    if type(status) is not str:
        codes.append('STATUS_UNKNOWN')
        return _result('needs_action', *codes, warning=True)
    if status not in _KNOWN_STATUSES:
        codes.append('STATUS_UNKNOWN')
        return _result('needs_action', *codes, warning=True)
    if warning:
        return _result('needs_action', *codes, warning=True)
    evidence_known = type(evidence) is str and evidence in _KNOWN_EVIDENCE
    if not evidence_known:
        codes.append('EVIDENCE_UNKNOWN')
        return _result('needs_action', *codes, warning=True)
    relation = event.get('payment_relation')
    if (status in ('MATCHED_AUTO', 'MATCHED_GROUP') and evidence in _VERIFIED_EVIDENCE
            and event.get('payment_status') == 'paid' and isinstance(relation, dict)
            and relation.get('status') == 'LINKED' and relation.get('transaction_ids')
            and relation.get('group_transaction_ids') and relation.get('event_ids')):
        if relation.get('balance') == 'BALANCED' or relation.get('source_total_status') == 'OBSERVATIONS_NOT_DISTINCT_PAYMENTS':
            return _result('completed', *(codes + ['MATCHING_RELATION_RESOLVED']))
        return _result('needs_action', *(codes + ['LINKED_GROUP_AMOUNT_DIFFERENCE' if
            relation.get('balance') == 'AMOUNT_DIFFERENCE' else 'LINKED_GROUP_AMOUNT_UNVERIFIED']))
    if evidence in ('conflict', 'evidence_conflict', 'refund_conflict'):
        return _result('needs_action', 'PAYMENT_EVIDENCE_CONFLICT', warning=True)
    if status in ('HOLD_AMOUNT_MISMATCH', 'HOLD_EVIDENCE_CONFLICT',
                  'HOLD_AMBIGUOUS', 'HOLD_GROUP_CHANGED', 'HOLD_PARTIAL_GROUP'):
        codes.append('MATCHING_REVIEW_REQUIRED')
        return _result('needs_action', *codes)
    if status in _MISSING_STATUSES or evidence in (
            'unknown', 'not_card_charge', 'paid_unverified', 'refund_unverified'):
        codes.append('PAYMENT_EVIDENCE_MISSING')
        return _result('evidence_missing', *codes)
    if status in _WAITING_STATUSES:
        codes.append('SOURCE_OR_DATE_PENDING')
        return _result('waiting_source', *codes)
    if evidence == 'scheduled':
        codes.append('SCHEDULED_EVIDENCE_REVIEW')
        return _result('needs_action', *codes)

    if status in _MATCHED_STATUSES:
        if not evidence_known or evidence not in _VERIFIED_EVIDENCE:
            codes.append('PAYMENT_EVIDENCE_UNVERIFIED')
            return _result('needs_action', *codes, warning=True)
        if type(reason) is not str or reason not in _SUCCESS_REASONS:
            codes.append('MATCH_REASON_UNKNOWN')
            return _result('needs_action', *codes, warning=True)
        inferred = event.get('inferred_link')
        individual = event.get('individual_payment_evidence')
        allocation = event.get('allocation_basis')
        empty_allocation = type(allocation) is str and allocation == ''
        if (inferred is True or (inferred is not None and inferred is not False) or
                individual is False or (individual is not None and individual is not True) or
                (allocation is not None and not empty_allocation)):
            codes.append('INFERRED_OR_GROUP_MATCH')
            return _result('needs_action', *codes)
        payment_status = event.get('payment_status')
        if type(payment_status) is not str or payment_status != 'paid':
            codes.append('PAYMENT_STATUS_UNVERIFIED')
            return _result('evidence_missing', *codes)
        transaction_id = event.get('transaction_id')
        if type(transaction_id) is not str or not transaction_id.strip():
            codes.append('TRANSACTION_ID_MISSING')
            return _result('needs_action', *codes, warning=True)
        codes.append('MATCHING_REVIEW_RESOLVED')
        return _result('completed', *codes)

    if status == 'RESERVATION_ONLY':
        return _result('evidence_missing', *(codes + ['PAYMENT_EVIDENCE_MISSING']))
    if status == 'NOT_CARD_CHARGE':
        codes.append('PAYMENT_EVIDENCE_MISSING')
        return _result('evidence_missing', *codes)
    codes.append('STATUS_UNKNOWN')
    return _result('needs_action', *codes, warning=True)


def classify_event(event, freshness, *, duplicate_identity=False):
    """Return a queue label and finite reason codes without echoing raw values."""
    ready, _, freshness_code = _envelope(freshness)
    if not ready:
        return _result('auto_recheck', freshness_code, warning=True)
    return _classify_ready_event(event, duplicate_identity=duplicate_identity)


def summarize_queue(events, freshness, *, coverage):
    """Count every event as its own fallback group and report envelope scope."""
    if type(coverage) is not str or coverage not in ('canonical', 'public_subset'):
        raise ValueError("coverage must be 'canonical' or 'public_subset'")
    if isinstance(events, (str, bytes, Mapping)):
        raise ValueError('events must be an iterable of event mappings')
    try:
        iterator = iter(events)
    except Exception:
        raise ValueError('events must be an iterable of event mappings') from None

    ready, freshness_status, freshness_code = _envelope(freshness)
    records = []
    identities = {}
    row_count = 0
    warning_count = 0
    if not ready:
        for _ in iterator:
            row_count += 1
            warning_count += 1
    else:
        for event in iterator:
            identity = event.get('ota_event_id') if type(event) is dict else None
            valid_identity = type(identity) is str and bool(identity.strip())
            result = _classify_ready_event(event)
            index = len(records)
            records.append([result['queue'], result['warning'],
                            identity if valid_identity else None])
            warning_count += int(result['warning'])
            if valid_identity:
                identities.setdefault(identity, []).append(index)
        for indices in identities.values():
            if len(indices) > 1:
                for index in indices:
                    queue, had_warning, identity = records[index]
                    records[index] = ('needs_action', True, identity)
                    warning_count += int(not had_warning)

    counts = {queue: {'event_count': 0, 'group_count': 0} for queue in QUEUES}
    for queue, _, _ in records:
        bucket = counts[queue]
        bucket['event_count'] += 1
        bucket['group_count'] += 1
    if not ready:
        counts['auto_recheck']['event_count'] = row_count
        counts['auto_recheck']['group_count'] = row_count
    if not ready:
        warning_count += 1

    generation_value = freshness.get('generation') if type(freshness) is dict else None
    generation = generation_value if type(generation_value) is int and generation_value >= 0 else None
    stale_value = freshness.get('stale') if type(freshness) is dict else None
    stale = stale_value if type(stale_value) is bool else None
    refreshing_value = freshness.get('refreshing') if type(freshness) is dict else None
    refreshing = refreshing_value if type(refreshing_value) is bool else None
    fresh_value = freshness.get('fresh') if type(freshness) is dict else None
    fresh = fresh_value if type(fresh_value) is bool else None
    enabled_value = freshness.get('enabled') if type(freshness) is dict else None
    enabled = enabled_value if type(enabled_value) is bool else None
    state_tags = [] if ready else [freshness_code]
    safe_status = freshness_status if freshness_status in _FRESHNESS_STATES else 'unknown'
    if coverage == 'public_subset':
        state_tags.append('PUBLIC_SUBSET_NOT_FULL_CANONICAL')
    return {
        'coverage': coverage,
        'grouping': 'singleton_fallback',
        'snapshot_status': safe_status,
        'stale': stale,
        'refreshing': refreshing,
        'fresh': fresh,
        'enabled': enabled,
        'generation': generation,
        'counts_authoritative': bool(ready and coverage == 'canonical'),
        'counts_by_queue': counts,
        'warning_count': warning_count,
        'state_tags': state_tags,
    }
