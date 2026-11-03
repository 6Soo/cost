"""Read current OTA stay evidence for old card ledger rows without rewriting them."""
from app.ota_core_projection import card_matches
from app.ota_mail import ledger_metadata
from collections import defaultdict


def stay_index(store):
    from . import ota_payment_review

    if store is None or not ota_payment_review.enabled():
        return {}
    # Reading a ledger must not start reconciliation or turn stale evidence into fact.
    service = getattr(store, '_ota_snapshot_service', None)
    if service is None:
        return {}
    current, state = service.display_context()
    if not current or not state.get('fresh'):
        return {}
    data = current.get('data') or {}
    facts = card_matches([], data)
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    blocked = {str(r.get('ota_event_id')) for r in data.get('results', [])
               if r.get('period_conflict')}
    by_source = defaultdict(list)
    for fact in facts:
        by_source[fact.get('source_hash')].append(fact)
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    with store._lock:
        manual = {str(r[0]) for r in store.conn.execute(
            "SELECT row_id FROM board_manual_overrides WHERE field='service_period'")}
    result = {}
    for fact in facts:
        tid = str(fact.get('transaction_id') or '')
        card = cards.get(tid) or {}
        event_id = str(fact.get('ota_event_id'))
        event = events.get(event_id) or {}
        period = fact.get('period')
        if (fact.get('item') != '숙박비' or 'card-' + tid in manual
                or not tid or not card.get('source_hash')
                or event_id in blocked or event.get('period_conflict')
                or fact.get('reservation_status') == 'refunded'
                or not isinstance(period, dict)
                or not period.get('starts_on') or not period.get('ends_on')):
            continue
        metadata = ledger_metadata({'matches': by_source[card.get('source_hash')]}, {
            'transaction_id': tid, 'source_hash': card.get('source_hash'),
            'transaction_direction': card.get('transaction_direction'), 'item': '숙박비',
        })
        if metadata.get('service_period'):
            result[tid] = metadata
    # Reservation dates can agree without identifying which room a card paid.
    # Keep that inference local to this read-only display, outside card_matches
    # and ledger_metadata, which supply financial/booking writes elsewhere.
    for tid, metadata in _toyoko_candidate_periods(data, manual).items():
        result.setdefault(tid, metadata)
    return result


def _toyoko_candidate_periods(data, manual):
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    occupied = {str(r.get('transaction_id')) for r in data.get('results', [])
                if r.get('transaction_id')}
    occupied.update(str(tid) for r in data.get('results', [])
                    for tid in r.get('reserved_card_ids') or ())
    occupied.update(str((r.get('reservation_link') or {}).get('transaction_id'))
                    for r in data.get('results', [])
                    if (r.get('reservation_link') or {}).get('transaction_id'))
    occupied.update(str(tid) for r in data.get('results', [])
                    if (r.get('payment_relation') or {}).get('status') == 'LINKED'
                    for tid in (r.get('payment_relation') or {}).get('transaction_ids') or ())
    occupied.update(str(link.get('transaction_id')) for link in (data.get('links') or {}).values()
                    if isinstance(link, dict) and link.get('transaction_id'))
    periods, blocked = defaultdict(set), set()
    for record in data.get('results', []):
        event = events.get(str(record.get('ota_event_id'))) or {}
        if event.get('provider') != 'toyoko' or event.get('event_type') != 'reservation':
            continue
        trace = record.get('candidate_search') or {}
        candidates = trace.get('candidates') or ()
        period = event.get('service_period') or {}
        unsafe = (record.get('status') != 'RESERVATION_ONLY'
                  or event.get('evidence_status') != 'reservation_only'
                  or event.get('source_trust') != 'sender_domain'
                  or not event.get('source_digest') or event.get('item') != '숙박비'
                  or event.get('reservation_status') not in ('observed', 'confirmed', 'completed')
                  or (record.get('reservation_link') or {}).get('status') == 'STALE'
                  or trace.get('status') != 'CANDIDATES_FOUND'
                  or any(obj.get(key) for obj in (event, record) for key in
                         ('evidence_missing', 'evidence_changed', 'period_conflict', 'service_period_conflict'))
                  or not period.get('starts_on') or not period.get('ends_on'))
        for candidate in candidates:
            tid = str(candidate.get('transaction_id') or '')
            if candidate.get('branch_status') != 'MATCH' or candidate.get('stay_date_status') != 'MATCH':
                continue
            if unsafe:
                blocked.add(tid)
            else:
                periods[tid].add((period['starts_on'], period['ends_on']))
    result = {}
    for tid, choices in periods.items():
        card = cards.get(tid) or {}
        if (len(choices) != 1 or tid in blocked or tid in occupied or 'card-' + tid in manual
                or not card.get('source_hash') or card.get('transaction_direction') != 'purchase'
                or any(card.get(key) for key in ('duplicate_of', 'parse_error', 'conflict_reason',
                                                'ota_review_held', 'reservation_refund_blocked'))
                or card.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')):
            continue
        start, end = next(iter(choices))
        result[tid] = {'booking_ref': '', 'service_period': start + '~' + end,
                       'ota_evidence': {'kind': 'reservation_period_inferred', 'payment_verified': False}}
    return result


def period_for(row, index):
    """An explicit stored value or a different saved reservation always wins."""
    stored = str(row.get('service_period') or '').strip()
    if stored:
        return stored
    row_id = str(row.get('row_id') or '')
    if not row_id.startswith('card-'):
        return ''
    tid = str(row.get('source_event_id') or row_id[5:])
    if row_id != 'card-' + tid:
        return ''
    found = index.get(tid) or {}
    reservation = str(row.get('reservation_no') or '').strip()
    if reservation and reservation != found.get('booking_ref'):
        return ''
    return found.get('service_period') or ''
