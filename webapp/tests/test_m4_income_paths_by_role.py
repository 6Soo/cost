"""GGL-003 across every entry path and role, with actual values asserted.

The reviewer asked for four cases to be pinned:

  A. owner + verified Google      -> Google substitutes, never summed
  B. viewer + grant + verified    -> the same figure the owner sees
  C. viewer + no grant            -> COST only; Google never leaks a figure
  D. available but unverified     -> COST only, and the 차액 excludes Google

§11.2.1 계약 1 says the same snapshot, permission and tab show the same rows and
totals on either path, so B must match A. `plush_income.load` reports
`verified=False` in every refusal and in `NOT_CONNECTED`, so a refused block
never promotes a Google amount into the confirmed figure.

Synthetic store and synthetic Google snapshot only.
"""
from __future__ import annotations

import json

import pytest

from webapp import access_control, ledger_board, plush_api
from webapp.ledger_store import LedgerStore

OWNER = "syn-owner"
VIEWER = "syn-viewer"
COST_INCOME = 1000000
GOOGLE_INCOME = 1000


class Handler:
    command = "GET"

    def __init__(self, user):
        self.headers = {access_control.SyntheticSessionAdapter.HEADER: user} if user else {}
        self.responses = []

    def _send_json(self, value, code=200, **_kwargs):
        self.responses.append((code, value))


def _call(path, user, store):
    from types import SimpleNamespace

    parsed = SimpleNamespace(path=path.split("?", 1)[0],
                             query=path.split("?", 1)[1] if "?" in path else "")
    handler = Handler(user)
    assert plush_api.dispatch(handler, parsed, board=store) is True
    return handler.responses[-1]


@pytest.fixture()
def income_case(tmp_path, monkeypatch):
    """One trip with COST income, a viewer account and a synthetic Google block."""
    from webapp import google_ledger_page as page
    from webapp.tests.test_google_canonical_workflow import healthy_snapshot
    from webapp.tests.test_google_ledger_page import rows_doc

    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_SNAPSHOT", str(tmp_path / "snap.json"))
    monkeypatch.setenv("WEBLEDGER_GOOGLE_LEDGER_ROWS", str(tmp_path / "rows.json"))
    snapshot = healthy_snapshot()
    key = snapshot["trips"][0]["key"]
    monkeypatch.setattr(page.google_authority, "load_consistent",
                        lambda *a: (snapshot, rows_doc()["sources"]))
    monkeypatch.setattr(page, "snapshot_for_display", lambda data: data)
    monkeypatch.setattr(page, "load_choices", lambda *a: {"choices": {key: "main"}})

    store = LedgerStore(tmp_path / "case.sqlite", seed_demo=False)
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner(OWNER)
    access.create_account(user_id=VIEWER, role=access_control.ROLE_VIEWER)
    previous_store, previous_access = ledger_board._STORE, ledger_board._ACCESS
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    trip = store.create_trip(starts_on="2026-11-10", ends_on="2026-11-20",
                             destination="합성 수입 여행",
                             client_request_id="case-trip")
    tab = trip["tab_id"]
    store.create_direct_income(
        fields={"display_tab_id": tab, "occurred_on": "2026-11-11",
                "customer_name": "합성 고객", "income_kind": "deposit",
                "amount_krw": COST_INCOME, "source_kind": "수기"},
        client_request_id="case-income")
    monkeypatch.setattr(page, "load_mapping", lambda *a: {key: tab})

    def grant(user):
        person = "case-person"
        access.register_reservation_person(reservation_person_id=person,
                                           display_name="합성 담당자")
        application = access.create_application(
            user_id=user, requested_name="합성 담당자", client_request_id="case-app")
        access.approve_application(
            application_id=application["application_id"], owner_id=OWNER,
            expected_revision=application["revision"],
            reservation_person_id=person, client_request_id="case-approval")
        access.apply_assignment_snapshot(
            user_id=user,
            items=[{"tab_id": tab, "snapshot_revision": 1, "state": "active"}],
            source_version="case-v", complete=True)

    def set_verified(value, grants):
        snap = json.loads(json.dumps(snapshot))
        for trip_entry in snap.get("trips", []):
            if trip_entry.get("key") != key:
                continue
            for block in (trip_entry.get("copies") or {}).values():
                income_block = block.get("income") or {}
                income_block["verified"] = value
        monkeypatch.setattr(page.google_authority, "load_consistent",
                            lambda *a: (snap, rows_doc()["sources"]))
        monkeypatch.setattr(page, "load_grants",
                            lambda *a: {"grants": {u: [key] for u in grants}})

    try:
        yield {"store": store, "tab": tab, "key": key, "grant": grant,
               "set_verified": set_verified}
    finally:
        ledger_board.bind_access(previous_access)
        ledger_board.bind_store(previous_store)
        access_control.bind_sessions(access_control.UnboundSessionAdapter())
        store.close()


