import json
import sys
import types

import pytest

import app
from app import guide_airfare

GUIDE = "GUIDE"
GUIDE_P = {"surname": "QZA", "given_name": "QZB"}
OTHER_P = {"surname": "QZC", "given_name": "QZD"}
UNKNOWN_P = {"surname": "QZE", "given_name": "QZF"}
GUIDE_NAMES = {("QZA", "QZB")}
OTHER_NAMES = {("QZC", "QZD")}
IDENTITIES = [{"assignee_name": GUIDE, "normalized": GUIDE}]

TABLE = {
    "version": 1,
    "max_gap_days": 5,
    "korea_airports": ["KSA", "KSB"],
    "airports": {
        "JPA": {"country": "XX", "regions": ["가상북부"]},
        "JPB": {"country": "XX", "regions": ["가상남부"]},
    },
}


def _fake_match(passenger, identities):
    key = (passenger["surname"], passenger["given_name"])
    if key in GUIDE_NAMES:
        return {"status": "guide", "guide": GUIDE}
    if key in OTHER_NAMES:
        return {"status": "not_guide", "guide": ""}
    return {"status": "unknown", "guide": ""}


@pytest.fixture(autouse=True)
def identity_stub(monkeypatch):
    stub = types.ModuleType("app.guide_identity")
    stub.match_passenger = _fake_match
    monkeypatch.setitem(sys.modules, "app.guide_identity", stub)
    monkeypatch.setattr(app, "guide_identity", stub, raising=False)
    return stub


def _trip(trip_id, destination, starts, ends, assignee=GUIDE):
    return {"trip_id": trip_id, "display_key": f"trip-{trip_id}", "destination": destination,
            "starts_on": starts, "ends_on": ends, "assignee_name": assignee}


def _leg(label, origin, dest, on):
    return {"label": label, "origin_city": "", "destination_city": "", "departure_on": on,
            "segments": [{"departure_airport": origin, "arrival_airport": dest}]}


def _evidence(legs, passengers=None, legs_complete=True, conflict=False):
    return {"passengers": passengers or [GUIDE_P], "legs": legs, "legs_complete": legs_complete,
            "conflict": conflict, "digest": "digest-test-1"}


def _run(evidence, trips, item="항공료", card=None):
    return guide_airfare.attribute(evidence=evidence, identities=IDENTITIES, trips=trips,
                                   airports=TABLE, item=item, card_amount_krw=card)


NORTH = "가상북부"
SOUTH = "가상남부"


def test_pre_departure_outbound_attributes_next_trip():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    result = _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")]), [trip])
    assert result["status"] == "ATTRIBUTED"
    assert result["code"] == "guide_airfare_pre_departure"
    assert result["trip_id"] == "T1"
    assert result["trip_name"] == "trip-T1"
    assert result["candidate_trip_ids"] == ["T1"]


def test_post_trip_return_attributes_previous_trip():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    result = _run(_evidence([_leg("back", "JPA", "KSA", "2026-03-21")]), [trip])
    assert result["status"] == "ATTRIBUTED"
    assert result["code"] == "guide_airfare_post_trip_return"
    assert result["trip_id"] == "T1"


def test_inter_trip_positioning_attributes_next_trip():
    a = _trip("A", NORTH, "2026-03-01", "2026-03-10")
    b = _trip("B", SOUTH, "2026-03-25", "2026-04-05")
    result = _run(_evidence([_leg("move", "JPA", "JPB", "2026-03-22")]), [a, b])
    assert result["status"] == "ATTRIBUTED"
    assert result["code"] == "guide_airfare_inter_trip"
    assert result["trip_id"] == "B"


def test_inter_trip_positioning_attributes_previous_trip():
    a = _trip("A", NORTH, "2026-03-01", "2026-03-10")
    b = _trip("B", SOUTH, "2026-03-25", "2026-04-05")
    result = _run(_evidence([_leg("move", "JPA", "JPB", "2026-03-12")]), [a, b])
    assert result["status"] == "ATTRIBUTED"
    assert result["code"] == "guide_airfare_inter_trip"
    assert result["trip_id"] == "A"


def test_inter_trip_positioning_within_gap_of_both_is_ambiguous():
    a = _trip("A", NORTH, "2026-03-01", "2026-03-10")
    b = _trip("B", SOUTH, "2026-03-14", "2026-03-25")
    result = _run(_evidence([_leg("move", "JPA", "JPB", "2026-03-12")]), [a, b])
    assert result["status"] == "HOLD"
    assert result["code"] == "HOLD_GUIDE_AIRFARE_AMBIGUOUS"
    assert result["trip_id"] == ""


def test_mid_trip_join_outbound_inside_trip():
    trip = _trip("T1", NORTH, "2026-03-01", "2026-03-20")
    result = _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-05")]), [trip])
    assert result["status"] == "ATTRIBUTED"
    assert result["code"] == "guide_airfare_mid_trip_join"
    assert result["trip_id"] == "T1"


def test_early_leave_inbound_before_trip_end():
    trip = _trip("T1", NORTH, "2026-03-01", "2026-03-20")
    result = _run(_evidence([_leg("back", "JPA", "KSA", "2026-03-15")]), [trip])
    assert result["status"] == "ATTRIBUTED"
    assert result["code"] == "guide_airfare_early_leave"
    assert result["trip_id"] == "T1"


def test_no_authoritative_trips_holds():
    result = _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")]), [])
    assert result["status"] == "HOLD"
    assert result["code"] == "HOLD_GUIDE_AIRFARE_NO_TRIP"


