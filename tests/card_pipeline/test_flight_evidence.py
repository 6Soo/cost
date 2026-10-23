"""Trip.com 항공 메일 근거 추출: 승객·여정 파싱, 병합, 인증 메일 수집과 메모."""
from unittest.mock import patch

from app import flight_evidence
from app.flight_evidence import collect_flight_evidence, merge_booking_evidence, parse_flight_text

ZW = "‌"
REF = "1" + ZW + "400" + ZW + "826" + ZW + "934" + ZW + "962" + ZW + "683"
OUTBOUND = ["가는편: 서울 - 삿포로", "2026년 6월 16일", "* 모든 출발·도착시간은 현지시간 기준입니다.",
            "07:10", "ICN 인천국제공항", "T1", "제주항공", "7C1501", "일반석", "10:00", "CTS 신치토세 공항", "I"]
RETURN = ["오는편: 삿포로 - 서울", "2026년 6월 21일", "14:30", "CTS 신치토세 공항", "I", "티웨이항공", "TW264",
          "일반석", "17:40", "ICN 인천국제공항", "T1"]
OUTBOUND_SEGMENT = {"departure_time": "07:10", "departure_airport": "ICN",
                    "arrival_time": "10:00", "arrival_airport": "CTS", "flight_number": "7C1501"}
RETURN_SEGMENT = {"departure_time": "14:30", "departure_airport": "CTS",
                  "arrival_time": "17:40", "arrival_airport": "ICN", "flight_number": "TW264"}


def _passenger_lines(people):
    lines = ["규정 조회 및 취소·변경 요청"]
    for surname, given in people:
        lines += [surname, "(성)", given, "(이름)", "성인 항공권", "이름 수정"]
    return lines


def _confirmation(legs=(OUTBOUND, RETURN), people=(("KIM", "ALPHA"),), ref=REF, booker="LEE BETA 고객님 안녕하세요,"):
    lines = ["예약번호", ref, booker]
    for leg in legs:
        lines += leg
    return "\n\n".join(lines + _passenger_lines(people))


def test_round_trip_one_passenger_with_segments():
    result = parse_flight_text(_confirmation())
    assert result["booking_ref"] == "1400826934962683"
    assert result["passengers"] == [{"surname": "KIM", "given_name": "ALPHA"}]
    assert result["legs"] == [
        {"label": "가는편", "origin_city": "서울", "destination_city": "삿포로",
         "departure_on": "2026-06-16", "segments": [OUTBOUND_SEGMENT]},
        {"label": "오는편", "origin_city": "삿포로", "destination_city": "서울",
         "departure_on": "2026-06-21", "segments": [RETURN_SEGMENT]},
    ]
    assert result["legs_complete"] is True


def test_explicit_cancellation_subject_is_preserved_but_policy_text_is_not_cancellation():
    cancelled = parse_flight_text("Subject: Booking cancellation confirmed\n예약번호\n1400826934962683\n" +
                                  _confirmation(people=(("KIM", "ALPHA"),)))
    policy = parse_flight_text("예약 취소 규정 조회 안내\n" + _confirmation(people=(("KIM", "ALPHA"),)))
    assert cancelled["cancellation_status"] == "CANCELLED"
    assert policy["cancellation_status"] == "NONE"


def test_cancellation_only_notice_needs_booking_reference_and_policy_phrases_are_not_cancellation():
    notice = parse_flight_text("Subject: Booking cancellation confirmed\n" + _confirmation(people=(), legs=()))
    assert notice["booking_ref"] == "1400826934962683"
    assert notice["cancellation_status"] == "CANCELLED"
    assert parse_flight_text("Subject: Booking cancellation confirmed") is None
    policy_body = parse_flight_text(_confirmation().replace("?? ?? ? ????? ??", "?? ?? ? ???? ????"))
    policy_subject = parse_flight_text("Subject: ?? ?? ??\n" + _confirmation())
    assert policy_body["cancellation_status"] == "NONE"
    assert policy_subject["cancellation_status"] == "NONE"
    conditional_policy = parse_flight_text(_confirmation().replace(
        "규정 조회 및 취소·변경 요청", "예약 취소가 완료되면 이메일로 안내합니다"))
    assert conditional_policy["cancellation_status"] == "NONE"
    assert parse_flight_text("예약 취소가 완료되었습니다") is None


def test_two_passengers_keep_inner_space_and_hangul_names():
    result = parse_flight_text(_confirmation(people=(("KIM", "MYUNG SUK"), ("김", "철수"))))
    assert result["passengers"] == [{"surname": "KIM", "given_name": "MYUNG SUK"},
                                    {"surname": "김", "given_name": "철수"}]


