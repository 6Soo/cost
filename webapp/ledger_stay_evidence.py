"""Read current OTA service dates for old card ledger rows without rewriting them."""
from app.ota_core_projection import card_matches
from app.ota_mail import ledger_metadata
from collections import defaultdict
import threading

_INDEX_LOCK = threading.Lock()
_INDEX_MEMO = {}


def stay_index(store):
    from . import ota_payment_review

    if store is None:
        return {}
    p2 = _p2_index(store)
    if not ota_payment_review.enabled():
        return p2
    # Reading a ledger must not start reconciliation or turn stale evidence into fact.
    service = getattr(store, '_ota_snapshot_service', None)
    if service is None:
        return p2
    # The last complete generation stays on screen while the next one is computed or retried;
    # a refresh takes minutes and dropping every date meanwhile hid verified evidence.
    current, _state = service.display_context()
    if not current or current.get('data') is None:
        return p2
    with store._lock:
        manual = {str(r[0]) for r in store.conn.execute(
            "SELECT row_id FROM board_manual_overrides WHERE field='service_period'")}
    # One snapshot generation and the same manual overrides give the same index; build it once.
    memo_key = (id(store), id(current), current.get('key'), frozenset(manual))
    with _INDEX_LOCK:
        if _INDEX_MEMO.get('key') == memo_key and _INDEX_MEMO.get('current') is current:
            return _with_p2(_INDEX_MEMO['result'], p2, current.get('data') or {})
    from app.ota_matching_defaults import provider_resolution_scope
    with provider_resolution_scope():
        result = _build_index(current.get('data') or {}, manual)
    with _INDEX_LOCK:
        _INDEX_MEMO.update(key=memo_key, current=current, result=result)
    return _with_p2(result, p2, current.get('data') or {})


def _p2_index(store):
    from app.ai_classification import service_metadata
    with store._lock:
        if not store.conn.execute("SELECT 1 FROM sqlite_master WHERE name='transactions'").fetchone():
            return {}
        ids = [r[0] for r in store.conn.execute("SELECT transaction_id FROM transactions WHERE classification_source='ai_inference' AND item IN ('숙박비','항공료','렌터카')")]
        return {tid: metadata for tid in ids if (metadata := service_metadata(store.conn, tid))}


