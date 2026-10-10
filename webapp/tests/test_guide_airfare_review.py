"""Guide airfare attribution with the reservation system as the guide/tour authority."""
import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app import flight_evidence, reservation_authority
from webapp import card_flow, guide_airfare_review, ota_payment_review

NOW = {"t": 1000.0}


def clock():
    return NOW["t"]


GUIDE = {"id": 7, "nickname": "닉네임", "real_name": "김철수", "flight_name_en": "KIM CHULSOO", "status": "active"}
OTHER_GUIDE = {"id": 8, "nickname": "다른대장", "real_name": "박영희", "flight_name_en": "PARK YOUNGHEE", "status": "active"}
TOUR = {"fldid": "F1", "code": "0801_북해도", "title": "t", "leader": "닉네임", "leader_guide_id": 7,
        "depart_date": "2026-08-01", "return_date": "2026-08-05", "status": "open"}


def authority(guides=None, tours=None):
    value = {"schema": reservation_authority.SCHEMA, "guides": copy.deepcopy(guides or [GUIDE]),
             "tours": copy.deepcopy(tours or [TOUR])}
    value["digest"] = reservation_authority.authority_digest(value)
    return value


def trip(trip_id="t1", key="0801_북해도", destination="북해도", starts_on="2026-08-01", ends_on="2026-08-05",
         name="김주형", source="owner_profile"):
    return {"tab_id": trip_id, "display_key": key, "destination": destination, "starts_on": starts_on,
            "ends_on": ends_on, "prepared_by_name": name, "assignee_source": source, "archived": False,
            "deleted": False, "revision": 1, "source_sha256": "s" * 8, "authority_status": "needs_review",
            "event_year": 2026}


class Board:
    def __init__(self, tmp_path, trips, state=None):
        self.path = tmp_path / "data" / "board.sqlite"
        self.trips = trips
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE reserve_trip_registrations(trip_id TEXT, source_key TEXT)")
        if state is not None:
            self._reservation_authority = state

    def list_trips(self, include_archived=False):
        return [dict(item) for item in self.trips]


def good_state(value=None):
    value = value or authority()
    return {"authority": value, "error": "", "checked_at": 0, "last_good_at": 0, "digest": value["digest"]}


@pytest.fixture
def valid_trips(monkeypatch):
    valid = set()
    monkeypatch.setattr(card_flow, "CardFlow", lambda board: SimpleNamespace(trip_valid=lambda tab: tab in valid))
    return valid


def evidence(passengers, legs, complete=True):
    return {"booking_ref": "REF1", "passengers": passengers, "legs": legs, "legs_complete": complete,
            "conflict": False, "source_digests": ["d1"], "digest": "e" * 64}


def leg(label, day, origin, destination):
    return {"label": label, "origin_city": "", "destination_city": "", "departure_on": day,
            "segments": [{"departure_airport": origin, "arrival_airport": destination}]}


ROUND_TRIP = [leg("가는편", "2026-07-30", "ICN", "CTS"), leg("오는편", "2026-08-06", "CTS", "ICN")]
CARD = {"transaction_id": "card-1", "transaction_direction": "purchase", "amount_krw": 500000}
EVENT = {"ota_event_id": "evt-1", "provider": "trip", "booking_ref": "REF1", "item": "항공료",
         "event_type": "charge"}
RESULT = {"ota_event_id": "evt-1", "status": "MATCHED_AUTO", "transaction_id": "card-1"}
GUIDE_PAX = {"surname": "KIM", "given_name": "CHULSOO"}
OTHER_PAX = {"surname": "LEE", "given_name": "YOUNGHEE"}


def run(board, monkeypatch, passengers, legs=ROUND_TRIP, event=EVENT, card=CARD):
    monkeypatch.setattr(flight_evidence, "collect_flight_evidence",
                        lambda directories: {("trip", "REF1"): evidence(passengers, legs)})
    return guide_airfare_review.evaluate(board, ["mail"], [event], [card], [RESULT])


def verdict_of(board, monkeypatch, passengers, **kwargs):
    return run(board, monkeypatch, passengers, **kwargs)["evt-1"]


