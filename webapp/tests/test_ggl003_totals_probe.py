"""GGL-003 evidence probe: do kind/search totals ever sum COST with Google income?

SPEC §11.2.1 계약 2 defines the totals as the tab-wide set before search.
GGL-003 forbids summing internal COST income with Google income (Google income
is user-entered and COST only reads it); GGL-014 forbids mixing an unverified
source into confirmed revenue.

This probe seeds a tab holding BOTH a COST income row and a verified Google
block, then reads the actual figures each path returns, so the policy answer is
a number rather than an opinion.  Synthetic store only — no production access.
"""
from __future__ import annotations

import json
import re

import pytest

from webapp import ledger_design, ledger_query
from webapp.tests.test_ledger_parity_spec_11_2_1 import (  # noqa: F401 - shared fixtures
    bound_store, grant_viewer_tabs, legacy_kpi, legacy_owner, make_trip, react_ledger,
)
from webapp.tests.test_trip_google_income import income_context  # noqa: F401


def _seed_cost_income_and_expense(store, tab):
    """Seed a COST income row and an expense row directly in the board table."""
    import json

    income_id, expense_id = f"ggl-income-{tab}", f"ggl-expense-{tab}"
    for row_id, kind, amount, payload in (
        (income_id, "income", 1000000,
         {"amount_krw": 1000000, "occurred_on": "2026-11-11", "income_kind": "잔금",
          "customer_name": "합성 고객", "source_kind": "수기", "revision": 1}),
        (expense_id, "expense", 250000,
         {"amount_krw": 250000, "occurred_on": "2026-11-12", "item": "식비",
          "pay_method": "현금", "description": "합성 지출", "source_kind": "수기",
          "revision": 1}),
    ):
        store.conn.execute(
            "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
            " VALUES (?,?,?,?,?)",
            (row_id, kind, tab, 1, json.dumps(payload, ensure_ascii=False)))
    store.conn.commit()
    return income_id, expense_id


def _connect_google(store, tab, monkeypatch):
    """Map the verified synthetic Google block to this tab (1,000원)."""
    from webapp import google_ledger_page as page

    monkeypatch.setattr(page, "load_mapping", lambda *a: {"syn-google-key": tab})
    monkeypatch.setattr(page, "owner_rows", lambda *a: {
        "income": [dict(row=6, date="2026-11-11", name="합성고객",
                        deposit=1000, balance=0, extra=0, amount=1000)],
        "expense": []})
    from webapp.tests.test_trip_google_income import board
    monkeypatch.setattr(board, "current_role", lambda: "owner")