def test_zero_width_and_repeated_spaces_are_normalized():
    text = _confirmation(people=(("KI​M", "AL⁠PHA"), ("LEE", "MYUNG   SUK‪")))
    result = parse_flight_text(text)
    assert result["booking_ref"] == "1400826934962683"
    assert result["passengers"] == [{"surname": "KIM", "given_name": "ALPHA"},
                                    {"surname": "LEE", "given_name": "MYUNG SUK"}]


def test_booker_greeting_is_not_a_passenger():
    result = parse_flight_text(_confirmation(people=(("KIM", "ALPHA"),)))
    assert all(person["surname"] != "LEE" for person in result["passengers"])
    assert len(result["passengers"]) == 1


def test_no_passenger_triples_still_parses_itinerary():
    result = parse_flight_text("\n\n".join(["예약번호", REF] + OUTBOUND + RETURN))
    assert result["passengers"] == []
    assert len(result["legs"]) == 2
    assert result["legs_complete"] is True


def test_empty_text_returns_none():
    assert parse_flight_text("") is None
    assert parse_flight_text("  \n\n  ") is None


def test_payment_notice_without_year_is_incomplete():
    text = "\n\n".join(["결제 완료 안내", "예약번호", REF, "가는편: 서울 - 삿포로", "6월 16일",
                       "오는편: 삿포로 - 서울", "6월 21일"] + _passenger_lines((("KIM", "ALPHA"),)))
    result = parse_flight_text(text)
    assert result["passengers"] == [{"surname": "KIM", "given_name": "ALPHA"}]
    assert result["legs"][0] == {"label": "가는편", "origin_city": "서울", "destination_city": "삿포로",
                                 "departure_on": "", "segments": []}
    assert result["legs_complete"] is False


def test_one_way_trip_has_single_leg():
    result = parse_flight_text(_confirmation(legs=(OUTBOUND,)))
    assert [leg["label"] for leg in result["legs"]] == ["가는편"]
    assert result["legs_complete"] is True


def test_connection_yields_two_segments():
    block = ["가는편: 서울 - 도쿄", "2026년 6월 16일", "07:10", "ICN 인천국제공항", "T1", "제주항공", "7C1501",
             "09:00", "NRT 나리타", "T2", "10:30", "NRT 나리타", "T2", "JL123", "13:00", "CTS 신치토세 공항"]
    result = parse_flight_text(_confirmation(legs=(block,)))
    assert result["legs"][0]["segments"] == [
        {"departure_time": "07:10", "departure_airport": "ICN", "arrival_time": "09:00",
         "arrival_airport": "NRT", "flight_number": "7C1501"},
        {"departure_time": "10:30", "departure_airport": "NRT", "arrival_time": "13:00",
         "arrival_airport": "CTS", "flight_number": "JL123"},
    ]
    assert result["legs_complete"] is True


def test_mismatched_connection_block_is_incomplete():
    block = ["가는편: 서울 - 도쿄", "2026년 6월 16일", "07:10", "ICN 인천국제공항", "09:00", "NRT 나리타",
             "10:30", "NRT 나리타", "13:00", "CTS 신치토세 공항", "7C1501"]
    result = parse_flight_text(_confirmation(legs=(block,)))
    assert result["legs"][0]["segments"] == []
    assert result["legs_complete"] is False


def test_invalid_calendar_date_is_incomplete():
    block = ["가는편: 서울 - 삿포로", "2026년 2월 31일", "07:10", "ICN 인천국제공항", "7C1501",
             "10:00", "CTS 신치토세 공항"]
    result = parse_flight_text(_confirmation(legs=(block,)))
    assert result["legs"][0]["departure_on"] == ""
    assert result["legs_complete"] is False


def test_merge_payment_notice_with_confirmation():
    payment = parse_flight_text("\n\n".join(
        ["결제 완료 안내", "예약번호", REF, "가는편: 서울 - 삿포로", "6월 16일", "오는편: 삿포로 - 서울", "6월 21일"]
        + _passenger_lines((("KIM", "ALPHA"), ("YOO", "ANSOON")))))
    confirmation = parse_flight_text(_confirmation())
    payment["source_digest"] = "a" * 64
    confirmation["source_digest"] = "b" * 64
    merged = merge_booking_evidence([payment, confirmation])
    assert merged["booking_ref"] == "1400826934962683"
    assert merged["passengers"] == [{"surname": "KIM", "given_name": "ALPHA"},
                                    {"surname": "YOO", "given_name": "ANSOON"}]
    assert merged["legs"][0]["departure_on"] == "2026-06-16"
    assert merged["legs"][0]["segments"] == [OUTBOUND_SEGMENT]
    assert merged["legs_complete"] is True
    assert merged["conflict"] is False
    assert merged["source_digests"] == ["a" * 64, "b" * 64]


def test_merge_conflicting_departure_dates_sets_conflict():
    first = parse_flight_text(_confirmation())
    second = parse_flight_text(_confirmation(legs=(["가는편: 서울 - 삿포로", "2026년 6월 17일"] + OUTBOUND[2:], RETURN)))
    assert merge_booking_evidence([first, second])["conflict"] is True
    clean = merge_booking_evidence([first])
    disputed = merge_booking_evidence([first, second])
    assert clean['digest'] != disputed['digest']


