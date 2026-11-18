"""The legacy KPI and the React trip summary must agree on 수입 (GGL-003).

Both paths read the same store. The legacy `_trip_kpi_html` shows COST income
when the tab has any, and a *verified* Google block otherwise; the React
`trip_summary` now follows the same rule instead of adding the two. This checks
them side by side on the same synthetic rows so a future edit to either one is
caught here.

Synthetic store only: no production access, no Google write.
"""
from __future__ import annotations

import re

import pytest

from webapp import ledger_board, ledger_design


def _kpi_amounts(tab_id: str) -> dict:
    """The legacy KPI's 수입·지출·차액 as integers, or None for unknown."""
    html = ledger_design._trip_kpi_html(tab_id)
    out = {}
    for label in ("수입", "지출", "차액"):
        match = re.search(rf"<dt>{label}</dt><dd>(.*?)</dd>", html, re.S)
        assert match, f"KPI에서 {label} 값을 찾지 못함: {html[:300]}"
        text = match.group(1).strip()
        out[label] = None if text == "—" else int(
            text.replace("원", "").replace("−", "-").replace(",", "").strip())
    return out


@pytest.fixture()
def parity_board(tmp_path, monkeypatch):
    from webapp import access_control
    from webapp.ledger_store import LedgerStore

    monkeypatch.setenv("WEBLEDGER_DB", str(tmp_path / "parity.sqlite"))
    store = LedgerStore(tmp_path / "parity.sqlite")
    access = access_control.attach_to_ledger_store(store)
    access.ensure_owner("syn-owner")
    previous_store, previous_access = ledger_board._STORE, ledger_board._ACCESS
    ledger_board.bind_store(store)
    ledger_board.bind_access(access)
    access_control.bind_synthetic_sessions(True)
    trip = store.create_trip(starts_on="2026-11-10", ends_on="2026-11-20",
                             destination="합성 수입 여행",
                             client_request_id="parity-trip")
    tab = trip["tab_id"]
    yield store, tab
    ledger_board.bind_access(previous_access)
    ledger_board.bind_store(previous_store)
    access_control.bind_sessions(access_control.UnboundSessionAdapter())
    store.close()


def test_cost_income_plus_a_google_block_is_not_summed_on_either_path(
        parity_board, monkeypatch):
    """GGL-003: both paths show the COST figure; Google is not added to it."""
    from webapp import google_ledger_page as page, plush_projection

    store, tab = parity_board
    store.create_direct_income(
        fields={"display_tab_id": tab, "occurred_on": "2026-11-11",
                "customer_name": "합성 고객", "income_kind": "deposit",
                "amount_krw": 1000000, "source_kind": "수기"},
        client_request_id="parity-income")
    # a verified Google block on the same tab
    monkeypatch.setattr(page, "get_trip_income_summary",
                        lambda _tab: {"show_rows": True, "amount": 1000, "count": 1,
                                      "verified": True})
    ledger = _kpi_amounts(tab)
    assert ledger["수입"] == 1000000, ledger

    rows = [
        {"row_id": "cost-1", "row_kind": "income", "display_amount_krw": 1000000},
        {"row_id": "google-income|t|main|9", "row_kind": "income",
         "google_income": True, "display_amount_krw": 1000},
    ]
    summary = plush_projection.trip_summary(dict(tab_id=tab, google_verified=True), rows)
    assert summary["income"] == str(ledger["수입"]), (summary, ledger)


def test_no_cost_income_uses_a_verified_google_block_on_both_paths(
        parity_board, monkeypatch):
    """A verified block substitutes when the tab has no COST income — on both."""
    from webapp import google_ledger_page as page, plush_projection

    store, tab = parity_board
    monkeypatch.setattr(page, "get_trip_income_summary",
                        lambda _tab: {"show_rows": True, "amount": 1000, "count": 1,
                                      "verified": True})
    ledger = _kpi_amounts(tab)
    assert ledger["수입"] == 1000, ledger

    summary = plush_projection.trip_summary(
        dict(tab_id=tab, google_verified=True),
        [{"row_id": "google-income|t|main|9", "row_kind": "income",
          "google_income": True, "display_amount_krw": 1000}])
    assert summary["income"] == str(ledger["수입"]), (summary, ledger)


def test_an_unverified_google_block_leaves_both_paths_unknown(
        parity_board, monkeypatch):
    """GGL-014: without COST income and without a verified block, both say unknown."""
    from webapp import google_ledger_page as page, plush_projection

    store, tab = parity_board
    monkeypatch.setattr(page, "get_trip_income_summary",
                        lambda _tab: {"show_rows": False, "amount": 1000, "count": 1,
                                      "verified": False})
    ledger = _kpi_amounts(tab)
    assert ledger["수입"] is None, ledger

    summary = plush_projection.trip_summary(
        dict(tab_id=tab, google_verified=False),
        [{"row_id": "google-income|t|main|9", "row_kind": "income",
          "google_income": True, "display_amount_krw": 1000}])
    assert summary["income"] == "미확인", summary
