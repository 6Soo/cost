import ast
import copy

from app.classify import PERIOD_OTA_ORIGIN
from app.reconciliation import stay_trip
from tests.fixtures.base_canonical_candidate_period_assignments_f86690b import BASE_METHOD_SOURCE
import webapp.card_flow as card_flow


def _base_method():
    method = next(node for node in ast.parse(BASE_METHOD_SOURCE).body
                  if isinstance(node, ast.FunctionDef))
    namespace = {"stay_trip": stay_trip, "_google_nets": card_flow._google_nets}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<frozen-base>", "exec"), namespace)
    return namespace[method.name]


def test_frozen_base_wrapper_matches_refactored_wrapper():
    trip_a = {"tab_id": "trip-a", "starts_on": "2026-07-01", "ends_on": "2026-08-31"}
    trip_b = {"tab_id": "trip-b", "starts_on": "2026-08-01", "ends_on": "2026-09-30"}

    def event(eid="e1", **updates):
        value = {"ota_event_id": eid, "event_type": "charge", "evidence_status": "paid_verified",
                 "payment_status": "paid", "provider": "agoda", "item": "숙박비",
                 "reservation_status": "confirmed", "group_count": 0,
                 "service_period": {"starts_on": "2026-07-10", "ends_on": "2026-07-12"}}
        value.update(updates)
        return value

    def card(cid="c1", source="source-a", **updates):
        value = {"transaction_id": cid, "source_hash": source, "merchant": "AGODA",
                 "merchant_normalized": "agoda", "ota_inference_eligible": True,
                 "transaction_direction": "purchase", "duplicate_of": "", "parse_error": "",
                 "conflict_reason": ""}
        value.update(updates)
        return value

    def result(eid="e1", cid="c1", status="HOLD_DATE_UNKNOWN", **updates):
        value = {"ota_event_id": eid, "status": status, "evidence_missing": False,
                 "evidence_changed": False, "group_count": 0,
                 "candidate_search": {"status": "CANDIDATES_FOUND", "candidates": [
                     {"transaction_id": cid, "resolution_allowed": False}]}}
        value.update(updates)
        return value

    def snapshot(events=None, cards=None, results=None, links=None):
        return {"data": {"events": events or [event()], "transactions": cards or [card()],
                          "results": results or [result()], "links": links or {}}}

    cases = [
        ("paid_lodging", snapshot(), [trip_a], {"source-a"}, set(), None, set(), {"trip-a": 9}, True),
        ("toyoko_reservation", snapshot([event(event_type="reservation", evidence_status="reservation_only",
                payment_status="unknown", provider="toyoko")], results=[result(status="RESERVATION_ONLY")]),
         [trip_a], {"source-a"}, set(), None, set(), {"trip-a": 9}, True),
        ("empty", {"data": {}}, [trip_a], {"source-a"}, set(), None, set(), {}, False),
        ("stale", snapshot(), [trip_a], {"source-a"}, set(), None, set(), {}, False, False),
        ("taken", snapshot(), [trip_a], {"source-a"}, {"source-a"}, None, set(), {}, False),
        ("selected_out", snapshot(), [trip_a], {"source-a"}, set(), {"other"}, set(), {}, False),
        ("blocked", snapshot(), [trip_a], {"source-a"}, set(), None, {"source-a"}, {}, False),
        ("reserved_result", snapshot(results=[result(reserved_card_ids=["c1"])]), [trip_a],
         {"source-a"}, set(), None, set(), {}, False),
        ("reserved_link", snapshot(links={"e1": {"transaction_id": "c1"}}), [trip_a],
         {"source-a"}, set(), None, set(), {}, False),
        ("duplicate", snapshot(cards=[card(duplicate_of="other")]), [trip_a],
         {"source-a"}, set(), None, set(), {}, False),
        ("parse_error", snapshot(cards=[card(parse_error="bad")]), [trip_a],
         {"source-a"}, set(), None, set(), {}, False),
        ("cancelled", snapshot([event(reservation_status="cancelled")]), [trip_a],
         {"source-a"}, set(), None, set(), {}, False),
        ("evidence_changed", snapshot(results=[result(evidence_changed=True)]), [trip_a],
         {"source-a"}, set(), None, set(), {}, False),
        ("group", snapshot(results=[result(group_count=2)]), [trip_a],
         {"source-a"}, set(), None, set(), {}, False),
        ("resolution_allowed", snapshot(results=[result(candidate_search={"status": "CANDIDATES_FOUND",
                 "candidates": [{"transaction_id": "c1", "resolution_allowed": True}]})]),
         [trip_a], {"source-a"}, set(), None, set(), {}, False),
        ("conflicting_periods", snapshot(events=[event(), event("e2", service_period={
                 "starts_on": "2026-08-10", "ends_on": "2026-08-12"})],
                 results=[result(), result("e2")]), [trip_a, trip_b], {"source-a"}, set(), None,
         set(), {"trip-a": 9, "trip-b": 8}, False),
        ("last_trip_validation", snapshot(), [trip_a], {"source-a"}, set(), None, set(),
         {"trip-a": 9}, False, False, True),
    ]

    calls = []
    original_nets = card_flow._google_nets
    card_flow._google_nets = lambda: calls.append("nets") or {"trip-a": 9, "trip-b": 8}
    try:
        for case in cases:
            name, snap, trips, sources, taken, selected, blocked, _nets, expected = case[:9]
            stale = len(case) > 9 and case[9] is False
            invalidate_last = len(case) > 10 and case[10] is True
            before = copy.deepcopy(snap)

            class Board:
                def list_trips(self): return trips

            class Flow:
                board = Board()
                def _held_ota_snapshot(self): return snap, not stale
                def trip_valid(self, trip_id): return not (invalidate_last and trip_id == "trip-a")

            old_calls = []
            calls.clear()
            old = _base_method()(Flow(), sources, taken, selected, blocked)
            old_calls = list(calls)
            calls.clear()
            new = card_flow.CardFlow._canonical_candidate_period_assignments(
                Flow(), sources, taken, selected, blocked)
            new_calls = list(calls)

            assert old == new, name
            assert old_calls == new_calls, name
            assert snap == before, name
            assert bool(old) is expected, name
            if name == "paid_lodging":
                assert old[0]["effects"]["item"] == "숙박비"
                assert old[0]["origin"] == PERIOD_OTA_ORIGIN
            if name == "last_trip_validation":
                assert old == []
    finally:
        card_flow._google_nets = original_nets
