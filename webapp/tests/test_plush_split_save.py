"""Synthetic tests for the Plush split-allocation connection.

Plush is a projection/descriptor layer: the split plan itself is saved by the
existing ``POST /api/income/{row_id}/allocations`` authority, which owns CSRF,
revision conflict, request idempotency and plan validation. These tests pin the
advertised action (URL, fields, role/closed gates) and exercise the advertised
payload contract against that authority; all data is synthetic.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from webapp import access_control, ledger_board, plush_api
from webapp.ledger_store import LedgerStore

OWNER = "syn-owner"


class Handler:
    command = "GET"

    def __init__(self, user: str | None):
        self.headers = {}
        if user:
            self.headers[access_control.SyntheticSessionAdapter.HEADER] = user
        self.responses = []

    def _send_json(self, value, code=200, **_kwargs):
        self.responses.append((code, value))


@pytest.fixture()
def descriptor_env(tmp_path):
    store = LedgerStore(tmp_path / "split.sqlite")
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner(OWNER)
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    try:
        yield store
    finally:
        ledger_board.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        ledger_board.bind_store(None)
        store.close()


def _call(path, user, store):
    parsed = SimpleNamespace(
        path=path.split("?", 1)[0],
        query=path.split("?", 1)[1] if "?" in path else "",
    )
    handler = Handler(user)
    assert plush_api.dispatch(handler, parsed, board=store) is True
    assert handler.responses
    return handler.responses[-1]


def _action(detail, action_id):
    for item in detail.get("actions", []):
        if item.get("id") == action_id:
            return item
    return None


def _make_income(store, *, amount=500000, request_id="plush-split-source", **extra):
    fields = {
        "display_tab_id": "trip-demo-a", "occurred_on": "2026-04-01",
        "amount_krw": amount, "income_kind": "deposit",
        "customer_id": None, "customer_name": "합성 고객",
        "nickname": "", "memo": "",
    }
    fields.update(extra)
    return store.create_direct_income(fields=fields, client_request_id=request_id)


def _allocation(customer, amount, *, tab="trip-demo-a", kind="deposit",
                allocation_id=""):
    return {"customer_name": customer, "display_tab_id": tab,
            "income_kind": kind, "amount_krw": amount,
            "allocation_id": allocation_id}


def _split_payload(revision, client_request_id, allocations, *,
                   new_principal=None):
    payload = {
        "csrf": ledger_board.CSRF_TOKEN,
        "expected_source_revision": revision,
        "client_request_id": client_request_id,
        "allocations": allocations,
    }
    if new_principal is not None:
        payload["new_principal_amount"] = new_principal
    return payload


def _post_split(port, row_id, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/income/{row_id}/allocations",
        data=data, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


# --- descriptor -------------------------------------------------------------

def test_income_row_advertises_the_split_save_action(descriptor_env):
    store = descriptor_env
    created = _make_income(store)
    status, detail = _call(f"/api/plush/row?id={created['row_id']}", OWNER, store)
    assert status == 200
    action = _action(detail, "income-split-save")
    assert action["method"] == "POST"
    assert action["href"] == f"/api/income/{created['row_id']}/allocations"
    assert action["encoding"] == "allocation-plan"
    assert action["csrf"] == "header"
    assert action["response"] == "json"
    assert "fields" not in action
    # The initial plan DTO carries the current state so a split form can render
    # and re-submit the full plan without a second read.
    assert detail["split"] == {
        "source_row_id": created["row_id"],
        "expected_source_revision": 1,
        "reflected_amount_krw": 500000,
        "source_kind": "직접 입력",
        "plan": [],
        "remainder": 500000,
    }


def test_allocation_row_points_at_its_source(descriptor_env):
    store = descriptor_env
    created = _make_income(store)
    store.save_allocations(
        source_row_id=created["row_id"], expected_source_revision=1,
        allocations=[_allocation("U1", 300000, allocation_id="alc-plush-1")
                     | {"nickname": "합성 별칭"}],
        client_request_id="plush-split-plan-1",
    )
    status, detail = _call("/api/plush/row?id=alc-plush-1", OWNER, store)
    assert status == 200
    assert detail["row"]["id"] == "alc-plush-1"
    action = _action(detail, "income-split-save")
    assert action is not None
    assert action["href"] == f"/api/income/{created['row_id']}/allocations"
    assert "fields" not in action
    assert detail["split"] == {
        "source_row_id": created["row_id"],
        "expected_source_revision": 2,
        "reflected_amount_krw": 500000,
        "source_kind": "직접 입력",
        "plan": [
            {"allocation_id": "alc-plush-1", "customer_name": "U1",
             "customer_id": None, "nickname": "합성 별칭",
             "display_tab_id": "trip-demo-a", "income_kind": "deposit",
             "amount_krw": 300000},
        ],
        "remainder": 200000,
    }


def test_split_save_absent_for_viewer(descriptor_env, monkeypatch):
    store = descriptor_env
    created = _make_income(store)
    access = ledger_board.access_store()
    access.create_account(user_id="syn-viewer", role=access_control.ROLE_VIEWER)
    monkeypatch.setattr(access, "visible_tabs", lambda user_id, now=None: {"trip-demo-a"})
    status, detail = _call(f"/api/plush/row?id={created['row_id']}", "syn-viewer", store)
    assert status == 200
    assert _action(detail, "income-split-save") is None
    assert detail["read_only"] is True
    assert detail["split"] is None


def test_split_save_absent_for_closed_trip(descriptor_env, monkeypatch):
    store = descriptor_env
    created = _make_income(store)
    original = plush_api._visible_trips

    def closed(board, access, session, owner, *args, **kwargs):
        return [{**trip, "visual_closed": True}
                if trip.get("tab_id") == "trip-demo-a"
                else trip
                for trip in original(board, access, session, owner)]

    monkeypatch.setattr(plush_api, "_visible_trips", closed)
    status, detail = _call(f"/api/plush/row?id={created['row_id']}", OWNER, store)
    assert status == 200
    assert _action(detail, "income-split-save") is None
    assert detail["split"] is None


def test_split_save_renders_only_for_saveable_income(descriptor_env, monkeypatch):
    store = descriptor_env
    rows = {
        "expense-row": {"row_id": "expense-row", "row_kind": "expense",
                        "source_kind": "카드", "revision": 4},
        "bank-income": {"row_id": "bank-income", "row_kind": "income",
                        "source_kind": "은행", "customer_name": "합성",
                        "income_kind": "deposit", "display_tab_id": "trip-demo-a",
                        "occurred_on": "2026-04-01", "amount_krw": 1000,
                        "revision": 5},
        "google-income": {"row_id": "google-income", "row_kind": "income",
                          "source_kind": "구글", "google_income": True, "revision": 6},
    }
    monkeypatch.setattr(store, "get_row", lambda row_id: rows.get(row_id))
    monkeypatch.setattr(store, "projected", lambda row: row)
    # All three ids resolve through the mocked get_row, so no Google snapshot is
    # read; the split save is server-side only for ordinary income rows.
    for row_id in ("expense-row", "bank-income", "google-income"):
        status, detail = _call(f"/api/plush/row?id={row_id}", OWNER, store)
        assert status == 200
        action = _action(detail, "income-split-save")
        if row_id == "bank-income":
            assert action is not None
            assert detail["split"]["source_kind"] == rows[row_id]["source_kind"]
            assert detail["split"]["source_row_id"] == "bank-income"
            assert detail["split"]["plan"] == []
        else:
            assert action is None, row_id
            assert detail["split"] is None, row_id


# --- the advertised contract against the authority ---------------------------

@pytest.fixture()
def http_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBLEDGER_DB", str(tmp_path / "split-http.sqlite"))
    monkeypatch.setenv("WEBLEDGER_CARD_FLOW", "0")
    monkeypatch.setenv("WEBLEDGER_UNIFIED_DB", "0")
    store = LedgerStore(tmp_path / "split-http.sqlite")
    server = ledger_board.serve(port=0, with_worker=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield store, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
        ledger_board.bind_store(None)
        store.close()


def test_advertised_payload_saves_replays_and_keeps_remainder(http_env):
    store, port = http_env
    created = _make_income(store)
    payload = _split_payload(
        1, "plush-split-http-1",
        [_allocation("U1", 300000, tab="trip-demo-a"),
         _allocation("U2", 200000, tab="trip-demo-b")],
        new_principal=500000,
    )
    status, saved = _post_split(port, created["row_id"], payload)
    assert status == 200, saved
    assert saved["outcome"] == "saved"
    assert saved["revision"] == 2
    assert saved["remainder"] == 0

    status, replayed = _post_split(port, created["row_id"], payload)
    assert status == 200, replayed
    assert replayed["revision"] == 2
    assert store.get_row(created["row_id"])["revision"] == 2

    status, cleared = _post_split(
        port, created["row_id"],
        _split_payload(2, "plush-split-http-2", []),
    )
    assert status == 200, cleared
    assert cleared["remainder"] == 500000
    assert store.active_allocations(created["row_id"]) == []


def test_split_validation_rejects_blank_zero_over_and_stale(http_env):
    store, port = http_env
    created = _make_income(store)

    status, result = _post_split(
        port, created["row_id"],
        _split_payload(1, "plush-split-http-3", [{}]),
    )
    assert status == 422 and result["code"] == "INVALID_VALUE"

    status, result = _post_split(
        port, created["row_id"],
        _split_payload(1, "plush-split-http-4", [_allocation("U1", 0)]),
    )
    assert status == 422 and result["code"] == "INVALID_VALUE"

    status, result = _post_split(
        port, created["row_id"],
        _split_payload(1, "plush-split-http-5", [_allocation("", 100000)]),
    )
    assert status == 422 and result["code"] == "INVALID_VALUE"

    status, result = _post_split(
        port, created["row_id"],
        _split_payload(1, "plush-split-http-6", [_allocation("U1", 600000)]),
    )
    assert status == 422 and result["code"] == "INVALID_VALUE"

    status, result = _post_split(
        port, created["row_id"], _split_payload(1, "plush-split-http-7", []))
    assert status == 200, result
    assert store.get_row(created["row_id"])["revision"] == 2

    status, result = _post_split(
        port, created["row_id"],
        _split_payload(1, "plush-split-http-8", [_allocation("U1", 100000)]),
    )
    assert status == 409 and result["code"] == "EDIT_CONFLICT"


def test_split_negative_refund_sign_protection(http_env):
    store, port = http_env
    created = _make_income(store, amount=-500000, request_id="plush-split-refund")
    status, result = _post_split(
        port, created["row_id"],
        _split_payload(1, "plush-split-refund-1",
                       [_allocation("R1", 100000, tab="trip-demo-b")]),
    )
    assert status == 422 and result["code"] == "INVALID_VALUE"
    status, saved = _post_split(
        port, created["row_id"],
        _split_payload(1, "plush-split-refund-2",
                       [_allocation("R1", -100000, tab="trip-demo-b")]),
    )
    assert status == 200, saved
    assert saved["remainder"] == -400000


def test_split_save_requires_csrf(http_env):
    store, port = http_env
    created = _make_income(store, request_id="plush-split-http-csrf")
    payload = {
        "expected_source_revision": 1,
        "client_request_id": "plush-split-http-csrf-plan",
        "allocations": [_allocation("U1", 100000)],
    }
    status, result = _post_split(port, created["row_id"], payload)
    assert status == 403 and result["code"] == "CSRF_REQUIRED"
