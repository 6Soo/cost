"""Projection tests for the Plush row-detail bank actions.

The advertised correction and source-link actions mirror the owner-only
server endpoints: bank-sourced income rows offer the ledger correction, and
directly entered income rows offer bank source linking. Each advertised shape
pins the server-required fields, revision, CSRF and response contract, and the
advertisement conditions stay symmetric with the store's refusal rules.
"""
from __future__ import annotations

import re
import sqlite3
from types import SimpleNamespace

import pytest

from webapp import access_control, ledger_board, plush_api
from webapp.income_ledger import BankImporter
from webapp.ledger_store import LedgerStore, SaveError

TRIP = "trip-demo-a"
BANK_CSV = (
    "occurred_on,payer_name,amount_krw,direction,account_ref,transaction_id,memo\n"
    "2026-04-02,김예시,500000,credit,ACC1,T1,\n"
    "2026-04-03,김예시,200000,credit,ACC1,T2,\n"
    "2026-04-04,출금자,-50000,debit,ACC1,T3,\n"
)


class Handler:
    command = "GET"

    def __init__(self, user):
        self.headers = {}
        if user:
            self.headers[access_control.SyntheticSessionAdapter.HEADER] = user
        self.responses = []

    def _send_json(self, value, code=200, **_kwargs):
        self.responses.append((code, value))


def call(path, user, store):
    parsed = SimpleNamespace(path=path.split("?", 1)[0],
                             query=path.split("?", 1)[1] if "?" in path else "")
    handler = Handler(user)
    assert plush_api.dispatch(handler, parsed, board=store) is True
    assert handler.responses
    return handler.responses[-1]


@pytest.fixture()
def env(tmp_path):
    db = tmp_path / "plush.sqlite"
    store = LedgerStore(db)
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner("syn-owner")
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    try:
        yield store, access, db
    finally:
        ledger_board.bind_access(None)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        ledger_board.bind_store(None)
        store.close()


def _detail(store, row_id, user="syn-owner"):
    status, detail = call(f"/api/plush/row?id={row_id}", user, store)
    assert status == 200
    return detail


def _action(detail, action_id):
    return next(action for action in detail["actions"] if action["id"] == action_id)


def _direct_row(store, request_id):
    return store.create_direct_income(
        fields={
            "display_tab_id": TRIP, "occurred_on": "2026-04-02", "amount_krw": 500000,
            "income_kind": "deposit", "customer_id": "U1", "customer_name": "김예시",
            "nickname": "", "memo": "",
        },
        client_request_id=request_id,
    )


def _bank_row(store, db):
    importer = BankImporter(sqlite3.connect(str(db), check_same_thread=False), store)
    received = importer.receive(BANK_CSV.encode("utf-8"), "bank.csv")
    assert received["reused"] is False
    matched = []
    for (rid,) in store.conn.execute(
            "SELECT row_id FROM board_rows WHERE row_kind='income' AND row_id LIKE 'bnk-%'"
            " ORDER BY row_id").fetchall():
        record = store.get_row(rid)
        if (record.get("amount_krw") == 500000 and str(record.get("occurred_on")) == "2026-04-02"
                and record.get("source_kind") == "은행"):
            matched.append(rid)
    assert matched, "bank fixture must yield one readable source row"
    return matched[0]


def test_direct_income_advertises_bank_link(env):
    store, _, _ = env
    row = _direct_row(store, "bank-actions-direct")
    detail = _detail(store, row["row_id"])
    assert detail["read_only"] is False
    link = _action(detail, "bank-link")
    assert link["method"] == "POST"
    assert link["href"] == f"/api/income/{row['row_id']}/link-bank"
    assert link["encoding"] == "json"
    assert link["csrf"] == "header"
    assert link["response"] == "json"
    assert {field["name"] for field in link["fields"]} == {
        "bank_batch_id", "bank_row_index", "expected_revision", "client_request_id"}
    assert all(action["id"] != "bank-correction" for action in detail["actions"])


def test_bank_income_advertises_correction_and_pins_fixed_amount(env):
    store, _, db = env
    row_id = _bank_row(store, db)
    detail = _detail(store, row_id)
    assert detail["read_only"] is False
    action = _action(detail, "bank-correction")
    assert action["method"] == "POST"
    assert action["href"] == f"/api/income/{row_id}/correct"
    assert action["encoding"] == "json"
    assert action["csrf"] == "header"
    assert action["response"] == "json"
    assert {field["name"] for field in action["fields"]} == {
        "corrected_amount_krw", "corrected_occurred_on", "reason",
        "expected_revision", "client_request_id"}
    assert all(action["id"] != "bank-link" for action in detail["actions"])
    edit_fields = {field["name"] for field in detail["edit_fields"]}
    assert "amount_krw" not in edit_fields
    assert "occurred_on" not in edit_fields


def test_direct_expense_does_not_advertise_bank_actions(env):
    store, _, _ = env
    created = store.create_manual_expense(
        fields={
            "display_tab_id": TRIP, "occurred_on": "2026-04-02", "pay_method": "현금",
            "item": "식음료", "description": "저녁", "amount_krw": 25000, "memo": "",
        },
        client_request_id="bank-actions-expense",
    )
    detail = _detail(store, created["row_id"])
    ids = {action["id"] for action in detail["actions"]}
    assert "bank-link" not in ids
    assert "bank-correction" not in ids


