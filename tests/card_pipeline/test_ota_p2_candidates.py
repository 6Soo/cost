"""P2 entry adapter selects the OTA events the router marks for review.

Synthetic fixtures mirror `tests/card_pipeline/test_ota_p2_routing.py`; no live
database, customer data, model call or write.
"""
import pytest

from app import ota_p2_candidates as candidates
from app import ota_p2_routing as routing
from tests.card_pipeline.test_ota_payments import event


def _result(identity, status, **changes):
    value = {"ota_event_id": identity, "status": status, "transaction_id": None}
    value.update(changes)
    return value


def _record(**changes):
    record = {"outcome": "no_relation",
              "candidate_outcomes": ["MATCH:0"],
              "sources": ["mail"],
              "policy_version": "DECISION_POLICY-2026-11-18",
              "explicit_conflicts": ["amount"],
              "candidate_ranking": ["card-y:1"]}
    record.update(changes)
    return record


# --- the target set is exactly INVESTIGATION_REQUIRED + INFERENCE_ONLY ------

@pytest.mark.parametrize("status", ["HOLD_NO_CARD", "HOLD_AMOUNT_MISMATCH",
                                    "HOLD_AMOUNT_UNVERIFIED", "HOLD_DATE_UNKNOWN",
                                    "HOLD_EVIDENCE_CONFLICT", "HOLD_GROUP_CHANGED",
                                    "HOLD_PARTIAL_GROUP", "HOLD_AMBIGUOUS"])
def test_unmatched_verified_charge_is_a_review_target(status):
    report = candidates.investigation_targets([event()], [_result("event-a", status)])
    assert report["targets"] == ["event-a"]
    assert report["target_count"] == 1
    assert report["creates_relation"] is False and report["run_mode"] == "READ_ONLY"


def test_verified_exact_relation_is_not_a_target():
    # A manual/confirmed link is EXACT in the router, so it must not be re-opened.
    report = candidates.investigation_targets(
        [event()], [_result("event-a", "MATCHED_AUTO", transaction_id="card-a")])
    assert report["targets"] == []
    assert report["obligations"] == {routing.EXACT_RELATION: 1}


def test_inferred_link_is_a_target():
    report = candidates.investigation_targets(
        [event()], [_result("event-a", "MATCHED_AUTO", transaction_id="card-a",
                            inferred_link=True)])
    assert report["targets"] == ["event-a"]
    assert report["obligations"] == {routing.INFERRED_RELATION: 1}


@pytest.mark.parametrize("status", ["RESERVATION_ONLY", "NOT_CARD_CHARGE", "PENDING_PAYMENT"])
def test_out_of_scope_events_are_not_targets(status):
    booking = event(provider="booking", evidence_status="reservation_only",
                    payment_status="not_card_charge", event_type="charge")
    report = candidates.investigation_targets([booking], [_result("event-a", status)])
    assert report["targets"] == []
    assert report["obligations"] == {routing.OUT_OF_SCOPE: 1}


def test_unavailable_engine_result_is_not_a_target():
    report = candidates.investigation_targets([event()], [{"ota_event_id": "event-a",
                                                           "status": "NO_RESULT"}])
    assert report["targets"] == []
    assert report["obligations"] == {routing.RESULT_UNAVAILABLE: 1}


# --- aggregate: only review-required events, exact ones preserved -----------

def test_mixed_pass_selects_only_review_required_events():
    events = [event("event-a"), event("event-b", provider="trip")]
    results = [
        _result("event-a", "HOLD_NO_CARD"),
        _result("event-b", "MATCHED_AUTO", transaction_id="card-b"),
    ]
    report = candidates.investigation_targets(events, results)
    assert report["targets"] == ["event-a"]
    assert report["obligations"] == {
        routing.EXACT_RELATION: 1,
        routing.INVESTIGATION_REQUIRED: 1,
    }


# --- boundary: no relation id leaves, inputs untouched, p2/search preserved --

def test_targets_carry_no_relation_identifier():
    report = candidates.investigation_targets([event()], [_result("event-a", "HOLD_NO_CARD")])
    # Only the local event ref is returned; the card/booking identity never leaks.
    assert report["targets"] == ["event-a"]
    assert "transaction_id" not in report and "booking_ref" not in report
    assert "card-a" not in str(report) and "BOOK12345" not in str(report)


def test_inputs_are_not_mutated():
    events = [event()]
    results = [_result("event-a", "HOLD_NO_CARD")]
    before = (dict(events[0]), dict(results[0]))
    candidates.investigation_targets(events, results)
    assert before == (events[0], results[0])


def test_p2_record_and_search_reasons_are_preserved_in_counts():
    report = candidates.investigation_targets(
        [event()], [_result("event-a", "HOLD_NO_CARD")],
        p2_records={"event-a": _record()},
        searches={"event-a": {"status": "CANDIDATES_FOUND", "candidates": [],
                              "rejected": []}})
    assert report["targets"] == ["event-a"]
    # The router still owns per-event detail; the adapter only surfaces targets.
    assert report["obligations"] == {routing.INVESTIGATION_REQUIRED: 1}