def _ledger(env, user):
    status, body = _call(f"/api/plush/ledger?tab={env['tab']}", user, env["store"])
    assert status == 200, body
    return body


def test_a_owner_sees_the_cost_figure_and_a_verified_google_block_substitutes(
        income_case):
    """A: 소유자 + 검증 Google — COST 수입이 있으면 Google은 더하지 않는다."""
    env = income_case
    env["set_verified"](True, [])
    body = _ledger(env, OWNER)
    assert body["trip"]["income"] == str(COST_INCOME), body["trip"]
    assert body["trip"]["profit"] == str(COST_INCOME), body["trip"]
    assert body["income_source"]["verified"] is True, body["income_source"]
    # the Google row is present in the list as separate evidence
    google_rows = [r for r in body["rows"] if r["id"].startswith("google-income|")]
    assert len(google_rows) == 1, body["rows"]


def test_b_a_granted_viewer_sees_the_same_summary_as_the_owner(income_case):
    """B: 열람자 + grant + 검증 — 소유자와 같은 수입·차액이어야 한다(계약 1)."""
    env = income_case
    env["grant"](VIEWER)
    env["set_verified"](True, [VIEWER])
    owner_body = _ledger(env, OWNER)
    viewer_body = _ledger(env, VIEWER)
    assert viewer_body["trip"]["income"] == owner_body["trip"]["income"], (
        viewer_body["trip"], owner_body["trip"])
    assert viewer_body["trip"]["profit"] == owner_body["trip"]["profit"], (
        viewer_body["trip"], owner_body["trip"])
    assert viewer_body["trip"]["income"] == str(COST_INCOME), viewer_body["trip"]


def test_c_a_viewer_without_a_grant_still_sees_the_cost_figure(income_case):
    """C: 열람자 + grant 없음 — Google 금액은 새지 않고 COST 수입은 그대로."""
    env = income_case
    env["grant"](VIEWER)
    env["set_verified"](True, [])
    body = _ledger(env, VIEWER)
    assert body["trip"]["income"] == str(COST_INCOME), body["trip"]
    assert body["income_source"]["available"] is False, body["income_source"]
    assert body["income_source"]["verified"] is False, body["income_source"]
    google_rows = [r for r in body["rows"] if r["id"].startswith("google-income|")]
    assert google_rows == [], body["rows"]


def test_d_an_unverified_block_never_enters_the_trip_figures(income_case):
    """D: available:true / verified:false — COST만, 차액에 Google 미포함."""
    env = income_case
    env["set_verified"](False, [])
    body = _ledger(env, OWNER)
    assert body["income_source"]["available"] is True, body["income_source"]
    assert body["income_source"]["verified"] is False, body["income_source"]
    assert body["trip"]["income"] == str(COST_INCOME), body["trip"]
    # the 차액 is COST income minus expense and does not carry the Google 1,000
    assert body["trip"]["profit"] == str(COST_INCOME), body["trip"]


def test_the_bootstrap_loop_reports_the_same_figures_as_the_ledger(income_case):
    """bootstrap's per-trip summaries must carry the same rule as the ledger."""
    env = income_case
    env["set_verified"](True, [])
    status, body = _call("/api/plush/bootstrap", OWNER, env["store"])
    assert status == 200, body
    trip = next((t for t in body["trips"] if t["id"] == env["tab"]), None)
    assert trip is not None, body["trips"]
    assert trip["income"] == str(COST_INCOME), trip
    assert trip["profit"] == str(COST_INCOME), trip
    assert trip["income_source"]["verified"] is True, trip["income_source"]