def test_google_income_does_not_advertise_bank_actions(env, monkeypatch):
    import webapp.plush_api as module

    store, _, _ = env
    row = {
        "row_id": "google-income|trip-demo-a|main|6", "row_kind": "income",
        "source_kind": "Google", "google_income": True, "amount_krw": 5000,
        "payer_name": "chez", "occurred_on": "2026-04-02",
        "display_tab_id": TRIP, "revision": 1,
    }
    monkeypatch.setattr(module, "_source_income", lambda *a, **k: {"rows": [row],
                                                                   "verified": False,
                                                                   "stale": False})
    detail = _detail(store, row["row_id"])
    ids = {action["id"] for action in detail["actions"]}
    assert "bank-link" not in ids
    assert "bank-correction" not in ids


def test_allocation_fragment_does_not_advertise_bank_actions(env):
    store, _, _ = env
    source = _direct_row(store, "bank-actions-frag-source")
    created = store.save_allocations(
        source_row_id=source["row_id"], expected_source_revision=1,
        allocations=[{"customer_name": "U1", "display_tab_id": TRIP,
                      "income_kind": "deposit", "amount_krw": 250000}],
        client_request_id="bank-actions-frag-alloc",
    )
    fragment_id = created["allocations"][0]
    detail = _detail(store, fragment_id)
    ids = {action["id"] for action in detail["actions"]}
    assert "bank-link" not in ids
    assert "bank-correction" not in ids


def test_remainder_fragment_is_not_a_board_row(env):
    store, _, _ = env
    source = _direct_row(store, "bank-actions-frag-remainder")
    created = store.save_allocations(
        source_row_id=source["row_id"], expected_source_revision=1,
        allocations=[{"customer_name": "U1", "display_tab_id": TRIP,
                      "income_kind": "deposit", "amount_krw": 250000}],
        client_request_id="bank-actions-frag-remainder-plan",
    )
    assert created["remainder"] == 250000
    remainder_id = f"rem-{source['row_id']}"
    status, body = call(f"/api/plush/row?id={remainder_id}", "syn-owner", store)
    assert status == 404
    assert body["code"] == "RESOURCE_NOT_FOUND"
    assert "actions" not in body
    store, _, _ = env
    row = _direct_row(store, "bank-actions-direct-edit")
    detail = _detail(store, row["row_id"])
    edit_fields = {field["name"] for field in detail["edit_fields"]}
    assert "amount_krw" in edit_fields
    assert "occurred_on" in edit_fields


def test_viewer_advertisement_is_refused(env, monkeypatch):
    store, access, _ = env
    access.create_account(user_id="syn-viewer", role=access_control.ROLE_VIEWER,
                          display_name="뷰어")
    monkeypatch.setattr(access, "visible_tabs", lambda user_id, now=None: {TRIP})
    row = _direct_row(store, "bank-actions-viewer")
    detail = _detail(store, row["row_id"], "syn-viewer")
    assert detail["read_only"] is True
    assert detail["actions"] == []


def test_closed_trip_has_no_write_actions(env):
    store, _, _ = env
    row = _direct_row(store, "bank-actions-closed")
    closed = store.save_trip_visual_close(tab_id=TRIP, expected_closed=False,
                                          closed=True, client_request_id="close-1")
    assert closed["visual_closed"] is True
    status, detail = call(f"/api/plush/row?id={row['row_id']}", "syn-owner", store)
    assert status == 200
    assert detail["read_only"] is True
    assert detail["actions"] == []


def test_advertised_conditions_match_store_refusals(env):
    store, _, _ = env
    direct = _direct_row(store, "bank-actions-agree-direct")
    bank = _bank_row(store, env[2])
    with pytest.raises(SaveError) as refused:
        store.correct_bank_income(row_id=direct["row_id"], corrected_amount_krw=1,
                                  reason="은행 정정", client_request_id="agree-1",
                                  expected_revision=1)
    assert refused.value.code == "INVALID_VALUE"
    with pytest.raises(SaveError) as refused:
        store.link_bank_source(row_id=bank, bank_batch_id="bnk-missing",
                               bank_row_index=0, expected_revision=1,
                               client_request_id="agree-2")
    assert refused.value.code == "INVALID_VALUE"


def test_actions_are_fresh_and_revision_pinned(env):
    store, _, _ = env
    direct = store.create_direct_income(
        fields={
            "display_tab_id": TRIP, "occurred_on": "2026-04-02", "amount_krw": 500000,
            "income_kind": "deposit", "customer_id": None, "customer_name": "김예시",
            "nickname": "", "memo": "",
        },
        client_request_id="bank-actions-fresh",
    )
    first = _detail(store, direct["row_id"])
    second = _detail(store, direct["row_id"])
    first_id = _action(first, "bank-link")["fields"][-1]["value"]
    second_id = _action(second, "bank-link")["fields"][-1]["value"]
    assert re.fullmatch(r"[0-9a-f]{32}", first_id)
    assert re.fullmatch(r"[0-9a-f]{32}", second_id)
    for detail in (first, second):
        action = _action(detail, "bank-link")
        revision_field = next(f for f in action["fields"] if f["name"] == "expected_revision")
        assert revision_field["value"] == detail["expected_revision"] == detail["row"]["revision"]
