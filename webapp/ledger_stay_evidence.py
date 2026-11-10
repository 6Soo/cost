"""Read current OTA service dates for old card ledger rows without rewriting them."""
from app.ota_core_projection import card_matches
from app.ota_mail import ledger_metadata
from collections import defaultdict
import threading

_INDEX_LOCK = threading.Lock()
_INDEX_MEMO = {}


def stay_index(store):
    from . import ota_payment_review

    if store is None or not ota_payment_review.enabled():
        return {}
    # Reading a ledger must not start reconciliation or turn stale evidence into fact.
    service = getattr(store, '_ota_snapshot_service', None)
    if service is None:
        return {}
    # The last complete generation stays on screen while the next one is computed or retried;
    # a refresh takes minutes and dropping every date meanwhile hid verified evidence.
    current, _state = service.display_context()
    if not current or current.get('data') is None:
        return {}
    with store._lock:
        manual = {str(r[0]) for r in store.conn.execute(
            "SELECT row_id FROM board_manual_overrides WHERE field='service_period'")}
    # One snapshot generation and the same manual overrides give the same index; build it once.
    memo_key = (id(store), id(current), current.get('key'), frozenset(manual))
    with _INDEX_LOCK:
        if _INDEX_MEMO.get('key') == memo_key and _INDEX_MEMO.get('current') is current:
            return _INDEX_MEMO['result']
    from app.ota_matching_defaults import provider_resolution_scope
    with provider_resolution_scope():
        result = _build_index(current.get('data') or {}, manual)
    with _INDEX_LOCK:
        _INDEX_MEMO.update(key=memo_key, current=current, result=result)
    return result


