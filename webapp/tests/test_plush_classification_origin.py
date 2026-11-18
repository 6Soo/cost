"""The row drawer's classification-origin label reads the stored provenance, not editorship."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from webapp import access_control, ledger_board, plush_api, plush_projection
from webapp.ledger_store import LedgerStore
from webapp.tests.test_card_automatic_ux import flow


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
def bound_store(tmp_path):
    previous_store, previous_access = ledger_board._STORE, ledger_board._ACCESS
    previous_adapter = access_control.session_adapter()
    store = LedgerStore(tmp_path / "origin.sqlite", seed_demo=False)
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner("syn-owner")
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    try:
        yield store, access
    finally:
        ledger_board.bind_access(previous_access)
        access_control.bind_sessions(previous_adapter)
        ledger_board.bind_store(previous_store)
        store.close()


def call(path, user, store):
    parsed = SimpleNamespace(path=path.split("?", 1)[0], query=path.split("?", 1)[1] if "?" in path else "")
    handler = Handler(user)
    assert plush_api.dispatch(handler, parsed, board=store) is True
    assert handler.responses
    return handler.responses[-1]


def _payload(store, row_id):
    return json.loads(store.conn.execute(
        "SELECT payload_json FROM board_rows WHERE row_id=?", (row_id,)).fetchone()[0])


def _insert(store, source, *, basis="", decided_at=None, confirmed_by="owner"):
    trip = store.create_trip(starts_on="2026-10-01", ends_on="2026-10-05",
                             destination="합성 출처", client_request_id=f"trip-{source or 'none'}")["tab_id"]
    row_id = "card-origin-" + (source or "none")
    record = {
        "row_id": row_id, "row_kind": "expense", "occurred_on": "2026-10-02",
        "item": "숙박비", "description": "합성", "amount_krw": 1000, "source_kind": "카드",
        "source_event_id": source or "none", "source_merchant": "합성 가맹점",
        "classification_state": "classified", "classification_source": source,
        "classification_basis": basis, "decided_at": decided_at,
        "confirmed_by": confirmed_by, "revision": 1,
    }
    store.conn.execute(
        "INSERT INTO board_rows(row_id,row_kind,display_tab_id,revision,payload_json)"
        " VALUES(?,?,?,?,?)", (row_id, "expense", trip, 1, json.dumps(record)))
    store.conn.commit()
    return trip, row_id


@pytest.mark.parametrize("source,label", [
    ("inference", "코드 추론"), ("auto_inferred", "코드 추론"), ("code_inference", "코드 추론"),
    ("ai_inference", "AI 추론"),
    ("manual", "직접"), ("user_decision", "직접"),
    ("rule", "자동"), ("owner_booking", "자동"),
])
@pytest.mark.parametrize("confirmed_by", ["owner", "automatic"])
def test_origin_label_follows_stored_source_not_editor(bound_store, source, label, confirmed_by):
    store, _ = bound_store
    _, row_id = _insert(store, source, confirmed_by=confirmed_by)
    code, body = call(f"/api/plush/row?id={row_id}", "syn-owner", store)
    assert code == 200
    assert body["classification_origin"] == label


def test_unknown_origin_omits_the_label(bound_store):
    store, _ = bound_store
    _, row_id = _insert(store, "")
    code, body = call(f"/api/plush/row?id={row_id}", "syn-owner", store)
    assert code == 200
    assert body["classification_origin"] == ""


def test_plain_revision_bump_and_field_edit_do_not_relabel_the_origin(bound_store):
    store, _ = bound_store
    _, row_id = _insert(store, "inference", basis="AUTO_TRIP_INFERRED 합성 기간")
    code, body = call(f"/api/plush/row?id={row_id}", "syn-owner", store)
    assert body["classification_origin"] == "코드 추론"
    store.save(row_id=row_id, expected_revision=1, client_request_id="origin-edit",
               change_mode="exception", changes={"description": "고친 내용"})
    code, body = call(f"/api/plush/row?id={row_id}", "syn-owner", store)
    assert body["classification_origin"] == "코드 추론"
    payload = _payload(store, row_id)
    payload["decided_at"] = "2026-11-18T00:00:00Z"
    store.conn.execute("UPDATE board_rows SET payload_json=? WHERE row_id=?",
                       (json.dumps(payload), row_id))
    store.conn.commit()
    code, body = call(f"/api/plush/row?id={row_id}", "syn-owner", store)
    assert body["classification_origin"] == "직접"


def test_viewer_never_receives_the_origin(bound_store, monkeypatch):
    store, access = bound_store
    access.create_account(user_id="syn-viewer", role=access_control.ROLE_VIEWER)
    trip, row_id = _insert(store, "ai_inference")
    monkeypatch.setattr(access, "visible_tabs", lambda user_id: {trip})
    monkeypatch.setattr(access, "require_view_tab", lambda user_id, tab_id, **_: None)
    code, body = call(f"/api/plush/row?id={row_id}", "syn-viewer", store)
    assert code == 200
    assert body["classification_origin"] is None
    assert body["decision"] is None
    assert body["source"] is None


def test_auto_record_projects_the_stored_source_into_the_row_payload(flow):
    """End-to-end through the real CardFlow auto-record path, not a hand-built DTO."""
    f, batch, _trip = flow
    assert f.auto_record(batch)["auto_recorded"] == 2
    projected = f.board.conn.execute(
        "SELECT payload_json FROM board_rows WHERE row_id='card-' || ("
        " SELECT transaction_id FROM transactions WHERE amount_krw=89891)").fetchone()[0]
    payload = json.loads(projected)
    assert payload["confirmed_by"] == "automatic"
    assert payload["classification_source"] in {"inference", "auto_inferred", "code_inference"}
    assert plush_projection.origin_label(payload) == "코드 추론"
