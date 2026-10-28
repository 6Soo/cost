import pytest

from app.provisional_assignment import (ota_service_period_candidate, rank_trip_candidates,
                                        canonical_trip_periods, propose_correction_pattern,
                                        approve_correction_pattern)


TRIPS = [
    {"trip_id": "A", "starts_on": "2026-08-01", "ends_on": "2026-08-05"},
    {"trip_id": "B", "starts_on": "2026-08-01", "ends_on": "2026-08-05"},
]


def test_low_evidence_unique_authoritative_trip_is_provisional():
    result = rank_trip_candidates([{"trip_id": "A", "score": 1, "basis": "날짜 근접"}], trips=TRIPS)
    assert (result["status"], result["trip_id"], result["confidence"]) == ("AUTO_PROVISIONAL", "A", "낮음")


def test_equal_top_candidates_are_held_for_review():
    result = rank_trip_candidates([{"trip_id": "A", "score": 5}, {"trip_id": "B", "score": 5}], trips=TRIPS)
    assert result["status"] == "CONFLICT_REVIEW"
    assert result["trip_id"] == ""
    assert [candidate["trip_id"] for candidate in result["candidates"]] == ["A", "B"]


def test_manual_choice_and_financial_hold_are_protected():
    candidate = [{"trip_id": "A", "score": 99}]
    assert rank_trip_candidates(candidate, trips=TRIPS, manual_trip_id="B")["trip_id"] == "B"
    held = rank_trip_candidates(candidate, trips=TRIPS, financial_hold=True)
    assert held["status"] == "FINANCIAL_HOLD" and held["trip_id"] == ""
    assert held["candidates"][0]["trip_id"] == "A"


def test_non_authoritative_or_out_of_period_candidate_is_rejected():
    result = rank_trip_candidates([{"trip_id": "ghost", "score": 99}], trips=TRIPS)
    assert result["status"] == "UNASSIGNED_NO_VALID_TRIP"
    result = rank_trip_candidates([{"trip_id": "A", "score": 99,
                                    "service_period": {"starts_on": "2026-09-01", "ends_on": "2026-09-02"}}], trips=TRIPS)
    assert result["status"] == "UNASSIGNED_NO_VALID_TRIP"


def test_ota_service_period_beats_card_date_and_requires_authoritative_period():
    candidates = ota_service_period_candidate(
        {"service_period": {"starts_on": "2026-08-03", "ends_on": "2026-08-04"}}, TRIPS)
    assert {candidate["trip_id"] for candidate in candidates} == {"A", "B"}
    assert ota_service_period_candidate({"service_period": {"starts_on": "bad", "ends_on": "bad"}}, TRIPS) == []
    assert ota_service_period_candidate({"service_period": {"starts_on": "2026-08-03", "ends_on": "2026-08-04"},
                                          "service_period_conflict": True}, TRIPS) == []


def test_open_trip_ends_before_next_trip_and_duplicate_evidence_is_aggregated():
    trips = [{"trip_id": "open", "starts_on": "2026-08-01", "ends_on": None},
             {"trip_id": "next", "starts_on": "2026-08-05", "ends_on": "2026-08-09"}]
    periods = canonical_trip_periods(trips)
    assert periods["open"]["ends_on"] == "2026-08-04"
    result = rank_trip_candidates([
        {"trip_id": "open", "score": 3, "basis": "service"},
        {"trip_id": "open", "score": 3, "basis": "date"},
        {"trip_id": "next", "score": 3, "basis": "date"}], trips=trips)
    assert result["status"] == "CONFLICT_REVIEW"
    assert [c["trip_id"] for c in result["candidates"]] == ["next", "open"]
    assert "service" in next(c["basis"] for c in result["candidates"] if c["trip_id"] == "open")


def test_manual_unassigned_hold_and_exclude_are_protected():
    for state in ("MANUAL_UNASSIGNED", "MANUAL_HOLD", "MANUAL_EXCLUDED"):
        result = rank_trip_candidates([{"trip_id": "A", "score": 99}], trips=TRIPS,
                                      manual_status=state)
        assert result["status"] == state and result["trip_id"] == ""


def test_disabled_invalid_and_conflicted_trips_are_not_candidates():
    trips = [dict(TRIPS[0], enabled=False), dict(TRIPS[1], conflict=True)]
    assert rank_trip_candidates([{"trip_id": "A", "score": 1}, {"trip_id": "B", "score": 1}],
                                trips=trips)["status"] == "UNASSIGNED_NO_VALID_TRIP"


def test_correction_patterns_stay_inactive_until_owner_approves_exact_scope():
    rows = [dict(owner_approved=True, merchant_normalized="example inn", trip_id="A",
                 service_start="2026-08-01", service_end="2026-08-03") for _ in range(2)]
    proposal = propose_correction_pattern(rows)
    assert proposal["status"] == "PENDING_OWNER_APPROVAL" and proposal["active"] is False
    with pytest.raises(ValueError, match="OWNER_APPROVAL_REQUIRED"):
        approve_correction_pattern(proposal, approved_by="")
    approved = approve_correction_pattern(proposal, approved_by="synthetic-owner")
    assert approved["active"] is True
    assert approved["scope"] == proposal["scope"]
    assert propose_correction_pattern([rows[0]])["status"] == "NO_PROPOSAL"
