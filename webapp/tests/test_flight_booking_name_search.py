"""Synthetic tests for name-only flight lookup. Never access live reservations."""
import json
import os
from unittest.mock import patch
from urllib.parse import urlsplit

from webapp import flight_passenger_page as page


def _index():
    return {
        "SYNTH-100": {
            "source_digests": ["sha-synthetic"],
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
            "legs": [{"origin": "ICN", "destination": "NRT"}],
            "cancellation_status": "NONE",
            "conflict": False,
        },
        "SYNTH-200": {
            "source_digests": ["sha-synthetic-b"],
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
            "legs": [],
            "cancellation_status": "CANCELLED",
            "conflict": False,
        },
        "SYNTH-NO-PROOF": {
            "passengers": [{"surname": "KIM", "given_name": "ALPHA"}],
        },
        "SYNTH-DIFFERENT": {
            "source_digests": ["sha-synthetic-c"],
            "passengers": [{"surname": "PARK", "given_name": "BETA"}],
        },
    }


class Handler:
    headers = {"X-CSRF-Token": "synthetic-csrf"}

    def _send_json(self, body, status=200):
        self.response = (status, body)

    def _send(self, body, status=200):
        self.response = (status, body)
        self.body = body


def test_name_search_needs_no_booking_number_or_tour_id():
    with patch("webapp.ota_payment_review.passenger_index_for", return_value=_index()) as lookup:
        found = page._name_search(object(), "  alpha / KIM ")
    assert [row["booking_ref"] for row in found["reservations"]] == ["SYNTH-100", "SYNTH-200"]
    assert found["reservations"][0]["source_verified"] is True
    assert found["reservations"][0]["cancelled"] is False
    assert found["reservations"][1]["cancelled"] is True
    lookup.assert_called_once()


def test_name_search_does_not_guess_korean_transliteration_or_unverified_records():
    with patch("webapp.ota_payment_review.passenger_index_for", return_value=_index()):
        assert page._name_search(object(), "김알파") == {"reservations": [], "truncated": False}
        assert not page._name_search(object(), "PARK BETA")["reservations"][0]["cancelled"]


def test_owner_only_post_search_csrf_and_old_assignment_route_stays():
    assert page.owns_route("/api/flight-passengers/assign")
    with patch.dict(os.environ, {page.FEATURE_FLAG: "1"}), patch(
        "webapp.ota_payment_review.passenger_index_for", return_value=_index()
    ):
        handler = Handler()
        assert page.dispatch(
            handler, urlsplit("/api/flight-passengers/name-search"),
            is_owner=True, board=object(), csrf="synthetic-csrf",
            raw=json.dumps({"name": "KIM ALPHA"}).encode(),
        )
        assert handler.response[0] == 200
        assert len(handler.response[1]["reservations"]) == 2
        handler = Handler()
        page.dispatch(handler, urlsplit("/api/flight-passengers/name-search"),
                      is_owner=False, board=object(), csrf="synthetic-csrf",
                      raw=b'{"name":"KIM ALPHA"}')
        assert handler.response[0] == 403
        handler = Handler()
        handler.headers = {}
        page.dispatch(handler, urlsplit("/api/flight-passengers/name-search"),
                      is_owner=True, board=object(), csrf="synthetic-csrf",
                      raw=b'{"name":"KIM ALPHA"}')
        assert handler.response[0] == 403


def test_page_renders_usable_name_only_ui_and_unknown_card_status():
    html = page._page('fake-token')
    assert '항공권 예약 확인' in html
    assert 'name="name"' in html
    assert 'name="booking_ref"' not in html
    assert 'name="tour_id"' not in html
    assert '예약일의 카드 거래 후보' in html
    assert '확정된 카드 연결 근거를 아직 검증할 수 없습니다' in html
    assert '/api/flight-passengers/name-search' in html
