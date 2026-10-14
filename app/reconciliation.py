"""The reconciliation rules in one place: origins, booking statuses, and the date rules that place a card row on a trip.

Card side: the card's use date (이용일) when the statement has one, else its approval date (승인일). The posting
date (매입일) is never used to place a row.
Booking side: a lodging stay runs from check-in to check-out, and a trip's last day is the check-out day, so the nights
of a stay inside a trip are the ones before the trip's end. A flight runs from departure to arrival, and both days are
service days.
"""
from datetime import date, timedelta

#: A trip the owner picked for one OTA booking. Applied to that booking's card rows only.
OWNER_BOOKING_ORIGIN = "owner-ota-booking"
#: Inferences the owner authorized from payment history.
OWNER_AUTHORIZED_INFERENCE_ORIGIN = "owner-authorized-inference-20261003"
#: The owner's exception for Georgia and Kazakhstan purchases in the European trip.
OWNER_COUNTRY_EXCEPTION_ORIGIN = "owner-country-exception-20261003"
#: A trip inferred from a confirmed reservation's stay dates, for one card row. Classified as an inference.
PERIOD_OTA_ORIGIN = "auto-ota-period"
OTA_MAIL_ORIGIN = "ota-mail-live"
OTA_PORTAL_ORIGIN = "ota-portal-live"
GUIDE_AIRFARE_ORIGIN = "guide-airfare-live"

#: Booking statuses that count as a reservation the trip may be assigned from.
CONFIRMED_STATUSES = frozenset({"confirmed", "completed", "upcoming"})


def card_use_date(transaction):
    """The card row's date for placing it on a trip: 이용일 when the statement has one, else 승인일."""
    return transaction.get("approval_date") or ""


def covers_stay(trip_start, trip_end, check_in, check_out, *, service=False):
    """Whether a booking's whole stay is inside the trip. Dates are ISO strings.

    A trip's last day is its check-out day: a lodging's nights run from check-in up to but not including check-out,
    and the trip ends on the check-out day. A flight's arrival day is a service day, so it must fall inside the trip.
    """
    return bool(trip_start and trip_end and trip_start <= check_in and check_out <= trip_end)


def overlaps_stay(trip_start, trip_end, check_in, check_out, *, service=False):
    """Whether any service day of a booking falls inside the trip. A lodging's check-out day is not a night of the stay."""
    if not (trip_start and trip_end):
        return False
    if service:
        return max(check_in, trip_start) <= min(check_out, trip_end)
    return max(check_in, trip_start) < min(check_out, trip_end)


def shared_days(trip_start, trip_end, check_in, check_out, *, service=False):
    """How many nights (or, for a flight, service days) a booking shares with a trip."""
    if not overlaps_stay(trip_start, trip_end, check_in, check_out, service=service):
        return 0
    start, end = max(check_in, trip_start), min(check_out, trip_end)
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + (1 if service else 0)


def stay_trip(trips, check_in, check_out, *, service=False, nets=None):
    """The verified trip a booking stay belongs to, or None when no trip shares a day with it.

    A trip that covers the whole stay wins; otherwise the trip sharing the most nights. A tie goes to the trip with
    the larger income minus expense (nets by tab id), and a tie that remains is left unassigned.
    """
    nets = nets or {}
    covering = [t for t in trips if covers_stay(t['starts_on'], t['ends_on'], check_in, check_out, service=service)]
    pool = covering or [t for t in trips if overlaps_stay(t['starts_on'], t['ends_on'], check_in, check_out,
                                                          service=service)]
    if not pool:
        return None
    rank = lambda t: (0 if covering else shared_days(t['starts_on'], t['ends_on'], check_in, check_out, service=service),
                      nets.get(t['tab_id'], float('-inf')))
    pool.sort(key=rank, reverse=True)
    if len(pool) > 1 and rank(pool[0]) == rank(pool[1]):
        return None
    return pool[0]
