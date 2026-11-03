from types import SimpleNamespace
import json
import sqlite3

import pytest

from app.trip_flight_assignment import resolve_assignment
from webapp.trip_flight_read import (build_authority_maps, confirmed_card_trip_rows, detail_for_trip, dispatch,
    page_for_trip, project_trip_bookings, trip_read_allowed)
from webapp.trip_flight_ui import render_flight_section, render_trip_flights


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


def test_outbound_label_wins_when_return_leg_is_listed_first():
    booking = {"legs": [
        {"label": "오는 편", "departure_on": "2026-11-06", "segments": []},
        {"label": "가는 편", "departure_on": "2026-11-07", "segments": []}]}
    assert resolve_assignment(booking, [trip("A", "2026-11-07", "2026-11-08")])[
        "outbound_departure_on"] == "2026-11-07"


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


def test_history_does_not_count_cancelled_or_conflicting_passengers_as_current():
    active = trip("A", "2026-11-07", "2026-11-10")
    index = {"ACTIVE": evidence("ACTIVE"),
             "CANCEL": evidence("CANCEL", cancellation_status="CANCELLED"),
             "CONFLICT": evidence("CONFLICT", conflict=True)}
    projection = project_trip_bookings(index, [active], source_generation="g",
                                       user_assignments={"trip:CONFLICT": {"trip_tab_id": "A"}})
    current = page_for_trip(projection, "A")
    history = page_for_trip(projection, "A", status="all")
    assert current["total_bookings"] == 1
    assert history["total_bookings"] == 3
    assert current["verified_passenger_count"] == history["verified_passenger_count"] == 2
    assert {item["booking_status"] for item in history["items"]} == {"ACTIVE", "CANCELLED", "CONFLICT"}
    other = trip("B", "2026-11-09", "2026-11-10")
    manual = project_trip_bookings({"ACTIVE": evidence("ACTIVE")}, [active, other],
                                   source_generation="g", user_assignments={
                                       "trip:ACTIVE": {"trip_tab_id": "B"}})
    assert manual["bookings"][0]["assigned_trip_tab_id"] == "B"
    assert manual["bookings"][0]["assignment_conflict"] is True
    assert page_for_trip(manual, "B")["verified_passenger_count"] == 0


def test_conflicting_flight_evidence_does_not_create_date_only_assignment():
    active = trip("A", "2026-11-07", "2026-11-10")
    index = {"PNR": evidence("PNR", conflict=True)}
    unresolved = project_trip_bookings(index, [active], source_generation="g")
    booking, = unresolved["bookings"]
    assert booking["assigned_trip_tab_id"] == ""
    assert booking["assignment_status"] == "CONFLICT"
    assert page_for_trip(unresolved, "A", status="all")["total_bookings"] == 0
    manual = project_trip_bookings(index, [active], source_generation="g",
                                   user_assignments={"trip:PNR": {"trip_tab_id": "A"}})
    assert manual["bookings"][0]["assignment_status"] == "USER_CONFIRMED"
    assert manual["bookings"][0]["assigned_trip_tab_id"] == "A"
    assert page_for_trip(manual, "A", status="all")["verified_passenger_count"] == 0
    linked = project_trip_bookings(index, [active], source_generation="g",
                                   authority_trip_ids={"trip:PNR": ["A"]})
    assert linked["bookings"][0]["assignment_status"] == "AUTHORITY_VERIFIED"
    assert linked["bookings"][0]["assigned_trip_tab_id"] == "A"
    assert page_for_trip(linked, "A", status="all")["verified_passenger_count"] == 0


def test_passenger_count_preserves_homonyms_and_provider_is_part_of_key():
    item = evidence("SAME")
    first = project_trip_bookings({"SAME": item}, [trip("A", "2026-11-07", "2026-11-10")], source_generation="g")["bookings"][0]
    assert first["passenger_count"] == 2
    assert "passengers" not in page_for_trip(project_trip_bookings({"SAME": item}, [trip("A", "2026-11-07", "2026-11-10")], source_generation="g"), "A")["items"][0]
    other_provider = {**item, "provider": "other"}
    result = project_trip_bookings({"SAME": other_provider}, [trip("A", "2026-11-07", "2026-11-10")], source_generation="g")
    assert result["bookings"][0]["provider"] == "other"