def test_kind_and_search_totals_do_not_sum_cost_with_google(bound_store, income_context, monkeypatch):
    store, access = bound_store
    snapshot, key = income_context
    tab = make_trip(store)
    _seed_cost_income_and_expense(store, tab)

    monkeypatch.setattr("webapp.google_ledger_page.load_mapping", lambda *a: {key: tab})
    monkeypatch.setattr("webapp.google_ledger_page.owner_rows", lambda *a: {
        "income": [dict(row=6, date="2026-11-11", name="합성고객",
                        deposit=1000, balance=0, extra=0, amount=1000)],
        "expense": []})
    snapshot["trips"][0]["copies"]["main"]["income"].update(
        total=1000, row_sum=1000, sheet_total=1000, verified=True)

    cost_income = store.tab_totals(tab)["income"]
    assert cost_income == 1000000, cost_income

    # --- legacy HTML board: the rendered KPI figures --------------------------
    kpi = legacy_kpi(tab)

    # --- shared query: what the React path uses ------------------------------
    linked = ledger_query.linked_bank_ids(store)
    rows = ledger_query.unified_rows(store, access, _owner_session(), True, tab)[0]
    totals = ledger_query.totals(rows, linked=linked)
    confirmed, known = ledger_query.confirmed_income(
        rows, linked=linked,
        google_verified=bool(income_context[0]["trips"][0]["copies"]["main"]["income"].get("verified")))

    status, body = react_ledger(store, tab, kind="income")
    assert status == 200, body

    report = {
        "COST tab income": cost_income,
        "Google block (verified)": 1000,
        "legacy KPI 수입": kpi["수입"],
        "legacy KPI 차액": kpi["차액"],
        "React trip.income": body["trip"]["income"],
        "kind=income filtered_total": body["filtered_total"],
        "kind=income total": body["total"],
        "kind=income source_totals": body["source_totals"]["filtered"],
        "shared totals.income": totals["income"],
        "confirms COST+Google": totals["income"] == cost_income + 1000,
    }
    print("GGL-003 probe numbers:", report)

    # --- the two figures that must be reported as evidence -------------------
    # kind/search total (React + shared helper) vs the legacy board's own kind
    # total.  The legacy summary counts COST rows only; the shared signed sum
    # also adds the Google income rows that the unified row set merged in.
    legacy_in, _legacy_ex, _wi, _we = ledger_design._selected_rows(tab, "", "in")
    legacy_kind_total = sum(ledger_design.board._shown_amount(row) for row in legacy_in)
    print("GGL-003 kind totals:", {
        "legacy kind=in rows": len(legacy_in),
        "legacy kind=in total": legacy_kind_total,
        "react kind=income filtered_total": body["filtered_total"],
        "delta": int(body["filtered_total"]) - legacy_kind_total,
    })

    assert kpi["수입"] == cost_income, f"레거시 KPI 수입이 COST와 다름: {kpi}"
    assert int(body["trip"]["income"]) == cost_income, (
        f"React 요약 수입이 COST와 다름: {body['trip']['income']}")
    assert known and confirmed == cost_income, f"확정 수입이 COST+Google 합산됨: {confirmed}"
    # GGL-003: the kind/search 조회 합계 must match the legacy board's kind total,
    # not a COST+Google sum.
    assert int(body["filtered_total"]) == legacy_kind_total, (
        f"kind 조회 합계가 COST+Google을 합산함: React {body['filtered_total']} != 레거시 {legacy_kind_total}")
    # GGL-003: the Google block is reported as its own source, never merged.
    source = body["source_totals"]["filtered"]
    assert source["google_income"] == "1000", source
    assert source["income"] == str(cost_income), source
    assert source["total"] == str(cost_income), source  # 지출 0, COST 수입 1,000,000
    assert int(body["filtered_total"]) != int(source["income"]) + int(source["google_income"]), (
        f"조회 합계가 두 출처를 합산함: {body['filtered_total']}")
    # Existing money contract: every figure is a string, so a 2^53-sized amount
    # never passes through a JavaScript number.
    for key, value in source.items():
        assert isinstance(value, str), (key, type(value))

    # --- expenditure side: COST expense stays alone and is not merged ---------
    status, exp = react_ledger(store, tab, kind="expense")
    assert status == 200, exp
    assert exp["filtered_total"] == "250000", exp["filtered_total"]
    assert exp["source_totals"]["filtered"]["expense"] == "250000"
    assert exp["source_totals"]["filtered"]["google_income"] == "0"


def test_unverified_google_rows_never_become_a_confirmed_amount(bound_store, income_context, monkeypatch):
    """GGL-014: a row's mere presence is not verification.

    Google income rows exist whenever the source block loads, but an unverified
    block (or a row whose amount is missing) must not contribute an amount or
    turn "unknown" into a confirmed zero.
    """
    store, access = bound_store
    snapshot, key = income_context
    tab = make_trip(store)
    _seed_cost_income_and_expense(store, tab)

    monkeypatch.setattr("webapp.google_ledger_page.load_mapping", lambda *a: {key: tab})
    monkeypatch.setattr("webapp.google_ledger_page.owner_rows", lambda *a: {
        "income": [dict(row=6, date="2026-11-11", name="합성고객",
                        deposit=1000, balance=0, extra=0, amount=1000)],
        "expense": []})
    # Unverified block: rows are present, the totals are not trusted.
    snapshot["trips"][0]["copies"]["main"]["income"].update(
        total=1000, row_sum=1000, sheet_total=1000, verified=False)

    status, body = react_ledger(store, tab, kind="income")
    assert status == 200, body
    source = body["source_totals"]["filtered"]
    assert body["income_source"]["verified"] is False, body["income_source"]
    # COST is still the confirmed figure, and the Google line stays separate.
    assert source["income"] == "1000000", source
    assert body["filtered_total"] == "1000000", body["filtered_total"]


