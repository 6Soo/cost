"""Display grace is not write authority: only fresh reservation authority may justify a guide ledger write."""
import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app import reservation_authority
from webapp import card_flow, guide_airfare_review as gar, ota_payment_review

GUIDE = {"id": 7, "nickname": "닉네임", "real_name": "김철수", "flight_name_en": "KIM CHULSOO", "status": "active"}
TOUR = {"fldid": "F1", "code": None, "title": "t", "leader": "닉네임", "leader_guide_id": 7,
        "depart_date": "2026-08-01", "return_date": "2026-08-05", "status": "open"}


def authority(guide=None):
    value = {"schema": reservation_authority.SCHEMA, "guides": [copy.deepcopy(guide or GUIDE)],
             "tours": [copy.deepcopy(TOUR)]}
    value["digest"] = reservation_authority.authority_digest(value)
    return value


class Fetch:
    def __init__(self):
        self.value = authority()
        self.error = None
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error:
            raise reservation_authority.AuthorityUnavailable(self.error)
        return self.value


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def board(tmp_path):
    return SimpleNamespace(path=tmp_path / "data" / "board.sqlite")


def test_fresh_authority_allows_a_write_and_ages_out_of_the_write_window(board):
    clock, fetch = Clock(), Fetch()
    gar.refresh_authority(board, fetcher=fetch, clock=clock)
    assert gar.write_authorization(board, clock=clock) == (True, "")
    clock.now = gar.WRITE_FRESH_SECONDS + 1
    assert gar.write_authorization(board, clock=clock) == (False, "GUIDE_AUTHORITY_STALE")


def test_degraded_last_good_is_shown_but_never_authorizes_a_write(board):
    clock, fetch = Clock(), Fetch()
    gar.refresh_authority(board, fetcher=fetch, clock=clock)
    fetch.error = "timeout"
    clock.now = 50
    state = gar.refresh_authority(board, fetcher=fetch, clock=clock)
    assert state["authority"] is not None and state["degraded"] is True and state["fresh"] is False
    assert gar.state_label(state) == "degraded"
    assert gar.write_authorization(board, clock=clock) == (False, "GUIDE_AUTHORITY_DEGRADED")
    assert gar.authority_summary(board)["state"] == "degraded"
    assert gar.authority_summary(board)["error"] == "timeout"


def test_the_ten_minute_display_grace_is_separate_from_the_write_window(board):
    assert gar.GRACE_SECONDS > gar.WRITE_FRESH_SECONDS
    clock, fetch = Clock(), Fetch()
    gar.refresh_authority(board, fetcher=fetch, clock=clock)
    fetch.error = "timeout"
    clock.now = gar.GRACE_SECONDS - 10
    state = gar.refresh_authority(board, fetcher=fetch, clock=clock)
    assert state["authority"] is not None
    assert gar.write_authorization(board, clock=clock)[0] is False
    clock.now = gar.GRACE_SECONDS + 100
    state = gar.refresh_authority(board, fetcher=fetch, clock=clock)
    assert state["authority"] is None
    assert gar.write_authorization(board, clock=clock) == (False, "GUIDE_AUTHORITY_UNAVAILABLE")


def test_recovery_makes_the_authority_fresh_again(board):
    clock, fetch = Clock(), Fetch()
    gar.refresh_authority(board, fetcher=fetch, clock=clock)
    fetch.error = "timeout"
    clock.now = 60
    gar.refresh_authority(board, fetcher=fetch, clock=clock)
    fetch.error = None
    clock.now = 120
    state = gar.refresh_authority(board, fetcher=fetch, clock=clock)
    assert state["fresh"] is True and state["degraded"] is False
    assert gar.write_authorization(board, clock=clock) == (True, "")


def test_unconfigured_authority_never_authorizes(board):
    assert gar.write_authorization(board) == (False, "GUIDE_AUTHORITY_UNAVAILABLE")


def test_the_snapshot_fingerprint_changes_when_freshness_changes_with_the_same_content(board, monkeypatch):
    monkeypatch.setattr(card_flow, "CardFlow", lambda b: SimpleNamespace(trip_valid=lambda t: False))
    clock, fetch = Clock(), Fetch()
    gar.refresh_authority(board, fetcher=fetch, clock=clock)
    fresh = gar.input_digest(board)
    fetch.error = "timeout"
    clock.now = 60
    gar.refresh_authority(board, fetcher=fetch, clock=clock)
    degraded = gar.input_digest(board)
    assert board._reservation_authority["digest"] == fetch.value["digest"]
    assert fresh != degraded
    fetch.error = None
    clock.now = 120
    gar.refresh_authority(board, fetcher=fetch, clock=clock)
    assert gar.input_digest(board) == fresh


