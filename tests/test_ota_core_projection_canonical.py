import ast
import copy

from app import ota_payments
from app.classify import PERIOD_OTA_ORIGIN
from app.ota_core_projection import project_canonical_candidate_period_assignments
from app.reconciliation import stay_trip
from tests.fixtures.base_canonical_candidate_period_assignments_f86690b import BASE_METHOD_SOURCE
import webapp.card_flow as card_flow


def _base_method():
    tree = ast.parse(BASE_METHOD_SOURCE)
    method = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
    namespace = {"stay_trip": stay_trip, "_google_nets": card_flow._google_nets}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<frozen-base>", "exec"), namespace)
    return namespace[method.name]


def test_frozen_base_wrapper_matches_refactored_wrapper():
    trip = {"tab_id": "trip-a", "starts_on": "2026-07-01", "ends_on": "2026-08-31"}
    snap = {"data": {
        "events": [{"ota_event_id": "e1", "event_type": "charge", "evidence_status": "paid_verified",
                    "payment_status": "paid", "provider": "agoda", "item": "lodging",
                    "reservation_status": "confirmed", "group_count": 0,
                    "service_period": {"starts_on": "2026-07-10", "ends_on": "2026-07-12"}}],
        "transactions": [{"transaction_id": "c1", "source_hash": "source-a", "merchant": "AGODA",
                          "merchant_normalized": "agoda", "ota_inference_eligible": True,
                          "transaction_direction": "purchase", "duplicate_of": "", "parse_error": "",
                          "conflict_reason": ""}],
        "results": [{"ota_event_id": "e1", "status": "HOLD_DATE_UNKNOWN", "evidence_missing": False,
                     "evidence_changed": False, "group_count": 0, "candidate_search": {
                         "status": "CANDIDATES_FOUND", "candidates": [
                             {"transaction_id": "c1", "resolution_allowed": False}]}}],
        "links": {}}}
    before = copy.deepcopy(snap)

    class Board:
        def list_trips(self): return [trip]

    class Flow:
        board = Board()
        def _held_ota_snapshot(self): return snap, True
        def trip_valid(self, trip_id): return trip_id == "trip-a"

    calls = []
    original_nets = card_flow._google_nets
    card_flow._google_nets = lambda: calls.append("nets") or {"trip-a": 10}
    try:
        old = _base_method()(Flow(), {"source-a"}, set(), None, set())
        old_calls = list(calls)
        calls.clear()
        new = card_flow.CardFlow._canonical_candidate_period_assignments(Flow(), {"source-a"}, set(), None, set())
        new_calls = list(calls)
    finally:
        card_flow._google_nets = original_nets

    assert old == new
    assert old_calls == new_calls
    assert snap == before
    assert old and old[0]["origin"] == PERIOD_OTA_ORIGIN
    assert callable(ota_payments._event_is_paid) and callable(stay_trip)
    choices = [("source-a", "trip-a", "lodging", "2026-07-10", "2026-07-12")]
    assert project_canonical_candidate_period_assignments(
        cards={"c1": snap["data"]["transactions"][0]}, choices=choices) == old