def test_explicit_booking_and_verified_card_authority_only():
    trips = [trip("A", "2026-11-07", "2026-11-08"), trip("B", "2026-11-09", "2026-11-10")]
    index = {"PNR": evidence("PNR")}
    users, authority, rev = build_authority_maps(index, trips,
        booking_trip_rules={("trip", "PNR"): {"status": "active", "trip_tab_id": "B", "revision": 2}},
        confirmed_card_links={"PNR": [{"transaction_id": "tx-1", "link_source": "USER_CONFIRMED"}]},
        expense_rows=[{"source_kind": "카드", "source_event_id": "tx-1", "display_tab_id": "A"}])
    result = project_trip_bookings(index, trips, source_generation=rev,
        user_assignments=users, authority_trip_ids=authority)["bookings"][0]
    assert result["assigned_trip_tab_id"] == "B"  # explicit booking choice wins
    assert result["assignment_conflict"] is True
    assert authority == {result["booking_key"]: ["A"]}

    # Merchant/amount coincidence or an unconfirmed payment link is not an authority.
    _, rejected, _ = build_authority_maps(index, trips,
        confirmed_card_links={"PNR": [{"transaction_id": "tx-1", "link_source": "MATCHED_AUTO"}]},
        expense_rows=[{"source_kind": "카드", "source_event_id": "tx-1", "display_tab_id": "A",
                       "merchant": "SAME", "amount_krw": 100}])
    assert rejected == {}


def test_verified_card_trip_adapter_uses_one_read_query_per_bounded_batch():
    class Connection:
        def __init__(self):
            self.calls = []
        def execute(self, sql, params):
            self.calls.append((sql, params))
            return SimpleNamespace(fetchall=lambda: [
                ("expense", "A", json.dumps({"source_kind": chr(0xCE74) + chr(0xB4DC),
                                               "source_event_id": "tx-1"}))])
    board = SimpleNamespace(conn=Connection())
    links = {"PNR": [{"transaction_id": "tx-1", "link_source": "USER_CONFIRMED"},
                     {"transaction_id": "tx-2", "link_source": "MATCHED_AUTO"}]}
    rows = confirmed_card_trip_rows(board, links)
    assert rows == [{"source_kind": chr(0xCE74) + chr(0xB4DC),
                     "source_event_id": "tx-1", "display_tab_id": "A"}]
    assert len(board.conn.calls) == 1
    assert "UPDATE" not in board.conn.calls[0][0].upper()


def test_detail_is_trip_scoped_and_first_received_date_label_is_preserved():
    trips = [trip("A", "2026-11-07", "2026-11-10")]
    projection = project_trip_bookings({"R": evidence("R", booking_date_status="FIRST_RECEIVED",
        reserved_on="2026-05-04")}, trips, source_generation="g")
    key = projection["bookings"][0]["booking_key"]
    detail = detail_for_trip(projection, "A", key)
    assert detail["item"]["booking_date_label"] == "최초 메일 수신일 기준 2026-05-04"
    assert "passengers" not in page_for_trip(projection, "A")["items"][0]
    with pytest.raises(LookupError, match="BOOKING_NOT_FOUND"):
        detail_for_trip(projection, "B", key)
    from webapp.trip_flight_read import handle_get
    mismatch = handle_get(None, board=None, trip_tab_id="A", query={"limit": ["20"]},
        is_owner=True, trip=trips[0], trips=trips, index={"R": evidence("R")},
        source_generation="g2", booking_key=key, expected_generation="g1")
    assert mismatch == {"code": "SOURCE_CHANGED"}