def _with_p2(exact, p2, data):
    result = dict(exact)
    occupied = _occupied_cards(data)
    occupied.update(str(row.get('transaction_id')) for row in data.get('transactions', ())
                    if any(row.get(k) for k in ('period_conflict','service_period_conflict','ota_review_held',
                                                'reservation_refund_blocked','evidence_missing','evidence_changed')))
    for tid, metadata in p2.items():
        if tid not in occupied:
            result.setdefault(tid, metadata)
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
    for tid, metadata in _airline_exact_amount_periods(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _airbnb_code_periods(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _agoda_recorded_card_periods(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _trip_price_change_periods(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _trip_preauthorization_cards(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _forest_order_periods(data, manual).items():
        result.setdefault(tid, metadata)
    for tid, metadata in _onsite_property_periods(data, manual).items():
        result.setdefault(tid, metadata)
    return result


def _forest_order_periods(data, manual):
    """A matched 숲나들e payment names its order; the same order and amount in the booking states the stay.

    The payment mail carries no stay and the booking no card, so the two meet only here.
    Display only: the existing payment link is untouched and no booking number is invented.
    """
    from datetime import date
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    cards = {str(c.get('transaction_id')): c for c in data.get('transactions', [])}
    flags = ('evidence_missing', 'evidence_changed', 'period_conflict', 'service_period_conflict')
    bookings = defaultdict(list)
    for event in events.values():
        if event.get('provider') == 'forest' and event.get('event_type') == 'reservation':
            order = str(event.get('booking_ref') or '').rsplit(':', 1)[-1]
            if order:
                bookings[order].append(event)
    if not bookings:
        return {}
    claimed = defaultdict(set)
    for record in data.get('results', []):
        for tid in [record.get('transaction_id'), *(record.get('reserved_card_ids') or ())]:
            if tid:
                claimed[str(tid)].add(str(record.get('ota_event_id')))
        relation = record.get('payment_relation') or {}
        if relation.get('status') == 'LINKED':
            for tid in relation.get('transaction_ids') or ():
                claimed[str(tid)].add(str(record.get('ota_event_id')))
        if (record.get('reservation_link') or {}).get('transaction_id'):
            claimed[str(record['reservation_link']['transaction_id'])].add(str(record.get('ota_event_id')))
    for event_id, link in (data.get('links') or {}).items():
        if isinstance(link, dict) and link.get('transaction_id'):
            claimed[str(link['transaction_id'])].add(str(event_id))
    result = {}
    for record in data.get('results', []):
        event = events.get(str(record.get('ota_event_id'))) or {}
        tid = str(record.get('transaction_id') or '')
        order = str(event.get('order_number') or '')
        amount = event.get('amount_krw')
        if (event.get('provider') != 'forest' or event.get('event_type') != 'charge' or not order or not tid
                or record.get('status') not in ('MATCHED_AUTO', 'MATCHED_USER')
                or event.get('evidence_status') != 'paid_verified' or not isinstance(amount, int) or amount <= 0
                or claimed[tid] != {str(event['ota_event_id'])}
                or any(obj.get(k) for obj in (event, record) for k in flags)):
            continue
        same = [b for b in bookings.get(order, ())
                if (b.get('reservation_amount_krw') if b.get('reservation_amount_krw') is not None
                    else b.get('amount_krw')) == amount]
        # One order, one amount: a second booking under the order or an amount that differs is no match.
        if len(same) != 1 or len(bookings[order]) != 1:
            continue
        booking = same[0]
        period = booking.get('service_period') or {}
        try:
            start, end = (date.fromisoformat(period[key]) for key in ('starts_on', 'ends_on'))
            valid = 0 < (end - start).days <= 60
        except (KeyError, TypeError, ValueError):
            valid = False
        card = cards.get(tid) or {}
        if (not valid or booking.get('reservation_status') not in ('confirmed', 'completed', 'observed')
                or not booking.get('source_digest') or any(booking.get(k) for k in flags)
                or booking.get('refund_status') not in (None, '', 'none_displayed')
                or 'card-' + tid in manual or not card.get('source_hash')
                or card.get('transaction_direction') != 'purchase'
                or any(card.get(k) for k in ('duplicate_of', 'parse_error', 'conflict_reason',
                                             'ota_review_held', 'reservation_refund_blocked'))
                or card.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')):
            continue
        result[tid] = {'booking_ref': order, 'booking_refs': [order], 'item': '숙박비',
                       'service_period': start.isoformat() + '~' + end.isoformat(),
                       'ota_evidence': {'kind': 'reservation_period_inferred', 'payment_verified': False}}
    return result


_GENERIC_NAME_TOKENS = frozenset({'HOTEL', 'HOTELS', 'RESORT', 'INN', 'SPA', 'THE', 'AND', 'JAPAN', 'TOKYO',
                                  'OSAKA', 'KYOTO', 'CO', 'LTD', 'INC'})


def _name_tokens(value):
    import re
    return [t for t in re.split(r'[^A-Z]+', str(value or '').upper()) if len(t) >= 4]


def _same_lodging(merchant, name):
    """Every distinctive romanized merchant token sits in the booking's lodging name."""
    import re
    # A card merchant field trails the city and country after a wide gap (split, not a backtracking sub).
    head = re.split(r'\s{2,}', str(merchant or ''), maxsplit=1)[0]
    tokens = [t for t in _name_tokens(head) if t not in _GENERIC_NAME_TOKENS]
    compact = re.sub(r'[^A-Z]', '', str(name or '').upper())
    return bool(tokens) and sum(map(len, tokens)) >= 8 and all(t in compact for t in tokens)


def _onsite_property_periods(data, manual):
    """A hotel card inside the stay of the one pay-at-property booking that names that hotel.

    The booking has no OTA charge, so the card the hotel itself took is its payment. The
    merchant's romanized name must be the booking's lodging name and the card day must fall
    in the stay; two bookings that fit make no match. Display only (LINK-109).
    """
    from datetime import date
    from app.ota_matching_defaults import provider_for_merchant
    names = data.get('property_names') or {}
    if not names:
        return {}
    flags = ('evidence_missing', 'evidence_changed', 'period_conflict', 'service_period_conflict')
    by_booking = defaultdict(list)
    for event in data.get('events', []):
        if event.get('provider') in ('agoda', 'trip') and event.get('booking_ref'):
            by_booking[(event['provider'], str(event['booking_ref']))].append(event)
    stays = {}
    for (provider, ref), related in by_booking.items():
        lodging = names.get(f'{provider}:{ref}')
        if not lodging:
            continue
        # A charge, a cancellation or any refund means the OTA, not the hotel, is paid; a scheduled charge is not a charge.
        # An Agoda scheduled auto-charge (a dated one) is the OTA's own payment (LINK-069), not the hotel's.
        if provider == 'agoda' and any(
                e.get('scheduled_for') and 'scheduled' in str(e.get('event_type')) + str(e.get('payment_status'))
                + str(e.get('evidence_status')) for e in related):
            continue
        if any(e.get('event_type') in ('refund', 'cancellation_notice')
               or e.get('evidence_status') in ('paid_verified', 'refund_verified', 'conflict',
                                               'evidence_conflict', 'refund_conflict')
               or e.get('payment_status') == 'paid'
               or e.get('item') not in (None, '', '숙박비')
               or e.get('reservation_status') in ('cancelled', 'refunded')
               or e.get('refund_status') not in (None, '', 'none_displayed', 'refund_pending')
               or any(e.get(k) for k in flags) for e in related):
            continue
        periods = set()
        for event in related:
            period = event.get('service_period') or {}
            if (event.get('reservation_status') in ('observed', 'confirmed', 'completed')
                    and event.get('source_digest') and period.get('starts_on') and period.get('ends_on')):
                periods.add((str(period['starts_on']), str(period['ends_on'])))
        if len(periods) != 1:
            continue
        try:
            start, end = (date.fromisoformat(v) for v in next(iter(periods)))
        except ValueError:
            continue
        if 0 < (end - start).days <= 60:
            stays[(provider, ref)] = (start, end, lodging)
    if not stays:
        return {}
    occupied = _occupied_cards(data)
    result = {}
    for card in data.get('transactions', []):
        tid = str(card.get('transaction_id') or '')
        if (not tid or tid in occupied or 'card-' + tid in manual or card.get('transaction_direction') != 'purchase'
                or not card.get('source_hash')
                or any(card.get(k) for k in ('duplicate_of', 'parse_error', 'conflict_reason',
                                             'ota_review_held', 'reservation_refund_blocked'))
                or card.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')
                or provider_for_merchant(str(card.get('merchant') or '').casefold())):
            continue
        try:
            day = date.fromisoformat(str(card.get('approval_date') or ''))
        except ValueError:
            continue
        fits = [key for key, (start, end, lodging) in stays.items()
                if start <= day <= end and any(_same_lodging(card.get('merchant'), n) for n in lodging)]
        if len(fits) != 1:
            continue
        start, end, _ = stays[fits[0]]
        result[tid] = {'booking_ref': fits[0][1], 'booking_refs': [fits[0][1]], 'item': '숙박비',
                       'service_period': start.isoformat() + '~' + end.isoformat(),
                       'ota_evidence': {'kind': 'reservation_period_inferred', 'payment_verified': False}}
    return result


def _trip_preauthorization_cards(data, manual):
    """Cards that are Trip.com's guarantee hold for a pay-at-property hotel, not a lodging payment.

    The account's order states the KRW pre-authorization, the stay and the refund. A Trip card
    charge of exactly that amount, approved between booking and check-in, is that hold. Equal
    holds pair only as a group: as many cards as orders, all candidates to all. Display only.
    """
    from datetime import date, timedelta
    from app.ota_matching_defaults import provider_for_merchant
    holds = [e for e in data.get('events', [])
             if e.get('provider') == 'trip' and e.get('evidence_kind') == 'portal_preauthorization'
             # A cancelled order's hold was still charged; an order of unknown state is not used.
             and e.get('reservation_status') in ('confirmed', 'completed', 'cancelled')
             and isinstance(e.get('preauthorization_amount_krw'), int) and e['preauthorization_amount_krw'] > 0]
    # The confirmation mail states the same hold when the portal was never read (LINK-092, RFND-047).
    portal_refs = {str(e.get('booking_ref')) for e in holds}
    mail_holds = [dict(e, preauthorization_amount_krw=e['preauthorized_amount_krw'])
                  for e in data.get('events', [])
                  if e.get('provider') == 'trip' and e.get('evidence_kind') == 'authenticated_payment_mail'
                  and e.get('evidence_status') == 'preauthorized' and e.get('event_type') == 'reservation'
                  and e.get('reservation_status') in ('confirmed', 'completed', 'cancelled')
                  and e.get('booking_ref') and str(e['booking_ref']) not in portal_refs
                  and isinstance(e.get('preauthorized_amount_krw'), int) and e['preauthorized_amount_krw'] > 0
                  and _valid_day(e.get('preauthorized_on'))]
    # One booking mailed more than once is one hold; two different holds of a booking are not guessed.
    by_ref = defaultdict(list)
    for e in mail_holds:
        by_ref[str(e['booking_ref'])].append(e)
    mail_holds = [group[0] for group in by_ref.values()
                  if len({(e['preauthorized_amount_krw'], e['preauthorized_on'],
                           (e.get('service_period') or {}).get('starts_on')) for e in group}) == 1
                  and len({e['reservation_status'] == 'cancelled' for e in group}) == 1]
    holds += mail_holds
    if not holds:
        return {}
    occupied = _occupied_cards(data)
    mail_ids = {str(e['ota_event_id']) for e in mail_holds}

    def window(event):
        if str(event.get('ota_event_id')) in mail_ids:
            day = date.fromisoformat(event['preauthorized_on'])
            return day - timedelta(days=1), day + timedelta(days=1)
        period = event.get('service_period') or {}
        try:
            booked = date.fromisoformat(str(event.get('booked_on')))
            start = date.fromisoformat(str(period.get('starts_on'))) if period.get('starts_on') else booked + timedelta(days=366)
        except ValueError:
            return None
        return booked - timedelta(days=1), start

    cards = {}
    for row in data.get('transactions', []):
        tid = str(row.get('transaction_id') or '')
        if (not tid or row.get('transaction_direction') != 'purchase' or row.get('duplicate_of')
                or row.get('parse_error') or row.get('conflict_reason') or not row.get('source_hash')
                or tid in occupied or 'card-' + tid in manual
                or provider_for_merchant(str(row.get('merchant') or '')) != 'trip'):
            continue
        cards[tid] = row
    candidates = defaultdict(set)   # card -> holds
    reverse = defaultdict(set)      # hold -> cards
    by_id = {}
    for event in holds:
        span = window(event)
        if not span:
            continue
        hold_id = str(event['ota_event_id'])
        by_id[hold_id] = event
        for tid, row in cards.items():
            try:
                day = date.fromisoformat(str(row.get('approval_date') or row.get('posting_date') or ''))
            except ValueError:
                continue
            if (int(row.get('amount_krw') or 0) == event['preauthorization_amount_krw']
                    and span[0] <= day <= span[1]
                    and (not event.get('card_last4') or str(row.get('card_tail') or '') == event['card_last4'])):
                candidates[tid].add(hold_id)
                reverse[hold_id].add(tid)
    def components():
        found, done = [], set()
        for start_card in list(candidates):
            if start_card in done:
                continue
            group_cards, group_holds, todo = set(), set(), [start_card]
            while todo:
                tid = todo.pop()
                if tid in group_cards:
                    continue
                group_cards.add(tid)
                for hold in candidates[tid]:
                    if hold not in group_holds:
                        group_holds.add(hold)
                        todo.extend(reverse[hold])
            done |= group_cards
            found.append((group_cards, group_holds))
        return found

    # A group with portal evidence keeps its fixed shape: mail holds never join it (LINK-092).
    for group_cards, group_holds in components():
        if group_holds & mail_ids and group_holds - mail_ids:
            for hold in group_holds & mail_ids:
                for tid in reverse.pop(hold, ()):
                    candidates[tid].discard(hold)
    candidates = defaultdict(set, {tid: held for tid, held in candidates.items() if held})
    result = {}
    for group_cards, group_holds in components():
        if len(group_cards) != len(group_holds):
            continue
        events = [by_id[h] for h in sorted(group_holds)]
        periods = sorted({(e['service_period']['starts_on'], e['service_period']['ends_on'])
                          for e in events if e.get('service_period')})
        refunds = {('unknown' if str(e['ota_event_id']) in mail_ids else e.get('preauthorization_refund'))
                   for e in events}
        refund = ('refunded' if refunds == {'refunded'} else 'not_refunded' if refunds == {'not_refunded'}
                  else 'unknown' if 'unknown' in refunds else 'partly_refunded')
        refs = sorted(str(e['booking_ref']) for e in events)
        for tid in group_cards:
            result[tid] = {'booking_ref': refs[0] if len(refs) == 1 else '', 'booking_refs': refs,
                           'service_period': (periods[0][0] + '~' + periods[0][1]) if len(periods) == 1 else '',
                           'ota_evidence': {'kind': 'card_preauthorization', 'refund': refund,
                                            'cancelled': ('all' if all(e.get('reservation_status') == 'cancelled' for e in events)
                                                          else 'some' if any(e.get('reservation_status') == 'cancelled' for e in events)
                                                          else 'none'),
                                            'refunded_krw': events[0].get('preauthorization_refunded_krw') if len(events) == 1 else None,
                                            'periods': [a + '~' + b for a, b in periods],
                                            'payment_verified': False}}
    return result


def _valid_day(value):
    from datetime import date
    try:
        date.fromisoformat(str(value))
    except ValueError:
        return False
    return True


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


def _airline_exact_amount_periods(data, manual):
    """An undated Asiana ticket mail names its departure day for the one card that equals it.

    The mail has no card tail or charge day and Asiana carries no approved descriptor
    record, so the core never forms a candidate. A card of the airline's own merchant
    name, the exact KRW total, bought before departure, paired one-to-one with the mail,
    only informs this read-only display; no payment, trip or reservation relation is made.
    """
    from datetime import date
    import re
    from app.ota_matching_defaults import load_defaults
    events = {str(e.get('ota_event_id')): e for e in data.get('events', [])}
    by_booking = defaultdict(list)
    for event in events.values():
        by_booking[(event.get('provider'), event.get('booking_ref'))].append(event)
    held = {}
    for record in data.get('results', []):
        event = events.get(str(record.get('ota_event_id'))) or {}
        if event.get('provider') != 'asiana' or record.get('status') != 'HOLD_DATE_UNKNOWN':
            continue
        period = event.get('service_period') or {}
        try:
            start, end = (date.fromisoformat(period[key]) for key in ('starts_on', 'ends_on'))
            valid = 0 <= (end - start).days <= 366
        except (KeyError, TypeError, ValueError):
            valid = False
        amount = _decimal(event.get('amount_krw'))
        related = by_booking[(event.get('provider'), event.get('booking_ref'))]
        if (not valid or amount is None or amount <= 0 or event.get('paid_on')
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
        held[str(event.get('ota_event_id'))] = (amount, start, end, str(event.get('booking_ref')))
    if not held:
        return {}
    aliases = [str(a).casefold() for a in load_defaults().get('provider_merchant_aliases', {}).get('asiana', ()) if a]
    occupied = _occupied_cards(data)
    cards = {}
    for card in data.get('transactions', []):
        merchant = str(card.get('merchant') or '').casefold()
        if any(re.search(rf"(?<![^\W_]){re.escape(alias)}(?![^\W_])", merchant) for alias in aliases):
            cards[str(card.get('transaction_id'))] = card
    # Every Asiana-named card, eligible or not, counts against uniqueness: an excluded twin still makes the pairing ambiguous.
    matches = defaultdict(set)
    claims = defaultdict(set)
    for event_id, (amount, start, _end, _ref) in held.items():
        for tid, card in cards.items():
            try:
                bought = date.fromisoformat(str(card.get('approval_date') or ''))
            except ValueError:
                continue
            if _decimal(card.get('amount_krw')) == amount and bought <= start:
                matches[event_id].add(tid)
                claims[tid].add(event_id)
    same_amount = defaultdict(set)
    for event in events.values():
        if event.get('provider') == 'asiana':
            same_amount[_decimal(event.get('amount_krw'))].add(str(event.get('ota_event_id')))
    result = {}
    for event_id, tids in matches.items():
        amount, start, end, booking_ref = held[event_id]
        if len(tids) != 1 or len(same_amount[amount]) != 1:
            continue
        tid = next(iter(tids))
        card = cards[tid]
        if (len(claims[tid]) != 1 or tid in occupied or 'card-' + tid in manual
                or card.get('transaction_direction') != 'purchase' or not card.get('source_hash')
                or any(card.get(k) for k in ('duplicate_of', 'parse_error', 'conflict_reason',
                                             'ota_review_held', 'reservation_refund_blocked'))
                or card.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')):
            continue
        result[tid] = {'booking_ref': booking_ref, 'booking_refs': [booking_ref],
                       'service_period': start.isoformat() + '~' + end.isoformat(), 'item': '항공료',
                       'ota_evidence': {'kind': 'reservation_period_inferred', 'payment_verified': False}}
    return result


def _airbnb_code_periods(data, manual):
    """An Airbnb card descriptor carries the reservation code its confirmation mail names.

    The code identifies the stay, not the amount paid; the card total (exchange and
    fees) is never compared. Only this read-only display reads the stay dates.
    """
    import re
    from datetime import date
    reservations = defaultdict(list)
    for event in data.get('events', []):
        if event.get('provider') == 'airbnb':
            reservations[str(event.get('booking_ref') or '')].append(event)
    if not reservations:
        return {}
    occupied = _occupied_cards(data)
    claims = defaultdict(list)
    for card in data.get('transactions', []):
        found = re.match(r'\s*airbnb\s*\*\s*(HM[A-Z0-9]{8})\b', str(card.get('merchant') or ''), re.I)
        if found:
            claims[found.group(1).upper()].append(card)
    result = {}
    for code, cards in claims.items():
        events = reservations.get(code) or []
        if len(events) != 1 or len(cards) != 1:
            continue
        event, card = events[0], cards[0]
        period = event.get('service_period') or {}
        try:
            valid = 0 < (date.fromisoformat(period['ends_on']) - date.fromisoformat(period['starts_on'])).days <= 60
        except (KeyError, TypeError, ValueError):
            valid = False
        tid = str(card.get('transaction_id') or '')
        if (not valid or event.get('reservation_status') != 'observed' or event.get('service_period_conflict')
                or event.get('evidence_kind') != 'authenticated_reservation_mail' or not event.get('source_digest')
                or not tid or tid in occupied or 'card-' + tid in manual
                or card.get('transaction_direction') != 'purchase' or not card.get('source_hash')
                or any(card.get(k) for k in ('duplicate_of', 'parse_error', 'conflict_reason',
                                             'ota_review_held', 'reservation_refund_blocked'))
                or card.get('refund_status') in ('refund_pending', 'refund_requested', 'refunded', 'refund_completed')):
            continue
        result[tid] = {'booking_ref': code, 'booking_refs': [code], 'item': '숙박비',
                       'service_period': period['starts_on'] + '~' + period['ends_on'],
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
    evidence = found.get('ota_evidence') or {}
    if evidence.get('source') == 'P2':
        if ((row.get('source_fact_digest') and row['source_fact_digest'] != evidence.get('source_hash'))
                or (row.get('item') and row['item'] != evidence.get('item'))):
            return ''
    if (found.get('ota_evidence') or {}).get('kind') == 'card_preauthorization':
        # A guarantee hold is not a stay; its dates are shown only by the pre-authorization label.
        return ''
    reservation = str(row.get('reservation_no') or '').strip()
    if (reservation and reservation != found.get('booking_ref')
            and reservation not in (found.get('booking_refs') or ())):
        return ''
    return found.get('service_period') or ''


def verified_period_for(row, index):
    """period_for without the screen-only inference (DATE-109): a stored value, or a verified link."""
    period = period_for(row, index)
    if not period or str(row.get('service_period') or '').strip():
        return period
    row_id = str(row.get('row_id') or '')
    evidence = (index.get(str(row.get('source_event_id') or row_id[5:])) or {}).get('ota_evidence') or {}
    if evidence.get('kind') == 'reservation_period_inferred' or evidence.get('payment_verified') is False:
        return ''
    return period


def flight_departure_days(found):
    """Sorted departure days of a saved flight booking in the passenger index; None when it cannot be used.

    Shared by the flight label on screen and the Rust period rule's flight evidence.
    """
    from datetime import date
    if (not found or found.get('conflict') or not found.get('source_digests')
            or found.get('cancellation_status') != 'NONE'
            or any(found.get(flag) for flag in
                   ('evidence_missing', 'evidence_changed', 'period_conflict', 'service_period_conflict'))):
        return None
    legs = found.get('legs') or []
    if not legs or any(not leg.get('departure_on') for leg in legs):
        return None
    try:
        return sorted({date.fromisoformat(leg['departure_on']) for leg in legs})
    except (ValueError, TypeError):
        return None


def export_index(store):
    """The screen's stay index for output paths; a store without a ledger connection has none."""
    if store is None or not hasattr(store, 'conn') or not hasattr(store, '_lock'):
        return {}
    return stay_index(store)


def index_from_snapshot(data, manual):
    """The same index the screen builds, from a full reconciliation result (offline tools)."""
    from app.ota_matching_defaults import provider_resolution_scope
    with provider_resolution_scope():
        return _build_index(data, manual)
