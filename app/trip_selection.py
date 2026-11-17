"""Pure shared trip periods and locality selection.

Callers supply authoritative trips; this module never reads or writes a store.
Only enclosing dates qualify for generic card attribution.
"""
from datetime import date
import re


FUKUTAKE_BASIS = '사용자 규칙: FUKUTAKE FOUNDATION · 결제일 당일 또는 이후 가장 가까운 세토우치 출발일'


def is_fukutake_purchase(transaction):
    return (bool(re.match(r'^FUKUTAKE\s+FOUNDATION(?:\b|$)',
                         str(transaction.get('merchant') or '').strip(), re.I))
            and transaction.get('transaction_direction', 'purchase') == 'purchase'
            and not any(transaction.get(k) for k in ('parse_error', 'duplicate_of', 'conflict_reason')))


def fukutake_trips(transaction, trips):
    """Return None outside this rule, otherwise only the nearest future Setouchi.

    Callers supply validated real trips. Never use today's date or posting date.
    """
    if not is_fukutake_purchase(transaction):
        return None
    try:
        day = date.fromisoformat(transaction.get('approval_date') or '').isoformat()
    except (TypeError, ValueError):
        return []
    candidates = [t for t in trips
                  if ('세토우치' in str(t.get('destination') or '')
                      or '세토우치' in str(t.get('display_key') or ''))
                  and t.get('starts_on') and t['starts_on'] >= day]
    first = min((t['starts_on'] for t in candidates), default=None)
    return sorted((t for t in candidates if t['starts_on'] == first),
                  key=lambda t: str(t.get('trip_id') or t.get('tab_id') or ''))


def canonical_trip_periods(trips):
    rows = []
    invalid = {'PERIOD_START_MISSING', 'PERIOD_START_MISMATCH', 'PERIOD_DATE_INVALID', 'PERIOD_ORDER'}
    for raw in trips:
        trip = dict(raw)
        flags = set(trip.get('flags') or trip.get('period_flags') or ())
        if (not trip.get('trip_id') or trip.get('archived') or trip.get('deleted')
                or trip.get('enabled') is False or trip.get('valid') is False
                or trip.get('conflict') or trip.get('period_conflict') or flags & invalid):
            continue
        try:
            start = date.fromisoformat(trip['starts_on'])
            end = date.fromisoformat(trip['ends_on']) if trip.get('ends_on') else None
            if end and end < start:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        rows.append((start, trip))
    rows.sort(key=lambda pair: pair[0])
    from .reconciliation import open_trip_end
    # A reverse pass preserves same-start ordering without scanning each suffix.
    following = None
    group_start = None
    next_start = None
    for start, trip in reversed(rows):
        if start != group_start:
            following, group_start = next_start, start
        if not trip.get('ends_on'):
            trip['ends_on'] = open_trip_end(trip['starts_on'], following)
        next_start = start.isoformat()
    return {str(trip['trip_id']): trip for _, trip in rows}


def past_trip(transaction, trip, *, original=None):
    """TRIP-099: compare the source payment day with the real trip's end.

    Exactly seven days is allowed. An unknown date proves no elapsed interval;
    source/date protection remains the caller's responsibility.
    """
    if (transaction.get('transaction_direction') in ('refund', 'cancellation')
            or isinstance(transaction.get('amount_krw'), (int, float)) and transaction['amount_krw'] < 0):
        if original is None:
            return False  # Refund date is not its payment date; financial guards resolve the original.
        transaction = original
    try:
        paid = date.fromisoformat(transaction.get('approval_date') or transaction.get('posting_date') or '')
        ended = date.fromisoformat(trip.get('ends_on') or '')
    except (TypeError, ValueError):
        return False
    return (paid - ended).days > 7


def card_trip_allowed(transaction, trip):
    """Shared temporal constraint and the owner's September Jeju card scope."""
    restricted = (trip.get('display_key') == '0909_제주'
                  and str(trip.get('starts_on') or '') == '2026-09-09')
    return (not past_trip(transaction, trip)
            and (not restricted or str(transaction.get('card_tail') or '') == '4813'))


def limit_past_trip(transaction, values, trips, *, original=None):
    """Final automatic-assignment guard, including inherited refund trips."""
    target = values.get('display_tab_id') or values.get('trip_id')
    trip = next((t for t in trips if (t.get('trip_id') or t.get('tab_id')) == target), None)
    if not trip or not past_trip(transaction, trip, original=original):
        return values
    from .card_destination import observed_quarter
    quarter = observed_quarter(original or transaction)
    if not quarter:
        raise ValueError('PAST_TRIP_PAYMENT_DATE_INVALID')
    return dict(values, display_tab_id=quarter[0], trip_id='', classification_state='classified',
                classification_source='inference',
                classification_basis='TRIP-099 · 결제일보다 7일 넘게 전에 종료된 여행 제외 · 결제일 분기 기타비용')


def regional_trips(transaction, trips, *, booking_agnostic=False):
    from .rules import is_booking_or_online, transaction_region, trip_region
    region = '' if booking_agnostic and is_booking_or_online(transaction) else transaction_region(transaction)
    return [trip for trip in trips if card_trip_allowed(transaction, trip)
            and (not region or trip_region(trip) == region)]


def period_or_preparation(trips, day):
    """Return only enclosing trips (owner decision 2026-11-12).

    The legacy function name and tuple shape remain for callers. The second
    value is always False; explicit preparation-stay rules live elsewhere.
    A malformed day cannot use a posting date. Input trips are validated.
    """
    try:
        day = date.fromisoformat(day).isoformat()
    except (TypeError, ValueError):
        return [], False
    enclosing = [t for t in trips if t.get('starts_on') and t.get('ends_on')
                 and t['starts_on'] <= day <= t['ends_on']]
    if enclosing:
        return enclosing, False
    return [], False
