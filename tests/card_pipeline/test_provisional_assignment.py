from app.provisional_assignment import ota_service_period_candidate, rank_trip_candidates


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
