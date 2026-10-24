"""토요코인 예약과 카드의 비결제 관계를 계산한다."""

def infer_links(events, searches, confirmed=None, occupied_transaction_ids=()):
    """Return reservation relation states without changing payment results."""
    confirmed = confirmed or {}
    claims = {}
    for event_id, trace in searches.items():
        for candidate in trace.get('candidates') or ():
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
        raw_candidates = list(trace.get('candidates') or ())
        candidates = [candidate for candidate in raw_candidates
                      if candidate.get('amount_status') in ('MATCH', 'UNKNOWN')]
        # A reservation cannot infer a specific room from group-total evidence.
        candidates = [candidate for candidate in candidates
                      if candidate.get('basis') != 'RESERVATION_GROUP_TOTAL_ONLY']
        viable = [candidate for candidate in candidates
                  if len(claims.get(str(candidate.get('transaction_id')), ())) == 1
                  and str(candidate.get('transaction_id')) not in set(map(str, occupied_transaction_ids))]
        status, chosen = 'NEEDS_REVIEW', None
        if (event.get('provider') == 'toyoko' and event.get('event_type') == 'reservation'
                and event.get('reservation_status') != 'cancelled'
                and not event.get('reservation_group_only') and len(viable) == 1
                and len(raw_candidates) == 1
                and viable[0].get('branch_status') == 'MATCH'
                and viable[0].get('stay_date_status') == 'MATCH'):
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
    event_fields = ('ota_event_id', 'provider', 'event_type', 'booking_ref', 'hotel_name',
                    'service_period', 'amount', 'currency', 'reservation_status',
                    'evidence_status', 'reservation_group_only')
    card_fields = ('transaction_id', 'source_hash', 'merchant', 'merchant_normalized',
                   'amount_krw', 'foreign_amount', 'foreign_currency', 'currency',
                   'approval_date', 'posting_date', 'card_id', 'card_tail', 'issuer',
                   'transaction_direction', 'direction', 'duplicate_of', 'parse_error',
                   'conflict_reason', 'ota_review_held', 'refund_status', 'cancellation_status',
                   'already_linked_event_id')
    return _digest({'event': {key: event.get(key) for key in event_fields},
                    'transaction': {key: transaction.get(key) for key in card_fields}})
