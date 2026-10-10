from app.bridge_diagnostics import classify_unbridgeable, hold_statistics


def tour(fldid, title, depart, ret, code=None):
    return {"fldid": fldid, "title": title, "depart_date": depart, "return_date": ret, "code": code}


def trip(key, start, end):
    return {"tab_id": key, "display_key": key, "starts_on": start, "ends_on": end}


def test_unbridgeable_trips_are_classified_without_creating_links():
    tours = [
        tour("A", "8월1(토)~5/노리쿠라 트레킹", "2026-08-01", "2026-08-05"),
        tour("B", "9월 첫째 주 여행 1", "2026-09-04", "2026-09-07"),
        tour("C", "9월 첫째 주 여행 2", "2026-09-04", "2026-09-07"),
        tour("D", "6월 북해도 후기", "2026-06-20", "2026-06-25"),
        tour("E", "9월23(수)~27 세토 트레킹", "2026-09-24", "2026-09-26"),
        tour("F", "10월 북해도 道東", "2026-10-05", "2026-10-09"),
    ]
    trips = [trip("0801_노리쿠라", "2026-08-01", "2026-08-05"), trip("0904_세토", "2026-09-04", "2026-09-07"),
             trip("0613_북해도", "2026-06-13", "2026-06-16"), trip("0404_에히메", "2026-04-04", "2026-04-07"),
             trip("0924_세토", "2026-09-24", "2026-09-27")]
    regions = {"0801_노리쿠라": "노리쿠라", "0904_세토": "세토", "0613_북해도": "북해도", "0404_에히메": "에히메",
               "0924_세토": "세토"}
    result = classify_unbridgeable(tours, trips, regions)
    assert result["MANUAL_CODE_NEEDED"] == ["0801_노리쿠라"]
    assert result["AMBIGUOUS"] == ["0904_세토"]
    assert result["DATE_CONFLICT"] == ["0924_세토"]
    assert result["SOURCE_MISSING"] == ["0613_북해도", "0404_에히메"]
    assert result["SOURCE_KEY_RECOVERABLE"] == []


def test_a_tour_that_already_carries_the_same_code_is_a_recoverable_key():
    tours = [tour("A", "x", "2026-08-02", "2026-08-05", code="20260801_노리쿠라")]
    result = classify_unbridgeable(tours, [trip("0801_노리쿠라", "2026-08-01", "2026-08-05")], {})
    assert result["SOURCE_KEY_RECOVERABLE"] == ["0801_노리쿠라"]


def test_hold_statistics_count_codes_only():
    rows = [{"guide_airfare": {"status": "HOLD", "code": "HOLD_GUIDE_IDENTITY_UNCONFIRMED"}},
            {"guide_airfare": {"status": "HOLD", "code": "HOLD_GUIDE_IDENTITY_UNCONFIRMED"}},
            {"guide_airfare": {"status": "ATTRIBUTED", "code": "guide_airfare_round_trip"}}, {}]
    assert hold_statistics(rows) == {"HOLD_GUIDE_IDENTITY_UNCONFIRMED": 2, "guide_airfare_round_trip": 1}


def test_a_code_with_another_year_is_not_a_recoverable_key():
    tours = [tour("A", "x", "2026-08-02", "2026-08-05", code="20250801_노리쿠라")]
    result = classify_unbridgeable(tours, [trip("0801_노리쿠라", "2026-08-01", "2026-08-05")], {})
    assert result["SOURCE_KEY_RECOVERABLE"] == []