def test_no_network_call_on_any_request_side_function(board, monkeypatch):
    monkeypatch.setattr(card_flow, "CardFlow", lambda b: SimpleNamespace(trip_valid=lambda t: False))
    clock, fetch = Clock(), Fetch()
    gar.refresh_authority(board, fetcher=fetch, clock=clock)
    monkeypatch.setattr(reservation_authority, "fetch_authority", lambda *a, **k: pytest.fail("fetched"))
    gar.write_authorization(board, clock=clock)
    gar.authority_summary(board)
    gar.input_digest(board)
    assert fetch.calls == 1


class Service:
    def __init__(self, results, fresh=True):
        self.current = {"key": "k", "generation": 1, "results": results, "links": {}, "data": {}}
        self.fresh = fresh

    def held(self):
        return self.current, self.fresh


def make_flow(tmp_path, results, monkeypatch, *, enabled=True, fresh_snapshot=True):
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE transactions(transaction_id TEXT, source_hash TEXT, merchant TEXT, merchant_normalized TEXT,"
        " card_kind TEXT, user_confirmed INT, classification_state TEXT, classification_source TEXT, trip_id TEXT,"
        " conflict_reason TEXT, parse_error TEXT, transaction_direction TEXT);"
        "CREATE TABLE import_batch_rows(batch_id TEXT, transaction_id TEXT);"
        "INSERT INTO transactions VALUES('guide-card','h1','대표_카카오페이-트립닷컴','대표_카카오페이-트립닷컴','credit',0,"
        "'classified','guide_airfare_evidence','t1','','','purchase');"
        "INSERT INTO transactions VALUES('plain-card','h2','다른 상점','다른 상점','credit',0,"
        "'classified','rule','','','','purchase');"
        "INSERT INTO import_batch_rows VALUES('b','guide-card'),('b','plain-card');")
    board = SimpleNamespace(conn=conn, path=tmp_path / "data" / "board.sqlite",
                            _ota_snapshot_service=Service(results, fresh_snapshot))
    flow = card_flow.CardFlow.__new__(card_flow.CardFlow)
    flow.board = board
    flow._ota_group_holds_cache = None
    monkeypatch.setattr(ota_payment_review, "enabled", lambda: enabled)
    return flow, board


def supported(board, trip="t1"):
    return [{"status": "MATCHED_AUTO", "transaction_id": "guide-card",
             "guide_airfare": {"status": "ATTRIBUTED", "trip_id": trip, "authority_state": "fresh",
                               "authority_digest": gar.authority_summary(board)["digest"]}}]


def test_a_fresh_supported_guide_row_has_no_hold_and_other_cards_are_untouched(tmp_path, monkeypatch):
    clock = Clock()
    flow, board = make_flow(tmp_path, [], monkeypatch)
    gar.refresh_authority(board, fetcher=Fetch(), clock=lambda: __import__("time").monotonic())
    board._ota_snapshot_service.current["results"] = supported(board)
    assert flow._guide_write_holds() == {}


def test_degraded_authority_holds_only_the_guide_row_C(tmp_path, monkeypatch):
    import time
    flow, board = make_flow(tmp_path, [], monkeypatch)
    now = time.monotonic()
    fetch = Fetch()
    gar.refresh_authority(board, fetcher=fetch, clock=lambda: now - 100)
    fetch.error = "timeout"
    gar.refresh_authority(board, fetcher=fetch, clock=lambda: now)
    board._ota_snapshot_service.current["results"] = supported(board)
    holds = flow._guide_write_holds()
    assert set(holds) == {"guide-card"}
    assert holds["guide-card"]["code"] == "GUIDE_AUTHORITY_DEGRADED"
    assert holds["guide-card"]["kind"] == "guide_authority_hold"


def test_unavailable_or_unconfigured_authority_holds_the_guide_row(tmp_path, monkeypatch):
    flow, board = make_flow(tmp_path, [], monkeypatch)
    assert flow._guide_write_holds()["guide-card"]["code"] == "GUIDE_AUTHORITY_UNAVAILABLE"


