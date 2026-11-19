"""Synthetic checks for the OTA -> P2 routing of DECISION_POLICY §3.0.

No live database, no customer data, no model call. Fixtures mirror
`tests/card_pipeline/test_ota_payments.py`.
"""
import pytest

from app import ota_p2_routing as routing
from tests.card_pipeline.test_ota_payments import card, event


def _search(*, accepted=(), rejected=(), status="CANDIDATES_FOUND"):
    return {"status": status,
            "candidates": [dict(transaction_id="card-x", date_status=date_status,
                                resolution_allowed=allowed)
                           for date_status, allowed in accepted],
            "rejected": [{"transaction_id": "card-y", "reason": reason} for reason in rejected]}


def _record(**changes):
    record = {"outcome": "no_relation",
              "candidate_outcomes": ["MATCH:0", "MISMATCH:1", "UNKNOWN:1"],
              "sources": ["payment_mail", "card_scope:2026-04-01..now"],
              "policy_version": "DECISION_POLICY-2026-11-18",
              "explicit_conflicts": ["amount"],
              "candidate_ranking": ["card-y:1"]}
    record.update(changes)
    return record


def _hold(status="HOLD_NO_CARD", **changes):
    return dict(ota_event_id="event-a", status=status, transaction_id=None,
                candidates=[], **changes)


# --- §3.0: a verified charge with no P1 card relation is always P2's target ---

@pytest.mark.parametrize("status", ["HOLD_NO_CARD", "HOLD_AMOUNT_MISMATCH",
                                    "HOLD_AMOUNT_UNVERIFIED", "HOLD_DATE_UNKNOWN",
                                    "HOLD_EVIDENCE_CONFLICT", "HOLD_GROUP_CHANGED",
                                    "HOLD_PARTIAL_GROUP", "HOLD_AMBIGUOUS"])
def test_every_unmatched_verified_charge_is_a_mandatory_review(status):
    record = routing.route(event(), _hold(status))
    assert record["obligation"] == routing.INVESTIGATION_REQUIRED
    assert record["reason_codes"] == [status]
    # With no P2 record the roster says not started, never "reviewed".
    assert record["investigation"] == "P2_NOT_STARTED"


def test_completed_item_classification_does_not_excuse_the_ota_review():
    # The event row itself carries no item/trip; completion of the *card* row
    # cannot be an input here because routing reads events and results only.
    record = routing.route(event(), _hold())
    assert record["obligation"] == routing.INVESTIGATION_REQUIRED
    assert "event-a" == record["event_ref"]


# --- verified relations stay P1; routing never re-checks them -------------

@pytest.mark.parametrize("status", ["MATCHED_AUTO", "MATCHED_USER", "MATCHED_GROUP"])
def test_verified_relation_is_preserved_and_not_reopened(status):
    record = routing.route(event(), {"status": status, "transaction_id": "card-a"})
    assert record["obligation"] == routing.EXACT_RELATION
    assert record["investigation"] is None and record["reason_codes"] == []


def test_matched_status_without_a_card_row_is_unavailable_not_a_relation():
    record = routing.route(event(), {"status": "MATCHED_AUTO", "transaction_id": None})
    assert record["obligation"] == routing.RESULT_UNAVAILABLE
    assert record["reason_codes"] == ["MATCHED_WITHOUT_TRANSACTION_ID"]


def test_inferred_link_is_not_a_verified_relation():
    record = routing.route(event(), {"status": "MATCHED_AUTO", "transaction_id": "card-a",
                                    "inferred_link": True,
                                    "payment_date_verified": False})
    assert record["obligation"] == routing.INFERRED_RELATION
    assert record["payment_date_verified"] is False
    assert "INFERRED_LINK_NOT_VERIFIED" in record["reason_codes"]


# --- §3.0 message item 1: no relation is demanded for events with no charge --

@pytest.mark.parametrize("status", ["RESERVATION_ONLY", "NOT_CARD_CHARGE", "PENDING_PAYMENT"])
@pytest.mark.parametrize("evidence", ["reservation_only", "unverified", "scheduled"])
def test_events_without_a_verified_charge_are_out_of_scope(status, evidence):
    charged = event(evidence_status=evidence, payment_status="unverified",
                    event_type="scheduled_charge")
    record = routing.route(charged, {"status": status, "transaction_id": None})
    assert record["obligation"] == routing.OUT_OF_SCOPE


