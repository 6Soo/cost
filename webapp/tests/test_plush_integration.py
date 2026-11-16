"""Supervisor acceptance through the real board HTTP route and disposable data."""
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from webapp import access_control, ledger_board
from webapp.tests.test_plush_ui import http_ui  # noqa: F401 - shared real HTTP fixture


@pytest.fixture
def plush_api(http_ui):
    port, access = http_ui
    store = ledger_board._active_store()
    trips = []
    for index in range(2):
        trips.append(store.create_trip(
            starts_on="2026-11-10", ends_on="2026-11-20",
            destination=f"합성 API 여행 {index}",
            client_request_id=f"plush-api-trip-{index}")["tab_id"])
    access.apply_assignment_snapshot(
        user_id="synthetic-ui-viewer",
        items=[{"tab_id": trips[0], "snapshot_revision": 1, "state": "active"}],
        source_version="plush-api-synthetic", complete=True)
    ids = []
    for index, (tab, amount, text) in enumerate([
        (trips[0], 12000, "합성 지출 양수"),
        (trips[0], -1200, "합성 환불 음수"),
        (trips[0], 9007199254740993, "합성 정밀 금액"),
        (trips[1], 300, "비허용 합성 여행 자료"),
    ]):
        result = store.create_manual_expense(
            fields={"display_tab_id": tab, "occurred_on": "2026-11-12",
                    "amount_krw": amount, "item": "식비", "pay_method": "현금",
                    "description": text}, client_request_id=f"plush-row-{index:04d}")
        ids.append(result["row_id"])

    def request(path, *, user="synthetic-ui-owner", method="GET", payload=None):
        headers = {"Accept": "application/json"}
        if user:
            headers[access_control.SyntheticSessionAdapter.HEADER] = user
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers,
                                     data=data, method=method)
        try:
            response = urllib.request.urlopen(req)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())

    return request, trips, ids


def test_bootstrap_uses_actual_session_and_viewer_allowlist(plush_api):
    request, trips, _ = plush_api
    assert request("/api/plush/bootstrap", user=None)[0] == 401
    status, owner = request("/api/plush/bootstrap")
    assert status == 200 and owner["role"] == "owner"
    assert {trip["id"] for trip in owner["trips"]} >= set(trips)
    status, viewer = request("/api/plush/bootstrap", user="synthetic-ui-viewer")
    assert status == 200 and viewer["role"] == "viewer"
    assert {trip["id"] for trip in viewer["trips"]} == {trips[0]}
    assert trips[1] not in json.dumps(viewer)
    assert not viewer["receipt_enabled"]


def test_ledger_pages_preserve_exact_amount_and_full_filtered_totals(plush_api):
    request, trips, _ = plush_api
    query = urllib.parse.urlencode({"tab": trips[0], "kind": "expense", "page_size": 2})
    status, first = request("/api/plush/ledger?" + query)
    assert status == 200
    assert len(first["rows"]) == 2 and first["total_count"] == 3
    assert first["total"] == "9007199254751793"
    assert first["filtered_total"] == first["total"]
    status, second = request("/api/plush/ledger?" + query + "&page=2")
    assert status == 200 and len(second["rows"]) == 1
    amounts = {row["amount"] for row in first["rows"] + second["rows"]}
    assert amounts == {"12000", "-1200", "9007199254740993"}
    search = urllib.parse.urlencode({"tab": trips[0], "q": "合成不存在"})
    status, empty = request("/api/plush/ledger?" + search)
    assert status == 200 and empty["rows"] == [] and empty["total_count"] == 0
    assert empty["filtered_total"] == "0" and empty["total"] == first["total"]


def test_viewer_cannot_read_other_trip_or_row_or_owner_data(plush_api):
    request, trips, rows = plush_api
    for path in [
        "/api/plush/ledger?" + urllib.parse.urlencode({"tab": trips[1]}),
        "/api/plush/row?" + urllib.parse.urlencode({"id": rows[-1]}),
    ]:
        status, response = request(path, user="synthetic-ui-viewer")
        assert status == 404
        assert "비허용 합성 여행 자료" not in json.dumps(response, ensure_ascii=False)
    for path in ["/api/plush/transactions?view=cards", "/api/plush/admin?view=accounts",
                 "/api/plush/auxiliary?view=rules"]:
        status, response = request(path, user="synthetic-ui-viewer")
        assert status in (403, 404)
        assert "rows" not in response and "fields" not in response


def test_viewer_allowed_ledger_is_read_only(plush_api):
    request, trips, rows = plush_api
    status, result = request("/api/plush/ledger?" + urllib.parse.urlencode({"tab": trips[0]}),
                             user="synthetic-ui-viewer")
    assert status == 200 and all(row["read_only"] for row in result["rows"])
    status, detail = request("/api/plush/row?" + urllib.parse.urlencode({"id": rows[0]}),
                             user="synthetic-ui-viewer")
    assert status == 200 and detail["row"]["read_only"]
    assert not any(action["method"] == "POST" for action in detail["actions"])