def test_merge_digest_is_stable_across_part_order():
    first = parse_flight_text(_confirmation())
    second = parse_flight_text(_confirmation(people=(("LEE", "BETA"),)))
    first["source_digest"] = "c" * 64
    second["source_digest"] = "d" * 64
    forward = merge_booking_evidence([first, second])
    backward = merge_booking_evidence([second, first])
    assert forward["digest"] == backward["digest"]
    assert len(forward["passengers"]) == 2


def _trip_message(message_id, text, authenticated=True):
    return {"id": message_id, "auth": authenticated,
            "payload": {"headers": [{"name": "From", "value": "noreply@trip.com"}],
                        "body": {"content": text}}}


def _fake_authenticated_headers(message, domains):
    return ({}, "trip.com") if message["auth"] else None


def _fake_body_text(payload):
    return payload["body"]["content"]


def test_collect_groups_authenticated_trip_mail_and_ignores_unauthenticated(tmp_path):
    flight_evidence._MEMO.clear()
    messages = {
        "m1": _trip_message("m1", _confirmation(people=(("KIM", "ALPHA"),))),
        "m2": _trip_message("m2", _confirmation(people=(("LEE", "BETA"),))),
        "m3": _trip_message("m3", _confirmation(ref="9999999999999999"), authenticated=False),
    }
    with patch("app.ota_mail.load_messages_from", return_value=(messages, [])), \
            patch("app.ota_mail.authenticated_headers", side_effect=_fake_authenticated_headers), \
            patch("app.ota_mail.body_text", side_effect=_fake_body_text):
        result = collect_flight_evidence([tmp_path])
    assert list(result) == [("trip", "1400826934962683")]
    evidence = result[("trip", "1400826934962683")]
    assert {(p["surname"], p["given_name"]) for p in evidence["passengers"]} == {("KIM", "ALPHA"), ("LEE", "BETA")}
    assert len(evidence["source_digests"]) == 2
    assert evidence["legs_complete"] is True


def test_collect_marks_authenticated_cancellation_subject_and_keeps_policy_text_unconfirmed(tmp_path):
    flight_evidence._MEMO.clear()
    messages = {"cancel": _trip_message("cancel", _confirmation(people=(("KIM", "ALPHA"),))),
                "policy": _trip_message("policy", _confirmation(people=(("LEE", "BETA"),)))}
    messages["cancel"]["subject"] = "Booking cancellation confirmed"
    messages["policy"]["subject"] = "Booking confirmed"
    with patch("app.ota_mail.load_messages_from", return_value=(messages, [])), \
            patch("app.ota_mail.authenticated_headers",
                  side_effect=lambda message, domains: ({"subject": message["subject"]}, "trip.com")), \
            patch("app.ota_mail.body_text", side_effect=_fake_body_text):
        result = collect_flight_evidence([tmp_path])
    evidence = result[("trip", "1400826934962683")]
    assert evidence["cancellation_status"] == "CONFLICT"


def test_collect_preserves_cancellation_only_notice_with_reference(tmp_path):
    flight_evidence._MEMO.clear()
    messages = {"cancel": _trip_message("cancel", "예약번호\n1400826934962683")}
    messages["cancel"]["subject"] = "Booking cancellation confirmed"
    with patch("app.ota_mail.load_messages_from", return_value=(messages, [])), \
            patch("app.ota_mail.authenticated_headers",
                  side_effect=lambda message, domains: ({"subject": message["subject"]}, "trip.com")), \
            patch("app.ota_mail.body_text", side_effect=_fake_body_text):
        result = collect_flight_evidence([tmp_path])
    assert result[("trip", "1400826934962683")]["cancellation_status"] == "CANCELLED"
    assert result[("trip", "1400826934962683")]["passengers"] == []


def test_collect_reuses_memo_for_identical_stamps(tmp_path):
    flight_evidence._MEMO.clear()
    mail_file = tmp_path / "gmail-a.json"
    mail_file.write_text('{"responses": []}', encoding="utf-8")
    messages = {"m1": _trip_message("m1", _confirmation())}
    with patch("app.ota_mail.load_messages_from", return_value=(messages, [])) as load, \
            patch("app.ota_mail.authenticated_headers", side_effect=_fake_authenticated_headers), \
            patch("app.ota_mail.body_text", side_effect=_fake_body_text):
        first = collect_flight_evidence([tmp_path])
        second = collect_flight_evidence([tmp_path])
        assert load.call_count == 1
        assert second == first
        mail_file.write_text('{"responses": [1]}', encoding="utf-8")
        collect_flight_evidence([tmp_path])
        assert load.call_count == 2