def test_render_trip_flights_is_public_lazy_hook():
    markup = render_trip_flights("A")
    assert 'class="trip-flight"' in markup
    assert "details.addEventListener('toggle'" in markup
    assert "booking_key" in markup


def test_booking_identity_survives_new_lineage_and_read_store_never_creates(tmp_path, monkeypatch):
    from webapp import trip_flight_read
    path = tmp_path / "absent.sqlite"
    monkeypatch.setattr("webapp.ota_payment_review.review_db_path", lambda: str(path))
    with pytest.raises(ValueError, match="FLIGHT_AUTHORITY_UNAVAILABLE"):
        trip_flight_read.read_booking_trip_rules()
    assert not path.exists()
    a = project_trip_bookings({"AB-123": evidence("AB-123")},
        [trip("A", "2026-11-07", "2026-11-10")], source_generation="g1")["bookings"][0]
    changed = evidence("AB-123")
    changed["source_digests"] = ["new-lineage"]
    b = project_trip_bookings({"AB-123": changed},
        [trip("A", "2026-11-07", "2026-11-10")], source_generation="g2")["bookings"][0]
    assert a["booking_key"] == b["booking_key"]


def test_existing_booking_trip_rules_are_read_without_mutating_synthetic_db(tmp_path, monkeypatch):
    from webapp import trip_flight_read
    path = tmp_path / "review.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE ota_review_booking_trips(provider TEXT, booking_ref TEXT, trip_tab_id TEXT, "
                 "trip_code TEXT, basis TEXT, revision INTEGER, status TEXT, user TEXT, changed_at TEXT)")
    conn.execute("INSERT INTO ota_review_booking_trips VALUES(?,?,?,?,?,?,?,?,?)",
        ("trip", "SYNTH", "trip-A", "", "explicit", 3, "active", "synthetic-owner", "2026-01-01"))
    conn.commit()
    conn.close()
    before = path.read_bytes()
    monkeypatch.setattr("webapp.ota_payment_review.review_db_path", lambda: str(path))
    rules = trip_flight_read.read_booking_trip_rules()
    assert rules[("trip", "SYNTH")]["revision"] == 3
    assert path.read_bytes() == before


def test_optional_booking_trip_schema_can_be_absent_in_isolated_review_store(tmp_path, monkeypatch):
    path = tmp_path / 'review.sqlite'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE ota_review_links(event_id TEXT PRIMARY KEY)')
    conn.commit()
    conn.close()
    before = path.read_bytes()
    monkeypatch.setattr('webapp.ota_payment_review.review_db_path', lambda: str(path))
    from webapp.trip_flight_read import read_booking_trip_rules
    assert read_booking_trip_rules() == {}
    class Handler:
        def _send_json(self, body, status=200):
            self.response = status, body
    handler = Handler()
    board = SimpleNamespace(live_trips=lambda **kwargs: [trip('A', '2026-11-07', '2026-11-10')])
    dispatch(handler, SimpleNamespace(path='/api/trips/A/flight-bookings', query=''),
             board=board, is_owner=True,
             snapshot={'fresh': True, 'generation': 'g', 'data': {'passengers': {'R': evidence('R')}}})
    assert handler.response[0] == 200
    assert handler.response[1]['total_bookings'] == 1
    assert handler.response[1]['items'][0]['assignment_status'] == 'AUTO_INFERRED'
    assert path.read_bytes() == before


@pytest.mark.parametrize('schema', [
    'CREATE TABLE unrelated(value TEXT)',
    'CREATE TABLE ota_review_booking_trip_history(value TEXT)',
    'CREATE TABLE ota_review_booking_trips(value TEXT)',
])
def test_unreadable_or_partial_booking_authority_still_fails_closed(tmp_path, monkeypatch, schema):
    path = tmp_path / 'review.sqlite'
    conn = sqlite3.connect(path)
    conn.execute(schema)
    conn.commit()
    conn.close()
    before = path.read_bytes()
    monkeypatch.setattr('webapp.ota_payment_review.review_db_path', lambda: str(path))
    from webapp.trip_flight_read import read_booking_trip_rules
    with pytest.raises(ValueError, match='FLIGHT_AUTHORITY_UNAVAILABLE'):
        read_booking_trip_rules()
    assert path.read_bytes() == before