def test_reservation_only_booking_event_carries_no_card_relation():
    booking = event(provider="booking", evidence_status="reservation_only",
                    payment_status="not_card_charge", event_type="charge")
    record = routing.route(booking, {"status": "RESERVATION_ONLY", "transaction_id": None})
    assert record["obligation"] == routing.OUT_OF_SCOPE


def test_absent_or_unknown_engine_result_is_never_a_review_completion():
    for result in (None, {"status": "NO_RESULT"}, {"status": "UNKNOWN"},
                   {"status": "SOMETHING_NEW"}):
        record = routing.route(event(), result)
        assert record["obligation"] == routing.RESULT_UNAVAILABLE
        assert record["investigation"] is None


# --- LINK-044: candidate signals, alias gaps and M:N -----------------------

@pytest.mark.parametrize("entry,signal", [
    ({"date_status": "MATCH", "resolution_allowed": True}, "MATCH"),
    ({"date_status": "UNKNOWN", "resolution_allowed": True}, "MATCH"),
    ({"date_status": "UNKNOWN", "resolution_allowed": False}, "UNKNOWN"),
    ({"date_status": "MISMATCH", "resolution_allowed": False}, "MISMATCH"),
    ({"reason": "AMOUNT_MISMATCH"}, "MISMATCH"),
    ({"reason": "CURRENCY_MISMATCH"}, "MISMATCH"),
    ({"reason": "CARD_IDENTITY_MISMATCH"}, "MISMATCH"),
    # Unregistered alias and financial protection are not counterparty conflicts.
    ({"reason": "PROVIDER_ALIAS_MISSING"}, "UNKNOWN"),
    ({"reason": "CARD_FINANCIAL_HOLD"}, "UNKNOWN"),
    ({"reason": "AMOUNT_EVIDENCE_REQUIRED"}, "UNKNOWN"),
    ({"reason": "FX_EVIDENCE_REQUIRED"}, "UNKNOWN"),
    ({}, "UNKNOWN"),
])
def test_candidate_signals_never_promote_or_overstate_a_conflict(entry, signal):
    assert routing.candidate_signal(entry) == signal


def test_several_accepted_edges_are_m_n_evidence_not_a_failure():
    summary = routing.candidate_summary(_search(accepted=[("MATCH", True),
                                                         ("UNKNOWN", True)]))
    assert summary["state"] == "CANDIDATES_FOUND"
    assert summary["counts"] == {"MATCH": 2}
    assert summary["candidate_count"] == 2
    assert summary["m_n_preserved"] is True


def test_zero_candidates_is_reported_with_its_search_limit():
    summary = routing.candidate_summary(_search(status="SEARCH_LIMIT_EXCEEDED"))
    assert summary["state"] == "SEARCH_LIMIT_EXCEEDED"
    assert summary["counts"] == {} and summary["truncated"] is True
    assert summary["m_n_preserved"] is False


def test_a_search_that_never_ran_is_not_zero_candidates():
    assert routing.candidate_summary(None)["state"] == "SEARCH_NOT_RUN"


def test_review_record_with_candidates_keeps_each_outcome_separate():
    record = routing.route(event(), _hold(),
                           search=_search(accepted=[("MATCH", True)],
                                          rejected=["AMOUNT_MISMATCH",
                                                    "PROVIDER_ALIAS_MISSING"]))
    evidence = record["candidate_evidence"]
    assert evidence["counts"] == {"MATCH": 1, "MISMATCH": 1, "UNKNOWN": 1}
    assert "M_N_EDGES_PRESERVED" not in record["reason_codes"]


def test_route_marks_truncated_and_m_n_search_results():
    truncated = routing.route(event(), _hold(),
                              search=_search(status="SEARCH_LIMIT_EXCEEDED"))
    assert truncated["reason_codes"] == ["HOLD_NO_CARD", "CANDIDATE_SEARCH_TRUNCATED"]
    assert truncated["candidate_evidence"]["truncated"] is True

    multi = routing.route(event(), _hold(),
                          search=_search(accepted=[("MATCH", True), ("MATCH", True)]))
    assert multi["reason_codes"] == ["HOLD_NO_CARD", "M_N_EDGES_PRESERVED"]
    assert multi["candidate_evidence"]["candidate_count"] == 2


def test_no_search_evidence_leaves_route_reasons_without_candidate_codes():
    record = routing.route(event(), _hold())
    assert "candidate_evidence" not in record
    assert "CANDIDATE_SEARCH_TRUNCATED" not in record["reason_codes"]
    assert "M_N_EDGES_PRESERVED" not in record["reason_codes"]


