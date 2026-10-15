"""The date rules that place a booking or a card row on a trip, pinned at their edges."""
from app.reconciliation import card_use_date, covers_stay, overlaps_stay, stay_trip


def test_a_lodging_is_covered_when_its_nights_are_inside_the_trip_including_the_last_night():
    assert covers_stay('2026-09-24', '2026-09-27', '2026-09-24', '2026-09-27')
    assert covers_stay('2026-09-24', '2026-09-27', '2026-09-24', '2026-09-28')
    assert not covers_stay('2026-09-24', '2026-09-27', '2026-09-24', '2026-09-29')


def test_a_flight_counts_its_arrival_day():
    assert covers_stay('2026-08-01', '2026-08-05', '2026-08-01', '2026-08-05', service=True)
    assert not covers_stay('2026-08-01', '2026-08-05', '2026-08-01', '2026-08-06', service=True)


def test_a_checkout_on_the_trip_start_is_not_an_overlap_but_the_last_night_of_the_trip_is():
    assert not overlaps_stay('2026-09-24', '2026-09-27', '2026-09-20', '2026-09-24')
    assert overlaps_stay('2026-09-24', '2026-09-27', '2026-09-27', '2026-09-29')


def test_the_last_night_goes_to_the_trip_that_starts_that_day():
    assert not overlaps_stay('2026-09-24', '2026-09-27', '2026-09-27', '2026-09-29', handover={'2026-09-27'})


def test_a_stay_that_runs_past_the_trip_end_partly_overlaps_it():
    assert overlaps_stay('2026-09-24', '2026-09-27', '2026-09-24', '2026-09-28')


def test_a_flight_arriving_on_the_trip_end_overlaps_it():
    assert overlaps_stay('2026-09-24', '2026-09-27', '2026-09-27', '2026-09-28', service=True)


def _trip(tab, starts_on, ends_on):
    return {'tab_id': tab, 'starts_on': starts_on, 'ends_on': ends_on}


def test_a_stay_goes_to_the_covering_trip_then_the_most_shared_nights_then_the_larger_net():
    a, b = _trip('a', '2026-09-20', '2026-09-24'), _trip('b', '2026-09-24', '2026-09-30')
    assert stay_trip([a, b], '2026-09-21', '2026-09-23')['tab_id'] == 'a'
    assert stay_trip([a, b], '2026-09-22', '2026-09-27')['tab_id'] == 'b'
    c = _trip('c', '2026-09-26', '2026-10-02')
    assert stay_trip([b, c], '2026-09-26', '2026-09-28') is None
    assert stay_trip([b, c], '2026-09-26', '2026-09-28', nets={'b': 5, 'c': 9})['tab_id'] == 'c'
    assert stay_trip([a], '2026-10-05', '2026-10-06') is None


def test_the_card_row_is_placed_by_its_use_date_when_it_has_one():
    assert card_use_date({'approval_date': '2026-05-07', 'posting_date': '2026-05-09'}) == '2026-05-07'


def test_a_night_on_the_day_before_the_next_trip_starts_is_that_trips_preparation_night():
    trips = [_trip('0408', '2026-04-08', '2026-04-12'), _trip('0413', '2026-04-13', '2026-04-16')]
    assert stay_trip(trips, '2026-04-12', '2026-04-13')['tab_id'] == '0413'
    assert stay_trip(trips, '2026-04-11', '2026-04-12')['tab_id'] == '0408'
