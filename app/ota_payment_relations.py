"""M:N evidence relations, without inventing one-to-one financial allocations."""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json


def _amount(value):
    try:
        amount = Decimal(str(value))
        return abs(amount) if amount.is_finite() and amount else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def attach_relations(events, cards, options, results, *, existing_links):
    """Preserve every admissible edge; account for each distinct card only once.

    The allocator already excludes user-owned cards and frozen groups. Its
    partial/ambiguous automatic allocation must not erase an evidence relation.
    Changed pins, missing evidence and explicit conflicts remain untouched.
    """
    by_id = {str(event.get('ota_event_id')): event for event in events}
    by_result = {str(row.get('ota_event_id')): row for row in results}
    allowed = {'MATCHED_AUTO', 'HOLD_AMBIGUOUS', 'HOLD_PARTIAL_GROUP', 'HOLD_DATE_UNKNOWN'}
    edges = {}
    reverse = defaultdict(set)
    for identity, candidates in options.items():
        event, result = by_id.get(identity), by_result.get(identity)
        if (not event or not result or identity in existing_links or result.get('status') not in allowed
                or any(event.get(key) or result.get(key) for key in
                       ('evidence_changed', 'evidence_missing', 'service_period_conflict', 'period_conflict'))):
            continue
        ids = {str(card['transaction_id']) for card in candidates if card.get('transaction_id')}
        if ids:
            edges[identity] = ids
            for card_id in ids:
                reverse[card_id].add(identity)
    visited = set()
    relations = {}
    for first in sorted(edges):
        if first in visited:
            continue
        pending, event_ids, card_ids = [first], set(), set()
        while pending:
            identity = pending.pop()
            if identity in event_ids:
                continue
            event_ids.add(identity)
            for card_id in edges[identity]:
                card_ids.add(card_id)
                pending.extend(reverse[card_id] - event_ids)
        visited.update(event_ids)
        event_ids, card_ids = sorted(event_ids), sorted(card_ids)
        currencies = {str(by_id[i].get('currency') or '').upper() for i in event_ids}
        currency = next(iter(currencies)) if len(currencies) == 1 else None
        amounts = [_amount(by_id[i].get('amount_krw') if currency == 'KRW' else by_id[i].get('amount'))
                   for i in event_ids]
        card_amounts = [_amount(cards[i].get('amount_krw') if currency == 'KRW' else
                               cards[i].get('foreign_amount')) for i in card_ids]
        bookings = [(str(by_id[i].get('provider') or ''), str(by_id[i].get('booking_ref') or i))
                    for i in event_ids]
        booking_counts = Counter(bookings)
        payment_amounts = {}
        observations_not_distinct = False
        for identity, booking, amount in zip(event_ids, bookings, amounts):
            source = by_id[identity]
            payment = source.get('payment_event_id')
            if not payment and source.get('payment_id') and source.get('payment_id_scheme'):
                payment = (source.get('provider'), source.get('payment_id_scheme'), source['payment_id'])
            if booking_counts[booking] > 1 and not payment:
                observations_not_distinct = True
            key = str(payment) if payment else identity
            if key in payment_amounts and payment_amounts[key] != amount:
                observations_not_distinct = True
            payment_amounts[key] = amount
        source_total = (sum(payment_amounts.values()) if currency and not observations_not_distinct
                        and all(a is not None for a in amounts) else None)
        card_total = sum(card_amounts) if currency and all(a is not None for a in card_amounts) else None
        balance = ('UNKNOWN' if source_total is None or card_total is None else
                   'BALANCED' if source_total == card_total else 'AMOUNT_DIFFERENCE')
        group_id = 'ota-relation-' + hashlib.sha256(json.dumps([event_ids, card_ids]).encode()).hexdigest()
        for identity in event_ids:
            event = by_id[identity]
            relations[identity] = dict(status='LINKED', relation_id=group_id,
                event_ids=event_ids, transaction_ids=sorted(edges[identity]), group_transaction_ids=card_ids,
                event_count=len(event_ids), card_count=len(card_ids), currency=currency,
                booking_count=len(booking_counts),
                source_total_status='OBSERVATIONS_NOT_DISTINCT_PAYMENTS' if observations_not_distinct else
                                    'VERIFIED_PAYMENT_TOTAL' if source_total is not None else 'AMOUNT_UNVERIFIED',
                source_total=str(source_total) if source_total is not None else None,
                card_total=str(card_total) if card_total is not None else None,
                balance=balance, payment_date_verified=bool(event.get('paid_on')),
                basis='merchant_amount_card_tail_without_payment_date' if not event.get('paid_on') else
                      'verified_payment_edges',
                individual_payment_verified=len(event_ids) == len(card_ids) == 1)
    output = []
    for result in results:
        relation = relations.get(str(result.get('ota_event_id')))
        if relation:
            result = dict(result, payment_relation=relation)
            if result.get('status') in {'HOLD_AMBIGUOUS', 'HOLD_PARTIAL_GROUP'}:
                result.update(status='MATCHED_GROUP', reason='many_to_many_payment_relation',
                              transaction_id=None, individual_payment_evidence=False)
        output.append(result)
    return output


def catalog_links(data):
    """Read-only reservation evidence; cancelled bookings keep their payment link."""
    events = {str(e.get('ota_event_id')): e for e in data.get('events', ())}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', ())}
    links = defaultdict(dict)
    for result in data.get('results', ()):
        relation = result.get('payment_relation') or {}
        event = events.get(str(result.get('ota_event_id')), {})
        if relation.get('status') != 'LINKED' or not event.get('booking_ref'):
            continue
        key = (str(event.get('provider') or ''), str(event['booking_ref']))
        for identity in relation.get('transaction_ids') or ():
            card = cards.get(str(identity))
            if not card:
                continue
            links[key][str(identity)] = dict(transaction_id=str(identity), merchant=card.get('merchant') or '',
                day=card.get('approval_date') or '', amount_krw=card.get('amount_krw'),
                event_count=relation.get('event_count'), card_count=relation.get('card_count'),
                booking_count=relation.get('booking_count'),
                balance=relation.get('balance'), payment_date_verified=relation.get('payment_date_verified'))
    return {key: [values[i] for i in sorted(values)] for key, values in links.items()}
