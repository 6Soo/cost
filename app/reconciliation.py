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
#: Inferences the owner authorized from payment history. They never reach back more than LEAD_DAYS before a trip.
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
#: How far before a trip a payment may be and still be assigned by inference without a booking.
LEAD_DAYS = 30


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


def payment_within_lead(card_day, trip_start, lead_days=LEAD_DAYS):
    """Whether a card row falls no more than lead_days before the trip starts. An unknown date is not within it."""
    if not card_day or not trip_start:
        return False
    return date.fromisoformat(card_day) >= date.fromisoformat(trip_start) - timedelta(days=lead_days)