def test_reservation_guide_with_assigned_bridged_trip_is_attributed(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    verdict = verdict_of(Board(tmp_path, [trip()], good_state()), monkeypatch, [GUIDE_PAX])
    assert (verdict["status"], verdict["trip_id"], verdict["trip_name"]) == ("ATTRIBUTED", "t1", "0801_북해도")
    assert verdict["code"] == "guide_airfare_round_trip" and verdict["guide_id"] == 7
    assert verdict["authority_digest"] == authority()["digest"][:12]


@pytest.mark.parametrize("pax", [{"surname": "kim", "given_name": "  chulsoo "},
                                 {"surname": "KIM", "given_name": "CHUL-SOO"} if False else {"surname": "Kim.", "given_name": "Chulsoo"}])
def test_case_space_and_punctuation_normalization_matches(tmp_path, valid_trips, monkeypatch, pax):
    valid_trips.add("t1")
    assert verdict_of(Board(tmp_path, [trip()], good_state()), monkeypatch, [pax])["status"] == "ATTRIBUTED"


@pytest.mark.parametrize("pax", [{"surname": "KIM", "given_name": "CHUL"}, {"surname": "KIM", "given_name": "SOO"},
                                 {"surname": "KIM", "given_name": "CHULSOOK"}, {"surname": "CHULSOO", "given_name": "KIM"}])
def test_partial_surname_only_and_reordered_names_do_not_match(tmp_path, valid_trips, monkeypatch, pax):
    valid_trips.add("t1")
    state = good_state(authority(guides=[GUIDE, OTHER_GUIDE]))
    verdict = verdict_of(Board(tmp_path, [trip()], state), monkeypatch, [pax])
    assert verdict["status"] == "NOT_APPLICABLE" and verdict["code"] == "NOT_APPLICABLE_NO_GUIDE_PASSENGER"


def test_a_guide_without_a_registered_flight_name_keeps_latin_names_unconfirmed(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    nameless = dict(GUIDE, flight_name_en=None)
    verdict = verdict_of(Board(tmp_path, [trip()], good_state(authority(guides=[nameless]))), monkeypatch, [GUIDE_PAX])
    assert (verdict["status"], verdict["code"]) == ("HOLD", "HOLD_GUIDE_IDENTITY_UNCONFIRMED")


def test_local_cost_assignee_and_local_alias_file_are_not_an_authority(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    root = tmp_path / "data"
    root.mkdir()
    (root / "guide-identities.json").write_text(json.dumps(
        {"version": 1, "guides": [{"assignee_name": "김주형", "aliases": [{"surname": "KIM", "given_name": "JOOHYUNG"}]}]},
        ensure_ascii=False), encoding="utf-8")
    state = good_state(authority(guides=[dict(GUIDE, flight_name_en=None)]))
    board = Board(tmp_path, [trip(name="김주형", source="manual")], state)
    verdict = verdict_of(board, monkeypatch, [{"surname": "KIM", "given_name": "JOOHYUNG"}])
    assert (verdict["status"], verdict["code"]) == ("HOLD", "HOLD_GUIDE_IDENTITY_UNCONFIRMED")


def test_a_guide_who_leads_no_bridged_trip_holds(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    unassigned = dict(TOUR, leader="다른대장", leader_guide_id=8)
    state = good_state(authority(guides=[GUIDE, OTHER_GUIDE], tours=[unassigned]))
    verdict = verdict_of(Board(tmp_path, [trip()], state), monkeypatch, [GUIDE_PAX])
    assert (verdict["status"], verdict["code"]) == ("HOLD", "HOLD_GUIDE_AIRFARE_NO_TRIP")


@pytest.mark.parametrize("change", [{"depart_date": "2026-08-02"}, {"return_date": "2026-08-06"},
                                    {"code": "0801_다른곳"}])
def test_date_or_code_mismatch_between_systems_holds(tmp_path, valid_trips, monkeypatch, change):
    valid_trips.add("t1")
    state = good_state(authority(tours=[dict(TOUR, **change)]))
    verdict = verdict_of(Board(tmp_path, [trip()], state), monkeypatch, [GUIDE_PAX])
    assert (verdict["status"], verdict["code"]) == ("HOLD", guide_airfare_review.MISMATCH)


def test_two_tours_claiming_the_same_trip_hold(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    second = dict(TOUR, fldid="F2", leader="다른대장", leader_guide_id=8)
    state = good_state(authority(guides=[GUIDE, OTHER_GUIDE], tours=[TOUR, second]))
    verdict = verdict_of(Board(tmp_path, [trip()], state), monkeypatch, [GUIDE_PAX])
    assert verdict["status"] == "HOLD" and verdict["code"] == guide_airfare_review.MISMATCH


def test_two_cost_trips_with_the_same_code_do_not_bridge(tmp_path, valid_trips, monkeypatch):
    valid_trips.update({"t1", "t2"})
    trips = [trip("t1"), trip("t2")]
    verdict = verdict_of(Board(tmp_path, trips, good_state()), monkeypatch, [GUIDE_PAX])
    assert verdict["status"] == "HOLD" and verdict["code"] == guide_airfare_review.MISMATCH


def test_a_non_authoritative_cost_trip_is_never_a_bridge_target(tmp_path, valid_trips, monkeypatch):
    verdict = verdict_of(Board(tmp_path, [trip()], good_state()), monkeypatch, [GUIDE_PAX])
    assert verdict["status"] == "HOLD" and verdict["code"] == guide_airfare_review.MISMATCH


def test_the_reserve_fldid_registration_is_a_bridge_key(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    board = Board(tmp_path, [trip(key="다른코드")], good_state(authority(tours=[dict(TOUR, code=None)])))
    board.conn.execute("INSERT INTO reserve_trip_registrations VALUES('t1','reserve:F1:2026')")
    assert verdict_of(board, monkeypatch, [GUIDE_PAX])["status"] == "ATTRIBUTED"
    board.conn.execute("UPDATE reserve_trip_registrations SET source_key='reserve:OTHER:2026'")
    assert verdict_of(board, monkeypatch, [GUIDE_PAX])["status"] == "HOLD"


def test_a_manual_cost_assignee_that_contradicts_reservation_is_a_conflict(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    board = Board(tmp_path, [trip(name="박다른", source="manual")], good_state())
    verdict = verdict_of(board, monkeypatch, [GUIDE_PAX])
    assert (verdict["status"], verdict["code"]) == ("HOLD", guide_airfare_review.CONFLICT)


def test_the_default_owner_profile_assignee_is_not_treated_as_an_assignment_claim(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    board = Board(tmp_path, [trip(name="박다른", source="owner_profile")], good_state())
    assert verdict_of(board, monkeypatch, [GUIDE_PAX])["status"] == "ATTRIBUTED"


def test_unavailable_authority_holds_every_airfare_and_never_means_no_guides(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    state = {"authority": None, "error": "timeout", "digest": "unavailable:timeout"}
    verdict = verdict_of(Board(tmp_path, [trip()], state), monkeypatch, [GUIDE_PAX])
    assert (verdict["status"], verdict["code"]) == ("HOLD", guide_airfare_review.UNAVAILABLE)
    assert verdict_of(Board(tmp_path, [trip()]), monkeypatch, [GUIDE_PAX])["code"] == guide_airfare_review.UNAVAILABLE


def test_mixed_passengers_and_refunds_keep_their_existing_protection(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    board = Board(tmp_path, [trip()], good_state())
    assert verdict_of(board, monkeypatch, [GUIDE_PAX, OTHER_PAX])["code"] == "HOLD_MIXED_PASSENGERS"
    refund = dict(CARD, transaction_direction="refund")
    assert verdict_of(board, monkeypatch, [GUIDE_PAX], card=refund)["code"] == "NOT_APPLICABLE_REFUND_EXISTING_PATH"


def test_the_published_verdict_carries_no_names_or_roster(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    board = Board(tmp_path, [trip()], good_state())
    text = json.dumps(run(board, monkeypatch, [GUIDE_PAX, OTHER_PAX]), ensure_ascii=False)
    text += json.dumps(run(board, monkeypatch, [GUIDE_PAX]), ensure_ascii=False)
    for name in ("CHULSOO", "KIM", "YOUNGHEE", "김철수", "닉네임", "PARK"):
        assert name not in text


class FakeFetch:
    def __init__(self):
        self.calls = 0
        self.value = authority()
        self.error = None

    def __call__(self):
        self.calls += 1
        if self.error:
            raise reservation_authority.AuthorityUnavailable(self.error)
        return self.value


def test_refresh_keeps_the_last_good_authority_for_the_grace_period_then_fails_closed(tmp_path):
    board = Board(tmp_path, [])
    fetch = FakeFetch()
    first = guide_airfare_review.refresh_authority(board, fetcher=fetch, clock=lambda: 0.0)
    assert first["authority"] is not None and first["digest"] == fetch.value["digest"]
    fetch.error = "timeout"
    kept = guide_airfare_review.refresh_authority(board, fetcher=fetch, clock=lambda: 100.0)
    assert kept["authority"] is not None and kept["degraded"] == "timeout"
    dead = guide_airfare_review.refresh_authority(board, fetcher=fetch, clock=lambda: 100.0 + 700.0)
    assert dead["authority"] is None and dead["error"] == "timeout" and dead["digest"] == "unavailable:timeout"


def test_refresh_is_throttled_and_without_a_token_makes_no_network_call(tmp_path, monkeypatch):
    board = Board(tmp_path, [])
    fetch = FakeFetch()
    guide_airfare_review.refresh_authority(board, fetcher=fetch, clock=lambda: 0.0)
    guide_airfare_review.refresh_authority(board, fetcher=fetch, clock=lambda: 10.0)
    assert fetch.calls == 1
    monkeypatch.delenv(reservation_authority.TOKEN_ENV, raising=False)
    monkeypatch.delenv(reservation_authority.TOKEN_FILE_ENV, raising=False)
    monkeypatch.setattr(reservation_authority.urllib.request, "OpenerDirector",
                        lambda *a, **k: pytest.fail("network used"), raising=False)
    state = guide_airfare_review.refresh_authority(Board(tmp_path, []), clock=lambda: 0.0)
    assert state["authority"] is None and state["error"] == "not_configured"


def digest(board):
    return guide_airfare_review.input_digest(board)


def test_input_digest_follows_reservation_authority_and_cost_trip_authority(tmp_path, valid_trips):
    valid_trips.add("t1")
    base = digest(Board(tmp_path, [trip()], good_state()))
    assert digest(Board(tmp_path, [trip()], good_state())) == base

    def changed(**tour_change):
        return digest(Board(tmp_path, [trip()], good_state(authority(tours=[dict(TOUR, **tour_change)]))))

    renamed = digest(Board(tmp_path, [trip()], good_state(authority(guides=[dict(GUIDE, flight_name_en="KIM CHULSOO JR")]))))
    inactive = digest(Board(tmp_path, [trip()], good_state(authority(guides=[dict(GUIDE, status="inactive")]))))
    assert len({base, renamed, inactive, changed(leader="다른대장", leader_guide_id=None),
                changed(depart_date="2026-08-02"), changed(code="0801_다른곳")}) == 6
    assert digest(Board(tmp_path, [trip(ends_on="2026-08-06")], good_state())) != base
    assert digest(Board(tmp_path, [trip()], None)) != base
    valid_trips.discard("t1")
    assert digest(Board(tmp_path, [trip()], good_state())) != base


def test_the_snapshot_input_key_includes_the_guide_state(monkeypatch):
    backend = SimpleNamespace(
        store=SimpleNamespace(), board=object(), _transactions=lambda: [],
        sources={"mail_directories": [], "portal_databases": [], "reference_documents": []})
    monkeypatch.setattr(ota_payment_review, "_guide_input_digest", lambda board: "one")
    first = ota_payment_review.input_key_for(backend)
    assert ota_payment_review.input_key_for(backend) == first
    monkeypatch.setattr(ota_payment_review, "_guide_input_digest", lambda board: "two")
    assert ota_payment_review.input_key_for(backend) != first


def test_the_request_path_digest_never_fetches(tmp_path, valid_trips, monkeypatch):
    valid_trips.add("t1")
    monkeypatch.setattr(reservation_authority, "fetch_authority",
                        lambda *a, **k: pytest.fail("fetched on the request path"))
    digest(Board(tmp_path, [trip()], good_state()))
    digest(Board(tmp_path, [trip()]))


class Service:
    def __init__(self, results, fresh=True):
        self.current = {"key": "k", "generation": 1, "results": results, "links": {}, "data": {}}
        self.fresh = fresh

    def held(self):
        return self.current, self.fresh


def flow_with(results, monkeypatch, fresh=True):
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE transactions(transaction_id TEXT, source_hash TEXT, merchant TEXT, merchant_normalized TEXT,"
        " card_kind TEXT, user_confirmed INT, classification_state TEXT, conflict_reason TEXT, parse_error TEXT,"
        " transaction_direction TEXT);"
        "CREATE TABLE import_batch_rows(batch_id TEXT, transaction_id TEXT);"
        "INSERT INTO transactions VALUES('card-1','hash-1','대표_카카오페이-트립닷컴','대표_카카오페이-트립닷컴','credit',0,'needs_review','','','purchase');"
        "INSERT INTO transactions VALUES('card-2','hash-2','다른 상점','다른 상점','credit',0,'needs_review','','','purchase');"
        "INSERT INTO import_batch_rows VALUES('b','card-1'),('b','card-2');")
    flow = card_flow.CardFlow.__new__(card_flow.CardFlow)
    flow.board = SimpleNamespace(conn=conn, _ota_snapshot_service=Service(results, fresh))
    monkeypatch.setattr(ota_payment_review, "enabled", lambda: True)
    return flow


ATTRIBUTED = {"status": "ATTRIBUTED", "code": "guide_airfare_pre_departure", "trip_id": "t1",
              "trip_name": "0801_북해도", "evidence_digest": "a" * 64, "booking_ref": "REF1"}


def test_the_card_flow_turns_an_attributed_verdict_into_one_guide_rule(monkeypatch):
    results = [{"ota_event_id": "e1", "status": "MATCHED_AUTO", "transaction_id": "card-1", "guide_airfare": ATTRIBUTED},
               {"ota_event_id": "e2", "status": "MATCHED_AUTO", "transaction_id": "card-2",
                "guide_airfare": dict(ATTRIBUTED, status="HOLD", code=guide_airfare_review.MISMATCH)}]
    rules = flow_with(results, monkeypatch)._guide_airfare_rules("b", None)
    assert len(rules) == 1
    rule = rules[0]
    assert rule["origin"] == "guide-airfare-live" and rule["optional"]["source_hash"] == "hash-1"
    assignment = rule["optional"]["inferred_assignment"]
    assert assignment["trip_id"] == "t1" and "여행 시작 전 출국" in assignment["basis"]
    assert rule["effects"] == {"item": "항공료", "description": "예약 REF1"}


def test_stale_missing_unselected_or_disabled_snapshot_yields_no_rules(monkeypatch):
    results = [{"status": "MATCHED_AUTO", "transaction_id": "card-1", "guide_airfare": ATTRIBUTED}]
    assert flow_with(results, monkeypatch, fresh=False)._guide_airfare_rules("b", None) == []
    assert flow_with(results, monkeypatch)._guide_airfare_rules("b", {"card-2"}) == []
    flow = flow_with(results, monkeypatch)
    flow.board._ota_snapshot_service.current = None
    assert flow._guide_airfare_rules("b", None) == []
    flow = flow_with(results, monkeypatch)
    assert len(flow._guide_airfare_rules("b", None)) == 1
    monkeypatch.setattr(ota_payment_review, "enabled", lambda: False)
    assert flow._guide_airfare_rules("b", None) == []
