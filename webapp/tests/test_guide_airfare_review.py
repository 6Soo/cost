"""Guide airfare attribution inside the OTA snapshot: evaluation, input fingerprint, classification hook."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app import flight_evidence
from webapp import card_flow, guide_airfare_review, ota_payment_review

REGISTRY = {"version": 1, "guides": [{"assignee_name": "김철수",
                                      "aliases": [{"surname": "KIM", "given_name": "CHULSOO"}]}]}


def trip(trip_id, key, destination, starts_on, ends_on, name="김철수", source="manual"):
    return {"tab_id": trip_id, "display_key": key, "destination": destination, "starts_on": starts_on,
            "ends_on": ends_on, "prepared_by_name": name, "assignee_source": source, "archived": False,
            "deleted": False, "revision": 1, "source_sha256": "s" * 8, "authority_status": "needs_review",
            "event_year": 2026}


class Board:
    def __init__(self, tmp_path, trips, owner=""):
        self.path = tmp_path / "board.sqlite"
        self.trips = trips
        self.owner = owner

    def list_trips(self, include_archived=False):
        return [dict(item) for item in self.trips]

    def owner_profile(self):
        return {"assignee_name": self.owner}


@pytest.fixture
def valid_trips(monkeypatch):
    valid = set()
    monkeypatch.setattr(card_flow, "CardFlow", lambda board: SimpleNamespace(trip_valid=lambda tab: tab in valid))
    return valid


@pytest.fixture
def registry_file(tmp_path, monkeypatch):
    path = tmp_path / "guide-identities.json"
    path.write_text(json.dumps(REGISTRY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv(guide_airfare_review.REGISTRY_ENV, str(path))
    return path


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
TRIP = trip("t1", "0801_북해도", "북해도", "2026-08-01", "2026-08-05")


def run(board, monkeypatch, passengers, legs=ROUND_TRIP, event=EVENT, card=CARD, complete=True):
    monkeypatch.setattr(flight_evidence, "collect_flight_evidence",
                        lambda directories: {("trip", "REF1"): evidence(passengers, legs, complete)})
    return guide_airfare_review.evaluate(board, ["mail"], [event], [card], [RESULT])


GUIDE = {"surname": "KIM", "given_name": "CHULSOO"}
OTHER = {"surname": "LEE", "given_name": "YOUNGHEE"}


def test_registered_guide_round_trip_is_attributed_to_the_one_trip(tmp_path, valid_trips, registry_file, monkeypatch):
    valid_trips.add("t1")
    verdict = run(Board(tmp_path, [TRIP]), monkeypatch, [GUIDE])["evt-1"]
    assert (verdict["status"], verdict["trip_id"], verdict["trip_name"]) == ("ATTRIBUTED", "t1", "0801_북해도")
    assert verdict["code"] == "guide_airfare_round_trip"
    assert verdict["booking_ref"] == "REF1" and verdict["evidence_digest"] == "e" * 64


def test_without_a_registered_alias_the_latin_name_stays_unconfirmed(tmp_path, valid_trips, monkeypatch):
    monkeypatch.delenv(guide_airfare_review.REGISTRY_ENV, raising=False)
    valid_trips.add("t1")
    verdict = run(Board(tmp_path, [TRIP]), monkeypatch, [GUIDE])["evt-1"]
    assert (verdict["status"], verdict["code"]) == ("HOLD", "HOLD_GUIDE_IDENTITY_UNCONFIRMED")


def test_a_booking_without_the_guide_is_not_applicable(tmp_path, valid_trips, registry_file, monkeypatch):
    valid_trips.add("t1")
    verdict = run(Board(tmp_path, [TRIP]), monkeypatch, [OTHER])["evt-1"]
    assert (verdict["status"], verdict["code"]) == ("NOT_APPLICABLE", "NOT_APPLICABLE_NO_GUIDE_PASSENGER")


def test_mixed_passengers_without_fares_hold(tmp_path, valid_trips, registry_file, monkeypatch):
    valid_trips.add("t1")
    verdict = run(Board(tmp_path, [TRIP]), monkeypatch, [GUIDE, OTHER])["evt-1"]
    assert (verdict["status"], verdict["code"], verdict["mixed"]) == ("HOLD", "HOLD_MIXED_PASSENGERS", True)


def test_a_trip_that_is_not_authoritative_is_never_a_target(tmp_path, valid_trips, registry_file, monkeypatch):
    verdict = run(Board(tmp_path, [TRIP]), monkeypatch, [GUIDE])["evt-1"]
    assert (verdict["status"], verdict["code"]) == ("HOLD", "HOLD_GUIDE_AIRFARE_NO_TRIP")


def test_an_untrusted_assignee_source_creates_no_guide_identity(tmp_path, valid_trips, registry_file, monkeypatch):
    valid_trips.add("t1")
    seeded = trip("t1", "0801_북해도", "북해도", "2026-08-01", "2026-08-05", source="seed")
    verdict = run(Board(tmp_path, [seeded]), monkeypatch, [GUIDE])["evt-1"]
    assert verdict["status"] == "HOLD" and verdict["code"] == "HOLD_GUIDE_IDENTITY_UNCONFIRMED"


def test_a_refund_or_non_purchase_card_keeps_the_existing_refund_path(tmp_path, valid_trips, registry_file, monkeypatch):
    valid_trips.add("t1")
    refund = dict(CARD, transaction_direction="refund")
    verdict = run(Board(tmp_path, [TRIP]), monkeypatch, [GUIDE], card=refund)["evt-1"]
    assert verdict["code"] == "NOT_APPLICABLE_REFUND_EXISTING_PATH"
    verdict = run(Board(tmp_path, [TRIP]), monkeypatch, [GUIDE], event=dict(EVENT, event_type="refund"))["evt-1"]
    assert verdict["code"] == "NOT_APPLICABLE_REFUND_EXISTING_PATH"


def test_only_matched_airfare_events_are_evaluated(tmp_path, valid_trips, registry_file, monkeypatch):
    valid_trips.add("t1")
    assert run(Board(tmp_path, [TRIP]), monkeypatch, [GUIDE], event=dict(EVENT, item="숙박비")) == {}
    held = guide_airfare_review.evaluate(Board(tmp_path, [TRIP]), [], [EVENT], [CARD],
                                         [dict(RESULT, status="HOLD_NO_CARD")])
    assert held == {}


def test_the_published_verdict_carries_no_passenger_names(tmp_path, valid_trips, registry_file, monkeypatch):
    valid_trips.add("t1")
    for passengers in ([GUIDE], [GUIDE, OTHER]):
        text = json.dumps(run(Board(tmp_path, [TRIP]), monkeypatch, passengers), ensure_ascii=False)
        for name in ("CHULSOO", "YOUNGHEE", "KIM", "LEE"):
            assert name not in text


def test_a_failed_evaluation_fails_closed(tmp_path):
    verdict = guide_airfare_review.failed(RuntimeError("x"))
    assert verdict["status"] == "HOLD" and verdict["code"] == "HOLD_GUIDE_AIRFARE_ERROR"


def digest(board):
    return guide_airfare_review.input_digest(board)


def test_input_digest_is_stable_and_follows_every_guide_input(tmp_path, valid_trips, registry_file, monkeypatch):
    valid_trips.add("t1")
    base = digest(Board(tmp_path, [TRIP]))
    assert digest(Board(tmp_path, [TRIP])) == base
    assert digest(Board(tmp_path, [dict(TRIP, prepared_by_name="박영수")])) != base
    assert digest(Board(tmp_path, [dict(TRIP, assignee_source="owner_profile")])) != base
    assert digest(Board(tmp_path, [dict(TRIP, ends_on="2026-08-06")])) != base
    assert digest(Board(tmp_path, [dict(TRIP, source_sha256="changed")])) != base
    assert digest(Board(tmp_path, [TRIP], owner="김철수")) != base
    valid_trips.discard("t1")
    assert digest(Board(tmp_path, [TRIP])) != base
    valid_trips.add("t1")
    registry_file.write_text(json.dumps(dict(REGISTRY, guides=[])), encoding="utf-8")
    assert digest(Board(tmp_path, [TRIP])) != base


def test_input_digest_follows_the_airport_table_and_parser_versions(tmp_path, valid_trips, registry_file, monkeypatch):
    valid_trips.add("t1")
    base = digest(Board(tmp_path, [TRIP]))
    table = tmp_path / "airports.json"
    from app import guide_airfare
    changed = guide_airfare.load_airport_table()
    changed["max_gap_days"] += 1
    table.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv(guide_airfare_review.AIRPORTS_ENV, str(table))
    assert digest(Board(tmp_path, [TRIP])) != base
    monkeypatch.delenv(guide_airfare_review.AIRPORTS_ENV)
    monkeypatch.setattr(flight_evidence, "PARSER_VERSION", "flight-evidence-vX")
    assert digest(Board(tmp_path, [TRIP])) != base


def test_the_snapshot_input_key_includes_the_guide_state(tmp_path, monkeypatch):
    backend = SimpleNamespace(
        store=SimpleNamespace(), board=object(), _transactions=lambda: [],
        sources={"mail_directories": [], "portal_databases": [], "reference_documents": []})
    monkeypatch.setattr(ota_payment_review, "_guide_input_digest", lambda board: "one")
    first = ota_payment_review.input_key_for(backend)
    assert ota_payment_review.input_key_for(backend) == first
    monkeypatch.setattr(ota_payment_review, "_guide_input_digest", lambda board: "two")
    assert ota_payment_review.input_key_for(backend) != first


class Service:
    def __init__(self, results, fresh=True):
        self.current = {"key": "k", "generation": 1, "results": results, "links": {}, "data": {}}
        self.fresh = fresh

    def held(self):
        return self.current, self.fresh


def flow_with(results, tmp_path, monkeypatch, fresh=True):
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


def test_the_card_flow_turns_an_attributed_verdict_into_one_guide_rule(tmp_path, monkeypatch):
    results = [{"ota_event_id": "e1", "status": "MATCHED_AUTO", "transaction_id": "card-1",
                "guide_airfare": ATTRIBUTED},
               {"ota_event_id": "e2", "status": "MATCHED_AUTO", "transaction_id": "card-2",
                "guide_airfare": dict(ATTRIBUTED, status="HOLD", code="HOLD_GUIDE_AIRFARE_AMBIGUOUS")}]
    rules = flow_with(results, tmp_path, monkeypatch)._guide_airfare_rules("b", None)
    assert len(rules) == 1
    rule = rules[0]
    assert rule["origin"] == "guide-airfare-live" and rule["optional"]["source_hash"] == "hash-1"
    assignment = rule["optional"]["inferred_assignment"]
    assert assignment["trip_id"] == "t1" and "여행 시작 전 출국" in assignment["basis"]
    assert "aaaaaaaaaaaa" in assignment["basis"]
    assert rule["effects"] == {"item": "항공료", "description": "예약 REF1"}


def test_a_stale_missing_or_unselected_snapshot_yields_no_rules(tmp_path, monkeypatch):
    results = [{"status": "MATCHED_AUTO", "transaction_id": "card-1", "guide_airfare": ATTRIBUTED}]
    assert flow_with(results, tmp_path, monkeypatch, fresh=False)._guide_airfare_rules("b", None) == []
    assert flow_with(results, tmp_path, monkeypatch)._guide_airfare_rules("b", {"card-2"}) == []
    flow = flow_with(results, tmp_path, monkeypatch)
    flow.board._ota_snapshot_service.current = None
    assert flow._guide_airfare_rules("b", None) == []
    flow = flow_with(results, tmp_path, monkeypatch)
    assert len(flow._guide_airfare_rules("b", None)) == 1
    monkeypatch.setattr(ota_payment_review, "enabled", lambda: False)
    assert flow._guide_airfare_rules("b", None) == []