def test_a_stale_snapshot_or_changed_attribution_holds(tmp_path, monkeypatch):
    import time
    flow, board = make_flow(tmp_path, [], monkeypatch, fresh_snapshot=False)
    gar.refresh_authority(board, fetcher=Fetch(), clock=time.monotonic)
    board._ota_snapshot_service.current["results"] = supported(board)
    assert flow._guide_write_holds()["guide-card"]["code"] == "GUIDE_SNAPSHOT_STALE"
    board._ota_snapshot_service.fresh = True
    board._ota_snapshot_service.current["results"] = supported(board, trip="other")
    assert flow._guide_write_holds()["guide-card"]["code"] == "GUIDE_ATTRIBUTION_CHANGED"
    board._ota_snapshot_service.current["results"] = [dict(supported(board)[0],
        guide_airfare={"status": "HOLD", "trip_id": ""})]
    assert flow._guide_write_holds()["guide-card"]["code"] == "GUIDE_ATTRIBUTION_CHANGED"


def test_a_new_authority_digest_after_the_snapshot_holds_the_old_attribution(tmp_path, monkeypatch):
    import time
    flow, board = make_flow(tmp_path, [], monkeypatch)
    fetch = Fetch()
    gar.refresh_authority(board, fetcher=fetch, clock=time.monotonic)
    board._ota_snapshot_service.current["results"] = supported(board)
    assert flow._guide_write_holds() == {}
    fetch.value = authority(dict(GUIDE, flight_name_en="KIM CHULSOO JR"))
    board._reservation_authority["checked_at"] = -1000
    gar.refresh_authority(board, fetcher=fetch, clock=time.monotonic)
    assert flow._guide_write_holds()["guide-card"]["code"] == "GUIDE_ATTRIBUTION_CHANGED"


def test_guide_holds_join_the_ledger_preview_holds_even_when_ota_review_is_off(tmp_path, monkeypatch):
    flow, board = make_flow(tmp_path, [], monkeypatch, enabled=False)
    holds = flow.ota_group_holds()
    assert set(holds) == {"guide-card"} and holds["guide-card"]["reason"]


def test_a_non_guide_card_is_never_held_by_this_guard(tmp_path, monkeypatch):
    flow, board = make_flow(tmp_path, [], monkeypatch, enabled=False)
    board.conn.execute("UPDATE transactions SET classification_source='rule' WHERE transaction_id='guide-card'")
    assert flow._guide_write_holds() == {}


def test_new_guide_rules_require_fresh_authority(tmp_path, monkeypatch):
    import time
    results = [{"status": "MATCHED_AUTO", "transaction_id": "guide-card",
                "guide_airfare": {"status": "ATTRIBUTED", "code": "guide_airfare_round_trip", "trip_id": "t1",
                                  "trip_name": "0801", "evidence_digest": "a" * 64, "booking_ref": "R"}}]
    flow, board = make_flow(tmp_path, results, monkeypatch)
    board.conn.execute("UPDATE transactions SET classification_source='', user_confirmed=0")
    assert flow._guide_airfare_rules("b", None) == []
    fetch = Fetch()
    gar.refresh_authority(board, fetcher=fetch, clock=time.monotonic)
    assert len(flow._guide_airfare_rules("b", None)) == 1
    fetch.error = "timeout"
    board._reservation_authority["checked_at"] = -1000
    gar.refresh_authority(board, fetcher=fetch, clock=time.monotonic)
    assert flow._guide_airfare_rules("b", None) == []


def test_a_preview_taken_before_the_authority_degraded_cannot_commit_the_row():
    from app.db import StoreError
    from tests.card_pipeline.test_review_holds import setup
    pipe, batch, row = setup()
    preview = pipe.preview(batch, tab_validator=lambda _: True)
    assert preview["ready"] == 1
    hold = {row["transaction_id"]: {"kind": "guide_authority_hold", "code": "GUIDE_AUTHORITY_DEGRADED",
                                    "reason": "대장 항공권 근거가 현재 확인된 reservation 자료로 뒷받침되지 않아 기록하지 않아요"}}
    projected = []
    with pytest.raises(StoreError) as caught:
        pipe.commit(batch, preview["digest"], "guide-stale", tab_validator=lambda _: True,
                    additional_holds=hold, projection=projected.append)
    assert caught.value.code == "PREVIEW_STALE" or "미리보기" in str(caught.value)
    assert projected == []
    assert pipe.store.conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == 0
    # a fresh preview taken under the hold shows the row blocked and books nothing
    held = pipe.preview(batch, tab_validator=lambda _: True, additional_holds=hold)
    assert held["ready"] == 0 and held["rows"][0]["blocked"] == "review_hold"