def test_airport_region_contradicting_every_trip_is_unrelated():
    trip = _trip("T1", SOUTH, "2026-03-10", "2026-03-20")
    result = _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")]), [trip])
    assert result["status"] == "HOLD"
    assert result["code"] == "HOLD_FLIGHT_ROUTE_UNRELATED"


def test_unmapped_airport_is_unverified():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    result = _run(_evidence([_leg("out", "KSA", "UNM", "2026-03-08")]), [trip])
    assert result["status"] == "HOLD"
    assert result["code"] == "HOLD_FLIGHT_ROUTE_UNVERIFIED"


def test_only_non_guide_passengers_not_applicable():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    result = _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")], passengers=[OTHER_P]), [trip])
    assert result["status"] == "NOT_APPLICABLE"
    assert result["code"] == "NOT_APPLICABLE_NO_GUIDE_PASSENGER"
    assert result["guide_match"] == "not_guide"


def test_only_unknown_passengers_hold_identity():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    result = _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")], passengers=[UNKNOWN_P]), [trip])
    assert result["status"] == "HOLD"
    assert result["code"] == "HOLD_GUIDE_IDENTITY_UNCONFIRMED"
    assert result["guide_match"] == "unknown"


def test_mixed_passengers_without_fares_hold():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    result = _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")], passengers=[GUIDE_P, OTHER_P]), [trip],
                  card=500000)
    assert result["status"] == "HOLD"
    assert result["code"] == "HOLD_MIXED_PASSENGERS"
    assert result["mixed"] is True
    assert result["trip_id"] == ""
    assert result["guide_portion_krw"] is None


def test_mixed_passengers_with_fares_summing_to_card_hold_portion():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    guide = {**GUIDE_P, "fare_krw": 300000}
    other = {**OTHER_P, "fare_krw": 200000}
    result = _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")], passengers=[guide, other]), [trip],
                  card=500000)
    assert result["status"] == "HOLD"
    assert result["code"] == "HOLD_GUIDE_PORTION_ONLY"
    assert result["guide_portion_krw"] == 300000
    assert result["trip_id"] == "T1"
    assert result["trip_name"] == "trip-T1"
    assert result["mixed"] is True


def test_round_trip_same_trip_attributes():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    legs = [_leg("out", "KSA", "JPA", "2026-03-08"), _leg("back", "JPA", "KSA", "2026-03-21")]
    result = _run(_evidence(legs), [trip])
    assert result["status"] == "ATTRIBUTED"
    assert result["code"] == "guide_airfare_round_trip"
    assert result["trip_id"] == "T1"


def test_round_trip_return_from_other_trip_is_ambiguous():
    t1 = _trip("T1", NORTH, "2026-03-01", "2026-03-10")
    t2 = _trip("T2", SOUTH, "2026-03-20", "2026-03-25")
    legs = [_leg("out", "KSA", "JPA", "2026-02-27"), _leg("back", "JPB", "KSA", "2026-03-26")]
    result = _run(_evidence(legs), [t1, t2])
    assert result["status"] == "HOLD"
    assert result["code"] == "HOLD_GUIDE_AIRFARE_AMBIGUOUS"


def test_incomplete_itinerary_holds():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    result = _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")], legs_complete=False), [trip])
    assert result["code"] == "HOLD_FLIGHT_ITINERARY_INCOMPLETE"
    undated = _run(_evidence([_leg("out", "KSA", "JPA", "")]), [trip])
    assert undated["code"] == "HOLD_FLIGHT_ITINERARY_INCOMPLETE"


def test_missing_evidence_holds():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    result = _run(None, [trip])
    assert result["status"] == "HOLD"
    assert result["code"] == "HOLD_PASSENGER_EVIDENCE_MISSING"


def test_non_airfare_item_not_applicable():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    result = _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")]), [trip], item="숙박비")
    assert result["status"] == "NOT_APPLICABLE"
    assert result["code"] == "NOT_APPLICABLE_NOT_AIRFARE"


def test_guide_abroad_on_other_trip_drops_outbound_relation():
    t1 = _trip("T1", SOUTH, "2026-03-05", "2026-03-15")
    t2 = _trip("T2", NORTH, "2026-03-10", "2026-03-20")
    leg = [_leg("out", "KSA", "JPA", "2026-03-08")]
    result = _run(_evidence(leg), [t1, t2])
    assert result["status"] == "HOLD"
    assert result["code"] == "HOLD_FLIGHT_ROUTE_UNRELATED"
    control = _run(_evidence(leg), [t2])
    assert control["code"] == "guide_airfare_pre_departure"
    assert control["trip_id"] == "T2"


def test_load_airport_table_has_production_entries():
    table = guide_airfare.load_airport_table()
    assert table["airports"]["CTS"]["regions"] == ["북해도"]
    assert "NRT" not in table["airports"]
    assert "HND" not in table["airports"]
    digest = guide_airfare.airport_table_digest(table)
    assert len(digest) == 64
    assert digest == guide_airfare.airport_table_digest(json.loads(json.dumps(table)))


def test_result_contains_no_passenger_names():
    trip = _trip("T1", NORTH, "2026-03-10", "2026-03-20")
    guide = {**GUIDE_P, "fare_krw": 300000}
    other = {**OTHER_P, "fare_krw": 200000}
    results = [
        _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")], passengers=[guide, other]), [trip], card=500000),
        _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")], passengers=[guide]), [trip]),
        _run(_evidence([_leg("out", "KSA", "JPA", "2026-03-08")], passengers=[OTHER_P]), [trip]),
    ]
    names = ["QZA", "QZB", "QZC", "QZD", "QZE", "QZF"]
    for result in results:
        text = json.dumps(result, ensure_ascii=False)
        assert not any(name in text for name in names)