# --- PROC-010: finished-with-no-relation vs did-not-run --------------------

def test_actual_review_completion_is_recorded_only_with_link_044_detail():
    for outcome in routing.ACCEPTED_OUTCOMES:
        state, findings = routing.investigation_state(_record(outcome=outcome))
        assert state == "P2_COMPLETED_UNVERIFIED" and findings == ()


@pytest.mark.parametrize("name", routing.REQUIRED_DETAIL)
def test_a_review_record_missing_any_required_detail_is_incomplete(name):
    record = _record()
    del record[name]
    state, findings = routing.investigation_state(record)
    assert state == "P2_RUN_INVALID"
    assert findings == ("MISSING_" + name.upper(),)


@pytest.mark.parametrize("record,expected", [
    ({"outcome": "failed", "candidate_outcomes": [], "sources": [], "policy_version": "x",
     "explicit_conflicts": [], "candidate_ranking": []}, "P2_RUN_FAILED"),
    ({"outcome": "no_relation", "error": "RETRIEVAL_PERMISSION_DENIED"}, "P2_RUN_FAILED"),
    ({"outcome": "no_relation"}, "P2_RUN_INVALID"),
    ({"outcome": "something_else", "candidate_outcomes": [], "sources": [],
     "policy_version": "x", "explicit_conflicts": [], "candidate_ranking": []}, "P2_RUN_INVALID"),
])
def test_failed_or_thin_records_are_not_a_completed_review(record, expected):
    state, _ = routing.investigation_state(record)
    assert state == expected
    assert state != "P2_COMPLETED_UNVERIFIED"


def test_p2_may_not_report_a_verified_relation():
    state, findings = routing.investigation_state(_record(outcome="relation_verified"))
    assert state == "P2_RUN_INVALID"
    assert findings == ("P2_CANNOT_VERIFY_RELATION",)


def test_completed_review_keeps_the_relation_unverified():
    record = routing.route(event(), _hold(), p2_record=_record())
    assert record["obligation"] == routing.INVESTIGATION_REQUIRED
    assert record["investigation"] == "P2_COMPLETED_UNVERIFIED"
    assert record["detail_findings"] == ()
    # Nothing in the route claims a link, a booking reference or a payment.
    assert "transaction_id" not in record and "booking_ref" not in record


# --- aggregate pass --------------------------------------------------------

def test_plan_aggregates_without_mutating_inputs_or_creating_relations():
    events = [event("event-a"), event("event-b", provider="trip"),
              event("event-c", provider="booking", evidence_status="reservation_only",
                    payment_status="not_card_charge")]
    results = [{"ota_event_id": "event-a", "status": "HOLD_NO_CARD", "transaction_id": None},
               {"ota_event_id": "event-b", "status": "MATCHED_AUTO", "transaction_id": "card-b"},
               {"ota_event_id": "event-c", "status": "RESERVATION_ONLY", "transaction_id": None}]
    before = ([dict(item) for item in events], [dict(item) for item in results])
    report = routing.plan(events, results, p2_records={"event-a": _record()})
    assert before == (events, results)
    assert report["obligations"] == {"CARD_RELATION_EXACT": 1,
                                     "CARD_RELATION_INVESTIGATION_REQUIRED": 1,
                                     "OUT_OF_CARD_RELATION_SCOPE": 1}
    assert report["investigation_states"] == {"P2_COMPLETED_UNVERIFIED": 1}
    assert report["engine_result_count"] == 3
    assert report["creates_relation"] is False and report["run_mode"] == "READ_ONLY"
    assert len(report["routes"]) == 3


def test_duplicate_result_rows_leave_the_event_unavailable():
    results = [{"ota_event_id": "event-a", "status": "HOLD_NO_CARD", "transaction_id": None},
               {"ota_event_id": "event-a", "status": "MATCHED_AUTO", "transaction_id": "card-a"}]
    report = routing.plan([event()], results)
    assert report["obligations"] == {"ENGINE_RESULT_UNAVAILABLE": 1}
    assert report["engine_result_count"] == 0


def test_plan_reports_counts_only_for_unknown_provider_text():
    # An arbitrary provider string cannot leak through: it is echoed locally but
    # never counted as a new vocabulary value in the summary.
    weird = event(provider="Customer Name Ltd")
    report = routing.plan([weird], [{"ota_event_id": "event-a", "status": "HOLD_NO_CARD"}])
    assert set(report["obligations"]) == {"CARD_RELATION_INVESTIGATION_REQUIRED"}
    assert weird["provider"] not in str(report["obligations"])
