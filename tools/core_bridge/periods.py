"""Booking-period inputs for the Rust period rule, and the Python reference output (``verified_period_for``).

``facts`` reproduces what ``webapp.ledger_stay_evidence._build_index`` reads before it decides: per card
transaction, the candidate matches, the event and card columns the rule looks at, and the manual/blocked
flags. Rust (``cost_core::period``) applies the rule to these inputs; until the second cutover this
adapter supplies them. Nothing here writes.
"""
from __future__ import annotations

from collections import defaultdict

# Columns the Rust rule reads (core/crates/core/src/period.rs FACT_KEYS / EVENT_KEYS / CARD_KEYS).
FACT_KEYS = ('transaction_id', 'item', 'source_hash', 'reservation_status', 'evidence_pending', 'refund_pending',
             'period_conflict', 'booking_link_conflict', 'booking_ref', 'group_size', 'service_period_basis', 'period',
             'source_digests', 'evidence_digests', 'source_sha256', 'inferred_link', 'allocation_basis')
EVENT_KEYS = ('event_type', 'evidence_status', 'payment_status', 'source_digest', 'period_conflict', 'refund_status')
CARD_KEYS = ('source_hash', 'transaction_direction', 'ota_review_held', 'reservation_refund_blocked', 'refund_status')


def _pick(source, keys):
    return {key: source.get(key) for key in keys if key in source}


def facts_from_snapshot(data, manual):
    """transaction_id -> candidate list, from one OTA reconciliation snapshot (the screen's ``data``)."""
    from app.ota_core_projection import card_matches
    found = card_matches([], data)
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    blocked = {str(r.get('ota_event_id')) for r in data.get('results', []) if r.get('period_conflict')}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    by_source = defaultdict(list)
    for fact in found:
        by_source[fact.get('source_hash')].append(fact)
    out = defaultdict(list)
    for fact in found:
        tid = str(fact.get('transaction_id') or '')
        if not tid:
            continue
        card = cards.get(tid) or {}
        event_id = str(fact.get('ota_event_id'))
        event = events.get(event_id) or {}
        out[tid].append({
            'fact': _pick(fact, FACT_KEYS), 'event': _pick(event, EVENT_KEYS), 'card': _pick(card, CARD_KEYS),
            'event_blocked': event_id in blocked or bool(event.get('period_conflict')),
            'manual': 'card-' + tid in manual,
            'matches': [_pick(f, FACT_KEYS) for f in by_source[card.get('source_hash')]]})
    return dict(out)


def verified_from_snapshot(data, manual, rows):
    """row_id -> ``verified_period_for(row, index)`` with the index the screen builds from this snapshot."""
    from webapp.ledger_stay_evidence import index_from_snapshot, verified_period_for
    index = index_from_snapshot(data, set(manual))
    return {str(row.get('row_id')): verified_period_for(row, index) for row in rows}


def periods(request):
    """Bridge command: ``{data, manual, rows?}`` -> ``{facts, verified?}`` (nothing is applied)."""
    data, manual = request['data'], set(request.get('manual') or ())
    result = {'facts': facts_from_snapshot(data, manual)}
    if 'rows' in request:
        result['verified'] = verified_from_snapshot(data, manual, request['rows'])
    return result
