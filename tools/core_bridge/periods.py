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


FLIGHTS_KEY = '@flights'  # core/crates/core/src/period.rs FLIGHTS_KEY
BASES = {'p2': 'p2_run', 'reservation': 'reservation_only', 'candidates': 'candidate_agreement'}  # InferredBasis::as_str


def p2_index(entries):
    """request ``p2`` entries -> the index shape of ``app.ai_classification.service_metadata`` (tests and goldens)."""
    return {str(e['transaction_id']): {
        'service_period': e['service_period'],
        'ota_evidence': {'kind': 'reservation_period_inferred', 'source': 'P2', 'payment_verified': False,
                         'execution': {'run_id': e.get('run_id'), 'model': e.get('model')},
                         'source_hash': e.get('source_hash'), 'decision_revision': e.get('decision_revision'),
                         'item': e.get('item'), 'evidence_refs': list(e.get('evidence_refs') or [])}}
        for e in entries}


def stay_index(data, manual, p2=None):
    """The screen's stay index for a snapshot, with the P2 periods merged as ``stay_index`` does."""
    from webapp.ledger_stay_evidence import _with_p2, index_from_snapshot
    index = index_from_snapshot(data, set(manual))
    return _with_p2(index, p2, data) if p2 else index


def inferred_from_snapshot(data, manual, p2=None):
    """transaction_id -> the inferred period (DATE-080, DATE-101, P2) the screen shows without verification.

    Only derived facts: the period, the booking numbers the row must agree with, the kind of basis, and for P2
    the run and source identifiers. A guarantee hold (card_preauthorization) is not a stay and is left out.
    """
    from app.ota_matching_defaults import provider_resolution_scope
    from webapp.ledger_stay_evidence import _toyoko_candidate_periods
    index = stay_index(data, manual, p2)
    with provider_resolution_scope():
        toyoko = set(_toyoko_candidate_periods(data, set(manual)))
    out = {}
    for tid, entry in index.items():
        evidence = entry.get('ota_evidence') or {}
        if evidence.get('kind') != 'reservation_period_inferred' or not entry.get('service_period'):
            continue
        p2_source = evidence.get('source') == 'P2'
        item = {'period': entry['service_period'], 'booking_ref': entry.get('booking_ref') or '',
                'booking_refs': list(entry.get('booking_refs') or []),
                'basis': BASES['p2' if p2_source else 'candidates' if tid in toyoko else 'reservation']}
        if p2_source:
            execution = evidence.get('execution') or {}
            item['p2'] = {'run_id': execution.get('run_id'), 'model': execution.get('model'),
                          'source_hash': evidence.get('source_hash'), 'item': evidence.get('item'),
                          'decision_revision': evidence.get('decision_revision'),
                          'evidence_ref_count': len(evidence.get('evidence_refs') or [])}
        out[str(tid)] = item
    return out


def flights_from_snapshot(data, manual):
    """``{'days': {booking_ref: [ISO days]}, 'manual': [transaction ids]}``: saved flight bookings with usable legs."""
    from webapp.ledger_stay_evidence import flight_departure_days
    days = {}
    for ref, found in sorted((data.get('passengers') or {}).items()):
        usable = flight_departure_days(found)
        if usable:
            days[str(ref)] = [day.isoformat() for day in usable]
    if not days:
        return {}
    return {'days': days, 'manual': sorted(m[5:] for m in manual if m.startswith('card-'))}


def evidence_from_snapshot(data, manual, p2=None):
    """The ``context.periods`` value for Rust: ``facts_from_snapshot`` plus inferred periods and flight evidence.

    A transaction with an inferred period becomes ``{'candidates': [...], 'inferred': {...}}``; the others keep
    the candidate list. Flight evidence sits under the reserved key ``@flights``.
    """
    facts = facts_from_snapshot(data, manual)
    for tid, inferred in inferred_from_snapshot(data, manual, p2).items():
        facts[tid] = {'candidates': facts.get(tid, []), 'inferred': inferred}
    flights = flights_from_snapshot(data, set(manual))
    if flights:
        facts[FLIGHTS_KEY] = flights
    return facts


def found_from_snapshot(data, manual, rows, p2=None):
    """row_id -> what the screen's rules give a blank row, in the order the Rust rule applies them.

    Stored value or verified link (``verified_period_for``), then the flight bookings (``flight_departure_days``),
    then the screen-only inference (``period_for``). ``kind`` is verified, inferred or none.
    """
    from webapp.ledger_stay_evidence import period_for, verified_period_for
    index = stay_index(data, manual, p2)
    flights = flights_from_snapshot(data, set(manual)).get('days', {})
    inferred = inferred_from_snapshot(data, manual, p2)
    out = {}
    for row in rows:
        row_id = str(row.get('row_id'))
        verified = verified_period_for(row, index)
        ref = str(row.get('reservation_no') or '').strip()
        tid = str(row.get('source_event_id') or row_id[5:])
        if verified:
            out[row_id] = {'kind': 'verified', 'period': verified}
        elif row.get('item') == '항공료' and ref and ref in flights and 'card-' + tid not in manual:
            out[row_id] = {'kind': 'verified', 'period': flights[ref][0] + '~' + flights[ref][-1]}
        elif tid in inferred and period_for(row, index):
            out[row_id] = {'kind': 'inferred', 'period': period_for(row, index), 'basis': inferred[tid]['basis']}
        else:
            out[row_id] = {'kind': 'none', 'period': ''}
    return out


def periods(request):
    """Bridge command: ``{data, manual, rows?}`` -> ``{facts, verified?}`` (nothing is applied).

    With ``inference`` set the answer also carries ``inferred``, ``flights`` and ``found`` (the new evidence
    kinds); without it the output is the one the first golden cases were written with.
    """
    data, manual = request['data'], set(request.get('manual') or ())
    result = {'facts': facts_from_snapshot(data, manual)}
    if 'rows' in request:
        result['verified'] = verified_from_snapshot(data, manual, request['rows'])
    if request.get('inference'):
        p2 = p2_index(request.get('p2') or [])
        result['inferred'] = inferred_from_snapshot(data, manual, p2)
        result['flights'] = flights_from_snapshot(data, manual)
        if 'rows' in request:
            result['found'] = found_from_snapshot(data, manual, request['rows'], p2)
    return result
