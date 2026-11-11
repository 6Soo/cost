from tools.p2_layer2.guard import guard_result, normalize_dates


def test_normalize_dates_accepts_iso_slash_and_korean_forms():
    assert normalize_dates("2026-07-05 / 2026.7.6 / 2026년 7월 7일") == {
        "2026-07-05", "2026-07-06", "2026-07-07"
    }


def test_period_is_cleared_when_cited_excerpt_has_no_dates():
    result = guard_result(
        {"trip_id": "trip-a", "service_start": "2026-07-05", "service_end": "2026-07-06",
         "confidence": "중간", "uncertainty": "", "evidence_refs": ["e1"]},
        {"e1": "예약 상품명과 금액만 표시됨"}, existing_trip="trip-a")
    assert result["service_start"] == result["service_end"] == ""
    assert "미확인" in result["uncertainty"]


def test_period_is_kept_when_both_dates_are_in_excerpt():
    result = guard_result(
        {"trip_id": "trip-a", "service_start": "2026-07-05", "service_end": "2026-07-06",
         "confidence": "중간", "uncertainty": "", "evidence_refs": ["e1"]},
        {"e1": "체크인 2026년 7월 5일, 체크아웃 2026-07-06"}, existing_trip="trip-a")
    assert result["service_start"] == "2026-07-05"
    assert result["service_end"] == "2026-07-06"


def test_no_evidence_forces_existing_trip_and_unknown_period():
    result = guard_result(
        {"trip_id": "trip-new", "service_start": "2026-07-05", "service_end": "2026-07-06",
         "confidence": "높음", "uncertainty": "", "evidence_refs": []}, {}, existing_trip="trip-old")
    assert result["trip_id"] == "trip-old"
    assert result["service_start"] == result["service_end"] == ""
    assert result["confidence"] == "낮음"