def _build_index(data, manual):
    facts = card_matches([], data)
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    blocked = {str(r.get('ota_event_id')) for r in data.get('results', [])
               if r.get('period_conflict')}
    by_source = defaultdict(list)
    for fact in facts:
        by_source[fact.get('source_hash')].append(fact)
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    result = {}
    for fact in facts:
        tid = str(fact.get('transaction_id') or '')
        card = cards.get(tid) or {}
        event_id = str(fact.get('ota_event_id'))
        event = events.get(event_id) or {}
        period = fact.get('period')
        if (fact.get('item') not in ('숙박비', '항공료', '렌터카') or 'card-' + tid in manual
                or not tid or not card.get('source_hash')
                or event_id in blocked or event.get('period_conflict')
                or fact.get('reservation_status') == 'refunded'
                or not isinstance(period, dict)
                or not period.get('starts_on') or not period.get('ends_on')):
            continue
        if fact.get('item') in ('항공료', '렌터카'):
            if (event.get('event_type') != 'charge'
                    or event.get('evidence_status') != 'paid_verified'
                    or event.get('payment_status') != 'paid'
                    or not event.get('source_digest')
                    or any(card.get(key) for key in ('ota_review_held', 'reservation_refund_blocked'))
                    or any(obj.get('refund_status') in ('refund_pending', 'refund_requested',
                                                       'refunded', 'refund_completed')
                           for obj in (card, event))):
                continue
        metadata = ledger_metadata({'matches': by_source[card.get('source_hash')]}, {
            'transaction_id': tid, 'source_hash': card.get('source_hash'),
            'transaction_direction': card.get('transaction_direction'), 'item': fact['item'],
        })
        if metadata.get('service_period'):
            result[tid] = metadata
    # Reservation dates can agree without identifying which room a card paid.
    # Keep that inference local to this read-only display, outside card_matches
    # and ledger_metadata, which supply financial/booking writes elsewhere.
    for tid, metadata in _toyoko_candidate_periods(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _linked_candidate_periods(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _rakuten_candidate_periods(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _skyticket_candidate_periods(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _agoda_recorded_card_periods(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _trip_price_change_periods(data, manual).items():
        result.setdefault(tid, metadata)
    return result


def _trip_price_change_periods(data, manual):
    """A Trip.com lodging price change's stay, for the one card charged its rise on the notice day.

    The rise is reservation evidence only; no payment or relation is created.
    """
    from datetime import date
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    occupied = _occupied_cards(data)
    claims, chosen = defaultdict(set), {}
    for record in data.get('results', []):
        event = events.get(str(record.get('ota_event_id'))) or {}
        if (event.get('provider') != 'trip' or not event.get('price_change_amount_krw')
                or record.get('status') != 'RESERVATION_ONLY'):
            continue
        trace = record.get('candidate_search') or {}
        candidates = trace.get('candidates') or ()
        period = event.get('service_period') or {}
        try:
            start, end = (date.fromisoformat(period[key]) for key in ('starts_on', 'ends_on'))
            valid = 0 <= (end - start).days <= 366
        except (KeyError, TypeError, ValueError):
            valid = False
        if (not valid or trace.get('status') != 'CANDIDATES_FOUND' or len(candidates) != 1
                or not event.get('source_digest') or not event.get('booking_ref')
                or event.get('reservation_status') == 'cancelled' or event.get('refund_status')
                or any(obj.get(k) for obj in (event, record)
                       for k in ('evidence_missing', 'evidence_changed', 'period_conflict', 'service_period_conflict'))):
            continue
        candidate = candidates[0]
        tid = str(candidate.get('transaction_id') or '')
        if candidate.get('basis') != 'PRICE_CHANGE_RISE_AND_DAY' or candidate.get('payment_verified') is not False or not tid:
            continue
        claims[tid].add(str(event['ota_event_id']))
        chosen[tid] = (start.isoformat() + '~' + end.isoformat(), str(event['booking_ref']))
    result = {}
    for tid, (period, booking_ref) in chosen.items():
        card = cards.get(tid) or {}
        if (len(claims[tid]) != 1 or tid in occupied or 'card-' + tid in manual
                or card.get('transaction_direction') != 'purchase' or not card.get('source_hash')
                or any(card.get(k) for k in ('duplicate_of', 'parse_error', 'conflict_reason',
                                             'ota_review_held', 'reservation_refund_blocked'))
                or card.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')):
            continue
        result[tid] = {'booking_ref': booking_ref, 'booking_refs': [booking_ref], 'service_period': period,
                       'ota_evidence': {'kind': 'reservation_period_inferred', 'payment_verified': False}}
    return result


def _occupied_cards(data):
    """Cards another result, reservation link, linked payment relation or saved link already claims."""
    results = data.get('results', [])
    occupied = {str(r['transaction_id']) for r in results if r.get('transaction_id')}
    occupied.update(str(tid) for r in results for tid in r.get('reserved_card_ids') or ())
    occupied.update(str(tid) for r in results if (r.get('payment_relation') or {}).get('status') == 'LINKED'
                    for tid in (r.get('payment_relation') or {}).get('transaction_ids') or ())
    occupied.update(str((r.get('reservation_link') or {}).get('transaction_id')) for r in results
                    if (r.get('reservation_link') or {}).get('transaction_id'))
    occupied.update(str(link.get('transaction_id')) for link in (data.get('links') or {}).values()
                    if isinstance(link, dict) and link.get('transaction_id'))
    return occupied


def _decimal(value, *, absolute=False):
    from decimal import Decimal, InvalidOperation
    try:
        number = Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return abs(number).normalize() if absolute else number.normalize()


def _agoda_recorded_card_periods(data, manual):
    """The owner-approved mutually unique Agoda pairing, read for cards already on a ledger.

    The core applies it only to still-open cards, so a recorded card never learns its
    stay. This display reads the same pairing without opening, linking or rewriting it.
    """
    from app import ota_inference
    from app.ota_matching_defaults import provider_resolution_scope
    from datetime import date
    with provider_resolution_scope():
        return _agoda_recorded_card_periods_in_scope(data, manual, ota_inference, date)


def _agoda_recorded_card_periods_in_scope(data, manual, ota_inference, date):
    occupied = _occupied_cards(data)
    events = [event for event in data.get('events', [])
              if not any(event.get(key) for key in ('evidence_missing', 'evidence_changed', 'period_conflict'))]
    # The pairing compares card tail and exact amount; only cards sharing both with an
    # undated Agoda event can take part, so the rest are left out before the full check.
    keys = {(str(e.get('card_last4') or ''), amount) for e in events
            if e.get('provider') == 'agoda' and not e.get('paid_on')
            for amount in (_decimal(e.get('amount'), absolute=True), _decimal(e.get('amount_krw'), absolute=True))
            if amount is not None}
    tails = {tail for tail, _ in keys}
    cards = [dict(card, ota_inference_eligible=True) for card in data.get('transactions', [])
             if str(card.get('card_tail') or card.get('card_last4') or '') in tails
             and any((str(card.get('card_tail') or card.get('card_last4') or ''), amount) in keys
                     for amount in (_decimal(card.get('amount_krw'), absolute=True),
                                    _decimal(card.get('foreign_amount'), absolute=True)) if amount is not None)]
    result = {}
    for identity, row in ota_inference.unique_pairs(events, cards, occupied=occupied).items():
        tid = str(row['transaction_id'])
        event = next(e for e in events if e.get('ota_event_id') == identity)
        period = event['service_period']
        try:
            valid = 0 <= (date.fromisoformat(period['ends_on']) - date.fromisoformat(period['starts_on'])).days <= 366
        except (KeyError, TypeError, ValueError):
            valid = False
        if (not valid or 'card-' + tid in manual or not row.get('source_hash')
                or any(row.get(k) for k in ('ota_review_held', 'reservation_refund_blocked'))
                or row.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')):
            continue
        result[tid] = {'booking_ref': str(event['booking_ref']), 'booking_refs': [str(event['booking_ref'])],
                       'service_period': period['starts_on'] + '~' + period['ends_on'],
                       'ota_evidence': {'kind': 'reservation_period_inferred', 'payment_verified': False}}
    for tid, metadata in _agoda_identical_room_periods(events, cards, occupied, manual, date).items():
        result.setdefault(tid, metadata)
    return result


def _agoda_identical_room_periods(events, cards, occupied, manual, date):
    """Identical rooms booked together: N equal cards and N equal bookings pair only as a group.

    When every booking in the group states the same stay, each card's stay is known even though
    which card paid which room is not. Display only; no link or payment is created.
    """
    import re
    from app import ota_payments as payments
    eligible = [e for e in events
                if e.get('provider') == 'agoda' and not e.get('paid_on') and e.get('event_type') == 'charge'
                and e.get('verified_portal_snapshot') is True and payments._event_is_paid(e)
                and e.get('reservation_status') in ('confirmed', 'completed')
                and e.get('refund_status') in (None, '', 'none_displayed')
                and re.fullmatch(r'\d{4}', str(e.get('card_last4') or ''))]
    groups = defaultdict(list)
    for event in eligible:
        groups[(event['card_last4'], str(event.get('currency') or '').upper(),
                _decimal(event.get('amount'), absolute=True))].append(event)
    result = {}
    for (_, _, amount), group in groups.items():
        refs = {str(e.get('booking_ref')) for e in group}
        if amount is None or len(group) < 2 or len(refs) != len(group):
            continue
        periods = {(str((e.get('service_period') or {}).get('starts_on')), str((e.get('service_period') or {}).get('ends_on')))
                   for e in group}
        if len(periods) != 1:
            continue
        start, end = next(iter(periods))
        try:
            if not 0 < (date.fromisoformat(end) - date.fromisoformat(start)).days <= 366:
                continue
        except ValueError:
            continue
        related = [e for e in events if e.get('provider') == 'agoda' and str(e.get('booking_ref')) in refs]
        if any(e.get('reservation_status') == 'cancelled' or e.get('event_type') == 'refund'
               or e.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')
               or e.get('service_period_conflict')
               or (e.get('service_period') and (str(e['service_period'].get('starts_on')),
                                                str(e['service_period'].get('ends_on'))) != (start, end))
               for e in related):
            continue
        sample = group[0]

        def same_amount(row):
            # Some card files give the foreign amount without its currency.
            return payments._amount_matches(sample, row, []) or (
                not str(row.get('foreign_currency') or '').strip()
                and str(sample.get('currency') or '').upper() not in ('', 'KRW')
                and _decimal(row.get('foreign_amount'), absolute=True) == amount)

        matched = [row for row in cards if payments._direction(row) == 'purchase' and not row.get('duplicate_of')
                   and payments.provider_compatible(sample, row, ())
                   and payments._strict_card_identity(sample, row) and same_amount(row)]
        if (len(matched) != len(group)
                or any(str(row['transaction_id']) in occupied for row in matched)):
            continue
        for row in matched:
            tid = str(row['transaction_id'])
            if ('card-' + tid in manual or not row.get('source_hash')
                    or any(row.get(k) for k in ('ota_review_held', 'reservation_refund_blocked', 'parse_error', 'conflict_reason'))
                    or row.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')):
                continue
            result[tid] = {'booking_ref': '', 'booking_refs': sorted(refs), 'service_period': start + '~' + end,
                           'ota_evidence': {'kind': 'reservation_period_inferred', 'payment_verified': False}}
    return result


def _skyticket_candidate_periods(data, manual):
    """A paid skyticket mail without a payment day names its departure days for the one card it equals.

    The mail carries no card tail or charge day, so the core keeps it undated and
    unlinked. Merchant, exact KRW total and a one-to-one pairing only inform this
    read-only display; no payment, trip or reservation relation is created.
    """
    from datetime import date
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    occupied = _occupied_cards(data)
    by_booking = defaultdict(list)
    for event in events.values():
        by_booking[(event.get('provider'), event.get('booking_ref'))].append(event)
    claims = defaultdict(set)
    chosen = {}
    for record in data.get('results', []):
        event = events.get(str(record.get('ota_event_id'))) or {}
        if event.get('provider') != 'skyticket' or record.get('status') != 'HOLD_DATE_UNKNOWN':
            continue
        trace = record.get('candidate_search') or {}
        candidates = trace.get('candidates') or ()
        period = event.get('service_period') or {}
        try:
            start, end = (date.fromisoformat(period[key]) for key in ('starts_on', 'ends_on'))
            valid = 0 <= (end - start).days <= 366
        except (KeyError, TypeError, ValueError):
            valid = False
        related = by_booking[(event.get('provider'), event.get('booking_ref'))]
        if (not valid or trace.get('status') != 'CANDIDATES_FOUND' or len(candidates) != 1
                or event.get('event_type') != 'charge' or event.get('evidence_status') != 'paid_verified'
                or event.get('payment_status') != 'paid' or event.get('evidence_kind') != 'authenticated_payment_mail'
                or str(event.get('currency') or '').upper() != 'KRW'
                or not event.get('source_digest') or not event.get('booking_ref')
                or any(e.get('evidence_status') != 'paid_verified' or e.get('event_type') != 'charge'
                       or e.get('service_period') != period or e.get('refund_status')
                       or e.get('period_conflict') or e.get('service_period_conflict')
                       or e.get('reservation_status') in ('cancelled', 'refunded') for e in related)
                or any(record.get(key) for key in ('evidence_missing', 'evidence_changed', 'period_conflict'))):
            continue
        candidate = candidates[0]
        tid = str(candidate.get('transaction_id') or '')
        if candidate.get('basis') != 'EXACT_AMOUNT_AND_CARD_EVIDENCE' or candidate.get('resolution_allowed') is not False or not tid:
            continue
        claims[tid].add(str(event.get('booking_ref')))
        chosen[tid] = (start.isoformat() + '~' + end.isoformat(), str(event.get('booking_ref')))
    result = {}
    for tid, (period, booking_ref) in chosen.items():
        card = cards.get(tid) or {}
        if (len(claims[tid]) != 1 or tid in occupied or 'card-' + tid in manual
                or card.get('transaction_direction') != 'purchase' or not card.get('source_hash')
                or any(card.get(k) for k in ('duplicate_of', 'parse_error', 'conflict_reason',
                                             'ota_review_held', 'reservation_refund_blocked'))
                or card.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')):
            continue
        result[tid] = {'booking_ref': booking_ref, 'booking_refs': [booking_ref], 'service_period': period,
                       'item': '항공료',
                       'ota_evidence': {'kind': 'reservation_period_inferred', 'payment_verified': False}}
    return result


def _rakuten_candidate_periods(data, manual):
    """A quoted booking amount can corroborate dates without verifying an OTA payment."""
    from datetime import date
    events={str(e.get('ota_event_id')):e for e in data.get('events',[])}
    cards={str(c.get('transaction_id')):c for c in data.get('transactions',[])}
    occupied=_occupied_cards(data)
    choices=defaultdict(set);refs=defaultdict(set);blocked=set()
    flags=('evidence_missing','evidence_changed','period_conflict','service_period_conflict','reservation_amount_conflict')
    for record in data.get('results',[]):
        event=events.get(str(record.get('ota_event_id'))) or {}
        if event.get('provider')!='rakuten':continue
        trace=record.get('candidate_search') or {}
        unsafe=(record.get('status')!='RESERVATION_ONLY' or trace.get('status')!='CANDIDATES_FOUND'
                or event.get('source_trust')!='authenticated_mail' or not event.get('source_digest')
                or event.get('event_type')!='reservation' or event.get('evidence_status')!='reservation_only'
                or event.get('item')!='숙박비' or not event.get('booking_ref')
                or event.get('reservation_status') not in ('observed','confirmed','completed')
                or event.get('refund_status') in ('refund_pending','refund_requested','refunded','refund_completed')
                or any(obj.get(k) for obj in (event,record) for k in flags))
        period=event.get('service_period') or {}
        try:
            start,end=(date.fromisoformat(period[k]) for k in ('starts_on','ends_on'))
            unsafe=unsafe or not 0<=(end-start).days<=366
        except (KeyError,TypeError,ValueError):unsafe=True
        for candidate in trace.get('candidates') or ():
            if any(candidate.get(k)!='MATCH' for k in ('provider_status','card_tail_status','reservation_date_status','amount_status')):
                continue
            if candidate.get('payment_verified') is not False or candidate.get('resolution_allowed') is not False:
                continue
            tid=str(candidate.get('transaction_id') or '')
            if unsafe:blocked.add(tid)
            else:
                choices[tid].add((start.isoformat(),end.isoformat()))
                refs[tid].add(str(event.get('booking_ref') or ''))
    result={}
    for tid,periods in choices.items():
        card=cards.get(tid) or {}
        if (len(periods)!=1 or tid in blocked or tid in occupied or 'card-'+tid in manual
                or card.get('transaction_direction')!='purchase' or not card.get('source_hash')
                or any(card.get(k) for k in ('duplicate_of','parse_error','conflict_reason','ota_review_held','reservation_refund_blocked'))
                or card.get('refund_status') in ('refund_pending','refund_requested','refunded','refund_completed')):continue
        start,end=next(iter(periods))
        result[tid]={'booking_ref':next(iter(refs[tid])) if len(refs[tid])==1 else '',
            'booking_refs':sorted(refs[tid]),'service_period':start+'~'+end,
            'ota_evidence':{'kind':'reservation_period_inferred','payment_verified':False}}
    return result


def _linked_candidate_periods(data, manual):
    """Display a shared period from core links, without inventing individual bookings.

    Core M:N relations may contain several observations of one stay. They do not
    enter card_matches(), whose metadata is also used for financial writes.
    """
    from datetime import date

    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    claims = defaultdict(list)
    for record in data.get('results', []):
        if record.get('status') in ('MATCHED_AUTO', 'MATCHED_USER'):
            identities = [record.get('transaction_id')]
            event_ids = [record.get('ota_event_id')]
        elif record.get('status') == 'MATCHED_GROUP':
            relation = record.get('payment_relation') or {}
            if relation.get('status') != 'LINKED':
                continue
            identities = relation.get('transaction_ids') or []
            event_ids = relation.get('event_ids') or []
            if not event_ids or record.get('ota_event_id') not in event_ids:
                continue
        else:
            continue
        for tid in identities:
            if tid:
                claims[str(tid)].append((record, event_ids))
    result = {}
    flags = ('evidence_missing', 'evidence_changed', 'period_conflict', 'service_period_conflict')
    # A payment receipt may omit the stay its own reservation mail states (Booking.com charges).
    # Any stale, changed, conflicting or cancelled observation of the booking withholds it entirely.
    stated, withheld = defaultdict(set), set()
    for event_id, event in events.items():
        if not event.get('provider') or not event.get('booking_ref'):
            continue
        key = (str(event['provider']), str(event['booking_ref']))
        period = event.get('service_period') or {}
        link = (data.get('links') or {}).get(event_id) or {}
        link = link if isinstance(link, dict) else {}
        if (any(event.get(k) or link.get(k) for k in flags) or link.get('status') == 'STALE'
                or (link.get('source_digest') and link['source_digest'] != event.get('source_digest'))
                or event.get('reservation_status') in ('cancelled', 'refunded')
                or event.get('refund_status') not in (None, '', 'none_displayed')):
            withheld.add(key)
        elif (event.get('source_digest') and event.get('item') in (None, '', '숙박비')
                and event.get('reservation_status') in ('observed', 'confirmed', 'completed')
                and isinstance(period, dict) and period.get('starts_on') and period.get('ends_on')):
            stated[key].add((str(period['starts_on']), str(period['ends_on'])))
    for key in withheld:
        stated.pop(key, None)
    for tid, records in claims.items():
        card = cards.get(tid) or {}
        if ('card-' + tid in manual or not card.get('source_hash')
                or card.get('transaction_direction') != 'purchase'
                or any(card.get(key) for key in ('duplicate_of', 'parse_error', 'conflict_reason',
                                                'ota_review_held', 'reservation_refund_blocked'))
                or card.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')):
            continue
        periods, refs = set(), set()
        unsafe = False
        for record, event_ids in records:
            if (any(record.get(key) for key in flags)
                    or (record.get('reservation_link') or {}).get('status') == 'STALE'
                    or (record.get('allocation_basis') in
                        ('auto_stable_order', 'user_approved_stable_order', 'frozen_user_confirmed_order')
                        and record.get('individual_payment_evidence') is False)):
                unsafe = True
                break
            for eid in event_ids:
                event = events.get(str(eid)) or {}
                period = event.get('service_period') or {}
                if not period:
                    same = stated.get((str(event.get('provider')), str(event.get('booking_ref'))), ())
                    period = dict(zip(('starts_on', 'ends_on'), next(iter(same)))) if len(same) == 1 else None
                link = (data.get('links') or {}).get(str(eid)) or {}
                if (not event.get('source_digest') or not event.get('provider')
                        or not event.get('booking_ref') or event.get('item') not in (None, '', '숙박비')
                        or event.get('reservation_status') not in ('observed', 'confirmed', 'completed')
                        or any(event.get(key) or link.get(key) for key in flags)
                        or (link.get('source_digest') and link['source_digest'] != event['source_digest'])
                        or link.get('status') == 'STALE' or not isinstance(period, dict)):
                    unsafe = True
                    break
                try:
                    start, end = (date.fromisoformat(period[key]) for key in ('starts_on', 'ends_on'))
                    valid = 0 <= (end - start).days <= 366
                except (KeyError, TypeError, ValueError):
                    valid = False
                if not valid:
                    unsafe = True
                    break
                periods.add((start.isoformat(), end.isoformat()))
                refs.add(str(event['booking_ref']))
            if unsafe:
                break
        if unsafe or len(periods) != 1:
            continue
        start, end = next(iter(periods))
        result[tid] = {'booking_ref': next(iter(refs)) if len(refs) == 1 else '',
                       'booking_refs': sorted(refs), 'service_period': start + '~' + end,
                       'ota_evidence': {'kind': 'reservation_period_inferred', 'payment_verified': False}}
    return result


def _toyoko_candidate_periods(data, manual):
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    occupied = _occupied_cards(data)
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
    if (reservation and reservation != found.get('booking_ref')
            and reservation not in (found.get('booking_refs') or ())):
        return ''
    return found.get('service_period') or ''