def test_missing_amount_google_row_is_not_counted_as_zero():
    """GGL-014 / §11.2.1 계약 4: an unreadable Google amount is unknown, not 0원.

    Asserted on the shared helper, where the amount rule lives, because the
    loader drops a row whose amount cannot be read before the totals are asked
    for it — the helper must hold the same rule if such a row ever reaches it.
    """
    unknown = {"row_id": "google-income|trip|x|6", "row_kind": "income",
               "google_income": True, "amount_missing": True, "amount_krw": None,
               "display_tab_id": "trip-synthetic"}
    known = {"row_id": "google-income|trip|x|7", "row_kind": "income",
             "google_income": True, "amount_missing": False, "amount_krw": 1000,
             "display_tab_id": "trip-synthetic"}

    # A set whose only Google row is unreadable reports no amount at all.
    only_unknown = ledger_query.display_totals([unknown])
    assert only_unknown["google_income"] is None, only_unknown
    assert only_unknown["google_income_count"] == "1", only_unknown
    assert only_unknown["google_unknown_count"] == "1", only_unknown
    assert only_unknown["google_incomplete"] == "False", only_unknown

    # No Google rows at all is a real, confirmed zero for that source.
    none_at_all = ledger_query.display_totals([dict(known, row_kind="expense", amount_krw=500)])
    assert none_at_all["google_income"] == "0", none_at_all
    assert none_at_all["google_income_count"] == "0", none_at_all

    # A partial sum says so rather than passing as complete.
    mixed = ledger_query.display_totals([unknown, known])
    assert mixed["google_income"] == "1000", mixed
    assert mixed["google_incomplete"] == "True", mixed
    assert mixed["google_unknown_count"] == "1", mixed
    # The Google block never leaks into the COST figure or the total.
    assert mixed["income"] == "0" and mixed["total"] == "0", mixed

    # A fully readable Google set is complete.
    all_known = ledger_query.display_totals([known])
    assert all_known["google_income"] == "1000", all_known
    assert all_known["google_incomplete"] == "False", all_known


def test_unverified_google_without_cost_income_stays_unknown(bound_store, income_context, monkeypatch):
    """GGL-003·GGL-014: a tab with only an unverified Google block has no confirmed income."""
    store, access = bound_store
    snapshot, key = income_context
    tab = make_trip(store)
    store.conn.execute(
        "INSERT INTO board_rows(row_id, row_kind, display_tab_id, revision, payload_json)"
        " VALUES (?,?,?,?,?)",
        (f"ggl-only-expense-{tab}", "expense", tab, 1,
         json.dumps({"amount_krw": 250000, "occurred_on": "2026-11-12", "item": "식비",
                     "pay_method": "현금", "description": "합성 지출", "source_kind": "수기",
                     "revision": 1}, ensure_ascii=False)))
    store.conn.commit()

    monkeypatch.setattr("webapp.google_ledger_page.load_mapping", lambda *a: {key: tab})
    monkeypatch.setattr("webapp.google_ledger_page.owner_rows", lambda *a: {
        "income": [dict(row=6, date="2026-11-11", name="합성고객",
                        deposit=1000, balance=0, extra=0, amount=1000)],
        "expense": []})
    snapshot["trips"][0]["copies"]["main"]["income"].update(
        total=1000, row_sum=1000, sheet_total=1000, verified=False)

    status, body = react_ledger(store, tab, kind="income")
    assert status == 200, body
    # No COST income and the Google block is unverified: the summary is unknown,
    # never a confirmed 0 or 1,000.
    assert body["trip"]["income"] == "미확인", body["trip"]
    assert body["trip"]["profit"] == "미확인", body["trip"]
    assert body["filtered_total"] == "0", body["filtered_total"]
    source = body["source_totals"]["filtered"]
    assert source["income"] == "0", source
    assert source["google_verified"] == "False", source


def _owner_session():
    """Owner scope without the HTTP session layer (the query helpers take none)."""
    return None
