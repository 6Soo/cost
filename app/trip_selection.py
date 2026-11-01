"""Pure shared trip periods, locality and preparation-gap selection.

Callers supply authoritative trips; this module never reads or writes a store.
Preparation changes attribution only, never the source date or trip schedule.
"""
from datetime import date


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


def regional_trips(transaction, trips, *, booking_agnostic=False):
    from .rules import is_booking_or_online, transaction_region, trip_region
    region = '' if booking_agnostic and is_booking_or_online(transaction) else transaction_region(transaction)
    return [trip for trip in trips if not region or trip_region(trip) == region]


def period_or_preparation(trips, day):
    """Return enclosing trips, else the nearest following start for any cost.

    Same-start candidates stay tied for the caller's existing tie/net policy.
    No following trip means no preparation assignment. A malformed day cannot
    use a posting date as a substitute. Input trips must already be validated.
    """
    try:
        day = date.fromisoformat(day).isoformat()
    except (TypeError, ValueError):
        return [], False
    enclosing = [t for t in trips if t.get('starts_on') and t.get('ends_on')
                 and t['starts_on'] <= day <= t['ends_on']]
    if enclosing:
        return enclosing, False
    following = [t for t in trips if t.get('starts_on') and t['starts_on'] > day]
    first = min((t['starts_on'] for t in following), default=None)
    return [t for t in following if t['starts_on'] == first], bool(following)
