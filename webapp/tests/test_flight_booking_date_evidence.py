"""Strict source-labeled booking dates: synthetic data only, no operational records."""
from app import flight_evidence as evidence
from webapp import flight_passenger_page as page
from unittest.mock import patch


def _part(day, digest, status="EXPLICIT_LABEL"):
    return {
        "booking_ref": "SYNTH-100", "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
        "legs": [], "source_digest": digest, "cancellation_status": "NONE",
        "reserved_on": day, "booking_date_status": status,
    }


def test_accepts_only_explicit_booking_created_date_with_valid_calendar():
    text = "예약번호: 123456789\n예약일: 2026-10-02\n출발일: 2026-10-27"
    got = evidence.parse_flight_text(text)
    assert got["reserved_on"] == "2026-10-02"
    assert got["booking_date_status"] == "EXPLICIT_LABEL"
    assert evidence._explicit_booking_date(["Booking created at: 2026/10/02"]) == (
        "2026-10-02", "EXPLICIT_LABEL")
    assert evidence._explicit_booking_date(["예약일: 2026-02-31"]) == ("", "UNKNOWN")


def test_never_infers_booking_date_from_mail_flight_issued_or_payment_dates():
    lines = [
        "Subject: 예약 완료 안내",
        "Date: 2026-10-01", "메일 수신일: 2026-10-01",
        "발권일: 2026-10-02", "결제일: 2026-10-03",
        "출발일: 2026-10-04", "2026-10-05",
    ]
    assert evidence._explicit_booking_date(lines) == ("", "UNKNOWN")
    assert evidence._explicit_booking_date([
        "예약일: 확인해 주세요", "예약일을 확인하세요"]) == ("", "UNKNOWN")


def test_conflicting_dates_fail_closed_and_digest_changes_when_date_changes():
    a = evidence.merge_booking_evidence([_part("2026-10-02", "one")])
    b = evidence.merge_booking_evidence([_part("2026-10-03", "one")])
    assert a["booking_date_status"] == "EXPLICIT_LABEL"
    assert a["reserved_on"] == "2026-10-02"
    assert a["digest"] != b["digest"]
    conflicting = evidence.merge_booking_evidence([
        _part("2026-10-02", "one"), _part("2026-10-03", "two")])
    assert conflicting["booking_date_status"] == "CONFLICT"
    assert conflicting["reserved_on"] == ""
    ambiguous = evidence.merge_booking_evidence([
        _part("2026-10-02", "one"), _part("", "two", "CONFLICT")])
    assert ambiguous["booking_date_status"] == "CONFLICT"
    assert ambiguous["reserved_on"] == ""


def test_name_search_exposes_verified_date_only_and_preserves_manual_fallback():
    index = {
        "SYNTH-100": {
            "source_digests": ["source-1"], "digest": "digest-1",
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
            "legs": [], "booking_date_status": "EXPLICIT_LABEL",
            "reserved_on": "2026-10-02",
            "cancellation_status": "NONE",
        },
        "SYNTH-200": {
            "source_digests": ["source-2"], "digest": "digest-2",
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
            "legs": [], "booking_date_status": "CONFLICT",
            "reserved_on": "2026-10-03",
            "cancellation_status": "NONE",
        },
    }
    with patch("webapp.ota_payment_review.passenger_index_for", return_value=index), patch(
        "webapp.flight_passenger_page._confirmed_card_index", return_value={}):
        res = page._name_search(object(), "KIM ALPHA")
    assert res["total"] == 2
    matched = {row["booking_ref"]: row for row in res["reservations"]}
    assert matched["SYNTH-100"]["reserved_on"] == "2026-10-02"
    assert matched["SYNTH-200"]["reserved_on"] == ""
    html = page._page("synthetic-csrf")
    assert "b.booking_date_status==='EXPLICIT_LABEL'" in html
    assert "USER_DATE_FILTER" in html
    assert "confirmedDay" in html
    assert "원본 명시 확인" in html
