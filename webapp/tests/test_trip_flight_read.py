from types import SimpleNamespace

import pytest

from app.trip_flight_assignment import resolve_assignment
from webapp.trip_flight_read import dispatch, page_for_trip, project_trip_bookings, trip_read_allowed
from webapp.trip_flight_ui import render_flight_section


def trip(tab, start, end):
    return {"tab_id": tab, "starts_on": start, "ends_on": end, "archived": False, "deleted": False}


def evidence(ref, outbound="2026-11-07", inbound="2026-11-11", **kwargs):
    return {"source_digests": ["synthetic:" + ref], "passengers": [
        {"surname": "SAMPLE", "given_name": "PERSON"}, {"surname": "SAMPLE", "given_name": "PERSON"}],
        "legs": [{"label": "오는편", "departure_on": inbound, "segments": [
            {"departure_on": inbound, "departure_airport": "FUK", "arrival_airport": "ICN"}]},
            {"label": "가는편", "departure_on": outbound, "segments": [
                {"departure_on": outbound, "departure_airport": "ICN", "arrival_airport": "FUK"}]}],
        "cancellation_status": "NONE", **kwargs}


def test_consecutive_trips_assigns_booking_only_to_first_outbound_trip():
    trips = [trip("A", "2026-11-07", "2026-11-08"), trip("B", "2026-11-09", "2026-11-10")]
    result = project_trip_bookings({"PNR-A": evidence("A")}, trips, source_generation="g1")
    booking, = result["bookings"]
    assert booking["assigned_trip_tab_id"] == "A"
    assert booking["outbound_departure_on"] == "2026-11-07"
    assert len(booking["legs"]) == 2
    assert page_for_trip(result, "A")["total_bookings"] == 1
    assert page_for_trip(result, "B")["total_bookings"] == 0


def test_separate_booking_and_booking_date_do_not_change_outbound_assignment():
    trips = [trip("A", "2026-11-07", "2026-11-08"), trip("B", "2026-11-09", "2026-11-10")]
    index = {"PNR-A": evidence("A", reserved_on="2026-05-04"),
             "PNR-B": evidence("B", "2026-11-09", "2026-11-13")}
    result = project_trip_bookings(index, trips, source_generation="g")
    assert [b["assigned_trip_tab_id"] for b in result["bookings"]] == ["A", "B"]
    assert result["bookings"][0]["reserved_on"] == "2026-05-04"


def test_user_confirmation_kept_and_conflict_exposed():
    trips = [trip("A", "2026-11-07", "2026-11-08"), trip("B", "2026-11-09", "2026-11-10")]
    decision = resolve_assignment({"legs": [{"departure_on": "2026-11-07"}]}, trips,
                                  user_assignment={"trip_tab_id": "B"})
    assert decision["trip_tab_id"] == "B"
    assert decision["assignment_status"] == "USER_CONFIRMED"
    assert decision["conflict"] is True


def test_conflicting_authority_and_date_tie_fail_closed():
    trips = [trip("A", "2026-11-07", "2026-11-08"), trip("B", "2026-11-07", "2026-11-10")]
    conflict = resolve_assignment({"legs": [{"departure_on": "2026-11-07"}]}, trips,
                                  authority_trip_ids=["A", "B"])
    tie = resolve_assignment({"legs": [{"departure_on": "2026-11-07"}]}, trips)
    assert conflict["assignment_status"] == "CONFLICT"
    assert tie["assignment_status"] == "CONFLICT"


def test_open_ended_trip_ends_before_next_trip():
    trips = [trip("A", "2026-11-07", ""), trip("B", "2026-11-09", "2026-11-10")]
    res = resolve_assignment({"legs": [{"departure_on": "2026-11-08"}]}, trips)
    assert res["trip_tab_id"] == "A"
    assert resolve_assignment({"legs": [{"departure_on": "2026-11-09"}]}, trips)["trip_tab_id"] == "B"


def test_snapshot_pagination_and_generation_change():
    trips = [trip("A", "2026-11-07", "2026-12-01")]
    index = {f"REF-{i:02}": evidence(f"{i:02}", f"2026-11-{7+i:02}", f"2026-11-{8+i:02}") for i in range(21)}
    projection = project_trip_bookings(index, trips, source_generation="g1")
    first = page_for_trip(projection, "A")
    assert len(first["items"]) == 20 and first["next_cursor"]
    assert len(page_for_trip(projection, "A", cursor=first["next_cursor"])["items"]) == 1
    changed = project_trip_bookings(index, trips, source_generation="g2")
    with pytest.raises(LookupError, match="SOURCE_CHANGED"):
        page_for_trip(changed, "A", cursor=first["next_cursor"])


def test_permissions_cancelled_reservations_and_safe_ui_markup():
    active = trip("A", "2026-11-07", "2026-11-10")
    assert trip_read_allowed(is_owner=True, trip=active)
    assert trip_read_allowed(is_owner=False, trip=active, allowed_trip_ids=["A"])
    assert not trip_read_allowed(is_owner=False, trip=active, allowed_trip_ids=["B"])
    assert not trip_read_allowed(is_owner=True, trip={**active, "archived": True})
    cancelled = project_trip_bookings({"C": evidence("C", cancellation_status="CANCELLED")},
        [active], source_generation="g")
    assert page_for_trip(cancelled, "A")["total_bookings"] == 0
    assert page_for_trip(cancelled, "A", status="all")["items"][0]["booking_status"] == "CANCELLED"
    markup = render_flight_section('a" onfocus="alert(1)')
    assert 'onfocus="alert(1)' not in markup
    assert "<details>" in markup and "<ol" in markup


def test_duplicate_passengers_count_once_and_provider_is_part_of_key():
    item = evidence("SAME")
    first = project_trip_bookings({"SAME": item}, [trip("A", "2026-11-07", "2026-11-10")], source_generation="g")["bookings"][0]
    assert first["passenger_count"] == 2
    assert "passengers" not in first
    other_provider = {**item, "provider": "other"}
    result = project_trip_bookings({"SAME": other_provider}, [trip("A", "2026-11-07", "2026-11-10")], source_generation="g")
    assert result["bookings"][0]["provider"] == "other"


def test_api_dispatch_requires_trip_access_fresh_snapshot_and_get():
    class Handler:
        def __init__(self):
            self.response = None
        def _send_json(self, body, status=200):
            self.response = (status, body)

    class Board:
        def live_trips(self, include_archived=False):
            return [trip("A", "2026-11-07", "2026-11-10")]

    parsed = SimpleNamespace(path="/api/trips/A/flight-bookings", query="limit=20")
    handler = Handler()
    assert dispatch(handler, parsed, board=Board(), is_owner=False, allowed_trip_ids=["B"], snapshot={})
    assert handler.response[0] == 404
    handler = Handler()
    assert dispatch(handler, parsed, board=Board(), is_owner=False, allowed_trip_ids=["A"], snapshot={})
    assert handler.response[0] == 503
    handler = Handler()
    assert dispatch(handler, parsed, board=Board(), is_owner=True,
        snapshot={"fresh": True, "generation": "g1", "data": {"passengers": {"R": evidence("R")}}})
    assert handler.response[0] == 200
    assert handler.response[1]["source_generation"] == "g1"
    handler = Handler()
    assert dispatch(handler, parsed, board=Board(), is_owner=True, raw=b"{}")
    assert handler.response[0] == 405
