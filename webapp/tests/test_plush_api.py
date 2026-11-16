"""Targeted authenticated projection tests for the Plush API."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from webapp import access_control
from webapp import ledger_board
from webapp import plush_api
from webapp.ledger_store import LedgerStore


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
    store = LedgerStore(tmp_path / "plush.sqlite")
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner("syn-owner")
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    try:
        yield store, access
    finally:
        ledger_board.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        ledger_board.bind_store(None)
        store.close()


def call(path, user, store):
    parsed = SimpleNamespace(path=path.split("?", 1)[0], query=path.split("?", 1)[1] if "?" in path else "")
    handler = Handler(user)
    assert plush_api.dispatch(handler, parsed, board=store) is True
    assert handler.responses
    return handler.responses[-1]


def test_bootstrap_and_ledger_are_structured_and_use_string_amounts(bound_store):
    store, _ = bound_store
    status, body = call("/api/plush/bootstrap", "syn-owner", store)
    assert status == 200
    assert body["role"] == "owner"
    assert body["trips"]
    assert all(isinstance(item["expense"], str) for item in body["trips"])

    status, ledger = call("/api/plush/ledger?tab=trip-demo-a&page_size=2&sort=amount_desc", "syn-owner", store)
    assert status == 200
    assert ledger["page_size"] == 2
    assert all(isinstance(item["amount"], str) for item in ledger["rows"])
    assert "operator_note" not in json.dumps(ledger, ensure_ascii=False)


def test_row_detail_has_owner_actions_but_no_legacy_html_href(bound_store):
    store, _ = bound_store
    status, detail = call("/api/plush/row?id=expense-demo-c1", "syn-owner", store)
    assert status == 200
    assert detail["actions"]
    assert all(action["href"].startswith("/api/") for action in detail["actions"])
    assert detail["expected_revision"]


def test_viewer_projection_uses_access_allowlist(bound_store, monkeypatch):
    store, access = bound_store
    access.create_account(user_id="syn-viewer", role=access_control.ROLE_VIEWER)
    monkeypatch.setattr(access, "visible_tabs", lambda user_id: {"trip-demo-a"})
    status, body = call("/api/plush/bootstrap", "syn-viewer", store)
    assert status == 200
    assert body["role"] == "viewer"
    assert [trip["id"] for trip in body["trips"]] == ["trip-demo-a"]
    status, _ = call("/api/plush/ledger?tab=trip-demo-b", "syn-viewer", store)
    assert status == 404


def test_viewer_without_a_valid_session_cannot_fallback_to_owner(bound_store):
    store, _ = bound_store
    status, body = call("/api/plush/bootstrap", "unknown-user", store)
    assert status == 401
    assert body["code"] == access_control.AUTH_REQUIRED


def test_non_plush_path_is_left_for_the_board_dispatch(bound_store):
    store, _ = bound_store
    handler = Handler("syn-owner")
    assert plush_api.dispatch(handler, SimpleNamespace(path="/board", query=""), board=store) is False
    assert not handler.responses


def test_transactions_without_a_card_source_report_unavailable_not_fake_rows(bound_store):
    store, _ = bound_store
    status, body = call("/api/plush/transactions?view=cards", "syn-owner", store)
    assert status == 200
    assert body["rows"] == []
    assert body["status"]["code"] == "SOURCE_UNAVAILABLE"
