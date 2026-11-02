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
    policy_body = parse_flight_text("취소 요청 시 수수료가 발생합니다\n" + _confirmation())
    policy_subject = parse_flight_text("Subject: 취소 규정 안내\n" + _confirmation())
    assert policy_body["cancellation_status"] == "NONE"
    assert policy_subject["cancellation_status"] == "NONE"
    assert parse_flight_text("예약 취소가 완료되면 이메일로 안내합니다\n" + _confirmation())["cancellation_status"] == "NONE"
    assert parse_flight_text("예약 취소 완료 시 이메일로 안내합니다\n" + _confirmation())["cancellation_status"] == "NONE"
    assert parse_flight_text("취소 요청 시 수수료가 발생합니다\n" + _confirmation())["cancellation_status"] == "NONE"
    assert parse_flight_text("예약 취소 완료\n" + _confirmation())["cancellation_status"] == "CANCELLED"
    assert parse_flight_text("예약 취소가 완료되었습니다\n" + _confirmation())["cancellation_status"] == "CANCELLED"
    assert parse_flight_text("예약 취소가 완료되었습니다\n예약 취소가 완료되면 이메일로 안내합니다\n" + _confirmation())["cancellation_status"] == "CANCELLED"


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


def test_labeled_departure_notice_assigns_only_explicit_one_way_day():
    text = ('예약번호: 9000012345678901\n결제일: 2031년 2월 1일\n'
            '출발：2031년 3월 10일 09:20, 합성 공항\n'
            '도착：2031년 3월 10일 11:00, 다른 공항\n')
    parsed = parse_flight_text(text)
    parsed['source_digest'] = 'synthetic'
    merged = merge_booking_evidence([parsed])
    assert merged['legs'][0]['departure_on'] == '2031-03-10'
    assert merged['legs_complete'] is False
    from webapp.trip_flight_read import project_trip_bookings, page_for_trip
    trip = {'tab_id': 'trip-A', 'starts_on': '2031-03-10', 'ends_on': '2031-03-12'}
    projection = project_trip_bookings({'9000012345678901': merged}, [trip], source_generation='x')
    assert page_for_trip(projection, 'trip-A')['total_bookings'] == 1
    assert parse_flight_text(text + '출발：2031년 3월 11일 09:20, 합성 공항\n') is None
    assert parse_flight_text(text + '예약번호: 9000099999999999\n') is None


def test_labeled_departure_disagreement_keeps_booking_in_conflict():
    def item(day):
        value = parse_flight_text(f'예약번호: 9000012345678901\n출발：2031년 3월 {day}일 09:20, 합성\n도착：2031년 3월 {day}일 11:00, 합성')
        value['source_digest'] = day
        return value
    result = merge_booking_evidence([item('10'), item('11')])
    assert result['conflict'] is True
    assert result['legs'] == []


def _flattened_confirmation():
    return (
        '예약번호 9000012345678901[합성] 예약 확인'
        '1: 알파 - 베타 | 2031년 3월 10일'
        '* 모든 출발·도착시간은 현지시간 기준입니다.'
        '09:20AAA 합성공항 T1합성항공 ZZ101 | 일반석 | 보잉 737-800 | 기내식 불포함'
        '11:00BBB 합성공항'
        '2: 감마 - 알파 | 2031년 3월 20일'
        '14:30CCC 합성공항 I합성항공 ZY202 | 일반석 | 에어버스 A330-300 | 기내식 불포함'
        '16:00AAA 합성공항 T1규정 조회 및 취소·변경 요청'
        'SYNTH\u00a0(성)\u00a0ALPHA\u00a0(이름)성인 항공권'
    )


def test_flattened_numbered_itinerary_keeps_explicit_names_reference_and_segments():
    result = parse_flight_text(_flattened_confirmation())
    assert result is not None
    assert result['booking_ref'] == '9000012345678901'
    assert result['passengers'] == [{'surname': 'SYNTH', 'given_name': 'ALPHA'}]
    assert result['legs_complete'] is True
    assert [leg['departure_on'] for leg in result['legs']] == ['2031-03-10', '2031-03-20']
    assert [leg['segments'][0]['flight_number'] for leg in result['legs']] == ['ZZ101', 'ZY202']
    assert result['legs'][0]['segments'][0]['departure_airport'] == 'AAA'
    assert result['legs'][1]['segments'][0]['arrival_airport'] == 'AAA'


def test_flattened_mail_collection_keeps_authentication_and_first_received_boundary(tmp_path):
    import hashlib
    import json
    flight_evidence._MEMO.clear()
    trusted = _trip_message('synthetic-trusted', _flattened_confirmation())
    trusted.update(owner_collected=True, internal_date='1893456000000')
    untrusted = _trip_message('synthetic-untrusted', _flattened_confirmation())
    (tmp_path / 'gmail-flattened.json').write_text(
        json.dumps({'responses': [trusted, untrusted]}), encoding='utf-8')

    bookings = collect_flight_evidence([tmp_path])

    assert len(bookings) == 1
    result = bookings[('trip', '9000012345678901')]
    assert result['source_digests'] == [hashlib.sha256(b'synthetic-trusted').hexdigest()]
    assert result['booking_date_status'] == 'FIRST_RECEIVED'
    assert result['passengers'] == [{'surname': 'SYNTH', 'given_name': 'ALPHA'}]
    assert result['legs_complete'] is True


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
