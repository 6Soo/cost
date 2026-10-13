"""The date rules that place a booking or a card row on a trip, pinned at their edges."""
from app.reconciliation import card_use_date, covers_stay, overlaps_stay, payment_within_lead


def test_a_lodging_is_covered_only_when_it_checks_out_by_the_trip_end():
    assert covers_stay('2026-09-24', '2026-09-27', '2026-09-24', '2026-09-27')
    assert not covers_stay('2026-09-24', '2026-09-27', '2026-09-24', '2026-09-28')


def test_a_flight_counts_its_arrival_day():
    assert covers_stay('2026-08-01', '2026-08-05', '2026-08-01', '2026-08-05', service=True)
    assert not covers_stay('2026-08-01', '2026-08-05', '2026-08-01', '2026-08-06', service=True)


def test_a_checkout_on_the_trip_start_or_a_check_in_on_the_trip_end_is_not_an_overlap():
    assert not overlaps_stay('2026-09-24', '2026-09-27', '2026-09-20', '2026-09-24')
    assert not overlaps_stay('2026-09-24', '2026-09-27', '2026-09-27', '2026-09-29')


def test_a_stay_that_runs_past_the_trip_end_partly_overlaps_it():
    assert overlaps_stay('2026-09-24', '2026-09-27', '2026-09-24', '2026-09-28')


def test_a_flight_arriving_on_the_trip_end_overlaps_it():
    assert overlaps_stay('2026-09-24', '2026-09-27', '2026-09-27', '2026-09-28', service=True)


def test_a_payment_is_within_the_lead_up_to_thirty_days_before_the_trip():
    assert payment_within_lead('2026-08-02', '2026-09-01')
    assert not payment_within_lead('2026-08-01', '2026-09-01')
    assert not payment_within_lead('', '2026-09-01')


def test_the_card_row_is_placed_by_its_use_date_when_it_has_one():
    assert card_use_date({'approval_date': '2026-05-07', 'posting_date': '2026-05-09'}) == '2026-05-07'