def _trip(tab_id, key, starts="2026-08-01", ends="2026-08-05", valid=True):
    return {"tab_id": tab_id, "display_key": key, "starts_on": starts, "ends_on": ends, "valid": valid}


def _tour(fldid, code=None, depart="2026-08-01", ret="2026-08-05"):
    return dict(TOUR, fldid=fldid, code=code, depart_date=depart, return_date=ret)


def _coverage(tours, trips, registrations):
    value = {"guides": [GUIDE], "tours": tours}
    return gar.bridge_coverage(value, trips, registrations)


def test_bridge_coverage_classifies_every_trip_without_guessing():
    trips = [_trip("a", "0801_가"), _trip("b", "0802_나"), _trip("c", "0803_다"), _trip("d", "0804_라"),
             _trip("e", "0805_마"), _trip("f", "0806_바"), _trip("g", "0807_사", valid=False)]
    tours = [
        _tour("FA"),                                  # a: fldid only
        _tour("FB", code="0802_나"),                  # b: code only
        _tour("FC", code="0803_다"),                  # c: fldid and code, same tour
        _tour("FD", depart="2026-08-09"),             # d: fldid, dates differ
        _tour("FE", code="0805_다른"),                # e: fldid but the tour's code disagrees
        _tour("FX", code="0806_바"), _tour("FY", code="0806_바"),   # f: two tours claim the code
    ]
    registrations = {"a": "FA", "c": "FC", "d": "FD", "e": "FE", "g": "FA"}
    coverage = _coverage(tours, trips, registrations)
    assert coverage["fldid"] == ["a"] and coverage["code"] == ["b"] and coverage["both"] == ["c"]
    assert coverage["date_mismatch"] == ["d"]
    assert sorted(coverage["conflict"]) == ["e", "f"]
    assert coverage["unbridgeable"] == [] and "g" not in sum(coverage.values(), [])


def test_fldid_and_code_pointing_at_different_tours_is_a_conflict_not_a_bridge():
    trips = [_trip("a", "0801_가")]
    tours = [_tour("F1"), _tour("F2", code="0801_가")]
    coverage = _coverage(tours, trips, {"a": "F1"})
    assert coverage["conflict"] == ["a"] and coverage["both"] == []


def test_a_trip_without_any_stable_key_is_unbridgeable_even_if_dates_match():
    coverage = _coverage([_tour("F1")], [_trip("a", "0801_가")], {})
    assert coverage["unbridgeable"] == ["a"]


def test_reservation_eight_digit_codes_match_cost_keys_only_with_the_same_year():
    trips = [_trip("a", "0801_가", starts="2026-08-01"), _trip("b", "0802_나", starts="2026-08-02", ends="2026-08-06")]
    tours = [_tour("FA", code="20260801_가"),
             _tour("FB", code="20250802_나", depart="2026-08-02", ret="2026-08-06")]
    coverage = _coverage(tours, trips, {})
    assert coverage["code"] == ["a"]
    assert coverage["unbridgeable"] == ["b"]
    assert gar._code_matches("0801_가", trips[0]) is True
    assert gar._code_matches("20260801_다", trips[0]) is False
    assert gar._code_matches("", trips[0]) is False


def test_a_corrected_reservation_date_turns_a_date_mismatch_into_an_exact_bridge():
    trips = [_trip("t1115", "1115_호남", starts="2026-11-15", ends="2026-11-17")]
    registrations = {"t1115": "fOzD"}
    overwritten = _tour("fOzD", depart="2026-11-18", ret="2026-11-20")
    assert _coverage([overwritten], trips, registrations)["date_mismatch"] == ["t1115"]
    corrected = _tour("fOzD", depart="2026-11-15", ret="2026-11-17")
    coverage = _coverage([corrected], trips, registrations)
    assert coverage["fldid"] == ["t1115"] and coverage["date_mismatch"] == []


def test_a_similar_title_never_creates_a_bridge_when_no_stable_key_exists():
    trips = [_trip("t1", "0801_노리쿠라")]
    tours = [dict(_tour("F9"), title="8월1(토)~5/노리쿠라 트레킹")]
    coverage = _coverage(tours, trips, {})
    assert coverage["unbridgeable"] == ["t1"] and coverage["fldid"] == [] and coverage["code"] == []
