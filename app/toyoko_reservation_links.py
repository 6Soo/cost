"""토요코인 예약과 카드의 비결제 관계를 계산한다."""

def infer_links(events, searches, confirmed=None):
    """Return reservation relation states without changing payment results."""
    confirmed = confirmed or {}
    claims = {}
    for event_id, trace in searches.items():
        for candidate in trace.get('candidates') or ():
            if candidate.get('amount_status') in ('MATCH', 'UNKNOWN'):
                claims.setdefault(str(candidate.get('transaction_id')), set()).add(str(event_id))
    for event_id, relation in confirmed.items():
        transaction_id = relation.get('transaction_id') if isinstance(relation, dict) else None
        if transaction_id:
            claims.setdefault(str(transaction_id), set()).add(str(event_id))
    result = {}
    for event in events:
        event_id = str(event.get('ota_event_id') or '')
        saved = confirmed.get(event_id)
        if saved:
            result[event_id] = dict(saved)
            continue
        trace = searches.get(event_id, {})
        candidates = [candidate for candidate in trace.get('candidates') or ()
                      if candidate.get('amount_status') in ('MATCH', 'UNKNOWN')]
        # A reservation cannot infer a specific room from group-total evidence.
        candidates = [candidate for candidate in candidates
                      if candidate.get('basis') != 'RESERVATION_GROUP_TOTAL_ONLY']
        viable = [candidate for candidate in candidates
                  if len(claims.get(str(candidate.get('transaction_id')), ())) == 1]
        status, chosen = 'NEEDS_REVIEW', None
        if (event.get('provider') == 'toyoko' and event.get('event_type') == 'reservation'
                and event.get('reservation_status') != 'cancelled'
                and not event.get('reservation_group_only') and len(viable) == 1
                and len(candidates) == 1):
            chosen = viable[0]
            status = 'INFERRED'
        result[event_id] = {'status': status,
                            'transaction_id': str(chosen['transaction_id']) if chosen else None,
                            'basis': chosen.get('basis') if chosen else trace.get('status'),
                            'amount_status': chosen.get('amount_status') if chosen else None,
                            'payment_verified': False}
    return result


def relation_digest(event, transaction):
    from app.ota_payments import _digest
    return _digest({'event': event, 'transaction': transaction})
