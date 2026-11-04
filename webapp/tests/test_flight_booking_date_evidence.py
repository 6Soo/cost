"""Strict source-labeled booking dates: synthetic data only, no operational records."""
from app import flight_evidence as evidence
from webapp import flight_passenger_page as page
from unittest.mock import patch
import pytest


def _part(day, digest, status="EXPLICIT_LABEL"):
    return {
        "booking_ref": "SYNTH-100", "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
        "legs": [], "source_digest": digest, "cancellation_status": "NONE",
        "reserved_on": day, "booking_date_status": status,
    }


def test_accepts_only_explicit_booking_created_date_with_valid_calendar():
    text = "예약번호: 123456789\nKIM\n(성)\nALPHA\n(이름)\n예약일: 2026-10-02\n출발일: 2026-10-27"
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
    with patch("webapp.flight_booking_index.passenger_index_for", return_value=index), patch(
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


def test_booking_time_preserves_zone_and_uses_exact_korean_day_only():
    raw = '예약번호: 123456789\nKIM\n(성)\nALPHA\n(이름)\n'
    utc = evidence.parse_flight_text(raw + 'Booking created at: 2026-10-02 23:30 UTC')
    assert utc['reserved_on'] == '2026-10-02'
    assert utc['booking_card_day'] == '2026-10-03'
    assert utc['booking_date_evidence'][0]['timestamp'] == '2026-10-02T23:30:00+00:00'
    no_zone = evidence.parse_flight_text(raw + '예약일: 2026-10-02 23:30')
    assert no_zone['reserved_on'] == '2026-10-02' and not no_zone['booking_card_day']
    date_only = evidence.parse_flight_text(raw + '예약일: 2026-10-02')
    assert date_only['booking_date_status'] == 'EXPLICIT_LABEL' and not date_only['booking_card_day']
    for bad in ('예약일: 2026-10-02 99:99 KST', '예약일: 2026-10-02 23:30 +25:00'):
        assert evidence.parse_flight_text(raw + bad)['booking_date_status'] == 'UNKNOWN'
    multi = evidence.parse_flight_text(raw + '예약번호: 987654321\n예약일: 2026-10-02 23:30 KST')
    assert multi['booking_date_status'] == 'CONFLICT' and not multi['booking_card_day']
    utc['source_digest'] = 'synthetic-source'
    merged = evidence.merge_booking_evidence([utc])
    assert merged['booking_date_evidence'][0]['source_digest'] == 'synthetic-source'
    altered = dict(utc, booking_date_evidence=[dict(utc['booking_date_evidence'][0], timezone='GMT')])
    assert merged['digest'] != evidence.merge_booking_evidence([altered])['digest']


@pytest.mark.parametrize('date_basis', ['EXPLICIT_LABEL', 'FIRST_RECEIVED'])
def test_browser_auto_day_requires_unlinked_fresh_uncancelled_zoned_evidence(date_basis):
    from copy import deepcopy
    from playwright.sync_api import sync_playwright, expect
    from webapp import site_shell
    base = {'booking_ref': 'SYNTH-OK', 'passenger_name': 'KIM ALPHA', 'legs': [],
            'source_verified': True, 'booking_date_status': date_basis,
            'reserved_on': '2026-10-02', 'booking_card_day': '2026-10-03',
            'booking_date_evidence': [{'timestamp': '2026-10-02T23:30:00+00:00'}],
            'linked_cards': [], 'cancelled': False, 'conflict': False}
    rows = [base]
    for name, extra in [('LINKED', {'linked_cards': [{'merchant': 'Synthetic linked', 'amount_krw': 100}]}),
                        ('CANCELLED', {'cancelled': True}), ('CONFLICT', {'conflict': True}),
                        ('NOZONE', {'booking_card_day': ''}), ('STALE', {'source_verified': False})]:
        rows.append(dict(deepcopy(base), booking_ref='SYNTH-' + name, **extra))
    with patch('webapp.ledger_design._nav_html', return_value='<aside id="nav"></aside>'):
        document = site_shell.wrap_document(page._page('synthetic-csrf'), '/flight-passengers')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            screen = browser.new_page(viewport={'width': 375, 'height': 812})
            screen.route('http://synthetic.test/flight-passengers', lambda route: route.fulfill(body=document, content_type='text/html'))
            screen.route('**/api/flight-passengers/name-search', lambda route: route.fulfill(json={
                'reservations': rows, 'total': len(rows), 'revision': 'synthetic', 'source_status': 'VERIFIED'}))
            calls = []
            def day(route):
                calls.append((route.request.method, route.request.url))
                route.fulfill(json={'filter_semantics': 'USER_DATE_FILTER', 'date': '2026-10-03',
                                    'items': [], 'total_count': 0, 'has_more': False, 'revision': 'synthetic'})
            screen.route('**/api/cards/transactions/day?*', day)
            screen.goto('http://synthetic.test/flight-passengers')
            screen.get_by_label('항공권 검색').fill('KIM ALPHA')
            screen.get_by_role('button', name='예약 조회', exact=True).click()
            expect(screen.locator('.fb-ticket')).to_have_count(6)
            assert not calls
            screen.locator('.fb-booking-choice > summary').first.click()
            screen.locator('.fb-more-details > summary').first.click()
            screen.locator('.fb-date-filter > summary').first.click()
            expect(screen.locator('.fb-date-status').first).to_contain_text('현재 조회 범위에서 결과 없음')
            if date_basis == 'FIRST_RECEIVED':
                expect(screen.locator('.fb-ticket').first).to_contain_text('최초 메일 수신일 기준')
                expect(screen.locator('.fb-date-status').first).to_contain_text('최초 인증 메일 수신일 기준')
            assert len(calls) == 1 and calls[0][0] == 'GET' and 'date=2026-10-03' in calls[0][1]
            expect(screen.locator('.fb-date-status').first).to_be_visible()
        finally:
            browser.close()