def test_limit_is_capped_at_twenty_and_bad_limit_is_http_400():
    class Handler:
        def _send_json(self, body, status=200):
            self.response = (status, body)
    class Board:
        def live_trips(self, include_archived=False):
            return [trip("A", "2026-11-07", "2026-12-30")]
    handler = Handler()
    parsed = SimpleNamespace(path="/api/trips/A/flight-bookings", query="limit=21")
    dispatch(handler, parsed, board=Board(), is_owner=True,
        snapshot={"fresh": True, "generation": "g", "data": {"passengers": {}}})
    assert handler.response == (400, {"code": "INVALID_LIMIT"})


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
    assert len(handler.response[1]["source_generation"]) == 64
    handler = Handler()
    assert dispatch(handler, parsed, board=Board(), is_owner=True, raw=b"{}")
    assert handler.response[0] == 405


def test_overlapping_periods_need_evidence_except_unique_departure_start():
    trips = [trip("A", "2026-11-07", "2026-11-10"), trip("B", "2026-11-08", "2026-11-12")]
    ambiguous = resolve_assignment({"legs": [{"departure_on": "2026-11-09"}]}, trips)
    assert ambiguous["assignment_status"] == "CONFLICT"
    assert ambiguous["trip_tab_id"] == ""
    boundary = resolve_assignment({"legs": [{"departure_on": "2026-11-08"}]}, trips)
    assert boundary["trip_tab_id"] == "B"


def test_invalid_archived_and_disabled_trips_cannot_cut_open_trip_period():
    trips = [trip("A", "2026-11-07", ""),
             {**trip("old", "2026-11-08", "2026-11-11"), "archived": True},
             {**trip("disabled", "2026-11-08", "2026-11-11"), "enabled": False},
             trip("bad", "2026-11-08", "invalid"),
             trip("next", "2026-11-10", "2026-11-15")]
    result = resolve_assignment({"legs": [{"departure_on": "2026-11-09"}]}, trips)
    assert result["trip_tab_id"] == "A"


def test_opaque_trip_ids_are_url_encoded_then_decoded_before_authorization():
    from urllib.parse import quote
    tab = "여행 & A"
    encoded = quote(tab, safe="")
    assert f'/api/trips/{encoded}/flight-bookings' in render_flight_section(tab)
    class Handler:
        def _send_json(self, body, status=200):
            self.response = status, body
    board = SimpleNamespace(live_trips=lambda **kwargs: [trip(tab, "2026-11-07", "2026-11-10")])
    handler = Handler()
    dispatch(handler, SimpleNamespace(path=f"/api/trips/{encoded}/flight-bookings", query=""),
             board=board, is_owner=True, booking_trip_rules={},
             snapshot={"fresh": True, "generation": "g", "data": {"passengers": {"R": evidence("R")}}})
    assert handler.response[0] == 200
    assert handler.response[1]["trip_tab_id"] == tab


def test_configured_authority_failure_cannot_silently_replace_manual_choice(tmp_path, monkeypatch):
    from webapp import trip_flight_read
    path = tmp_path / "missing-authority.sqlite"
    monkeypatch.setattr("webapp.ota_payment_review.review_db_path", lambda: str(path))
    class Handler:
        def _send_json(self, body, status=200):
            self.response = status, body
    board = SimpleNamespace(live_trips=lambda **kwargs: [trip("A", "2026-11-07", "2026-11-10")])
    handler = Handler()
    dispatch(handler, SimpleNamespace(path="/api/trips/A/flight-bookings", query=""),
             board=board, is_owner=True,
             snapshot={"fresh": True, "generation": "g", "data": {"passengers": {"R": evidence("R")}}})
    assert handler.response == (503, {"code": "FLIGHT_AUTHORITY_UNAVAILABLE"})
    assert not path.exists()
